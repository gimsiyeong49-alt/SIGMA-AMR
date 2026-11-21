#include "hospital_nav/navigation_node.hpp"

#include <tf2/utils.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.h>

#include <algorithm>
#include <chrono>
#include <cmath>

using namespace std::chrono_literals;

namespace hospital_nav
{

namespace
{

const char* failureReasonToString(FailureReason reason)
{
  switch (reason) {
    case FailureReason::PLANNING_FAILED: return "PLANNING_FAILED";
    case FailureReason::PATH_LOST:       return "PATH_LOST";
    case FailureReason::STUCK:           return "STUCK";
    case FailureReason::OSCILLATION:     return "OSCILLATION";
    case FailureReason::NONE:
    default:                             return "NONE";
  }
}

const char* recoveryActionToString(RecoveryAction action)
{
  switch (action) {
    case RecoveryAction::IGNORE_AND_KEEP_MOVING: return "IGNORE_AND_KEEP_MOVING";
    case RecoveryAction::REPLAN_ONLY:            return "REPLAN_ONLY";
    case RecoveryAction::BACKUP_AND_RETRY:       return "BACKUP_AND_RETRY";
    case RecoveryAction::SPIN_AND_RETRY:         return "SPIN_AND_RETRY";
    case RecoveryAction::ABORT_TO_IDLE:          return "ABORT_TO_IDLE";
    case RecoveryAction::NONE:
    default:                                     return "NONE";
  }
}

}  // namespace

NavigationNode::NavigationNode(const rclcpp::NodeOptions& options)
  : rclcpp::Node("navigation_node", options)
{
  RCLCPP_INFO(get_logger(), "=== Hospital Navigation Node Starting ===");

  loadParameters();

  tf_buffer_   = std::make_shared<tf2_ros::Buffer>(get_clock());
  tf_listener_ = std::make_shared<tf2_ros::TransformListener>(*tf_buffer_);

  CostmapParams cm_params;
  cm_params.resolution       = get_parameter("costmap_resolution").as_double();
  cm_params.inflation_radius = get_parameter("inflation_radius").as_double();
  cm_params.inscribed_radius = get_parameter("inscribed_radius").as_double();
  cm_params.cost_scaling     = get_parameter("cost_scaling_factor").as_double();
  cm_params.obstacle_range   = get_parameter("obstacle_range").as_double();
  cm_params.raytrace_range   = get_parameter("raytrace_range").as_double();
  cm_params.global_frame     = global_frame_;
  cm_params.robot_frame      = robot_frame_;
  costmap_ = std::make_shared<Costmap>(this, tf_buffer_, cm_params);

  planner_frequency_ = get_parameter("planner_frequency").as_double();
  replan_frequency_  = get_parameter("replan_frequency").as_double();

  PlannerParams gp_params;
  gp_params.allow_unknown = get_parameter("allow_unknown").as_bool();
  gp_params.planner_freq  = planner_frequency_;
  gp_params.global_frame  = global_frame_;
  global_planner_ = std::make_shared<GlobalPlanner>(this, costmap_, gp_params);

  LocalPlannerParams lp_params;
  lp_params.lookahead_distance          = get_parameter("lookahead_distance").as_double();
  lp_params.lookahead_gain              = get_parameter("lookahead_gain").as_double();
  lp_params.min_lookahead               = get_parameter("min_lookahead").as_double();
  lp_params.max_lookahead               = get_parameter("max_lookahead").as_double();
  lp_params.max_linear_vel              = get_parameter("max_linear_vel").as_double();
  lp_params.min_linear_vel              = get_parameter("min_linear_vel").as_double();
  lp_params.max_angular_vel             = get_parameter("max_angular_vel").as_double();
  lp_params.goal_tolerance_xy           = get_parameter("goal_tolerance_xy").as_double();
  lp_params.goal_tolerance_yaw          = get_parameter("goal_tolerance_yaw").as_double();
  lp_params.controller_freq             = controller_freq_;
  lp_params.emergency_stop_dist         = get_parameter("emergency_stop_distance").as_double();
  lp_params.slowdown_dist               = get_parameter("slowdown_distance").as_double();
  lp_params.rotate_in_place_enter_angle = get_parameter("rotate_in_place_enter_angle").as_double();
  lp_params.rotate_in_place_exit_angle  = get_parameter("rotate_in_place_exit_angle").as_double();
  lp_params.goal_slowdown_dist          = get_parameter("goal_slowdown_distance").as_double();
  lp_params.final_yaw_align_gain        = get_parameter("final_yaw_align_gain").as_double();
  lp_params.min_rotate_speed            = get_parameter("min_rotate_speed").as_double();
  lp_params.front_obstacle_half_angle   = get_parameter("front_obstacle_half_angle").as_double();
  lp_params.curvature_low_threshold     = get_parameter("curvature_low_threshold").as_double();
  lp_params.curvature_high_threshold    = get_parameter("curvature_high_threshold").as_double();
  lp_params.curvature_min_scale         = get_parameter("curvature_min_scale").as_double();
  lp_params.robot_frame                 = robot_frame_;
  lp_params.regulated_linear_scaling_min_radius = get_parameter("regulated_linear_scaling_min_radius").as_double();
  lp_params.regulated_linear_scaling_min_speed  = get_parameter("regulated_linear_scaling_min_speed").as_double();
  lp_params.use_arc_collision_check             = get_parameter("use_arc_collision_check").as_bool();
  lp_params.arc_check_samples                   = static_cast<int>(get_parameter("arc_check_samples").as_int());
  lp_params.arc_check_robot_radius              = get_parameter("arc_check_robot_radius").as_double();
  local_planner_ = std::make_shared<LocalPlanner>(this, lp_params);

  recovery_backup_dist_ = get_parameter("recovery_backup_dist").as_double();
  recovery_backup_vel_  = get_parameter("recovery_backup_vel").as_double();
  recovery_spin_angle_  = get_parameter("recovery_spin_angle").as_double();
  recovery_spin_vel_    = get_parameter("recovery_spin_vel").as_double();

  RecoveryManagerParams rm_params;
  rm_params.max_recovery_attempts             = static_cast<int>(get_parameter("max_recovery_attempts").as_int());
  rm_params.near_goal_distance                = get_parameter("recovery_near_goal_distance").as_double();
  rm_params.very_near_goal_distance           = get_parameter("recovery_very_near_goal_distance").as_double();
  rm_params.oscillation_ignore_distance       = get_parameter("recovery_oscillation_ignore_distance").as_double();
  rm_params.disable_replan_near_goal_distance = get_parameter("disable_replan_near_goal_distance").as_double();
  rm_params.backup_timeout                    = get_parameter("recovery_backup_timeout").as_double();
  rm_params.spin_timeout                      = get_parameter("recovery_spin_timeout").as_double();
  recovery_manager_ = std::make_unique<RecoveryManager>(rm_params);

  stuck_timeout_            = get_parameter("stuck_timeout").as_double();
  stuck_vel_threshold_      = get_parameter("stuck_velocity_threshold").as_double();
  stuck_distance_threshold_ = get_parameter("stuck_distance_threshold").as_double();
  stuck_yaw_threshold_      = get_parameter("stuck_yaw_threshold").as_double();

  oscillation_timeout_  = get_parameter("oscillation_timeout").as_double();
  oscillation_distance_ = get_parameter("oscillation_distance").as_double();

  amcl_cov_x_threshold_   = get_parameter("amcl_cov_x_threshold").as_double();
  amcl_cov_y_threshold_   = get_parameter("amcl_cov_y_threshold").as_double();
  amcl_cov_yaw_threshold_ = get_parameter("amcl_cov_yaw_threshold").as_double();
  amcl_pose_timeout_      = get_parameter("amcl_pose_timeout").as_double();

  localization_min_samples_ = static_cast<int>(get_parameter("localization_min_samples").as_int());
  costmap_warmup_cycles_    = static_cast<int>(get_parameter("costmap_warmup_cycles").as_int());
  costmap_warmup_remaining_ = costmap_warmup_cycles_;

  setupSubscribers();
  setupPublishers();
  setupTimers();

  last_moving_time_        = now();
  last_pose_check_time_    = now();
  last_replan_time_        = now();
  last_amcl_pose_time_     = now();
  recovery_start_time_     = now();
  last_planning_attempt_time_ =
    now() - rclcpp::Duration::from_seconds(planner_frequency_ > 0.0 ? (1.0 / planner_frequency_) : 1.0);

  RCLCPP_INFO(get_logger(), "=== Hospital Navigation Node Ready ===");
  RCLCPP_INFO(get_logger(), "  global_frame: %s", global_frame_.c_str());
  RCLCPP_INFO(get_logger(), "  robot_frame:  %s", robot_frame_.c_str());
  RCLCPP_INFO(get_logger(), "  controller:   %.1f Hz", controller_freq_);
  RCLCPP_INFO(get_logger(), "  planner:      %.2f Hz", planner_frequency_);
  RCLCPP_INFO(get_logger(), "  replan:       %.2f Hz", replan_frequency_);
  RCLCPP_INFO(get_logger(), "  Initial state: WAIT_LOCALIZATION");
}

void NavigationNode::loadParameters()
{
  global_frame_ = declare_parameter("global_frame", std::string("map"));
  odom_frame_   = declare_parameter("odom_frame", std::string("odom"));
  robot_frame_  = declare_parameter("robot_frame", std::string("base_footprint"));

  declare_parameter("map_topic", std::string("/map"));
  declare_parameter("scan_topic", std::string("/scan_multi"));

  declare_parameter("costmap_resolution", 0.05);
  declare_parameter("inflation_radius", 0.75);
  declare_parameter("inscribed_radius", 0.45);
  declare_parameter("cost_scaling_factor", 3.0);
  declare_parameter("obstacle_range", 5.0);
  declare_parameter("raytrace_range", 6.0);

  declare_parameter("allow_unknown", false);
  declare_parameter("planner_frequency", 1.0);
  declare_parameter("replan_frequency", 0.2);

  declare_parameter("lookahead_distance", 0.35);
  declare_parameter("lookahead_gain", 0.3);
  declare_parameter("min_lookahead", 0.30);
  declare_parameter("max_lookahead", 0.80);
  declare_parameter("max_linear_vel", 0.4);
  declare_parameter("min_linear_vel", 0.05);
  declare_parameter("max_angular_vel", 1.0);
  declare_parameter("goal_tolerance_xy", 0.25);
  declare_parameter("goal_tolerance_yaw", 0.30);
  controller_freq_ = declare_parameter("controller_frequency", 20.0);

  declare_parameter("rotate_in_place_enter_angle", 1.0);
  declare_parameter("rotate_in_place_exit_angle", 0.30);
  declare_parameter("goal_slowdown_distance", 1.20);
  declare_parameter("final_yaw_align_gain", 1.5);
  declare_parameter("min_rotate_speed", 0.15);
  declare_parameter("front_obstacle_half_angle", 0.35);

  declare_parameter("regulated_linear_scaling_min_radius", 0.9);
  declare_parameter("regulated_linear_scaling_min_speed",  0.25);
  declare_parameter("use_arc_collision_check",             true);
  declare_parameter("arc_check_samples",                   6);
  declare_parameter("arc_check_robot_radius",              0.45);

  declare_parameter("curvature_low_threshold", 0.1);
  declare_parameter("curvature_high_threshold", 1.5);
  declare_parameter("curvature_min_scale", 0.4);

  declare_parameter("emergency_stop_distance", 0.20);
  declare_parameter("slowdown_distance", 1.20);

  declare_parameter("max_recovery_attempts", 2);
  declare_parameter("recovery_backup_dist", 0.18);
  declare_parameter("recovery_backup_vel", -0.08);
  declare_parameter("recovery_spin_angle", 0.785398);
  declare_parameter("recovery_spin_vel", 0.35);

  declare_parameter("recovery_near_goal_distance", 0.80);
  declare_parameter("recovery_very_near_goal_distance", 0.35);
  declare_parameter("recovery_oscillation_ignore_distance", 0.80);
  declare_parameter("disable_replan_near_goal_distance", 0.90);
  declare_parameter("recovery_backup_timeout", 1.8);
  declare_parameter("recovery_spin_timeout", 2.5);

  declare_parameter("stuck_timeout", 6.0);
  declare_parameter("stuck_velocity_threshold", 0.02);
  declare_parameter("stuck_distance_threshold", 0.05);
  declare_parameter("stuck_yaw_threshold", 0.15);

  declare_parameter("oscillation_timeout", 20.0);
  declare_parameter("oscillation_distance", 0.10);

  declare_parameter("amcl_cov_x_threshold", 0.05);
  declare_parameter("amcl_cov_y_threshold", 0.05);
  declare_parameter("amcl_cov_yaw_threshold", 0.10);
  declare_parameter("localization_min_samples", 5);
  declare_parameter("costmap_warmup_cycles", 3);
  declare_parameter("amcl_pose_timeout", 2.0);
}

void NavigationNode::setupSubscribers()
{
  goal_sub_ = create_subscription<geometry_msgs::msg::PoseStamped>(
    "/goal_pose",
    rclcpp::QoS(1),
    std::bind(&NavigationNode::goalCallback, this, std::placeholders::_1));

  const std::string map_topic = get_parameter("map_topic").as_string();
  map_sub_ = create_subscription<nav_msgs::msg::OccupancyGrid>(
    map_topic,
    rclcpp::QoS(1).transient_local().reliable(),
    std::bind(&NavigationNode::mapCallback, this, std::placeholders::_1));

  const std::string scan_topic = get_parameter("scan_topic").as_string();
  scan_sub_ = create_subscription<sensor_msgs::msg::LaserScan>(
    scan_topic,
    rclcpp::SensorDataQoS(),
    std::bind(&NavigationNode::scanCallback, this, std::placeholders::_1));

  amcl_pose_sub_ = create_subscription<geometry_msgs::msg::PoseWithCovarianceStamped>(
    "/amcl_pose",
    rclcpp::QoS(10),
    std::bind(&NavigationNode::amclPoseCallback, this, std::placeholders::_1));
}

void NavigationNode::setupPublishers()
{
  cmd_vel_pub_ = create_publisher<geometry_msgs::msg::Twist>("/cmd_vel", 10);
  global_path_pub_ = create_publisher<nav_msgs::msg::Path>("/global_path", 10);
  costmap_pub_ = create_publisher<nav_msgs::msg::OccupancyGrid>(
    "/hospital_nav/costmap", rclcpp::QoS(1).transient_local());
  state_pub_ = create_publisher<std_msgs::msg::String>("/hospital_nav/state", 10);
  marker_pub_ = create_publisher<visualization_msgs::msg::Marker>("/hospital_nav/markers", 10);
}

void NavigationNode::setupTimers()
{
  const auto control_period = std::chrono::duration<double>(1.0 / controller_freq_);
  control_timer_ = create_wall_timer(
    std::chrono::duration_cast<std::chrono::nanoseconds>(control_period),
    std::bind(&NavigationNode::controlLoop, this));

  costmap_timer_ = create_wall_timer(100ms, std::bind(&NavigationNode::costmapLoop, this));
}

void NavigationNode::goalCallback(const geometry_msgs::msg::PoseStamped::SharedPtr msg)
{
  RCLCPP_INFO(get_logger(),
              "Goal received: (%.2f, %.2f, yaw=%.2f)",
              msg->pose.position.x,
              msg->pose.position.y,
              tf2::getYaw(msg->pose.orientation));

  current_goal_ = *msg;
  if (current_goal_.header.frame_id.empty()) {
    current_goal_.header.frame_id = global_frame_;
  }

  goal_received_ = true;
  recovery_count_ = 0;
  current_recovery_action_ = RecoveryAction::NONE;
  current_recovery_timeout_ = 0.0;
  stuck_tracking_initialized_ = false;
  resetOscillationTracking();

  last_planning_attempt_time_ =
    now() - rclcpp::Duration::from_seconds(planner_frequency_ > 0.0 ? (1.0 / planner_frequency_) : 1.0);

  if (!navigation_enabled_) {
    RCLCPP_INFO(get_logger(), "Goal stored. Waiting for stable localization first.");
    return;
  }

  transitionTo(NavState::PLANNING);
}

void NavigationNode::mapCallback(const nav_msgs::msg::OccupancyGrid::SharedPtr msg)
{
  costmap_->mapCallback(msg);
}

void NavigationNode::scanCallback(const sensor_msgs::msg::LaserScan::SharedPtr msg)
{
  costmap_->scanCallback(msg);
  local_planner_->updateScanData(msg);
}

void NavigationNode::amclPoseCallback(
  const geometry_msgs::msg::PoseWithCovarianceStamped::SharedPtr msg)
{
  amcl_pose_received_ = true;
  last_amcl_pose_time_ = now();

  const bool reliable = isLocalizationReliable(*msg);

  if (!navigation_enabled_) {
    if (reliable) {
      ++stable_localization_count_;

      if (!localization_ready_ &&
          stable_localization_count_ >= std::max(1, localization_min_samples_)) {
        localization_ready_ = true;
        costmap_warmup_remaining_ = std::max(0, costmap_warmup_cycles_);

        RCLCPP_INFO(get_logger(),
                    "Localization converged. Starting costmap warmup (%d cycles).",
                    costmap_warmup_remaining_);
      }
    } else {
      stable_localization_count_ = 0;
      localization_ready_ = false;
      costmap_warmup_remaining_ = std::max(0, costmap_warmup_cycles_);
    }
  }
}

void NavigationNode::costmapLoop()
{
  if (!costmap_->isMapReceived()) {
    return;
  }

  if (!navigation_enabled_) {
    if (localization_ready_ && costmap_warmup_remaining_ > 0) {
      costmap_->update();
      --costmap_warmup_remaining_;
    }
    return;
  }

  costmap_->update();
  publishCostmap();
}

void NavigationNode::controlLoop()
{
  publishState();

  if (navigation_enabled_ && isAmclTimedOut()) {
    RCLCPP_WARN(get_logger(),
                "AMCL pose timed out. Returning to WAIT_LOCALIZATION.");
    resetLocalizationState(false);
    transitionTo(NavState::WAIT_LOCALIZATION);
    return;
  }

  switch (state_) {
    case NavState::WAIT_LOCALIZATION: handleWaitLocalization(); break;
    case NavState::IDLE:              handleIdle();             break;
    case NavState::PLANNING:          handlePlanning();         break;
    case NavState::MOVING:            handleMoving();           break;
    case NavState::ARRIVED:           handleArrived();          break;
    case NavState::RECOVERY:          handleRecovery();         break;
  }
}

void NavigationNode::transitionTo(NavState new_state)
{
  if (state_ == new_state) {
    return;
  }

  RCLCPP_INFO(get_logger(),
              "FSM: %s -> %s",
              stateToString(state_).c_str(),
              stateToString(new_state).c_str());

  if (state_ == NavState::RECOVERY && new_state != NavState::RECOVERY) {
    current_recovery_action_ = RecoveryAction::NONE;
    current_recovery_timeout_ = 0.0;
  }

  if (new_state == NavState::PLANNING) {
    last_planning_attempt_time_ =
      now() - rclcpp::Duration::from_seconds(planner_frequency_ > 0.0 ? (1.0 / planner_frequency_) : 1.0);
  }

  if (new_state == NavState::RECOVERY) {
    geometry_msgs::msg::PoseStamped current_pose;
    if (getRobotPose(current_pose)) {
      recovery_start_pose_ = current_pose;
      recovery_spin_start_yaw_ = tf2::getYaw(current_pose.pose.orientation);
      resetStuckTracking(current_pose);
    }
    recovery_start_time_ = now();

    RCLCPP_WARN(get_logger(),
                "RECOVERY action=%s attempt=%d timeout=%.2fs",
                recoveryActionToString(current_recovery_action_),
                recovery_count_,
                current_recovery_timeout_);
  }

  if (new_state == NavState::MOVING) {
    last_replan_time_ = now();
    resetOscillationTracking();
  }

  state_ = new_state;
}

void NavigationNode::handleWaitLocalization()
{
  publishZeroVelocity();

  if (!costmap_->isMapReceived()) {
    RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 3000,
                         "WAIT_LOCALIZATION: waiting for map...");
    return;
  }

