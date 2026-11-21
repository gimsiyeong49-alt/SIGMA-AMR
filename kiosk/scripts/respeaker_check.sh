#!/usr/bin/env bash
# =========================================================================
# respeaker_check.sh — reSpeaker XVF3800 상태 확인·복구
#
#   사용법:  ./scripts/respeaker_check.sh            상태만 확인(일반 권한). 종료 코드 0=정상 2=비정상 1=없음
#            sudo ./scripts/respeaker_check.sh fix   비정상이면 USB 리셋으로 복구(관리자 권한, 최대 3번)
#
#   배경(2026-11-12 확인): reSpeaker 는 켜지는 상황에 따라 녹음 사양을 두 가지로 알려 준다.
#     · 정상: Data packet interval 500 us (패킷 최대 96 B)  → 녹음·재생 모두 정상
#     · 비정상: 125 us (192 B) — 실제로는 500 us 단위로 보내서 보드의 수신 버퍼가 넘침(xHCI "buffer overrun")
#       → 녹음이 0.1~0.25초 뒤 멈추고, 오류가 쌓이면 USB 컨트롤러가 장치를 끊어 스피커까지 먹통.
#     부팅 직후·젯슨 본체 USB-C 직결에서 비정상, 허브에서 다시 꽂으면 정상으로 잡히는 경우가 많았다.
#   boot_prep_root.sh(부팅·브링업 재시작 때 root 로 실행)가 'fix' 를 자동 호출한다.
# =========================================================================
MODE="${1:-check}"

find_dev() {   # reSpeaker USB 장치 sysfs 경로
  local d
  for d in /sys/bus/usb/devices/*; do
    [ -f "$d/product" ] && grep -qi "reSpeaker" "$d/product" 2>/dev/null && { echo "$d"; return 0; }
  done
  return 1
}

capture_interval() {   # 녹음 쪽 Data packet interval(µs). 없으면 빈 값
  local c
  c="$(grep -il "reSpeaker" /proc/asound/card*/id /proc/asound/card*/stream0 2>/dev/null | head -1 | sed -E 's#/proc/asound/(card[0-9]+)/.*#\1#')"
  [ -n "$c" ] || return 1
  sed -n '/Capture:/,$p' "/proc/asound/$c/stream0" 2>/dev/null | grep -m1 "Data packet interval" | grep -oE "[0-9]+"
}

state() {   # 출력: "정상 500" / "비정상 125" / "없음"
  local iv
  find_dev >/dev/null || { echo "없음"; return 1; }
  for _ in 1 2 3 4 5; do iv="$(capture_interval)"; [ -n "$iv" ] && break; sleep 1; done
  if [ -z "$iv" ]; then echo "없음"; return 1; fi
  if [ "$iv" -ge 500 ]; then echo "정상 $iv"; return 0; fi
  echo "비정상 $iv"; return 2
}

if [ "$MODE" = "fix" ]; then
  if [ "$(id -u)" != "0" ]; then echo "fix 는 관리자 권한이 필요합니다: sudo $0 fix" >&2; exit 1; fi
  for n in 1 2 3; do
    st="$(state)"; rc=$?
    echo "[respeaker] 상태: $st"
    [ $rc -eq 0 ] && exit 0
    [ $rc -eq 1 ] && { echo "[respeaker] 장치를 찾지 못함(연결 확인)"; exit 1; }
    dev="$(find_dev)"
    # 2026-11-15: 예전엔 authorized 0→1 로 '재인식'했으나 이건 드라이버만 떼었다 붙일 뿐 장치가 설정(녹음 사양)을
    #  다시 보고하지 않음 — 장치 번호가 부팅 때 그대로(dmesg) 였고 한 번도 복구 못 함. 손으로 다시 꽂을 때만 정상.
    #  → USB 리셋(USBDEVFS_RESET): 장치에 다시 꽂을 때와 같은 버스 리셋을 보내 처음부터 다시 연결(전원만 유지).
    #   설정이 바뀌면 커널이 장치를 새로 인식(새 장치 번호)하고 사운드 드라이버도 새 사양으로 다시 붙는다.
    #   (이 커널 5.10 에는 포트 끄기(port/disable)가 없어 소프트웨어로 할 수 있는 가장 강한 방법)
    node="/dev/bus/usb/$(printf %03d "$(cat "$dev/busnum")")/$(printf %03d "$(cat "$dev/devnum")")"
    echo "[respeaker] 비정상 사양 → USB 리셋 시도 $n/3 ($dev, $node, 장치번호 $(cat "$dev/devnum"))"
    /usr/bin/python3 -c 'import fcntl,os,sys; fd=os.open(sys.argv[1], os.O_WRONLY); fcntl.ioctl(fd, 21780, 0); os.close(fd)' "$node" 2>&1 \
      | sed 's/^/[respeaker]   리셋 오류: /'
    sleep 5
    dev2="$(find_dev)"; [ -n "$dev2" ] && echo "[respeaker]   리셋 후 장치번호 $(cat "$dev2/devnum" 2>/dev/null)"
  done
  st="$(state)"; rc=$?
  echo "[respeaker] 최종 상태: $st"
  [ $rc -eq 0 ] || echo "[respeaker] ⚠ USB 리셋으로 복구되지 않음 → USB 허브 A-1 에서 손으로 뽑았다 다시 꽂아 주세요"
  exit $rc
fi

st="$(state)"; rc=$?
echo "$st"
exit $rc
