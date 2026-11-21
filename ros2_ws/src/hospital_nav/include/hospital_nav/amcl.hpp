#pragma once
#include <rclcpp/rclcpp.hpp>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/pose_array.hpp>
#include <visualization_msgs/msg/marker_array.hpp>
#include <tf2_ros/transform_broadcaster.h>
#include <tf2_ros/transform_listener.h>
#include <tf2_ros/buffer.h>
#include <tf2/LinearMath/Transform.h>
#include <random>
#include <mutex>
#include <vector>

namespace hospital_nav {

struct Particle {
    double x, y, theta, weight;
};

class AMCL : public rclcpp::Node {
public:
    explicit AMCL(const rclcpp::NodeOptions & options = rclcpp::NodeOptions());

private:
    void mapCallback(const nav_msgs::msg::OccupancyGrid::SharedPtr msg);
    void odomCallback(const nav_msgs::msg::Odometry::SharedPtr msg);
    void scanCallback(const sensor_msgs::msg::LaserScan::SharedPtr msg);
    void initialPoseCallback(const geometry_msgs::msg::PoseWithCovarianceStamped::SharedPtr msg);

    void initParticles(double x, double y, double theta, double sigma);
    void motionUpdate(double dx, double dy, double dtheta);
    void sensorUpdate(const sensor_msgs::msg::LaserScan::SharedPtr scan);
    void resample();
    void publishResult();
    void publishParticleHeatmap(const rclcpp::Time & stamp);

    void buildLikelihoodField();
    double likelihood(double x, double y);
    void injectRandomParticles(int count);
    void buildFreeCellList();

    std::vector<Particle> particles_;
    int  num_particles_{500};
    bool map_received_{false};
    bool initialized_{false};
    bool initial_pose_received_{false};

    nav_msgs::msg::OccupancyGrid::SharedPtr map_;
    std::vector<double> likelihood_field_;
    struct FreeCell { double wx, wy; };
    std::vector<FreeCell> free_cells_;

    double odom_x_{0}, odom_y_{0}, odom_theta_{0};
    mutable std::mutex odom_mutex_;
    bool odom_initialized_{false};

    bool   pending_init_{false};
    double pending_x_{0}, pending_y_{0}, pending_theta_{0};

    rclcpp::TimerBase::SharedPtr publish_timer_;

    rclcpp::Subscription<nav_msgs::msg::OccupancyGrid>::SharedPtr              map_sub_;
    rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr                   odom_sub_;
    rclcpp::Subscription<sensor_msgs::msg::LaserScan>::SharedPtr               scan_sub_;
    rclcpp::Subscription<geometry_msgs::msg::PoseWithCovarianceStamped>::SharedPtr init_sub_;

    rclcpp::Publisher<geometry_msgs::msg::PoseWithCovarianceStamped>::SharedPtr pose_pub_;
    rclcpp::Publisher<geometry_msgs::msg::PoseArray>::SharedPtr                particle_pub_;
    rclcpp::Publisher<visualization_msgs::msg::MarkerArray>::SharedPtr         particle_marker_pub_;
    rclcpp::Publisher<nav_msgs::msg::OccupancyGrid>::SharedPtr                 particle_heatmap_pub_;

    std::shared_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster_;
    std::shared_ptr<tf2_ros::Buffer>               tf_buffer_;
    std::shared_ptr<tf2_ros::TransformListener>    tf_listener_;

    std::mt19937 rng_{std::random_device{}()};

    double sigma_hit_{0.2};
    double z_hit_{0.95};
    double z_rand_{0.05};
    double laser_max_range_{10.0};
    int    laser_skip_{10};
    double alpha1_{0.10};
    double alpha2_{0.05};
    double alpha3_{0.10};
    double alpha4_{0.05};
    double random_particle_ratio_{0.02};
};

} // namespace hospital_nav
