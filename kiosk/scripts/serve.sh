#!/usr/bin/env bash
# =========================================================================
# serve.sh — 키오스크 서버 (정적 파일 + STT/nav 브리지) · 실행 방법 일원화
#
# 사용법:  ./scripts/serve.sh [포트]      (기본 8000) · 종료 Ctrl+C
#
# 실행 환경(확정): stt 패키지의 .venv 파이썬으로 실행한다.
#   · 이유: 녹음 의존성(sounddevice 등)이 보장된 사용자 검증 환경(= stt CLI와 동일).
#   · llm(map_labels 매칭)은 .venv에 rclpy가 없어 폴백(EXTRA_ALIASES)으로 동작하지만
#     결과는 동일(원무과/내과/외과/약국). /goal·/nav 는 map_labels.json 직접 사용 → 무관.
#   · .venv가 없으면 시스템 python3로 폴백.
#
# 실제 STT: whisper-server(8080) + 마이크 필요(없어도 정적 UI·매칭은 동작).
#   · 환경변수 override 가능: STT_AUDIO_DEVICE, WHISPER_SERVER_URL
# =========================================================================
set -euo pipefail

PORT="${1:-8000}"
HERE="$(cd "$(dirname "$0")" && pwd)"

VENV_PY="/mnt/ssd/cart_ros2/src/stt_package/stt/.venv/bin/python3"
PY="python3"
[ -x "$VENV_PY" ] && PY="$VENV_PY"

# USB 마이크 카드 자동 감지 (카드번호는 재부팅/재연결마다 바뀔 수 있음).
# 사용자가 STT_AUDIO_DEVICE 를 직접 지정했으면 그대로 존중한다. 웹캠 마이크는 제외.
#  1순위 reSpeaker XVF3800(카드 이름 C16K6Ch, 6ch) → 카드 '이름'으로 지정, 0번 채널(DSP 처리 음성)만 사용
#  2순위 예전 USB 마이크("Usb Audio Device", 1ch)
if [ -z "${STT_AUDIO_DEVICE:-}" ]; then
  set +e
  RESPK_CARD=$(arecord -l 2>/dev/null | grep -i "reSpeaker" | sed -E 's/^card [0-9]+: ([^ ]+) .*/\1/' | head -1)
  MIC_CARD=$(arecord -l 2>/dev/null | grep "Usb Audio Device" | grep -iv webcam | sed -E 's/^card ([0-9]+):.*/\1/' | head -1)
  set -e
  if [ -n "${RESPK_CARD:-}" ]; then
    export STT_AUDIO_DEVICE="plughw:CARD=${RESPK_CARD},DEV=0"
    # 인식용 소리 = 0번(처리 음성), 말소리 감지 = 2번(마이크 원음 — 0번은 자동 게인으로 배경음이 출렁임)
    export STT_CHANNELS="${STT_CHANNELS:-6}" STT_CHANNEL="${STT_CHANNEL:-0}" STT_VAD_CHANNEL="${STT_VAD_CHANNEL:-2}"
    echo "[serve] 마이크 자동감지: reSpeaker → STT_AUDIO_DEVICE=$STT_AUDIO_DEVICE (인식 채널 ${STT_CHANNEL} · 감지 채널 ${STT_VAD_CHANNEL} / ${STT_CHANNELS})"
  elif [ -n "${MIC_CARD:-}" ]; then
    export STT_AUDIO_DEVICE="plughw:${MIC_CARD},0"
    echo "[serve] 마이크 자동감지: STT_AUDIO_DEVICE=$STT_AUDIO_DEVICE  (card $MIC_CARD = USB Audio Device)"
  else
    echo "[serve] ⚠ USB 마이크 자동감지 실패 → 기본값(plughw:0,0). 'arecord -l' 확인 후 STT_AUDIO_DEVICE 지정 권장."
  fi
else
  echo "[serve] STT_AUDIO_DEVICE(수동)=$STT_AUDIO_DEVICE"
fi

# 마이크 캡처 게인 설정. 기본이 0%면 발화 RMS가 낮아 VAD가 감지를 못한다.
# 퍼센트로 지정(장치별 범위 달라도 이식성 유지). MIC_CAPTURE_GAIN 로 조정 가능.
MIC_GAIN="${MIC_CAPTURE_GAIN:-40%}"
CARD_NUM=$(printf '%s' "${STT_AUDIO_DEVICE:-}" | sed -nE 's/^plughw:([0-9]+),.*/\1/p')
if [ -n "$CARD_NUM" ]; then
  set +e
  amixer -c "$CARD_NUM" sset 'Auto Gain Control' off >/dev/null 2>&1
  if amixer -c "$CARD_NUM" sset Mic "$MIC_GAIN" >/dev/null 2>&1; then
    echo "[serve] 마이크 캡처 게인: card $CARD_NUM Mic=$MIC_GAIN (VAD 감지 안정화)"
  elif amixer -c "$CARD_NUM" sset Capture "$MIC_GAIN" >/dev/null 2>&1; then
    echo "[serve] 마이크 캡처 게인: card $CARD_NUM Capture=$MIC_GAIN"
  else
    echo "[serve] ⚠ 마이크 게인 자동설정 실패 → 인식 안되면 'alsamixer -c $CARD_NUM'에서 Capture 올리기"
  fi
  set -e
fi

echo "[serve] python: $PY"
echo "[serve] http://localhost:${PORT}/   (정적 + /listen + /goal + /nav) · 종료 Ctrl+C"
echo

exec "$PY" "$HERE/kiosk_server.py" "$PORT"
