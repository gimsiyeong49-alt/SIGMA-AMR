#!/usr/bin/env python3

import json
import math
import sys
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient

from nav2_msgs.action import NavigateToPose
from geometry_msgs.msg import PoseStamped
from action_msgs.msg import GoalStatus


LABELS_FILE = Path("/mnt/ssd/cart_ros2/src/hospital_mission/map/map_labels.json")


def load_labels(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    labels = {}

    for zone in data.get("zones", []):
        name = zone.get("name")
        if name:
            labels[name] = zone

        for alias in zone.get("alias", []):
            labels[alias] = zone

    return labels


def extract_label(text: str, labels: dict):
    text = text.strip()

    if text in labels:
        return text

    for label in labels.keys():
        if label in text:
            return label

    return None


def zone_to_pose(zone: dict) -> PoseStamped:
    pose = PoseStamped()
    pose.header.frame_id = zone.get("frame_id", "map")

    if "nav_goal" in zone:
        nav_goal = zone["nav_goal"]

        pose.pose.position.x = float(nav_goal["x"])
        pose.pose.position.y = float(nav_goal["y"])
        pose.pose.position.z = 0.0

        if "qz" in nav_goal and "qw" in nav_goal:
            pose.pose.orientation.x = 0.0
            pose.pose.orientation.y = 0.0
            pose.pose.orientation.z = float(nav_goal["qz"])
            pose.pose.orientation.w = float(nav_goal["qw"])
            return pose

        yaw_deg = float(nav_goal.get("yaw_deg", 0.0))

    elif zone.get("type") == "rectangle":
        pose.pose.position.x = (float(zone["x_min"]) + float(zone["x_max"])) / 2.0
        pose.pose.position.y = (float(zone["y_min"]) + float(zone["y_max"])) / 2.0
        pose.pose.position.z = 0.0
        yaw_deg = float(zone.get("rotation_deg", 0.0))

    else:
        pose.pose.position.x = float(zone["x"])
        pose.pose.position.y = float(zone["y"])
        pose.pose.position.z = 0.0
        yaw_deg = float(zone.get("yaw_deg", zone.get("yaw", 0.0)))

    yaw_rad = math.radians(yaw_deg)

    pose.pose.orientation.x = 0.0
    pose.pose.orientation.y = 0.0
    pose.pose.orientation.z = math.sin(yaw_rad / 2.0)
    pose.pose.orientation.w = math.cos(yaw_rad / 2.0)

    return pose


class VoiceToNav(Node):
    def __init__(self):
        super().__init__("voice_to_nav")
        self.client = ActionClient(self, NavigateToPose, "navigate_to_pose")

    def send_goal(self, pose: PoseStamped, label: str):
        self.get_logger().info("Nav2 서버 대기 중...")

        if not self.client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error("Nav2 action server 없음: /navigate_to_pose")
            return False

        pose.header.stamp = self.get_clock().now().to_msg()

        goal = NavigateToPose.Goal()
        goal.pose = pose

        self.get_logger().info(
            f"목적지 전송: {label} "
            f"x={pose.pose.position.x:.3f}, y={pose.pose.position.y:.3f}"
        )

        future = self.client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, future)

        goal_handle = future.result()

        if not goal_handle.accepted:
            self.get_logger().error("목표 거부됨")
            return False

        self.get_logger().info("목표 수락 → 이동 시작")

        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future)

        status = result_future.result().status

        if status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info(f"도착 완료: {label}")
            return True

        self.get_logger().warn(f"이동 실패 또는 중단 status={status}")
        return False


def main():
    if len(sys.argv) < 2:
        print("사용법:")
        print("  python3 voice_to_nav.py 화장실")
        print("  python3 voice_to_nav.py '화장실로 가줘'")
        sys.exit(1)

    text = " ".join(sys.argv[1:]).strip()

    if not LABELS_FILE.exists():
        print(f"라벨 파일 없음: {LABELS_FILE}")
        sys.exit(1)

    labels = load_labels(LABELS_FILE)

    label = extract_label(text, labels)

    if not label:
        print(f"목적지 추출 실패: {text}")
        print(f"가능한 라벨: {list(labels.keys())}")
        sys.exit(1)

    print(f"STT 텍스트: {text}")
    print(f"추출된 목적지: {label}")

    zone = labels[label]
    pose = zone_to_pose(zone)

    rclpy.init()
    node = VoiceToNav()

    try:
        node.send_goal(pose, label)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
