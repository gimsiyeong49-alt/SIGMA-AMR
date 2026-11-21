#!/usr/bin/env bash
# =========================================================================
# run_app.sh — 앱 실제 STT 모드 원클릭 기동 (터미널 하나로 전부)
#
#   사용법:  ./scripts/run_app.sh [포트]      (기본 8000) · 종료 Ctrl+C
#
# 하는 일(순서대로):
#   1) 마이크 충돌 정리 — stt CLI / 중복 kiosk_server 종료 (마이크는 1프로세스만 점유 가능)
#   2) whisper-server(8080) 확인, 없으면 백그라운드 기동 후 로드 대기
#   3) USB 마이크 카드 자동감지 (serve.sh가 처리) — stale STT_AUDIO_DEVICE 무시
#   4) 앱 서버(kiosk_server) 기동 → 브라우저에서 http://localhost:PORT/ 접속
#
# 실제 STT로 동작하려면 src/js/config.js 의 useMock=false 여야 함(이미 false).
# =========================================================================
set -euo pipefail

PORT="${1:-8000}"
HERE="$(cd "$(dirname "$0")" && pwd)"

WHISPER_DIR="/mnt/ssd/cart_ros2/src/stt_package/whisper.cpp"
WHISPER_BIN="./build/bin/whisper-server"
WHISPER_MODEL="models/ggml-medium.bin"
WHISPER_URL="http://127.0.0.1:8080/"
LOG_DIR="$HERE/../logs"
mkdir -p "$LOG_DIR"

echo "════════════════════════════════════════════════════════"
echo " [1/4] 마이크 충돌 정리 (stt CLI / 중복 앱서버 종료)"
echo "════════════════════════════════════════════════════════"
# 브래킷 트릭([s]): 이 스크립트 자신의 명령줄에 매칭돼 self-kill 되는 것을 방지
pkill -f "[b]in/stt --device" 2>/dev/null && echo "  · stt CLI 종료함" || echo "  · stt CLI 없음(OK)"
pkill -f "[k]iosk_server.py"  2>/dev/null && echo "  · 기존 kiosk_server 종료함" || echo "  · 실행중 kiosk_server 없음(OK)"
sleep 1

echo
echo "════════════════════════════════════════════════════════"
echo " [2/4] whisper-server(8080) 확인/기동"
echo "════════════════════════════════════════════════════════"
if curl -s -o /dev/null -w "%{http_code}" "$WHISPER_URL" 2>/dev/null | grep -q "200"; then
  echo "  · 이미 실행 중(OK)"
else
  if [ ! -x "$WHISPER_DIR/build/bin/whisper-server" ]; then
    echo "  ✗ whisper-server 바이너리 없음: $WHISPER_DIR/build/bin/whisper-server" >&2
    echo "    (whisper.cpp 빌드 필요) — 중단합니다." >&2
    exit 1
  fi
  echo "  · 백그라운드 기동: $WHISPER_BIN -m $WHISPER_MODEL --port 8080 (setsid=Ctrl+C 무관)"
  # setsid = 새 세션/프로세스그룹 → 앱을 Ctrl+C 해도 whisper-server는 살아남는다.
  # (다음 실행 때 '이미 실행 중'으로 재사용 → 모델 재로드 없음)
  # CUDA 환경변수는 사용자 원본 실행법과 동일하게 명시(GPU 가속).
  ( cd "$WHISPER_DIR" \
    && export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda-11.4}" \
    && export PATH="/usr/local/cuda-11.4/bin:$PATH" \
    && export LD_LIBRARY_PATH="/usr/local/cuda-11.4/lib64:${LD_LIBRARY_PATH:-}" \
    && setsid "$WHISPER_BIN" -m "$WHISPER_MODEL" --host 127.0.0.1 --port 8080 \
      > "$LOG_DIR/whisper.log" 2>&1 < /dev/null & )
  echo -n "  · 모델 로드 대기"
  for i in $(seq 1 40); do
    if curl -s -o /dev/null -w "%{http_code}" "$WHISPER_URL" 2>/dev/null | grep -q "200"; then
      echo " → 준비 완료(OK)"; break
    fi
    echo -n "."; sleep 1
    if [ "$i" -eq 40 ]; then echo; echo "  ✗ whisper-server 응답 없음(로그: $LOG_DIR/whisper.log)" >&2; exit 1; fi
  done
fi

echo
echo "════════════════════════════════════════════════════════"
echo " [2.5/4] TTS 서버(MeloTTS, 5002) 확인/기동"
echo "════════════════════════════════════════════════════════"
TTS_VENV="/mnt/ssd/cart_ros2/src/tts_package/tts/.venv/bin/python3"
if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:5002/" 2>/dev/null | grep -q "200"; then
  echo "  · 이미 실행 중(OK)"
elif [ -x "$TTS_VENV" ]; then
  echo "  · 백그라운드 기동 (모델 로드+워밍업 ~25초, 준비 전엔 브라우저 TTS 폴백)"
  # setsid = 앱을 Ctrl+C 해도 TTS 서버는 살아남는다. 준비를 기다리지 않음(앱은 먼저 뜸).
  setsid "$TTS_VENV" -u "$HERE/tts_server.py" > "$LOG_DIR/tts_server.log" 2>&1 < /dev/null &
else
  echo "  ⚠ TTS venv 없음($TTS_VENV) → TTS 생략(브라우저 TTS로 동작)"
fi

echo
echo "════════════════════════════════════════════════════════"
echo " [3/4] USB 마이크 자동감지 → [4/4] 앱 서버 기동"
echo "════════════════════════════════════════════════════════"
# stale export가 있으면 serve.sh가 그대로 존중하므로, 자동감지가 동작하도록 해제
unset STT_AUDIO_DEVICE
echo "  · 브라우저: http://localhost:${PORT}/   (마이크 버튼 → 말하기)"
echo "  · 종료: Ctrl+C"
echo

exec "$HERE/serve.sh" "$PORT"
