#!/usr/bin/env bash
# =========================================================================
# install_respeaker_autofix.sh — reSpeaker 자동 복구를 '비밀번호 없이' 쓸 수 있게 설치(한 번만, 관리자 권한)
#
#   사용법:  sudo ./scripts/install_respeaker_autofix.sh
#
#   하는 일:
#     1) scripts/respeaker_check.sh 를 /usr/local/sbin/respeaker_check.sh 로 복사(root 소유·일반 사용자 수정 불가)
#        — 프로젝트 폴더의 파일을 그대로 허용하면 누구나 내용을 바꿔 관리자 권한으로 실행할 수 있어 위험하므로 사본을 쓴다
#     2) /etc/sudoers.d/respeaker : 사용자 wjs 가 그 사본의 'fix' 만 비밀번호 없이 실행하도록 허용
#     3) sudoers 문법 검사(틀리면 바로 지움 — sudo 자체가 망가지지 않게)
#     4) (2026-11-15) /etc/udev/rules.d/89-respeaker-no-pulseaudio.rules : 데스크톱 사운드(PulseAudio)가 reSpeaker 를
#        쓰지 않게 함. PulseAudio 가 reSpeaker 를 기본 스피커·마이크로 잡고 있으면 보드의 브라우저 소리·장치 재연결 확인
#        중에 장치를 열어 TTS 재생이 'Device or resource busy' 로 실패(로그 확인). 로봇 스피커·마이크는 TTS·안내 서버 전용.
#     5) (2026-11-15) /etc/udev/rules.d/90-respeaker-usb.rules : reSpeaker 장치 제어(USB) 권한(Seeed 위키 권장 규칙) —
#        일반 사용자로 스피커 앰프 켜기(respeaker_ctl.py amp-on)를 할 수 있게. 설치 직후 앰프를 켜고 전후 상태를 보여 줌.
#   이후 키오스크 앱(녹음 데이터 미수신 시)·start_guide/start_voice_ui(시작 시 비정상)가 자동으로 복구를 실행한다.
#   respeaker_check.sh 를 고쳤으면 이 스크립트를 다시 실행해 사본을 갱신할 것.
#   되돌리기: sudo rm /etc/sudoers.d/respeaker /usr/local/sbin/respeaker_check.sh /etc/udev/rules.d/89-respeaker-no-pulseaudio.rules /etc/udev/rules.d/90-respeaker-usb.rules
# =========================================================================
set -euo pipefail
if [ "$(id -u)" != "0" ]; then echo "관리자 권한 필요: sudo $0" >&2; exit 1; fi
HERE="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-wjs}"

install -o root -g root -m 755 "$HERE/respeaker_check.sh" /usr/local/sbin/respeaker_check.sh
echo "  · 복사: /usr/local/sbin/respeaker_check.sh (root 소유)"

TMP="$(mktemp)"
echo "$USER_NAME ALL=(root) NOPASSWD: /usr/local/sbin/respeaker_check.sh fix" > "$TMP"
if visudo -cf "$TMP" >/dev/null; then
  install -o root -g root -m 440 "$TMP" /etc/sudoers.d/respeaker
  echo "  · 허용: $USER_NAME → /usr/local/sbin/respeaker_check.sh fix (비밀번호 없이)"
else
  echo "  ✗ sudoers 문법 오류 — 설치하지 않음" >&2; rm -f "$TMP"; exit 1
fi
rm -f "$TMP"
visudo -c >/dev/null && echo "  · sudoers 전체 검사 OK"
echo "  확인: sudo -n /usr/local/sbin/respeaker_check.sh fix"

# 4) PulseAudio 가 reSpeaker 무시(PULSE_IGNORE) — 다음 연결(부팅·다시 꽂기)부터 적용. 지금 세션은 아래 pactl 로 바로 끔
cat > /etc/udev/rules.d/89-respeaker-no-pulseaudio.rules <<'RULE'
# reSpeaker XVF3800(2886:001e)은 로봇 TTS·음성인식 서버가 직접(ALSA) 쓴다. PulseAudio 가 열면 재생이 'busy' 로 실패.
SUBSYSTEM=="sound", ATTRS{idVendor}=="2886", ATTRS{idProduct}=="001e", ENV{PULSE_IGNORE}="1"
RULE
udevadm control --reload-rules && echo "  · udev 규칙: PulseAudio 가 reSpeaker 무시(/etc/udev/rules.d/89-respeaker-no-pulseaudio.rules)"
UID_N="$(id -u "$USER_NAME")"
C="$(sudo -u "$USER_NAME" XDG_RUNTIME_DIR=/run/user/$UID_N pactl list short cards 2>/dev/null | awk '/reSpeaker/{print $2}' || true)"   # set -e: 실패해도 진행
if [ -n "$C" ]; then
  sudo -u "$USER_NAME" XDG_RUNTIME_DIR=/run/user/$UID_N pactl set-card-profile "$C" off && echo "  · 지금 세션: PulseAudio 에서 reSpeaker 끔" || true
fi

# 5) reSpeaker 장치 제어 권한 + 스피커 앰프 켜기
cat > /etc/udev/rules.d/90-respeaker-usb.rules <<'RULE'
# reSpeaker XVF3800 장치 제어(앰프 켜기 등)를 일반 사용자도 할 수 있게(Seeed 위키 권장 규칙)
SUBSYSTEM=="usb", ATTRS{idVendor}=="2886", MODE="0666"
RULE
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb --attr-match=idVendor=2886 || true
sleep 1
echo "  · udev 규칙: reSpeaker 장치 제어 권한(/etc/udev/rules.d/90-respeaker-usb.rules)"
echo "  · 스피커 앰프 확인·켜기:"
/usr/bin/python3 "$HERE/respeaker_ctl.py" amp-on || echo "  ✗ 앰프 켜기 실패(위 메시지 참고)"
