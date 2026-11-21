#!/usr/bin/env bash
# =========================================================================
# run_sim_exp2.sh — 실험 2(자율주행 안내 성공률) 시뮬레이션 한 번에 실행
#
#   사용법:  ./sim/run_sim_exp2.sh [결과폴더]          (기본: 5곳 × 4회 = 20회, 실제 시간으로 약 1~2시간)
#            REPS=1 ./sim/run_sim_exp2.sh              (5곳 × 1회 빠른 확인)
#   구성:    가짜 로봇·라이다(fake_robot.py) + 실제 Nav2 설정(agv.yaml)·지도(my_map) + 실제 주행 요청 감시기
#            + 실제 복귀·정렬 감시기(return_home_watcher.py) + 자동 평가(sim_exp2.py)
#   안전:    ROS_DOMAIN_ID=77·로컬 전용 + 시뮬 전용 요청 폴더 → 실제 로봇·키오스크와 섞이지 않음.
#            단, CPU 를 많이 쓰니 실제 안내 서버(start_guide)와 동시에 돌리지 말 것.
# =========================================================================
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
CART="${CART:-/mnt/ssd/cart_ros2}"
OUT="${1:-/mnt/ssd/experiments/sim/$(date +%Y%m%d_%H%M%S)}"
REPS="${REPS:-4}"
export ROS_DOMAIN_ID="${SIM_DOMAIN:-77}" ROS_LOCALHOST_ONLY=1
export ROS_LOG_DIR="$OUT/roslog"          # ROS 로그를 eMMC(~/.ros) 대신 결과 폴더(SSD)에
set +u                                    # ROS 설정 파일은 정의 안 된 변수를 씀
source /opt/ros/galactic/setup.bash
source "$CART/install/setup.bash"
set -u
MAP="$CART/src/hospital_mission/map/my_map.yaml"
PARAMS="$CART/src/hospital_mission/config/agv.yaml"
LABELS="$CART/src/hospital_mission/map/map_labels.json"
BUS="$OUT/bus"
mkdir -p "$BUS/nav_request" "$BUS/nav_request_done"
if pgrep -x bt_navigator >/dev/null || curl -s -m 1 -o /dev/null http://127.0.0.1:8000/; then
  echo "⚠ 실제 주행 스택이나 안내 서버가 돌고 있습니다. CPU 경쟁을 피하려면 끄고 실행하세요." >&2
fi
read -r HX HY HYAW < <(python3 - "$LABELS" <<'EOF'
import json, math, sys
for z in json.load(open(sys.argv[1], encoding="utf-8"))["zones"]:
    if z["name"] == "초기 위치":
        g = z["nav_goal"]
        yaw = math.atan2(2 * g["qw"] * g["qz"], 1 - 2 * g["qz"] ** 2) if "qz" in g else math.radians(g.get("yaw_deg", 0))
        print(g["x"], g["y"], yaw)
EOF
)
echo "결과 폴더: $OUT · 초기 위치 ($HX, $HY, $HYAW rad) · 도메인 $ROS_DOMAIN_ID · 목적지별 $REPS 회"
PIDS=()
cleanup() {
  for p in "${PIDS[@]}"; do kill -INT -- -"$p" 2>/dev/null; done
  sleep 3
  for p in "${PIDS[@]}"; do kill -KILL -- -"$p" 2>/dev/null; done
}
trap cleanup EXIT INT TERM
setsid python3 -u "$HERE/fake_robot.py" --ros-args -p map_yaml:="$MAP" -p x:="$HX" -p y:="$HY" -p yaw:="$HYAW" \
  > "$OUT/fake_robot.log" 2>&1 &
PIDS+=($!)
setsid ros2 launch "$HERE/sim_nav.launch.py" map:="$MAP" params_file:="$PARAMS" > "$OUT/navigation.log" 2>&1 &
PIDS+=($!)
SIM_BUS="$BUS" setsid python3 -u "$HERE/nav_request_watcher_sim.py" > "$OUT/nav_request_watcher.log" 2>&1 &
PIDS+=($!)
NAV_BUS_DIR="$BUS" setsid python3 -u "$ROOT/scripts/return_home_watcher.py" > "$OUT/return_home.log" 2>&1 &
PIDS+=($!)
python3 -u "$HERE/sim_exp2.py" --bus "$BUS" --labels "$LABELS" --navlog "$OUT/navigation.log" \
  --retlog "$OUT/return_home.log" --out "$OUT" --reps "$REPS" --dests "${DESTS:-내과,외과,소아청소년과,산부인과,마취통증의학과}" 2>&1 | tee "$OUT/sim_exp2.log"
