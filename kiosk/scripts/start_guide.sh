#!/usr/bin/env bash
# =========================================================================
# start_guide.sh — 병원 안내 기동 (브링업 이후 나머지 전부)
#
#   전제: 브링업은 부팅 시 agv-bringup.service 가 이미 띄워 둔다.
#         (설치: sudo ./scripts/install_boot_bringup.sh)
#
#   사용법:  ./scripts/start_guide.sh [앱포트]      (기본 8000) · 종료 Ctrl+C   — RViz 켬
#            ./scripts/start_guide_norviz.sh [앱포트]                         — RViz 끔(시연·실사용, CPU 절약)
#            ※ 실행 전 로봇을 '초기 위치'에 세워 둘 것(2단계에서 그 위치로 지정)
#
#   전제: 브링업(ROS2 포함)은 이미 떠 있다 — 확인하지 않는다.
#   순서:
#     [1] 내비게이션 hospital_mission/navigation.launch.py
#     [2] 초기 위치 자동 지정 (RViz 2D Pose Estimate 대체)
#     [3] 복귀 감시 (도착 → N초 뒤 초기 위치로)
#     [4] 앱 환경(LLM·PIN) → run_app.sh: STT(whisper) → TTS(MeloTTS) → 마이크 → 앱 서버
#         마이크·스피커·음성 대사 목록(tts_enabled.txt)은 start_voice_ui.sh 와 동일
#
#   시작·종료 시 '밀린 요청' 정리(clear_pending): 이전 실행에서 실패해 남은 것이
#     다음 실행 때 뒤늦게 실행되던 문제(갑자기 주행 / 갑자기 말함) 방지.
#     · Nav2 목적지 요청(bus/nav_request/*.json) → bus/nav_request_discarded/ 로 이동(삭제 안 함)
#     · TTS 서버의 대기·재생 중 문장 → POST /flush 로 버림
#     · STT 녹음 프로세스(bin/stt) 종료, 로봇 상태(kiosk_status.json) → idle
#   Ctrl+C 시: 복귀감시·내비·앱 서버만 종료.
#     · 브링업은 유지(부팅 서비스 소유)  → 끄려면 sudo systemctl stop agv-bringup
#     · STT/TTS 서버도 유지(모델 로딩이 느려서 다음 실행을 빠르게) → run_app.sh 설계 그대로
#
#   sudo 불필요. (브링업까지 직접 띄우는 예전 방식은 start_all.sh --bringup)
# =========================================================================
set -euo pipefail

PORT="${1:-8000}"
USE_RVIZ="${USE_RVIZ:-true}"   # start_guide_norviz.sh 가 false 로 넘김
HERE="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$HERE/../logs"
mkdir -p "$LOG_DIR"

NAV_PGID=""
RETURN_PGID=""
_CLEANED=0
BUS="/mnt/ssd/cart_ros2/src/llm_package/bus"
TTS_FLUSH_URL="http://127.0.0.1:${TTS_PORT:-5002}/flush"

