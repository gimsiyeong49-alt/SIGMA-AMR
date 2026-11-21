# HANDOFF.md — 웹 <-> VS Code 인수인계 요약

> claude.ai 웹에서 이 내용을 읽고 다음 사이클(사이클 5)을 기획한다.
> 반대로 웹에서 새 기획이 나오면 PLAN.md로 옮긴다.
> **최종 갱신: 2026-09-02**
> - 사이클 3~5(로봇 주행): 2026-07-21 (섹션 0~6)
> - **[ui-dev 트랙] 접수·다국어(S-04) 섹션 7 / 사이클5(응급·대기·admin보안) 섹션 7.5 / 사이클6(디자인 시스템·흐름 체계화) 섹션 7.6 (별개 트랙)**

---

## 0. 다음에 할 일 (사이클 5 목표) ★

> **"AGV 전원을 켜면 자동으로 스크립트가 실행되어, 최종적으로 음성인식 화면이 뜬다.
>  단, 브링업·내비게이션 등 백엔드 기동 과정은 화면에 보이지 않고, 화면에는 처음부터 음성인식 화면만 나온다."**

핵심 요구:
- **전원 ON → 자동 실행** (사람이 터미널에서 명령을 치지 않아도 됨)
- 브링업·내비·whisper·복귀감시 등은 **백그라운드/숨김**으로 기동 (터미널 로그가 화면에 안 보이게)
- 화면에는 **부팅 직후부터 음성인식 화면(키오스크)** 만 표시

고려할 것 (구현 시 조사 필요):
- 자동 실행 수단: systemd user 서비스 / `.desktop` autostart / `~/.bashrc` 등 — 어느 것이 sudo(장치권한)·ROS 환경과 맞는지.
  현재 `start_all.sh`는 **sudo 비밀번호를 물어봄** → 자동 실행하려면 비번 없는 sudo(sudoers NOPASSWD 특정 명령) 설정이 필요.
- 브라우저 키오스크: `chromium --kiosk` 를 백엔드 준비 완료 후 자동 실행. 준비 전까지 "잠시만요" 화면 or 검은 화면.
- **초기 위치 자동 지정([5]단계)** 은 로봇이 실제 초기 위치에 있어야 함 → 전원 자동기동과 어떻게 조화시킬지(항상 초기 위치에서 부팅한다고 가정?).
- 백엔드 준비가 끝나기 전 음성 버튼을 누르면? → 준비될 때까지 버튼 비활성 or 대기 표시.

---

## 1. 사이클 3 목표 — 달성 ✅ / 사이클 4 — 이동 화면 개선

### 사이클 3 (실제 로봇 왕복) — "만족스러운 결과" (2026-07-20)
```
음성 인식 → 안내도 하이라이트 → "네" → 실제 주행 → 도착
        → 5초 후 음성 화면 복귀 + 로봇 자동 복귀 → 초기 위치·초기 방향까지 정밀 복원
```



### 사이클 4 (이동 화면 실시간 표시) — 진행 중
좌표 변환을 재시도했으나 **불가 판정** → 방식을 바꿔 완성:
- **안내도↔맵 2차원 변환은 성립하지 않음.** 안내도는 축척도가 아니라 모식도(건물 실측 1:4.28 vs
  이미지 2.07:1), nav_goal은 "방 앞 복도" 좌표라 방 위치를 대표 못 함 → similarity 잔차 **RMS 3.79m**.
- 대신 **"안내도 위 모식 경로 + 실제 진행률"**: 로봇 머리(이모지)가 복도를 따라 이동.
  - 진행률 = 1 − (남은 거리 / 처음 거리), **좌표 변환 없이** 계산(로봇·목적지 둘 다 map 좌표).
  - 경로는 복도 위에만(로봇은 방 안 진입 안 함), 출발점은 원무과 왼쪽 복도(START_X=63%).
  - 경로를 점 트랙으로 표시(지난 점 초록, 남은 점 회색), 남은 직선거리(m) 표시.
  - 마커 크기는 복도 폭에 맞춤(vh 스케일).

---

## 2. 지금 어떻게 실행하나 (현재는 수동)

### 전체 기동 (한 줄)
```bash
cd /mnt/ssd/projects/myproject
./scripts/start_all.sh          # 종료 Ctrl+C
```
7단계: 장치권한(sudo) → ROS환경 → 브링업 → 내비 → 초기위치 자동지정 → 복귀감시 → 앱+whisper.
각 단계는 `ros2 node list`로 준비 확인 후 진행. 이미 뜬 브링업/내비는 건너뜀(중복 기동=이중 모터제어 위험).

> ⚠️ 실행 전 **로봇을 초기 위치에 물리적으로 세워둘 것** ([5]단계가 amcl에 초기위치를 알려줌).

### 개별 도구
| 명령 | 용도 |
|---|---|
| `./scripts/run_app.sh` | 앱+whisper만 |
| `./scripts/get_pose.sh` | 현재 로봇 자세 출력 |
| `./scripts/set_home.sh` | 지금 서 있는 자세를 "초기 위치"로 등록 (주차 후 1회) |
| `./scripts/set_initial_pose.sh` | RViz 2D Pose Estimate 자동 대체 |
| `./scripts/return_home_watcher.sh` | 복귀 감시 단독 실행(로그 실시간) |

---

## 3. 구조 (누가 무엇을 하나)

```
[브라우저 앱]  ──POST /listen──▶ [kiosk_server]  ──▶ whisper-server(8080, GPU)
     ▲                                │  도메인 프롬프트 주입 → 장소 매칭
     │ GET /robot_status(진행률·pose)  │
     │         POST /nav ──▶ nav_request/*.json ──▶ [nav_request_watcher] ──▶ Nav2
     │                            (파일버스)          (기존 코드, 수정 안 함)
     └──── kiosk_status.json ◀── [return_home_watcher] ── TF(map→base) 도착판정
                                        └─▶ 복귀 요청 + 도착 후 방향 정밀 정렬(/cmd_vel)
```
**설계 원칙**: 기존 `nav_request_watcher.py`는 한 줄도 수정 안 함. 도착 감지·복귀·정렬·진행률은
전부 별도 노드 `return_home_watcher.py`가 담당.

### 역할 분리
| 항목 | 담당 |
|---|---|
| 목적지 주행·정지 | Nav2 (방향 강제 안 함: `yaw_goal_tolerance=3.14159`) |
| 초기 위치 방향 복원 | return_home_watcher의 TF 폐루프 정렬 (0.5° 이내) |

### 핵심 파일
```
scripts/start_all.sh            # 전체 순차 기동 (7단계) — 사이클5에서 '자동·숨김' 대상
scripts/run_app.sh              # 앱+whisper 원클릭
scripts/ros_env.sh              # ROS 환경 (DOMAIN_ID=30, CYCLONEDDS_URI unset)
scripts/kiosk_server.py         # /listen /goal /nav /nav_status /robot_status
scripts/return_home_watcher.py  # 도착감지→복귀→방향정렬 + 이동 진행률 발행
scripts/set_home.py/.sh         # 현재 자세를 초기 위치로 등록
src/js/app.js                   # 화면 흐름 + 이동화면(로봇 머리) + 도착 후 자동복귀
src/js/data/guideRoute.js       # 안내도 위 모식 경로/점 트랙 (좌표변환 대체)
src/js/robotController.js       # /nav 전송 + waitArrival(진행률 폴링)
src/js/config.js                # useMock=false
```

