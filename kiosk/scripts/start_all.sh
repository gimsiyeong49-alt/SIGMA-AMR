#!/usr/bin/env bash
# =========================================================================
# start_all.sh — AGV 스택 기동 (내비게이션부터)
#
#   사용법:  ./scripts/start_all.sh [앱포트]            (기본 8000) · 종료 Ctrl+C
#            ./scripts/start_all.sh --bringup [앱포트]  (브링업까지 직접 띄우는 예전 방식)
#
# 브링업(장치권한·팬·전원모드 + agv_bringup)은 부팅 시 agv-bringup.service 가 자동으로 띄운다
#   (설치: sudo ./scripts/install_boot_bringup.sh). 이 스크립트는 브링업이 떠 있는지 확인만 하고
#   내비게이션부터 이어서 진행한다.
#
# 순서(각 단계는 "떴는지 확인"하고 다음으로 넘어간다. 고정 sleep 미사용):
#   [1] (--bringup 일 때만) 장치 권한(sudo) + 팬 + SSD 마운트
#   [2] ROS2 환경 (ros_env.sh)                 ← DOMAIN_ID=30, CYCLONEDDS_URI unset
#   [3] 브링업 확인 (부팅 서비스) — --bringup 이면 직접 기동
#   [4] 내비게이션 hospital_mission/navigation.launch.py
#   [5] 초기 위치 자동 지정(= RViz 2D Pose Estimate 대체)
#   [6] 복귀 감시 노드 (도착 감지 → N초 뒤 초기 위치로 자동 복귀)
#   [7] 앱 + whisper (run_app.sh, 포그라운드)
#
# 안전장치:
#   · 이미 실행 중인 브링업/내비는 다시 띄우지 않고 건너뛴다(중복 기동 = 이중 모터제어
#     위험). 수동으로 띄워둔 상태에서 실행해도 안전하다.
#   · Ctrl+C 하면 이 스크립트가 띄운 것(내비·복귀감시·앱)만 정리한다.
#     부팅 서비스가 띄운 브링업은 그대로 살아 있다.
# =========================================================================
set -euo pipefail

WITH_BRINGUP=0
if [ "${1:-}" = "--bringup" ]; then WITH_BRINGUP=1; shift; fi
PORT="${1:-8000}"
HERE="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$HERE/../logs"
mkdir -p "$LOG_DIR"

BRINGUP_PGID=""
NAV_PGID=""
RETURN_PGID=""
_CLEANED=0

# 런치를 새 세션(setsid)으로 띄우고 그 PGID를 표준출력으로 돌려준다.
#  · $! 를 쓰지 않는 이유: setsid 는 상황에 따라 fork 하므로 $! 가 이미 죽은
#    래퍼 PID일 수 있다(그러면 정리 때 엉뚱한 그룹을 kill 하게 된다).
#  · 대신 새 세션의 리더가 된 bash 가 자기 $$(=PGID)를 파일에 적게 하고 그것을 읽는다.
#    exec 로 런치를 덮어쓰므로 PID/PGID가 그대로 유지된다.
# 사용법: PGID=$(start_launch <pgid파일> <로그파일> <명령...>)
start_launch() {
  local pgidfile="$1" logfile="$2"
  shift 2
  rm -f "$pgidfile"
  setsid bash -c 'echo $$ > "$1"; shift; exec "$@"' _ "$pgidfile" "$@" \
      >> "$logfile" 2>&1 < /dev/null &
  for _ in $(seq 1 25); do
    [ -s "$pgidfile" ] && break
    sleep 0.2
  done
  cat "$pgidfile" 2>/dev/null || true
}

cleanup() {
  [ "$_CLEANED" = "1" ] && return    # EXIT/INT 중복 호출 방지
  _CLEANED=1
  echo
  echo "── 종료: 이 스크립트가 띄운 것 정리 ──"
  for entry in "복귀감시:$RETURN_PGID" "내비게이션:$NAV_PGID" "브링업:$BRINGUP_PGID"; do
    name="${entry%%:*}"; pgid="${entry##*:}"
    if [ -n "$pgid" ] && kill -0 "-$pgid" 2>/dev/null; then
      echo "  · $name 종료 중..."
      kill -INT "-$pgid" 2>/dev/null || true
      for _ in $(seq 1 20); do
        kill -0 "-$pgid" 2>/dev/null || break
        sleep 0.5
      done
      kill -0 "-$pgid" 2>/dev/null && kill -TERM "-$pgid" 2>/dev/null || true
    fi
  done
  [ -z "$BRINGUP_PGID" ] && echo "  · 브링업은 유지됨(부팅 서비스 소유). 끄려면: sudo systemctl stop agv-bringup"
  echo "  완료."
}
trap cleanup EXIT INT TERM

