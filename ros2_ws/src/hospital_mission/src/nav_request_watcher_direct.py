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


# ===== 경로 설정 =====
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


def zone_to_pose(zone: dict) -> PoseStamped:
    pose = PoseStamped()
    pose.header.frame_id = zone.get("frame_id", "map")

    # 1순위: nav_goal이 있으면 이 좌표를 사용
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

    # 2순위: rectangle이면 중심 좌표 사용
    elif zone.get("type") == "rectangle":
        x_min = float(zone["x_min"])
        x_max = float(zone["x_max"])
        y_min = float(zone["y_min"])
        y_max = float(zone["y_max"])

        pose.pose.position.x = (x_min + x_max) / 2.0
        pose.pose.position.y = (y_min + y_max) / 2.0
        pose.pose.position.z = 0.0

        yaw_deg = float(zone.get("rotation_deg", 0.0))

    # 3순위: point 형식
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


class NavRequestWatcherDirect(Node):
    def __init__(self):
        super().__init__("nav_request_watcher_direct")

        NAV_REQUEST_DIR.mkdir(parents=True, exist_ok=True)
        NAV_REQUEST_DONE_DIR.mkdir(parents=True, exist_ok=True)
        NAV_REQUEST_FAILED_DIR.mkdir(parents=True, exist_ok=True)

        if not LABELS_FILE.exists():
            raise FileNotFoundError(f"라벨 파일 없음: {LABELS_FILE}")

        self.labels = load_labels(LABELS_FILE)

        self.client = ActionClient(
            self,
            NavigateToPose,
            "navigate_to_pose"
        )

        self.processing = False
        self.current_request_file = None
        self.current_label = None

        self.timer = self.create_timer(0.5, self.check_request)

        self.get_logger().info("===== nav_request_watcher_direct started =====")
        self.get_logger().info(f"labels file: {LABELS_FILE}")
        self.get_logger().info(f"nav_request dir: {NAV_REQUEST_DIR}")
        self.get_logger().info(f"loaded labels: {list(self.labels.keys())}")

    def check_request(self):
        if self.processing:
            return

        files = sorted(NAV_REQUEST_DIR.glob("*.json"))

        if not files:
            return

        request_file = files[0]
        self.processing = True
        self.current_request_file = request_file

        try:
            with open(request_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            raw_text = self.get_text_from_request(data)
            target = self.extract_label(raw_text)

            self.get_logger().info(f"request file: {request_file}")
            self.get_logger().info(f"raw text/place: {raw_text}")

            if not target:
                self.get_logger().error(f"목적지 추출 실패. 가능한 라벨: {list(self.labels.keys())}")
                self.move_file(request_file, NAV_REQUEST_FAILED_DIR)
                self.reset_state()
                return

            self.current_label = target

            zone = self.labels[target]
            pose = zone_to_pose(zone)
            pose.header.stamp = self.get_clock().now().to_msg()

            self.get_logger().info(f"추출된 목적지: {target}")
            self.get_logger().info(
                f"Nav2 goal 좌표: "
                f"x={pose.pose.position.x:.3f}, "
                f"y={pose.pose.position.y:.3f}, "
                f"qz={pose.pose.orientation.z:.4f}, "
                f"qw={pose.pose.orientation.w:.4f}"
            )

            self.send_nav2_goal(pose, target)

        except Exception as e:
            self.get_logger().error(f"요청 처리 중 오류: {e}")
            self.move_file(request_file, NAV_REQUEST_FAILED_DIR)
            self.reset_state()

    def get_text_from_request(self, data: dict) -> str:
        # run_goal/location/STT 결과에서 올 수 있는 키들을 모두 허용
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

    def extract_label(self, text: str):
        text = str(text).strip()

        # 정확히 일치
        if text in self.labels:
            return text

        # 문장 안에 라벨명이 포함된 경우
        # 예: "화장실로 가줘" 안에서 "화장실" 추출
        for label in self.labels.keys():
            if label in text:
                return label

        return None

    def send_nav2_goal(self, pose: PoseStamped, label: str):
        self.get_logger().info("Nav2 navigate_to_pose action server 대기 중...")

        if not self.client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error("Nav2 action server 없음: /navigate_to_pose")
            if self.current_request_file:
                self.move_file(self.current_request_file, NAV_REQUEST_FAILED_DIR)
            self.reset_state()
            return

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = pose

        self.get_logger().info(f"목적지 전송: {label}")

        future = self.client.send_goal_async(
            goal_msg,
            feedback_callback=self.feedback_callback
        )

        future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        try:
            goal_handle = future.result()
        except Exception as e:
            self.get_logger().error(f"goal response 오류: {e}")
            if self.current_request_file:
                self.move_file(self.current_request_file, NAV_REQUEST_FAILED_DIR)
            self.reset_state()
            return

        if not goal_handle.accepted:
            self.get_logger().error("Nav2 goal 거부됨")
            if self.current_request_file:
                self.move_file(self.current_request_file, NAV_REQUEST_FAILED_DIR)
            self.reset_state()
            return

        self.get_logger().info("Nav2 goal 수락됨 → 이동 시작")

        if self.current_request_file:
            self.move_file(self.current_request_file, NAV_REQUEST_DONE_DIR)

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.result_callback)

    def feedback_callback(self, feedback_msg):
        distance = feedback_msg.feedback.distance_remaining
        self.get_logger().info(f"남은 거리: {distance:.2f} m")

    def result_callback(self, future):
        try:
            result = future.result()
            status = result.status
        except Exception as e:
            self.get_logger().error(f"result 오류: {e}")
            self.reset_state()
            return

        if status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info(f"도착 완료: {self.current_label}")
        else:
            self.get_logger().warn(f"이동 실패 또는 중단. status={status}")

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
        self.current_request_file = None
        self.current_label = None


def main(args=None):
    rclpy.init(args=args)

    node = NavRequestWatcherDirect()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
