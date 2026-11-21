#pragma once

#include <rclcpp/rclcpp.hpp>
#include <nav_msgs/msg/path.hpp>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include "hospital_nav/costmap.hpp"

#include <vector>
#include <queue>

namespace hospital_nav
{

struct PlannerParams
{
  bool allow_unknown       = false;
  double planner_freq      = 1.0;
  std::string global_frame = "map";
};

class GlobalPlanner
{
public:
  GlobalPlanner(rclcpp::Node* node, std::shared_ptr<Costmap> costmap,
                const PlannerParams& params);

  bool makePlan(const geometry_msgs::msg::PoseStamped& start,
                const geometry_msgs::msg::PoseStamped& goal,
                nav_msgs::msg::Path& path);

private:
  struct Cell
  {
    int x, y;
    double g, f;
    int parent_idx;
  };

  struct CellCompare
  {
    bool operator()(const Cell& a, const Cell& b) const { return a.f > b.f; }
  };

  double heuristic(int x1, int y1, int x2, int y2) const;
  int    toIndex(int x, int y) const;

  // Recovery: start셀 막힘 시 근처 자유 셀 탐색
  bool findFreeCellNear(int cx, int cy, int& out_x, int& out_y) const;

  // Theta*: 두 셀 사이 직선 경로가 장애물 없는지 확인 (Bresenham)
  bool lineOfSight(int x0, int y0, int x1, int y1) const;

  // 경로 보간: 로컬 플래너에 충분한 밀도 제공
  void interpolatePath(nav_msgs::msg::Path& path, double max_dist_m);

  rclcpp::Node*            node_;
  std::shared_ptr<Costmap> costmap_;
  PlannerParams            params_;

  static constexpr int    NUM_DIRS   = 8;
  static constexpr int    dx_[8]     = { 1,  1,  0, -1, -1, -1,  0,  1};
  static constexpr int    dy_[8]     = { 0,  1,  1,  1,  0, -1, -1, -1};
  static constexpr double dcost_[8]  = {1.0, 1.414, 1.0, 1.414,
                                        1.0, 1.414, 1.0, 1.414};
};

}  // namespace hospital_nav
