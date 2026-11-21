#pragma once

#include <rclcpp/rclcpp.hpp>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>
#include <geometry_msgs/msg/transform_stamped.hpp>
#include <tf2_ros/buffer.h>

#include <memory>
#include <mutex>
#include <string>
#include <vector>
#include <cstdint>

namespace hospital_nav
{

constexpr uint8_t FREE_SPACE      = 0;
constexpr uint8_t INSCRIBED_COST  = 253;
constexpr uint8_t LETHAL_COST     = 254;
constexpr uint8_t NO_INFORMATION  = 255;

struct CostmapParams
{
  double resolution       = 0.05;
  double inflation_radius = 0.75;
  double inscribed_radius = 0.45;
  double cost_scaling     = 3.0;
  double obstacle_range   = 5.0;
  double raytrace_range   = 6.0;

  std::string global_frame = "map";
  std::string robot_frame  = "base_footprint";
};

struct InflationCell
{
  int dx;
  int dy;
  uint8_t cost;
};

class Costmap
{
public:
  Costmap(rclcpp::Node* node,
          std::shared_ptr<tf2_ros::Buffer> tf_buffer,
          const CostmapParams& params);

  void mapCallback(const nav_msgs::msg::OccupancyGrid::SharedPtr msg);
  void scanCallback(const sensor_msgs::msg::LaserScan::SharedPtr msg);
  void update();

  bool isMapReceived() const
  {
    std::lock_guard<std::mutex> lock(map_mutex_);
    return map_received_;
  }

  unsigned int getSizeX() const
  {
    std::lock_guard<std::mutex> lock(map_mutex_);
    return size_x_;
  }

  unsigned int getSizeY() const
  {
    std::lock_guard<std::mutex> lock(map_mutex_);
    return size_y_;
  }

  double getResolution() const
  {
    std::lock_guard<std::mutex> lock(map_mutex_);
    return resolution_;
  }

  bool worldToMap(double wx, double wy, int& mx, int& my) const;
  void mapToWorld(int mx, int my, double& wx, double& wy) const;
  bool isValid(int mx, int my) const;
  uint8_t getCost(int mx, int my) const;

  nav_msgs::msg::OccupancyGrid toOccupancyGrid() const;

private:
  void applyStaticLayer();
  void applyObstacleLayer();
  void applyInflation();

  // 로봇 footprint 내부를 FREE로 클리어
  void clearFootprint();

  void computeInflationKernel();
  uint8_t computeInflationCost(double distance) const;

  // Bresenham raytrace — 끝점(endpoint) 직전까지만 클리어
  void raytrace(int x0, int y0, int x1, int y1);

  bool lookupScanTransform(
    const sensor_msgs::msg::LaserScan::SharedPtr& scan,
    geometry_msgs::msg::TransformStamped& tf_scan) const;

  bool lookupRobotPose(double& wx, double& wy) const;

  // 내부용: map_mutex_가 이미 잡혀 있다고 가정
  bool worldToMapUnlocked(double wx, double wy, int& mx, int& my) const;
  void mapToWorldUnlocked(int mx, int my, double& wx, double& wy) const;
  bool isValidUnlocked(int mx, int my) const;
  uint8_t getCostUnlocked(int mx, int my) const;

private:
  rclcpp::Node* node_;
  std::shared_ptr<tf2_ros::Buffer> tf_buffer_;
  CostmapParams params_;

  mutable std::mutex map_mutex_;
  mutable std::mutex scan_mutex_;

  bool map_received_ = false;

  unsigned int size_x_ = 0;
  unsigned int size_y_ = 0;
  double resolution_ = 0.05;
  double origin_x_ = 0.0;
  double origin_y_ = 0.0;

  std::vector<uint8_t> static_grid_;
  std::vector<uint8_t> obstacle_grid_;
  std::vector<uint8_t> master_grid_;
  std::vector<InflationCell> inflation_kernel_;

  sensor_msgs::msg::LaserScan::SharedPtr latest_scan_;
};

}  // namespace hospital_nav
