#!/usr/bin/env bash
# =========================================================================
# revert_audio_1112.sh — reSpeaker 관련 '시스템 설정'을 11-12(마이크·스피커 정상 확인 때) 상태로 되돌림
#
#   사용법:  sudo ./scripts/revert_audio_1112.sh
#
#   되돌리는 것(11-12 이후 추가된 시스템 설정):
#     · /etc/udev/rules.d/89-respeaker-no-pulseaudio.rules  (PulseAudio 가 reSpeaker 무시) → 삭제
#     · /etc/udev/rules.d/90-respeaker-usb.rules            (장치 제어 권한) → 삭제
#     · /etc/sudoers.d/respeaker, /usr/local/sbin/respeaker_check.sh (비밀번호 없는 자동 복구) → 삭제
#     · PulseAudio 에서 꺼 둔 reSpeaker 를 다시 켜고 기본 스피커·마이크로(11-12 때처럼)
#   코드(시작 스크립트·부팅 준비·안내 서버 자동 복구 호출)는 git 으로 이미 11-12 버전으로 되돌림.
#   도중에 reSpeaker 를 다시 꽂으라고 안내함(PulseAudio 가 장치를 다시 인식하려면 필요). 스피커 커넥터도 그때 끝까지.
# =========================================================================
set -uo pipefail
if [ "$(id -u)" != "0" ]; then echo "관리자 권한 필요: sudo $0" >&2; exit 1; fi
USER_NAME="${SUDO_USER:-wjs}"
UID_N="$(id -u "$USER_NAME")"
PA() { sudo -u "$USER_NAME" XDG_RUNTIME_DIR="/run/user/$UID_N" pactl "$@"; }

rm -f /etc/udev/rules.d/89-respeaker-no-pulseaudio.rules /etc/udev/rules.d/90-respeaker-usb.rules
udevadm control --reload-rules
echo "  · udev 규칙 2개 삭제(PulseAudio 무시·장치 제어 권한)"
rm -f /etc/sudoers.d/respeaker /usr/local/sbin/respeaker_check.sh
visudo -c >/dev/null && echo "  · 자동 복구용 sudoers·관리자 사본 삭제 (sudoers 검사 OK)"

echo
echo "  ▶ 지금 해 주세요: ① reSpeaker 의 스피커 커넥터를 뽑았다가 끝까지 다시 꽂기"
echo "                    ② reSpeaker USB 를 허브 A-1 에서 뽑았다가 다시 꽂기"
echo "    (다시 꽂으면 자동으로 다음 단계로 넘어갑니다. 최대 3분 기다림)"
OLD_DEV="$(for d in /sys/bus/usb/devices/*; do [ -f "$d/product" ] && grep -qi reSpeaker "$d/product" && cat "$d/devnum"; done 2>/dev/null | head -1)"
CARD=""
for _ in $(seq 1 180); do
  NEW_DEV="$(for d in /sys/bus/usb/devices/*; do [ -f "$d/product" ] && grep -qi reSpeaker "$d/product" && cat "$d/devnum"; done 2>/dev/null | head -1)"
  if [ -n "$NEW_DEV" ] && [ "$NEW_DEV" != "$OLD_DEV" ]; then
    CARD="$(PA list short cards 2>/dev/null | awk '/reSpeaker/{print $2}' | head -1)"
    [ -n "$CARD" ] && break
  fi
  sleep 1
done
if [ -z "$CARD" ]; then
  echo "  ⚠ 3분 안에 reSpeaker 재연결을 못 봤습니다. 다시 꽂은 뒤 이 스크립트를 한 번 더 실행해 주세요." >&2
  exit 1
fi
echo "  · reSpeaker 다시 인식됨 (장치 번호 $OLD_DEV → $NEW_DEV)"
PA set-card-profile "$CARD" output:analog-stereo+input:multichannel-input && echo "  · PulseAudio 에서 reSpeaker 다시 켬"
SINK="$(PA list short sinks 2>/dev/null | awk '/reSpeaker/{print $2}' | head -1)"
SRC="$(PA list short sources 2>/dev/null | awk '/reSpeaker/ && !/monitor/{print $2}' | head -1)"
[ -n "$SINK" ] && PA set-default-sink "$SINK" && echo "  · 기본 스피커 = reSpeaker"
[ -n "$SRC" ] && PA set-default-source "$SRC" && echo "  · 기본 마이크 = reSpeaker"

HERE="$(cd "$(dirname "$0")" && pwd)"
echo
sleep 6   # PulseAudio 가 방금 켠 장치를 놓을 때까지(쉬는 장치는 5초 뒤 놓음) — 안 기다리면 '사용 중'
echo "  ▶ 확인(스피커로 0.4초 '삐' → 마이크로 받아 판정):"
sudo -u "$USER_NAME" python3 "$HERE/audio_selftest.py" --no-amp 2>&1 | sed 's/^/    /' || true
echo "  완료. 키오스크는 start_guide 를 Ctrl+C 후 다시 실행하면 11-12 버전으로 돕니다."