  if (!amcl_pose_received_) {
    RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 3000,
                         "WAIT_LOCALIZATION: waiting for /amcl_pose...");
    return;
  }

  if (!localization_ready_) {
    RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 3000,
                         "WAIT_LOCALIZATION: waiting for stable AMCL covariance...");
    return;
  }

  if (costmap_warmup_remaining_ > 0) {
    RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 3000,
                         "WAIT_LOCALIZATION: costmap warmup in progress (%d cycles left)...",
                         costmap_warmup_remaining_);
    return;
  }

  navigation_enabled_ = true;

  RCLCPP_INFO(get_logger(), "Localization ready. Navigation enabled.");

  if (goal_received_) {
    transitionTo(NavState::PLANNING);
  } else {
    transitionTo(NavState::IDLE);
  }
}

void NavigationNode::handleIdle()
{
  publishZeroVelocity();
}

void NavigationNode::handlePlanning()
{
  if (!navigation_enabled_) {
    transitionTo(NavState::WAIT_LOCALIZATION);
    return;
  }

  if (!goal_received_) {
    publishZeroVelocity();
    transitionTo(NavState::IDLE);
    return;
  }

  const double planning_period = (planner_frequency_ > 0.0) ? (1.0 / planner_frequency_) : 0.0;
  if (planning_period > 0.0 &&
      (now() - last_planning_attempt_time_).seconds() < planning_period) {
    publishZeroVelocity();
    return;
  }
  last_planning_attempt_time_ = now();

  if (!costmap_->isMapReceived()) {
    RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 3000,
                         "PLANNING: waiting for map...");
    publishZeroVelocity();
    return;
  }

  geometry_msgs::msg::PoseStamped current_pose;
  if (!getRobotPose(current_pose)) {
    RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000,
                         "PLANNING: cannot get robot pose (TF missing)");
    publishZeroVelocity();
    return;
  }

  nav_msgs::msg::Path path;
  if (global_planner_->makePlan(current_pose, current_goal_, path)) {
    current_path_ = path;
    global_path_pub_->publish(path);
    publishPathMarker(path);
    local_planner_->setPath(path);
    resetStuckTracking(current_pose);
    last_moving_time_ = now();
    transitionTo(NavState::MOVING);
    return;
  }

  publishZeroVelocity();
  handleFailure(FailureReason::PLANNING_FAILED,
                current_pose,
                distanceToGoal(current_pose),
                headingErrorToGoal(current_pose));
}

