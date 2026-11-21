#pragma once

#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include <nav_msgs/msg/path.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>

#include <vector>
#include <mutex>
#include <string>

namespace hospital_nav
{

struct LocalPlannerParams
{
  // Lookahead
  double lookahead_distance = 0.35;
  double lookahead_gain     = 0.3;
  double min_lookahead      = 0.30;
  double max_lookahead      = 0.80;

  // Velocity
  double max_linear_vel  = 0.4;
  double min_linear_vel  = 0.05;
  double max_angular_vel = 1.0;

  // Goal tolerance
  double goal_tolerance_xy  = 0.20;
  double goal_tolerance_yaw = 0.20;
  double controller_freq    = 20.0;

  // Safety — RPP에서는 바이너리 정지 대신 부드러운 규제
  double emergency_stop_dist = 0.20;   // 진짜 충돌 직전만 (arc clearance <= 0)
  double slowdown_dist       = 1.20;   // 여기서부터 감속 시작

  // Rotate-in-place
  double rotate_in_place_enter_angle = 1.0;
  double rotate_in_place_exit_angle  = 0.30;
  double goal_slowdown_dist          = 0.80;
  double final_yaw_align_gain        = 1.5;
  double min_rotate_speed            = 0.12;
  double front_obstacle_half_angle   = 0.35;  // fallback용 (arc check 비활성 시)

  // 기존 곡률 파라미터 (하위 호환 유지, RPP에서는 미사용)
  double curvature_low_threshold  = 0.1;
  double curvature_high_threshold = 1.5;
  double curvature_min_scale      = 0.2;

  // === RPP: Regulated Pure Pursuit ===
  // 회전 반경 기반 속도 규제
  double regulated_linear_scaling_min_radius = 0.9;   // m, 이 반경 이하부터 감속
  double regulated_linear_scaling_min_speed  = 0.25;  // 최소 유지 속도 비율 [0,1]

  // Arc 기반 장애물 검사
  bool   use_arc_collision_check = true;
  int    arc_check_samples       = 6;
  double arc_check_robot_radius  = 0.45;  // m, inscribed_radius와 맞출 것

  std::string robot_frame = "base_footprint";
};

class LocalPlanner
{
public:
  LocalPlanner(rclcpp::Node* node, const LocalPlannerParams& params);

  void setPath(const nav_msgs::msg::Path& path);
  void updatePath(const nav_msgs::msg::Path& path);

  bool computeVelocity(const geometry_msgs::msg::PoseStamped& current_pose,
                       geometry_msgs::msg::Twist& cmd_vel);

  bool isGoalReached(const geometry_msgs::msg::PoseStamped& current_pose) const;
  void updateScanData(const sensor_msgs::msg::LaserScan::SharedPtr scan);
  bool hasPath() const;
  void clearPath();

private:
  bool findLookaheadPoint(const geometry_msgs::msg::PoseStamped& current_pose,
                          geometry_msgs::msg::PoseStamped& lookahead_point);
  void   updateClosestIndex(double robot_x, double robot_y);
  double computeLookahead(double linear_vel) const;

  // RPP 핵심: arc 위 샘플 점들로 장애물까지 최소 여유 거리 계산
  double getArcMinClearance(double curvature, double arc_length) const;

  // RPP 핵심: 곡률 + 장애물 + 목표 거리로 규제된 선속도 계산
  double computeRPPLinearVel(double curvature,
                              double arc_clearance,
                              double dist_to_goal) const;

  // fallback: arc check 비활성 시 전방 콘 최소 거리
  double getMinFrontDistance() const;

  double computeGoalSpeedScale(double dist_to_goal) const;
  double normalizeAngle(double angle) const;
  double applyMinRotateSpeed(double w) const;

private:
  rclcpp::Node*      node_;
  LocalPlannerParams params_;

  nav_msgs::msg::Path path_;
  size_t              closest_idx_ = 0;

  mutable std::mutex path_mutex_;
  sensor_msgs::msg::LaserScan::SharedPtr latest_scan_;
  mutable std::mutex scan_mutex_;

  bool   rotating_in_place_ = false;
  double last_linear_cmd_   = 0.0;
  double last_angular_cmd_  = 0.0;
};

}  // namespace hospital_nav
