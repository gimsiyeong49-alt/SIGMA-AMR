#!/usr/bin/env bash
# =========================================================================
# kiosk_boot.sh — ④브링업 → ⑤내비+초기위치 → ⑥음성인식 앱 화면(마지막)
#
#   런처(agv-kiosk-launch.sh)가 ①팬 ②SSD마운트 ③장치권한 을 끝낸 뒤 이 스크립트를
#   exec 로 호출한다. 여기서는 ROS 백엔드를 "완료까지" 기다린 다음, 마지막에 크로미움을
#   전체화면(키오스크)으로 띄운다. → 사용자 눈엔 "준비 끝나고 음성인식 화면이 뜬다".
#
#   화면엔 터미널이 안 보인다(모든 출력은 logs/ 로). 탈출구: Ctrl+Alt+F3.
# =========================================================================
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PROJ="$(cd "$HERE/.." && pwd)"
LOG_DIR="$PROJ/logs"; mkdir -p "$LOG_DIR"
exec >>"$LOG_DIR/kiosk_boot.log" 2>&1
echo ""
echo "======================================================== "
echo "[boot] kiosk_boot 시작 PID=$$ DISPLAY=${DISPLAY:-?}"

APP_PORT="${1:-8000}"
APP_URL="http://localhost:${APP_PORT}/"
CHROME="$(command -v chromium-browser || command -v chromium || echo /usr/bin/chromium-browser)"
log(){ echo "[boot $(cut -d' ' -f1 /proc/uptime 2>/dev/null)s] $*"; }

# ── 0) 디스플레이 준비 대기 ──────────────────────────────────────────────
for _ in $(seq 1 30); do
  [ -n "${DISPLAY:-}" ] && command -v xset >/dev/null 2>&1 && xset q >/dev/null 2>&1 && break
  sleep 1
done
log "DISPLAY 준비: ${DISPLAY:-없음}"

# ── 1) ROS 환경 (autostart는 .bashrc를 안 읽으므로 반드시 source) ─────────
# shellcheck disable=SC1091
source "$HERE/ros_env.sh"
log "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-?} RMW=${RMW_IMPLEMENTATION:-?}"

# ── 2) 앱 서버 + whisper 를 백그라운드로 미리 기동 (ROS와 독립, 병렬) ─────
# 화면(크로미움)은 백엔드까지 끝난 뒤 마지막에 띄우지만, 앱 서버 준비는
# 시간이 걸리므로 미리 백그라운드로 올려둔다.
if pgrep -f "[k]iosk_server.py" >/dev/null; then
  log "앱 서버 이미 실행 중"
else
  log "앱+whisper 기동 (run_app.sh, 백그라운드)"
  setsid bash -c 'exec "$@"' _ "$HERE/run_app.sh" "$APP_PORT" \
      >>"$LOG_DIR/run_app.log" 2>&1 < /dev/null &
fi

# ── 3) ROS 백엔드 시퀀스: 브링업 → 내비 → 초기위치 → 복귀감시 (완료까지 대기) ──
# 순서를 지키기 위해 여기서 "완료될 때까지" 기다린다. (백엔드가 먼저 끝난 뒤에
# 화면을 띄우므로, 크로미움/세션이 백엔드를 방해할 일이 없다 = setsid 불필요)
log "ROS 백엔드 시퀀스 시작 (브링업→내비→초기위치→복귀감시, 완료까지 대기)"
bash "$HERE/kiosk_backend.sh"
log "ROS 백엔드 시퀀스 종료"

# ── 4) 앱 서버 포트 준비 대기 ────────────────────────────────────────────
log "앱 서버 포트 $APP_PORT 대기..."
for _ in $(seq 1 60); do
  curl -s -o /dev/null "http://127.0.0.1:${APP_PORT}/" 2>/dev/null && break
  sleep 1
done
curl -s -o /dev/null "http://127.0.0.1:${APP_PORT}/" 2>/dev/null && log "앱 서버 준비 완료" || log "⚠ 앱 서버 미준비 — 그래도 브라우저 시도"

# ── 5) ⑥ 음성인식 앱 화면 (마지막, 전체화면 키오스크) ────────────────────
# 서버측 STT라 브라우저 마이크 권한 불필요. 독립 프로필로 평소 브라우저와 분리.
log "크로미움 키오스크 실행: $APP_URL"
exec "$CHROME" \
  --user-data-dir="$PROJ/.chrome-kiosk" \
  --kiosk "$APP_URL" \
  --start-fullscreen --window-size=1920,1080 --window-position=0,0 \
  --disable-gpu --disable-gpu-compositing \
  --noerrdialogs --disable-infobars --no-first-run \
  --disable-session-crashed-bubble --disable-features=Translate \
  --check-for-update-interval=31536000 \
  --overscroll-history-navigation=0
