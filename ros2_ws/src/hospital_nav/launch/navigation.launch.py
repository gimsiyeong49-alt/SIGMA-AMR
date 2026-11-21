import os
from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    pkg_dir     = get_package_share_directory('hospital_nav')
    params_file = os.path.join(pkg_dir, 'config', 'params.yaml')
    map_file    = os.path.join(pkg_dir, 'map', '415_map.yaml')
    rviz_config = os.path.join(pkg_dir, 'rviz', 'navigation.rviz')

    map_loader = Node(
        package='hospital_nav',
        executable='map_loader',
        name='map_loader',
        output='screen',
        parameters=[{'map_yaml_path': map_file}],
    )

    amcl = Node(
        package='hospital_nav',
        executable='amcl',
        name='amcl',
        output='screen',
        parameters=[params_file],  # params.yaml에서 읽음
    )

    navigation_node = Node(
        package='hospital_nav',
        executable='navigation_node',
        name='navigation_node',
        output='screen',
        parameters=[params_file],
        remappings=[('/cmd_vel', '/cmd_vel'), ('/goal_pose', '/goal_pose')],
    )

    rviz = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        arguments=['-d', rviz_config],
        output='screen',
    )

    return LaunchDescription([map_loader, amcl, navigation_node, rviz])
