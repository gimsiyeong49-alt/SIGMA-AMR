#!/usr/bin/env bash

source /opt/ros/galactic/setup.bash

CONTROLLER_MAC="A0:5A:5C:E3:9C:BA"

echo "=========================================="
echo " AML Bluetooth Joystick"
echo "=========================================="
echo " Linear  : 0.30 m/s (실제)"
echo " Angular : 0.75 rad/s (실제)"
echo " L1 + Left Stick"
echo "=========================================="

echo "[1/3] Bluetooth 연결 확인..."

if ! bluetoothctl info "$CONTROLLER_MAC" | grep -q "Connected: yes"; then
    echo "Wireless Controller 연결 시도..."
    bluetoothctl connect "$CONTROLLER_MAC"
    sleep 2
fi

if ! bluetoothctl info "$CONTROLLER_MAC" | grep -q "Connected: yes"; then
    echo
    echo "[ERROR] 조이스틱 Bluetooth 연결 실패"
    echo "조이스틱 HOME 버튼을 눌러 켠 뒤 다시 joyaml을 실행하세요."
    exit 1
fi

echo "[OK] Bluetooth 연결됨"

cleanup()
{
    trap - INT TERM EXIT

    echo
    echo "[STOP] Joystick control 종료"

    if [ -n "${JOY_PID:-}" ]; then
        kill "$JOY_PID" 2>/dev/null
        wait "$JOY_PID" 2>/dev/null
    fi
}

trap cleanup INT TERM EXIT

echo "[2/3] joy_node 실행..."

ros2 run joy joy_node &
JOY_PID=$!

sleep 2

if ! kill -0 "$JOY_PID" 2>/dev/null; then
    echo "[ERROR] joy_node 실행 실패"
    exit 1
fi

echo "[OK] joy_node 실행됨"

echo "[3/3] teleop_twist_joy 실행..."
echo
echo "=========================================="
echo " READY"
echo
echo " L1 + ↑ : 전진"
echo " L1 + ↓ : 후진"
echo " L1 + ← : 좌회전"
echo " L1 + → : 우회전"
echo
echo " L1 놓기 : 정지"
echo " Ctrl+C  : 조이스틱 제어 종료"
echo
echo " Linear max  : 0.30 m/s (실제)"
echo " Angular max : 0.75 rad/s (실제)"
echo "=========================================="
echo

# 2026-11-15: ① 속도 2.00→0.30 m/s, 4.80→0.75 rad/s — 11-12 모터 환산 보정(실제=명령) 전엔 실제가 명령의 15.6%라
#   2.00 이 실제 0.31 m/s 였음. 보정 후 그대로 두면 실제 2 m/s(모터 한계까지)를 요구 → 같은 체감으로 환산.
# ② 조이스틱 전용 통로 /cmd_vel_joy 로 보냄 — 모터 드라이버가 빠르게 멈추고(L1 놓으면 0.3초·5cm) Nav2 보다 우선.
#   (/cmd_vel 은 Nav2 용 부드러운 감속이라 놓아도 한참 밀려갔음) 되돌리기: ~/aml_joystick.sh.bak_before_joy_20261115
ros2 run teleop_twist_joy teleop_node --ros-args \
    -r cmd_vel:=/cmd_vel_joy \
    -p axis_linear.x:=1 \
    -p scale_linear.x:=0.30 \
    -p axis_angular.yaw:=0 \
    -p scale_angular.yaw:=0.75 \
    -p enable_button:=4 \
    -p require_enable_button:=true

