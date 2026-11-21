import os

from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, DeclareLaunchArgument, GroupAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch.conditions import IfCondition

from launch_ros.actions import Node, SetParameter
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():

    pkg_dir = get_package_share_directory("hospital_mission")
    nav2_dir = get_package_share_directory("nav2_bringup")

    map_file = os.path.join(pkg_dir, "map", "my_map.yaml")
    params_file = os.path.join(pkg_dir, "config", "agv.yaml")
    rviz_config = os.path.join(pkg_dir, "rviz", "hospital_view.rviz")

    # map_labels.json은 src에 있으므로 절대 경로로 지정
    # 이 파일에서 각 영역의 nav_goal을 읽어서 Nav2 goal로 변환함
    map_labels_file = "/mnt/ssd/cart_ros2/src/hospital_mission/map/map_labels.json"

    nav_request_dir = "/mnt/ssd/cart_ros2/src/llm_package/bus/nav_request"
    nav_request_done_dir = "/mnt/ssd/cart_ros2/src/llm_package/bus/nav_request_done"

    map_arg = DeclareLaunchArgument(
        "map",
        default_value=map_file,
        description="맵 yaml 경로"
    )

    params_arg = DeclareLaunchArgument(
        "params_file",
        default_value=params_file,
        description="nav2 파라미터 yaml 경로"
    )

    # 2026-11-11: RViz 켜기/끄기 선택(기본 켬). 끄면 CPU 약 0.5코어 절약(실측 rviz2 46~57%)
    #   예) ros2 launch hospital_mission navigation.launch.py use_rviz:=false
    rviz_arg = DeclareLaunchArgument(
        "use_rviz",
        default_value="true",
        description="RViz 실행 여부(true/false)"
    )

    nav2 = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_dir, "launch", "bringup_launch.py")
        ),
        launch_arguments={
            "slam": "False",
            "use_sim_time": "False",
            "autostart": "True",
            "map": LaunchConfiguration("map"),
            "params_file": LaunchConfiguration("params_file"),
        }.items(),
    )

    rviz = Node(
        package="rviz2",
        executable="rviz2",
        name="rviz2",
        arguments=["-d", rviz_config],
        output="screen",
        condition=IfCondition(LaunchConfiguration("use_rviz")),
    )

    vision_obstacle = Node(
        package="hospital_mission",
        executable="vision_obstacle_node",
        name="vision_obstacle_node",
        output="screen",
    )

    nav_request_watcher = Node(
        package="hospital_mission",
        executable="nav_request_watcher",
        name="nav_request_watcher",
        output="screen",
        parameters=[
            {
                "map_labels_path": map_labels_file,
                "nav_request_dir": nav_request_dir,
                "nav_request_done_dir": nav_request_done_dir,
            }
        ],
    )

    return LaunchDescription([
        map_arg,
        params_arg,
        rviz_arg,
        # 2026-11-12: Nav2 Galactic lifecycle_manager 의 bond(생존 확인) 경쟁 상태 버그로 기동 중
        #   "statemap::StateUndefinedException: transition invoked while in transition" → lifecycle_manager 죽음 →
        #   bt_navigator 미활성 → 목표 전부 거부(로그상 4회 발생). bond_timeout=0 으로 bond 자체를 끈다.
        #   (대가: 노드가 중간에 죽어도 lifecycle_manager 가 자동 감지·정지하지 않음 — start_guide.sh 가 활성 상태를 따로 확인)
        GroupAction([
            SetParameter(name="bond_timeout", value=0.0),
            nav2,
        ]),
        rviz,
        vision_obstacle,
        nav_request_watcher,
    ])
