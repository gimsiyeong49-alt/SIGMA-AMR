#include "hospital_nav/costmap.hpp"

#include <tf2/utils.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.h>

#include <algorithm>
#include <cmath>

namespace hospital_nav
{

Costmap::Costmap(rclcpp::Node* node,
                 std::shared_ptr<tf2_ros::Buffer> tf_buffer,
                 const CostmapParams& params)
  : node_(node), tf_buffer_(std::move(tf_buffer)), params_(params)
{
}

// ============================================================
// 맵 콜백: static layer 초기화
// ============================================================
void Costmap::mapCallback(const nav_msgs::msg::OccupancyGrid::SharedPtr msg)
{
  std::lock_guard<std::mutex> lock(map_mutex_);

  size_x_     = msg->info.width;
  size_y_     = msg->info.height;
  resolution_ = msg->info.resolution;
  origin_x_   = msg->info.origin.position.x;
  origin_y_   = msg->info.origin.position.y;

  const size_t total = static_cast<size_t>(size_x_) * size_y_;

  static_grid_.assign(total, FREE_SPACE);
  obstacle_grid_.assign(total, FREE_SPACE);
  master_grid_.assign(total, FREE_SPACE);

  for (size_t i = 0; i < total; ++i) {
    const int8_t val = msg->data[i];

    if (val < 0) {
      static_grid_[i] = NO_INFORMATION;
    } else if (val == 0) {
      static_grid_[i] = FREE_SPACE;
    } else if (val >= 65) {
      static_grid_[i] = LETHAL_COST;
    } else {
      static_grid_[i] = static_cast<uint8_t>(
        std::min(252.0, static_cast<double>(val) * 252.0 / 100.0));
    }
  }

  computeInflationKernel();

  map_received_ = true;

  RCLCPP_INFO(
    node_->get_logger(),
    "Costmap: static layer loaded (%u x %u, res=%.3f)",
    size_x_, size_y_, resolution_);
}

// ============================================================
// 스캔 콜백: 최신 scan 저장
// ============================================================
void Costmap::scanCallback(const sensor_msgs::msg::LaserScan::SharedPtr msg)
{
  std::lock_guard<std::mutex> lock(scan_mutex_);
  latest_scan_ = msg;
}

// ============================================================
// costmap 전체 갱신
// ============================================================
void Costmap::update()
{
  std::lock_guard<std::mutex> map_lock(map_mutex_);

  if (!map_received_) {
    return;
  }

  applyStaticLayer();
  applyObstacleLayer();
  clearFootprint();      // 로봇 발자국 내부 클리어
  applyInflation();
}

// ============================================================
// static layer → master 복사
// ============================================================
void Costmap::applyStaticLayer()
{
  master_grid_ = static_grid_;
}

// ============================================================
// obstacle layer: scan을 costmap에 반영
// ============================================================
void Costmap::applyObstacleLayer()
{
  sensor_msgs::msg::LaserScan::SharedPtr scan;
  {
    std::lock_guard<std::mutex> lock(scan_mutex_);
    scan = latest_scan_;
  }

  if (!scan) {
    return;
  }

  geometry_msgs::msg::TransformStamped tf_scan;
  if (!lookupScanTransform(scan, tf_scan)) {
    return;
  }

  const double sensor_wx  = tf_scan.transform.translation.x;
  const double sensor_wy  = tf_scan.transform.translation.y;
  const double sensor_yaw = tf2::getYaw(tf_scan.transform.rotation);

  int sensor_mx = 0;
  int sensor_my = 0;
  if (!worldToMapUnlocked(sensor_wx, sensor_wy, sensor_mx, sensor_my)) {
    return;
  }

  // 동적 obstacle layer는 매 프레임 새로 구성
  std::fill(obstacle_grid_.begin(), obstacle_grid_.end(), FREE_SPACE);

  double angle = scan->angle_min;

  for (size_t i = 0; i < scan->ranges.size(); ++i, angle += scan->angle_increment) {
    const double r = scan->ranges[i];

    if (std::isnan(r) || std::isinf(r)) {
      continue;
    }
    if (r < scan->range_min) {
      continue;
    }

    const double hit_angle = sensor_yaw + angle;

    if (r <= std::min(static_cast<double>(scan->range_max), params_.obstacle_range)) {
      // hit point
      const double hit_wx = sensor_wx + r * std::cos(hit_angle);
      const double hit_wy = sensor_wy + r * std::sin(hit_angle);

      int hit_mx = 0;
      int hit_my = 0;
      if (worldToMapUnlocked(hit_wx, hit_wy, hit_mx, hit_my)) {
        // raytrace: sensor → hit point 직전까지 free space 클리어
        raytrace(sensor_mx, sensor_my, hit_mx, hit_my);

        // obstacle marking (hit point 자체)
        const size_t idx = static_cast<size_t>(hit_my) * size_x_ + hit_mx;
        obstacle_grid_[idx] = LETHAL_COST;
      }
    } else {
      // obstacle_range 밖이면 marking은 안 하고 free ray만 반영
      const double rt_dist = std::min(r, params_.raytrace_range);
      const double rt_wx = sensor_wx + rt_dist * std::cos(hit_angle);
      const double rt_wy = sensor_wy + rt_dist * std::sin(hit_angle);

      int rt_mx = 0;
      int rt_my = 0;
      if (worldToMapUnlocked(rt_wx, rt_wy, rt_mx, rt_my)) {
        raytrace(sensor_mx, sensor_my, rt_mx, rt_my);
      }
    }
  }

  // obstacle layer → master 합성 (max)
  const size_t total = static_cast<size_t>(size_x_) * size_y_;
  for (size_t i = 0; i < total; ++i) {
    if (obstacle_grid_[i] > master_grid_[i]) {
      master_grid_[i] = obstacle_grid_[i];
    }
  }
}

// ============================================================
// Footprint clearing
// 로봇이 현재 서 있는 위치의 inscribed_radius 내부를
// FREE_SPACE로 클리어 — 자기 자신이 장애물로 보이는 것 방지
// ============================================================
void Costmap::clearFootprint()
{
  double robot_wx, robot_wy;
  if (!lookupRobotPose(robot_wx, robot_wy)) {
    return;
  }

  int robot_mx, robot_my;
  if (!worldToMapUnlocked(robot_wx, robot_wy, robot_mx, robot_my)) {
    return;
  }

  // inscribed_radius 내부의 셀을 FREE로
  const int cell_radius = static_cast<int>(
    std::ceil(params_.inscribed_radius / resolution_));

  for (int dy = -cell_radius; dy <= cell_radius; ++dy) {
    for (int dx = -cell_radius; dx <= cell_radius; ++dx) {
      const double dist = std::hypot(dx, dy) * resolution_;
      if (dist > params_.inscribed_radius) {
        continue;
      }

      const int nx = robot_mx + dx;
      const int ny = robot_my + dy;
      if (!isValidUnlocked(nx, ny)) {
        continue;
      }

      const size_t idx = static_cast<size_t>(ny) * size_x_ + nx;
      // static layer의 lethal은 건드리지 않음 (벽은 항상 유지)
      if (static_grid_[idx] < LETHAL_COST) {
        master_grid_[idx] = FREE_SPACE;
      }
    }
  }
}

// ============================================================
// Inflation layer
// ============================================================
void Costmap::applyInflation()
{
  if (inflation_kernel_.empty()) {
    return;
  }

  std::vector<std::pair<int, int>> lethal_cells;
  lethal_cells.reserve((size_x_ * size_y_) / 16 + 1);

  for (unsigned int y = 0; y < size_y_; ++y) {
    for (unsigned int x = 0; x < size_x_; ++x) {
      if (master_grid_[static_cast<size_t>(y) * size_x_ + x] == LETHAL_COST) {
        lethal_cells.emplace_back(static_cast<int>(x), static_cast<int>(y));
      }
    }
  }

  for (const auto& cell : lethal_cells) {
    const int cx = cell.first;
    const int cy = cell.second;

    for (const auto& kernel : inflation_kernel_) {
      const int nx = cx + kernel.dx;
      const int ny = cy + kernel.dy;

      if (!isValidUnlocked(nx, ny)) {
        continue;
      }

      const size_t idx = static_cast<size_t>(ny) * size_x_ + nx;
      if (kernel.cost > master_grid_[idx]) {
        master_grid_[idx] = kernel.cost;
      }
    }
  }
}

// ============================================================
// inflation 커널 미리 계산
// ============================================================
void Costmap::computeInflationKernel()
{
  inflation_kernel_.clear();

  if (resolution_ <= 0.0) {
    RCLCPP_WARN(node_->get_logger(), "Costmap: invalid resolution %.6f", resolution_);
    return;
  }

  const int cell_radius = static_cast<int>(
    std::ceil(params_.inflation_radius / resolution_));

  for (int dy = -cell_radius; dy <= cell_radius; ++dy) {
    for (int dx = -cell_radius; dx <= cell_radius; ++dx) {
      if (dx == 0 && dy == 0) {
        continue;
      }

      const double dist = std::hypot(dx, dy) * resolution_;
      if (dist > params_.inflation_radius) {
        continue;
      }

      const uint8_t cost = computeInflationCost(dist);
      if (cost > FREE_SPACE) {
        inflation_kernel_.push_back({dx, dy, cost});
      }
    }
  }

  std::sort(
    inflation_kernel_.begin(),
    inflation_kernel_.end(),
    [](const InflationCell& a, const InflationCell& b) {
      return a.cost > b.cost;
    });

  RCLCPP_INFO(
    node_->get_logger(),
    "Costmap: inflation kernel size = %zu cells (radius=%.2f m, inscribed=%.2f m)",
    inflation_kernel_.size(),
    params_.inflation_radius,
    params_.inscribed_radius);
}

uint8_t Costmap::computeInflationCost(double distance) const
{
  if (distance <= 0.0) {
    return LETHAL_COST;
  }
  if (distance <= params_.inscribed_radius) {
    return INSCRIBED_COST;
  }
  if (distance > params_.inflation_radius) {
    return FREE_SPACE;
  }

  const double val = 252.0 * std::exp(
    -params_.cost_scaling * (distance - params_.inscribed_radius));

  return static_cast<uint8_t>(std::clamp(val, 0.0, 252.0));
}

// ============================================================
// Bresenham raytrace
// 끝점(x1,y1)은 clearing하지 않음 — hit point를 지우지 않기 위해
// ============================================================
void Costmap::raytrace(int x0, int y0, int x1, int y1)
{
  int dx = std::abs(x1 - x0);
  int dy = std::abs(y1 - y0);
  int sx = (x0 < x1) ? 1 : -1;
  int sy = (y0 < y1) ? 1 : -1;
  int err = dx - dy;

  // 끝점 직전까지만 clearing
  while (x0 != x1 || y0 != y1) {
    if (isValidUnlocked(x0, y0)) {
      const size_t idx = static_cast<size_t>(y0) * size_x_ + x0;
      obstacle_grid_[idx] = FREE_SPACE;
    }

    const int e2 = 2 * err;
    if (e2 > -dy) {
      err -= dy;
      x0 += sx;
    }
    if (e2 < dx) {
      err += dx;
      y0 += sy;
    }
  }
  // x0==x1 && y0==y1 인 끝점은 clearing하지 않음
}

// ============================================================
// TF lookups
// ============================================================
bool Costmap::lookupScanTransform(
  const sensor_msgs::msg::LaserScan::SharedPtr& scan,
  geometry_msgs::msg::TransformStamped& tf_scan) const
{
  try {
    tf_scan = tf_buffer_->lookupTransform(
      params_.global_frame,
      scan->header.frame_id,
      tf2::TimePointZero,
      tf2::durationFromSec(0.1));
    return true;
  } catch (const tf2::TransformException& ex) {
    RCLCPP_WARN_THROTTLE(
      node_->get_logger(),
      *node_->get_clock(),
      2000,
      "Costmap: scan TF failed (%s -> %s): %s",
      scan->header.frame_id.c_str(),
      params_.global_frame.c_str(),
      ex.what());
    return false;
  }
}

bool Costmap::lookupRobotPose(double& wx, double& wy) const
{
  try {
    const auto tf = tf_buffer_->lookupTransform(
      params_.global_frame,
      params_.robot_frame,
      tf2::TimePointZero,
      tf2::durationFromSec(0.05));
    wx = tf.transform.translation.x;
    wy = tf.transform.translation.y;
    return true;
  } catch (const tf2::TransformException&) {
    return false;
  }
}

// ============================================================
// 좌표 변환
// ============================================================
bool Costmap::worldToMap(double wx, double wy, int& mx, int& my) const
{
  std::lock_guard<std::mutex> lock(map_mutex_);
  return worldToMapUnlocked(wx, wy, mx, my);
}

void Costmap::mapToWorld(int mx, int my, double& wx, double& wy) const
{
  std::lock_guard<std::mutex> lock(map_mutex_);
  mapToWorldUnlocked(mx, my, wx, wy);
}

bool Costmap::isValid(int mx, int my) const
{
  std::lock_guard<std::mutex> lock(map_mutex_);
  return isValidUnlocked(mx, my);
}

uint8_t Costmap::getCost(int mx, int my) const
{
  std::lock_guard<std::mutex> lock(map_mutex_);
  return getCostUnlocked(mx, my);
}

bool Costmap::worldToMapUnlocked(double wx, double wy, int& mx, int& my) const
{
  if (resolution_ <= 0.0) {
    return false;
  }

  mx = static_cast<int>(std::floor((wx - origin_x_) / resolution_));
  my = static_cast<int>(std::floor((wy - origin_y_) / resolution_));

  return isValidUnlocked(mx, my);
}

void Costmap::mapToWorldUnlocked(int mx, int my, double& wx, double& wy) const
{
  wx = origin_x_ + (static_cast<double>(mx) + 0.5) * resolution_;
  wy = origin_y_ + (static_cast<double>(my) + 0.5) * resolution_;
}

bool Costmap::isValidUnlocked(int mx, int my) const
{
  return mx >= 0 &&
         my >= 0 &&
         mx < static_cast<int>(size_x_) &&
         my < static_cast<int>(size_y_);
}

uint8_t Costmap::getCostUnlocked(int mx, int my) const
{
  if (!isValidUnlocked(mx, my)) {
    return LETHAL_COST;
  }

  return master_grid_[static_cast<size_t>(my) * size_x_ + mx];
}

// ============================================================
// 퍼블리시용 변환
// ============================================================
nav_msgs::msg::OccupancyGrid Costmap::toOccupancyGrid() const
{
  std::lock_guard<std::mutex> lock(map_mutex_);

  nav_msgs::msg::OccupancyGrid grid;
  grid.header.frame_id = params_.global_frame;
  grid.info.resolution = resolution_;
  grid.info.width      = size_x_;
  grid.info.height     = size_y_;
  grid.info.origin.position.x = origin_x_;
  grid.info.origin.position.y = origin_y_;
  grid.info.origin.orientation.w = 1.0;

  grid.data.resize(static_cast<size_t>(size_x_) * size_y_);

  for (size_t i = 0; i < master_grid_.size(); ++i) {
    const uint8_t c = master_grid_[i];

    if (c == NO_INFORMATION) {
      grid.data[i] = -1;
    } else if (c == FREE_SPACE) {
      grid.data[i] = 0;
    } else if (c >= LETHAL_COST) {
      grid.data[i] = 100;
    } else {
      grid.data[i] = static_cast<int8_t>(
        std::min(99, static_cast<int>(c) * 100 / 252));
    }
  }

  return grid;
}

}  // namespace hospital_nav
