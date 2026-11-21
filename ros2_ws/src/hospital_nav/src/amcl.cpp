#include "hospital_nav/amcl.hpp"
#include <tf2/utils.h>
#include <cmath>
#include <numeric>
#include <algorithm>

namespace hospital_nav {

AMCL::AMCL(const rclcpp::NodeOptions & options)
: Node("amcl", options)
{
    declare_parameter("num_particles",         500);
    declare_parameter("sigma_hit",             0.2);
    declare_parameter("z_hit",                 0.95);
    declare_parameter("z_rand",                0.05);
    declare_parameter("laser_max_range",       10.0);
    declare_parameter("laser_skip",            10);
    declare_parameter("alpha1",                0.10);
    declare_parameter("alpha2",                0.05);
    declare_parameter("alpha3",                0.10);
    declare_parameter("alpha4",                0.05);
    declare_parameter("random_particle_ratio", 0.02);

    num_particles_         = get_parameter("num_particles").as_int();
    sigma_hit_             = get_parameter("sigma_hit").as_double();
    z_hit_                 = get_parameter("z_hit").as_double();
    z_rand_                = get_parameter("z_rand").as_double();
    laser_max_range_       = get_parameter("laser_max_range").as_double();
    laser_skip_            = get_parameter("laser_skip").as_int();
    alpha1_                = get_parameter("alpha1").as_double();
    alpha2_                = get_parameter("alpha2").as_double();
    alpha3_                = get_parameter("alpha3").as_double();
    alpha4_                = get_parameter("alpha4").as_double();
    random_particle_ratio_ = get_parameter("random_particle_ratio").as_double();

    auto map_qos = rclcpp::QoS(rclcpp::KeepLast(1)).transient_local().reliable();

    map_sub_ = create_subscription<nav_msgs::msg::OccupancyGrid>(
        "/map", map_qos, std::bind(&AMCL::mapCallback, this, std::placeholders::_1));
    odom_sub_ = create_subscription<nav_msgs::msg::Odometry>(
        "/odom", 10, std::bind(&AMCL::odomCallback, this, std::placeholders::_1));
    scan_sub_ = create_subscription<sensor_msgs::msg::LaserScan>(
        "/scan_multi", rclcpp::SensorDataQoS(),
        std::bind(&AMCL::scanCallback, this, std::placeholders::_1));
    init_sub_ = create_subscription<geometry_msgs::msg::PoseWithCovarianceStamped>(
        "/initialpose", 10,
        std::bind(&AMCL::initialPoseCallback, this, std::placeholders::_1));

    pose_pub_             = create_publisher<geometry_msgs::msg::PoseWithCovarianceStamped>("/amcl_pose", 10);
    particle_pub_         = create_publisher<geometry_msgs::msg::PoseArray>("/particle_cloud_pose", 10);
    particle_marker_pub_  = create_publisher<visualization_msgs::msg::MarkerArray>("/particle_cloud_markers", 10);
    particle_heatmap_pub_ = create_publisher<nav_msgs::msg::OccupancyGrid>("/particle_heatmap", 10);

    tf_broadcaster_ = std::make_shared<tf2_ros::TransformBroadcaster>(this);
    tf_buffer_      = std::make_shared<tf2_ros::Buffer>(get_clock());
    tf_listener_    = std::make_shared<tf2_ros::TransformListener>(*tf_buffer_);

    publish_timer_ = create_wall_timer(
        std::chrono::milliseconds(500),
        [this]() {
            if (initialized_) {
                publishResult();
            } else if (odom_initialized_) {
                geometry_msgs::msg::TransformStamped tf_msg;
                tf_msg.header.stamp    = get_clock()->now();
                tf_msg.header.frame_id = "map";
                tf_msg.child_frame_id  = "odom";
                tf_msg.transform.rotation.w = 1.0;
                tf_broadcaster_->sendTransform(tf_msg);
            }
        });

    RCLCPP_INFO(get_logger(), "AMCL started. Waiting for /initialpose ...");
}

void AMCL::mapCallback(const nav_msgs::msg::OccupancyGrid::SharedPtr msg)
{
    map_ = msg;
    buildLikelihoodField();
    buildFreeCellList();
    map_received_ = true;
    RCLCPP_INFO(get_logger(), "Map received [%d x %d] res=%.3f, free_cells=%zu",
        msg->info.width, msg->info.height, msg->info.resolution, free_cells_.size());

    if (pending_init_) {
        initParticles(pending_x_, pending_y_, pending_theta_, 0.5);
        pending_init_ = false;
    }
}

void AMCL::buildLikelihoodField()
{
    int W = map_->info.width;
    int H = map_->info.height;
    likelihood_field_.assign(W * H, 0.0);

    double sigma2 = sigma_hit_ * sigma_hit_;
    int radius    = static_cast<int>(3.0 * sigma_hit_ / map_->info.resolution);

    for (int y = 0; y < H; y++) {
        for (int x = 0; x < W; x++) {
            if (map_->data[y * W + x] != 100) continue;
            for (int dy = -radius; dy <= radius; dy++) {
                for (int dx = -radius; dx <= radius; dx++) {
                    int nx = x + dx, ny = y + dy;
                    if (nx < 0 || nx >= W || ny < 0 || ny >= H) continue;
                    double dist2 = (dx*dx + dy*dy) *
                                   map_->info.resolution * map_->info.resolution;
                    double val = std::exp(-dist2 / (2.0 * sigma2));
                    auto & cell = likelihood_field_[ny * W + nx];
                    if (val > cell) cell = val;
                }
            }
        }
    }
    RCLCPP_INFO(get_logger(), "Likelihood field built.");
}

double AMCL::likelihood(double wx, double wy)
{
    int    W   = map_->info.width;
    int    H   = map_->info.height;
    double res = map_->info.resolution;
    double ox  = map_->info.origin.position.x;
    double oy  = map_->info.origin.position.y;

    int mx = static_cast<int>((wx - ox) / res);
    int my = static_cast<int>((wy - oy) / res);

    if (mx < 0 || mx >= W || my < 0 || my >= H) return 0.0;
    return likelihood_field_[my * W + mx];
}

void AMCL::buildFreeCellList()
{
    free_cells_.clear();
    int    W   = map_->info.width;
    int    H   = map_->info.height;
    double res = map_->info.resolution;
    double ox  = map_->info.origin.position.x;
    double oy  = map_->info.origin.position.y;

    for (int y = 0; y < H; y++)
        for (int x = 0; x < W; x++)
            if (map_->data[y * W + x] == 0)
                free_cells_.push_back({ox + (x + 0.5) * res,
                                       oy + (y + 0.5) * res});
}

void AMCL::injectRandomParticles(int count)
{
    if (free_cells_.empty()) return;
    std::uniform_int_distribution<int>     cell_dist(0, (int)free_cells_.size() - 1);
    std::uniform_real_distribution<double> theta_dist(-M_PI, M_PI);

    for (int i = 0; i < count && i < (int)particles_.size(); ++i) {
        auto min_it = std::min_element(particles_.begin(), particles_.end(),
            [](const Particle& a, const Particle& b) { return a.weight < b.weight; });
        const auto& cell = free_cells_[cell_dist(rng_)];
        min_it->x      = cell.wx;
        min_it->y      = cell.wy;
        min_it->theta  = theta_dist(rng_);
        min_it->weight = 1.0 / num_particles_;
    }
}

void AMCL::initialPoseCallback(
    const geometry_msgs::msg::PoseWithCovarianceStamped::SharedPtr msg)
{
    double x     = msg->pose.pose.position.x;
    double y     = msg->pose.pose.position.y;
    double theta = tf2::getYaw(msg->pose.pose.orientation);

    RCLCPP_INFO(get_logger(), "initialpose received: (%.2f, %.2f, %.2f)", x, y, theta);
    initial_pose_received_ = true;

    if (!map_received_) {
        pending_x_ = x; pending_y_ = y; pending_theta_ = theta;
        pending_init_ = true;
        RCLCPP_WARN(get_logger(), "Map not ready. Init pending.");
        return;
    }
    initParticles(x, y, theta, 0.5);
}

void AMCL::initParticles(double x, double y, double theta, double sigma)
{
    std::normal_distribution<double> dist_xy(0.0, sigma);
    std::normal_distribution<double> dist_th(0.0, sigma * 0.3);

    particles_.resize(num_particles_);
    for (auto & p : particles_) {
        p.x      = x + dist_xy(rng_);
        p.y      = y + dist_xy(rng_);
        p.theta  = theta + dist_th(rng_);
        p.weight = 1.0 / num_particles_;
    }
    initialized_ = true;
    publishResult();

    RCLCPP_INFO(get_logger(), "Particles initialized: %d at (%.2f, %.2f, %.2f)",
        num_particles_, x, y, theta);
}

void AMCL::odomCallback(const nav_msgs::msg::Odometry::SharedPtr msg)
{
    double x     = msg->pose.pose.position.x;
    double y     = msg->pose.pose.position.y;
    double theta = tf2::getYaw(msg->pose.pose.orientation);

    if (!odom_initialized_) {
        odom_x_ = x; odom_y_ = y; odom_theta_ = theta;
        odom_initialized_ = true;
        return;
    }

    double dx     = x - odom_x_;
    double dy     = y - odom_y_;
    double dtheta = theta - odom_theta_;

    while (dtheta >  M_PI) dtheta -= 2*M_PI;
    while (dtheta < -M_PI) dtheta += 2*M_PI;

    if (std::hypot(dx, dy) < 0.003 && std::abs(dtheta) < 0.005) return;

    {
        std::lock_guard<std::mutex> lock(odom_mutex_);
        odom_x_ = x; odom_y_ = y; odom_theta_ = theta;
    }

    if (initialized_) motionUpdate(dx, dy, dtheta);
}

void AMCL::motionUpdate(double dx, double dy, double dtheta)
{
    double trans = std::hypot(dx, dy);
    double rot1  = std::atan2(dy, dx);

    if (trans > 0.001) {
        const double prev_heading = odom_theta_ - dtheta;
        const double heading_diff = std::atan2(
            std::sin(rot1 - prev_heading),
            std::cos(rot1 - prev_heading));
        if (std::abs(heading_diff) > M_PI / 2.0) {
            trans = -trans;
            rot1  = std::atan2(-dy, -dx);
        }
    }

    double rot2 = dtheta - rot1;
    if (std::abs(trans) < 0.01) { rot1 = 0.0; rot2 = dtheta; }

    std::normal_distribution<double> noise(0.0, 1.0);

    for (auto & p : particles_) {
        double nr1 = rot1  - (alpha1_*std::abs(rot1)  + alpha2_*std::abs(trans)) * noise(rng_);
        double nt  = trans - (alpha3_*std::abs(trans) + alpha4_*(std::abs(rot1)+std::abs(rot2))) * noise(rng_);
        double nr2 = rot2  - (alpha1_*std::abs(rot2)  + alpha2_*std::abs(trans)) * noise(rng_);

        p.x     += nt * std::cos(p.theta + nr1);
        p.y     += nt * std::sin(p.theta + nr1);
        p.theta += nr1 + nr2;

        while (p.theta >  M_PI) p.theta -= 2*M_PI;
        while (p.theta < -M_PI) p.theta += 2*M_PI;
    }
}

void AMCL::scanCallback(const sensor_msgs::msg::LaserScan::SharedPtr scan)
{
    if (!map_received_ || !initialized_) return;
    sensorUpdate(scan);
    resample();
    publishResult();
}

void AMCL::sensorUpdate(const sensor_msgs::msg::LaserScan::SharedPtr scan)
{
    double angle_min = scan->angle_min;
    double angle_inc = scan->angle_increment;
    int    n_rays    = static_cast<int>(scan->ranges.size());

    for (auto & p : particles_) {
        double log_w = 0.0;
        for (int i = 0; i < n_rays; i += laser_skip_) {
            float r = scan->ranges[i];
            if (r < scan->range_min || r > static_cast<float>(laser_max_range_)) continue;

            // lidar_lMer가 base_footprint 기준 180도 회전 → M_PI 추가
            double angle = angle_min + i * angle_inc + p.theta + M_PI;
            double hit_x = p.x + r * std::cos(angle);
            double hit_y = p.y + r * std::sin(angle);

            double lh = z_hit_ * likelihood(hit_x, hit_y) + z_rand_ / laser_max_range_;
            log_w += (lh > 1e-9) ? std::log(lh) : std::log(1e-9);
        }
        p.weight = std::exp(log_w);
    }

    double total = 0.0;
    for (auto & p : particles_) total += p.weight;
    if (total < 1e-15)
        for (auto & p : particles_) p.weight = 1.0 / num_particles_;
    else
        for (auto & p : particles_) p.weight /= total;
}

void AMCL::resample()
{
    double sum_sq = 0.0;
    for (auto & p : particles_) sum_sq += p.weight * p.weight;
    double n_eff = (sum_sq > 0) ? 1.0 / sum_sq : 0.0;

    if (n_eff > num_particles_ / 2.0) return;

    std::vector<double> cum(num_particles_);
    cum[0] = particles_[0].weight;
    for (int i = 1; i < num_particles_; i++)
        cum[i] = cum[i-1] + particles_[i].weight;

    std::uniform_real_distribution<double> dist(0.0, 1.0 / num_particles_);
    double r = dist(rng_);

    std::vector<Particle> new_particles(num_particles_);
    int j = 0;
    for (int i = 0; i < num_particles_; i++) {
        double u = r + i * (1.0 / num_particles_);
        while (j < num_particles_ - 1 && cum[j] < u) j++;
        new_particles[i]        = particles_[j];
        new_particles[i].weight = 1.0 / num_particles_;
    }
    particles_ = std::move(new_particles);

    int inject = static_cast<int>(std::ceil(random_particle_ratio_ * num_particles_));
    if (inject > 0) injectRandomParticles(inject);
}

void AMCL::publishResult()
{
    if (particles_.empty()) return;

    double mean_x = 0, mean_y = 0, mean_cos = 0, mean_sin = 0;
    for (auto & p : particles_) {
        mean_x   += p.weight * p.x;
        mean_y   += p.weight * p.y;
        mean_cos += p.weight * std::cos(p.theta);
        mean_sin += p.weight * std::sin(p.theta);
    }
    double mean_theta = std::atan2(mean_sin, mean_cos);

    auto stamp = get_clock()->now();

    geometry_msgs::msg::PoseWithCovarianceStamped pose_msg;
    pose_msg.header.stamp    = stamp;
    pose_msg.header.frame_id = "map";
    pose_msg.pose.pose.position.x = mean_x;
    pose_msg.pose.pose.position.y = mean_y;
    tf2::Quaternion q; q.setRPY(0, 0, mean_theta);
    pose_msg.pose.pose.orientation.x = q.x();
    pose_msg.pose.pose.orientation.y = q.y();
    pose_msg.pose.pose.orientation.z = q.z();
    pose_msg.pose.pose.orientation.w = q.w();
    pose_pub_->publish(pose_msg);

    tf2::Transform map_to_base;
    map_to_base.setOrigin({mean_x, mean_y, 0.0});
    tf2::Quaternion mq; mq.setRPY(0, 0, mean_theta);
    map_to_base.setRotation(mq);

    double snap_x, snap_y, snap_theta;
    {
        std::lock_guard<std::mutex> lock(odom_mutex_);
        snap_x = odom_x_; snap_y = odom_y_; snap_theta = odom_theta_;
    }

    tf2::Transform odom_to_base;
    odom_to_base.setOrigin({snap_x, snap_y, 0.0});
    tf2::Quaternion oq; oq.setRPY(0, 0, snap_theta);
    odom_to_base.setRotation(oq);

    tf2::Transform map_to_odom = map_to_base * odom_to_base.inverse();

    geometry_msgs::msg::TransformStamped tf_msg;
    tf_msg.header.stamp    = stamp;
    tf_msg.header.frame_id = "map";
    tf_msg.child_frame_id  = "odom";
    tf_msg.transform.translation.x = map_to_odom.getOrigin().x();
    tf_msg.transform.translation.y = map_to_odom.getOrigin().y();
    tf_msg.transform.translation.z = 0.0;
    tf_msg.transform.rotation.x = map_to_odom.getRotation().x();
    tf_msg.transform.rotation.y = map_to_odom.getRotation().y();
    tf_msg.transform.rotation.z = map_to_odom.getRotation().z();
    tf_msg.transform.rotation.w = map_to_odom.getRotation().w();
    tf_broadcaster_->sendTransform(tf_msg);

    if (!initial_pose_received_) return;

    geometry_msgs::msg::PoseArray pa;
    pa.header.stamp    = stamp;
    pa.header.frame_id = "map";
    pa.poses.reserve(particles_.size());
    for (auto & p : particles_) {
        geometry_msgs::msg::Pose pose;
        pose.position.x = p.x;
        pose.position.y = p.y;
        tf2::Quaternion pq; pq.setRPY(0, 0, p.theta);
        pose.orientation.x = pq.x();
        pose.orientation.y = pq.y();
        pose.orientation.z = pq.z();
        pose.orientation.w = pq.w();
        pa.poses.push_back(pose);
    }
    particle_pub_->publish(pa);

    visualization_msgs::msg::MarkerArray ma;
    visualization_msgs::msg::Marker del;
    del.header.stamp = stamp; del.header.frame_id = "map";
    del.action = visualization_msgs::msg::Marker::DELETEALL;
    del.ns = "particles";
    ma.markers.push_back(del);

    double max_w = 1e-300;
    for (auto & p : particles_) if (p.weight > max_w) max_w = p.weight;

    for (size_t i = 0; i < particles_.size(); ++i) {
        auto & p = particles_[i];
        visualization_msgs::msg::Marker m;
        m.header.stamp = stamp; m.header.frame_id = "map";
        m.ns = "particles"; m.id = (int)i;
        m.type = visualization_msgs::msg::Marker::ARROW;
        m.action = visualization_msgs::msg::Marker::ADD;
        m.pose.position.x = p.x; m.pose.position.y = p.y; m.pose.position.z = 0.0;
        tf2::Quaternion aq; aq.setRPY(0, 0, p.theta);
        m.pose.orientation.x = aq.x(); m.pose.orientation.y = aq.y();
        m.pose.orientation.z = aq.z(); m.pose.orientation.w = aq.w();
        m.scale.x = 0.15; m.scale.y = 0.03; m.scale.z = 0.03;
        double ratio = p.weight / max_w;
        m.color.r = (float)ratio;
        m.color.g = (float)(0.5 + 0.5*ratio);
        m.color.b = (float)(1.0 - ratio);
        m.color.a = (float)(0.5 + 0.5*ratio);
        m.lifetime = rclcpp::Duration(0, 500000000);
        ma.markers.push_back(m);
    }
    particle_marker_pub_->publish(ma);

    if (map_received_) publishParticleHeatmap(stamp);
}

void AMCL::publishParticleHeatmap(const rclcpp::Time & stamp)
{
    int W = map_->info.width, H = map_->info.height;
    double res = map_->info.resolution;
    double ox = map_->info.origin.position.x, oy = map_->info.origin.position.y;

    std::vector<double> density(W * H, 0.0);
    for (auto & p : particles_) {
        int mx = (int)((p.x-ox)/res), my = (int)((p.y-oy)/res);
        if (mx<0||mx>=W||my<0||my>=H) continue;
        for (int dy=-3; dy<=3; dy++) for (int dx=-3; dx<=3; dx++) {
            int nx=mx+dx, ny=my+dy;
            if (nx<0||nx>=W||ny<0||ny>=H) continue;
            double d2=(dx*dx+dy*dy)*res*res;
            density[ny*W+nx] += p.weight * std::exp(-d2/(2.0*0.1*0.1));
        }
    }
    double max_d = *std::max_element(density.begin(), density.end());
    if (max_d < 1e-15) return;

    nav_msgs::msg::OccupancyGrid grid;
    grid.header.stamp = stamp; grid.header.frame_id = "map";
    grid.info.resolution = res; grid.info.width = W; grid.info.height = H;
    grid.info.origin = map_->info.origin;
    grid.data.resize(W*H, -1);
    for (int i=0; i<W*H; i++)
        if (density[i]>1e-15)
            grid.data[i] = std::clamp((int)(density[i]/max_d*100.0), 0, 100);
    particle_heatmap_pub_->publish(grid);
}

} // namespace hospital_nav

int main(int argc, char ** argv) {
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<hospital_nav::AMCL>());
    rclcpp::shutdown();
    return 0;
}