---

## 4. 값비싸게 배운 것 (반복하지 말 것)

1. **Nav2 도착 정밀도를 `yaw_goal_tolerance`로 조이지 말 것.** 조이면 목표 방향 맞추려 회전 반복 →
   recovery 갇힘 → goal 영영 미완료 → 다음 명령까지 막힘. 정밀도는 "도착 후 폐루프 보정"으로.
2. **다른 컨트롤러(Nav2) 주행 중 `/cmd_vel`에 끼어들지 말 것.** 충돌로 20초간 순 회전 1.12°(떨기만).
   `wait_until_stopped()`로 정지 확인 후 개입.
3. **이 로봇은 명령 각속도의 약 12%로만 회전**(0.4→0.048rad/s). 실측 회전율 기반 자동 상향 필요.
4. **whisper-server를 같은 프로세스 그룹에 띄우면 앱 Ctrl+C에 같이 죽음** → `setsid` 필수.
   `setsid`+`$!` 도 위험(fork 시 죽은 PID) → 세션리더가 자기 `$$`를 파일에 기록.
5. **라이다 2개 동시 `SL_RESULT_OPERATION_TIMEOUT` = 전원 의심**(USB-UART는 USB 전원만으로 인식됨).
6. **환경변수 함정**: `STT_AUDIO_DEVICE`가 `--device`보다 우선. `CYCLONEDDS_URI`는 매 터미널 unset.
7. **좌표(초기위치/목표)를 옮길 땐 my_map.pgm 자유공간 안인지 먼저 확인.** 벽·미탐색으로 나가면
   Nav2가 못 가 도착반경(0.8m) 밖에서 정지 → 복귀/정렬이 영영 시작 안 됨.
   (실측: 초기위치 오른쪽은 벽까지 0.25m뿐인데 1m 이동 요청 → 실패, 되돌림.)
8. **함수 단위 테스트만으론 "주변 코드 삭제"를 못 잡음.** 편집 후 AST 미정의참조 검사 + 상위 진입점 통합 실행.

---

## 5. 남은 것 / 확인 필요

- **초기 위치 조정 한계**: 로봇 오른쪽은 벽까지 0.25m뿐(더 못 감). 여유 = 뒤 1.0m/왼쪽 1.1m/앞 2.0m.
  현재 등록값은 "만족" 시점 값(x=-22.4157, y=47.4429, yaw=175.55°)으로 되돌려 둠.
  기둥 회피가 더 필요하면 오른쪽 말고 뒤/각도로 접근.
- **amcl 추정 vs 실제**: 정렬 완료 로그가 `오차 0.2°`인데 눈으로 틀어져 보이는 경우 있었음 — 재확인 필요.
  있다면 소프트웨어 정밀도가 아니라 위치추정 문제.
- **약국 nav_goal 없음** → 앱에서 "안내 준비 중" 차단 중. 좌표 추가 시 자동 반영.
- **위치 정밀 복원(병진)** 은 장애물 위험으로 미구현(방향만 정렬).
- **PLAN.md 저장 문제**: 사이클 3은 채팅 지시로 진행. 사이클 4 PLAN은 파일에 반영됨(사이클2 잔여 위에 append됨).

---

## 6. 튜닝 파라미터 (환경변수)

```bash
# 복귀 감시 / 정렬
RETURN_DELAY_SEC=5      ARRIVE_RADIUS=0.8      ALIGN_TOL_DEG=0.5
ALIGN_MAX_W=0.8         ALIGN_TIMEOUT=90       ALIGN_ENABLE=0(끄기)
# 음성
WHISPER_PROMPT="원무과 내과 외과 약국 ..."   STT_AUDIO_DEVICE=plughw:1,0(미지정 시 자동감지)
# 이동화면 출발점 (src/js/data/guideRoute.js)
START_X=63   # 안내도상 출발 x%(원무과 왼쪽 복도). 값 클수록 오른쪽.
```

## 참고 · 빠른 검증
```bash
curl -X POST localhost:8000/listen -d '{"text":"원무과 어디"}'   # 매칭
curl "localhost:8000/goal?id=wonmu"                              # 목표 좌표
curl localhost:8000/robot_status                                 # 상태·진행률
tail -f logs/return_home.log                                     # 복귀·정렬 로그
```

---

## 7. [ui-dev 트랙] 병원 접수·다국어 시나리오 (S-04) — 2026-09-02

> ⚠️ **이 섹션은 로봇 주행(섹션 0~6)과 별개 트랙.** `ui-dev` 브랜치에서 `start_ui.sh`(UI 전용, 로봇 스택 없음)로만 진행한 브라우저 UI 실험. **main/start_all은 동결**(프로덕션 기준선). 여기 변경은 사용자가 명시할 때만 나중에 start_all에 병합한다.
> 시나리오 정의는 `SCENARIOS.md`, 세부 로그는 `PROGRESS.md` 참조.

### 한 것 ✅
- **홈 2단계 + 언어 전환**: 홈에 큰 박스 2개(왼쪽 "접수 안내" / 오른쪽 "위치 안내"). 위치 선택 시 마이크 버튼 등장. 우상단 **국기 4개(🇰🇷🇺🇸🇯🇵🇨🇳)** 로 UI·답변 언어 전환(localStorage 저장). **어드민은 한국어 고정(제외).**
- **위치 안내(S-01)**: 기존 길안내 + **LLM 매칭(gpt-4o-mini, start_ui 전용)** — 동의어·오인식·타국어 발화까지 진료과로 매핑. 규칙매칭 실패 시에만 OpenAI 폴백(비용 최소).
- **접수(S-04)**:
  - **초진**: 이름·주민번호·연락처 입력 → 환자 데이터셋 저장 → "어디가 불편하세요?"(음성/타자) → **트리아지(증상→진료과)** → 해당 진료과 **대기명단 등록** → 위치 안내 제안.
  - **재진**: 이름·주민번호 → **예약 조회** → 예약 있으면 그 진료과에 **자동 등록**(간호사가 적어둔 증상 반영, 예약 소비) / 없으면 증상 흐름.
- **간호사 admin(`?admin=1`)**: **탭 3페이지** = 환자 데이터셋 / 예약 명단 / 대기 현황. 데이터셋·예약은 **이름·주민번호·전화번호순 정렬**. 예약 등록은 **날짜(년월일)·증상/사유** 포함. 각 칸/항목 **삭제** 버튼.
- **저장 분리(관심사 3파일, SSD `data/`, gitignore)**: `patients.json`(등록 정보만) · `reservations.json`(예약 별도) · `waitlist.json`(대기). 한쪽 삭제해도 다른 쪽 안전. **주민번호 평문 저장 금지** — 표시용 마스킹(`900101-1******`) + 매칭용 sha256 해시만.
- **다국어(한/영/일/중)**: 홈·위치안내·접수 흐름 전부 번역. 증상→진료과 LLM이 4개국어 발화 매핑. 진료과 정식명(영/일/중) 포함. **안내도 이미지 라벨은 한글 유지**(답변 텍스트만 번역).
- **원무과 추가**: 진단검사의학과 오른쪽 옆 작은 방을 원무과(접수창구)로 지정 + 안내도에 세로 라벨(이미지에 구움). AGV 초기 위치 정면이라 주행 불필요.

