#!/usr/bin/env bash
# =========================================================================
# get_pose.sh — 로봇의 현재 위치(map 기준)를 출력한다.
#
#   사용법:  ./scripts/get_pose.sh
#
# 전제: 브링업 + 내비게이션이 실행 중이고, RViz에서 2D Pose Estimate로
#       초기 위치를 이미 지정한 상태여야 한다.
#       (지정 전에는 amcl이 map→odom TF를 발행하지 않아 좌표를 읽을 수 없다)
#
# ROS2 환경을 source 한 뒤 get_pose.py 를 실행한다.
# ※ stt의 .venv 파이썬에는 rclpy가 없으므로 반드시 시스템 python3 을 쓴다.
# =========================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROS_SETUP="/opt/ros/galactic/setup.bash"
WS_SETUP="/mnt/ssd/cart_ros2/install/setup.bash"

[ -f "$ROS_SETUP" ] || { echo "✗ ROS2 setup을 찾을 수 없습니다: $ROS_SETUP" >&2; exit 1; }

# set -u 상태에서 ROS setup 스크립트가 미설정 변수를 건드려도 죽지 않게 잠시 해제
set +u
# shellcheck disable=SC1090
source "$ROS_SETUP"
[ -f "$WS_SETUP" ] && source "$WS_SETUP"
set -u

exec python3 "$HERE/get_pose.py"