void NavigationNode::handleMoving()
{
  if (!navigation_enabled_) {
    publishZeroVelocity();
    transitionTo(NavState::WAIT_LOCALIZATION);
    return;
  }

  geometry_msgs::msg::PoseStamped current_pose;
  if (!getRobotPose(current_pose)) {
    publishZeroVelocity();
    return;
  }

  const double dist_to_goal = distanceToGoal(current_pose);
  const double heading_error = headingErrorToGoal(current_pose);

  if (local_planner_->isGoalReached(current_pose)) {
    publishZeroVelocity();
    transitionTo(NavState::ARRIVED);
    return;
  }

  if (replan_frequency_ > 0.0 &&
      dist_to_goal > recovery_manager_->params().disable_replan_near_goal_distance) {
    const double replan_period = 1.0 / replan_frequency_;
    if ((now() - last_replan_time_).seconds() > replan_period) {
      nav_msgs::msg::Path new_path;
      if (global_planner_->makePlan(current_pose, current_goal_, new_path)) {
        current_path_ = new_path;
        global_path_pub_->publish(new_path);
        publishPathMarker(new_path);
        local_planner_->updatePath(new_path);
      }
      last_replan_time_ = now();
    }
  }

  geometry_msgs::msg::Twist cmd_vel;
  if (!local_planner_->computeVelocity(current_pose, cmd_vel)) {
    if (local_planner_->isGoalReached(current_pose)) {
      publishZeroVelocity();
      transitionTo(NavState::ARRIVED);
    } else {
      publishZeroVelocity();
      handleFailure(FailureReason::PATH_LOST, current_pose, dist_to_goal, heading_error);
    }
    return;
  }

  cmd_vel_pub_->publish(cmd_vel);

  if (std::abs(cmd_vel.linear.x) > stuck_vel_threshold_ ||
      std::abs(cmd_vel.angular.z) > stuck_vel_threshold_) {
    last_moving_time_ = now();
  }

  const bool stuck = isStuck(current_pose, cmd_vel);
  const bool oscillating = (!stuck) ? isOscillating(current_pose) : false;

  if (stuck) {
    publishZeroVelocity();
    handleFailure(FailureReason::STUCK, current_pose, dist_to_goal, heading_error);
    return;
  }

  if (oscillating) {
    publishZeroVelocity();
    handleFailure(FailureReason::OSCILLATION, current_pose, dist_to_goal, heading_error);
    return;
  }
}

