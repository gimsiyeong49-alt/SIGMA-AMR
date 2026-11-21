#!/usr/bin/env bash
# =========================================================================
# return_home_watcher.sh — 도착 감지 → N초 뒤 초기 위치 자동 복귀
#
#   사용법:  ./scripts/return_home_watcher.sh      (Ctrl+C 종료)
#
#   환경변수(선택):
#     RETURN_DELAY_SEC  도착 후 대기 시간(기본 10)
#     ARRIVE_RADIUS     도착 판정 반경 m (기본 0.8)
#
# 전제: 브링업 + 내비게이션 실행 중(TF map→base 필요).
# ※ rclpy 필요 → 시스템 python3 사용.
# =========================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/ros_env.sh"
exec python3 "$HERE/return_home_watcher.py" "$@"
