#!/usr/bin/env bash
# =========================================================================
# start_guide_norviz.sh — start_guide.sh 와 같고 RViz(지도 시각화 창)만 끈 버전
#
#   사용법:  ./scripts/start_guide_norviz.sh [앱포트]      (기본 8000) · 종료 Ctrl+C
#   언제:    시연·실사용처럼 RViz 창을 볼 필요가 없을 때. RViz는 CPU를 약 0.5코어(실측 46~57%) 써서
#            끄면 Nav2 제어 주기·음성 처리에 여유가 생긴다.
#   RViz가 필요할 때(경로·costmap 눈으로 확인, 디버깅)는 ./scripts/start_guide.sh
#   ※ 내비게이션이 이미 떠 있으면 start_guide.sh 가 다시 띄우지 않으므로, RViz 켬/끔을 바꾸려면 먼저 Ctrl+C로 끄고 실행
# =========================================================================
HERE="$(cd "$(dirname "$0")" && pwd)"
USE_RVIZ=false exec "$HERE/start_guide.sh" "$@"