void NavigationNode::handleArrived()
{
  publishZeroVelocity();

  RCLCPP_INFO(get_logger(), "========================================");
  RCLCPP_INFO(get_logger(), "  ARRIVED at goal (%.2f, %.2f)",
              current_goal_.pose.position.x,
              current_goal_.pose.position.y);
  RCLCPP_INFO(get_logger(), "========================================");

  current_path_.poses.clear();
  local_planner_->clearPath();
  goal_received_ = false;
  recovery_count_ = 0;
  current_recovery_action_ = RecoveryAction::NONE;
  current_recovery_timeout_ = 0.0;
  stuck_tracking_initialized_ = false;
  resetOscillationTracking();
  clearPublishedArtifacts();

  transitionTo(NavState::IDLE);
}

void NavigationNode::handleRecovery()
{
  if (!navigation_enabled_) {
    publishZeroVelocity();
    transitionTo(NavState::WAIT_LOCALIZATION);
    return;
  }

  if (current_recovery_action_ == RecoveryAction::NONE) {
    transitionTo(NavState::PLANNING);
    return;
  }

  geometry_msgs::msg::PoseStamped current_pose;
  if (!getRobotPose(current_pose)) {
    publishZeroVelocity();
    transitionTo(NavState::IDLE);
    return;
  }

  if (current_recovery_timeout_ > 0.0 &&
      (now() - recovery_start_time_).seconds() > current_recovery_timeout_) {
    RCLCPP_WARN(get_logger(),
                "RECOVERY: action %s timed out after %.2fs -> replan",
                recoveryActionToString(current_recovery_action_),
                current_recovery_timeout_);
    publishZeroVelocity();
    local_planner_->clearPath();
    resetStuckTracking(current_pose);
    resetOscillationTracking();
    current_recovery_action_ = RecoveryAction::NONE;
    current_recovery_timeout_ = 0.0;
    transitionTo(NavState::PLANNING);
    return;
  }

  switch (current_recovery_action_) {
    case RecoveryAction::BACKUP_AND_RETRY: {
      const double backed = std::hypot(
        current_pose.pose.position.x - recovery_start_pose_.pose.position.x,
        current_pose.pose.position.y - recovery_start_pose_.pose.position.y);

      if (backed < recovery_backup_dist_) {
        geometry_msgs::msg::Twist backup_cmd;
        backup_cmd.linear.x = recovery_backup_vel_;
        cmd_vel_pub_->publish(backup_cmd);
        return;
      }

      publishZeroVelocity();
      local_planner_->clearPath();
      resetStuckTracking(current_pose);
      resetOscillationTracking();
      current_recovery_action_ = RecoveryAction::NONE;
      current_recovery_timeout_ = 0.0;
      transitionTo(NavState::PLANNING);
      return;
    }

    case RecoveryAction::SPIN_AND_RETRY: {
      const double current_yaw = tf2::getYaw(current_pose.pose.orientation);
      const double yaw_delta = std::abs(
        normalizeAngle(current_yaw - recovery_spin_start_yaw_));

      if (yaw_delta < recovery_spin_angle_) {
        geometry_msgs::msg::Twist spin_cmd;
        const double spin_dir = (recovery_count_ % 2 == 0) ? -1.0 : 1.0;
        spin_cmd.angular.z = spin_dir * recovery_spin_vel_;
        cmd_vel_pub_->publish(spin_cmd);
        return;
      }

      publishZeroVelocity();
      local_planner_->clearPath();
      resetStuckTracking(current_pose);
      resetOscillationTracking();
      current_recovery_action_ = RecoveryAction::NONE;
      current_recovery_timeout_ = 0.0;
      transitionTo(NavState::PLANNING);
      return;
    }

    case RecoveryAction::REPLAN_ONLY:
    case RecoveryAction::IGNORE_AND_KEEP_MOVING:
    case RecoveryAction::ABORT_TO_IDLE:
    case RecoveryAction::NONE:
    default:
      publishZeroVelocity();
      current_recovery_action_ = RecoveryAction::NONE;
      current_recovery_timeout_ = 0.0;
      transitionTo(NavState::PLANNING);
      return;
  }
}