# 이전에 처리되지 못하고 남은 요청들을 버린다(시작 직전 + 종료 시).
clear_pending() {
  local n=0 f ts
  ts="$(date +%Y%m%d_%H%M%S)"
  if compgen -G "$BUS/nav_request/*.json" > /dev/null; then
    mkdir -p "$BUS/nav_request_discarded"
    for f in "$BUS"/nav_request/*.json; do
      mv -f "$f" "$BUS/nav_request_discarded/${ts}_$(basename "$f")" && n=$((n+1))
    done
  fi
  echo "  · Nav2 미처리 요청 정리: ${n}건 (보관: bus/nav_request_discarded/)"
  if curl -s -m 3 -X POST "$TTS_FLUSH_URL" 2>/dev/null | grep -q '"flushed"'; then
    echo "  · TTS 대기 문장 비움"
  elif curl -s -m 2 -o /dev/null "http://127.0.0.1:${TTS_PORT:-5002}/" 2>/dev/null; then
    echo "  ⚠ TTS 서버가 예전 버전(/flush 없음) — 한 번 재시작 필요: pkill -f tts_server.py"
  fi
  pkill -f "[b]in/stt --device" 2>/dev/null && echo "  · STT 녹음 프로세스 종료" || true
  printf '{"state": "idle", "place": "", "updated_at": %s}\n' "$(date +%s.%N)" \
    > "$BUS/kiosk_status.json.tmp" && mv -f "$BUS/kiosk_status.json.tmp" "$BUS/kiosk_status.json" || true
}

# 런치를 새 세션(setsid)으로 띄우고 그 PGID를 돌려준다(Ctrl+C 가 직접 닿지 않게, 정리는 cleanup 이 담당).
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
  [ "$_CLEANED" = "1" ] && return
  _CLEANED=1
  echo
  echo "── 종료: 이 스크립트가 띄운 것 정리 ──"
  for entry in "복귀감시:$RETURN_PGID" "정리:" "내비게이션:$NAV_PGID"; do
    name="${entry%%:*}"; pgid="${entry##*:}"
    [ "$name" = "정리" ] && { clear_pending; continue; }
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
  echo "  · 브링업은 유지(부팅 서비스). 끄려면: sudo systemctl stop agv-bringup"
  echo "  · STT/TTS 서버는 유지(다음 실행 가속)."
  echo "  완료."
}
trap cleanup EXIT INT TERM

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

# Nav2 노드가 '떠 있는 것'과 '활성(active)'은 다르다 — 기동 중 lifecycle_manager 가 죽으면 노드는 떠 있어도
#  비활성이라 주행 목표가 전부 거부된다(2026-11-12 실제 발생). 핵심 노드가 active 가 될 때까지 확인.
wait_nav_active() {
  local timeout="${1:-90}" deadline n st ok
  deadline=$(( SECONDS + timeout ))
  echo -n "  · Nav2 활성 상태 확인(controller·planner·bt_navigator)"
  while [ $SECONDS -lt $deadline ]; do
    ok=1
    for n in controller_server planner_server bt_navigator; do
      st="$(timeout 8 ros2 lifecycle get "/$n" 2>/dev/null | head -1)"
      case "$st" in active*) ;; *) ok=0 ;; esac
    done
    if [ "$ok" = "1" ]; then echo " → 모두 active(OK)"; return 0; fi
    echo -n "."
    sleep 3
  done
  echo
  echo "  ✗ Nav2가 ${timeout}초 안에 활성화되지 않았습니다 → 이대로면 주행 목표가 '거부'됩니다." >&2
  for n in controller_server planner_server bt_navigator; do
    echo "     /$n: $(timeout 8 ros2 lifecycle get "/$n" 2>/dev/null | head -1)" >&2
  done
  echo "    로그 확인: grep -nE 'ERROR|FATAL|died|terminate' logs/navigation.log | tail" >&2
  return 1
}
hdr() {
  echo
  echo "════════════════════════════════════════════════════════"
  echo " $1"
  echo "════════════════════════════════════════════════════════"
}

# ROS2 환경 (ros2 명령을 쓰려면 이 셸에서 필요 — 확인 단계 아님)
# shellcheck disable=SC1091
source "$HERE/ros_env.sh"

# ── 이전 실행의 밀린 요청 정리 ──────────────────────────────────────────
hdr "[0/4] 이전 실행의 밀린 요청 정리"
clear_pending

# ── [1] 내비게이션 ──────────────────────────────────────────────────────
hdr "[1/4] 내비게이션 (navigation.launch.py)"
if node_running "amcl"; then
  echo "  · 이미 실행 중 → 건너뜀 (중복 기동 방지)"
else
  echo "  · 기동 (로그: logs/navigation.log) · RViz $([ "$USE_RVIZ" = "true" ] && echo 켬 || echo 끔)"
  NAV_PGID=$(start_launch "$LOG_DIR/.navigation.pgid" "$LOG_DIR/navigation.log" \
               ros2 launch hospital_mission navigation.launch.py use_rviz:="$USE_RVIZ")
  wait_for_node "amcl" "amcl(위치추정)" 120 || {
    echo "  로그 마지막 20줄:"; tail -20 "$LOG_DIR/navigation.log" >&2; exit 1; }
  wait_for_node "bt_navigator" "bt_navigator(경로계획)" 60 || true
fi

# ── [2] 초기 위치 자동 지정 ─────────────────────────────────────────────
hdr "[2/4] 초기 위치 자동 지정 (2D Pose Estimate 대체)"
echo "  ※ 로봇이 실제로 '초기 위치'에 서 있어야 합니다."
if ! python3 "$HERE/set_initial_pose.py"; then
  echo "  ✗ 초기 위치 지정 실패 → 이동 명령이 위험하므로 중단합니다." >&2
  exit 1
fi
# Nav2 활성 확인은 초기 위치 '다음'에 — 경로 계획기(planner_server)는 map 좌표(=초기 위치가 정해져야 생김)가
#  있어야 활성화를 마치므로, 그 전에 확인하면 서로 기다리다 시간 초과(2026-11-12 실수)
wait_nav_active 90 || { echo "  Ctrl+C 로 끄고 다시 실행해 주세요(내비게이션까지 새로 띄워야 함)." >&2; exit 1; }

# ── [3] 복귀 감시 ───────────────────────────────────────────────────────
hdr "[3/4] 복귀 감시 (도착 → ${RETURN_DELAY_SEC:-5}초 뒤 초기 위치로)"
if pgrep -f "[r]eturn_home_watcher.py" > /dev/null; then
  echo "  · 이미 실행 중 → 건너뜀"
else
  RETURN_PGID=$(start_launch "$LOG_DIR/.return.pgid" "$LOG_DIR/return_home.log" \
                  python3 "$HERE/return_home_watcher.py")
  sleep 1
  if kill -0 "-$RETURN_PGID" 2>/dev/null; then
    echo "  · 기동 완료 (로그: logs/return_home.log)"
  else
    echo "  ⚠ 복귀 감시 기동 실패 — 안내는 되지만 자동 복귀는 동작하지 않습니다."
    tail -5 "$LOG_DIR/return_home.log" 2>/dev/null || true
  fi
fi

# ── [4] 앱 환경 + STT/TTS/앱 서버 ───────────────────────────────────────
hdr "[4/4] 앱 환경(LLM·PIN) → STT → TTS → 앱 서버"
export LLM_MATCH_ENABLE=1
export OPENAI_MODEL="${OPENAI_MODEL:-gpt-4o-mini}"
if [ -z "${OPENAI_API_KEY:-}" ] && [ -f "$HERE/../.openai_key" ]; then
  export OPENAI_API_KEY="$(tr -d '[:space:]' < "$HERE/../.openai_key")"
fi
if [ -n "${OPENAI_API_KEY:-}" ]; then
  echo "  · LLM 매칭 ON (모델 $OPENAI_MODEL) — 문진·트리아지·장소매칭"
else
  echo "  · LLM 매칭 대기 — OPENAI_API_KEY 없음(.openai_key). 지금은 규칙매칭만."
fi
if [ -z "${ADMIN_PIN:-}" ]; then
  if [ -f "$HERE/../.admin_pin" ]; then
    export ADMIN_PIN="$(tr -d '[:space:]' < "$HERE/../.admin_pin")"
  else
    export ADMIN_PIN="0000"
  fi
fi
echo "  · 관리자 PIN 설정됨(?nurse=1 · ?doctor=1)"
# 로봇이 소리 내어 말할 대사 목록 — start_voice_ui.sh 와 같은 tts_enabled.txt 사용(저장 즉시 반영)
export TTS_ONLY_FILE="$(cd "$HERE/.." && pwd)/tts_enabled.txt"
TTS_ON="$(sed -e 's/#.*//' -e 's/[[:space:]]//g' "$TTS_ONLY_FILE" 2>/dev/null | grep -v '^$' | tr '\n' ' ' || true)"
echo "  · TTS 켠 대사: ${TTS_ON:-없음(전부 무음)} — 편집: tts_enabled.txt (저장 즉시 반영)"
echo "  · 화면: chromium --user-data-dir=/tmp/k-patient --kiosk \"http://localhost:${PORT}/\""
echo
# exec 하지 않는다 — trap(정리)이 동작해야 하므로 포그라운드 자식으로 실행.
"$HERE/run_app.sh" "$PORT"
