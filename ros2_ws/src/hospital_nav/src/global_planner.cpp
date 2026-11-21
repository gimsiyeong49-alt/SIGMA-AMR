#include "hospital_nav/global_planner.hpp"
#include <tf2/utils.h>
#include <cmath>
#include <algorithm>
#include <limits>

namespace hospital_nav
{

GlobalPlanner::GlobalPlanner(rclcpp::Node* node, std::shared_ptr<Costmap> costmap,
                             const PlannerParams& params)
  : node_(node), costmap_(costmap), params_(params)
{
  RCLCPP_INFO(node_->get_logger(), "GlobalPlanner: Theta* initialized");
}

// ============================================================
// start셀 막힘 시 근처 자유 셀 탐색
// ============================================================
bool GlobalPlanner::findFreeCellNear(int cx, int cy, int& out_x, int& out_y) const
{
  constexpr int SEARCH_RADIUS = 8;
  for (int r = 1; r <= SEARCH_RADIUS; ++r) {
    for (int ddx = -r; ddx <= r; ++ddx) {
      for (int ddy = -r; ddy <= r; ++ddy) {
        if (std::abs(ddx) != r && std::abs(ddy) != r) continue;
        int nx = cx + ddx, ny = cy + ddy;
        if (!costmap_->isValid(nx, ny)) continue;
        if (costmap_->getCost(nx, ny) < INSCRIBED_COST) {
          out_x = nx; out_y = ny;
          return true;
        }
      }
    }
  }
  return false;
}

// ============================================================
// Theta* LOS 체크 — Bresenham 직선 위의 모든 셀이 통과 가능한지 확인
// 장애물(INSCRIBED_COST 이상)이 하나라도 있으면 false
// ============================================================
bool GlobalPlanner::lineOfSight(int x0, int y0, int x1, int y1) const
{
  int dx  = std::abs(x1 - x0);
  int dy  = std::abs(y1 - y0);
  int sx  = (x0 < x1) ? 1 : -1;
  int sy  = (y0 < y1) ? 1 : -1;
  int err = dx - dy;

  int cx = x0, cy = y0;

  while (cx != x1 || cy != y1) {
    if (!costmap_->isValid(cx, cy)) return false;
    if (costmap_->getCost(cx, cy) >= INSCRIBED_COST) return false;

    const int e2 = 2 * err;
    if (e2 > -dy) { err -= dy; cx += sx; }
    if (e2 <  dx) { err += dx; cy += sy; }
  }

  // 끝점 체크
  if (!costmap_->isValid(x1, y1)) return false;
  if (costmap_->getCost(x1, y1) >= INSCRIBED_COST) return false;

  return true;
}

// ============================================================
// Theta* 경로 계획
//
// A*와 다른 점: 이웃 셀 업데이트 시
//   - 조부모(grandparent)까지 LOS가 확보되면 현재 셀 건너뛰고 직접 연결
//   - 격자 셀 따라가지 않으므로 경로 꺾임이 대폭 줄어듦
//   - 결과: 46 poses → 5~10 poses (RPP가 훨씬 부드럽게 따라감)
// ============================================================
bool GlobalPlanner::makePlan(const geometry_msgs::msg::PoseStamped& start,
                             const geometry_msgs::msg::PoseStamped& goal,
                             nav_msgs::msg::Path& path)
{
  path.poses.clear();
  path.header.frame_id = params_.global_frame;
  path.header.stamp    = node_->now();

  if (!costmap_->isMapReceived()) {
    RCLCPP_WARN(node_->get_logger(), "GlobalPlanner: no map received yet");
    return false;
  }

  int start_mx, start_my, goal_mx, goal_my;

  if (!costmap_->worldToMap(start.pose.position.x, start.pose.position.y,
                            start_mx, start_my)) {
    RCLCPP_ERROR(node_->get_logger(), "GlobalPlanner: start outside costmap");
    return false;
  }
  if (!costmap_->worldToMap(goal.pose.position.x, goal.pose.position.y,
                            goal_mx, goal_my)) {
    RCLCPP_ERROR(node_->get_logger(), "GlobalPlanner: goal outside costmap");
    return false;
  }

  // start셀 막힘 처리
  if (costmap_->getCost(start_mx, start_my) >= INSCRIBED_COST) {
    int free_x, free_y;
    if (findFreeCellNear(start_mx, start_my, free_x, free_y)) {
      RCLCPP_WARN(node_->get_logger(),
                  "GlobalPlanner: start blocked (cost=%d), using nearby cell",
                  costmap_->getCost(start_mx, start_my));
      start_mx = free_x; start_my = free_y;
    } else {
      RCLCPP_ERROR(node_->get_logger(), "GlobalPlanner: start blocked, no free cell nearby");
      return false;
    }
  }

  if (costmap_->getCost(goal_mx, goal_my) >= INSCRIBED_COST) {
    RCLCPP_ERROR(node_->get_logger(), "GlobalPlanner: goal is in obstacle (cost=%d)",
                 costmap_->getCost(goal_mx, goal_my));
    return false;
  }

  const unsigned int sx    = costmap_->getSizeX();
  const size_t       total = static_cast<size_t>(sx) * costmap_->getSizeY();

  std::vector<double> g_cost(total, std::numeric_limits<double>::infinity());
  std::vector<int>    parent(total, -1);
  std::vector<bool>   closed(total, false);

  std::priority_queue<Cell, std::vector<Cell>, CellCompare> open;

  const int start_idx = toIndex(start_mx, start_my);
  const int goal_idx  = toIndex(goal_mx,  goal_my);

  g_cost[start_idx] = 0.0;
  open.push({start_mx, start_my, 0.0,
             heuristic(start_mx, start_my, goal_mx, goal_my), -1});

  bool found      = false;
  int  iterations = 0;
  constexpr int MAX_ITERATIONS = 500000;

  while (!open.empty() && iterations < MAX_ITERATIONS) {
    ++iterations;
    const Cell current = open.top();
    open.pop();

    const int cidx = toIndex(current.x, current.y);
    if (closed[cidx])              continue;
    if (current.g > g_cost[cidx]) continue;

    closed[cidx] = true;

    if (current.x == goal_mx && current.y == goal_my) {
      found = true;
      break;
    }

    for (int d = 0; d < NUM_DIRS; ++d) {
      const int nx = current.x + dx_[d];
      const int ny = current.y + dy_[d];

      if (!costmap_->isValid(nx, ny)) continue;

      const int nidx = toIndex(nx, ny);
      if (closed[nidx]) continue;

      const uint8_t cost = costmap_->getCost(nx, ny);
      if (cost >= INSCRIBED_COST)                         continue;
      if (cost == NO_INFORMATION && !params_.allow_unknown) continue;

      // ── Theta*: 조부모(grandparent) LOS 체크 ──────────
      const int gp_idx = parent[cidx];  // 현재 노드의 부모 = 조부모

      if (gp_idx >= 0) {
        const int gp_x = gp_idx % static_cast<int>(sx);
        const int gp_y = gp_idx / static_cast<int>(sx);

        if (lineOfSight(gp_x, gp_y, nx, ny)) {
          // 조부모 → 이웃 직선 경로 사용 (현재 노드 건너뜀)
          const double dist = std::hypot(static_cast<double>(nx - gp_x),
                                         static_cast<double>(ny - gp_y));
          const double new_g = g_cost[gp_idx] +
                               dist * (1.0 + static_cast<double>(cost) / 50.0);

          if (new_g < g_cost[nidx]) {
            g_cost[nidx] = new_g;
            parent[nidx] = gp_idx;  // 직접 조부모에 연결
            open.push({nx, ny, new_g,
                       new_g + heuristic(nx, ny, goal_mx, goal_my), gp_idx});
          }
          continue;  // LOS 성공 시 A* fallback 생략
        }
      }

      // ── A* fallback: LOS 실패 시 일반 그리드 이동 ────
      const double cell_cost = dcost_[d] * (1.0 + static_cast<double>(cost) / 50.0);
      const double new_g     = g_cost[cidx] + cell_cost;

      if (new_g < g_cost[nidx]) {
        g_cost[nidx] = new_g;
        parent[nidx] = cidx;
        open.push({nx, ny, new_g,
                   new_g + heuristic(nx, ny, goal_mx, goal_my), cidx});
      }
    }
  }

  if (!found) {
    RCLCPP_WARN(node_->get_logger(),
                "GlobalPlanner: no path found (%d iterations)", iterations);
    return false;
  }

  RCLCPP_INFO(node_->get_logger(),
              "GlobalPlanner: path found in %d iterations", iterations);

  // ── 경로 역추적 ────────────────────────────────────────────
  std::vector<std::pair<int,int>> map_path;
  int idx = goal_idx;
  while (idx != -1 && idx != start_idx) {
    map_path.emplace_back(idx % static_cast<int>(sx),
                          idx / static_cast<int>(sx));
    idx = parent[idx];
  }
  map_path.emplace_back(start_mx, start_my);
  std::reverse(map_path.begin(), map_path.end());

  // ── map → world 변환 ────────────────────────────────────────
  for (auto& [mx, my] : map_path) {
    geometry_msgs::msg::PoseStamped ps;
    ps.header = path.header;
    costmap_->mapToWorld(mx, my, ps.pose.position.x, ps.pose.position.y);
    ps.pose.position.z    = 0.0;
    ps.pose.orientation.w = 1.0;
    path.poses.push_back(ps);
  }

  // ── orientation 계산 ──────────────────────────────────────
  for (size_t i = 0; i < path.poses.size(); ++i) {
    double yaw;
    if (i + 1 < path.poses.size()) {
      yaw = std::atan2(
        path.poses[i+1].pose.position.y - path.poses[i].pose.position.y,
        path.poses[i+1].pose.position.x - path.poses[i].pose.position.x);
    } else {
      yaw = tf2::getYaw(goal.pose.orientation);
    }
    path.poses[i].pose.orientation.z = std::sin(yaw / 2.0);
    path.poses[i].pose.orientation.w = std::cos(yaw / 2.0);
  }

  // ── 보간: 0.10m 간격으로 채워서 로컬 플래너에 충분한 밀도 ──
  interpolatePath(path, 0.10);

  RCLCPP_INFO(node_->get_logger(),
              "GlobalPlanner: final path has %zu poses", path.poses.size());
  return true;
}

// ============================================================
// 경로 보간
// ============================================================
void GlobalPlanner::interpolatePath(nav_msgs::msg::Path& path, double max_dist_m)
{
  if (path.poses.size() < 2) return;

  nav_msgs::msg::Path dense;
  dense.header = path.header;

  for (size_t i = 0; i + 1 < path.poses.size(); ++i) {
    const auto& p0  = path.poses[i];
    const auto& p1  = path.poses[i + 1];
    const double ddx = p1.pose.position.x - p0.pose.position.x;
    const double ddy = p1.pose.position.y - p0.pose.position.y;
    const double dist = std::hypot(ddx, ddy);

    dense.poses.push_back(p0);

    if (dist > max_dist_m) {
      const int    steps = static_cast<int>(std::ceil(dist / max_dist_m));
      const double yaw   = std::atan2(ddy, ddx);

      for (int s = 1; s < steps; ++s) {
        const double t = static_cast<double>(s) / steps;
        geometry_msgs::msg::PoseStamped ps;
        ps.header             = path.header;
        ps.pose.position.x    = p0.pose.position.x + t * ddx;
        ps.pose.position.y    = p0.pose.position.y + t * ddy;
        ps.pose.position.z    = 0.0;
        ps.pose.orientation.z = std::sin(yaw / 2.0);
        ps.pose.orientation.w = std::cos(yaw / 2.0);
        dense.poses.push_back(ps);
      }
    }
  }

  dense.poses.push_back(path.poses.back());
  path = dense;
}

// ============================================================
// 휴리스틱 (옥타일 거리)
// ============================================================
double GlobalPlanner::heuristic(int x1, int y1, int x2, int y2) const
{
  const int dx = std::abs(x2 - x1);
  const int dy = std::abs(y2 - y1);
  return 1.0 * std::max(dx, dy) + 0.414 * std::min(dx, dy);
}

int GlobalPlanner::toIndex(int x, int y) const
{
  return y * static_cast<int>(costmap_->getSizeX()) + x;
}

}  // namespace hospital_nav