void NavigationNode::handleFailure(FailureReason reason,
                                   const geometry_msgs::msg::PoseStamped& current_pose,
                                   double dist_to_goal,
                                   double heading_error)
{
  RecoveryContext ctx;
  ctx.reason = reason;
  ctx.dist_to_goal = dist_to_goal;
  ctx.heading_error = heading_error;
  ctx.recovery_count = recovery_count_;
  ctx.localization_ok = navigation_enabled_;
  ctx.goal_received = goal_received_;

  const RecoveryDecision decision = recovery_manager_->decide(ctx);

  RCLCPP_WARN(get_logger(),
              "Failure %s -> %s (dist=%.2f, recovery_count=%d, why=%s)",
              failureReasonToString(reason),
              recoveryActionToString(decision.action),
              dist_to_goal,
              recovery_count_,
              decision.reason_text.c_str());

  switch (decision.action) {
    case RecoveryAction::IGNORE_AND_KEEP_MOVING:
      if (reason == FailureReason::OSCILLATION) {
        resetOscillationTracking();
      }
      if (reason == FailureReason::STUCK) {
        resetStuckTracking(current_pose);
      }
      return;

    case RecoveryAction::REPLAN_ONLY:
      if (decision.consume_attempt) {
        ++recovery_count_;
      }
      publishZeroVelocity();
      local_planner_->clearPath();
      current_path_.poses.clear();
      clearPublishedArtifacts();
      resetOscillationTracking();
      resetStuckTracking(current_pose);

      if (state_ == NavState::PLANNING) {
        last_planning_attempt_time_ = now();
      } else {
        transitionTo(NavState::PLANNING);
      }
      return;

    case RecoveryAction::BACKUP_AND_RETRY:
    case RecoveryAction::SPIN_AND_RETRY:
      if (decision.consume_attempt) {
        ++recovery_count_;
      }
      publishZeroVelocity();
      current_recovery_action_ = decision.action;
      current_recovery_timeout_ = decision.action_timeout;
      transitionTo(NavState::RECOVERY);
      return;

    case RecoveryAction::ABORT_TO_IDLE:
      publishZeroVelocity();
      goal_received_ = false;
      recovery_count_ = 0;
      current_recovery_action_ = RecoveryAction::NONE;
      current_recovery_timeout_ = 0.0;
      current_path_.poses.clear();
      local_planner_->clearPath();
      clearPublishedArtifacts();
      resetOscillationTracking();
      resetStuckTracking(current_pose);
      transitionTo(NavState::IDLE);
      return;

    case RecoveryAction::NONE:
    default:
      return;
  }
}

