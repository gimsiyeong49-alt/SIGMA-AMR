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
NAV_REQUEST_FAILED_DIR = Path("/mnt/ssd/cart_ros2/src/llm_package/bus/nav_request_failed")


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
    text = str(text).strip()

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


class NavToLabelAuto(Node):
    def __init__(self):
        super().__init__("nav_to_label_auto")

        NAV_REQUEST_DIR.mkdir(parents=True, exist_ok=True)
        NAV_REQUEST_DONE_DIR.mkdir(parents=True, exist_ok=True)
        NAV_REQUEST_FAILED_DIR.mkdir(parents=True, exist_ok=True)

        if not LABELS_FILE.exists():
            raise FileNotFoundError(f"라벨 파일 없음: {LABELS_FILE}")

        self.labels = load_labels(LABELS_FILE)

        self.client = ActionClient(self, NavigateToPose, "navigate_to_pose")

        self.processing = False
        self.current_file = None
        self.current_label = None

        self.timer = self.create_timer(0.5, self.check_nav_request)

        self.get_logger().info("===== nav_to_label_auto started =====")
        self.get_logger().info(f"labels file: {LABELS_FILE}")
        self.get_logger().info(f"nav_request dir: {NAV_REQUEST_DIR}")
        self.get_logger().info(f"loaded labels: {list(self.labels.keys())}")

    def check_nav_request(self):
        if self.processing:
            return

        files = sorted(NAV_REQUEST_DIR.glob("*.json"))

        if not files:
            return

        request_file = files[0]
        self.processing = True
        self.current_file = request_file

        try:
            with open(request_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            text = self.get_request_text(data)
            label = extract_label(text, self.labels)

            self.get_logger().info(f"request file: {request_file}")
            self.get_logger().info(f"request text: {text}")

            if not label:
                self.get_logger().error(f"목적지 라벨 추출 실패: {text}")
                self.get_logger().error(f"가능한 라벨: {list(self.labels.keys())}")
                self.move_file(request_file, NAV_REQUEST_FAILED_DIR)
                self.reset_state()
                return

            self.current_label = label

            zone = self.labels[label]
            pose = zone_to_pose(zone)
            pose.header.stamp = self.get_clock().now().to_msg()

            self.get_logger().info(f"목적지 라벨: {label}")
            self.get_logger().info(
                f"Nav2 goal: x={pose.pose.position.x:.3f}, "
                f"y={pose.pose.position.y:.3f}, "
                f"qz={pose.pose.orientation.z:.4f}, "
                f"qw={pose.pose.orientation.w:.4f}"
            )

            self.send_goal(pose, label)

        except Exception as e:
            self.get_logger().error(f"nav_request 처리 실패: {e}")
            self.move_file(request_file, NAV_REQUEST_FAILED_DIR)
            self.reset_state()

    def get_request_text(self, data: dict) -> str:
        for key in [
            "place_name",
            "destination",
            "target",
            "goal",
            "text",
            "user_text",
            "stt_text",
            "recognized_text",
            "original_user_text",
        ]:
            value = data.get(key)
            if value:
                return str(value).strip()

        return ""

    def send_goal(self, pose: PoseStamped, label: str):
        self.get_logger().info("Nav2 navigate_to_pose 서버 대기 중...")

        if not self.client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error("Nav2 action server 없음: /navigate_to_pose")
            if self.current_file:
                self.move_file(self.current_file, NAV_REQUEST_FAILED_DIR)
            self.reset_state()
            return

        goal = NavigateToPose.Goal()
        goal.pose = pose

        self.get_logger().info(f"Nav2 목적지 전송: {label}")

        future = self.client.send_goal_async(
            goal,
            feedback_callback=self.feedback_callback
        )

        future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        try:
            goal_handle = future.result()
        except Exception as e:
            self.get_logger().error(f"goal response 오류: {e}")
            if self.current_file:
                self.move_file(self.current_file, NAV_REQUEST_FAILED_DIR)
            self.reset_state()
            return

        if not goal_handle.accepted:
            self.get_logger().error("Nav2 goal 거부됨")
            if self.current_file:
                self.move_file(self.current_file, NAV_REQUEST_FAILED_DIR)
            self.reset_state()
            return

        self.get_logger().info("Nav2 goal 수락됨 → 이동 시작")

        if self.current_file:
            self.move_file(self.current_file, NAV_REQUEST_DONE_DIR)

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.result_callback)

    def feedback_callback(self, feedback_msg):
        distance = feedback_msg.feedback.distance_remaining
        self.get_logger().info(f"남은 거리: {distance:.2f} m")

    def result_callback(self, future):
        try:
            status = future.result().status
        except Exception as e:
            self.get_logger().error(f"result 오류: {e}")
            self.reset_state()
            return

        if status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info(f"도착 완료: {self.current_label}")
        else:
            self.get_logger().warn(f"이동 실패 또는 중단 status={status}")

        self.reset_state()

    def move_file(self, src_file: Path, dst_dir: Path):
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst_file = dst_dir / src_file.name

        try:
            if dst_file.exists():
                dst_file.unlink()

            shutil.move(str(src_file), str(dst_file))
            self.get_logger().info(f"파일 이동: {src_file} -> {dst_file}")

        except Exception as e:
            self.get_logger().error(f"파일 이동 실패: {e}")

    def reset_state(self):
        self.processing = False
        self.current_file = None
        self.current_label = None


def main(args=None):
    rclpy.init(args=args)

    node = NavToLabelAuto()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
