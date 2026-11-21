#!/usr/bin/env bash
# =========================================================================
# start_ui.sh — UI 개발/수정 전용 기동 (로봇 스택 없이 앱 화면만)
#
#   사용법:  ./scripts/start_ui.sh [포트]      (기본 8000) · 종료 Ctrl+C
#
#   하는 일:
#     · kiosk 앱 서버(정적 UI + /goal + /nav 브리지)만 띄운다.
#     · ROS 내비 스택(amcl/Nav2/드라이버)은 전혀 건드리지 않는다 → UI 수정·확인에 집중.
#     · whisper(STT)·tts는 여기서 띄우지 않는다. 이미 실행 중이면 그대로 음성도 동작(재사용).
#
#   언제 뭘 쓰나:
#     · start_ui.sh   → UI만 (레이아웃·문구·화면 흐름 수정). 가장 가벼움. ★이 스크립트
#     · run_app.sh    → UI + 음성(whisper+tts). 로봇 없이 음성까지 테스트.
#     · start_all.sh  → 전체(로봇 스택 포함). 실제 주행.
# =========================================================================
set -uo pipefail   # -e 는 빼둔다(아래 상태확인이 non-zero여도 계속 진행)

PORT="${1:-8000}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "════════════════════════════════════════════════════"
echo " UI 전용 기동 — 로봇 스택 없이 앱 화면만 (수정용)"
echo "════════════════════════════════════════════════════"

# 1) 기존 kiosk 정리 (포트 충돌/중복 방지).
#    대괄호 트릭([k]): 이 스크립트 자신의 명령줄에 매칭돼 self-kill 되는 것을 방지.
if pkill -f "[k]iosk_server.py" 2>/dev/null; then
  echo " · 기존 kiosk 서버 종료"; sleep 1
else
  echo " · 실행 중 kiosk 없음(OK)"
fi

# 2) 음성 서버(whisper/tts) 상태 안내 — 여기서 띄우지 않고, 떠 있으면 재사용만.
code() { curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$1/" 2>/dev/null; }
[ "$(code 8080)" = "200" ] && echo " · whisper(STT) 실행중 → 음성 입력 가능" \
                           || echo " · whisper 없음 → 음성 입력 불가(레이아웃·문구 수정엔 무관)"
[ "$(code 5002)" = "200" ] && echo " · tts 실행중 → 로봇 스피커 음성 출력 가능" \
                           || echo " · tts 없음 → 음성 출력은 브라우저 TTS로 폴백"
echo "   (음성까지 필요하면 run_app.sh 사용)"
echo

# 2.5) LLM 매칭(gpt-4o-mini) — start_ui 전용. 규칙으로 못 잡은 발화를 동의어/오인식까지 흡수.
#      API 키: 환경변수 OPENAI_API_KEY 또는 프로젝트 루트 .openai_key 파일(gitignore).
#      모델 교체: OPENAI_MODEL=gpt-4o 등.
export LLM_MATCH_ENABLE=1
export OPENAI_MODEL="${OPENAI_MODEL:-gpt-4o-mini}"
if [ -z "${OPENAI_API_KEY:-}" ] && [ -f "$HERE/../.openai_key" ]; then
  export OPENAI_API_KEY="$(tr -d '[:space:]' < "$HERE/../.openai_key")"
fi
if [ -n "${OPENAI_API_KEY:-}" ]; then
  echo " · LLM 매칭 ON (모델 $OPENAI_MODEL) — 규칙으로 못 잡은 발화는 OpenAI로 매핑"
else
  echo " · LLM 매칭 대기 — OPENAI_API_KEY 없음(.openai_key 파일에 키 넣으면 켜짐). 지금은 규칙매칭만."
fi
echo

# 2.6) 관리자(간호사) PIN — ?nurse=1 접근 보호. .admin_pin 파일 또는 기본값(데모용 0000).
if [ -z "${ADMIN_PIN:-}" ]; then
  if [ -f "$HERE/../.admin_pin" ]; then
    export ADMIN_PIN="$(tr -d '[:space:]' < "$HERE/../.admin_pin")"
  else
    export ADMIN_PIN="0000"   # 데모 기본값. .admin_pin 파일 만들면 교체됨.
  fi
fi
echo " · 관리자 PIN 설정됨(?nurse=1 접근 시 필요). 변경: 루트에 .admin_pin 파일."
echo

# 3) kiosk 기동. serve.sh 재사용(마이크 자동감지·게인·venv 처리). 포그라운드, 종료 Ctrl+C.
echo " ▶ 브라우저에서 열기:  http://localhost:${PORT}/     · 종료: Ctrl+C"
echo " ▶ 마이크 없이 타자로 질문(개발용):  http://localhost:${PORT}/?dev=1"
echo "    → 홈 화면 입력창에 '내과 어디예요' 처럼 치면 결과가 화면에 글로 뜸"
echo
exec "$HERE/serve.sh" "$PORT"
