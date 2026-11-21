#!/usr/bin/env bash
# =========================================================================
# kiosk_backend.sh — ROS 백엔드 순차 기동 (브링업 → 내비 → 초기위치 → 복귀감시)
#
#   kiosk_boot.sh 가 이 스크립트를 setsid 로 "완전히 분리"해서 실행한다.
#   그래야 크로미움을 exec 하거나 사용자가 키오스크에서 빠져나와 세션이 흔들려도
#   이 초기화 시퀀스가 SIGHUP 으로 죽지 않고 끝까지(특히 set_initial_pose 까지) 완료된다.
#   (기존엔 ( ... ) & 서브셸이라 세션과 함께 죽어 2D pose 지정이 안 됐음)
#
#   ※ 로봇이 실제로 '초기 위치'에 있을 때만 set_initial_pose 가 올바르다.
# =========================================================================
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJ="$(cd "$HERE/.." && pwd)"
LOG_DIR="$PROJ/logs"; mkdir -p "$LOG_DIR"
exec >>"$LOG_DIR/kiosk_backend.log" 2>&1

echo ""
echo "==== kiosk_backend 시작 PID=$$ ===="
# shellcheck disable=SC1091
source "$HERE/ros_env.sh"
log(){ echo "[backend $(cut -d' ' -f1 /proc/uptime 2>/dev/null)s] $*"; }

launch_bg(){ local logf="$1"; shift; setsid bash -c 'exec "$@"' _ "$@" >>"$logf" 2>&1 < /dev/null & }
node_up(){ ros2 node list 2>/dev/null | grep -q -- "$1"; }
wait_node(){ local p="$1" label="$2" t="${3:-90}"; local end=$((SECONDS+t))
  while [ $SECONDS -lt $end ]; do node_up "$p" && { log "$label 준비 OK"; return 0; }; sleep 2; done
  log "⚠ $label 이 ${t}s 안에 안 뜸"; return 1; }

# ── 브링업 ──────────────────────────────────────────────────────────────
if node_up "robot_state_publisher"; then log "브링업 이미 실행 중"; else
  log "브링업 기동"; launch_bg "$LOG_DIR/bringup.log" ros2 launch agv_body agv_bringup.launch.py
  wait_node "robot_state_publisher" "브링업" 90
fi

# ── 내비게이션 ──────────────────────────────────────────────────────────
if node_up "amcl"; then log "내비 이미 실행 중"; else
  log "내비 기동"; launch_bg "$LOG_DIR/navigation.log" ros2 launch hospital_mission navigation.launch.py
fi
# 초기위치 발행은 amcl 구독이 필요 → amcl 준비를 반드시 기다린다
wait_node "amcl" "amcl" 120
wait_node "bt_navigator" "bt_navigator" 60 || true

# ── 초기 위치 자동 지정 (2D Pose Estimate 대체) ─────────────────────────
log "초기 위치 지정 시작 (로봇이 초기 위치에 있다고 가정)"
if python3 "$HERE/set_initial_pose.py" 2>&1 | sed 's/^/[initpose] /'; then
  log "초기 위치 지정 완료"
else
  log "⚠ 초기 위치 지정 실패 (로그의 [initpose] 확인)"
fi

# ── 복귀 감시 ───────────────────────────────────────────────────────────
if pgrep -f "[r]eturn_home_watcher.py" >/dev/null; then log "복귀감시 이미 실행 중"; else
  log "복귀감시 기동"; launch_bg "$LOG_DIR/return_home.log" python3 "$HERE/return_home_watcher.py"
fi

log "ROS 백엔드 시퀀스 완료"
