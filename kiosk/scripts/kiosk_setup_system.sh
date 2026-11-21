#!/usr/bin/env bash
# =========================================================================
# kiosk_setup_system.sh — 전원 ON 자동실행을 위한 "1회" 시스템 설정
#
#   실행:  sudo /mnt/ssd/projects/myproject/scripts/kiosk_setup_system.sh
#          (딱 한 번, 비밀번호 1회. 이후로는 전원만 켜면 비번 없이 자동 실행)
#
#   하는 일:
#     ① 자동 로그인   — 부팅 시 로그인 화면 없이 wjs 세션 진입 (/etc/gdm3/custom.conf)
#     ② NOPASSWD sudo — 부팅 런처가 쓰는 딱 3종류 명령만 비번 없이 실행 허용
#                        (jetson_clocks --fan / mount /mnt/ssd / chmod 766 장치들)
#                        → 자동실행 중 비번을 물어보지 않게 함. (전체 sudo 개방 아님)
#
#   되돌리기:
#     ① /etc/gdm3/custom.conf 를 백업(.bak.*)으로 복원
#     ② sudo rm /etc/sudoers.d/agv-kiosk
# =========================================================================
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "✗ sudo 로 실행하세요: sudo $0"; exit 1; }
TARGET_USER="${SUDO_USER:-wjs}"
STAMP="$(date +%Y%m%d_%H%M%S)"
echo "대상 사용자: $TARGET_USER"
echo

# ── ① 자동 로그인 (gdm3) ────────────────────────────────────────────────
echo "① 자동 로그인 설정 (/etc/gdm3/custom.conf)"
GDM=/etc/gdm3/custom.conf
if [ -f "$GDM" ]; then
  cp -a "$GDM" "${GDM}.bak.${STAMP}"; echo "   백업: ${GDM}.bak.${STAMP}"
  python3 - "$GDM" "$TARGET_USER" <<'PY'
import sys, re
path, user = sys.argv[1], sys.argv[2]
s = open(path).read(); lines = s.splitlines()
out, in_daemon, de, du = [], False, False, False
for ln in lines:
    st = ln.strip()
    if st.startswith('[') and st.endswith(']'):
        if in_daemon:
            if not de: out.append('AutomaticLoginEnable=true'); de=True
            if not du: out.append(f'AutomaticLogin={user}'); du=True
        in_daemon = (st == '[daemon]'); out.append(ln); continue
    if in_daemon and re.match(r'\s*#?\s*AutomaticLoginEnable\s*=', ln):
        out.append('AutomaticLoginEnable=true'); de=True; continue
    if in_daemon and re.match(r'\s*#?\s*AutomaticLogin\s*=', ln):
        out.append(f'AutomaticLogin={user}'); du=True; continue
    out.append(ln)
if in_daemon:
    if not de: out.append('AutomaticLoginEnable=true')
    if not du: out.append(f'AutomaticLogin={user}')
if '[daemon]' not in s:
    out += ['[daemon]', 'AutomaticLoginEnable=true', f'AutomaticLogin={user}']
open(path,'w').write('\n'.join(out)+'\n')
PY
  grep -E "^\[daemon\]|AutomaticLogin" "$GDM" | sed 's/^/     /'
else
  echo "   ⚠ $GDM 없음 — 건너뜀"
fi
echo

# ── ② NOPASSWD sudo (런처가 쓰는 3종 명령만) ─────────────────────────────
echo "② NOPASSWD sudo (/etc/sudoers.d/agv-kiosk)"
SUDOERS=/etc/sudoers.d/agv-kiosk
TMP="$(mktemp)"
cat > "$TMP" <<EOF
# AGV 키오스크 전원ON 자동실행용 — 아래 명령들만 ${TARGET_USER}가 비번 없이 실행.
# (agv-kiosk-launch.sh 의 ①팬 ②마운트 ③장치권한 단계용. 전체 sudo 개방 아님)
${TARGET_USER} ALL=(root) NOPASSWD: /usr/bin/jetson_clocks --fan
${TARGET_USER} ALL=(root) NOPASSWD: /usr/bin/mount /dev/nvme0n1p1 /mnt/ssd
${TARGET_USER} ALL=(root) NOPASSWD: /usr/bin/chmod 766 /dev/ttyMD
${TARGET_USER} ALL=(root) NOPASSWD: /usr/bin/chmod 766 /dev/ttyLidar_F
${TARGET_USER} ALL=(root) NOPASSWD: /usr/bin/chmod 766 /dev/ttyLidar_R
${TARGET_USER} ALL=(root) NOPASSWD: /usr/bin/chmod 766 /dev/ttyIMU
EOF
# ★ 반드시 문법 검증 후 설치 (sudoers 문법 오류는 sudo 잠금 위험)
if visudo -cf "$TMP" >/dev/null 2>&1; then
  install -m 0440 -o root -g root "$TMP" "$SUDOERS"
  echo "   설치: $SUDOERS (visudo 검증 통과)"
  sed 's/^/     /' "$SUDOERS"
else
  echo "   ✗ sudoers 문법 검증 실패 — 설치 안 함(안전)"; visudo -cf "$TMP"
fi
rm -f "$TMP"
echo

echo "════════════════════════════════════════════════════"
echo " 1회 시스템 설정 완료."
echo " 이제 재부팅하면(로봇을 초기 위치에 둔 채):"
echo "   자동로그인 → ①팬 ②SSD마운트 ③장치권한 → ④브링업→내비→초기위치 → ⑥음성앱 전체화면"
echo " autostart 등록(~/.config/autostart/agv-kiosk.desktop)은 이미 되어 있음."
echo "════════════════════════════════════════════════════"