bool NavigationNode::getRobotPose(geometry_msgs::msg::PoseStamped& pose)
{
  try {
    const auto tf = tf_buffer_->lookupTransform(
      global_frame_, robot_frame_, tf2::TimePointZero, tf2::durationFromSec(0.2));

    pose.header.stamp = tf.header.stamp;
    pose.header.frame_id = global_frame_;
    pose.pose.position.x = tf.transform.translation.x;
    pose.pose.position.y = tf.transform.translation.y;
    pose.pose.position.z = tf.transform.translation.z;
    pose.pose.orientation = tf.transform.rotation;
    return true;
  } catch (const tf2::TransformException& ex) {
    RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000,
                         "getRobotPose: %s", ex.what());
    return false;
  }
}

bool NavigationNode::isStuck(const geometry_msgs::msg::PoseStamped& current_pose,
                             const geometry_msgs::msg::Twist& commanded_vel)
{
  const bool commanding_motion =
    (std::abs(commanded_vel.linear.x) > stuck_vel_threshold_) ||
    (std::abs(commanded_vel.angular.z) > stuck_vel_threshold_);

  if (!commanding_motion) {
    resetStuckTracking(current_pose);
    return false;
  }

  if (!stuck_tracking_initialized_) {
    resetStuckTracking(current_pose);
    return false;
  }

  const double dist = std::hypot(
    current_pose.pose.position.x - last_pose_for_stuck_.pose.position.x,
    current_pose.pose.position.y - last_pose_for_stuck_.pose.position.y);

  const double current_yaw = tf2::getYaw(current_pose.pose.orientation);
  const double last_yaw    = tf2::getYaw(last_pose_for_stuck_.pose.orientation);
  const double yaw_delta   = std::abs(normalizeAngle(current_yaw - last_yaw));

  if (dist > stuck_distance_threshold_ || yaw_delta > stuck_yaw_threshold_) {
    resetStuckTracking(current_pose);
    return false;
  }

  return (now() - last_pose_check_time_).seconds() > stuck_timeout_;
}

