#include "hospital_nav/local_planner.hpp"
#include <tf2/utils.h>
#include <algorithm>
#include <cmath>
#include <limits>

namespace hospital_nav
{

LocalPlanner::LocalPlanner(rclcpp::Node* node, const LocalPlannerParams& params)
  : node_(node), params_(params)
{
  RCLCPP_INFO(node_->get_logger(),
    "LocalPlanner [RPP]: arc_check=%s, min_radius=%.2f m, min_speed_ratio=%.2f",
    params_.use_arc_collision_check ? "ON" : "OFF",
    params_.regulated_linear_scaling_min_radius,
    params_.regulated_linear_scaling_min_speed);
}

void LocalPlanner::setPath(const nav_msgs::msg::Path& path)
{
  std::lock_guard<std::mutex> lock(path_mutex_);
  path_              = path;
  closest_idx_       = 0;
  rotating_in_place_ = false;
  last_linear_cmd_   = 0.0;
  last_angular_cmd_  = 0.0;
  RCLCPP_INFO(node_->get_logger(),
              "LocalPlanner: received NEW path with %zu poses (full reset)",
              path_.poses.size());
}

void LocalPlanner::updatePath(const nav_msgs::msg::Path& path)
{
  std::lock_guard<std::mutex> lock(path_mutex_);
  path_ = path;
  if (!path_.poses.empty() && closest_idx_ >= path_.poses.size())
    closest_idx_ = path_.poses.size() - 1;
  RCLCPP_DEBUG(node_->get_logger(),
               "LocalPlanner: path updated with %zu poses (state preserved)",
               path_.poses.size());
}

void LocalPlanner::updateScanData(const sensor_msgs::msg::LaserScan::SharedPtr scan)
{
  std::lock_guard<std::mutex> lock(scan_mutex_);
  latest_scan_ = scan;
}

bool LocalPlanner::hasPath() const
{
  std::lock_guard<std::mutex> lock(path_mutex_);
  return !path_.poses.empty();
}

void LocalPlanner::clearPath()
{
  std::lock_guard<std::mutex> lock(path_mutex_);
  path_.poses.clear();
  closest_idx_       = 0;
  rotating_in_place_ = false;
  last_linear_cmd_   = 0.0;
  last_angular_cmd_  = 0.0;
}

// ============================================================
// computeVelocity — RPP 메인 루프
// ============================================================
bool LocalPlanner::computeVelocity(const geometry_msgs::msg::PoseStamped& current_pose,
                                   geometry_msgs::msg::Twist& cmd_vel)
{
  cmd_vel = geometry_msgs::msg::Twist();
  std::lock_guard<std::mutex> path_lock(path_mutex_);

  if (path_.poses.empty()) {
    last_linear_cmd_ = last_angular_cmd_ = 0.0;
    rotating_in_place_ = false;
    return false;
  }

  const double robot_x   = current_pose.pose.position.x;
  const double robot_y   = current_pose.pose.position.y;
  const double robot_yaw = tf2::getYaw(current_pose.pose.orientation);

  const auto&  goal         = path_.poses.back();
  const double goal_dx      = goal.pose.position.x - robot_x;
  const double goal_dy      = goal.pose.position.y - robot_y;
  const double dist_to_goal = std::hypot(goal_dx, goal_dy);
  const double yaw_error    = normalizeAngle(
    tf2::getYaw(goal.pose.orientation) - robot_yaw);

  // ── 1. Goal 도착 판정 ────────────────────────────────────
  if (dist_to_goal <= params_.goal_tolerance_xy) {
    rotating_in_place_ = false;
    if (std::abs(yaw_error) <= params_.goal_tolerance_yaw) {
      last_linear_cmd_ = last_angular_cmd_ = 0.0;
      return false;
    }
    // 최종 yaw 정렬
    cmd_vel.linear.x  = 0.0;
    cmd_vel.angular.z = applyMinRotateSpeed(
      std::clamp(params_.final_yaw_align_gain * yaw_error,
                 -params_.max_angular_vel, params_.max_angular_vel));
    last_linear_cmd_  = 0.0;
    last_angular_cmd_ = cmd_vel.angular.z;
    return true;
  }

  // ── 2. Lookahead point 탐색 ──────────────────────────────
  geometry_msgs::msg::PoseStamped lookahead;
  if (!findLookaheadPoint(current_pose, lookahead)) {
    last_linear_cmd_ = last_angular_cmd_ = 0.0;
    rotating_in_place_ = false;
    return false;
  }

  // ── 3. 로봇 로컬 좌표 변환 ──────────────────────────────
  const double dx      = lookahead.pose.position.x - robot_x;
  const double dy      = lookahead.pose.position.y - robot_y;
  const double c       =  std::cos(robot_yaw);
  const double s       =  std::sin(robot_yaw);
  const double local_x =  c * dx + s * dy;
  const double local_y = -s * dx + c * dy;
  const double dist_la = std::hypot(local_x, local_y);

  if (dist_la < 1e-4) {
    last_linear_cmd_ = last_angular_cmd_ = 0.0;
    return true;
  }

  const double angle_to_la = std::atan2(local_y, local_x);
  const double abs_angle   = std::abs(angle_to_la);

  // ── 4. Rotate-in-place 히스테리시스 ─────────────────────
  if (!rotating_in_place_ && abs_angle > params_.rotate_in_place_enter_angle) {
    rotating_in_place_ = true;
  } else if (rotating_in_place_ && abs_angle < params_.rotate_in_place_exit_angle) {
    rotating_in_place_ = false;
  }

  // ── 5. 제자리 회전 (heading error가 너무 큼) ────────────
  if (rotating_in_place_) {
    cmd_vel.linear.x  = 0.0;
    cmd_vel.angular.z = applyMinRotateSpeed(
      std::clamp(2.0 * angle_to_la,
                 -params_.max_angular_vel, params_.max_angular_vel));
    last_linear_cmd_  = 0.0;
    last_angular_cmd_ = cmd_vel.angular.z;
    RCLCPP_DEBUG_THROTTLE(node_->get_logger(), *node_->get_clock(), 300,
      "RPP: rotate-in-place %.2f rad", angle_to_la);
    return true;
  }

  // ── 6. Pure Pursuit 곡률 κ = 2y_l / L² ─────────────────
  const double curvature = 2.0 * local_y / (dist_la * dist_la);

  // ── 7. Arc 장애물 검사 (RPP 핵심) ───────────────────────
  // 로봇이 실제로 달릴 arc 위의 점들을 샘플링해서 장애물 여유 계산
  // → 직진 시 옆 벽은 무시, 실제 경로 방향만 체크
  const double lookahead_dist = computeLookahead(last_linear_cmd_);
  const double arc_clearance  = params_.use_arc_collision_check
    ? getArcMinClearance(curvature, lookahead_dist)
    : (getMinFrontDistance() - params_.arc_check_robot_radius);

  // ── 8. RPP 규제 선속도 계산 (binary stop 없음) ──────────
  double linear_vel = computeRPPLinearVel(curvature, arc_clearance, dist_to_goal);

  // 방향 오차 감속 (±90° 넘으면 정지, ±45~90° 사이에서 선형 감속)
  if (abs_angle > M_PI / 2.0) {
    linear_vel = 0.0;
  } else if (abs_angle > M_PI / 4.0) {
    linear_vel *= 1.0 - (abs_angle - M_PI / 4.0) / (M_PI / 4.0);
  }

  linear_vel = std::clamp(linear_vel,
    (linear_vel > 0.001 ? params_.min_linear_vel : 0.0),
    params_.max_linear_vel);

  // ── 9. 각속도: ω = κ × v ────────────────────────────────
  double angular_vel;
  if (linear_vel < 0.01) {
    // 선속도가 0에 가까우면 제자리 회전
    angular_vel = applyMinRotateSpeed(
      std::clamp(2.0 * angle_to_la,
                 -params_.max_angular_vel, params_.max_angular_vel));
  } else {
    angular_vel = std::clamp(curvature * linear_vel,
                             -params_.max_angular_vel, params_.max_angular_vel);
  }

  cmd_vel.linear.x  = linear_vel;
  cmd_vel.angular.z = angular_vel;
  last_linear_cmd_  = linear_vel;
  last_angular_cmd_ = angular_vel;

  RCLCPP_DEBUG_THROTTLE(node_->get_logger(), *node_->get_clock(), 300,
    "RPP: angle=%.2f curv=%.3f clearance=%.2f lin=%.2f ang=%.2f",
    angle_to_la, curvature, arc_clearance, linear_vel, angular_vel);

  return true;
}

// ============================================================
// getArcMinClearance — RPP 핵심
//
// curvature: κ = 1/R (부호 있음, 좌회전 > 0)
// arc_length: lookahead 거리 (m)
//
// arc 위 N개 점의 좌표(로봇 로컬 프레임):
//   κ≠0: x(s) = sin(κs)/κ,  y(s) = (1-cos(κs))/κ
//   κ=0: x(s) = s,           y(s) = 0
//
// 각 점 방향의 레이저 빔과 비교해 여유(clearance) 계산.
// 직진 시 → forward 빔만 확인 → 옆 벽 무시 → emergency stop 오탐 해결
// ============================================================
double LocalPlanner::getArcMinClearance(double curvature, double arc_length) const
{
  sensor_msgs::msg::LaserScan::SharedPtr scan;
  { std::lock_guard<std::mutex> lock(scan_mutex_); scan = latest_scan_; }
  if (!scan || scan->ranges.empty()) return 100.0;

  const int    n_ranges   = static_cast<int>(scan->ranges.size());
  double       min_clear  = 100.0;

  for (int i = 1; i <= params_.arc_check_samples; ++i) {
    const double t = static_cast<double>(i) / params_.arc_check_samples;
    const double arc_s = arc_length * t;

    // arc 위 점의 로컬 좌표
    double px, py;
    if (std::abs(curvature) < 1e-6) {
      px = arc_s; py = 0.0;
    } else {
      const double theta = curvature * arc_s;
      px = std::sin(theta) / curvature;
      py = (1.0 - std::cos(theta)) / curvature;
    }

    // 로봇에서 이 점까지의 방향(scan 프레임 기준)
    const double point_angle = std::atan2(py, px);
    const double point_dist  = std::hypot(px, py);

    // scan 인덱스 계산
    const int center_idx = static_cast<int>(
      std::round((point_angle - scan->angle_min) / scan->angle_increment));

    if (center_idx < 0 || center_idx >= n_ranges) continue;

    // 인접 3개 빔 확인 (노이즈 대응)
    for (int di = -1; di <= 1; ++di) {
      const int idx = center_idx + di;
      if (idx < 0 || idx >= n_ranges) continue;

      const float r = scan->ranges[idx];
      if (std::isnan(r) || std::isinf(r) || r < scan->range_min) continue;

      // clearance = 레이저 거리 - arc 점까지 거리 - 로봇 반경
      const double clearance = static_cast<double>(r) - point_dist
                               - params_.arc_check_robot_radius;
      if (clearance < min_clear) min_clear = clearance;
    }
  }

  return min_clear;
}

// ============================================================
// computeRPPLinearVel — 규제된 선속도
//
// 1. Goal 감속 (기존 동일)
// 2. 곡률 기반 속도 규제: 회전 반경이 작을수록 감속
//    v *= max(min_speed_ratio, R / R_min)
// 3. 장애물 기반 속도 규제: clearance가 작을수록 감속
//    clearance <= 0: 완전 정지 (충돌 직전)
//    0 < clearance < slowdown_dist: 선형 감속
//    clearance >= slowdown_dist: 감속 없음
// ============================================================
double LocalPlanner::computeRPPLinearVel(double curvature,
                                          double arc_clearance,
                                          double dist_to_goal) const
{
  double v = params_.max_linear_vel;

  // 1. Goal 근접 감속
  v *= computeGoalSpeedScale(dist_to_goal);

  // 2. 회전 반경 기반 규제
  if (std::abs(curvature) > 1e-6) {
    const double turning_radius = 1.0 / std::abs(curvature);
    if (turning_radius < params_.regulated_linear_scaling_min_radius) {
      const double radius_scale = std::max(
        params_.regulated_linear_scaling_min_speed,
        turning_radius / params_.regulated_linear_scaling_min_radius);
      v *= radius_scale;
    }
  }

  // 3. 장애물 근접 규제 (binary stop 없이 부드럽게)
  if (arc_clearance <= 0.0) {
    // arc 위 점이 이미 장애물 영역 → 완전 정지
    v = 0.0;
    RCLCPP_WARN_THROTTLE(node_->get_logger(), *node_->get_clock(), 500,
      "RPP: arc collision (clearance=%.3f m) → stop", arc_clearance);
  } else if (arc_clearance < params_.slowdown_dist) {
    const double obs_scale = std::clamp(
      arc_clearance / params_.slowdown_dist, 0.0, 1.0);
    // slowdown 구간에서 최소 min_speed_ratio 유지 (완전 정지는 clearance<=0만)
    v *= std::max(obs_scale, params_.regulated_linear_scaling_min_speed);
  }

  return std::clamp(v, 0.0, params_.max_linear_vel);
}

// ============================================================
// isGoalReached
// ============================================================
bool LocalPlanner::isGoalReached(const geometry_msgs::msg::PoseStamped& current_pose) const
{
  std::lock_guard<std::mutex> lock(path_mutex_);
  if (path_.poses.empty()) return true;

  const auto& goal = path_.poses.back();
  const double dx  = goal.pose.position.x - current_pose.pose.position.x;
  const double dy  = goal.pose.position.y - current_pose.pose.position.y;
  if (std::hypot(dx, dy) > params_.goal_tolerance_xy) return false;

  return std::abs(normalizeAngle(
    tf2::getYaw(goal.pose.orientation) -
    tf2::getYaw(current_pose.pose.orientation))) < params_.goal_tolerance_yaw;
}

// ============================================================
// 경로 추종 헬퍼
// ============================================================
void LocalPlanner::updateClosestIndex(double robot_x, double robot_y)
{
  if (path_.poses.empty()) return;

  const int window = 20;
  const int start  = std::max(0, static_cast<int>(closest_idx_) - window);
  const int end    = std::min(static_cast<int>(path_.poses.size()),
                              static_cast<int>(closest_idx_) + window);

  double min_dist = std::numeric_limits<double>::max();
  size_t best_idx = closest_idx_;

  for (int i = start; i < end; ++i) {
    const double d = std::hypot(
      path_.poses[i].pose.position.x - robot_x,
      path_.poses[i].pose.position.y - robot_y);
    if (d < min_dist) { min_dist = d; best_idx = static_cast<size_t>(i); }
  }
  closest_idx_ = best_idx;
}

bool LocalPlanner::findLookaheadPoint(const geometry_msgs::msg::PoseStamped& current_pose,
                                       geometry_msgs::msg::PoseStamped& lookahead_point)
{
  if (path_.poses.empty()) return false;

  const double robot_x = current_pose.pose.position.x;
  const double robot_y = current_pose.pose.position.y;

  updateClosestIndex(robot_x, robot_y);

  const double ld = computeLookahead(last_linear_cmd_);

  for (size_t i = closest_idx_; i < path_.poses.size(); ++i) {
    const double d = std::hypot(
      path_.poses[i].pose.position.x - robot_x,
      path_.poses[i].pose.position.y - robot_y);
    if (d >= ld) { lookahead_point = path_.poses[i]; return true; }
  }

  lookahead_point = path_.poses.back();
  return true;
}

double LocalPlanner::computeLookahead(double linear_vel) const
{
  return std::clamp(
    params_.lookahead_distance + params_.lookahead_gain * std::abs(linear_vel),
    params_.min_lookahead, params_.max_lookahead);
}

double LocalPlanner::getMinFrontDistance() const
{
  sensor_msgs::msg::LaserScan::SharedPtr scan;
  { std::lock_guard<std::mutex> lock(scan_mutex_); scan = latest_scan_; }
  if (!scan) return 100.0;

  double min_dist = 100.0;
  double angle    = scan->angle_min;
  for (size_t i = 0; i < scan->ranges.size(); ++i, angle += scan->angle_increment) {
    if (std::abs(std::atan2(std::sin(angle), std::cos(angle)))
        > params_.front_obstacle_half_angle) continue;
    const double r = scan->ranges[i];
    if (std::isnan(r) || std::isinf(r)) continue;
    if (r < scan->range_min || r > scan->range_max) continue;
    if (r < min_dist) min_dist = r;
  }
  return min_dist;
}

double LocalPlanner::computeGoalSpeedScale(double dist_to_goal) const
{
  if (dist_to_goal >= params_.goal_slowdown_dist) return 1.0;
  return std::clamp(dist_to_goal / std::max(1e-6, params_.goal_slowdown_dist), 0.15, 1.0);
}

double LocalPlanner::normalizeAngle(double angle) const
{
  return std::atan2(std::sin(angle), std::cos(angle));
}

double LocalPlanner::applyMinRotateSpeed(double w) const
{
  if (std::abs(w) < 1e-6) return 0.0;
  if (std::abs(w) < params_.min_rotate_speed)
    return (w > 0.0) ? params_.min_rotate_speed : -params_.min_rotate_speed;
  return w;
}

}  // namespace hospital_nav