### 서버 엔드포인트 (kiosk_server.py, start_ui 전용)
`/listen`(장소매칭) · `/triage`(증상→진료과) · `/patient/register` · `/patient/remove` · `/reservation/check` · `/reservation/set`(날짜·증상) · `/reservation/remove` · `/waitlist`(GET·환자목록·예약·대기) · `/waitlist/add`(consumeReservation) · `/waitlist/remove`.
LLM 매칭·트리아지는 `LLM_MATCH_ENABLE=1`(start_ui.sh만 설정) + `OPENAI_API_KEY`(루트 `.openai_key`, gitignore) 필요.

### 남은 것 / 미해결 ⚠️
- **마이크·스피커 없음** → 음성 경로 미검증. STT(Whisper)는 현재 `language="ko"` 고정. **지금은 전부 타자 기준.**
- **일/중 native 이름 타이핑 불가(물리 키보드)**: 지금은 **로마자 입력**으로 처리(외국인 접수 현실과 일치, 이름칸 안내문 로마자로 표시). 한자/가나 native 입력은 **터치스크린 전환 시** 온스크린 키보드 또는 OS IME(ibus)로 해결 예정. (eMMC 여유<1GB → 설치 전 용량 확인 필요)
- **음성으로 이름 받아쓰기**: 동음 한자 문제로 부정확 → 이름엔 부적합(증상 등 일반 발화엔 적합). 보류.
- **예약 = 근사**: 실제 병원 예약 시스템 연동 없음. 간호사가 admin에서 직접 기록하는 방식.
- **대기명단 운영**: ✅ 사이클5에서 호출/순번/완료·환자 대기화면까지 완결(아래 섹션 7.5).
- 접수 흐름 다국어는 구현했으나 **음성 부분은 마이크 없어 미검증**.

### 다음에 기획할 것 (웹, 사이클 6 후보)
- **터치스크린 온스크린 키보드**(로마자 우선) → 이후 CJK IME(한자/가나 native 입력).
- **마이크 도입 시**: 국기 선택에 맞춰 Whisper 언어 전환(음성 다국어), 증상 음성 입력 검증 + 음성 응급 키워드 검증(D-10 잔여).
- start_ui 실험분을 **start_all(프로덕션)에 병합할 시점** 결정.
- (선택) 실제 EMR/예약 시스템 연동, 대기 현황판(대형 디스플레이).

### 백업 지점 (ui-dev)
태그: `pre-english`, `multilang-zh-done`, `reception-label-done`, `s04-triage-done`, `cycle5-done` (+ `backup/*` 브랜치). 문제 시 복구용.

---

## 7.5 [ui-dev 트랙·사이클 5] 접수 시나리오 강화 완료 — 2026-09-02

> 목표(데모 수준): 응급을 태연히 접수하지 않게 안전 경계 + 대기명단 "호출·순번·완료" 완결 + admin 무방비 노출 차단.
> 상세 로그 PROGRESS.md(2026-09-02 항목들), 계획 PLAN.md(사이클5). 전부 ui-dev / start_ui.

### A. 응급 안전 경계
- **응급 키워드 필터를 LLM 트리아지보다 먼저**(규칙 기반). 통과한 발화만 /triage LLM. 한/영/일/중 4개국어(KTAS 1~2, 9범주). 클라이언트 `isEmergency` + 서버 `/triage` 안전망(응급이면 `{emergency:true}` 반환, LLM 호출 안 함).
- 응급 판정 시 **트리아지·대기등록 안 하고** 전용 화면(🚨 크게·다국어·배경 점멸) + **[직원 호출]**(경보음). "119/직원 호출" 안내.
- 비응급 결과엔 **면책 문구 항상 표시**("진단 아님, 의료진과 상담"·4개국어). 추천 진료과는 **강제 아님** — 환자가 다른 과 선택 가능.

### B. 대기명단 운영 완결
- waitlist.json 구조: `{queues:{진료과id:[entry]}, counters:{진료과id:다음순번}}`. entry에 `ticket`(진료과별 순번·재사용 안 함)·`status`(waiting→called→완료 시 제거)·`called_at`.
- admin 대기현황: 항목별 **[호출][완료][삭제]**. 호출 시 상태·시각 기록, 완료 시 정리.
- **환자 대기화면**(접수 완료 후): "순번 N번 / 앞 M명 / 예상 진료과"(4개국어), 2.5초 폴링. 호출되면 초록 점멸 + "🔔 호출되었습니다 — XX로 오세요"(음성), 앞 1명 이하 "곧 순서" 강조.
- 순번·대기줄은 **진료과별 독립**(내과/외과 별개).

### C. admin 접근 통제
- **PIN 게이트**: `ADMIN_PIN` 설정 시(start_ui.sh가 `.admin_pin` 또는 기본 `0000` 로드) 민감 엔드포인트가 `X-Admin-Pin` 헤더 요구. 보호: `GET /waitlist`, `/patient/remove`, `/reservation/set·remove`, `/waitlist/remove·call·done`. 개방(환자용): `/waitlist/add·status`, `/reservation/check`, `/patient/register`, `/triage`, `/listen`. 확인: `/admin/auth`.
- ?admin=1 → PIN 게이트 화면 → 인증 후 진입(모든 admin 요청 `adminFetch`로 헤더 부착).
- **자동 잠금**: admin 3분 무조작 → PIN 폐기·재인증.

### D. 검증 상태
- **서버 4개국어 검증 통과**: (a)응급 분기 ko/en/ja/zh, (b)일반→추천 과, (c)접수→순번→호출→완료.
- **사용자 브라우저 확인 남음**: 응급/대기/면책/PIN **화면 표시**, **마이크 음성** 응급 감지(마이크 없음).

### 신규 엔드포인트(사이클5)
`/triage`(응급 선검사 내장) · `/waitlist/call` · `/waitlist/done` · `/waitlist/status` · `/admin/auth`. waitlist.json 스키마 변경(순번/상태).

### 관리자 PIN 운영
- 기본 `0000`(데모). 변경: 프로젝트 루트에 `.admin_pin` 파일(gitignore) 생성. start_ui.sh 재기동 시 반영.

### 빠른 검증 (사이클5, ADMIN_PIN=1234 예)
```bash
curl -X POST localhost:8000/triage -H 'Content-Type: application/json' -d '{"text":"숨을 못 쉬어요"}'   # → {"emergency":true}
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/waitlist                                        # PIN 없으면 403
curl -s -o /dev/null -w '%{http_code}\n' -H 'X-Admin-Pin: 1234' localhost:8000/waitlist                 # 200
```