void NavigationNode::resetStuckTracking(const geometry_msgs::msg::PoseStamped& current_pose)
{
  last_pose_for_stuck_ = current_pose;
  last_pose_check_time_ = now();
  stuck_tracking_initialized_ = true;
}

bool NavigationNode::isOscillating(const geometry_msgs::msg::PoseStamped& current_pose)
{
  const auto now_time = now();

  pose_history_.push_back({
    current_pose.pose.position.x,
    current_pose.pose.position.y,
    now_time
  });

  while (!pose_history_.empty() &&
         (now_time - pose_history_.front().stamp).seconds() > oscillation_timeout_) {
    pose_history_.pop_front();
  }

  if (pose_history_.size() < 10 ||
      (now_time - pose_history_.front().stamp).seconds() < oscillation_timeout_ * 0.8) {
    return false;
  }

  double cx = 0.0, cy = 0.0;
  for (const auto& rec : pose_history_) {
    cx += rec.x;
    cy += rec.y;
  }
  cx /= static_cast<double>(pose_history_.size());
  cy /= static_cast<double>(pose_history_.size());

  for (const auto& rec : pose_history_) {
    if (std::hypot(rec.x - cx, rec.y - cy) > oscillation_distance_) {
      return false;
    }
  }

  return true;
}

void NavigationNode::resetOscillationTracking()
{
  pose_history_.clear();
}

