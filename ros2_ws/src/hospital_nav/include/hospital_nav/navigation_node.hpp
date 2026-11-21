#pragma once

#include <rclcpp/rclcpp.hpp>

#include <geometry_msgs/msg/pose_stamped.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <nav_msgs/msg/path.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>
#include <std_msgs/msg/string.hpp>
#include <visualization_msgs/msg/marker.hpp>

#include <tf2_ros/buffer.h>
#include <tf2_ros/transform_listener.h>

#include <deque>
#include <memory>
#include <string>

#include "hospital_nav/costmap.hpp"
#include "hospital_nav/global_planner.hpp"
#include "hospital_nav/local_planner.hpp"
#include "hospital_nav/recovery_manager.hpp"

namespace hospital_nav
{

enum class NavState
{
  WAIT_LOCALIZATION,
  IDLE,
  PLANNING,
  MOVING,
  ARRIVED,
  RECOVERY
};

class NavigationNode : public rclcpp::Node
{
public:
  explicit NavigationNode(const rclcpp::NodeOptions& options = rclcpp::NodeOptions());

private:
  struct PoseRecord
  {
    double x;
    double y;
    rclcpp::Time stamp;
  };

  void loadParameters();
  void setupSubscribers();
  void setupPublishers();
  void setupTimers();

  void goalCallback(const geometry_msgs::msg::PoseStamped::SharedPtr msg);
  void mapCallback(const nav_msgs::msg::OccupancyGrid::SharedPtr msg);
  void scanCallback(const sensor_msgs::msg::LaserScan::SharedPtr msg);
  void amclPoseCallback(const geometry_msgs::msg::PoseWithCovarianceStamped::SharedPtr msg);

  void costmapLoop();
  void controlLoop();

  void transitionTo(NavState new_state);

  void handleWaitLocalization();
  void handleIdle();
  void handlePlanning();
  void handleMoving();
  void handleArrived();
  void handleRecovery();

  void handleFailure(FailureReason reason,
                     const geometry_msgs::msg::PoseStamped& current_pose,
                     double dist_to_goal,
                     double heading_error);

  bool getRobotPose(geometry_msgs::msg::PoseStamped& pose);

  bool isStuck(const geometry_msgs::msg::PoseStamped& current_pose,
               const geometry_msgs::msg::Twist& commanded_vel);
  void resetStuckTracking(const geometry_msgs::msg::PoseStamped& current_pose);

  bool isOscillating(const geometry_msgs::msg::PoseStamped& current_pose);
  void resetOscillationTracking();

  bool isLocalizationReliable(const geometry_msgs::msg::PoseWithCovarianceStamped& msg) const;
  bool isAmclTimedOut() const;
  void resetLocalizationState(bool clear_goal = false);
  void clearPublishedArtifacts();

  double distanceToGoal(const geometry_msgs::msg::PoseStamped& current_pose) const;
  double headingErrorToGoal(const geometry_msgs::msg::PoseStamped& current_pose) const;
  double normalizeAngle(double angle) const;

  void publishZeroVelocity();
  void publishState();
  void publishCostmap();
  void publishPathMarker(const nav_msgs::msg::Path& path);

  std::string stateToString(NavState state) const
  {
    switch (state) {
      case NavState::WAIT_LOCALIZATION: return "WAIT_LOCALIZATION";
      case NavState::IDLE:              return "IDLE";
      case NavState::PLANNING:          return "PLANNING";
      case NavState::MOVING:            return "MOVING";
      case NavState::ARRIVED:           return "ARRIVED";
      case NavState::RECOVERY:          return "RECOVERY";
      default:                          return "UNKNOWN";
    }
  }

  std::shared_ptr<tf2_ros::Buffer> tf_buffer_;
  std::shared_ptr<tf2_ros::TransformListener> tf_listener_;

  std::shared_ptr<Costmap> costmap_;
  std::shared_ptr<GlobalPlanner> global_planner_;
  std::shared_ptr<LocalPlanner> local_planner_;
  std::unique_ptr<RecoveryManager> recovery_manager_;

  rclcpp::Subscription<geometry_msgs::msg::PoseStamped>::SharedPtr goal_sub_;
  rclcpp::Subscription<nav_msgs::msg::OccupancyGrid>::SharedPtr map_sub_;
  rclcpp::Subscription<sensor_msgs::msg::LaserScan>::SharedPtr scan_sub_;
  rclcpp::Subscription<geometry_msgs::msg::PoseWithCovarianceStamped>::SharedPtr amcl_pose_sub_;

  rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr cmd_vel_pub_;
  rclcpp::Publisher<nav_msgs::msg::Path>::SharedPtr global_path_pub_;
  rclcpp::Publisher<nav_msgs::msg::OccupancyGrid>::SharedPtr costmap_pub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr state_pub_;
  rclcpp::Publisher<visualization_msgs::msg::Marker>::SharedPtr marker_pub_;

  rclcpp::TimerBase::SharedPtr control_timer_;
  rclcpp::TimerBase::SharedPtr costmap_timer_;

  std::string global_frame_;
  std::string odom_frame_;
  std::string robot_frame_;

  double controller_freq_{20.0};
  double planner_frequency_{1.0};
  double replan_frequency_{0.2};

  NavState state_{NavState::WAIT_LOCALIZATION};

  geometry_msgs::msg::PoseStamped current_goal_;
  nav_msgs::msg::Path current_path_;

  bool goal_received_{false};

  bool amcl_pose_received_{false};
  bool localization_ready_{false};
  bool navigation_enabled_{false};

  int stable_localization_count_{0};
  int localization_min_samples_{5};
  int costmap_warmup_cycles_{3};
  int costmap_warmup_remaining_{0};

  double amcl_cov_x_threshold_{0.05};
  double amcl_cov_y_threshold_{0.05};
  double amcl_cov_yaw_threshold_{0.10};
  double amcl_pose_timeout_{2.0};

  rclcpp::Time last_amcl_pose_time_;

  int recovery_count_{0};
  RecoveryAction current_recovery_action_{RecoveryAction::NONE};
  double current_recovery_timeout_{0.0};

  double recovery_backup_dist_{0.18};
  double recovery_backup_vel_{-0.08};
  double recovery_spin_angle_{0.785398};
  double recovery_spin_vel_{0.35};

  geometry_msgs::msg::PoseStamped recovery_start_pose_;
  geometry_msgs::msg::PoseStamped last_pose_for_stuck_;

  double recovery_spin_start_yaw_{0.0};

  bool stuck_tracking_initialized_{false};

  double stuck_timeout_{6.0};
  double stuck_vel_threshold_{0.02};
  double stuck_distance_threshold_{0.05};
  double stuck_yaw_threshold_{0.15};

  double oscillation_timeout_{20.0};
  double oscillation_distance_{0.10};

  rclcpp::Time last_moving_time_;
  rclcpp::Time last_pose_check_time_;
  rclcpp::Time last_replan_time_;
  rclcpp::Time last_planning_attempt_time_;
  rclcpp::Time recovery_start_time_;

  std::deque<PoseRecord> pose_history_;
};

}  // namespace hospital_nav
