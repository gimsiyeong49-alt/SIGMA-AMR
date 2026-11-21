#!/usr/bin/env bash
# live_drive_monitor.sh — 주행 실시간 감시(회전 걸림·슬립·덜컹·명령 없음). 사용법: ./scripts/live_drive_monitor.sh  · 종료 Ctrl+C
# 안내 서버(start_guide)와 따로, 다른 터미널에서 켜 두면 됨. 읽기만 하고 로봇에 명령은 안 보냄.
HERE="$(cd "$(dirname "$0")" && pwd)"
source /opt/ros/galactic/setup.bash
source /mnt/ssd/cart_ros2/install/setup.bash
exec python3 -u "$HERE/live_drive_monitor.py" "$@"
