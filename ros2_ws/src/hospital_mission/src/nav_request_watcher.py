#!/usr/bin/env python3

import json
import math
import shutil
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient

from nav2_msgs.action import NavigateToPose
from geometry_msgs.msg import PoseStamped
from action_msgs.msg import GoalStatus


LABELS_FILE = Path("/mnt/ssd/cart_ros2/src/hospital_mission/map/map_labels.json")
NAV_REQUEST_DIR = Path("/mnt/ssd/cart_ros2/src/llm_package/bus/nav_request")
NAV_REQUEST_DONE_DIR = Path("/mnt/ssd/cart_ros2/src/llm_package/bus/nav_request_done")


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
        cx = (float(zone["x_min"]) + float(zone["x_max"])) / 2.0
        cy = (float(zone["y_min"]) + float(zone["y_max"])) / 2.0
        yaw_deg = float(zone.get("rotation_deg", 0.0))

        pose.pose.position.x = cx
        pose.pose.position.y = cy
        pose.pose.position.z = 0.0

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


class NavRequestWatcher(Node):
    def __init__(self):
        super().__init__("nav_request_watcher")

        NAV_REQUEST_DIR.mkdir(parents=True, exist_ok=True)
        NAV_REQUEST_DONE_DIR.mkdir(parents=True, exist_ok=True)

        if not LABELS_FILE.exists():
            raise FileNotFoundError(f"라벨 파일 없음: {LABELS_FILE}")

        self.labels = load_labels(LABELS_FILE)
        self.client = ActionClient(self, NavigateToPose, "navigate_to_pose")

        self.processing = False
        self.timer = self.create_timer(0.5, self.check_request)

        self.get_logger().info("[NAV_REQUEST] watcher started")
        self.get_logger().info(f"[NAV_REQUEST] labels file: {LABELS_FILE}")
        self.get_logger().info(f"[NAV_REQUEST] request dir: {NAV_REQUEST_DIR}")
        self.get_logger().info(f"[NAV_REQUEST] loaded labels: {list(self.labels.keys())}")

    def check_request(self):
        if self.processing:
            return

        request_files = sorted(NAV_REQUEST_DIR.glob("*.json"))

        if not request_files:
            return

        request_file = request_files[0]
        self.processing = True

        try:
            with open(request_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            target_text = (
                data.get("place_name")
                or data.get("destination")
                or data.get("target")
                or data.get("goal")
                or data.get("text")
                or data.get("user_text")
                or ""
            )

            target = self.extract_label(target_text)

            if not target:
                self.get_logger().error(f"[NAV_REQUEST] 목적지 추출 실패: {data}")
                self.move_to_done(request_file)
                self.processing = False
                return

            self.get_logger().info(f"[NAV_REQUEST] STT/요청 텍스트: {target_text}")
            self.get_logger().info(f"[NAV_REQUEST] 추출된 목적지: {target}")

            zone = self.labels[target]
            pose = zone_to_pose(zone)
            pose.header.stamp = self.get_clock().now().to_msg()

            self.get_logger().info(
                f"[NAV_REQUEST] Nav2 goal: "
                f"x={pose.pose.position.x:.3f}, "
                f"y={pose.pose.position.y:.3f}, "
                f"qz={pose.pose.orientation.z:.4f}, "
                f"qw={pose.pose.orientation.w:.4f}"
            )

            self.send_goal(pose, target, request_file)

        except Exception as e:
            self.get_logger().error(f"[NAV_REQUEST] 처리 실패: {e}")
            self.processing = False

    def extract_label(self, text: str):
        text = str(text).strip()

        if text in self.labels:
            return text

        for label in self.labels.keys():
            if label in text:
                return label

        return None

    def send_goal(self, pose: PoseStamped, label: str, request_file: Path):
        self.get_logger().info("[NAV_REQUEST] nav2 서버 대기 중...")

        if not self.client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error("[NAV_REQUEST] navigate_to_pose action server 없음")
            self.processing = False
            return

        goal = NavigateToPose.Goal()
        goal.pose = pose

        self.get_logger().info(f"[NAV_REQUEST] 목적지 전송: {label}")

        future = self.client.send_goal_async(
            goal,
            feedback_callback=self.feedback_callback
        )

        future.add_done_callback(
            lambda f: self.goal_response_callback(f, request_file, label)
        )

    def goal_response_callback(self, future, request_file: Path, label: str):
        goal_handle = future.result()

        if not goal_handle.accepted:
            self.get_logger().error("[NAV_REQUEST] 목표 거부됨")
            self.processing = False
            return

        self.get_logger().info("[NAV_REQUEST] 목표 수락 → 이동 시작")
        self.move_to_done(request_file)

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            lambda f: self.result_callback(f, label)
        )

    def feedback_callback(self, feedback_msg):
        distance = feedback_msg.feedback.distance_remaining
        self.get_logger().info(f"[NAV_REQUEST] 남은 거리: {distance:.2f} m")

    def result_callback(self, future, label: str):
        status = future.result().status

        if status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info(f"[NAV_REQUEST] 도착 완료: {label}")
        else:
            self.get_logger().warn(f"[NAV_REQUEST] 이동 실패 또는 중단 status={status}")

        self.processing = False

    def move_to_done(self, request_file: Path):
        done_path = NAV_REQUEST_DONE_DIR / request_file.name

        try:
            shutil.move(str(request_file), str(done_path))
            self.get_logger().info(f"[NAV_REQUEST] 요청 완료 처리: {done_path}")
        except Exception as e:
            self.get_logger().error(f"[NAV_REQUEST] 파일 이동 실패: {e}")


def main(args=None):
    rclpy.init(args=args)
    node = NavRequestWatcher()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
