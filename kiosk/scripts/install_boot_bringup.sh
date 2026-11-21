#!/usr/bin/env bash
# =========================================================================
# install_boot_bringup.sh — 부팅 시 브링업 자동 시작 서비스 설치/갱신/해제 (sudo 필요)
#
#   설치·갱신: sudo ./scripts/install_boot_bringup.sh           (등록 + 지금 바로 (재)시작)
#   해제:      sudo ./scripts/install_boot_bringup.sh --remove  (중지 + 등록 해제)
#   상태:      systemctl status agv-bringup
#   로그:      logs/boot_prep.log(장치권한·팬·전원모드) · logs/bringup.log(브링업)
# =========================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
UNIT=agv-bringup.service
DEST=/etc/systemd/system/$UNIT

if [ "$(id -u)" != 0 ]; then echo "sudo 로 실행하세요: sudo $0 $*" >&2; exit 1; fi

if [ "${1:-}" = "--remove" ]; then
  systemctl disable --now "$UNIT" 2>/dev/null || true
  rm -f "$DEST"
  systemctl daemon-reload
  echo "해제 완료: 부팅 시 브링업 자동 시작 안 함"
  exit 0
fi

chmod +x "$HERE/boot_prep_root.sh" "$HERE/boot_bringup.sh"
mkdir -p "$HERE/../logs" && chown wjs:wjs "$HERE/../logs"

# 이미 수동으로 띄운 브링업이 있으면 중복(이중 모터제어) 방지를 위해 안내
if pgrep -f "[a]gv_bringup.launch.py" >/dev/null && ! systemctl is-active --quiet "$UNIT"; then
  echo "⚠ 수동으로 띄운 브링업이 이미 실행 중입니다. 그 터미널에서 먼저 종료한 뒤 다시 실행하세요."
  exit 1
fi

# fstab: SSD 장치 대기 5초 → 30초 (부팅 시 NVMe 인식이 5초를 넘겨 마운트가 '실패' 처리되던 문제)
FSTAB=/etc/fstab
if grep -qE '^[^#]*[[:space:]]/mnt/ssd[[:space:]].*x-systemd\.device-timeout=5([,[:space:]]|$)' "$FSTAB"; then
  BAK="$FSTAB.bak.agv-$(date +%Y%m%d_%H%M%S)"
  cp -a "$FSTAB" "$BAK"
  sed -i -E '/^[^#]*[[:space:]]\/mnt\/ssd[[:space:]]/ s/x-systemd\.device-timeout=5([,[:space:]]|$)/x-systemd.device-timeout=30\1/' "$FSTAB"
  if findmnt -s -n -o OPTIONS /mnt/ssd 2>/dev/null | grep -q "x-systemd.device-timeout=30" \
     && [ "$(grep -cvE '^[[:space:]]*(#|$)' "$FSTAB")" = "$(grep -cvE '^[[:space:]]*(#|$)' "$BAK")" ]; then
    echo "fstab: /mnt/ssd 장치 대기 5초 → 30초 (백업: $BAK)"
  else
    cp -a "$BAK" "$FSTAB"; echo "⚠ fstab 수정 검증 실패 → 원복함(백업: $BAK)"
  fi
else
  echo "fstab: 변경 불필요"
fi

install -m 644 "$HERE/$UNIT" "$DEST"
systemctl daemon-reload
systemctl enable "$UNIT"
systemctl restart "$UNIT"      # 갱신 시에도 새 설정으로 즉시 반영
sleep 3
systemctl --no-pager --lines=5 status "$UNIT" || true
echo
echo "설치 완료: 전원을 켜면 SSD 마운트 대기 → 장치권한·팬·전원모드 → 브링업 순으로 자동 실행됩니다."
echo "  로그: $HERE/../logs/boot_prep.log · $HERE/../logs/bringup.log"
echo "  재시작: sudo systemctl restart agv-bringup"
