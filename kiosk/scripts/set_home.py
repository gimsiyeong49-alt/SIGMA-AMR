#!/usr/bin/env python3
# =========================================================================
# set_home.py — 지금 로봇이 서 있는 자세를 "초기 위치"로 등록한다.
#
#   사용법:  ./scripts/set_home.sh
#
#   1) 로봇을 원하는 주차 자세로 물리적으로 세운다(방향까지).
#   2) 이 스크립트를 실행하면 현재 TF(map→base) 자세가 map_labels.json 의
#      "초기 위치" nav_goal 로 저장된다. 복귀는 이 자세를 목표로 삼는다.
#
# 안전: 수정 전 자동 백업. 다른 zone(원무과/내과/외과/track)은 건드리지 않는다.
# =========================================================================
import json
import math
import shutil
import sys
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from tf2_ros import Buffer, TransformListener

LABELS_PATH = Path("/mnt/ssd/cart_ros2/src/hospital_mission/map/map_labels.json")
HOME_ZONE = "초기 위치"
MAP_FRAME = "map"
BASE_CANDIDATES = ("base_footprint", "base_link")
TIMEOUT_SEC = 10.0
SAMPLES = 10          # 여러 번 읽어 평균 → amcl 추정의 미세 흔들림 완화


class PoseReader(Node):
    def __init__(self):
        super().__init__("set_home")
        self.buf = Buffer()
        self.listener = TransformListener(self.buf, self)

    def read(self):
        for cand in BASE_CANDIDATES:
            try:
                tf = self.buf.lookup_transform(MAP_FRAME, cand, rclpy.time.Time())
                t, q = tf.transform.translation, tf.transform.rotation
                return t.x, t.y, math.atan2(2 * q.w * q.z, 1 - 2 * q.z * q.z), cand
            except Exception:
                continue
        return None


def main():
    rclpy.init()
    node = PoseReader()

    samples = []
    base_used = None
    deadline = time.time() + TIMEOUT_SEC
    while time.time() < deadline and len(samples) < SAMPLES:
        rclpy.spin_once(node, timeout_sec=0.2)
        got = node.read()
        if got:
            samples.append(got[:3])
            base_used = got[3]

    if not samples:
        print("\n✗ 현재 자세를 읽지 못했습니다 (map→base TF 없음).")
        print("  브링업/내비게이션이 실행 중이고 위치추정이 되어 있어야 합니다.")
        node.destroy_node(); rclpy.shutdown(); sys.exit(1)

    xs = sum(s[0] for s in samples) / len(samples)
    ys = sum(s[1] for s in samples) / len(samples)
    # 각도는 산술평균이 아니라 벡터평균 (179°와 -179°의 평균이 0°가 되지 않도록)
    yaw = math.atan2(sum(math.sin(s[2]) for s in samples) / len(samples),
                     sum(math.cos(s[2]) for s in samples) / len(samples))
    qz, qw = math.sin(yaw / 2), math.cos(yaw / 2)

    with open(LABELS_PATH, encoding="utf-8") as f:
        data = json.load(f)

    before = None
    found = False
    for z in data.get("zones", []):
        if z.get("name") == HOME_ZONE:
            before = dict(z.get("nav_goal") or {})
            z["nav_goal"] = {"x": round(xs, 4), "y": round(ys, 4),
                             "yaw_deg": round(math.degrees(yaw), 2),
                             "qz": round(qz, 4), "qw": round(qw, 4)}
            z["created_at"] = time.time()
            found = True
            break

    if not found:
        print(f"\n✗ map_labels.json 에 '{HOME_ZONE}' zone 이 없습니다.")
        node.destroy_node(); rclpy.shutdown(); sys.exit(1)

    backup = LABELS_PATH.with_suffix(
        f".json.bak.{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(LABELS_PATH, backup)
    with open(LABELS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print()
    print("=" * 58)
    print(f" '{HOME_ZONE}' 등록 완료   (frame: {MAP_FRAME} → {base_used})")
    print("=" * 58)
    if before:
        print(f"  이전: x={before.get('x')}  y={before.get('y')}  "
              f"yaw={before.get('yaw_deg')}°")
    print(f"  현재: x={xs:.4f}  y={ys:.4f}  yaw={math.degrees(yaw):.2f}°")
    print(f"  ({len(samples)}회 측정 평균)")
    print(f"  백업: {backup.name}")
    print()
    print("  ※ 복귀 감시 노드는 이 파일을 매번 새로 읽으므로 재시작 불필요.")
    print()

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
