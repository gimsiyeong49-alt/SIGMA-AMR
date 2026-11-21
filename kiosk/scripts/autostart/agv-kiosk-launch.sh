#!/usr/bin/env bash
# =========================================================================
# agv-kiosk-launch.sh — 전원 ON 자동 실행 런처 (홈/eMMC, /mnt/ssd 마운트 전에도 실행)
#   GNOME autostart가 이 파일을 실행한다. 사용자 지정 순서:
#     ① sudo jetson_clocks --fan
#     ② sudo mount /dev/nvme0n1p1 /mnt/ssd
#     ③ cm/cl/ci  (sudo chmod 766 장치들)
#     ④ kiosk_boot.sh  (브링업 → 내비 → 초기위치 → 음성인식 앱 화면)
#   ①②③은 NOPASSWD sudo (kiosk_setup_system.sh가 1회 설정). 그래서 비번 안 물음.
# =========================================================================
LOG="$HOME/agv-kiosk-launch.log"
exec > "$LOG" 2>&1
echo "==== launch uptime=$(cut -d' ' -f1 /proc/uptime 2>/dev/null)s ===="

# ① 팬
echo "① jetson_clocks --fan"
sudo -n /usr/bin/jetson_clocks --fan && echo "  OK" || echo "  실패(무시하고 계속)"

# ② SSD 마운트 (장치가 나타날 때까지 대기 후)
echo "② /mnt/ssd 마운트"
if mountpoint -q /mnt/ssd; then
  echo "  이미 마운트됨"
else
  for i in $(seq 1 60); do [ -b /dev/nvme0n1p1 ] && break; sleep 1; done
  sudo -n /usr/bin/mount /dev/nvme0n1p1 /mnt/ssd && echo "  마운트 OK" || echo "  ✗ 마운트 실패"
fi
for i in $(seq 1 30); do mountpoint -q /mnt/ssd && break; sleep 1; done
mountpoint -q /mnt/ssd || { echo "✗ /mnt/ssd 마운트 안 됨 → 중단"; exit 1; }

# ③ 장치 권한 (cm / cl / ci)
echo "③ 장치 권한 (cm/cl/ci)"
for d in /dev/ttyMD /dev/ttyLidar_F /dev/ttyLidar_R /dev/ttyIMU; do
  if [ -e "$d" ]; then
    sudo -n /usr/bin/chmod 766 "$d" && echo "  766 $d" || echo "  ✗ $d (NOPASSWD 설정 확인)"
  else
    echo "  ⚠ 장치 없음: $d"
  fi
done

# ④ 브링업→내비→초기위치→앱 (kiosk_boot에 위임, 화면은 마지막에)
KIOSK=/mnt/ssd/projects/myproject/scripts/kiosk_boot.sh
[ -x "$KIOSK" ] || { echo "✗ $KIOSK 없음/실행불가"; exit 1; }
echo "④ kiosk_boot 실행 (브링업→내비→초기위치→음성앱)"
exec "$KIOSK"