# ── 공통 대기 함수 ───────────────────────────────────────────────────────
# ros2 node list 에 특정 노드가 나타날 때까지 대기
wait_for_node() {
  local pattern="$1" label="$2" timeout="${3:-90}"
  local deadline=$(( SECONDS + timeout ))
  echo -n "  · $label 대기"
  while [ $SECONDS -lt $deadline ]; do
    if ros2 node list 2>/dev/null | grep -q -- "$pattern"; then
      echo " → 확인(OK)"
      return 0
    fi
    echo -n "."
    sleep 2
  done
  echo
  echo "  ✗ $label 이 ${timeout}초 안에 뜨지 않았습니다." >&2
  return 1
}

node_running() { ros2 node list 2>/dev/null | grep -q -- "$1"; }

# ── [1] 장치 권한 / 팬 / 마운트 (--bringup 일 때만) ─────────────────────
echo "════════════════════════════════════════════════════════"
echo " [1/7] 장치 권한 + 팬 + SSD 마운트"
echo "════════════════════════════════════════════════════════"
if [ "$WITH_BRINGUP" = "1" ]; then
echo "  · sudo 권한이 필요합니다(장치 권한 부여). 비밀번호를 한 번 입력하면 이후 단계는 자동입니다."
sudo -v

if mountpoint -q /mnt/ssd; then
  echo "  · /mnt/ssd 이미 마운트됨(건너뜀)"
else
  echo "  · /mnt/ssd 마운트"
  sudo mount /dev/nvme0n1p1 /mnt/ssd
fi

# 팬은 실패해도 기동을 막지 않는다(냉각 설정일 뿐)
sudo /usr/bin/jetson_clocks --fan 2>/dev/null && echo "  · 팬 설정 완료" \
  || echo "  ⚠ jetson_clocks --fan 실패(무시하고 계속)"

# 기존 cm / cl / ci 별칭과 동일 (매 부팅마다 필요)
for dev in /dev/ttyMD /dev/ttyLidar_F /dev/ttyLidar_R /dev/ttyIMU; do
  if [ -e "$dev" ]; then
    sudo chmod 766 "$dev" && echo "  · 권한 부여: $dev"
  else
    echo "  ⚠ 장치 없음: $dev  (연결 확인 필요)"
  fi
done
else
  echo "  · 건너뜀 — 부팅 서비스(agv-bringup)가 처리"
fi

# ── [2] ROS2 환경 ───────────────────────────────────────────────────────
echo
echo "════════════════════════════════════════════════════════"
echo " [2/7] ROS2 환경"
echo "════════════════════════════════════════════════════════"
# shellcheck disable=SC1091
source "$HERE/ros_env.sh"
echo "  · ROS_DOMAIN_ID=$ROS_DOMAIN_ID  RMW=$RMW_IMPLEMENTATION  LOCALHOST_ONLY=$ROS_LOCALHOST_ONLY"
echo "  · CYCLONEDDS_URI=${CYCLONEDDS_URI:-(unset)}"

# ── [3] 브링업 ──────────────────────────────────────────────────────────
echo
echo "════════════════════════════════════════════════════════"
echo " [3/7] 브링업 (agv_bringup.launch.py)"
echo "════════════════════════════════════════════════════════"
if node_running "robot_state_publisher"; then
  echo "  · 실행 중(부팅 서비스 또는 수동) → 재사용"
elif [ "$WITH_BRINGUP" != "1" ]; then
  # 부팅 직후엔 브링업이 아직 올라오는 중일 수 있으니 잠시 기다린다
  wait_for_node "robot_state_publisher" "브링업(부팅 서비스)" 60 || {
    echo "  브링업이 떠 있지 않습니다. 확인:" >&2
    echo "    systemctl status agv-bringup      (로그: logs/bringup.log)" >&2
    echo "    시작: sudo systemctl start agv-bringup" >&2
    echo "    서비스 미설치면: sudo ./scripts/install_boot_bringup.sh" >&2
    echo "    또는 예전 방식: ./scripts/start_all.sh --bringup" >&2
    exit 1; }
else
  echo "  · 기동 (로그: logs/bringup.log)"
  BRINGUP_PGID=$(start_launch "$LOG_DIR/.bringup.pgid" "$LOG_DIR/bringup.log" \
                   ros2 launch agv_body agv_bringup.launch.py)
  wait_for_node "robot_state_publisher" "브링업" 90 || {
    echo "  로그 마지막 20줄:"; tail -20 "$LOG_DIR/bringup.log" >&2; exit 1; }
fi

# ── [4] 내비게이션 ──────────────────────────────────────────────────────
echo
echo "════════════════════════════════════════════════════════"
echo " [4/7] 내비게이션 (navigation.launch.py)"
echo "════════════════════════════════════════════════════════"
if node_running "amcl"; then
  echo "  · 이미 실행 중 → 건너뜀 (중복 기동 방지)"
