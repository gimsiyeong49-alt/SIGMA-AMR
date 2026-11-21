#pragma once
#include <rclcpp/rclcpp.hpp>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <string>

namespace hospital_nav {

class MapLoader : public rclcpp::Node {
public:
    explicit MapLoader(const rclcpp::NodeOptions & options = rclcpp::NodeOptions());

private:
    void loadMap(const std::string & yaml_path);
    bool parsePgm(const std::string & pgm_path,
                  nav_msgs::msg::OccupancyGrid & grid);

    rclcpp::Publisher<nav_msgs::msg::OccupancyGrid>::SharedPtr map_pub_;
    rclcpp::TimerBase::SharedPtr timer_;
    nav_msgs::msg::OccupancyGrid map_msg_;
};

} // namespace hospital_nav
