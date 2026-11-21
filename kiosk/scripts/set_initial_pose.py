#!/usr/bin/env python3
# =========================================================================
# set_initial_pose.py — RViz의 "2D Pose Estimate"를 자동으로 대신한다.
#
#   map_labels.json 의 "초기 위치" zone → /initialpose 로 발행 → amcl 이 수신하면
#   map→odom TF가 생기고 위치추정이 시작된다.
#
#   사용법:  ./scripts/set_initial_pose.sh          (기본: "초기 위치")
#            ./scripts/set_initial_pose.sh 원무과    (다른 zone으로 지정도 가능)
#
# 주의: 로봇이 실제로 그 위치·방향에 서 있을 때만 의미가 있다.
#       (엉뚱한 곳에서 발행하면 amcl이 잘못된 위치로 추정을 시작한다)
# =========================================================================
import json
import math
import sys
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseWithCovarianceStamped
from tf2_ros import Buffer, TransformListener

LABELS_PATH = Path("/mnt/ssd/cart_ros2/src/hospital_mission/map/map_labels.json")
DEFAULT_ZONE = "초기 위치"
BASE_CANDIDATES = ("base_footprint", "base_link")
MAP_FRAME = "map"

# amcl 초기 분포의 불확실성. RViz 2D Pose Estimate 가 쓰는 기본값과 동일한 수준.
COV_XY = 0.25          # x, y 분산 (m^2)
COV_YAW = 0.06853892   # yaw 분산 (rad^2)

PUBLISH_TIMES = 3      # amcl이 첫 발행을 놓치는 경우가 있어 여러 번 보낸다
PUBLISH_INTERVAL = 0.5
SUB_WAIT_SEC = 15.0    # amcl(구독자)이 뜰 때까지 대기
VERIFY_SEC = 10.0      # 발행 후 map→base TF 확인 대기


def load_zone(name):
    if not LABELS_PATH.exists():
        raise FileNotFoundError(f"map_labels.json 이 없습니다: {LABELS_PATH}")
    with open(LABELS_PATH, encoding="utf-8") as f:
        zones = json.load(f).get("zones", [])
    for z in zones:
        if z.get("name") == name:
            return z
    have = ", ".join(z.get("name", "?") for z in zones)
    raise KeyError(f"'{name}' zone이 map_labels.json에 없습니다. (있는 zone: {have})")


def zone_to_xyq(zone):
    """zone의 nav_goal → (x, y, qz, qw). qz/qw가 없으면 yaw_deg로 계산."""
    ng = zone.get("nav_goal")
    if not isinstance(ng, dict) or "x" not in ng or "y" not in ng:
        raise ValueError(f"{zone.get('name')}: nav_goal(x,y)이 없습니다.")
    x, y = float(ng["x"]), float(ng["y"])
    if "qz" in ng and "qw" in ng:
        return x, y, float(ng["qz"]), float(ng["qw"])
    yaw = math.radians(float(ng.get("yaw_deg", 0.0)))
    return x, y, math.sin(yaw / 2.0), math.cos(yaw / 2.0)


def yaw_deg_from_quat(z, w):
    return math.degrees(math.atan2(2.0 * w * z, 1.0 - 2.0 * z * z))


class InitialPoseSetter(Node):
    def __init__(self):
        super().__init__("set_initial_pose")
        self.pub = self.create_publisher(PoseWithCovarianceStamped, "/initialpose", 10)
        self.buf = Buffer()
        self.listener = TransformListener(self.buf, self)

    def wait_for_amcl(self, timeout):
        """amcl이 /initialpose를 구독할 때까지 대기. 구독자가 없으면 발행해도 사라진다."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.pub.get_subscription_count() > 0:
                return True
            rclpy.spin_once(self, timeout_sec=0.2)
        return False

    def publish(self, x, y, qz, qw):
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = MAP_FRAME
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.pose.position.x = x
        msg.pose.pose.position.y = y
        msg.pose.pose.position.z = 0.0
        msg.pose.pose.orientation.z = qz
        msg.pose.pose.orientation.w = qw
        cov = [0.0] * 36
        cov[0] = COV_XY     # x
        cov[7] = COV_XY     # y
        cov[35] = COV_YAW   # yaw
        msg.pose.covariance = cov

        for i in range(PUBLISH_TIMES):
            msg.header.stamp = self.get_clock().now().to_msg()
            self.pub.publish(msg)
            rclpy.spin_once(self, timeout_sec=0.05)
            if i < PUBLISH_TIMES - 1:
                time.sleep(PUBLISH_INTERVAL)

    def current_pose(self, timeout):
        """map→base TF (위치추정이 살아있는지 확인용)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            rclpy.spin_once(self, timeout_sec=0.2)
            for cand in BASE_CANDIDATES:
                try:
                    tf = self.buf.lookup_transform(MAP_FRAME, cand, rclpy.time.Time())
                    t, q = tf.transform.translation, tf.transform.rotation
                    return t.x, t.y, q.z, q.w, cand
                except Exception:
                    continue
        return None


def main():
    zone_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ZONE

    try:
        zone = load_zone(zone_name)
        x, y, qz, qw = zone_to_xyq(zone)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"✗ {exc}")
        sys.exit(1)

    rclpy.init()
    node = InitialPoseSetter()

    print(f"  목표 초기 위치 '{zone_name}': "
          f"x={x:.4f} y={y:.4f} yaw={yaw_deg_from_quat(qz, qw):.2f}°")

    if not node.wait_for_amcl(SUB_WAIT_SEC):
        print("✗ /initialpose 구독자(amcl)가 없습니다. 내비게이션이 떠 있는지 확인하세요.")
        node.destroy_node()
        rclpy.shutdown()
        sys.exit(1)

    node.publish(x, y, qz, qw)
    print(f"  /initialpose 발행 완료 ({PUBLISH_TIMES}회)")

    got = node.current_pose(VERIFY_SEC)
    if got is None:
        print("✗ 발행 후에도 map→base TF가 없습니다. amcl 상태를 확인하세요.")
        node.destroy_node()
        rclpy.shutdown()
        sys.exit(1)

    gx, gy, gqz, gqw, base = got
    err = math.hypot(gx - x, gy - y)
    dyaw = abs(yaw_deg_from_quat(gqz, gqw) - yaw_deg_from_quat(qz, qw))
    dyaw = min(dyaw, 360.0 - dyaw)
    print(f"  확인: 현재 추정 위치 x={gx:.4f} y={gy:.4f} "
          f"yaw={yaw_deg_from_quat(gqz, gqw):.2f}°  (frame {base})")
    print(f"  오차: 거리 {err:.3f} m, 방향 {dyaw:.2f}°")

    # amcl은 발행값을 그대로 쓰지 않고 스캔매칭으로 보정하므로 약간의 차이는 정상이다.
    if err > 1.0 or dyaw > 25.0:
        print("  ⚠ 오차가 큽니다. 로봇이 실제로 초기 위치에 있는지 확인하세요.")
    else:
        print("  ✓ 초기 위치 지정 정상")

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