### 빠른 검증 (start_ui 실행 중)
```bash
curl -X POST localhost:8000/triage -H 'Content-Type: application/json' -d '{"text":"머리가 아프고 열이 나요"}'   # 증상→진료과
curl -X POST localhost:8000/reservation/set -H 'Content-Type: application/json' -d '{"name":"홍길동","rrn":"900101-1234567","deptId":"internal","date":"2026-09-15","symptom":"정기검진"}'
curl localhost:8000/waitlist                                     # 환자·예약·대기 현황(admin용)
# 브라우저: localhost:8000/?dev=1 (타자 테스트)  ·  localhost:8000/?admin=1 (간호사 관리)
```

---

## 7.6 [ui-dev 트랙·사이클 6] 접수 흐름 체계화 + UI 디자인 — 2026-09-02

> 기능은 사이클5 그대로 유지, **흐름·표현·디자인만** 다듬음(로직·엔드포인트 무변경). 전부 ui-dev/start_ui.
> 상세 PROGRESS.md(2026-09-02 사이클6 항목), 계획 PLAN.md(사이클6).

### A. 디자인 시스템 기반
- **css/tokens.css 신설**: 다크→**라이트 화이트/블루 병원 톤**. 색(primary #1763c9·success·danger + soft/strong, 대비 AA)·글꼴 단계(--fs-xs~3xl, 히어로 vh 캡)·간격·반경·그림자·터치(--touch-min 64px)·포커스링. 하드코딩 색 전부 토큰 수렴.
- **공통 컴포넌트**: 버튼 체계(primary/danger/secondary/ghost+상태), 카드, 입력필드, **스텝 인디케이터**, 스피너.
- **접근성**: 대비≥4.5:1, 터치≥64px, :focus-visible 링, 색+아이콘/텍스트 병행 — tokens.css에 명문화.

### B. 접수 흐름 체계화
- **스텝 인디케이터**(상단): 초진 ①정보입력→②증상→③완료 / 재진 ①본인확인→②확인→③완료 (4개국어).
- **뒤로 가기/수정**: 폼↔선택, 증상↔폼. 입력값 보존(뒤로 시 이름/주민/연락처 복원).
- **무조작 자동 리셋**: 60초(환경변수 KIOSK_IDLE_SEC, /config로 노출) 무조작 → "계속?" 오버레이 → 15초 더 무응답 시 홈 초기화(다음 사람에게 정보 안 남김).
- **입력 검증·친절 안내**: 이름/주민번호(13자리)/연락처(9~11) 형식 검사, 겁주지 않는 ℹ️ 안내(4개국어)+필드 강조.
- **로딩 표시**: 트리아지/등록/조회 구간 "확인 중입니다" 스피너 오버레이.

### C. 화면별 새 디자인
- 홈(파랑 카드+아이콘+부제), 접수 폼(카드·큰 필드·파랑 버튼), 트리아지(추천 chip 파랑 강조+다른 과 선택+면책 박스), 응급(🚨·직원호출 강조), 대기 순번(파랑/호출 초록 패널), admin(탭·표 가독성, 한국어 유지).

### D. 검증
- 내부 화면 렌더(미리보기)로 4개국어 레이아웃 확인(영/일 긴 문장 포함). 스텝/콘텐츠 겹침 수정.
- Chromium 헤드리스 콘솔 에러 0(누적). 기능 무회귀 확인(triage 응급/일반, 대기 순번, PIN 403/200).
- **남은 것**: D-16 실기기 1920×1080 전체화면 최종 조정은 사용자 실기기(스케일 환경)에서 확인 필요.

### 신규/변경 (사이클6)
- 신규: `src/css/tokens.css`, 서버 `GET /config`(idleSec). 환경변수 `KIOSK_IDLE_SEC`(기본 60).
- 백업: `cycle6-done` 태그(+backup/cycle6).

### 다음(사이클 7 후보)
- D-16 실기기 미세조정, 터치스크린 온스크린 키보드/CJK IME, 마이크 도입 시 음성 다국어, start_all 병합 시점.

### 7.6.1 후속: 고DPR/줌 화면 잘림 대응 (진행 중, 2026-09-02)

> 실기기에서 접수 폼·대기 화면 하단(확인·처음으로 버튼 등)이 **잘리는** 현상. 원인·조치·미해결을 정리.

- **원인**: 실기기 디스플레이 배율이 높아(추정 DPR ≈2.6~2.7, 또는 브라우저 줌 상향) **논리 뷰포트 높이가 매우 낮음(≈400px대)**. 새 UI가 커서 흐름 화면이 한두 요소만큼 넘침.
- **조치(누적)**:
  1. 전체 크기 토큰·히어로 요소 축소(1차) → 부족.
  2. `.screen`을 `overflow-y:auto` + `justify-content:safe center`로 → **넘쳐도 잘리지 않고 세로 스크롤**(안전장치). 스텝 인디케이터 absolute→in-flow(겹침 제거).
  3. 흐름 화면(폼·대기) 추가 축소(2차): 카드 여백·필드·확인 버튼·스텝·제목·간격·순번 (터치 최소 42px 유지).
- **검증 방법(중요)**: 헤드리스 DPR 1로는 실조건 재현이 안 됨. `chromium --force-device-scale-factor=2.7`(실기기 이상)로 렌더해야 함. 현재 그 조건에서 폼·대기 **하단 여백 확보하며 전부 표시**됨.
- **미해결/확인 필요**:
  - 사용자 실기기에서 재확인 필요(강력 새로고침). 여전히 잘리면 **브라우저 줌 %**(주소창 ⋮)와 스크린샷 필요.
  - 브라우저 **줌이 100%가 아닐 가능성** → Ctrl+0로 확인 권장(제 디자인은 DPR 2.5에서 이미 맞았는데 실기기가 유독 크게 렌더됨).
  - 근본적으로 매우 낮은 뷰포트(≤400px)에서는 "완전 맞춤"과 "큰 글씨(고령친화)"가 상충 → 최후엔 스크롤 허용으로 데이터 손실은 없음.
- **관련 커밋**: `fix(cycle6) ...` 3건(전체 축소 / 스크롤+폼 vh / DPR2.7 추가 축소).

### 검증 도구 메모 (다음에 재사용)
- 실기기 배율 재현: `chromium --headless=new --force-device-scale-factor=2.7 --window-size=1920,1080 --screenshot=out.png URL`
- 내부 화면(클릭 필요분)은 scratchpad에 실제 CSS를 link한 하네스(`harness.html#form-screen` 등)로 렌더해 확인.
- 콘솔 에러 점검: `--enable-logging=stderr --v=1 --dump-dom` 후 stderr에서 `uncaught|TypeError` grep.

---

## 7.7 [ui-dev 트랙·사이클 7] 접수 시스템 시각 정돈 + 정보 체계화 — 2026-09-02

> 새 기능 없음. 기존 접수 UI를 토큰 기반으로 정돈. 기능(트리아지·대기·예약·PIN·다국어) 불변. ui-dev/start_ui.
> 상세 PROGRESS.md(2026-09-02 사이클7), 계획 PLAN.md(사이클7).

### A. 진단(선행)
- 화면 전수 점검 후 토큰 미준수 목록화: 타이포(var(--fs-*) 12회 vs font-size 35+ → 대부분 자체 clamp), 간격(--sp-* 1회), 반경(999/8/12px 리터럴), 색(하드코딩 rgba·result 다른 빨강·route dot 다른 파랑·admin 헤더 3색). 우선순위 합의: 타이포→색→admin→화면 위계.

### B~C. 정돈(수행)
- **타이포(B-6)**: --fs-* 스케일을 vw+vh min()으로 재정의(낮은 뷰포트 자동 축소) + 전 화면 제목/본문/라벨/버튼이 스케일 사용. 히어로(마이크·순번·응급아이콘·로봇)만 커스텀.
- **색(B-5, C-10)**: 규칙 확립 — 파랑=모든 액션(마이크·듣기·네·확인·예약저장·호출·보조 CTA), 빨강=응급·삭제·지도 타깃, 초록=완료(admin '완료')에만, 회색=부차. 하드코딩 rgba 전부 토큰 팔레트로.
- **간격·반경(B-4·B-7)**: px 리터럴 → --sp-*/--radius-*(pill·sm). 공통 요소(버튼·칩·입력·카드·탭) 반경·간격 통일.
- **admin(C-11)**: 탭·정렬·목록·헤더 타이포/간격/색 정돈, 섹션 헤더색 통일.
- **화면 위계(C-8,9,10)**: 스텝+제목 일관, 주 CTA=파랑 채움 vs 보조=고스트/아웃라인. 초진 폼은 단일 목적이라 분할 안 함.

### D. 검증
- 실기기 배율(--force-device-scale-factor=2.7)로 전 화면 렌더 → 잘림 없이 위계·색·타이포 일관. 콘솔 0. 기능 무회귀.
- 검증 도구: `chromium --headless --force-device-scale-factor=2.7`(실기기 재현), scratchpad 하네스로 내부 화면 렌더. ★창 모드(DPR1)로 보면 실조건과 다름 — 반드시 고DPR로 확인.

### 남은 것 / 다음(사이클 8 후보)
- **화면 잘림(고DPR)**: 7.6.1의 후속으로 이번에 요소 크기 대폭 축소 + `.screen` 스크롤 허용. DPR 2.7까지 여유 확인. **단, 사용자 실기기에서 최종 확인 필요**(브라우저 줌 100%인지 Ctrl+0 확인 권장 — 실기기가 유독 크게 렌더됨).
- 터치스크린 온스크린 키보드/CJK IME, 마이크 도입 시 음성 다국어, start_all 병합.
- 백업: `cycle7-done`(+backup/cycle7), 시작 기준선 `cycle7-base`.

---

## 7.8 [ui-dev 트랙·사이클 7 후속] 국기 언어 선택 접이식 + 카드 겹침 해소 — 2026-09-07

> 홈 화면 우상단 언어 국기 선택 UI 개선. CSS/상호작용만, 기능·다국어 로직 불변. ui-dev/start_ui.
> 상세 PROGRESS.md(2026-09-07 항목 3개), 관련 커밋 3건.

### 배경
- 기존: 4개국 국기(🇰🇷🇺🇸🇯🇵🇨🇳)를 우상단에 항상 전부 노출 → 산만.
- 요구: 평소엔 현재 언어 국기 1개만, 터치하면 세로로 펼쳐 선택.

### 한 것
1. **접이식 국기 선택기**
   - 접힘: 현재(활성) 국기 1개 + 작은 ▾ 힌트만 표시.
   - 터치 → `.lang-bar.open` 세로 4개 펼침 → 국기 선택 시 `setLang()`+접힘. 바깥 클릭 시 닫힘.
   - JS(app.js init): 국기 클릭 시 접힘 상태면 열기만, 열린 상태면 언어 적용+닫기. `document` 클릭으로 닫힘.
2. **펼침 시 카드 겹침 해소**(사용자 실기기 스샷으로 2회 반복 수정)
   - 펼친 목록을 **불투명 드롭다운 패널**(흰 배경·테두리·그림자, z-index 20)로 → 카드 위에 깔끔히 뜸. 개별 국기는 패널 안에서 테두리 없이(선택된 것만 파랑 강조).
   - 국기 크기 소폭 축소(clamp 20→17..24).
   - **홈 메뉴 폭 `min(86vw→76vw, 700px)`**: 뷰포트 무관 좌우 12vw 여백 확보 → 국기 드롭다운과 항상 분리. (82vw로는 실기기에서 여전히 겹쳐 76vw로 재조정.)

### 검증
- 실기기 논리 뷰포트가 예상보다 넓음(**~780px, DPR≈2.4** 로 추정 정정 — 기존 2.7 추정과 다름).
- 헤드리스 렌더(DPR 2.4, 폭 780·860px, 좁게 711px)에서 접힘/펼침 모두 카드-패널 겹침 없음 확인. 콘솔 0.
- scratchpad 하네스: `lang_home.html`(펼침), `lang_home_collapsed.html`(접힘) — 실제 CSS를 file://로 link.

### 참고/남은 것
- 부작용: 홈 카드가 약간 좁아짐(76vw). 사용자 실기기 최종 확인 요청함.
- **검증 도구 정정**: 실기기 재현은 `--force-device-scale-factor=2.4 --window-size=780,440` 가 기존 2.7/1920 보다 실제에 가까움(카드 폭 비율 기준 역산).
- 미해결(이월): 터치스크린 온스크린 키보드/CJK IME, 마이크 도입 시 음성 다국어, start_all 병합.

---

## 7.9 [ui-dev 트랙·사이클 7 B] 접수 시스템 시각 정돈 — 진단 후 실행 — 2026-09-07

> 사이클7 A(진단) 재수행 후 B(정돈) 실행. 환자 공개 흐름 우선 정돈 + admin 실버그.
> 전부 시각/구조 정돈이며 기능(트리아지·대기·PIN·다국어) 로직 불변. main/start_all 무변경.
> 상세 PROGRESS.md(2026-09-07 #1~#5), 계획 PLAN.md(사이클7).

### A. 진단 결과(요지)
- 사이클7에서 이미 상당수 토큰화됨 → "제각각 남은 잔여"에 집중.
- 핵심 발견: (1) 증상입력 필드가 개발용 dev-input 룩(1px)이라 초진 폼(2px)과 불일치, (2) 트리아지 결과 화면만 스텝 없음(흐름 단절), (3) admin 날짜입력 `color-scheme:dark` 잔재(실버그), (4) 팔레트 묶인 rgba 리터럴 산재, (5) 자잘한 매직 px.
- 합의 우선순위(사용자 조정): **1 → 3 → 2 → 4 → 5** (환자 공개 흐름 1·3 먼저, admin 2 다음, 잔여 4·5 마무리).

### B. 실행 결과 (커밋)
1. **#1 증상입력 필드 통일** `5661756` — `#intake-form input`을 초진 폼과 동일 룩(2px --border·--radius·포커스 링·.invalid). CSS만.
2. **#3 결과 화면 스텝 연결** `d7806de` — retry-screen에 `#retry-steps` 추가 + `showRetry(…, stepIdx)`. 트리아지 추천/애매 결과만 stepIdx=1(증상) 전달 → 정보✓→증상→완료 표시. 위치안내 흐름·초진/재진 선택은 미전달(스텝 없음). i18n·트리아지 판단 불변, 제시 구조만.
3. **#2 admin 버그+정돈** `d0c8aae` — 날짜입력 `color-scheme dark→light`(실버그), 예약폼 입력 배경 --bg→--surface + 폼 카드 테두리, 간격 --sp 토큰화, 호출됨 행 강조(--primary-soft + 좌측 4px --primary 액센트).
4. **#4 잔여 색 토큰화** `700c293` — tokens.css에 `--primary-rgb/--danger-rgb/--danger-strong-rgb` 채널 토큰 + `--focus-ring` 토큰화. 마이크펄스·응급버튼그림자·지도하이라이트·경로점 → 토큰 참조. map 그림자 rgba(0,0,0,.35)→--shadow-lg. 로봇 드롭섀도우·모달 스크림은 의도적 유지.
5. **#5 잔여 px→토큰** `1026a9d` — disclaimer/form-note 마진 4px→--sp-1(값 동일). ▾힌트 -2px·step gap 6px·헤어라인 반경은 유지.

### D. 검증(항목별)
- 각 항목: DPR1 전체화면(--force-device-scale-factor=1) 렌더로 깨짐 없음 확인 + 커밋.
- 기능 무회귀: /triage 일반(internal)·응급(emergency) 정상, admin 보호 엔드포인트 무인증 403 유지, 라이브 콘솔 0(전 항목).
- 토큰 치환 `rgba(var(--x-rgb), …)` 실렌더 스와치 확인.
- 하네스: intake.html(증상=초진 필드 일치), retry_result.html(결과 스텝 위계), admin.html(달력 라이트·호출행 강조).

### 결과 상태 / 남은 것
- 환자 공개 흐름(홈→선택→폼→증상→결과→대기/응급)이 입력 필드 룩·단계 표시·색 규칙 모두 일관.
- **서버 재시작 불필요**(정적 파일). 실기기 강력 새로고침으로 반영.
- 사용자 실기기 전 흐름 최종 확인 요망(#3은 HTML/JS도 변경됨 — 새로고침 필수).
- 이월: 온스크린 키보드/CJK IME, 마이크 도입 시 음성 다국어, start_all 병합.

---

## 8.0 [ui-dev 트랙·사이클 8] AI 대화형 문진 — 2026-09-08

> 접수의 증상 입력을 1회 입력 → 짧은 대화형 문진으로. AI가 애매할 때만 되묻고, 종합해
> 추천 진료과 + 증상 요약 생성. 요약은 대기명단에 실어 의료진이 미리 파악.
> 안전이 기능보다 우선: 응급 필터(KTAS)가 문진 전 과정 작동, AI는 진단·병명·약 금지.
> 기존 기능(트리아지·대기·PIN·다국어)·main/start_all 무변경. 백업: cycle8-base / cycle8-done.

### A. 대화 엔진(서버, kiosk_server.py)
- `POST /interview` (무상태): 클라가 messages 전체 전송. interview_next() —
  (a) 매 답변 is_emergency()(기존 KTAS 재사용) 선검사 → 응급 즉시 {action:"emergency"} (LLM 안 부름)
  (b) assistant≥2(MAX_FOLLOWUPS) 상한 → {action:"done"}
  (c) 그 외 LLM(_openai_text 자유출력) → JSON {action: ask/done/emergency}. 파싱실패·무효·LLM off → done.
- `POST /interview/summarize`: is_emergency 재확인 → _triage_match(기존 재사용)로 진료과 id +
  LLM으로 summary_ko(의료진 한국어 요약) + recap(환자 언어). 실패 시 발화 원문 폴백.
- 프롬프트(_interview_prompt): **기본 done**, 애매/다과 가능/위험신호일 때만 질문.
  진료과 구분·위험신호 우선순위 + 재질문 금지 + few-shot + 남은질문수 인지. (2회 조정으로 품질↑)
- 헬퍼: _openai_text / _parse_json_obj / _transcript / _patient_texts / _last_user_text. MAX_FOLLOWUPS=2.

### B. 문진 화면(클라, index.html/app.js/style.css)
- intake-screen을 채팅형으로: #interview-log 말풍선(자동 스크롤) + 통일 입력창 +
  "이대로 접수하기"(항상) + 뒤로/처음으로. (intake-q·wave 제거)
- startInterview/submitAnswer/finishInterview/showInterviewResult/addChatMsg/listenInterview.
  첫 질문(symptomQ)은 UI 전용→상한 정확. interviewBusy 중복방지. 스피너·응급·면책 기존 재사용.
- 결과: retry 화면 재사용 + 리캡 박스(#retry-recap, showRetry 5번째 인자). i18n interview.finish 4개국어.

### C. 대기명단 연결
- waitlist entry에 symptom_summary(한국어 요약) 필드 추가(하위호환). symptom=짧은 주증상.
  addToWaitlist(...,summary) → /waitlist/add symptomSummary → waitlist_add.
- admin 대기현황에 '📝 요약' 줄 표시(.wait-info/.wait-summary, 없으면 symptom 폴백).

### D. 검증
- 응급 우회 4개국어×대화중간 즉시(규칙기반), 진단 회피 4개국어, 중단 무크래시, HTTP 엔드포인트(임시 8011),
  회귀(트리아지·응급·PIN·다국어) 모두 확인. 화면 DPR1/DPR2.4 렌더 정상.

### 남은 것 / 다음 사이클 후보
- ⚠️ 서버+클라 변경 → **start_ui.sh 재시작 필수**. 실기기 전 흐름(초진→문진→종합→대기→admin 요약) 최종 확인 요망.
- 문진 품질 더 필요시 OPENAI_MODEL=gpt-4o 상향(start_ui.sh) 검토.
- 진단질문만 왔을 때 명시적 "진단은 의료진이" 안내 문구 표시(현재는 안전하게 done→수동 선택)는 선택적 개선.
- 음성 문진(구조는 열려 있음: recognizer.listen 병행), 온스크린 키보드/CJK IME는 이월.

---

# 부록: 병원 접수 시스템 — 아키텍처 & 구현 설명 (기술 개요)

> 이 섹션은 진행 기록이 아니라, "이 접수 시스템이 어떤 기술로 어떻게 만들어졌는지"를
> 처음 보는 사람에게 설명하기 위한 개요다. (2026-09 기준, ui-dev 트랙)

## 1. 한눈에

병원 로비의 **키오스크(터치 화면) + 안내 로봇** 프로토타입. 환자가 스스로 접수하고,
증상을 AI와 짧게 대화(문진)해 알맞은 진료과 대기명단에 오르며, 위치 안내는 로봇이 한다.
간호사는 같은 서버의 관리자 화면(PIN)에서 환자·예약·대기를 관리한다.

**설계 철학: 의존성 최소화.** 프런트엔드 프레임워크·빌드 도구·DB·웹서버 프레임워크가 없다.
브라우저 + 파이썬 표준 라이브러리만으로 돌아가 Jetson(arm64)에서 가볍게 구동된다.

## 2. 기술 스택

| 영역 | 사용 기술 | 비고 |
|---|---|---|
| 프런트엔드 | 순수 HTML/CSS/JS (ES Modules) | 프레임워크·번들러 없음. 브라우저가 그대로 로드 |
| 스타일 | CSS 커스텀 프로퍼티(디자인 토큰) | `tokens.css`(값) + `style.css`(컴포넌트) |
| 백엔드 | Python 3 표준 라이브러리 `http.server` | `ThreadingTCPServer`, 외부 웹프레임워크 없음 |
| 저장소 | JSON 파일 3개 | DB 없음. 원자적 쓰기 + 스레드 락 |
| AI(문진·분류) | OpenAI Responses API(`gpt-4o-mini`) | `urllib`로 직접 호출. 키 없으면 규칙기반 폴백 |
| 음성 | STT=whisper 서버, TTS=MeloTTS | 서버의 `/listen`·`/speak` 경유(위치안내 음성용) |
| 로봇 주행 | ROS2 / Nav2 (별도 스택) | 파일버스(nav_request)로 느슨히 연동 |
| 실행 | 브라우저 키오스크(Chromium) + venv 파이썬 | `start_ui.sh`(UI 전용) / `start_all`(전체, 동결) |

## 3. 구성 요소

```
[브라우저 키오스크]  ──HTTP──▶  [kiosk_server.py (파이썬)]  ──▶  patients/reservations/waitlist.json
  index.html                       │  정적 파일 서빙 + JSON API      (파일 저장소)
  css/ (tokens,style)              ├──▶ OpenAI API (문진/트리아지/장소매칭)
  js/app.js (+모듈)                ├──▶ whisper(STT)/MeloTTS(TTS)  (음성)
                                   └──▶ ROS2/Nav2 (nav_request 파일)  (로봇 주행)
```

- **서버는 정적 파일 서버 겸 API 서버** 한 개(`http.server.SimpleHTTPRequestHandler` 확장).
  `src/`를 그대로 서빙하고, 특정 경로만 가로채 JSON으로 응답한다.
- **상태(대화·화면 전환)는 클라이언트가 보유**한다. 서버는 무상태에 가깝고,
  영구 데이터만 JSON 파일에 둔다.

## 4. 프런트엔드 구조

- **단일 페이지, 화면 전환식**: `index.html`에 모든 화면(`<section class="screen">`)이 들어 있고,
  JS가 `.active` 클래스를 옮겨 전환한다(라우터·프레임워크 없음).
  화면: 홈 → (접수/위치) → 초진·재진 선택 → 정보 입력 → AI 문진(채팅) → 종합 결과 →
  대기 현황 / 응급 / 지도·이동 / 관리자(탭 3개).
- **모듈 분리**(`src/js/`):
  - `app.js` — 흐름 오케스트레이션 + i18n + 접수/문진/대기/관리자 로직(핵심).
  - `recognizer/` — 입력 계약(`listen()/cancel()`) 뒤에 실제 STT(whisper)를 숨김.
  - `robotController.js` — `/nav`(주행 요청)·`/speak`(TTS) 호출 래퍼.
  - `data/locations.js`, `data/guideRoute.js` — 장소 id·좌표·경로 모식.
  - `utils/coordTransform.js`, `config.js` — 좌표 변환·전역 설정(층 표기 등).
- **디자인 시스템**: 모든 색·크기·간격·반경·그림자를 `tokens.css`의 CSS 변수로 정의하고,
  화면들은 그 토큰만 참조한다. 그래서 "따뜻한 신뢰" 리테마도 `tokens.css` 값만 바꿔 전체 반영.
  고령친화(큰 글씨·큰 터치·강한 대비), 고DPR 대응(vw+vh `min()` 스케일), 라이트 톤.
- **다국어(한/영/일/중)**: 정적 문구는 `LABELS`(data-i18n 속성), 동적/음성 문구는 `STR`
  함수 테이블로 관리. 국기 버튼으로 전환(관리자 화면은 한국어 고정).

## 5. 백엔드 구조 (kiosk_server.py)

- `SimpleHTTPRequestHandler`를 상속해 `do_GET`/`do_POST`에서 경로를 분기.
  나머지는 부모 클래스가 `src/`를 정적 서빙.
- **주요 엔드포인트(그룹별)**

  | 그룹 | 경로 | 설명 |
  |---|---|---|
  | 환자 | `/patient/register` · `/patient/check` · `/patient/remove`* | 초진 등록 / 재진 본인확인 / 삭제 |
  | 예약 | `/reservation/check` · `/reservation/set`* · `/reservation/remove`* | 재진 예약 조회 / 등록·삭제 |
  | 대기 | `/waitlist/add` · `/waitlist/status` · `/waitlist/call`* · `/waitlist/done`* · `/waitlist/remove`* · `/waitlist`(GET)* | 대기 등록·순번조회·호출·완료·삭제·전체조회 |
  | AI | `/triage` · `/interview` · `/interview/summarize` | 증상→진료과 / 문진 다음질문 / 종합 |
  | 음성·로봇 | `/listen` · `/speak` · `/nav` · `/nav_status` · `/goal` · `/robot_status` | STT / TTS / 주행요청·상태 |
  | 기타 | `/config` · `/admin/auth` | 클라 설정(무조작 리셋 등) / PIN 확인 |

  (`*` = 관리자 전용. `ADMIN_PATHS` + `/waitlist` GET은 `X-Admin-Pin` 헤더 필요. `ADMIN_PIN` 미설정 시 개방)
- **동시성/안정성**: 스레드 서버 + 파일 접근은 `_data_lock`으로 직렬화, 저장은 임시파일 쓰고
  `replace`로 원자적 교체(중간에 죽어도 파일 안 깨짐).
- **AI 호출**: `_openai_classify`(단일 토큰 분류: 장소·진료과)와 `_openai_text`(자유 서술: 문진 질문·요약).
  `LLM_MATCH_ENABLE`+키가 있을 때만 호출하고, 없거나 실패하면 **규칙 기반으로 폴백**(무중단).

## 6. 데이터 저장 (관심사 분리 + 개인정보 보호)

파일 3개로 분리해 한쪽이 지워져도 다른 쪽이 안전:
- `patients.json` — 환자 등록(이름·주민번호(가공)·연락처).
- `reservations.json` — 예약(별도 관리).
- `waitlist.json` — `{queues:{진료과:[대기entry]}, counters:{진료과:순번}}`.
  대기열이 완전히 비면 순번 카운터를 리셋(다음엔 1번부터).

**주민등록번호 취급(핵심)** — 평문 저장 금지:
- **마스킹** `rrn_masked`(예 `900101-1******`) — 공개 화면·매칭 표시용.
- **해시** `rrn_hash`(sha256) — 초진 등록 시 동일 환자 식별.
- **재진 식별** — 앞 7자리(생년월일6+성별1) 마스킹값 + 이름으로 대조(전체 13자리를 받지 않음).
- **암호화** `rrn_enc` — 전체 번호는 기기 로컬 키(`.rrn_key`)로 암호화해서만 저장하고,
  PIN 인증된 관리자 화면에서만 복호화해 전체 표시(의료진용). 표준 라이브러리 HMAC-SHA256 기반.

## 7. 접수 흐름 (환자 관점)

1. 홈에서 **접수 안내** 선택 → **초진/재진** 선택.
2. **초진**: 이름·주민번호(숫자당 한 칸 13칸)·연락처(자동 하이픈) 입력 → 데이터셋 등록.
   **재진**: 이름·주민번호 앞 7칸(뒤 6칸은 `*` 고정) 입력 → 데이터셋 등록 여부·이름 일치 확인
   (미등록/불일치면 차단). 예약이 있으면 그 진료과로 자동 등록.
3. **AI 문진**: "어디가 불편하세요?"로 시작해, AI가 필요할 때만 1~2개 되묻는다(채팅형).
   환자는 언제든 **"이대로 접수하기"**로 중단 가능.
4. **종합**: 대화를 바탕으로 추천 진료과 + 증상 요약(환자에겐 자기 언어 리캡, 대기명단엔 한국어)을 만들어 확인.
5. **대기 등록**: 진료과별 순번을 받고 대기 화면에서 앞 인원·호출 상태를 폴링으로 갱신.
   원하면 로봇이 진료과 위치까지 안내.

## 8. AI 대화형 문진 (사이클8)

- `/interview`: 지금까지 대화(클라 보유)를 통째로 받아 **다음 질문 or "충분함"**을 JSON으로 반환.
  서버 무상태. `/interview/summarize`: 전체 대화 → 추천 진료과(기존 트리아지 재사용) + 요약.
- **프롬프트 원칙**: 기본은 "마침(done)", 증상이 모호하거나 진료과가 안 좁혀질 때만 되묻는다.
  진단·병명·약 언급 금지. 질문은 진료과 구분·위험신호에 결정적인 것 하나만.

## 9. 안전 · 개인정보 (기능보다 우선)

- **응급 필터(KTAS, 규칙기반, 4개국어)**: 트리아지·문진의 **모든 환자 답변을 LLM 호출 전에** 먼저 검사.
  응급 신호면 즉시 응급 화면으로 분기(AI 안 거침). 서버·클라 이중 방어.
- **진단 회피**: AI는 진단/처방/약을 말하지 않고 접수 안내로 되돌림(프롬프트 + 면책 문구 상시).
- **개인정보**: 위 6번(마스킹/해시/암호화). 관리자 기능은 PIN 게이트 + 무조작 자동 잠금.
- **비밀값**: `.openai_key`·`.admin_pin`·`.rrn_key`는 gitignore(커밋 금지). `data/`도 gitignore.

## 10. 실행 · 배포

- `scripts/start_ui.sh` — UI 전용 실행(이 트랙에서 개발/시연에 사용). `LLM_MATCH_ENABLE=1`,
  `OPENAI_MODEL`(기본 gpt-4o-mini), `.openai_key`/`.admin_pin` 로드 후 서버 기동.
- `start_all` — 로봇/주행 포함 전체(프로덕션, **동결**: 이 트랙에선 건드리지 않음).
- 서버는 stt venv 파이썬으로 구동, 포트 8000. 정적 파일 변경은 **새로고침**만,
  서버 코드 변경은 **재시작** 필요.
- 브랜치 전략: 실험·UI는 `ui-dev`, `main`은 프로덕션 동결. 사이클마다 백업 태그(`cycleN-base/done`).

## 11. 설계상 특징 요약

- 프레임워크·빌드·DB 없이 "브라우저 + 표준 라이브러리"만으로 완결 → Jetson에서 가볍고 이식 쉬움.
- 토큰 기반 디자인으로 테마·크기 일괄 제어(고령친화·고DPR·다국어).
- AI는 "있으면 좋고 없어도 도는" 보조(폴백 규칙 상존) → 오프라인/키 없음에도 접수 자체는 동작.
- 안전(응급·진단회피)과 개인정보(주민번호 비평문)를 기능보다 우선하는 이중 방어 구조.

---

## 10.0 [ui-dev 트랙·사이클 10] 의사 화면 + 콜보드 + 진료 상태 흐름 — 2026-09-11

> "환자 키오스크 + 간호사 admin"에 **의사 화면**과 **대기실 콜보드**를 더해 "접수→대기→진료"를 하나로 연결.
> 기존 문진·트리아지·대기·PIN·다국어, main/start_all 무변경. 백업: cycle10-base / cycle10-done.

### 화면 4종
① 키오스크(환자 접수·안내, 공개) ② 간호사 admin(PIN, `?admin=1`) ③ **의사 admin**(PIN, `?doctor=1`) ④ **콜보드**(공개, `?callboard=1`, 대기실 모니터).

### 상태 흐름
`waiting → called → in_progress → done`. 호출=간호사/의사, 진료시작·완료·메모=의사.
완료는 **소프트**(삭제 대신 status=done 보존 → 의사 "오늘 완료"+메모 유지). 순번·앞인원·카운터 리셋은 **활성(waiting/called/in_progress)** 기준.

### 서버(A·B)
- entry 확장(하위호환): `memo`·`in_progress_at`·`done_at`(+`memo_at`).
- 신규: `POST /waitlist/start`·`/waitlist/memo`(PIN), `GET /doctor/queue?dept=`(PIN, 요약·메모 포함), `GET /callboard`(공개, **순번+상태만**). `/waitlist/done`은 소프트로 변경. `/waitlist/status`(환자용)는 status만 반환(메모·요약 미포함).
- 접근통제: 의사·상태전환·메모 엔드포인트는 ADMIN_PIN 뒤. 콜보드/환자 status엔 PII·건강정보 없음.

### 클라(C·D)
- 의사 admin: PIN(공통) → 진료과 선택 → 카드(순번·이름·주민마스킹·초/재진·상태 + 증상요약 + 메모 textarea) + [재호출]/[진료 시작]/[완료], "오늘 완료" 접이 목록. 3초 폴링, 자동잠금 공용. 한국어 고정.
- 콜보드: 진료과별 호출/진료중 순번 대형 표시(2.5초 폴링). 공개·PII 없음.
- 간호사 admin: 진료중(🩺)/완료(✅) 배지, 활성 인원 표시. 환자 대기화면: "진료 중" 반영 + 소프트완료 시 완료 안내.

### 검증(E)
- HTTP 엔드투엔드(임시서버·데이터 백업복원): 접수→호출→콜보드→진료시작→메모→의사조회→완료→상태전파 전부 정상.
- 접근통제: PIN 없이 의사/메모 403, 환자 status·콜보드에 메모·요약·이름·주민 없음. 라이브 콘솔 0(4모드).

### 남은 것 / 다음 사이클 후보
- ⚠️ 서버+클라 변경 → **start_ui.sh 재시작** 후 실기기 전 흐름·전체화면 확인.
- done 항목 자동 정리(당일/기간), 재진 시 과거 진료메모 참고(별도 이력 저장), 여러 의사 동시 진료 편성 — 이월.
- 진입 URL: 의사 `?doctor=1`, 콜보드 `?callboard=1`, 간호사 `?admin=1`.
