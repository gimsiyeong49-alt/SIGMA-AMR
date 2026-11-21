#!/usr/bin/env python3
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, DeclareLaunchArgument
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory as gpsd_ekf


def generate_launch_description():

    agv_body = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                get_package_share_directory('agv_body'),
                'launch', 'agv_body.launch.py'
            ])
        ]),
        launch_arguments={'use_rviz': 'true'}.items(),
    )

    lidars = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                get_package_share_directory('sllidar_ros2'),
                'launch', 'run_lidars.launch.py'
            ])
        ]),
    )

    imu = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                get_package_share_directory('stella_ahrs'),
                'launch', 'stella_ahrs_launch.py'
            ])
        ]),
    )

    ekf_config = os.path.join(
        get_package_share_directory('agv_mapping'),
        'config', 'ekf.yaml'
    )

    ekf_node = Node(
        package='robot_localization',
        executable='ekf_node',
        name='ekf_filter_node',
        output='screen',
        parameters=[ekf_config],
    )

    return LaunchDescription([
        agv_body,
        lidars,
        imu,
        ekf_node,
    ])
