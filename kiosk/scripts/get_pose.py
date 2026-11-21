#!/usr/bin/env python3
# =========================================================================
# get_pose.py — 로봇의 현재 위치(map 기준)를 읽어 출력한다.
#
#   사용법:  ./scripts/get_pose.sh
#            (내부적으로 ROS2 환경을 source 한 뒤 이 파일을 실행)
#
# 용도: RViz에서 2D Pose Estimate로 수동 지정한 "주차 위치"를 좌표로 받아적어
#       두면, 이후 기동 스크립트가 그 좌표를 /initialpose 로 자동 발행할 수 있다.
#
# 읽는 방법: TF(map → base_footprint/base_link)를 조회한다.
#   · /amcl_pose 토픽은 로봇이 정지해 있으면 갱신 발행이 없어 대기가 걸릴 수 있어
#     상시 브로드캐스트되는 TF를 1순위로 쓴다.
# =========================================================================
import math
import time
import sys

import rclpy
from rclpy.node import Node
from tf2_ros import Buffer, TransformListener

BASE_CANDIDATES = ("base_footprint", "base_link")
MAP_FRAME = "map"
TIMEOUT_SEC = 10.0


def yaw_from_quat(z, w):
    """평면 주행(roll=pitch=0) 가정에서 z,w만으로 yaw 계산."""
    return math.atan2(2.0 * w * z, 1.0 - 2.0 * z * z)


class PoseReader(Node):
    def __init__(self):
        super().__init__("get_pose")
        self.buf = Buffer()
        self.listener = TransformListener(self.buf, self)


def main():
    rclpy.init()
    node = PoseReader()

    tf = None
    base_used = None
    deadline = time.time() + TIMEOUT_SEC
    while time.time() < deadline and tf is None:
        rclpy.spin_once(node, timeout_sec=0.2)
        for cand in BASE_CANDIDATES:
            try:
                tf = node.buf.lookup_transform(MAP_FRAME, cand, rclpy.time.Time())
                base_used = cand
                break
            except Exception:
                continue

    if tf is None:
        print()
        print("✗ 현재 위치를 읽지 못했습니다.")
        print(f"  {MAP_FRAME} → {'/'.join(BASE_CANDIDATES)} TF가 없습니다.")
        print("  확인할 것:")
        print("   · 브링업/내비게이션이 실행 중인가?")
        print("   · RViz에서 2D Pose Estimate로 초기 위치를 지정했는가?")
        print("     (지정 전에는 amcl이 map→odom TF를 발행하지 않습니다)")
        node.destroy_node()
        rclpy.shutdown()
        sys.exit(1)

    t = tf.transform.translation
    q = tf.transform.rotation
    yaw = yaw_from_quat(q.z, q.w)
    yaw_deg = math.degrees(yaw)

    print()
    print("=" * 62)
    print(f" 현재 로봇 위치  (frame: {MAP_FRAME} → {base_used})")
    print("=" * 62)
    print(f"  x     = {t.x:.4f}")
    print(f"  y     = {t.y:.4f}")
    print(f"  yaw   = {yaw_deg:.2f}°   ({yaw:.4f} rad)")
    print(f"  quat  = z:{q.z:.4f}  w:{q.w:.4f}")
    print()
    print("-" * 62)
    print(" [A] map_labels.json 의 nav_goal 형식 (장소 좌표로 등록할 때)")
    print("-" * 62)
    print('      "nav_goal": {')
    print(f'        "x": {t.x:.3f}, "y": {t.y:.3f},')
    print(f'        "qz": {q.z:.4f}, "qw": {q.w:.4f},')
    print('        "frame_id": "map"')
    print("      }")
    print()
    print("-" * 62)
    print(" [B] 초기 위치 자동 지정용 (기동 스크립트가 발행할 값)")
    print("-" * 62)
    print(f"  INIT_X={t.x:.4f}")
    print(f"  INIT_Y={t.y:.4f}")
    print(f"  INIT_QZ={q.z:.4f}")
    print(f"  INIT_QW={q.w:.4f}")
    print()
    print("  ※ 지금 이 자리가 '주차 위치'라면 위 4개 값을 적어두세요.")
    print("     다음 단계에서 이 값을 /initialpose 로 자동 발행하게 만듭니다.")
    print()

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