else
  echo "  · 기동 (로그: logs/navigation.log)"
  NAV_PGID=$(start_launch "$LOG_DIR/.navigation.pgid" "$LOG_DIR/navigation.log" \
               ros2 launch hospital_mission navigation.launch.py)
  wait_for_node "amcl" "amcl(위치추정)" 120 || {
    echo "  로그 마지막 20줄:"; tail -20 "$LOG_DIR/navigation.log" >&2; exit 1; }
  wait_for_node "bt_navigator" "bt_navigator(경로계획)" 60 || true
fi

# ── [5] 초기 위치 자동 지정 ─────────────────────────────────────────────
echo
echo "════════════════════════════════════════════════════════"
echo " [5/7] 초기 위치 자동 지정 (2D Pose Estimate 대체)"
echo "════════════════════════════════════════════════════════"
echo "  ※ 로봇이 실제로 '초기 위치'에 서 있어야 합니다."
if ! python3 "$HERE/set_initial_pose.py"; then
  echo "  ✗ 초기 위치 지정 실패 → 이동 명령이 위험하므로 중단합니다." >&2
  exit 1
fi

# ── [6] 복귀 감시 노드 ──────────────────────────────────────────────────
echo
echo "════════════════════════════════════════════════════════"
echo " [6/7] 복귀 감시 (도착 → ${RETURN_DELAY_SEC:-5}초 뒤 초기 위치로)"
echo "════════════════════════════════════════════════════════"
if pgrep -f "[r]eturn_home_watcher.py" > /dev/null; then
  echo "  · 이미 실행 중 → 건너뜀"
else
  RETURN_PGID=$(start_launch "$LOG_DIR/.return.pgid" "$LOG_DIR/return_home.log" \
                  python3 "$HERE/return_home_watcher.py")
  sleep 1
  if kill -0 "-$RETURN_PGID" 2>/dev/null; then
    echo "  · 기동 완료 (로그: logs/return_home.log)"
  else
    echo "  ⚠ 복귀 감시 노드 기동 실패 — 안내는 되지만 자동 복귀는 동작하지 않습니다."
    tail -5 "$LOG_DIR/return_home.log" 2>/dev/null || true
  fi
fi

# ── [6.5] 앱 환경(UI 시스템): LLM 매칭 + 관리자 PIN (start_ui.sh와 동일) ──
#   UI 화면 파일은 두 스크립트가 같은 src/ 를 서빙하므로 동일하다. 차이는 이 환경변수뿐:
#   · LLM 매칭/문진/트리아지(OpenAI)  · 관리자·의사 화면 PIN 보호.
#   run_app.sh→serve.sh→kiosk_server.py 로 그대로 상속된다.
echo
echo "════════════════════════════════════════════════════════"
echo " [6.5/7] 앱 환경(UI): LLM 매칭 + 관리자 PIN"
echo "════════════════════════════════════════════════════════"
export LLM_MATCH_ENABLE=1
export OPENAI_MODEL="${OPENAI_MODEL:-gpt-4o-mini}"
if [ -z "${OPENAI_API_KEY:-}" ] && [ -f "$HERE/../.openai_key" ]; then
  export OPENAI_API_KEY="$(tr -d '[:space:]' < "$HERE/../.openai_key")"
fi
if [ -n "${OPENAI_API_KEY:-}" ]; then
  echo "  · LLM 매칭 ON (모델 $OPENAI_MODEL) — 문진·트리아지·장소매칭에 OpenAI 사용"
else
  echo "  · LLM 매칭 대기 — OPENAI_API_KEY 없음(.openai_key 파일에 키 넣으면 켜짐). 지금은 규칙매칭만."
fi
if [ -z "${ADMIN_PIN:-}" ]; then
  if [ -f "$HERE/../.admin_pin" ]; then
    export ADMIN_PIN="$(tr -d '[:space:]' < "$HERE/../.admin_pin")"
  else
    export ADMIN_PIN="0000"   # 데모 기본값. .admin_pin 파일 만들면 교체됨.
  fi
fi
echo "  · 관리자 PIN 설정됨(?admin=1 · ?doctor=1 접근 시 필요). 변경: 루트에 .admin_pin 파일."

# ── [7] 앱 + whisper ────────────────────────────────────────────────────
echo
echo "════════════════════════════════════════════════════════"
echo " [7/7] 앱 + whisper (run_app.sh)"
echo "════════════════════════════════════════════════════════"
# exec 하지 않는다 — trap(정리)이 동작해야 하므로 포그라운드 자식으로 실행.
"$HERE/run_app.sh" "$PORT"
