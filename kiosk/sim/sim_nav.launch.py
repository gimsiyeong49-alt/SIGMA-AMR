# sim_nav.launch.py — 실험 2 시뮬레이션용 Nav2(실제 navigation.launch.py 와 같은 bringup·설정·지도·bond_timeout 0).
#   RViz·카메라 장애물 노드·주행 요청 감시기는 뺌(감시기는 nav_request_watcher_sim.py 로 따로, 시뮬 폴더 사용).
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import SetParameter


def generate_launch_description():
    nav2_dir = get_package_share_directory("nav2_bringup")
    nav2 = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(nav2_dir, "launch", "bringup_launch.py")),
        launch_arguments={"slam": "False", "use_sim_time": "False", "autostart": "True",
                          "map": LaunchConfiguration("map"),
                          "params_file": LaunchConfiguration("params_file")}.items())
    return LaunchDescription([DeclareLaunchArgument("map"), DeclareLaunchArgument("params_file"),
                              GroupAction([SetParameter(name="bond_timeout", value=0.0), nav2])])
