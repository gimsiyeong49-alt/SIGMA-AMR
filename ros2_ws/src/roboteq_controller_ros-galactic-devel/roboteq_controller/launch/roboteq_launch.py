import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    ld = LaunchDescription()
    config = os.path.join(
        get_package_share_directory('roboteq_controller'),
        'config',
        'query.yaml'
        )
        
    node=Node(
        package = 'roboteq_controller',
        name = 'roboteq_controller_node',
        executable = 'roboteq_controller_node',
        parameters = [config],
        # 2026-11-12: 죽으면 2초 뒤 자동 재시작(예전엔 한 번 죽으면 브링업을 재시작할 때까지 바퀴가 안 움직였음)
        respawn = True,
        respawn_delay = 2.0,
    )
    ld.add_action(node)
    return ld