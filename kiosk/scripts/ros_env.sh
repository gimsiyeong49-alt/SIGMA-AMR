#!/usr/bin/env bash
# =========================================================================
# ros_env.sh — ROS2 환경 설정 (사용자의 수동 실행 절차와 동일하게 맞춘 것)
#
#   다른 스크립트에서:  source "$(dirname "$0")/ros_env.sh"
#
# ※ CYCLONEDDS_URI 주의:
#   ~/.bashrc 는 CYCLONEDDS_URI(=cyclonedds_lo.xml, 루프백 전용)를 export 하지만,
#   사용자의 실제 기동 절차는 매 터미널에서 이것을 unset 한다. 여기서도 동일하게
#   unset 해야 브링업/내비와 같은 조건이 된다.
# =========================================================================

# ROS setup 스크립트들은 미설정 변수를 참조하므로 set -u 환경에서 잠시 해제한다.
_ros_env_had_u=0
case "$-" in *u*) _ros_env_had_u=1; set +u ;; esac

# shellcheck disable=SC1091
source /opt/ros/galactic/setup.bash
if [ -f /mnt/ssd/cart_ros2/install/setup.bash ]; then
  # shellcheck disable=SC1091
  source /mnt/ssd/cart_ros2/install/setup.bash
fi

export ROS_DOMAIN_ID=30
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
unset CYCLONEDDS_URI

[ "$_ros_env_had_u" = "1" ] && set -u
unset _ros_env_had_u
