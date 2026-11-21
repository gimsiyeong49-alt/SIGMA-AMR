#!/usr/bin/env bash
# =========================================================================
# start_voice_ui.sh — UI + 음성(STT·TTS)만 기동 (로봇 주행 없음)
#
#   start_guide.sh 에서 로봇 부분(내비·초기 위치·복귀 감시)을 뺀 버전.
#   로봇을 움직이지 않고 화면·문진·음성 흐름을 손볼 때 쓴다.
#
#   사용법:  ./scripts/start_voice_ui.sh [앱포트]      (기본 8000) · 종료 Ctrl+C
#
#   순서:
#     [0] 안전 확인 — 내비 목적지 처리기(nav_request_watcher)가 떠 있으면 중단
#         (떠 있으면 화면에서 목적지를 고를 때 로봇이 실제로 움직이므로)
#     [1] 이전 실행의 밀린 요청 정리 (start_guide.sh 와 동일)
#     [2] 앱 환경(LLM·PIN) → run_app.sh: STT(whisper) → TTS(MeloTTS) → 마이크 → 앱 서버
#
#   TTS: 프로젝트 루트의 tts_enabled.txt 에 켠 대사만 로봇이 말한다(기본 전부 무음). start_guide.sh 도 동일.
#        '#' 을 지우고 저장하면 바로 반영. TTS 서버·기능 자체는 그대로 떠 있다.
#
#   화면에서 목적지를 골라도 로봇은 움직이지 않는다(요청 파일만 생김).
#   그 요청 파일은 종료 시 bus/nav_request_discarded/ 로 옮겨 버린다
#   → 나중에 start_guide.sh 를 켰을 때 뒤늦게 주행하지 않음.
#
#   Ctrl+C 시: 앱 서버 종료 + 밀린 요청 정리. STT/TTS 서버는 유지(run_app.sh 설계).
#   브링업(부팅 서비스)은 건드리지 않는다. sudo 불필요.
# =========================================================================
set -euo pipefail

PORT="${1:-8000}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BUS="/mnt/ssd/cart_ros2/src/llm_package/bus"
TTS_FLUSH_URL="http://127.0.0.1:${TTS_PORT:-5002}/flush"
_CLEANED=0

# 이전에 처리되지 못하고 남은 요청들을 버린다(시작 직전 + 종료 시). start_guide.sh 와 동일.
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

cleanup() {
  [ "$_CLEANED" = "1" ] && return
  _CLEANED=1
  echo
  echo "── 종료: 밀린 요청 정리 ──"
  clear_pending
  echo "  · STT/TTS 서버는 유지(다음 실행 가속)."
  echo "  완료."
}

hdr() {
  echo
  echo "════════════════════════════════════════════════════════"
  echo " $1"
  echo "════════════════════════════════════════════════════════"
}

# ── [0] 안전 확인 ───────────────────────────────────────────────────────
hdr "[0/2] 안전 확인 (로봇 주행 없음)"
if pgrep -f "[n]av_request_watcher" > /dev/null; then
  echo "  ✗ 내비게이션(nav_request_watcher)이 실행 중입니다." >&2
  echo "    이대로면 화면에서 목적지를 고를 때 로봇이 실제로 움직입니다." >&2
  echo "    start_guide.sh 를 먼저 Ctrl+C 로 끈 뒤 다시 실행하세요." >&2
  exit 1
fi
echo "  · 내비게이션 꺼져 있음 → 목적지를 골라도 로봇은 움직이지 않음"
trap cleanup EXIT INT TERM

# ── [1] 밀린 요청 정리 ──────────────────────────────────────────────────
hdr "[1/2] 이전 실행의 밀린 요청 정리"
clear_pending

# ── [2] 앱 환경 + STT/TTS/앱 서버 ───────────────────────────────────────
hdr "[2/2] 앱 환경(LLM·PIN) → STT → TTS → 앱 서버"
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
export TTS_ONLY_FILE="$(cd "$HERE/.." && pwd)/tts_enabled.txt"
TTS_ON="$(sed -e 's/#.*//' -e 's/[[:space:]]//g' "$TTS_ONLY_FILE" 2>/dev/null | grep -v '^$' | tr '\n' ' ' || true)"
echo "  · TTS 켠 대사: ${TTS_ON:-없음(전부 무음)} — 편집: tts_enabled.txt (저장 즉시 반영)"
echo "  · 화면: chromium --user-data-dir=/tmp/k-patient --kiosk \"http://localhost:${PORT}/\""
echo
# exec 하지 않는다 — trap(정리)이 동작해야 하므로 포그라운드 자식으로 실행.
"$HERE/run_app.sh" "$PORT"