bool NavigationNode::isLocalizationReliable(
  const geometry_msgs::msg::PoseWithCovarianceStamped& msg) const
{
  const double var_x   = msg.pose.covariance[0];
  const double var_y   = msg.pose.covariance[7];
  const double var_yaw = msg.pose.covariance[35];

  return (var_x >= 0.0 && var_x <= amcl_cov_x_threshold_) &&
         (var_y >= 0.0 && var_y <= amcl_cov_y_threshold_) &&
         (var_yaw >= 0.0 && var_yaw <= amcl_cov_yaw_threshold_);
}

bool NavigationNode::isAmclTimedOut() const
{
  if (!amcl_pose_received_) {
    return true;
  }

  return (now() - last_amcl_pose_time_).seconds() > amcl_pose_timeout_;
}

void NavigationNode::resetLocalizationState(bool clear_goal)
{
  navigation_enabled_ = false;
  localization_ready_ = false;
  stable_localization_count_ = 0;
  costmap_warmup_remaining_ = std::max(0, costmap_warmup_cycles_);
  amcl_pose_received_ = false;

  recovery_count_ = 0;
  current_recovery_action_ = RecoveryAction::NONE;
  current_recovery_timeout_ = 0.0;
  stuck_tracking_initialized_ = false;
  current_path_.poses.clear();

  local_planner_->clearPath();
  resetOscillationTracking();
  publishZeroVelocity();
  clearPublishedArtifacts();

  if (clear_goal) {
    goal_received_ = false;
  }
}

void NavigationNode::clearPublishedArtifacts()
{
  if (global_path_pub_) {
    nav_msgs::msg::Path empty_path;
    empty_path.header.frame_id = global_frame_;
    empty_path.header.stamp = now();
    global_path_pub_->publish(empty_path);
  }

  if (marker_pub_) {
    visualization_msgs::msg::Marker marker;
    marker.header.frame_id = global_frame_;
    marker.header.stamp = now();
    marker.ns = "global_path";
    marker.id = 0;
    marker.action = visualization_msgs::msg::Marker::DELETE;
    marker_pub_->publish(marker);
  }
}

double NavigationNode::distanceToGoal(const geometry_msgs::msg::PoseStamped& current_pose) const
{
  if (!goal_received_) {
    return 1e9;
  }

  return std::hypot(
    current_goal_.pose.position.x - current_pose.pose.position.x,
    current_goal_.pose.position.y - current_pose.pose.position.y);
}

double NavigationNode::headingErrorToGoal(const geometry_msgs::msg::PoseStamped& current_pose) const
{
  if (!goal_received_) {
    return 0.0;
  }

  return normalizeAngle(
    tf2::getYaw(current_goal_.pose.orientation) -
    tf2::getYaw(current_pose.pose.orientation));
}

double NavigationNode::normalizeAngle(double angle) const
{
  return std::atan2(std::sin(angle), std::cos(angle));
}

void NavigationNode::publishZeroVelocity()
{
  cmd_vel_pub_->publish(geometry_msgs::msg::Twist());
}

void NavigationNode::publishState()
{
  std_msgs::msg::String msg;
  msg.data = stateToString(state_);
  state_pub_->publish(msg);
}

void NavigationNode::publishCostmap()
{
  if (!navigation_enabled_) {
    return;
  }
  if (!costmap_->isMapReceived()) {
    return;
  }
  if (costmap_pub_->get_subscription_count() == 0) {
    return;
  }

  auto grid = costmap_->toOccupancyGrid();
  grid.header.stamp = now();
  costmap_pub_->publish(grid);
}

void NavigationNode::publishPathMarker(const nav_msgs::msg::Path& path)
{
  if (!navigation_enabled_) {
    return;
  }
  if (marker_pub_->get_subscription_count() == 0) {
    return;
  }

  visualization_msgs::msg::Marker marker;
  marker.header.frame_id = global_frame_;
  marker.header.stamp = now();
  marker.ns = "global_path";
  marker.id = 0;
  marker.type = visualization_msgs::msg::Marker::LINE_STRIP;
  marker.action = visualization_msgs::msg::Marker::ADD;
  marker.scale.x = 0.05;
  marker.color.r = 0.0;
  marker.color.g = 1.0;
  marker.color.b = 0.0;
  marker.color.a = 0.8;
  marker.lifetime = rclcpp::Duration(0, 0);

  for (const auto& ps : path.poses) {
    geometry_msgs::msg::Point p;
    p.x = ps.pose.position.x;
    p.y = ps.pose.position.y;
    p.z = 0.05;
    marker.points.push_back(p);
  }

  marker_pub_->publish(marker);
}

}  // namespace hospital_nav

int main(int argc, char** argv)
{
  rclcpp::init(argc, argv);

  auto node = std::make_shared<hospital_nav::NavigationNode>();

  rclcpp::executors::MultiThreadedExecutor executor(rclcpp::ExecutorOptions(), 2);
  executor.add_node(node);
  executor.spin();

  rclcpp::shutdown();
  return 0;
}
