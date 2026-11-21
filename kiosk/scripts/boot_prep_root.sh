#!/usr/bin/env bash
# =========================================================================
# boot_prep_root.sh — 부팅 시 브링업 전 준비 (root 로 실행: agv-bringup.service 의 ExecStartPre=+)
#   · 전원 모드 고정(기본 3 = MODE_30W_ALL) — MAXN 에서 모터 구동 시 젯슨이 꺼지던 문제 대응.
#     2026-11-11: 4(30W_6CORE)는 주행+음성 동시 실행 시 CPU 포화(TTS 한 문장 3~10초) → 같은 30W에 8코어인 3으로.
#     3으로 주행 시험해 보드 꺼짐 없음 확인(사용자). 되돌리려면 AGV_POWER_MODE=4
#   · 팬/클럭(jetson_clocks --fan)
#   · 장치 권한(ttyMD / ttyLidar_F / ttyLidar_R / ttyIMU) — USB 인식 지연 대비 최대 30초 대기
#   실패해도 브링업을 막지 않도록 항상 exit 0 (단, 장치 누락은 로그로 남김)
# =========================================================================
set -u
# journal(systemctl status) + logs/boot_prep.log 양쪽에 남긴다
PLOG="$(cd "$(dirname "$0")" && pwd)/../logs/boot_prep.log"
exec > >(tee -a "$PLOG") 2>&1
log(){ echo "[boot_prep $(date '+%F %T')] $*"; }

# 1) 전원 모드 — 이미 같으면 건드리지 않음(불필요한 전환/재부팅 요구 방지)
WANT="${AGV_POWER_MODE:-3}"
CUR="$(nvpmodel -q 2>/dev/null | sed -n '2p' | tr -d '[:space:]')"
if [ -n "$WANT" ] && [ "$CUR" != "$WANT" ]; then
  log "전원 모드 $CUR → $WANT 로 변경"
  nvpmodel -m "$WANT" </dev/null || log "⚠ nvpmodel -m $WANT 실패(무시)"
else
  log "전원 모드 유지: $CUR"
fi

# 2) 팬/클럭 (전원 모드 설정 뒤에 — 해당 모드 한도 안에서 적용됨)
/usr/bin/jetson_clocks --fan && log "jetson_clocks --fan 완료" || log "⚠ jetson_clocks 실패(무시)"

# 3) 장치 권한 — 장치가 나타날 때까지 대기
DEVS="/dev/ttyMD /dev/ttyLidar_F /dev/ttyLidar_R /dev/ttyIMU"
for _ in $(seq 1 30); do
  missing=0
  for d in $DEVS; do [ -e "$d" ] || missing=1; done
  [ "$missing" = 0 ] && break
  sleep 1
done
for d in $DEVS; do
  if [ -e "$d" ]; then chmod 766 "$d" && log "권한 부여: $d"
  else log "⚠ 장치 없음: $d (연결 확인 필요)"; fi
done
exit 0
