#!/usr/bin/env bash
# experiment2.sh — 실험 2(자율주행 단계별 성공률) 기록 도우미 실행. ROS 환경을 불러 로봇 위치 오차까지 자동 기록.
#   사용법: ./scripts/experiment2.sh        진행
#           ./scripts/experiment2.sh 표     표 2 출력 + exp2_summary.md 저장
#   안내 서버(start_guide)와 따로, 다른 터미널에서 실행. 읽기만 함(진행 중 r 확인 시에만 '초기 위치' 복귀 요청).
HERE="$(cd "$(dirname "$0")" && pwd)"
source /opt/ros/galactic/setup.bash
source /mnt/ssd/cart_ros2/install/setup.bash
exec python3 -u "$HERE/experiment2.py" "$@"
