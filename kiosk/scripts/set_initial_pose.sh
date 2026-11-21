#!/usr/bin/env bash
# =========================================================================
# set_initial_pose.sh — RViz "2D Pose Estimate"를 자동으로 대신한다.
#
#   사용법:  ./scripts/set_initial_pose.sh          (기본: "초기 위치")
#            ./scripts/set_initial_pose.sh 원무과
#
# 전제: 브링업 + 내비게이션(amcl)이 실행 중이어야 한다.
# ※ rclpy가 필요하므로 시스템 python3 로 실행한다(stt의 .venv에는 rclpy 없음).
# =========================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/ros_env.sh"
exec python3 "$HERE/set_initial_pose.py" "$@"
