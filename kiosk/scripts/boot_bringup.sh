#!/usr/bin/env bash
# =========================================================================
# boot_bringup.sh — 부팅 시 브링업 실행 (wjs 로 실행: agv-bringup.service 의 ExecStart)
#   start_all.sh 는 이 브링업을 재사용하고 내비게이션부터 이어서 띄운다.
#   start_all.sh 를 Ctrl+C 로 꺼도 이 브링업은 계속 살아 있다(서비스 소유).
#   수동 제어:  sudo systemctl stop|start|restart agv-bringup
# =========================================================================
HERE="$(cd "$(dirname "$0")" && pwd)"
LOG="$HERE/../logs/bringup.log"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "[boot_bringup $(date '+%F %T')] 브링업 시작"
# shellcheck disable=SC1091
source "$HERE/ros_env.sh"
exec ros2 launch agv_body agv_bringup.launch.py
