#!/usr/bin/env bash
# =========================================================================
# record_nav_bag.sh — 주행 rosbag 녹화 (충돌·떨림 원인 분석용)
#
#   사용법:  ./scripts/record_nav_bag.sh [메모]          예) ./scripts/record_nav_bag.sh 내과왕복
#            ./scripts/record_nav_bag.sh --deep [메모]   + DWB 후보 궤적 평가(/evaluation)·전역 costmap까지(용량 큼)
#            종료: Ctrl+C  → 녹화 마무리 + 그 시점의 설정·로그를 같은 폴더에 복사
#
#   start_guide.sh 를 켠 '다른 터미널'에서 실행한다(주행 시스템과 따로). 주행 시작 전에 켜고, 끝나면 Ctrl+C.
#   저장: /mnt/ssd/bags/nav_YYYYmmdd_HHMMSS[_메모]/   (SSD. 기본 약 0.5~1 MB/초 → 10분에 수백 MB)
#   분석: python3 scripts/analyze_nav_bag.py /mnt/ssd/bags/<폴더>
#
#   녹화하는 것(없는 토픽은 나타날 때 자동으로 잡음):
#     · 명령/움직임: /cmd_vel(Nav2가 낸 속도 명령) · /odom · /odometry/filtered  (/imu/data 는 약 900Hz라 --deep 에서만)
#                    모터 드라이버(/motor_command /motor_amps /feedback /hall_speed /battery_amps /volts /fault_flag)
#     · 센서:        /scan_multi(합친 LiDAR) · /lidar_F|R/scan_filtered · /people_obstacles(카메라 사람)
#     · 위치:        /tf · /tf_static · /map · /amcl_pose · /initialpose · /particle_cloud 제외(큼)
#     · Nav2:        /plan(전역 경로) · /local_plan · /transformed_global_plan · /received_global_plan
#                    /local_costmap/costmap(+updates, footprint) · /goal_pose · navigate_to_pose 액션 상태·피드백
#                    /behavior_tree_log · /speed_limit
#     · 로그:        /rosout(경고·복구 동작) · /diagnostics
# =========================================================================
set -euo pipefail

DEEP=0
if [ "${1:-}" = "--deep" ]; then DEEP=1; shift; fi
LABEL="${1:-}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BAGS=/mnt/ssd/bags
STAMP="$(date +%Y%m%d_%H%M%S)"
NAME="nav_${STAMP}${LABEL:+_$LABEL}"
OUT="$BAGS/$NAME"
CFG=/mnt/ssd/cart_ros2/src/hospital_mission/config/agv.yaml

mkdir -p "$BAGS"
# eMMC가 아니라 SSD인지 확인(녹화는 용량이 큼)
if ! mountpoint -q /mnt/ssd; then echo "✗ /mnt/ssd 가 마운트돼 있지 않습니다. 중단." >&2; exit 1; fi

# shellcheck disable=SC1091
source "$HERE/ros_env.sh" >/dev/null 2>&1

TOPICS=(
  /cmd_vel /odom /odometry/filtered
  /motor_command /motor_amps /feedback /hall_speed /battery_amps /volts /fault_flag
  /scan_multi /lidar_F/scan_filtered /lidar_R/scan_filtered /people_obstacles
  /tf /tf_static /map /amcl_pose /initialpose
  /plan /local_plan /transformed_global_plan /received_global_plan
  /local_costmap/costmap /local_costmap/costmap_updates /local_costmap/published_footprint
  /goal_pose /navigate_to_pose/_action/status /navigate_to_pose/_action/feedback
  /behavior_tree_log /speed_limit
  /rosout /diagnostics
)
if [ "$DEEP" = "1" ]; then
  # /evaluation: DWB가 매 주기(20Hz) 평가한 후보 궤적 600개와 비평가(critic)별 점수 → "왜 그 경로를 골랐나"
  # /global_costmap/costmap: 지도 전체(539×2069) 1초마다 → 시간당 수 GB
  TOPICS+=(/evaluation /global_costmap/costmap /marker /vision_result/image /imu/data)
fi

# /map · /tf_static 은 '처음 한 번만' 보내는 토픽(transient_local) → 늦게 켠 녹화기도 받도록 QoS 지정
QOS="$BAGS/.qos_overrides.yaml"
cat > "$QOS" <<'EOF'
/map:
  reliability: reliable
  durability: transient_local
  history: keep_last
  depth: 1
/tf_static:
  reliability: reliable
  durability: transient_local
  history: keep_last
  depth: 100
/scan_multi:
  reliability: best_effort
  durability: volatile
  history: keep_last
  depth: 10
EOF
# ↑ 2026-11-13: /scan_multi 는 병합 프로그램이 best-effort 로 발행 → 녹화기가 reliable 로 구독하면 0개 녹화됨(nav_20261112_235325)

snapshot() {
  # 녹화 당시 설정·로그를 함께 보관(나중에 "그때 어떤 파라미터였나" 비교)
  mkdir -p "$OUT/context"
  cp -f "$CFG" "$OUT/context/agv.yaml" 2>/dev/null || true
  for f in navigation.log return_home.log boot_prep.log; do
    [ -f "$HERE/../logs/$f" ] && tail -n 3000 "$HERE/../logs/$f" > "$OUT/context/$f" || true
  done
  { echo "label: ${LABEL}"; echo "start: ${STAMP}"; echo "end: $(date +%Y%m%d_%H%M%S)"
    echo "nvpmodel: $(nvpmodel -q 2>/dev/null | head -1)"
    echo "deep: ${DEEP}"; } > "$OUT/context/meta.txt"
  echo "  · 설정·로그 사본: $OUT/context/"
  echo "  · 분석: python3 $HERE/analyze_nav_bag.py $OUT"
}
trap snapshot EXIT

echo "════════════════════════════════════════════════════════"
echo " rosbag 녹화 → $OUT"
echo "   토픽 ${#TOPICS[@]}개 (deep=${DEEP}) · 종료 Ctrl+C"
echo "════════════════════════════════════════════════════════"
# 압축은 끔(CPU가 이미 바쁨). 1GB마다 파일 분할. 숨은 토픽(액션 상태) 포함.
ros2 bag record -o "$OUT" -b 1000000000 --include-hidden-topics \
  --qos-profile-overrides-path "$QOS" "${TOPICS[@]}" || true
