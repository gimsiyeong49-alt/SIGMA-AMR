cmake_minimum_required(VERSION 3.8)
project(hospital_nav)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic -O2)
endif()
set(CMAKE_CXX_STANDARD 17)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)
find_package(visualization_msgs REQUIRED)

set(DEPS
  rclcpp
  std_msgs
  geometry_msgs
  nav_msgs
  sensor_msgs
  tf2
  tf2_ros
  tf2_geometry_msgs
  visualization_msgs
)

include_directories(include)

add_executable(navigation_node
  src/navigation_node.cpp
  src/recovery_manager.cpp
  src/costmap.cpp
  src/global_planner.cpp
  src/local_planner.cpp
)
ament_target_dependencies(navigation_node ${DEPS})

add_executable(map_loader src/map_loader.cpp)
ament_target_dependencies(map_loader ${DEPS})
target_link_libraries(map_loader yaml-cpp)

add_executable(amcl src/amcl.cpp)
ament_target_dependencies(amcl
  rclcpp
  nav_msgs
  sensor_msgs
  geometry_msgs
  tf2
  tf2_ros
  tf2_geometry_msgs
  visualization_msgs
)

install(TARGETS
  navigation_node
  map_loader
  amcl
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY
  launch
  config
  map
  rviz
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
