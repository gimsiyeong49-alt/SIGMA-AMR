# PROGRESS.md — 실행 진행 기록

> Claude Code가 작업할 때마다 여기에 무엇을 했는지 append 한다.

## 로그
- (2026-07-16) 초기 셋업 완료.
- (2026-07-16) [항목1] src/ 파일 구조 생성: index.html, css/style.css, js/app.js. ES Modules 방식.
- (2026-07-16) [항목2] 풀스크린 키오스크 레이아웃(1920x1080 기준 반응형) + 화면 전환 골격 완성. data-nav 속성 기반 메뉴↔지도 전환(app.js showScreen).
- (2026-07-16) [항목3] 서비스 메뉴 화면: 큰 터치 버튼 4개(길안내/호출/정보안내/복귀) + 안내 메시지 영역. 버튼 클릭 시 안내 텍스트 표시(menuScreen.js).
- (2026-07-16) [항목4] 지도 화면: SVG 평면도(공간+지점 5개)와 로봇 아이콘을 홈 위치에 표시(mapScreen.js). moveRobotTo() 이동 애니메이션 함수도 미리 구현(항목5에서 연결). 지점 좌표는 data/locations.js. 참고: 이 환경에 node 미설치(브라우저 앱이라 불필요), 실제 동작 검증은 항목7에서 진행 예정.
- (2026-07-16) [항목5] 길안내/복귀 흐름 연결: 메뉴에서 길안내(→안내데스크)·복귀(→충전스테이션) 선택 시 지도 화면으로 전환 후 로봇 아이콘이 목적지까지 이동(rAF 애니메이션) + 도착 배너 표시(app.js runGuideFlow).
- (2026-07-16) [항목6] robotController mock 모듈 분리(robotController.js): goTo(Promise)/speak/returnHome. 화면 코드는 이 인터페이스만 호출 → 실제 제어(ROS)로 교체할 단일 지점. goTo 도착 후 speak를 Promise 체인으로 이어붙임. 지도에 안내 배너(setMapMessage) 추가.
- (2026-07-16) [항목7] 로컬 실행 방법 마련: scripts/serve.sh (python3 -m http.server, 추가 설치 0). 아래 "실행 방법" 섹션에 서버 구동 + 크로미움 풀스크린 실행법 기록.
- (2026-07-16) [항목8] 통합 테스트 통과: 서버 구동 후 모든 자산 200/올바른 content-type 확인. chromium 헤드리스 렌더로 JS 모듈 그래프가 오류 없이 실행됨을 검증 — 메뉴 버튼 4개 동적 생성, 지도 SVG 로봇+지점 5개 렌더 확인. (실제 터치 인터랙션 최종 확인은 사용자가 로봇 터치스크린에서 진행 권장.)

---

## 실행 방법 (로컬 테스트)

ES Modules 사용으로 `file://` 직접 열기는 불가 → 정적 서버 필요.

1) 정적 서버 실행 (추가 설치 없음, python3 사용):

```bash
cd /mnt/ssd/projects/myproject
./scripts/serve.sh          # 기본 8000 포트, 다른 포트는 ./scripts/serve.sh 8123
```

2) 브라우저에서 열기: http://localhost:8000/

3) 크로미움 풀스크린(키오스크)로 열기:

```bash
chromium-browser --kiosk --app=http://localhost:8000/
# 또는 일반 풀스크린:  chromium-browser --start-fullscreen http://localhost:8000/
# 키오스크 종료: Alt+F4 (또는 Ctrl+W)
```

- 테스트 흐름: "위치 안내" 터치 → 지도로 전환 → 로봇이 안내데스크로 이동 → 도착 안내 배너.
  "정보 안내" → 메뉴 안내 메시지.

---

## 로그 (추가)
- (2026-07-16) [수정] 서비스 버튼을 4개→2개로 축소: 호출·복귀 제거, "위치 안내"(구 길안내)·"정보 안내"만 유지(사용자 요청, 현재 불필요 기능 정리). app.js runGuideFlow의 복귀(returnHome) 분기 제거. robotController.returnHome()은 mock 인터페이스로 보존.
- (2026-07-16) [4F 안내도] 실사 사진(map/7839.jpg, 유리 안내판 촬영본)을 기반으로, 빛 반사·입체감·모든 호실 번호/이름을 제거한 벡터 평면 안내도(assets/floor-4f.svg)를 새로 작성. 4곳만 이름 표기(410 약국·411 내과·412 외과·415 원무과), 나머지 방은 빈 박스. 각 지정 방에 id(room-410 등) 부여(향후 붉은 하이라이트용).
- (2026-07-16) [4F 안내도] mapScreen을 평면도 로더로 교체(fetch로 SVG 인라인). 위치 안내 버튼 → 4F 안내도 표시로 연결. 기존 추상 지도/로봇 이동 애니메이션은 제거, robotController는 콘솔 mock으로 축소(실제 제어 교체 지점 유지). data/locations.js를 진료실 좌표(ROOMS)로 재작성.
  ※ 아직 미구현(사용자 지시대로): 음성 인식, 방 붉은 반투명 하이라이트, 안내 시작 네/아니오, 정보 안내 질의응답. 현재는 "위치 안내 → 안내도 표시"까지.
- (2026-07-16) [4F 안내도 간략화] 사용자 요청 반영해 floor-4f.svg 재작성: (1) 상/하단 방 사이 복도 폭 확대, (2) 중앙 상단 = 지하 1층(↓)/2층(↑) 표기(현재 층=1층 가정), (3) 중앙 하단 계단 실선 → "입구"(문틀+진입 화살표), (4) 양 끝 계단/빈 공간 제거로 간결화. 방 id(room-410 등) 유지.
- (2026-07-16) [1F 안내도 규격 조정] floor-4f.svg → floor-1f.svg 로 재작성/개명: (1) 제목 4F→1F, (2) 입구 폭 = 좌·우 벽 폭(각 120) 대칭, (3) 좌/우 방을 중앙 컬럼 모서리(860/1220)에 딱 맞춰 입구 가림 제거, (4) 약국을 원무과 바로 옆(하단 우측)으로 이동, (5) 복도 폭 추가 확대·전체 규격 정돈. mapScreen fetch 경로·index.html 헤더·locations.js(ROOMS 좌표, 약국 이동) 함께 갱신.
- (2026-07-16) [화장실 추가] 중앙 상단 계단(지하1층/2층)을 오른쪽으로 압축(각 폭 180→120)하고, 왼쪽 빈 공간에 화장실 추가 → 화장실|지하1층|2층 3등분. 화장실 픽토그램(남/여) + 라벨, room-restroom id 부여. locations.js ROOMS에 화장실(향후 안내 대상) 추가.
- (2026-07-16) [안내도 디테일] 7839 반영: (1) 좌상단·우상단 코너에 좁은 계단 추가, (2) 화장실↔중앙계단 사이 여백(960~992), (3) 내과·외과 라인 좌측 이동(우측 끝 코너 계단 공간 확보), (4) 약국을 원무과보다 좁게(105 vs 165). locations.js ROOMS 좌표 갱신.
- (2026-07-16) [안내도 규격 정밀화] (1) 양 끝 코너 계단을 좌·우 2칸으로 분할, (2) 화장실↔중앙계단 여백 확대(65) + 중앙계단 추가 압축(114→100), (3) 입구 폭 축소(120→80), (4) 416호(하단 좌측 끝) 폭 축소(65), (5) 전체 7839 규격 근접(복도 폭은 유지). locations.js ROOMS 좌표 갱신.
- (2026-07-17) [번호 기반 안내도로 전환] map/Screenshot.png(정보공학관 4층평면도, 치수 포함 CAD 도면) 구조/치수 기반으로 floor-1f.svg→floor-4f.svg 재작성. 방 한글 이름 전부 삭제, 번호(401~419)만 표기. 시설은 기호 유지: 화장실 픽토그램·엘리베이터(▲▼)·계단(평행선)·코너 계단(좌우 2칸)·하부 로비 계단(X)·입구(화살표). 방 폭 비율을 도면에 맞춤(401~408 좁게, 417/413 넓게, 416/414 좁게, 410~412 중간). 층 표기 1F→4F(방번호 4xx와 일치). mapScreen fetch·index.html 헤더·locations.js(ROOMS 18개, name 비움) 갱신. my_map.pgm은 SLAM 점유지도(참고용, 변환도구 부재로 직접 렌더 생략).
  ※ 미해결: 층을 1F(병원)로 되돌릴지 4F(도면 원본)로 유지할지 사용자 확인 필요. 진료과 이름은 추후 재매핑 예정.
- (2026-07-17) [실측 비율 반영 재작성] my_map.pgm(PIL로 분석)에서 건물 footprint ≈ 22.3m x 95.45m, 가로세로비 ≈ 4.3:1(길고 납작) 확인. Screenshot.png 중앙부 확대로 배치 확인(상단 중앙=화장실·엘리베이터(X)·계단, 중앙 하단=계단실 2곳 사이 로비+입구). floor-4f.svg를 길고 납작한 실측 비율로 전면 재작성, 중앙 순환부 위치 정정(이전엔 어색했음). locations.js ROOMS 좌표 갱신. (참고: pgm은 SLAM 점유지도라 rotate 후 랜드스케이프로 렌더해 확인)
- (2026-07-17) [픽셀 정밀 재현] 손그림이 계속 틀려서, Screenshot.png의 실제 벽을 PIL 투영분석(수직/수평 프로젝션 피크)으로 검출해 방/코어/계단 경계 픽셀 좌표를 그대로 SVG 좌표계로 사용. 검출값: 상단 좌계단86-119, 401~408(각~34px, 119~394), 화장실394-432·EV432-494·계단537-590, 410(590-692)·411(692-793)·412(793-895)·내부계단895-929·외부계단941-968; 하단 419(107-221)·418(221-322)·417(322-456)·416(456-494)·로비494-622·415(622-760)·414(760-793)·413(793-934)·우계단934-968; 하부 로비 계단실 2곳+입구. 원본과 상하 비교 이미지로 정렬 확인. locations.js도 동일 픽셀 좌표로 갱신.
- (2026-07-17) [7839 대조 다듬기] 7839.jpg 안내판에서 방별 채움색을 PIL로 샘플링(어두운 텍스트 픽셀 제외). 색 배정: 노랑(401,402,404~408)·청록(403 공실)·보라(410~412,414)·분홍(419,418,417,416,415,413). SVG에 색 코딩 반영, 화장실 아이콘 파란색(남/녀), 계단·입구에 녹색 비상구 마커 추가. 7839와 상하 비교로 확인.
- (2026-07-18) [하이라이트 정렬 재수정] 사용자 스크린샷(1920x1080)에서 빨간 영역이 위로 밀리는 문제. 원인 = 좌표가 아니라 CSS 레이아웃: 화면이 세로로 빠듯하면 flex가 .map-wrap을 이미지보다 짧게 줄이고 overflow:hidden이 이미지 하단을 잘라, 하이라이트 %가 이미지와 어긋남(헤드리스 작은 창에선 안 드러남). 해결: .map-wrap을 flex:0 0 auto + width:fit-content로 이미지 크기에 정확히 맞추고, #map-img를 max-width/max-height(60vh)로 종횡비 유지 축소. 안내 배너는 지도 겹침/글자 잘림 있어 지도 아래 패널로 이동. 1920x1080에서 4개 방 모두 정위치 확인. (사용자 지적: 빨간 화살표가 회색조로 어두워 dark<110 벽검출에 섞이던 것도 navy-only 마스크로 확인했으나, 실제 배포 좌표는 이미 방에 맞았고 렌더링이 문제였음)
- (2026-07-18) [하이라이트 정렬 수정] 빨간 영역이 방과 살짝 어긋나던 문제: flat_map에서 4개 방 벽 픽셀 정밀 검출(상단 방 y190-314, 하단 y356-478; 내과 x1132-1280·외과 x1280-1428·원무과 x1177-1366·약국 x1366-1428) → locations.js rect를 정확한 % (안쪽 4px 여백)로 갱신. style.css는 방 밖으로 삐지던 box-shadow 링 제거. 4개 방 모두 인앱 렌더로 정위치 확인.
- (2026-07-17) [방향 전환: 7839 사진 직접 편집] 사용자 요청으로 벡터 대신 7839.jpg 원본 사진을 cv2로 편집. (1) 한글=작은 dark 컴포넌트(높이<35px), 번호=큰 글자(높이>=35px)로 분류(측정 기반)→한글만 모폴로지 클로징으로 방 색 채워 제거, 번호 유지. (2) 배경(도면 밖) 반사→균일 회색 교체. (3) 밝은 스페큘러 인페인트, 하단 제목 제거. 결과: /mnt/ssd/cart_ros2/src/hospital_mission/map/7839_clean.jpg (3793x1825, 원본 보존). 남은 것: 일부 방 미세 한글 잔상, 빨간 경로 화살표(요청 범위 밖이라 유지), 원근 왜곡 미보정.
- (2026-07-17) [7839_clean 추가 정리] 사용자 요청으로 (1) 빨간 경로 화살표 제거(HSV 빨강 마스크 인페인트), (2) 한글 잔상 추가 제거(높이 임계 35→38px), (3) 기울기 보정(minAreaRect 각도 -1.28° 레벨링). 7839_clean.jpg 갱신. 측정상 회전 ~0°·키스톤 미세(near-frontal)라 원근 보정은 소폭. 아래쪽 로비 사선은 실제 건물 형태(CAD와 동일). 남은 미세 잔상: 404·412에 아주 옅게.
- (2026-07-17) [내비 점유지도에 호실번호 삽입] 새 파일 20_navigation_occupancy_map.png(3793x1825, 흑백 라인, 번호 없음)에 7839의 호실 번호 삽입. cv2 투영분석으로 방 띠(상단 y453-667, 하단 y748-965)와 수직 벽 검출→방 중심 산출→순서대로 번호(상단 401~408·410~412, 하단 419~416·415~413) cv2.putText 스탬프. 7839와 상하 비교로 18개 전부 올바른 방 위치 확인. 결과: 20_navigation_occupancy_map_numbered.png (원본 보존).
- (2026-07-17) [flat_map 장소명 라벨] flat_map.png(1804x872, 남색 라인 "1F")의 각 방에 진료과명 삽입: 410 내과·411 외과·415 원무과·414 약국. 방 벽 검출로 위치 산출, Noto Sans CJK KR로 작은 크기(22~26px, 세로 안 잘리게) 렌더. 결과: flat_map_labeled.png (원본 보존).
- (2026-07-17) [앱 UI: 음성안내 흐름 구성] flat_map_labeled.png 기반으로 키오스크 흐름 구현(STT/LLM/로봇은 mock): (1) 음성 화면(마이크 버튼) → (2) 듣는 중(파형+데모 예시질문 칩) → (3) 결과(안내도+해당 방 반투명 빨강 하이라이트+위치 문구+"안내할까요?" 네/아니오) → (4) 이동 중(로봇 애니메이션→도착). 아니오→음성 화면 복귀. 파일: index.html/app.js 재작성, mockRecognizer.js(키워드→장소, DEMO_QUERIES), robotController.js(goTo Promise·speak=브라우저TTS), data/locations.js(장소 rect%·안내문구), style.css 재작성. 구 menuScreen/mapScreen 제거. 4개 화면 렌더 확인. ※ 실제 stt_package/llm_package는 mockRecognizer만 교체하면 연결됨.

## 사이클 2 (2026-07-18~)
- (2026-07-18) [조사] 실제 파이프라인 파악: STT(stt_package, whisper.cpp `stt` CLI → stt/outputs/*.txt), LLM(llm_package `llm` CLI: outputs 폴링 → map_labels.json 매칭 → Nav2 직접 전송, OpenAI fallback), map_labels.json(원무과·내과·외과·track만, 약국 없음), 파일버스(llm_package/bus/nav_request). 브라우저 앱은 아직 미연결.
- (2026-07-18) [A-1] 층 표기를 config로 분리: src/js/config.js(floor:'1F') 신설. 지도 이미지에서 "1F" 제거한 flat_map_guide.png 생성(원본 flat_map_labeled.png 보존, map dir + src/assets 동일 저장). 결과화면에 층 배지(HTML) 추가해 config.floor로 표시. 하이라이트 정렬 유지 확인.
- (2026-07-18) [A-2] 안내도에서 빨간 경로 화살표 제거: flat_map_labeled.png(원본 보존)에서 1F 화이트아웃(A1) + 빨강/분홍 픽셀을 흰색 치환 → flat_map_guide.png(남은 빨강 0px). 소화기 빨강 아이콘 1개도 함께 제거됨(앱 빨강 하이라이트와 혼동 방지). map dir + src/assets 동일 저장. 지도 지오메트리 불변이라 하이라이트 %좌표 그대로 유효.
- (2026-07-18) [B-3] 입력측 인터페이스(계약) 정의 + 목/실제 전환 스위치. recognizer/{index,mock,real}.js 신설. 계약: recognizer.listen()→Promise<{text, locationId, confidence}|null>(취소=null), recognizer.cancel(). CONFIG.useMock로 mock/real 선택. app.js를 계약만 쓰도록 리팩터(startListening 루프: listen→못찾으면 재질문 재시도, 취소는 null). 구 mockRecognizer.js 제거. real.js는 항목4~5 스텁. 검증: index.html 모듈 로드 OK(floor 배지='1F'), listen()→칩클릭→{locationId:'wonmu',confidence:0.95} 계약대로 동작.
- (2026-07-18) [B-4] (사용자 선택 A: 정적서버 통합) stt_package 연결. scripts/kiosk_server.py 신설(파이썬 stdlib): src/ 정적 서빙 + POST /listen. /listen은 stt 소스를 sys.path로 import해 1회 녹음(record_continuous_utterances VAD)+whisper-server 인식(run_whisper_server)+postprocess → 텍스트, 이름→id 매칭(ALIASES, 약국→pharmacy 포함) → {text,locationId,confidence}. 같은 출처라 CORS 불필요. 마이크 없이 파이프라인 검증용 텍스트 주입 훅(JSON body {"text":..} 또는 ?text=). serve.sh를 kiosk_server.py 실행으로 교체. recognizer/real.js가 fetch('/listen') 호출(취소=AbortController). 검증: 정적 200, /listen 주입 매칭(원무과→wonmu 등) OK, 실제경로는 마이크/whisper 없어 graceful error(젯슨에서 whisper-server 8080+마이크 필요), mock 모드 앱 로드 정상. ※서버측 매칭은 항목5에서 llm_package 기반으로 고도화 예정.
- (2026-07-18) [B-5] llm_package 연결(서버측 매칭 고도화). kiosk_server.py가 llm_package/llm/src를 import해 load_map_labels/build_label_index/match_location으로 map_labels.json 기반 매칭. 매칭된 zone name→앱 id는 NAME_TO_ID(원무과→wonmu·내과→internal·외과→surgery·약국→pharmacy). map_labels에 없는 약국은 EXTRA_ALIASES 폴백으로 pharmacy 매핑(좌표 없어도 견딤). map_labels.json mtime 변경 시 인덱스 자동 재로드(약국 추가 시 무재시작). llm import 실패 시 폴백 별칭만으로도 동작. 검증: 원무과/내과/외과/약국/접수 정상 id, 화장실=null.
- (2026-07-18) [B-6] 인식 실패/재질문 UX. #retry-screen + showRetry(message, choices)로 3케이스 처리: (A)장소 못 찾음→"어느 곳을 찾으시나요?"+장소 버튼(원무과/약국/내과/외과)+다시 말하기, (B)저신뢰(CONF_LOW≤conf<CONF_HIGH)→"'○○' 맞나요?" 네/아니오, (C)무음/인식 실패(text 없음)→"다시 듣기". app.js handleRecognition에서 conf(0.85/0.5) 임계로 분기. mock DEMO_QUERIES를 {label,text,confidence?} 객체로 바꿔 각 케이스 시연 예시 포함(내과 conf0.6=저신뢰, 빈 text=실패 등). 렌더 확인.
- (2026-07-18) [B-7] mock 모드 시연 검증: 데모 칩 5개가 recognizer 계약으로 각각 {원무과/약국=conf0.95 확정, 내과=conf0.6 저신뢰, "어 그 저기"=loc없음, 무음=실패} 반환 → app 분기(확정→안내 / B.확인 / A.장소버튼 / C.다시듣기)에 정확히 매핑됨을 헤드리스로 확인. 실제 stt/llm 없이 전 흐름 데모 가능.
- (2026-07-18) [C-8] 좌표 변환 유틸 src/js/utils/coordTransform.js. 앵커 3곳(원무과·내과·외과: 안내도 방중심 px ↔ map_labels nav_goal m)으로 3점 affine 정확 해(3x3 역행렬). guideToMap(px,py)/guideRectToMap(rect%). 앵커 재현오차 0m 확인.
- (2026-07-18) [C-9] 좌표 변환 검증(로봇 미이동, scripts/validate_coord.py). 3점 affine은 앵커를 정확 재현(0m)하나 이는 3점=6파라미터라 독립 검증 아님. leave-one-out 교차검증(2점 similarity로 held-out 예측) 오차: 내과 10.52m, 외과 10.96m, 원무과 13.13m (평균 ~11.5m). rect_center 앵커는 14~18m로 더 나쁨. ★원인: (1)안내도가 스타일화된 그림이라 실제 건물 비율과 달라 단순 affine/similarity로 안 맞음, (2)앵커 3곳뿐 + 내과·외과가 같은 안내도 y(252)라 조건수 나쁨, (3)nav_goal이 방 중심이 아니라 접근 포즈라 안내도 방중심과 의미 불일치. ★결론: 일반 픽셀→미터 변환은 현재 데이터로 신뢰 불가(10m+) → 알려진 방은 map_labels.json nav_goal 직접 조회 사용(정확). 정확한 임의지점 변환을 원하면 앵커를 안내도 전역에 4곳+ 분산 배치하거나 SLAM 맵 이미지 좌표를 직접 사용 필요.
- (2026-07-18) [C-10] robotController.goTo가 실제 목표 좌표 계산·출력. kiosk_server에 GET /goal?id= 추가(id→name 역매핑→map_labels.json nav_goal 반환, 없으면 error). goTo(location)이 /goal 조회 후 "★실제 목표 좌표(map): x,y,yaw"를 콘솔 출력(신뢰=nav_goal 직접). 약국처럼 좌표 없으면 견디고 coordTransform 안내도 추정을 "비신뢰(~11m)"로 경고 출력. 실제 ROS 발행은 TODO로 자리만(다음 사이클). 검증: 원무과 x=-23.19,y=51.337,yaw=-102.18 출력, 약국은 추정 경고. (편집 중 export const robotController={ 줄 누락 버그 있었으나 복구·앱 로드 정상 확인)

## 사이클 3 (2026-07-18~)
- (2026-07-18) [A-1] API 키 조사: myproject·cart_ros2 저장소 전체(작업트리·git 히스토리 pickaxe·blob·설정파일) 스캔 결과 키 없음(클린). llm/cli.py는 OPENAI_API_KEY를 env로 읽음(하드코딩X). 히스토리 재작성 불필요. 유일 노출=대화/로컬 트랜스크립트→키 로테이션이 실효조치(사용자가 대시보드에서 처리 완료). 예방: .gitignore에 .env/시크릿 패턴 추가.
- (2026-07-18) [최우선-중복워처 조사] nav_to_label_auto.py는 CMakeLists·launch·설치 어디에도 등록 안 된 레거시(고아) 스크립트. nav_request_watcher_direct.py도 동일(또 다른 고아 변종). 정식 워처는 nav_request_watcher.py뿐 — CMakeLists로 executable 설치 + navigation.launch.py(line 68~88)가 기동. 따라서 `ros2 launch hospital_mission navigation.launch.py`는 nav_request_watcher 하나만 띄움 → 기본 상태 이중 goal 위험 없음. 고아 2개는 수동 python3 실행 시에만 위험 → 수동 실행 금지 권장(오실행 방지 위해 legacy/ 이동은 사용자 지시 대기).
- (2026-07-18) [A-2] kiosk_server 환경변수화: WHISPER_SERVER_URL(기본 http://127.0.0.1:8080/inference), STT_AUDIO_DEVICE(기본 plughw:0,0)를 os.environ로 읽음. RecordConfig device=None→STT_DEVICE(실녹음 실패 원인 제거). 시작 로그에 설정 표시. 기본값·override 검증 완료.
- (2026-07-18) [A-3] 실행 방법 일원화. 환경 실측: stt .venv·시스템 python3 모두 stt.recorder import OK, rclpy는 둘 다 기본 미탑재(llm.cli import 실패). 녹음이 핵심이고 llm 매칭은 EXTRA_ALIASES 폴백이 동일 결과(4곳)를 내므로 → kiosk_server를 stt 패키지 .venv로 실행 확정(사용자 검증 녹음환경=stt CLI와 동일). serve.sh가 .venv python(/mnt/ssd/cart_ros2/src/stt_package/stt/.venv/bin/python3) 우선 사용, 없으면 시스템 python3 폴백. 검증: .venv 실행에서 정적200·/goal(map_labels 직접)·/listen 매칭(폴백) 정상. /goal·/nav는 rclpy 불필요(json 직접). 실행 방법을 serve.sh 주석 + PROGRESS에 기록.
- (2026-07-18) [B-4 확인] nav_request_watcher.py 파일이동 시점: move_to_done가 (라벨추출 실패 line135) 또는 (goal 수락="이동 시작" line202~203)에서 호출. 실제 도착(STATUS_SUCCEEDED line217)은 로그만·파일 안 옮김. failed 폴더 없음(Nav2서버없음176/goal거부198 시 파일은 nav_request/에 stuck). ⇒ done/=goal수락(이동시작)이지 도착 아님.
- (2026-07-18) [B-4] POST /nav 구현(kiosk_server). do_POST /nav: {id}→ID_TO_NAME 한글라벨→ nav_request/kiosk_{ts}_{id}.json 에 {"place_name":이름,"source":"kiosk"} 작성, {ok,file,name} 응답. 좌표 없는 곳(zone_has_goal=False, 약국)은 파일 안 쓰고 {blocked} 반환(failed로 안 감). GET /nav_status?file=: nav_request/=pending, done/=accepted(이동시작), failed/=failed. robotController.goTo: mock=애니메이션→{arrived:true}, 실제=_sendNav(/nav+상태폴링 ~15s)→{status:moving/failed/timeout/blocked}. app.js showResult가 /goal로 좌표 확인→없으면 "네" 버튼 disabled+"안내 준비 중"(약국). confirmYes가 상태별 메시지(도착/이동 중/응답없음/실패), 도착 알림은 다음 사이클로 보류. 기존 워처 미수정. 검증: /nav 파일작성·약국 blocked·status 전이(pending→accepted)·약국 결과화면 버튼 비활성 렌더 확인, 테스트 파일 정리(bus 잔여 0).
- (2026-07-18) [마이크 디버깅] stt CLI·앱 모두 녹음 실패 원인 = USB 마이크 카드번호 변경(plughw:0,0→실제 card1=plughw:1,0; card0 캡처장치 없음, card2 웹캠). ★핵심: stt_package/recorder.py _resolve_device가 os.environ["STT_AUDIO_DEVICE"] > --device > 기본 순으로 환경변수 최우선 → 사용자 절차의 export STT_AUDIO_DEVICE=plughw:0,0 이 --device를 무시. 해결: 그 export를 plughw:1,0로 바꾸거나 unset. 앱은 serve.sh에 USB 마이크 카드 자동감지 추가(arecord -l의 "Usb Audio Device" 카드 파싱, 웹캠 제외; STT_AUDIO_DEVICE 미지정 시 자동설정). 셸에 stale STT_AUDIO_DEVICE 있으면 존중되니 주의. (stt_package 미수정, 진단만)
- (2026-07-18) [앱 실제 STT 연동] 앱은 stt CLI와 "연동"이 아니라 kiosk_server /listen 으로 스스로 녹음함을 확인. config.js useMock true→false 로 전환(실제 STT 모드). 흐름: 브라우저 POST /listen → kiosk_server 녹음(STT_AUDIO_DEVICE=plughw:1,0) → whisper-server:8080 → 장소매칭 → {text,locationId,confidence} → 결과화면. 주의: stt CLI를 켜두면 마이크 충돌하므로 앱 사용 시 stt CLI는 Ctrl+C로 꺼야 함. 중복 kiosk_server 3개(2개는 기본0,0) 정리. real.js/index.js는 이미 배선돼 있어 스위치만 전환.
- (2026-07-18) [원클릭 런처] scripts/run_app.sh 추가 — 터미널 하나로 실제 STT 앱 전체 기동: (1)마이크 충돌 정리(stt CLI·중복 kiosk_server pkill, 브래킷트릭 self-kill 방지) (2)whisper-server(8080) 확인, 없으면 whisper.cpp 디렉토리에서 medium 모델로 백그라운드 기동+로드대기(최대40s, 로그 logs/whisper.log) (3)stale STT_AUDIO_DEVICE unset (4)serve.sh exec(마이크 자동감지 plughw:1,0). 검증: 4단계 정상, GET / 200, /goal?id=internal 실제 map 좌표 반환. logs/ .gitignore 추가.
- (2026-07-19) [앱 음성인식 실패 원인규명+해결] "앱 마이크 버튼 눌러도 인식 못함" 진단: (근본원인 2개) ①stt CLI는 기본이 버튼모드(스페이스로 녹음, RMS무관)라 잘 되지만 앱 /listen은 VAD모드(자동감지, 고정임계 500)를 씀 → 마이크 게인이 낮으면 발화가 500을 못넘겨 무한대기. ②card1 캡처게인이 0%(-12dB) → 발화 RMS 부족. 해결: (a)serve.sh가 감지한 카드에 캡처게인 40% 자동설정(MIC_CAPTURE_GAIN 조정가능, AGC off). (b)kiosk_server /listen이 매 녹음직전 주변음 1초 측정→임계값 자동보정(하위20%*2.2+120, 350~1500 클램프; VAD_THRESHOLD 환경변수로 고정 가능). 고정 500 폐기. 검증: 게인 0%→40%(+6dB) 상향확인, 주변음221→임계값606 산출, 매칭·whisper·마이크 각 단계 정상. arecord -d는 정수초만 받는 점 반영. stt_package는 미수정(파라미터만 조정).
- (2026-07-19) [발화 앞부분 잘림 버그 수정] 증상: 앱에서 "원무과는 어디에 있어" 말했는데 whisper가 "관은 어디에 있어"로 인식→매칭실패→선택화면(멈춘 게 아니었음). 원인: 직전 커밋의 VAD 자동보정이 매 /listen마다 주변음 1초를 측정(arecord)하는데, 사용자가 버튼 누르고 바로 말하면 그 1초에 발화 앞부분("원무")이 먹힘(wav 2.1초=앞 0.5~1초 손실 확인). 해결: _get_vad_threshold()로 임계값을 서버 시작 시 1회만 측정·캐시(게인 고정이라 안정적)→ /listen엔 측정 지연 0. 부가: /listen 응답 시 서버콘솔에 [kiosk] 인식='..' → 매칭=.. 로그 추가(디버깅 가시성). 검증: 시작로그에 VAD 1회 측정, "원무과는 어디에 있어"→wonmu 매칭.
- (2026-07-19) [인식품질 저하(어두 잘림) 개선] 증상: 앱 인식률 처참("원무과는 어디에 있어"→"관어 어디에 있어", "과어", "개꿔"). CLI(버튼모드)는 정상. 분석: 저장 wav 길이 1.7s(정상 ~2.8s)로 앞 ~1.1초 잘림 확인. 원인: VAD 임계값이 "원무" 같은 약한 어두를 늦게 잡고 pre_roll 0.3s로는 복구 불가. 해결: /listen의 record_continuous_utterances에 pre_roll_sec=2.0(트리거 전 2초 프리버퍼로 어두 복원), silence_sec=1.2, min_record_sec=0.6, max_record_sec=12.0 전달(임계값은 유지→오검출 위험 없음, 앞쪽 무음은 whisper가 무시). stt_package 미수정(호출 파라미터만). 사용자 실측 검증 필요.
- (2026-07-19) [오인식 해결: whisper 도메인 프롬프트 + 서버 생존] 사용자 질문 "whisper 서버 문제냐": 아님. 진단: (1)whisper-server는 GPU(CUDA0 Xavier)로 정상 동작 확인 — CUDA 환경변수는 정확도 아닌 속도 요소라 원인 아님. (2)진짜 원인=whisper가 병원 진료과명 같은 도메인 단어를 몰라 오인식(원무과→원목과, 내과→내권/내꽝). 저장 wav로 프롬프트 A/B 실험: 어휘 프롬프트("원무과 내과 외과 약국 접수 수납...") 주면 3개 전부 정확히 교정됨. 적용: kiosk_server가 whisper /inference를 직접 호출(stdlib urllib multipart)하며 WHISPER_PROMPT를 초기 프롬프트로 전달(run_whisper_server는 prompt 미지원이라 우회, stt_package 미수정). WHISPER_PROMPT 환경변수로 교체 가능. 검증: 3개 wav→원무과/내과/내과, 매칭 wonmu/internal/internal 성공. (3)부가 발견: run_app.sh가 whisper-server를 같은 프로세스그룹 백그라운드로 띄워 앱 Ctrl+C 시 whisper도 SIGINT로 죽음("Caught signal 2") → setsid로 새 세션 분리(앱 Ctrl+C에도 생존, 다음 실행 시 재사용=모델 재로드 없음)+CUDA 환경변수 명시.
- (2026-07-20) [현재 좌표 조회 도구] scripts/get_pose.py + get_pose.sh 추가 — 로봇의 현재 위치(map 기준)를 읽어 출력. TF(map→base_footprint/base_link) 조회 방식(정지 상태에선 /amcl_pose가 갱신 발행을 안 해 대기가 걸릴 수 있어 상시 브로드캐스트되는 TF를 사용). 출력에 map_labels nav_goal 형식과 INIT_X/Y/QZ/QW(초기위치 자동발행용)를 함께 제공. ROS2 galactic + 워크스페이스 setup을 source 후 시스템 python3로 실행(.venv엔 rclpy 없음). 실측: 현재 주차 좌표 x=-22.4487 y=47.5130 yaw=175.58° (qz=0.9993 qw=0.0386), base_footprint 기준. 스택 구성 확인: 위치추정=nav2_amcl, hospital_nav의 map_loader/amcl/navigation_node/rviz 노드 구성. 다음 목표: 브링업→내비→2D pose 자동지정→stt→앱 순차 기동 스크립트.
- (2026-07-20) [초기 위치 등록] map_labels.json에 "초기 위치" zone 추가(현재 주차 좌표). nav_goal={x:-22.4491, y:47.5130, yaw_deg:175.54, qz:0.9992, qw:0.0389, frame_id:map}. alias=[초기위치,시작 위치,대기 위치,홈,원위치,제자리,복귀]로 음성 복귀 명령도 매칭되게 함. 사전조사: 소비 코드(nav_request_watcher.zone_to_pose, voice_to_nav, llm/cli)는 nav_goal이 있으면 그것만 쓰고 x_min/x_max는 nav_goal 없을 때만 폴백으로 사용 → 사각형 필드(다른 좌표계라 임의값 위험)는 넣지 않음. qz/qw가 있으면 watcher가 그 방향 그대로 사용하므로 복귀 시 최초 2D pose 방향이 재현됨. 검증: 기존 zone 4개 무변경(백업 diff), llm 매칭('초기 위치로 돌아가'→초기 위치, '홈으로 복귀'→복귀, '원위치'→원위치), zone_to_pose 실행 결과 position(-22.4491,47.5130)/orientation(z0.9992,w0.0389) 정확. 백업: map_labels.json.bak.20260720_155903 (해당 파일은 cart_ros2에서 untracked라 사용자 관례대로 커밋 안 함).
- (2026-07-20) [전체 스택 기동 스크립트] 사용자 실제 절차 조사 반영: cm/cl/ci는 빌드가 아니라 sudo chmod 766 (ttyMD/ttyLidar_F/ttyLidar_R/ttyIMU) 장치권한 별칭, ROS 환경은 DOMAIN_ID=30·LOCALHOST_ONLY=0·rmw_cyclonedds_cpp이며 ~/.bashrc가 export하는 CYCLONEDDS_URI를 매 터미널 수동 unset하는 구조(=ros_env.sh로 재현). stt_node는 존재하지 않음 확인(설치 실행파일 없음) → 앱(run_app.sh)이 STT 담당, 마이크 충돌 없음.
  신규 파일: ros_env.sh(공통 ROS 환경), set_initial_pose.py/.sh(RViz 2D Pose Estimate 대체: map_labels "초기 위치" → /initialpose 발행, amcl 구독자 대기→3회 발행→map→base TF로 오차 검증), start_all.sh(6단계 순차: 장치권한/팬/마운트 → ROS환경 → 브링업 → 내비 → 초기위치 → 앱).
  안전장치: 이미 떠있는 브링업/내비는 건너뜀(중복 기동=이중 모터제어 위험 방지), Ctrl+C 시 이 스크립트가 띄운 것만 정리, 각 단계는 고정 sleep 대신 ros2 node list로 준비 확인.
  검증: set_initial_pose 실행 성공(발행 후 오차 0.066m/0.76° — amcl 스캔매칭 보정 정상범위). start_launch의 PGID 획득 방식 버그 발견·수정 — setsid가 fork하면 $!가 이미 죽은 래퍼 PID라 엉뚱한 그룹을 kill할 위험이 있어, 세션리더 bash가 자기 $$를 파일에 기록하고 exec로 런치를 덮어쓰는 방식으로 변경. 실측: PGID 정확, 자식 포함 트리 전체가 그룹 종료로 0개 잔존.
  결정(사용자): 복귀는 '도착 후 N초 대기 뒤 자동', 복귀 중 새 음성요청이 오면 '즉시 새 목적지로 전환'. → 다음 작업(미구현).
- (2026-07-20) [복귀 기능 구현] scripts/return_home_watcher.py(+.sh) 추가 — 기존 nav_request_watcher 무수정 원칙 유지하며 자동 복귀 구현. 방식: nav_request_done/에 새 파일(=goal 수락) 감지 → 해당 zone 좌표를 TF(map→base_footprint)로 추적 → ARRIVE_RADIUS(기본 0.8m) 진입 시 도착 판정 → RETURN_DELAY_SEC(기본 10s) 대기 → nav_request/에 {"place_name":"초기 위치","source":"return_home"} 원자적 기록(tmp→os.replace)하여 복귀. 목적지가 초기 위치면 재예약 안 함(무한 왕복 방지), 대기/복귀 중 사용자 새 요청(source!=return_home) 감지 시 즉시 취소하고 새 목적지 우선(사용자 결정 반영), TRACK_TIMEOUT_SEC(240s) 미도착 시 감시 종료. 버스 경로는 NAV_BUS_DIR로 덮어쓸 수 있게 해 실로봇에 goal을 보내지 않고 테스트 가능하게 함. 검증: 임시버스로 전체 상태머신 통과(목적지 감지→도착→대기→복귀요청 생성→복귀 추적→완료), 생성 파일 스키마 정상, 실제 버스에 유출 없음 확인. start_all.sh에 [6/7] 단계로 통합(중복 실행 방지, 종료 시 정리 대상 포함). 참고: 테스트 중 실제 버스 done/에 사용자의 앱 안내 요청(kiosk_*_wonmu/internal, 16:23~16:29)이 있어 로봇이 원무과 근처에 있었음 → 앱→실로봇 이동이 실제로 동작 중임을 확인.
- (2026-07-20) [복귀 방향 불일치 해결] 증상: 복귀 시 위치는 맞는데 바라보는 방향이 복원되지 않음. 원인은 좌표 등록이 아니라 Nav2 설정 — hospital_mission/config/agv.yaml의 general_goal_checker.yaw_goal_tolerance가 3.14159(=180°)로 되어 있어 도착 판정에서 방향을 사실상 검사하지 않았음(위치만 맞으면 도착 처리). 등록된 초기 위치의 qz/qw는 이미 정확했고 실제로 현재 자세와 0.077m/0.06°밖에 차이나지 않아, 좌표 재등록만으로는 절대 해결 불가한 건이었음. 조치: yaw_goal_tolerance 3.14159→0.15(약 8.6°)로 수정(DWB에 RotateToGoal critic이 이미 있어 최종 회전 가능). agv.yaml은 이 한 줄만 변경(diff로 확인), 백업 agv.yaml.bak.20260720_165930. 함께: 사용자 요청대로 현재 자세를 초기 위치로 재등록(x=-22.4157 y=47.4429 yaw=175.55°, qz=0.9992 qw=0.0388), 기존 zone 4개 무변경 확인, zone_to_pose로 목표 자세 정상 생성 확인. ※ 파라미터는 런치 시점에 읽으므로 내비게이션 재시작 필요. ※ 부작용(의도된): 원무과/내과/외과 도착 시에도 등록된 방향으로 회전해 정지하게 됨(도착이 약간 느려지지만 진료과를 바라보게 됨).
  · 참고: 직전 "라이다 안 돌아감/브링업 실패"는 스크립트 문제가 아니라 라이다 전원 미공급이었음(사용자 확인). 단독 라이다 런치도 동일 실패, 포트 점유 없음·권한 정상·udev 심볼릭링크 정상(시리얼번호로 확인)으로 소프트웨어 요인을 배제해 특정함.
- (2026-07-20) [도착 화면 + 5초 뒤 자동 복귀] 요구: 도착 시 "XX에 도착했습니다" 표시 → 5초 후 음성 버튼 화면 복귀와 동시에 로봇은 초기 위치(방향 포함)로 이동. 문제: kiosk_server는 stt .venv에서 돌아 rclpy가 없어 TF를 못 보므로 도착을 알 수 없음. 해결(3단 연결): (1) return_home_watcher가 상태 전이마다 bus/kiosk_status.json에 {state,place,updated_at} 원자적 기록(moving/arrived/returning/idle), (2) kiosk_server에 GET /robot_status 추가(파일 없으면 state=unknown 안전 폴백 → 감시노드 미실행 시 기존 동작 유지), (3) robotController.waitArrival()이 이를 폴링(0.7s)하고 app.js confirmYes가 도착 시 showArrival() → ARRIVE_HOLD_MS(5s) 후 resetToVoice. 이전 안내의 잔여 상태를 오인하지 않도록 요청 시각(sentAt)보다 오래된 updated_at은 무시. resetToVoice에서 타이머 해제(사용자가 먼저 조작한 경우 대비). watcher RETURN_DELAY_SEC 기본값 10→5로 맞춰 화면 복귀와 로봇 복귀가 동시에 일어나게 함. 검증: 헤드리스 크로미움으로 JS 오류 0·앱 초기화 정상, /robot_status 응답 정상, 상태머신 단위테스트(위치 주입)로 arrived→(정확히 지연시간)→복귀요청 생성+returning→idle 전이 및 파일 스키마 확인. ※ 테스트 중 ROS 스택이 내려가 있어 TF 기반 실주행 검증은 사용자 실측 필요.
- (2026-07-20) [초기 방향 완전 복원 — TF 피드백 정렬] 측정: yaw_goal_tolerance=0.15는 실행 중 노드에 실제 반영됨(ros2 param get으로 확인), 복귀 후 실측 오차 위치 0.043m/방향 1.37°. 사용자는 "주차 상태와 완벽히 동일"을 원하므로 Nav2 허용오차에 의존하지 않는 폐루프 정렬을 추가. 구현: return_home_watcher가 복귀 위치 도착 후 TF(map→base)로 현재 yaw를 보며 /cmd_vel에 angular.z만 발행(병진 성분 0)해 제자리 회전으로 목표 yaw에 수렴(비례제어, ALIGN_TOL_DEG 기본 0.5°). 안전장치: 각속도 상한 ALIGN_MAX_W=0.4rad/s, 타임아웃 20s, 정렬 중 새 사용자 요청 감지 시 즉시 중단, try/finally로 어떤 경로로 빠져나가도 stop_robot() 실행(정지 명령 3회 발행), 프로세스 종료(main finally)에서도 정지, ALIGN_ENABLE=0으로 비활성화 가능. 목표 yaw는 map_labels nav_goal의 qz/qw 우선 사용. 검증(실로봇 미발행: CMD_VEL_TOPIC=/test_cmd_vel + 위치 주입 + 회전 적분 시뮬레이터): 174.18°→175.55° 최종오차 0.24°, 랩어라운드 179°→-179°는 최단 2° 경로로 0.18°, 180° 회전 0.31°, 마지막 발행 명령 0.000(정지), 각속도 상한 준수. ※ 실로봇은 관성·모터 데드밴드가 있어 미세 헌팅 가능 — 그 경우 ALIGN_MIN_W(기본 0.12) 하향 조정.
- (2026-07-20) [회귀 수정: 목적지 goal 미완료] 증상: 원무과 도착 후 제자리 회전하다 멈추고 복귀 안 함(RViz: Distance remaining 0.20m, Recoveries 9, Feedback active = goal 미완료 상태 지속). 원인: 직전에 내가 yaw_goal_tolerance를 3.14159→0.15로 조인 것이 회귀를 유발 — 로봇이 원무과 등록 방향(-102.18°)을 맞추려 회전 반복하다 수렴 못 하고 recovery에 갇힘. Nav2가 이전 goal을 붙들고 있어 복귀 요청(return_20260720_205454.json)이 nav_request/에 처리되지 못한 채 잔류했고, 내 watcher는 240초 타임아웃으로 감시 종료. 조치: (1) agv.yaml yaw_goal_tolerance를 3.14159로 원복(주석 제외 시 최초 상태와 동일함을 diff로 확인) — 목적지에서는 방향을 강제하지 않고, 초기 위치의 정확한 방향은 return_home_watcher의 TF 폐루프 정렬(기본 0.5°)이 담당하는 역할 분리가 올바른 설계. (2) 잔류 요청 파일을 .stale로 이름 변경해 보류(삭제 아님) — 그대로 두면 내비 재시작 시 로봇이 예고 없이 출발하는 위험. (3) 재발 방지: watcher에 discard_pending_return() 추가 — 추적 타임아웃 시 자기가 낸 미처리 복귀 요청을 .stale로 무효화. 단위검증으로 타임아웃 후 nav_request/에 .stale만 남는 것 확인. 교훈: 도착 정밀도는 Nav2 허용오차를 조이는 방식(목표 미완료·recovery 위험)보다 도착 후 폐루프 보정이 안전하다.
- (2026-07-20) [정렬 미완성 대응 + 초기위치 재등록 도구] 증상: 복귀 후 방향이 ~30° 부족, 위치도 부정확. 조사: RViz는 Feedback=reached/Recoveries=0으로 goal 정상완료(원복 효과 확인). 단 21:12 트립의 정렬 로그가 21:19 watcher 재시작 때 덮어써져 증거 소실 — start_launch가 로그를 '>'로 truncate하던 결함을 '>>'(append)로 수정. 유력 원인=모터 데드밴드: ALIGN_MIN_W(0.12rad/s)가 실제 구동 하한보다 낮으면 명령만 나가고 로봇은 안 돌아 타임아웃까지 흘러 정렬 미완성. 대응: align_to_yaw에 무회전 감지 시 최소 각속도 단계 상향(1.5배+0.03, ALIGN_MAX_W까지) 로직과 2초 간격 진행 로그(현재각/남은각), 종료 시 '실제 회전량' 기록 추가 — 회전량이 0에 가까우면 데드밴드 문제임을 바로 식별 가능. 검증: 데드밴드 0.25rad/s 시뮬레이션에서 기존 설정이면 145°에 멈출 상황을, 자동 상향으로 175.33°(오차 0.22°)까지 수렴시킴(증상과 동일한 '30° 부족' 재현 후 해결). 신규: set_home.py/.sh — 로봇을 원하는 자세로 주차 후 1회 실행하면 현재 TF 자세(10회 측정, 각도는 벡터평균으로 랩어라운드 안전)를 map_labels "초기 위치"에 저장(자동 백업, 타 zone 무변경, watcher 재시작 불필요). ※ 미해결 가능성: TF상 오차(1.13°)와 사용자 체감(30°)의 괴리는 amcl 추정과 실제의 불일치일 수도 있음 — 다음 시도의 '실제 회전량' 로그로 판별 예정.
- (2026-07-20) [내가 만든 회귀 수정: 메서드 삭제] 증상: 원무과 도착 후 정지, 앱은 "이동 중" 고정, 복귀 없음. 원인: 직전 align_to_yaw 교체 시 문자열 슬라이스 범위를 잘못 잡아(align_to_yaw ~ '새 파일 감지' 주석 사이를 통째 치환) write_status/write_return_request/discard_pending_return 3개 메서드가 삭제됨. 로그에 AttributeError: 'ReturnHomeWatcher' object has no attribute 'write_status'로 노드가 죽어 있었음. ast.parse는 통과(문법상 유효)했고 내 검증이 align_to_yaw만 직접 호출해 tick() 전체 경로를 안 거쳐 놓침. 조치: 3개 메서드 복원 + AST로 'self.X 호출되지만 정의 없음'을 검사해 누락 0 확인 + tick() 전체 경로 통합테스트(목적지 감지→arrived→복귀요청→returning→도착→데드밴드 있는 방향정렬 0.46°→idle) 통과. 교훈: 함수 단위 테스트만으로는 '주변 코드 삭제'를 못 잡는다. 편집 후에는 (1) AST로 미정의 참조 검사 (2) 상위 진입점(tick) 통합 실행을 항상 할 것. 앱이 "이동 중"에 멈춘 것도 이 노드 사망이 원인(도착 상태가 갱신되지 않아 waitArrival이 타임아웃까지 폴링).
- (2026-07-20) [정렬 실패 근본원인: Nav2와 /cmd_vel 충돌] 실측 로그: 정렬 중 yaw가 -40.91→-27.33→-35.99→-40.08로 진동만 하고 20초간 순 회전량 1.12°, 최종 오차 -144.36°. 배제한 원인: (1) QoS — 내 발행자와 roboteq 구독자 모두 RELIABLE/VOLATILE로 동일해 명령은 정상 도달, (2) 데드밴드 — err가 커서 계속 ALIGN_MAX_W(0.4rad/s)를 발행했으므로 하한 문제 아님, (3) 상시 0 발행 — 정지 상태에서 /cmd_vel에 6초간 메시지 없음 확인. 진짜 원인: 도착 판정이 "ARRIVE_RADIUS(0.8m) 진입 순간"이라 Nav2가 아직 주행 중인데 정렬이 끼어들어 controller_server와 내 노드가 /cmd_vel을 두고 경쟁 → 로봇이 떨기만 함(로그의 '위치 오차 0.80m'=반경 경계값이 단서였음). 조치: wait_until_stopped() 추가 — 위치 변화<0.02m, 각도 변화<1.0°가 STOP_STABLE_SEC(1.5s) 지속될 때까지 대기 후에만 정렬 시작(최대 40s, 초과 시 경고 후 진행). 고정 sleep 방식을 정지 감지로 대체. ALIGN_TIMEOUT 20→30s(큰 각도 회전 대비). 검증: Nav2 주행 중에는 명령이 무효화되는 상황을 그대로 모사한 통합테스트에서, 정지 확인 후 142.99° 회전해 오차 0.26° 달성(기존 실패 시나리오와 동일 조건). 참고: 목적지에서 방향을 강제하지 않도록 원복했으므로 Nav2는 임의 방향으로 주차하며, 초기 방향 복원은 전적으로 이 정렬이 담당한다(그래서 144° 같은 큰 회전이 정상).
- (2026-07-20) [정렬 미완주: 구동 스케일 대응] 정지 대기 도입 후 로봇이 실제로 회전하기 시작(실제 회전량 1.12°→43.37°)했으나 여전히 미완료. 로그의 각도 변화율 분석: 2초마다 ~5.5°씩 꾸준히 회전 = 약 2.75°/s(0.048rad/s)인데 명령은 0.4rad/s → 실제 회전이 명령의 약 12%에 불과(구동계 스케일 차이). 이 속도로 137°는 50초 필요한데 타임아웃 30초라 중간에 끊김. 조치: (1) ALIGN_MAX_W 0.4→0.8(Nav2 max_vel_theta=1.0보다 낮은 선), (2) ALIGN_TIMEOUT 30→90s, (3) 램프 조건을 "안 움직임(0.3°/샘플)"에서 "실측 회전율이 ALIGN_MIN_RATE(기본 8°/s) 미만이면 상향"으로 개선 — 데드밴드뿐 아니라 '명령 대비 실제가 느린' 경우까지 자동 대응하며, 실제 로봇의 스케일이 달라도 적응함. 검증: 12% 스케일을 그대로 모사한 테스트에서 0.242→0.437→0.750→0.800rad/s로 자동 상향 후 136.65° 회전, 오차 0.29°, 24.9초 소요(타임아웃 90s 대비 여유), ±180° 경계 통과 정상.
- (2026-07-20) [사이클 3 종료] 사용자 확인 "만족스러운 결과". HANDOFF.md를 사이클3 완료 기준으로 전면 개정 — 달성 내용, 실행 방법(start_all.sh 7단계 + 개별 도구 + 초기위치 재등록 절차), 구조 다이어그램(앱/kiosk_server/파일버스/return_home_watcher 역할 분리), 해결한 문제 목록, "값비싸게 배운 것" 7가지(Nav2 허용오차 조이기 금지, /cmd_vel 경쟁, 구동 스케일 12%, setsid, 라이다 전원, 환경변수 우선순위, 편집 후 통합검증), 남은 것(위치 정밀도·amcl 괴리 재확인·약국 좌표), 튜닝 환경변수 표를 수록. 메모리도 동일 내용으로 갱신.

## 사이클 4 (2026-07-20~)
- (2026-07-20) [A-1 대응점 조사 — ★nav_goal 부적합 판정, B 진행 보류] 사용자 지시대로 nav_goal을 대응점으로 쓰기 전 검증. 결론: **nav_goal은 방 위치가 아니라 "방 앞 복도" 좌표이며 rect 중심과 어긋나 대응점으로 쓸 수 없다.**
  근거 (실측):
  · 3개 nav_goal의 분포 — x 폭 1.83m vs y 폭 10.62m, 주축비 8.2:1(사실상 복도선 위 일렬), 최적직선에서의 수직 편차 0.31~0.76m(복도 폭 수준).
  · nav_goal 주변 3x3m 점유율 = 자유공간 95~97%(원무과 95.4/내과 95.8/외과 96.6) → 방 내부가 아니라 열린 복도.
  · 반면 안내도에서는 내과·외과가 위쪽 줄, 원무과가 아래쪽 줄(복도 반대편)이라 주축비 1.3:1의 뚜렷한 삼각형. 즉 "복도 수직방향 위치" 정보가 안내도에만 있고 nav_goal에는 없다 → 어떤 affine으로도 동시 만족 불가.
  · 쌍별 축척 불일치 2.81배(0.02584 / 0.03476 / 0.07257 m/px). 내과 꼭짓점 끼인각 안내도 68.3° vs 실제맵 14.5°.
  · similarity(4DOF) 적합 잔차: 내과 4.098m, 원무과 3.291m, 외과 3.944m → **RMS 3.794m / 최대 4.098m** (PLAN의 1m 기준 크게 초과). 축척 0.02345 m/px, 회전 90.2°.
  · 3점으로 affine(6DOF)을 강행하면 잔차는 1.7e-12m로 '0'이지만 이는 미지수=방정식이라 자동으로 0인 것이고, 그때 파라미터는 이방성 10.05배·두 축 사이각 105.5°(심한 전단)로 물리적으로 불가능한 변환.
  추가 확인:
  · **4번째 대응점 확보 불가** — 약국은 rect%는 있으나 nav_goal 없음, track은 nav_goal은 있으나 안내도에 없음, 홈 pose는 map 좌표만 알고 안내도상 위치를 모름. 따라서 현재 유효 대응쌍은 3개뿐이고, 3점+6DOF로는 항목3의 잔차 검증이 원리적으로 불가능(항상 0).
  · **안내도 자체가 축척도가 아님** — 건물 실측 22.3m x 95.5m(가로세로 1:4.28)인데 안내도 이미지는 1804x872(2.07:1). 안내판 사진을 재구성한 모식도라 국소 왜곡 가능성도 있음.
  · map_labels의 zone rect는 track만 nav_goal과 정확히 일치하고 원무과/내과/외과는 33m 이상 어긋남 → 그 rect들은 다른/구버전 좌표계로 판단, 대응점으로 사용 불가.
  조치: PLAN 지시("대응점으로 쓰기 전 확인하고 어긋나면 보고")에 따라 항목 2(affine 적합) 착수하지 않고 사용자 판단 대기. B·C 미착수.
- (2026-07-20) [A 판정 → 방식 전환 · B-4/5/6 구현] 사용자 제안 채택: 좌표 변환을 포기하고 "안내도 위 모식 경로를 실제 진행률만큼 이동하는 로봇 머리"로 표현. 결정(사용자): 진행 근거=실제 진행률, 화면=결과 화면과 동일한 안내도.
  근거 보강: 2차원 변환은 불가하지만 **복도를 따라가는 1차원 대응은 성립** — 안내도 x% = 0.7734*(map y) + 30.397, 원무과로 검증 시 예측 70.10% vs 실제 70.485%(오차 0.38%p ≈ 7px). 초기 위치는 복도상 x=67.09%.
  구현: (1) return_home_watcher가 이동 중 0.5초 주기로 pose·goal·remaining_m·progress를 kiosk_status.json에 기록. 진행률=1-남은거리/처음거리이며 **단조 증가**로 고정(직선거리는 우회 주행 시 일시적으로 늘어나므로) — 실측 테스트에서 로봇이 뒤로 갔을 때 22.7% 유지 확인. (2) kiosk_server /robot_status가 그대로 노출. (3) src/js/data/guideRoute.js 신규 — 복도 중심선(y=38.4%)과 출발점(x=67.09%)을 상수로 두고 [출발→복도 직진→방 진입] 3점 폴리라인 생성, 진행률 t에 대한 좌표·방향 계산(이미지 종횡비 보정). (4) 이동 화면을 지도 화면으로 교체: 결과 화면과 같은 안내도 + 목적지 하이라이트 + 로봇 머리(CSS transition 0.6s로 부드럽게) + 남은 직선거리 표시. robotController.waitArrival에 onUpdate 콜백 추가(2Hz 폴링을 그대로 재사용).
  검증: 실제 브라우저 모듈로 경로 계산 테스트 — 3개 목적지 모두 도착점이 방 중심과 일치, 경로 단조 진행, JS 오류 0건. 헤드리스 스크린샷으로 진행률 60% 지점 렌더 확인(로봇이 복도에서 원무과로 진입하는 위치, 하이라이트·남은거리·층 표기 정상). 백엔드는 tick() 통합 경로로 진행률 갱신·단조성 확인.
  미구현: 항목 7(아이콘에 yaw 반영) — 로봇 머리 이모지라 회전이 어색할 수 있어 사용자 확인 후 결정. C 섹션(실주행 검증·복귀 중 표시·재보정 문서화) 미착수.
- (2026-07-20) [이동 화면 3건 수정] 사용자 피드백 반영. (1) 맵 잘림: #move-map-img가 #map-img 크기규칙에 안 걸려 원본 1804px로 렌더→잘림. CSS 셀렉터를 '#map-img, #move-map-img'로 공통화해 전체 맵 표시. (2) 복도만 이동: routeTo가 방 중심까지 3점(방 진입)이던 것을 복도 위 2점(출발→방 앞, 둘 다 y=CORRIDOR_Y)으로 축소. AGV는 복도만 다니므로 로봇 머리도 방 안으로 안 들어감(방은 하이라이트로만 표시). (3) 경로 점 표시: routeDots()로 경로를 1.8% 간격 점들로 분할, .route-dot로 렌더(지난 점=초록 passed, 남은 점=옅은 파랑). placeRobot이 진행률로 로봇을 옮기며 지나온 점을 passed 처리. 추가 발견/수정: 홈(복도x=67.09%)이 내과(66.85%) 바로 위라 홈 출발 시 내과 이동거리 4px(거의0). 홈의 1차원 복도위치가 내과와 겹치는 문제 → 애니메이션 출발점을 START_X=56%(중앙 로비, 모든 방 왼쪽)로 고정해 세 방향 모두 일관된 이동 표시. 해당 복도선(y=38.4%, x56~75%)이 벽 0%로 뚫려있음을 픽셀로 확인. 진행률(실제 남은거리)은 그대로 실제값. 검증: 브라우저 모듈로 경로 전부 복도위(y=38.4 고정)·JS오류0, 헤드리스 스크린샷으로 전체맵+복도상 로봇+점트랙(초록/회색) 확인.
- (2026-07-21) [이동 출발점 위치 수정] 사용자 지적: 이동 화면의 로봇 출발점이 원무과 왼쪽이 아니라 화장실 부근에 잡힘. 원인: START_X=56%가 화장실(≈50%) 옆 엘리베이터/계단 구역. 참고그리드 렌더로 확인 — 원무과 왼쪽 끝=65.47%, 그 바로 앞 복도=63%. START_X 56%→63%로 이동(복도선 y=38.4% 위, 벽 0% 기확인). 이동거리: 내과 69px·원무과 135px·외과 218px로 세 방향 모두 여전히 가시적. 헤드리스 스크린샷으로 출발점이 원무과 왼쪽 복도에 위치함 확인. map_labels 초기 위치도 사용자 요청대로 뒤로0.2+오른쪽0.2m·yaw 170.55°로 조정 완료(별도 백업).
- (2026-07-21) [초기위치 이동 실패 원인규명 + 되돌림] 증상: 초기위치를 오른쪽1.0m·뒤0.5m 이동 후 복귀 시 로봇이 회전을 아예 안 함. 규명: 로그상 마지막 복귀가 "초기 위치 도착 대기"까지만 있고 "도착"/"정렬 시작"이 없음 → 로봇이 목표에서 1.71m 떨어진 곳(도착반경0.8m 밖)에 멈춰 정렬 단계 미도달(회전 로직 자체는 정상, 이전 위치에선 172° 회전 성공 기록). 점유지도 분석: 새 초기위치(-21.499,48.690)가 복도 벽 너머 회색(미탐색) 구역에 위치 → Nav2가 경로를 못 짜 벽 앞에 정지. 이전홈 기준 방향별 벽까지 여유 측정: 오른쪽(로봇+y) 0.25m뿐, 뒤 1.0m, 왼쪽 1.1m, 앞 2.0m. 즉 오른쪽 여유 0.25m인데 1.0m 이동해 0.75m가 벽/미탐색으로 나감. 조치: 사용자 결정대로 동작하던 이전 위치(-22.157,47.786, yaw170.55°)로 되돌림(백업에서 초기위치만 복원, 타 zone 무변경). 교훈: 초기위치·목표 좌표를 옮길 때는 my_map.pgm 자유공간(픽셀>200) 안에 있는지 먼저 확인해야 함. 도착반경(0.8m) 밖이면 정렬은 영영 시작 안 됨.
- (2026-07-21) [로봇 머리 마커 축소] 사용자: 이동 화면 로봇 머리가 복도보다 커서 불편. 측정: 로봇 통행 복도(x67~70%) 실제폭 40px(화면상 ~30px)인데 마커 상한 52px라 복도보다 큼. 수정: .robot-marker font-size clamp(26px,3.4vw,52px)→clamp(12px,2.1vh,24px). 지도가 높이(60vh) 기준 축소되므로 vw→vh로 바꿔 지도와 함께 스케일. drop-shadow도 축소. 좁은 도착지점(원무과) 스크린샷으로 복도 안에 들어가는 것 확인.
- (2026-07-21) [초기위치 만족값 복원 + 사이클5 목표 기록] 사용자 요청대로 초기 위치를 처음 "만족스러운 결과"(2026-07-20) 시점 값으로 되돌림: x=-22.4157, y=47.4429, yaw=175.55°(qz0.9992,qw0.0388). 백업 20260721_183246에서 초기위치만 복원, 현재값은 20260721_212246에 백업, 타 zone 무변경, watcher 반영 확인. HANDOFF.md를 사이클4 진행 기준으로 전면 갱신하고 다음 목표(사이클5) 명시: AGV 전원 ON 시 자동 실행 → 브링업/내비 등 백엔드는 화면에 안 보이게(백그라운드) → 부팅 직후부터 음성인식 화면만 표시. 구현 고려사항 기록(자동실행 수단 systemd/autostart, start_all.sh가 sudo 비번 물어봄→NOPASSWD 필요, chromium --kiosk 자동실행, 초기위치 자동지정과 전원기동 조화, 준비 전 음성버튼 처리). 메모리도 갱신.

## 사이클 5 (2026-07-21~) — 전원 ON 자동 실행
- (2026-07-21) [자동 실행 골격] 목표: 전원 켜면 비번 없이 음성인식 홈 전체화면, 브링업/내비 등 백엔드는 화면에 안 보이게. 조사: systemd+GNOME/X11(DISPLAY=:1, user wjs), gdm 자동로그인 꺼짐, /mnt/ssd는 이미 fstab에 nofail 자동마운트(→마운트 sudo 불필요), chromium=/usr/bin/chromium-browser, 장치심볼릭 ttyMD→ACM0/ttyLidar_F→USB2/R→USB0/IMU→USB1(전용 udev규칙 파일 없음). 설계: 런타임(매부팅)엔 sudo 안 쓰도록 시스템설정을 1회만 → NOPASSWD 영구권한 불필요(더 안전).
  신규: scripts/kiosk_boot.sh — autostart가 호출. 모든 출력 logs/kiosk_boot.log로(화면 숨김), DISPLAY·/mnt/ssd 대기 → ros_env.sh source(.desktop은 .bashrc 안 읽으므로 필수) → 앱+whisper(run_app.sh) 먼저 백그라운드(음성화면 최속 표시) → ROS백엔드(브링업→내비→set_initial_pose→복귀감시) 백그라운드 → 포트8000 대기 → chromium --kiosk 전체화면(독립 user-data-dir로 기존 브라우저와 충돌 방지, 서버측STT라 브라우저 마이크권한 불필요). setsid 기반 launch_bg로 세션 분리. 탈출구 Ctrl+Alt+F3.
  신규: ~/.config/autostart/agv-kiosk.desktop — 로그인 시 kiosk_boot.sh 자동 실행(Terminal=false, NoDisplay=true).
  신규: scripts/kiosk_setup_system.sh — 사용자가 sudo로 1회 실행. ①gdm 자동로그인(custom.conf 백업 후 [daemon]에 AutomaticLoginEnable/AutomaticLogin=wjs 삽입, python으로 안전 편집) ②udev 99-agv-serial.rules(ttyUSB*/ttyACM* MODE=0666 → cm/cl/ci 대체) ③agv-fan.service(jetson_clocks --fan oneshot). 되돌리기 방법 주석에 명시. 검증: 전 스크립트 문법OK, launch_bg 인자전달 정상, gdm 편집로직을 사본으로 dry-run해 [daemon] 아래 정확 삽입 확인, 참조파일 존재 확인. ※실제 재부팅 검증은 사용자 몫(chromium 키오스크가 화면 점유하므로 라이브 테스트 안 함).
- (2026-07-21) [자동실행 버그 수정: 초기위치 미지정] 사용자 테스트에서 브링업·내비는 뜨는데 2D pose(초기위치·방향)가 안 됨. 진단: kiosk_boot.log에 [initpose] 출력 전무, 복귀감시 미실행, amcl 추정(-23.06,50.52)이 등록 초기위치(-22.42,47.44)와 ~2.9m 어긋남 → set_initial_pose가 실행 안 된 것. 원인: kiosk_boot.sh가 ROS �- (2026-07-22) [자동실행 재부팅 실패 원인규명·수정] 증상: 전원 껐다 켜니 앱 아예 안 뜸. 규명: (1) gnome-session 로그 "Could not parse desktop file agv-kiosk.desktop or references not found TryExec binary" — autostart가 Exec=/mnt/ssd/... 를 실행하려는데 파일이 없음. (2) 근본원인: /mnt/ssd가 부팅 자동마운트에 실패 — journalctl "Dependency failed for /mnt/ssd", fstab의 x-systemd.device-timeout=5 라 NVMe가 5초 안에 안 떠서 mount 실패, nofail이라 부팅은 진행. 사용자가 매번 수동 sudo mount 하던 것(원래 AGV 절차에도 있던 명령). 프로젝트가 /mnt/ssd에 있으니 마운트 실패=자동실행 원천 불가. 수정: ① 홈(eMMC, 항상 존재)에 런처 ~/.local/bin/agv-kiosk-launch.sh 생성 — /mnt/ssd 마운트+스크립트 준비를 최대 300초 대기 후 kiosk_boot 실행. autostart .desktop의 Exec를 이 홈 런처로 변경(GNOME이 parse 시점에 항상 찾을 수 있게). ② kiosk_setup_system.sh에 fstab device-timeout 5→60초 수정 단계 추가(NVMe 지연 대응, 백업 후 python 편집, daemon-reload). 저장소에 scripts/autostart/ 백업본 보관. 검증: 런처·setup 문법OK, fstab 편집 사본 dry-run으로 5→60 확인, gdm 편집 재확인. ※이전 수정(백엔드 서브셸이 세션과 함께 죽어 set_initial_pose 미실행)도 kiosk_backend.sh 분리+setsid로 해결한 상태.
- (2026-07-22) [자동실행 사용자 지정 순서로 재구성 + git 복구] 전원 강제종료로 git 저장소 손상(6개 loose 객체 empty, HEAD 포함) → 마지막 정상 커밋 6ec4a58로 main 복원, 69커밋 히스토리 무손실 확인, 손상 orphan 객체 제거(작업트리는 처음부터 무손실). 원격 백업은 토큰 폐기로 보류.
  자동실행 재설계(사용자 지정 순서 ①팬 ②SSD마운트 ③cm/cl/ci ④브링업 ⑤내비+초기위치 ⑥음성앱 화면 '마지막'): (1) 홈 런처 ~/.local/bin/agv-kiosk-launch.sh 재작성 — sudo -n으로 ①jetson_clocks --fan ②mount(장치대기 후, 이미 마운트면 skip) ③chmod 766 4개 장치, 그다음 exec kiosk_boot. /mnt/ssd 마운트 전에도 실행되도록 홈(eMMC)에 위치. (2) kiosk_boot.sh 재작성 — 앱서버는 병렬 백그라운드로 미리 올리되, kiosk_backend를 '완료까지 대기'(foreground)한 뒤 마지막에 크로미움 전체화면 → 사용자가 원한 '앱 화면 마지막' 순서. 백엔드가 크로미움보다 먼저 끝나므로 setsid 분리 불필요. (3) kiosk_setup_system.sh 재작성 — udev/팬서비스/fstab 방식 폐기하고, 자동로그인 + NOPASSWD sudoers(딱 3종 명령: jetson_clocks --fan/mount /mnt/ssd/chmod 766 장치)만. visudo -cf로 문법검증 후 install. (4) 크로미움 GPU 초기화 에러(ANGLE pbuffer, Jetson 흔함) 대응 --disable-gpu 추가(단순 페이지라 SW렌더 무방).
  중요 버그 수정: kiosk_backend/kiosk_boot의 wait_node에서 'local ... t=${3:-90} end=$((SECONDS+t))' 한 줄 선언이 set -u에서 t unbound로 크래시(백엔드가 브링업 직후 죽어 초기위치 미실행이던 근본원인) → local 분리로 수정. 수정 후 초기위치 지정 성공 검증(발행→confirm 오차 0.022m/0.20°, 175.55° 사용). 초기 위치·방향은 사용자 요청대로 만족값(175.55°) 유지(재등록 안 함). ※amcl이 정지상태에서 126°로 수렴하는 괴리는 별개 이슈로 남김.

## 사이클 6 (2026-08-07~) — TTS 음성 안내
- (2026-08-07) [TTS 연동] tts_package(MeloTTS 한국어, /mnt/ssd/src/MeloTTS develop설치, kykim/bert-kor-base BERT) 확인. 다국어 지원(EN/ES/FR/ZH/JP/KR). 검증: 합성 동작(GPU Xavier), 스피커 재생(aplay card0 USB=plughw:0,0). BERT 476M 최초 다운로드가 네트워크 타임아웃으로 실패→HF_HUB_DOWNLOAD_TIMEOUT=60으로 재시도해 완료(SSD 캐시). 속도 실측: 모델로드 7.7s(1회)+워밍업 첫합성 14.6s, 이후 문장당 ~1s(오디오~2.7s). → 상주서버 방식 채택.
  신규 scripts/tts_server.py: MeloTTS 상주 HTTP서버(tts venv로 실행). 시작 시 로드+워밍업, POST /tts(합성→로봇스피커 aplay 재생), /synth(WAV만), GET / 헬스. 합성/재생 락 직렬화. 환경변수 TTS_PORT(5002)/TTS_SPEAKER_DEVICE(plughw:0,0)/TTS_SPEED.
  kiosk_server: /speak 엔드포인트 추가 — 텍스트를 tts_server로 보내 재생, _stt_lock 공유로 STT 녹음과 배타 실행(로봇이 말하는 중 자기 목소리 인식 방지). tts_server 꺼져있으면 실패 반환→앱이 브라우저TTS 폴백.
  robotController.speak(): 1순위 서버 MeloTTS(POST /speak, 재생완료까지 await 가능), 실패 시 브라우저 내장TTS 폴백. app.js startListening에서 speak를 await 후 listen(순서 보장). run_app.sh에 TTS서버 자동기동 추가(setsid, 준비 안 기다림).
  검증: /speak end-to-end 동작(합성1.06s→스피커 재생→ok), 헤드리스 JS 오류 0. 다음: 미리합성 캐시(고정문구 즉시재생) 및 자유대화(생성LLM) 연동은 후속.
- (2026-08-07) [TTS 무음 수정: 스피커 카드 자동감지] 증상: start_all.sh로 기동 시 안내 이동은 되나 TTS 스피커 음성 안 남. 원인: 재부팅 후 USB 스피커(UACDemoV1.0)가 card0→card1로 재번호됐는데 tts_server가 plughw:0,0 하드코딩 + aplay 실패를 무시(stderr DEVNULL)해서 /speak가 무음인데도 ok 반환. 마이크 카드 재번호와 같은 종류의 함정. 수정: tts_server에 _detect_speaker() 추가 — aplay -l에서 USB 오디오 출력 카드 자동 감지(HDMI 제외), TTS_SPEAKER_DEVICE로 강제 가능. play()가 aplay 반환코드 확인해 실패 시 로그(무음 원인 추적). 검증: 재기동 시 plughw:1,0 자동감지, /speak 재생 시 aplay 에러 0. 참고: 서버 새 JS는 정상 서빙됐고(브라우저 캐시로 오인 가능) 실제 원인은 스피커 장치였음. 교훈: aplay/arecord는 stderr 죽이면 무음/무녹음이 조용히 성공처럼 보인다.
- (2026-08-11) [초기위치 넓은 곳으로 이전 — 기둥 스침 근본 해결] 기존 초기위치(-22.42,47.44)는 기둥 사이 nook이라 전방향 최소여유 0.65~0.70m뿐 → 로봇(URDF 0.9×0.7m, 제자리회전 필요반경 0.57m)이 복귀 후 방향정렬 회전 시 모서리가 기둥에 스침(여유 8~13cm). 원인: Nav2가 로봇을 robot_radius 0.4m 원으로 과소모델링 + xy_goal_tolerance 0.45로 중심이탈 허용 + 회전 스윕 0.57m. 임시방편(A:여유0.70m지점 이동 +0.40x/-0.10y, B:xy_tol 0.45→0.15) 적용했으나 nook 최대여유 0.70m라 최악여유 여전히 ~0.55m로 부족 판정. → 사용자가 RViz 2D Pose Estimate로 넓은 자리로 이동·방향 지정(뒤가 벽). 검증: 새 위치 map(-19.726,36.737) 전방향 최소여유 1.20m(뒤 벽 1.25m, 앞·좌·우 2.5m+) → 회전여유 0.63m 충분. A+B 원복(agv.yaml xy_goal_tolerance 0.45 복구, 임시 롤백스크립트 제거) 후 set_home.sh로 현재 자세 등록: x=-19.7260 y=36.7368 yaw=83.96°(+y 바라봄, 뒤=벽). watcher 반영 확인. 교훈: 로봇 실제 footprint(0.9×0.7)와 Nav2 모델(0.4원)의 괴리 + 회전 스윕 반경(0.57m)을 초기위치 선정 시 고려해야. 좁은 nook은 어떤 설정으로도 회전 불안정.
- (2026-08-12) [라이다 기반 벽 정렬 — amcl 방향오차 우회] 증상: 넓은 자리로 옮겼는데 복귀 후 방향이 벽과 살짝 틀어짐(왼쪽). 진단: amcl이 이 자리에서 방향을 ~20° 부정확하게 추정(정지상태 104° 안정, 등록 84°와 20°차, 위치도 0.53m 어긋남). 등록 yaw(83.96°)는 벽과 거의 수직(계산 83.3°)으로 정확했고 정렬 메커니즘도 정상 — 순수 amcl 위치추정 오차. 라이다 실측은 정확·안정(벽 수직오차 1.29° 5회 동일). 해결: return_home_watcher에 라이다 기반 벽 정렬 추가. /scan_multi(프레임이 base_footprint와 정렬: yaw0·중심)의 뒤쪽 ±35° 섹터에서 벽 점(210개) SVD 선적합→벽선 각도→로봇 x축 수직에서의 편차 e 계산. align_to_wall(): e를 0으로 닫는 제자리회전 폐루프(angular.z=sign(e)*w, 데드밴드시 각속도 상향, 타임아웃/새요청취소/정지보장). 도착 정렬을 2단계로: ①align_to_yaw(amcl, 뒤가 벽 향하게 대략) ②align_to_wall(라이다, 벽과 정밀 수직). WALL_ALIGN_ENABLE=0으로 끌 수 있음. 검증: 문법·AST참조OK, 측정만 테스트 후 실제 회전 1회 시험 — 시작 +2.23°→최종 -0.24°(허용0.6°) 수렴, 부호·데드밴드 대응 정상. 교훈: amcl 방향추정이 불안정한 자리에선 라이다로 벽을 직접 봐 정렬하면 amcl 오차와 무관하게 물리적으로 정확. /scan은 BEST_EFFORT QoS라 rclpy는 qos_profile_sensor_data 필요(CLI echo 기본 RELIABLE은 무수신).
- (2026-08-12) [주행 속도 튜닝] 사용자 요청: 기본 주행 2배, 좁은 곳/회전은 현재처럼 느리게. agv.yaml DWB(FollowPath) 수정: max_vel_x 0.8→1.6, max_speed_xy 0.8→1.6(기본 주행 2배), max_vel_theta 1.0 유지(회전 각속도 그대로=회전 느림 유지), BaseObstacle.scale 0.1→0.4(장애물 근처 감속 강화→좁은 공간에서 느려짐). 좁은곳/회전 감속은 DWB가 자동 처리(고속 궤적이 장애물/경로이탈로 무효·감점→느린 궤적 선택; PathAlign.scale 16이라 회전 시 경로추종 위해 감속). 백업 config/agv.yaml.bak.*. ※nav 재시작 필요(런치 시 읽음). ※1.6m/s는 병원 실내엔 빠른 편 — 실주행 확인 후 조정 권장. BaseObstacle.scale는 너무 소심/진동하면 낮추고 좁은곳 감속 부족하면 높임.
- (2026-08-12) [원무과→산부인과 이름 변경] 사용자 요청. 기능 영향 전부 변경(id는 'wonmu' 유지=내부 안깨지게): map_labels.json zone name, locations.js name+약국desc, kiosk_server.py WHISPER_PROMPT/NAME_TO_ID/EXTRA_ALIASES(접수·수납 별칭은 산부인과와 무관해 제거), mock.js 데모라벨/키워드. 안내도 이미지(flat_map_guide.png)에 '원무과' 글자가 구워져 있어 PIL로 교체: 원무과 방 박스(내부 x1181~1363,y360~474) 지우고 '산부인과'(Noto Sans CJK KR Medium 44px, 색#00006b, 이웃 약국과 무게 맞춤) 렌더. 검증: match_location('산부인과')→wonmu, ID_TO_NAME[wonmu]='산부인과'. 백업: map_labels.json.bak.*, 이미지 백업은 scratchpad.
- (2026-08-12) [이동화면 초기위치 갱신] 홈을 넓은 자리로 옮긴 것 반영. 1D 대응식(안내도 x%=0.7734*mapY+30.397)에 새 홈 mapY=36.7368 대입 → 58.81%. guideRoute.js HOME_X 67.09→58.81, START_X 63.0→58.81(새 홈이 모든 방보다 왼쪽 중앙복도라 예전의 내과 겹침 회피용 오프셋 불필요). START(58.81%,38.4%) 픽셀 확인 복도(벽 아님). 진행률은 실제 남은거리 그대로.
- (2026-08-12) [원무과→산부인과가 브라우저/서버에 반영 안 되던 문제] 원인 2가지: ①kiosk_server가 예전 프로세스라 NAME_TO_ID/WHISPER_PROMPT(모듈 상수)를 옛값으로 들고 있었음 ②정적파일(JS 모듈·안내도 이미지)에 캐시방지 헤더가 없어 브라우저가 옛 버전 캐시. 해결: kiosk_server Handler.end_headers 오버라이드로 Cache-Control:no-cache,no-store 등 추가(모든 정적파일) + 서버를 동일 환경(/proc/PID/environ 캡처→xargs -0 env 재현, STT_AUDIO_DEVICE=plughw:1,0 등 유지)으로 재시작. 검증: 헤더 확인, 서버제공 locations.js=산부인과, 이미지 md5 디스크와 일치, POST /listen?text=산부인과→{locationId:wonmu,0.95}. ★이미 캐시된 브라우저는 최초 1회 하드리프레시(Ctrl+Shift+R) 필요, 이후엔 일반 새로고침으로도 최신 반영.
- (2026-08-12) [산부인과 라벨 크기 축소 + 이동화면 초기위치 L자 재구성] ①라벨: 원본 라벨(내과·외과)이 Noto Sans CJK KR Medium 26px(글자높이23·폭매칭)임을 실측 확인. 산부인과가 44px로 컸던 것을 26px로 재렌더(색#00006b) → 이웃과 동일 크기. ②초기위치: nav 실측상 홈(map -19.73,36.74)은 방들(y47~58)보다 훨씬 아래 '큰 홀'에 있음(방 복도가 아님). 안내도 벽 검출로 하부 홀(복도 아래·방들 왼쪽, 벽 x55~65% 사이) 확인. guideRoute.js를 L자 경로로 재구성: HOME_X=60,HOME_Y=46(하부 홀), routeTo=[홈 → (홈x,복도38.4) 위로 진입 → (방x,복도)]. START_X 제거(routeTo만 사용). 실제 rect로 4개 방 경로 렌더 검증 — 벽 통과 없이 홀에서 올라와 복도 따라 방 앞 도착, 415와 확실히 구분. pointAt/routeDots는 다중세그먼트 이미 지원.
- (2026-08-12) [장소 안내 문구 심플화] 사용자 요청. 화면/TTS 문장은 locations.js의 desc로 조합됨(화면 `'{name}'는 {desc}`, TTS `{name}는 {desc} {name}로 안내해 드릴까요?`). desc 3개 수정: 산부인과·내과='우측 복도 진입부에 있습니다.', 외과='우측 복도 중앙부에 있습니다.'. 약국은 요청 없어 유지. no-cache라 새로고침으로 반영.
- (2026-08-12) [캐스터 꼬임/슬립 스톨 — 탈출 1단계: 감지·로그 노드] 하드웨어: 구동륜 2 + 캐스터 4. 가끔 캐스터 꼬임/슬립으로 이동·회전이 버벅이거나 멈춤. 사용자 결정: Nav2 복구 튜닝 방향으로, 먼저 감지·로그만(모터 동작 없음). 신호 확인(드라이브 스택 라이브): /cmd_vel(명령), /imu/data(각속도=슬립무관 회전 실측), /odometry/filtered(IMU+엔코더 융합), /odom(엔코더 원본), /motor_amps(전류 [2채널], 정지 시 [0,0]). scripts/stall_monitor.py 신설(순수 관찰자, rclpy, BEST_EFFORT 구독): 명령有(cmd 신선·v≥0.03 or ω≥0.05) & 실제 정지(imuω<0.03 & filt v<0.02)가 STALL_SEC(1.5s) 지속 시 '스톨' 기록 — cmd/imu/filt/enc/amps 전부 + 분류힌트(전류높음=꼬임 / 엔코더는 도는데 실제정지=슬립 / 둘다정지). 해소 시 지속시간·peak전류 기록. 로그: logs/stall_monitor.log(전체)+logs/stall_events.log(이벤트). 임계값 env로 튜닝. 상시 백그라운드 기동(pid 확인). 다음: 실운용서 스톨 이벤트 수집→임계값 확정→Nav2 복구 튜닝(progress_checker 10→~4s, backup 먼저=캐스터 재정렬, 위글 추가). ※Nav2 기존 복구=[spin,backup,wait]로 spin이 먼저라 꼬임 악화 가능, 복귀/벽정렬 watcher엔 복구 없음. 교훈: pkill -f 패턴이 명령줄 내 경로와 self-match해 셸이 SIGTERM(exit144) — pkill은 항상 단독 실행.
- (2026-08-12) [스톨 탈출 2단계: 실제 회복 동작 구현] 사용자 결정: 자료 수집(1단계) 대신 바로 구현(랜덤이라 데이터 불확실). 아키텍처: 스톨 감지·회복을 각 제어주체 안에 넣음(stall_monitor가 cmd_vel 직접 쏘면 Nav2와 충돌하므로). ①워처 정렬(회전 위주=캐스터 꼬임 최악, cmd_vel 직접발행): return_home_watcher에 _caster_unstick() 위글 추가 — 각속도를 ALIGN_MAX_W까지 올려도 실제 회전이 안 나올 때(rate<임계 지속) 트리거. 좌우 번갈아 흔들기(±0.6rad/s, 0.4s, 2사이클, 정/역 대칭이라 net≈0·병진0=자리안옮김·벽쪽 안밀림). 정렬당 최대 3회(UNSTICK_MAX_TRIES), 초과 시 포기·정지(무한반복 금지). align_to_yaw·align_to_wall 둘 다 통합, 위글 후 floor_w 리셋해 낮은속도부터 재시도. 상수 env튜닝(UNSTICK_*). ②Nav2 주행: progress_checker 튜닝 required_movement_radius 0.5→0.10, movement_time_allowance 10→5초(스톨 시 더 빨리 복구 진입). ★보류: 복구 순서 backup先 재정렬 — default_bt_xml_filename="navigate_w_replanning_and_recovery.xml"이 실제 설치파일(navigate_to_pose_...)과 불일치, nav이 폴백으로 도는 중이라 시스템BT 편집은 위험 → 별도 확인 후 커스텀BT로. 검증: 문법·AST참조OK(_caster_unstick 2곳 호출), 워처 재시작 정상. ※Nav2 재시작해야 progress_checker 적용. stall_monitor는 이제 '탈출이 실제로 먹히는지' 검증 도구로 병행.
- (2026-08-12) [위글 완화 + 초기위치 이동] 사용자: 슬립 탈출 위글이 너무 격렬해 벽 충돌 뻔함. UNSTICK_WIGGLE_W 0.6→0.4, UNSTICK_WIGGLE_SEC 0.4→0.35(스윙 폭 ~40%↓). 초기위치 이동 요청: 현재 홈에서 로봇프레임 왼0.7+뒤0.7. ★안전검증: my_map 점유격자로 여유 계산 — 요청(왼0.7+뒤0.7)은 중심→벽 0.50m인데 로봇 회전반경 0.57m라 회전 시 벽 충돌(풋프린트 벽 겹침 확인). '뒤로'가 벽 쪽이라 여유를 1:1로 깎음(현재 1.20m). 사용자 선택=왼0.7+뒤0.3(여유 0.90m 안전). map_labels.json 초기 위치 (-19.726,36.7368)→(-20.4537,36.5121), yaw 83.96° 유지. 워처 재시작(새 위글+새 홈). 교훈: 초기위치는 반드시 점유격자 여유(≥회전반경0.57+버퍼)를 먼저 검증하고 설정. 백업 map_labels.json.bak.*.
- (2026-08-12) [초기위치 방향 수정(오른쪽) + 뒤로 추가] 사용자: 앞 커밋에서 로봇프레임 왼쪽(맵 -x)으로 옮겼는데 사용자 화면엔 오른쪽으로 보임 → 반대편(맵 +x=로봇 오른손 방향) 원함 + 뒤로 0.3 더. 안전검증(my_map 점유격자): 오른0.7+뒤0.6은 0.60m(회전반경0.57 빠듯,❌), 뒤0.5는 0.70m(✅). 원 요청(뒤 총0.6)을 안전선 0.5로 캡. map_labels.json 초기 위치 (-20.4537,36.5121)→(-19.0825,36.1659), yaw 83.96° 유지. 워처는 홈을 파일서 live 로드(재시작 불필요). ★좌우 혼동 주의: 코드의 로봇프레임 left(맵-x)가 사용자 화면에선 우측으로 보임 — 방향 지정 시 맵 그려 확인 필요. 백업 map_labels.json.bak.*.
- (2026-08-12) [약국→영상의학과 교체] 산부인과 때와 동일 방식. id 'pharmacy' 유지(내부). 변경: locations.js name+desc(우측 복도 안쪽에 있습니다), kiosk_server.py WHISPER_PROMPT/NAME_TO_ID/EXTRA_ALIASES(처방 별칭 제거), mock.js. 약국은 map_labels에 nav_goal 없어 정보안내만 되는 장소 — 영상의학과도 동일 유지(내비 목표 없음, 필요 시 RViz로 추가 가능). 안내도 이미지: 약국 칸이 좁아(~60px, 2글자용) 5글자 한 줄 불가 → 2줄 배치(영상/의학과, Noto Medium 20px, #00006b). 검증: match_location('영상의학과')→pharmacy, ID_TO_NAME[pharmacy]=영상의학과, 서버 이미지 md5 일치. 부수효과: 영상의학과는 '과'로 끝나 조사(는/로) 자연스러움(약국의 약국는/약국로 어색함 해소). ※kiosk_server 재시작 필요.
- (2026-08-12) [영상의학과에 실제 내비 목표 지정] 사용자가 로봇을 원하는 자리에 세워두고 "현재 위치를 영상의학과로 지정" 요청. TF(map→base_footprint) 현재 위치 x=-21.0618 y=68.0942 yaw=80.63°(qz0.647,qw0.7625) 획득 — 기존 방들(y47~58)보다 위쪽 복도. 안전검증: my_map 여유 0.95m(복도 내, 벽 아님). map_labels.json에 zone "영상의학과" 신규 추가(name/description/frame_id=map/nav_goal). 매칭은 build_label_index가 name만, 내비는 nav_goal만 사용 → x_min 등 라벨에디터 메타는 생략. 검증(라이브서버, kiosk_server가 map_labels mtime 변경 자동재로드→재시작 불필요): /goal?id=pharmacy가 좌표 반환(이전엔 '미설정'), match_location('영상의학과')→pharmacy. 이제 약국과 달리 영상의학과는 실제 이동 목적지(앱의 '좌표없음→이동차단' 해제됨). 백업 map_labels.json.bak.*.
- (2026-08-12) [신규 장소 소아청소년과 추가(외과 옆)] 사용자가 로봇을 세워둔 자리를 소아청소년과로 지정 요청. TF 현재위치 x=-21.3489 y=69.4071 yaw=106.30°. ★확인결과 이 위치는 외과(y57.75)서 11.83m 떨어진 위쪽복도이고 방금 지정한 영상의학과(y68.09)와 1.34m로 거의 겹침 — 사용자에 알림(AskUserQuestion). 사용자 선택='현재 위치 그대로 지정'(nav목표=현재자리, 안내도 라벨만 외과 옆). 신규 id 'pediatric'. 변경: map_labels.json zone 추가(nav_goal), locations.js 신규엔트리(rect 외과 오른쪽 빈방 x79.16/w8.26/y22.25/h13.30, room412, desc'외과 옆에 있습니다'), kiosk_server.py NAME_TO_ID/EXTRA_ALIASES/WHISPER_PROMPT, mock.js. 안내도 이미지: 외과 오른쪽 빈방(벽 1428~1577, 폭146px)에 '소아청소년과'(6글자) Noto Medium 24px 1줄(폭132px,여유14). kiosk_server 재시작(NAME_TO_ID/ID_TO_NAME 모듈상수라 필요). 검증(JSON바디 경로): 소아청소년과→pediatric 0.95, /goal?id=pediatric 좌표반환. ★함정: /listen?text= 디버그경로(L433)는 URL 날것한글을 latin-1로 되돌리는 방식이라 퍼센트인코딩(urllib.quote)과 불일치→한글유실. 테스트는 JSON바디나 curl 날것한글로. 백업 map_labels.json.bak.*.
- (2026-08-12) [도착음성 복구 + 속도2배 + 회전안전(RotationShim)]
  ①도착 안내(영상의학과/소아청소년과 무음): 원인=return_home_watcher가 죽어있었음(내 kill 실험 중 사망 추정). 코드·좌표는 완전 범용(load_zone_goal 라이브 읽기, start_tracking/arrived 처리 장소무관)이라 워처만 살아있으면 내과/외과와 동일 동작. 워처 없으면 /robot_status='unknown'→앱 waitArrival 즉시 false(robotController L81)→도착음성 없음. 워처 재기동(pid). ★워처가 조용히 죽는 건 신뢰성 문제 — 데모 시 반드시 실행 확인(start_all.sh L182가 정상 기동).
  ②속도 2배: agv.yaml max_vel_x/max_speed_xy 1.6→3.2. 실제속도는 구동스케일(회전 실측 ~12% 관측)로 명령보다 낮으니 상한 3.2는 과하지 않음. max_vel_theta 1.0 유지.
  ③회전 방식(정지→제자리 회전→주행): nav2_rotation_shim_controller(Galactic 설치됨)로 FollowPath 래핑. 경로 방향과 angular_dist_threshold(0.6rad≈34°) 이상 어긋나면 정지 후 제자리 회전으로 정렬(rotate_to_heading_angular_vel 0.8, max_angular_accel 2.5) 뒤 DWB로 주행. 고속 회전이동 중 넓은 풋프린트(0.9×0.7,회전반경0.57)가 벽 스치는 것 방지. DWB params는 FollowPath 네임스페이스 그대로 유지. YAML 검증 OK. ※Nav2 재시작 필요. 백업 agv.yaml.bak.*.
- (2026-08-12) [TTS 무음 재발 — 스피커 카드 재번호 → 이름기반 감지로 근본해결] 증상: TTS 안 들림. 원인: USB 스피커(UACDemoV1.0)가 card0→card1로 재번호됐는데 실행 중 tts_server(1.9h 전 기동)는 plughw:0,0 고정 → aplay "No such file or directory" 반복 실패(무음). tts_server._detect_speaker 개선: 카드 '번호' 대신 '이름'(plughw:CARD=UACDemoV10,DEV=0)을 쓰도록 → 재부팅으로 번호가 바뀌어도 유지(근본 재발 방지). aplay로 장치 열림 검증 후 tts_server 재시작(모델 로드~21s). 검증: POST /tts ok:true, aplay 실패 로그 없음. 교훈: USB 오디오(마이크·스피커) 카드 번호는 재부팅/재연결마다 바뀜 — 항상 이름(CARD=) 또는 자동감지로 잡을 것.
- (2026-08-12) [TTS 음량 증가] 사용자 요청. USB 스피커(UACDemoV10) ALSA 'PCM' 볼륨 76%(-7.66dB)→100%(-0.94dB, +약6.7dB≈체감 2배). 재부팅해도 유지되게 tts_server가 기동 시 _set_speaker_volume()로 감지된 카드에 amixer sset(PCM/Speaker/Master 등 순차 시도, TTS_VOLUME env 기본 100%)를 적용. 검증: 로그 '스피커 볼륨 설정: PCM=100%', 재생 ok. 100%(하드웨어 0dB 근처)가 상한 — 더 필요하면 WAV 소프트웨어 게인(클리핑 위험) 필요.
- (2026-08-12) [TTS 음량 100%→85%로 하향] 100%는 너무 컸음. 원래 76%보다 조금만 위인 85%(-5.05dB)로. amixer 즉시 적용 + tts_server 기본 TTS_VOLUME 85%. 미세조정은 amixer -c UACDemoV10 sset PCM NN% 또는 TTS_VOLUME env.
- (2026-08-19) [이동/회전 방식·속도 롤백] 사용자가 RotationShim+속도2배(3.2) 이동을 실제로 써보고 마음에 안 든다 → 되돌림. agv.yaml을 변경 직전 백업(agv.yaml.bak.20260819_191620)으로 복원: plugin DWB(제자리회전 shim 제거, 기존 부드러운 주행), max_vel_x/max_speed_xy 3.2→1.6. 캐스터 탈출(위글)·stall_monitor·progress_checker 튜닝은 이동방식과 무관하므로 유지. 현재 shim 흔적 0, YAML OK. 3.2+shim 상태는 agv.yaml.rotationshim.* 로 별도 보관. ※Nav2 재시작해야 적용. ※속도는 1.6(2배 직전값)으로 둠 — 원래 0.8을 원하면 추가 조정 필요.
- (2026-08-19) [소아청소년과 도착음성 실패 원인규명·수정] 사용자: 소아청소년과 도착음성 안 나옴 + 거리 왕복 착각 의심. 조사: return_home_watcher는 살아있고 로그상 '소아청소년과' 도착을 정확히 감지·"arrived" 기록함(코드·좌표 정상, 거리계산은 편도만 사용, 왕복 아님). 진짜 원인=앱쪽: 소아청소년과/영상의학과는 홈에서 32~33m로 멀어 느린 로봇이 이동 마치기 전 앱 waitArrival 타임아웃(180초)이 먼저 끝나 도착음성을 놓침. 워처 TRACK_TIMEOUT(240초)보다 앱(180초)이 짧은 불일치. 수정: app.js·robotController.js waitArrival 타임아웃 180→300초(워처 240초보다 넉넉). 내과/외과(12~22m)는 180초 내 도착이라 음성 정상이었음. ※거리 왕복 착각은 코드상 없음(initial_dist/remaining 모두 편도). 소아청소년과 좌표(-21.35,69.41)가 amcl 드리프트로 의도(외과 옆)와 다르면 재설정 필요 — 별도 확인.
- (2026-08-19) [복귀 후 벽정렬 안 됨 원인규명·수정] 사용자: 영상의학과 갔다 복귀하면 벽과 수평 정렬 안 됨. 로그 분석: 정렬 자체는 정상(시간내 도착한 복귀는 align_to_yaw+align_to_wall 완료, 벽오차 -0.08~-0.85°). 진짜 원인=복귀(32m)가 워처 TRACK_TIMEOUT(240초)을 초과 → '도착 확인 안됨'으로 감시 종료 → 도착핸들러(정렬) 아예 실행 안 됨. 도착음성 이슈와 동일 뿌리(먼거리+느린로봇+짧은 타임아웃). 수정: TRACK_TIMEOUT_SEC 240→480초, 앱 waitArrival 300→480초(일관성). 워처·앱 재적용. ★근본: 32m 복귀에 240초 초과 = 실효속도 <0.13m/s로 비정상적으로 느림(구동스케일 or 이동중 캐스터 스톨/Nav2 recovery 지연 의심) — 타임아웃 증가는 대증요법, 느린 원인은 별도 조사 필요.
- (2026-08-19) [신규 장소 마취통증의학과 추가(영상의학과 오른쪽)] nav=로봇 현재위치 x=-20.1529 y=76.4751 yaw=73.96°(여유1.10m). 안내도=영상의학과 오른쪽 빈방(벽 1428~1626, 폭198px). id 'pain'. 변경: map_labels.json zone(nav_goal), locations.js 엔트리(rect x79.16/w10.9/y41.28/h13.07 bottom row, room413, desc'영상의학과 옆에 있습니다'), kiosk_server.py NAME_TO_ID/EXTRA_ALIASES/WHISPER_PROMPT, mock.js. 안내도 라벨 '마취통증의학과'(7글자) Noto Medium 26px 1줄(폭167,여유25)—넓은 방이라 이웃과 동일크기 가능. kiosk_server 재시작(마이크 card 재번호로 STT_AUDIO_DEVICE=plughw:CARD=Device,DEV=0). 검증: match→pain 0.95, /goal?id=pain 좌표반환, 이미지 md5일치. 좌표는 영상의학과(y68)·소아청소년과(y69)보다 더 위(y76) — 실제로는 다 위쪽 복도 군집.
- (2026-08-19) [신규 장소 진단검사의학과 추가(왼쪽 복도 아래, 오른쪽서 2번째 방)] nav=로봇 현재위치 x=-27.0817 y=18.2896 yaw=-86.53°(여유1.40m, 이전 장소들과 완전 다른 좌하단 구역). 안내도: 왼쪽 아래 방행 벽검출(x 449/597/743/939/993px=방4개), 맨오른쪽=R1(좁음,939~993), 오른쪽서 2번째=R2(743~939, 중심46.6%)에 배치. id 'labmed'. 변경: map_labels zone(nav_goal), locations.js(rect x41.2/w10.85/y41.1/h13.7, room416, desc'왼쪽 복도 아래쪽에 있습니다'), kiosk_server NAME_TO_ID/EXTRA_ALIASES/WHISPER_PROMPT, mock.js. 라벨 '진단검사의학과'(7글자) 26px 1줄(폭167,방196). kiosk 재시작. 검증: match→labmed, /goal?id=labmed 좌표, 이미지md5일치. ※'맨오른쪽 방' 해석: R1(폭54px 좁은방) 포함해 2번째=R2로 배치 — 다르면 조정.
- (2026-08-19) [화장실 추가 — 마크 있음, 글자 라벨 없음] nav=로봇 현재위치 x=-26.2478 y=30.8996 yaw=84.19°(여유9.90m 넓은곳). 안내도엔 남/녀+휠체어 아이콘이 이미 있어 텍스트 라벨 안 넣음(이미지 미변경). 하이라이트 rect만 화장실 구역에 배치: 벽검출 x837~956(46.4~53.0%)·y161~313(18.5~35.9%). id 'toilet'. 변경: map_labels zone(nav_goal), locations.js(rect x46.4/w6.6/y18.5/h17.5, room'', desc'중앙 복도 왼쪽, 엘리베이터 옆'), kiosk_server NAME_TO_ID/EXTRA_ALIASES(화장실/변소)/WHISPER_PROMPT, mock.js. 검증: match 화장실→toilet, /goal?id=toilet 좌표, 하이라이트박스가 아이콘 정확히 덮음. ※화장실은 받침(ㄹ)이라 앱 템플릿 '화장실는'이 어색(→화장실은). '화장실로'는 맞음.
- (2026-08-19) [Nav2 주행 중 회전 시 벽 근접 정지/덜컥거림 — 안전 방향 수정 1단계] 진단: 실제 로봇 회전반경 0.57m인데 Nav2 robot_radius가 global0.4/local0.3으로 과소 → Nav2가 벽 0.4m만 띄우고 회전 시도, 실제 모서리(0.57m)는 벽 안쪽 → 라이다 근접→컨트롤러 정지/극저속. min_speed_theta=0이라 데드밴드 저속명령→바퀴 덜컥. 복도폭 측정 3~10m라 물리적 문제 아님(설정 문제). 사용자 최우선=벽충돌 방지. ★안전 방향=로봇모델 키우기(벽에서 더 멀어짐=더 안전). 위험방향(인플레이션/마진 축소)은 안 건드림. 1단계: robot_radius global0.4→0.55, local0.3→0.55(회전반경 0.57 근사). 백업 agv.yaml.bak.*. 롤백=robot_radius 0.4/0.3 복원. ※Nav2 재시작 필요. 2단계(min_speed_theta 0→~0.35, 덜컥거림)는 이거 시험 후. 시험법: 넓은곳·저속·E-stop대기·한번에 하나씩.
- (2026-08-19) [robot_radius 변경 롤백] 사용자 요청으로 앞 변경(robot_radius 0.4/0.3→0.55)을 원복: global 0.4, local 0.3. YAML OK. ※Nav2 재시작해야 원복 적용. (회전 시 벽근접 문제는 하드웨어 접지/서스펜션 쪽 개선으로 방향 전환 논의 중)
- (2026-08-19) [속도 2배 + 복귀 전 홈방향 제자리 회전] 사용자 요청.
  ①속도: agv.yaml max_vel_x·max_speed_xy 1.6→3.2. ※Nav2 재시작 필요. ※실효속도는 슬립/구동스케일로 더 낮음, 슬립 심하면 오히려 악화 가능(하드웨어 접지개선과 병행 권장).
  ②복귀 전 회전: return_home_watcher, 도착·대기(DWELL) 종료 후 복귀요청 직전에 '홈 방향 바라보기' 제자리 회전 삽입. 홈bearing=atan2(home_y-cur_y, home_x-cur_x), align_to_yaw(bearing, tol=8°)로 거칠게 정렬(방향만; Nav2가 이후 세밀조정) → 좁은 복도 중간 회전 회피(목적지는 넓어 회전 안전). align_to_yaw에 tol 파라미터 추가(기본 ALIGN_TOL 0.5° 유지, 벽정렬엔 영향 없음). 회전 중 새 요청이면 복귀 취소. PRE_RETURN_FACE_HOME/PRE_RETURN_TOL_DEG env로 on-off·튜닝. 검증: 문법·AST OK, 워처 재시작 정상. (워처는 이미 라이브; 속도만 Nav2 재시작 대기)
- (2026-08-19) [앞 변경 롤백] 사용자 요청으로 직전 커밋(속도2배+복귀전회전) 되돌림: agv.yaml max_vel_x/max_speed_xy 3.2→1.6, return_home_watcher.py는 git으로 복귀-전-회전 삽입 전 버전 복원(TRACK_TIMEOUT 480은 유지). 워처 재시작. ※속도는 Nav2 재시작해야 원복 적용.
- (2026-08-19) [복귀 중 회전 진동/멈춤 완화 — Nav2 회전 완만화 4종] 증상: 복귀 중 좁은복도/특정장소서 회전하다 멈추거나 반대로 회전(진동). 진단: 실측 회전 12%(구동스케일 지연+캐스터 stick-slip)로 DWB가 과명령→튐→반대명령 진동, 벽비용 겹치면 멈춤. 근본은 접지/구동보정(하드웨어)이나, 안전한 대증(느리고 부드럽게=충돌위험 안 늘림) 4종 적용: agv.yaml max_vel_theta 1.0→0.6, min_speed_theta 0→0.2(데드밴드 위 결정적), acc_lim_theta 2.5→1.5(부드러운 가감속), Oscillation 크리틱 튜닝(scale1.0/reset_dist0.05/angle0.2/reset_time1.5 — 진동 억제하되 영구잠금→멈춤 방지). 백업 agv.yaml.rotcalm_bak.*. ※Nav2 재시작 필요. 롤백=백업 복원 or 값 원복(1.0/0/2.5, Oscillation.* 제거).
- (2026-08-19) [회전 파라미터 롤백] 사용자 요청("기존 걸로 복구"). agv.yaml을 rotcalm 백업(1787994890)으로 복원 → max_vel_theta 1.0, min_speed_theta 0, acc_lim_theta 2.5, Oscillation.* 제거. max_vel_x 1.6 유지. YAML OK. ※별개 이슈: ROS 내비 스택(브링업/amcl/Nav2)이 죽어있음(사용자가 Nav2 재시작 중 스택이 안 올라온 듯) → start_all.sh 재기동 필요. 이건 설정과 무관.
- (2026-08-29) [agv.yaml 완전 최초 복원] 사용자 요청("완전 최초로"). 가장 오래된 백업(20260720_165930)으로 복원 — 세션 중 agv.yaml 변경 전부 원복: max_vel_x/max_speed_xy 1.6→0.8, BaseObstacle.scale 0.4→0.1, progress_checker 0.10/5→0.5/10. (회전파라미터·robot_radius·RotationShim은 앞서 이미 원복됨.) 최초 백업과 100% 동일 확인. 현재상태 안전백업 agv.yaml.before_full_revert.*. ※map_labels(추가 장소들·홈위치)·locations.js 등은 그대로(agv.yaml만 원복). ※ROS 스택은 여전히 꺼져있어 start_all.sh 재기동 필요(설정과 무관).
- (2026-08-29) [바퀴 속도 살짝 상향 + base_width 확인] 사용자 요청. ①속도: agv.yaml max_vel_x/max_speed_xy 0.8→1.0(살짝만). 백업 agv.yaml.speedbump_bak.*. ②base_width: 실제 cmd_vel→모터 변환·오도메트리는 roboteq_controller가 담당(query.yaml cmd_vel_topic=/cmd_vel, track_width=0.475 — 주석상 0.6223→0.475로 캘리브레이션됨). URDF 바퀴간격 0.48과 사실상 일치 → 보정 불필요. 앞서 지적한 diff_tf base_width 0.46은 브링업에서 안 띄우는 미사용 노드라 무관(twist_to_motors도 미사용). ★결론: 회전 실측 12% 손실은 base_width 오류 아님 = 순수 접지/슬립(하드웨어). ※Nav2 재시작해야 속도 적용.
- (2026-08-29) [안내 문구 재정비] 사용자 요청. locations.js desc를 위치기준으로 갱신: 내과/산부인과=우측복도 초입, 외과/영상의학과=우측복도 중간, 소아청소년과/마취통증의학과=우측복도 끝, 화장실=좌측복도 초입, 진단검사의학과=좌측복도 중간. app.js 문구 변경: 배너 `'{name}'{조사} {desc}에 있습니다.`, 음성(hasGoal) `{name}{조사} {desc}에 있고, 해당 위치로 안내를 할까요?`, confirmQ '해당 위치로 안내를 할까요?'. 한글 받침 조사 헬퍼 josa() 추가(화장실→'은', 내과→'는' 자동). 검증: 내과→"내과는 우측 복도 초입에 있고, 해당 위치로 안내를 할까요?", 화장실→"화장실은...". kiosk 재기동(UI서빙). ※자율주행은 이전 상태 킵(agv.yaml speed 1.0). ※ROS 스택은 여전히 꺼져있어 실제 이동엔 start_all.sh 필요.
- (2026-08-29) [데모용 mock 인식기 제거] 사용자 요청("데모용 인식할 질문 선택"= mock 불필요). useMock=false(실제 STT)라 이미 미사용이던 mock 경로 일괄 삭제: mock.js 삭제, recognizer/index.js는 항상 realRecognizer, index.html demo-box(데모용·인식할 질문을 선택하세요) 제거, config.js useMock 제거, robotController.js useMock 분기+CONFIG import 제거(goTo 단순화), real.js demo-box 숨김코드·주석 정리, style.css .demo-box/.demo-label 제거. ※.demo-chips 클래스는 재질문화면(retry-choices)이 재사용해 유지. 검증: 서버 index.html demo-box 0, useMock 0, mock.js 404. 실제 인식(마이크+whisper)엔 영향 없음.
- (2026-08-29) [UI 전용 기동 스크립트 추가] 사용자 요청("start_all.sh 말고 ui만"). scripts/start_ui.sh 신설: kiosk 앱 서버만 띄움(serve.sh 재사용=마이크 자동감지·게인·venv), ROS 스택(amcl/Nav2/드라이버)은 전혀 안 건드림. 기존 kiosk 정리 후 기동, whisper(8080)/tts(5002) 상태만 안내(재사용, 여기서 안 띄움). 포그라운드·Ctrl+C 종료. 용도 구분: start_ui(UI만)/run_app(UI+음성)/start_all(전체). 검증: 기동 시 포트8000·홈화면 서빙 OK. 부수: serve.sh 헤더의 옛 mock 주석 정리(mock 제거 반영).
- (2026-08-29) [개발용 타자 입력 기능 추가(마이크/스피커 없이 UI 확인)] 사용자: 마이크·스피커 없어서 타자로 질문→글로 답변하는 임시 기능 필요. 구현: URL ?dev=1 일 때만 홈화면에 타자 입력폼 표시(프로덕션 무관). index.html dev-input form, app.js initDevInput()(제출 시 /listen에 텍스트 바디 POST→실제 매칭 결과→handleRecognition, 즉 실제 음성과 동일 흐름), style.css .dev-input, start_ui.sh에 ?dev=1 URL 안내 추가. 검증: /listen 텍스트바디로 내과→internal/화장실→toilet/마취통증의학과→pain 매칭(마이크 불필요), 결과화면에 문구 글로 표시. TTS 없어도 화면 텍스트(배너/confirmQ)로 답 확인 가능.
- (2026-08-29) [start_ui 전용 LLM 매칭 고도화(gpt-4o-mini)] 사용자 요청: 동의어·오인식·부분명("청소년과"→소아청소년과)도 한번에 매칭. 설계: 규칙매칭 1순위(빠름·무료·정확)→실패 시 OpenAI 폴백. kiosk_server._openai_match() 추가(OpenAI Responses API /v1/responses, urllib 표준라이브러리, NAME_TO_ID를 프롬프트로 줘 id 분류, temperature0). match_location 3단계로: llm규칙→EXTRA_ALIASES→_openai_match. 게이팅: LLM_MATCH_ENABLE=1 + OPENAI_API_KEY 있을 때만(기본 off=규칙만, 회귀없음 검증). start_ui.sh가 LLM_MATCH_ENABLE=1 세팅 + OPENAI_API_KEY를 env 또는 .openai_key(gitignore)에서 로드. 모델교체=OPENAI_MODEL env(기본 gpt-4o-mini). ★start_all/run_app엔 미적용(플래그 안 줌)=프로덕션 영향 0. 사용자가 .openai_key에 키 넣어야 실제 동작.

## 2026-09-01 — 영어 다국어 지원(start_ui, ui-dev)
- 질문 언어 자동 감지(detectLang): 한글 있으면 ko, 영문이면 en.
- locations.js: 각 장소에 name_en/desc_en 추가(정식 진료과명, 답변 텍스트 전용).
- app.js: 답변·버튼(Yes/No)·안내·이동·도착 문구를 STR 다국어 테이블로 언어별 출력.
- 지도 이미지는 한글 라벨 그대로 유지(방 안에 영어명 안 들어가서). 답변만 영어.
- kiosk_server.py: LLM 매칭 프롬프트에 영어 예시 추가(radiology→pharmacy 등).
- 검증: /listen 로 "where is radiology"→pharmacy, "restroom"→toilet, "pediatrics"→pediatric, 한국어도 정상.

## 2026-09-01 — 일본어 다국어 지원(start_ui, ui-dev)
- detectLang에 일본어(히라가나/가타카나/한자) 감지 추가.
- locations.js: name_ja/desc_ja(정식 진료과명: 内科/外科/産婦人科/放射線科/小児科/麻酔科・ペインクリニック/臨床検査科/お手洗い).
- app.js: STR을 tt(한/영/일) 3언어 테이블로 확장 — 답변·버튼(はい/いいえ)·안내·이동·도착 문구 일본어 출력.
- kiosk_server.py: LLM 프롬프트에 일본어 예시 추가(放射線科→pharmacy 등).
- 검증(임시 8001, 새 프롬프트): 放射線科/レントゲン→pharmacy, 麻酔科→pain, 検査科→labmed, 産婦人科→wonmu, 小児科→pediatric 모두 정상.
- 주의: 개선된 일본어 매칭(放射線科 등)은 start_ui.sh 재기동 후 적용됨.

## 2026-09-01 — 중국어(간체) 다국어 지원(start_ui, ui-dev)
- detectLang: 가나→ja, (가나없이)한자→zh 로 일/중 구분. 한글→ko, 영문→en 유지.
- locations.js: name_zh/desc_zh(간체 정식명: 内科/外科/妇产科/放射科/儿科/麻醉疼痛科/检验科/洗手间).
- app.js: tt()·STR을 4언어(한/영/일/중)로 확장 — 답변·버튼(是/否)·안내·이동·도착 중국어 출력.
- kiosk_server.py: LLM 프롬프트에 중국어 예시 추가(放射科→pharmacy 등).
- 검증(임시 8001, 새 프롬프트): 放射科→pharmacy, 洗手间→toilet, 儿科→pediatric, 妇产科→wonmu, 麻醉疼痛科→pain, 检验科→labmed 정상.
- 주의: 개선된 중국어 매칭은 start_ui.sh 재기동 후 적용됨. (일/중 한자 단어 하나만 입력 시 zh로 감지되는 경계 케이스 있음)

## 2026-09-01 — S-04 수속 안내 구현(start_ui, ui-dev)
- 진입: 홈 "📋 접수·수속 안내" 버튼 + "접수/수속/초진/재진/처음 왔어요" 발화 인텐트 감지.
- 흐름: 초진/재진 → (재진)예약유무 → 증상 입력(intake 화면, 음성+타자) → 증상→진료과 트리아지 → "원무과 접수 후 ○○과" 안내 → 기존 길안내(S-01) 합류.
- 재진·예약함: 예약 조회 시스템 없어 진료과 되묻기로 처리.
- 서버: /triage 엔드포인트 추가(증상→진료과). _triage_keyword(무료 규칙, 소아/부인과 우선) + _openai_classify(LLM 폴백) — _openai_match도 이 공용 헬퍼로 리팩터.
- 트리아지 대상: 내과/외과/산부인과/소아청소년과/마취통증의학과(영상·검사는 의뢰과라 제외).
- 응급 키워드 감지 시 트리아지 대신 응급실/직원 안내.
- 검증: /triage 로 머리+열→internal, 아이열→pediatric, 무릎→pain, 베임→surgery, 임신→wonmu, 모호→null 정상.
- 주의: /triage 는 서버 변경이라 start_ui.sh 재기동 필요.

## 2026-09-01 — S-04 확장: 홈 2단계 + 환자 등록 + 대기명단(start_ui, ui-dev)
- 홈 2단계: "위치 안내"/"접수 안내" 두 버튼만 → 위치 선택 시 마이크 등장(음성 장소안내), 접수 선택 시 초진/재진.
- 초진: 이름·주민번호·연락처 입력 → patients.json 저장 → 증상 음성/타자 → 트리아지 → 진료과 대기명단 등록 → 위치안내 제안.
- 재진: 이름·주민번호 입력 → 조회 → 예약 여부. 예약=이전 진료과(last_dept) 대기명단 자동등록 / 미예약=증상으로.
- 서버: /patient/register·/patient/lookup·/waitlist/add(POST), /waitlist(GET). 저장: data/patients.json, data/waitlist.json(SSD, gitignore).
- 주민번호 평문 저장 금지: 마스킹(900101-1******)+sha256 해시만. 재진 조회는 해시 매칭.
- 관리자 화면: ?admin=1 → 진료과별 대기명단, 5초 자동 새로고침.
- 검증: 초진 등록→트리아지(무릎→pain)→대기추가(1번), 재진 조회(lastDept 자동파악), 예약 대기추가 모두 정상. 저장파일에 평문 주민번호 없음.
- 주의: 서버 신규 엔드포인트라 start_ui.sh 재기동 필요.

## 2026-09-01 — S-04 재진 예약 자동화 + 간호사 관리(admin) (start_ui, ui-dev)
- 초진은 그대로. 재진: 예약 물어보지 않고 데이터셋 조회 → 예약 있으면 해당 진료과 자동 등록(예약 소비), 없으면 증상 음성인식.
- 환자 레코드에 reservation 필드 추가. 간호사가 admin에서 예약을 직접 기록.
- 서버: /reservation/set(예약 등록), /waitlist/remove(항목 삭제), waitlist 항목에 id 부여, /waitlist/add consumeReservation 플래그(예약 소비). GET /waitlist에 reservations·depts 포함.
- admin(?admin=1): 예약 등록 폼(이름·주민번호·진료과), 예약 현황, 진료과별 대기명단 칸 분리 + 칸마다 삭제 버튼. 스크롤 가능.
- 검증: 예약등록→재진조회(예약 노출)→자동등록(소비)→재조회(예약 없음)→대기삭제 모두 정상.
- 주의: 서버 신규 엔드포인트라 start_ui.sh 재기동 필요.

## 2026-09-01 — 데이터셋/예약 저장 분리 (start_ui, ui-dev)
- 관심사 3파일 분리: patients.json(등록 정보만: 이름·주민번호·연락처), reservations.json(예약 별도), waitlist.json(대기명단).
- 예약을 환자 레코드에서 분리 → 데이터셋을 지워도 예약 안전(그 반대도).
- 서버: /reservation/check(재진 조회, reservations.json), /reservation/set(간호사), /reservation/remove(rrn 또는 rrnHash), waitlist_add는 데이터셋 미변경(예약 소비만).
- 재진 클라: /patient/lookup → /reservation/check 로 변경.
- admin: 예약 현황에 삭제 버튼(rrn_hash로 삭제), 대기명단 칸별 삭제 유지.
- 검증: 새 patients.json 키는 name/rrn_masked/rrn_hash/contact/created_at/updated_at 뿐(예약·이력 없음), reservations.json 별도 확인.
- 주의: 서버 변경이라 start_ui.sh 재기동 필요.

## 2026-09-02 — [사이클5·A-1] 응급 키워드 필터 4개국어 + 서버 안전망 (ui-dev)
- 규칙 기반 응급 필터를 LLM 트리아지보다 먼저: 증상→(a)규칙 응급검사→(b)통과시만 /triage LLM.
- 클라이언트 isEmergency를 한/영/일/중 4개국어 키워드(KTAS 1~2, 9범주+공통)로 교체. EMERGENCY_KW 배열→정규식.
- 서버 /triage에도 동일 규칙(is_emergency) 안전망: 응급이면 {emergency:true} 반환하고 LLM 호출 안 함. 클라이언트도 data.emergency 존중(방어 심층).
- 중증 수식어(심한/갑자기/剧烈/激しい) 포함해 경증 오탐 방지.
- 검증(임시 8014): 4개국어 응급(숨못쉼·심한흉통·갑작두통·토혈·마비·can't breathe·呼吸困难·抽搐 등) 전부 EMERGENCY, 경증(가벼운 두통·무릎·감기)은 정상 트리아지.
- 응급 분기 화면 자체는 A-2에서 크게(직원호출/119) 개선 예정. 지금은 기존 다국어 안내 메시지.

## 2026-09-02 — [사이클5·A-2] 응급 분기 전용 화면 (ui-dev)
- 응급 판정 시 트리아지·대기등록 안 하고 전용 화면(#emergency-screen)으로 분기.
- 크게·다국어: 🚨 아이콘(점멸) + "응급 상황일 수 있습니다"(빨강 대형) + "즉시 직원 호출/119"(4개국어). 배경 빨강 점멸.
- [직원 호출] 버튼: Web Audio 경보음(삐뽀) + "직원을 호출했습니다" 안내. 실제 호출신호 연동 자리(현재 데모용).
- showEmergency를 retry형에서 전용 화면으로 교체. emg-title/sub/call은 STR 4개국어, 처음으로는 data-i18n.
- 정적 변경(서버 무관) → 새로고침만.

## 2026-09-02 — [사이클5·A-3] 트리아지 면책 문구 + 추천(강제 아님) (ui-dev)
- 비응급 트리아지 결과에 면책 문구 항상 표시: "이 안내는 진단이 아니며 정확한 것은 의료진과 상담"(4개국어). showRetry에 note 파라미터 + #retry-note(빈값 CSS 숨김).
- LLM이 고른 과를 강제하지 않음: "추천 진료과 XX"로 제시 + [XX로 접수(추천)] + 다른 walk-in 과 버튼들 → 환자가 최종 선택. (기존엔 자동 등록이었음)
- 애매(트리아지 실패) 화면에도 면책 문구 표시.
- 정적 변경 → 새로고침만.

## 2026-09-02 — [사이클5·B-4] 대기명단 스키마 확장: 순번·상태 (ui-dev)
- waitlist.json 구조 변경: {queues:{진료과id:[entry]}, counters:{진료과id:다음순번}}. (기존 파일 없어 마이그레이션 불필요)
- entry에 ticket(진료과별 순번, 재사용 안 함)·status("waiting"→"called"→완료시 제거)·called_at 추가.
- waitlist_add 반환에 ticket·id·ahead(앞 대기+호출 인원). /waitlist GET의 waitlistById는 queues에서 생성(항목에 ticket/status 포함).
- admin 대기현황: "#순번 · 이름 · 마스킹 · 초/재진 · 대기/🔔호출됨 · 증상" 표시. 접수 확인문구는 순번(ticket) 표시.
- 검증: internal(A=1,B=2)·surgery(C=1) 과별 독립 순번, ahead 정상 → B-7(과별 분리)도 구조 충족.
- 호출/완료 버튼(B-5)·환자 대기화면(B-6) 다음.

## 2026-09-02 — [사이클5·B-5] admin 호출/완료 버튼 (ui-dev)
- 서버: /waitlist/call(상태 called+호출시각), /waitlist/done(완료=목록 정리). waitlist_call/done 함수 추가.
- admin 대기현황 각 항목에 [호출][완료][삭제] 버튼. 호출됨 항목은 파란 하이라이트+"🔔호출됨"+버튼 "재호출".
- 검증: 호출→status=called, 완료→제거(순번 유지, 재번호 없음).

## 2026-09-02 — [사이클5·B-6,B-7] 환자 대기 현황 화면 + 과별 순번 (ui-dev)
- 서버 /waitlist/status(POST {deptId,id}): 내 순번·앞 대기수(ahead)·상태 반환. 완료로 목록서 빠지면 found:false.
- 접수 완료 시 retry 확인 대신 전용 #wait-screen: "접수 완료 / 순번 N번 / 앞에 M명 / 예상 진료과 XX"(4개국어). 2.5초 폴링.
- 호출되면 초록 점멸 + "🔔 호출되었습니다 — XX로 오세요"(음성 1회). 앞 1명 이하면 "곧 순서입니다" 강조. 완료(빠짐)면 감사 인사.
- 위치 안내 버튼(해당 진료과로 길안내) + 처음으로. resetToVoice에서 폴링 정지.
- B-7: 순번/대기줄/상태 모두 진료과별 독립(B-4 구조) — internal·surgery 별개 검증.
- 검증(임시): B ahead 1→(A호출)1→(A완료)0→(B호출)called 정상.

## 2026-09-02 — [사이클5·C-8,C-9] admin 접근 통제: PIN 게이트 + 자동 잠금 (ui-dev)
- C-8: ADMIN_PIN(env, start_ui.sh가 .admin_pin 또는 기본 0000 로드) 설정 시 민감 엔드포인트 X-Admin-Pin 헤더 요구.
  보호: GET /waitlist, /patient/remove, /reservation/set·remove, /waitlist/remove·call·done. /admin/auth(POST {pin})로 확인.
  개방 유지(환자용): /waitlist/add·status, /reservation/check, /patient/register, /triage, /listen.
  클라: ?admin=1 → PIN 게이트(#admin-gate) → 인증 후 진입. 모든 admin 요청은 adminFetch(헤더 부착).
- C-9: 자동 잠금 — admin 화면 3분 무조작 시 PIN 폐기·새로고침 정지·게이트 복귀(재인증). PIN 보호 상태에서만.
- .admin_pin gitignore 추가. start_ui.sh에 PIN 로딩(2.6) 추가.
- 검증(ADMIN_PIN=1234): auth 정오답, /waitlist 헤더없음 403·PIN 200, 환자 add 200(개방), admin remove 403/200.

## 2026-09-02 — [사이클5·D-10] 다국어 검증(서버) (ui-dev)
- (a) 응급 분기: ko(숨못쉼)·en(can't breathe)·ja(意識がない)·zh(突然剧烈头痛) 전부 EMERGENCY ✓
- (b) 일반 증상→추천 과: 무릎→pain(ko/en), お腹が痛い→internal(ja), 咳嗽发烧→internal(zh) ✓
- (c) 접수→순번→호출→완료: 등록(순번1,ahead0)→상태(waiting)→호출(called)→완료(found:false) ✓
- 남은 검증(사용자 브라우저 몫, JS런타임·마이크 없음): 면책문구/응급화면/대기화면/PIN게이트 '화면 표시', 마이크 음성 응급 감지.
- 백업 태그 cycle5-done 생성.

## 2026-09-02 — [사이클6·A-1] 디자인 토큰(라이트 화이트/블루) (ui-dev)
- css/tokens.css 신설(style.css보다 먼저 로드). 다크→라이트 전환.
- 색: bg #eef3f9, surface #fff, text #16202e, primary #1763c9, success #1a854b, danger #d12f2f (+soft/strong, 대비 AA↑). 기존 이름(--accent/--blue 등)은 새 팔레트로 매핑해 자동 재테마.
- 글꼴 --fs-xs~3xl(clamp, 히어로는 vh 캡), 간격 --sp-1~8, --radius-sm/lg/pill, --shadow-sm/lg, --touch-min 64px, --focus-ring(+:focus-visible).
- style.css의 :root 제거(토큰은 tokens.css로 일원화), 하드코딩 색 전부 토큰으로 수렴(점멸 배경·#fff·#f4f7fa). 남은 hex 0.
- 검증: Chromium 헤드리스로 홈 렌더 확인 — 라이트 테마 정상, 가독성·기능 유지.
- 로직·엔드포인트 무변경(CSS만).

## 2026-09-02 — [사이클6·A-2] 공통 컴포넌트 스타일 (ui-dev)
- 버튼 체계: .btn-primary/.btn-danger(새), .btn-secondary/.btn-ghost/.chip에 호버·터치최소·상태 보강. 모두 --touch-min(64px)+포커스.
- .card, .field(입력 공통·invalid·focus-ring), .steps/.step/.step-sep(스텝 인디케이터), .spinner(로딩).
- 전부 토큰만 사용. 추가 CSS(기존 규칙 파괴 없음) → 기능·레이아웃 무영향. C에서 화면에 적용.

## 2026-09-02 — [사이클6·A-3] 접근성 기준 정립 (ui-dev)
- 기준 명문화(tokens.css): 대비≥4.5:1(본문)·큰글씨≥3:1, 터치≥64px, 포커스 항상 표시(:focus-visible 링), 색+아이콘/텍스트 병행.
- 감사: outline 제거 2곳 모두 focus-ring 대체 확인. 상태는 아이콘/텍스트 병행(🔔/🚨) 확인.
- 색 대비: text #16202e/ text-dim #556579 / primary·success·danger 흰글씨 전부 AA 이상(A-1에서 산출).

## 2026-09-02 — [사이클6·B-4] 진행 단계 표시(스텝 인디케이터) (ui-dev)
- form/intake/wait 화면 상단에 스텝 인디케이터(.steps .flow-steps). setSteps(host, activeIdx) 렌더.
- 초진 ①정보입력→②증상→③완료 / 재진 ①본인확인→②확인→③완료 (4개국어, currentPatient.visitType로 라벨 선택).
- 지난 단계 ✓·초록, 현재 단계 파랑 강조. 로직·엔드포인트 무변경(표시만).

## 2026-09-02 — [사이클6·B-5] 뒤로 가기 / 수정 (ui-dev)
- form/intake 화면에 "뒤로" 버튼: 폼→초진/재진 선택, 증상→폼(recognizer.cancel 후).
- 값 보존: startPatientForm이 같은 visitType 재진입 시 currentPatient의 name/rrn/contact를 폼에 복원 → 증상단계에서 뒤로 눌러 이름/번호 수정 가능.
- submitPatientForm이 contact도 currentPatient에 저장.
- "수정"은 뒤로 이동+값 복원으로 구현(별도 요약-확인 화면은 데모 범위상 생략; 필요 시 추가 가능).

## 2026-09-02 — [사이클6·B-6] 무조작 자동 리셋 (ui-dev)
- 홈/관리자 제외 화면에서 IDLE_MS(기본 60초, 환경변수 KIOSK_IDLE_SEC) 무조작 시 "계속 이용하시겠어요?" 오버레이(4개국어).
- 오버레이에서 15초 더 무응답 → resetToVoice(홈 초기화, currentPatient·폼값 정리) → 다음 사람에게 이전 정보 안 남음. [계속하기]로 이어감.
- 서버 /config(GET, 공개)로 idleSec 노출 → 클라 로드 시 반영. showScreen마다 타이머 재무장 + click/keydown/touch로 유지.
- 검증: /config=45(env), Chromium 콘솔 에러 0.

## 2026-09-02 — [사이클6·B-7] 입력 검증·친절 안내 (ui-dev)
- submitPatientForm 형식 검증: 이름 필수, 주민번호 13자리, (초진)연락처 9~11자리.
- 오류 시 겁주는 빨간 대신 친절 안내(#form-msg, ℹ️ + 파랑 강조) + 해당 필드만 .invalid 표시 + 포커스 + 음성 안내(4개국어). 무엇을 어떻게 고칠지 예시 포함.
- 입력 중(input)엔 오류 표시 자동 해제.
- 검증: Chromium 콘솔 에러 0.

## 2026-09-02 — [사이클6·B-8] 로딩·전환 상태 (ui-dev)
- 로딩 오버레이(#loading-modal, 스피너+"확인 중입니다…" 4개국어). showLoading/hideLoading.
- 적용: /triage(LLM 대기·핵심), 초진 /patient/register, 재진 /reservation/check, /waitlist/add. finally로 항상 해제.
- 검증: 콘솔 에러 0.

## 2026-09-02 — [사이클6·C-9] 홈 화면 새 디자인 (ui-dev)
- 홈 박스를 .home-box(파랑 테두리 흰 카드+그림자)로: 큰 아이콘 + 파랑 제목 + 부제(접수=환자 등록·증상 접수 / 위치=진료과·시설 찾기, 4개국어).
- 기존 초록 테두리(--accent 흔적) 제거 → 블루 병원 톤 통일. 호버 primary-soft.
- 검증: 헤드리스 렌더 확인(깔끔·고대비·큰 터치).

## 2026-09-02 — [사이클6·C-10] 접수 입력 화면 새 디자인 (ui-dev)
- patient-form을 카드(흰 표면+테두리+그림자+패딩, max 560px)로. 입력 필드 min-height 64px·2px 테두리·focus-ring·--fs-base.
- 확인 버튼 파랑(primary) 큰 버튼(호버/눌림). form-note 잔글씨 토큰화.
- 검증: 콘솔 에러 0. (실제 화면 렌더는 D 통합 확인)

## 2026-09-02 — [사이클6·C-11] 증상·트리아지 결과 새 디자인 (ui-dev)
- 추천 진료과 chip 파랑 강조(.chip.primary, showRetry choice.primary 플래그). 다른 과는 일반 chip → 선택 명확.
- 면책 문구를 차분한 박스(surface-2 배경·둥근·패딩)로 — 눈에 띄되 위압적이지 않게.
- 증상 입력 필드/버튼 크게(min-height 64px, --fs-base, 파랑 버튼).

## 2026-09-02 — [사이클6·C-12,13,14] 응급·대기·admin 화면 다듬기 (ui-dev)
- C-12 응급: 직원호출 버튼 크게+그림자+은은한 펄스, 제목/서브 정리. 배경 danger-soft 점멸 유지.
- C-13 대기 순번: 순번을 파랑 강조 패널(primary-soft)로, 호출 시 초록 패널+초록 텍스트. 앞인원 굵게.
- C-14 admin: 탭 활성 파랑(primary-soft/primary), 대기 dept 헤더 파랑. 표·탭 가독성 위주(한국어 유지). 헤드리스 렌더 확인.
- 블루 톤 일관성: 정렬 활성/국기 활성/chip active의 초록 잔재를 파랑으로 통일.
- 검증: 콘솔 에러 0, admin 렌더 정상.

## 2026-09-02 — [사이클6·D-15,16] 전 흐름 화면 검증 (ui-dev)
- 내부 화면(폼/트리아지 추천/응급/대기)을 실제 CSS로 렌더한 미리보기로 확인: 카드·큰 필드·파랑 확인버튼, 추천 chip 강조+다른 과 선택+면책 박스, 응급(영어 긴 문장 줄바꿈 정상), 대기 순번(일본어) — 4개국어 레이아웃 안 깨짐.
- 발견/수정: 상단 스텝 인디케이터가 짧은 뷰포트에서 중앙 콘텐츠와 겹침 → 흐름 화면(form/intake/wait)을 상단 정렬+상단 여백(clamp 66~116px)으로 변경해 해소.
- 콘솔 에러 0(누적). 홈은 1920×1080 헤드리스 렌더 확인.
- D-16(실기기 1920×1080 전체화면 최종 조정)은 스케일 환경 특성상 사용자 실기기 확인 필요 → [~].

## 2026-09-02 — [사이클6·D-16 후속] 전체 크기 축소(화면 잘림 수정) (ui-dev)
- 사용자 실기기(스케일된 낮은 뷰포트)에서 UI가 커서 하단 잘림 → 토큰·히어로 요소 일괄 축소.
- 글꼴 토큰 하향(--fs-base 27→23, --fs-2xl 68→48, --fs-3xl 120→78 등), 히어로 축소(마이크 300→220, 순번 110→72, 응급아이콘 150→88, 제목류), 화면 gap·flow padding-top 축소.
- 홈 박스 min-height 420→360(42vh). 스텝-제목 간격 확보(padding-top 10vh).
- 검증: 실제 CSS로 홈/폼/증상추천/응급/대기 화면을 1920×640(낮은 높이)로 렌더 → 전부 잘림 없이 수용. 콘솔 에러 0. 로직·엔드포인트 무변경(CSS 토큰만).

## 2026-09-02 — [사이클6 후속2] 고배율(DPR) 실기기 화면 잘림 수정 (ui-dev)
- 원인: 실기기가 고DPR(≈2.5)이라 논리 뷰포트 높이가 매우 낮음(≈430px). 이전 검증(1920×640, DPR1)이 실조건 미반영이라 여전히 잘림.
- 수정: (1) .screen을 overflow-y:auto + justify-content:safe center → 콘텐츠가 뷰포트보다 커도 잘리지 않고 세로 스크롤. (2) 폼 필드/버튼 min-height를 vh 반영(clamp 44~60px)해 낮은 화면에서 축소. (3) 스텝 인디케이터를 absolute→in-flow로 바꿔 겹침/여백 하드코딩 제거.
- 검증: chromium --force-device-scale-factor=2.5 (실기기 조건)로 홈·폼·대기 렌더 → 세 화면 모두 잘림 없이 전부 표시. 콘솔 에러 0.

## 2026-09-02 — [사이클6 후속3] 흐름 화면 추가 축소(더 낮은 뷰포트 대응) (ui-dev)
- 실기기가 예상보다 더 큰 배율(≈DPR 2.6~2.7+ 또는 브라우저 줌)이라 폼/대기가 한두 요소만큼 넘쳐 여전히 잘림.
- 폼 카드 여백·필드·확인버튼·스텝·제목·간격, 대기 순번/문구를 추가 축소(터치 최소 42px 유지).
- 검증: --force-device-scale-factor=2.7(실기기 이상)로 폼·대기 렌더 → 하단 여백까지 확보하며 전부 표시. 콘솔 에러 0.
- 참고: 브라우저 줌이 100%가 아니면 더 커질 수 있음 → 사용자에게 Ctrl+0 확인 요청.

## 2026-09-02 — [사이클7·A] 진단(접수 화면 시각/토큰 점검) (ui-dev)
- 화면 전수 점검: 홈/초진·재진 폼/증상/트리아지결과/응급/대기/admin + 인접(listening/result/moving).
- 토큰 미준수 발견:
  - 타이포: var(--fs-*) 12회 vs font-size 선언 35+ → 대부분 자체 clamp/min. 제목류 화면마다 값 제각각(위계 불일치). ★최우선.
  - 간격: var(--sp-*) 1회. admin·dev-input 등 px 리터럴 산재(세로 리듬 없음).
  - 반경: 999px/8px/12px/4px/2px 리터럴(--radius-pill/sm 미적용).
  - 색(rgba 하드코딩): mic글로우/응급그림자/admin호출행/result하이라이트(다른 빨강)/route dot(다른 파랑)/오버레이/drop-shadow. admin 섹션 헤더 3색 제각각(accent-strong/blue-strong/primary).
- 합의된 우선순위: (1)전역 토큰 정착(타이포·간격·반경) → (2)색 규칙 통일 → (3)admin 정리 → (4)화면별 위계.
- 기능(트리아지·대기·PIN·다국어)은 불변. 백업 태그 cycle7-base 생성.

## 2026-09-02 — [사이클7·B-6] 타이포 위계: --fs-* 스케일 정착(주요 화면) (ui-dev)
- --fs-* 스케일을 vw+vh 동시 반영 min()으로 재정의(낮은 뷰포트 자동 축소, 잘림 방지 유지).
- 홈/음성/대기/응급/듣는중/재질문/결과·이동의 제목·본문·라벨·버튼 font-size를 자체 clamp→ var(--fs-*)로 수렴(20곳). 히어로(마이크·순번·응급아이콘·로봇·층배지)는 커스텀 유지.
- 검증: DPR 2.7로 폼·대기·응급·홈 렌더 → 잘림 없이 위계 명확. 콘솔 0. 기능 불변.
- admin 타이포는 3순위(admin 정리)에서 간격·색과 함께 수렴 예정.

## 2026-09-02 — [사이클7·B-5] 색 사용 규칙 통일 (ui-dev)
- 규칙: 주색(파랑)=핵심 액션, 빨강=응급/삭제/타깃, 초록=성공(호출/완료)만, 회색=부차.
- 핵심 액션을 파랑으로: 마이크 버튼(그라디언트+글로우), 듣는중 파형, 결과 "네"(안내 시작), 결과 배너 장소명.
- 하드코딩 rgba를 토큰 색으로 통일: 결과 방 하이라이트→--danger 톤(209,47,47), route dot·admin 호출행→--primary(23,99,201).
- admin 섹션 헤더 3색(초록/파랑/파랑) → --primary로 통일. 남은 rgba는 그림자·오버레이(중립)뿐.
- 초록(--accent/--success)은 호출됨·완료·대기 성공 상태에만 유지. 콘솔 0. 기능 불변.

## 2026-09-02 — [사이클7·B-4,B-7,C-11] 간격·반경 토큰화 + admin 정돈 (ui-dev)
- 반경(B-7): chip/파형 999px→--radius-pill, lang-flag/admin 입력·버튼·탭·삭제·호출행 8px/12px→--radius-sm(계열). 공통 요소 반경 통일.
- 간격(B-4): admin 탭/정렬/폼/목록·dev-input의 px 리터럴(8·10·12·14·16·4)→--sp-*로 수렴(세로/가로 리듬 통일).
- admin 타이포(C-11, B-6 이월분): 탭·정렬·입력·목록·헤더·버튼 font-size→--fs-* 스케일.
- 색 규칙 마저: admin 예약저장 버튼 --accent(초록)→--primary(핵심 액션=파랑), admin-act.call --blue→--primary, admin-resv-label 초록→파랑.
- 검증: admin 렌더(탭·정렬·목록·삭제) 일관 확인, 콘솔 0. 기능 불변.

## 2026-09-02 — [사이클7·C-8,9,10] 화면별 위계·CTA 정리 (ui-dev)
- C-9(스텝+제목 일관): 스텝 인디케이터(in-flow 상단)+제목(--fs-xl)이 모든 흐름 화면에서 동일 위계로 맞물림.
- C-10(CTA 분명): 주 액션=파랑 채움(확인/네/예약저장/호출), 보조=고스트/아웃라인. 보조 CTA(.btn-secondary '위치 안내') 테두리 초록→파랑 통일. 홈 개발버튼·이동경로 지나온 점도 주색으로.
- 색 규칙 최종: 파랑=모든 핵심/보조 액션, 빨강=응급·삭제·타깃, 초록=완료(admin '완료')만, 회색=부차. --accent(초록) 잔여 1곳(admin-act.done)만.
- C-8(화면당 목적): 초진 폼 3필드는 한 목적(본인 정보)이라 분할 안 함(단계 과다 방지). 카드 단일 목적 유지.
- 콘솔 0. 기능 불변.

## 2026-09-02 — [사이클7·D] 검증 (ui-dev)
- 실기기 배율(--force-device-scale-factor=2.7)로 홈·초진폼·트리아지추천·응급·대기·admin 렌더 → 전부 잘림 없이 위계·색·타이포 일관.
- Chromium 콘솔 에러 0(누적). 기능 무회귀(triage 응급/일반, 대기 순번, PIN, 다국어 라벨) 확인.
- before/after: before=cycle7-base 태그(+사용자 잘림 스크린샷), after=본 세션 DPR2.7 렌더(scratchpad d_*/b6_*/c11_*). 주 개선: 색 규칙(파랑=액션/빨강=응급·삭제/초록=완료), 타이포 --fs-* 스케일 위계, 간격·반경 토큰 통일, admin 정돈.
- 백업 태그 cycle7-done 생성.

## 2026-09-02 — [사이클7 후속] 국기 언어 선택 접이식 (ui-dev)
- 평소 접힘: 현재 언어 국기 1개만(우상단) + 작은 ▾ 힌트. 터치 시 .lang-bar.open → 세로로 4개국 국기 펼침.
- 펼침 상태에서 국기 선택 → setLang + 접힘. 바깥 클릭 시 닫힘. 국기 버튼은 카드형(테두리·그림자), 선택된 것 파랑 강조.
- 로직·다국어 무변경(UI 상호작용만). 검증: 접힘=국기 1개, 펼침=세로 4개, 콘솔 0.

## 2026-09-07 — [사이클7 후속] 국기 펼침 시 카드 겹침 해소 (ui-dev)
- 펼친 국기 목록을 불투명 드롭다운 패널(흰 배경·테두리·그림자)로 감싸 카드 위에 깔끔히 뜨게 함. 개별 국기는 패널 안에서 테두리 없이(선택된 것만 파랑 강조).
- 국기 크기 소폭 축소(clamp 20→17..24), z-index 6→20.
- 홈 메뉴 폭 min(86vw→82vw,700px)로 좁혀 좁은 뷰포트(고DPR)에서 우상단 국기 영역과 좌우 간격 확보.
- 로직·다국어 무변경(CSS만). 검증: 실기기 조건(DPR 2.7, 논리뷰포트 711×400) 렌더 — 접힘/펼침 모두 카드와 겹침 없음, 콘솔 0.

## 2026-09-07 — [후속2] 국기 겹침 실기기 재확인·홈메뉴 폭 추가 축소 (ui-dev)
- 실기기(논리뷰포트 ~780px, DPR≈2.4)에서 82vw로도 카드 우상단이 국기 패널 밑으로 살짝 들어감.
- 홈 메뉴 폭 82vw→76vw: 뷰포트 무관 좌우 12vw 여백 확보 → 국기 드롭다운과 항상 분리.
- 검증: 780·860px 뷰포트 렌더 모두 카드-패널 명확 분리, 겹침 없음.

## 2026-09-07 — [사이클7 B·#1] 증상입력 필드 룩 통일 (ui-dev)
- 증상입력 폼(#intake-form input)이 개발용 dev-input 룩(1px 얇은 테두리)을 상속 → 초진 폼 필드와 불일치였음.
- #intake-form input을 초진 폼과 동일하게: 2px --border 테두리 + --radius + --surface 배경 + 포커스 링(--focus-ring) + .invalid(--danger) 상태. 버튼도 --radius 명시.
- CSS만(HTML/JS 무변경). 검증: DPR1 전체화면 렌더에서 증상필드=초진필드 룩 일치·깨짐 없음. /triage 일반(internal)·응급(emergency) 정상, 콘솔 0.

## 2026-09-07 — [사이클7 B·#3] 결과/선택 화면 위계 — 스텝 연결 (ui-dev)
- retry-screen이 접수 트리아지 결과로 쓰일 때 스텝 인디케이터가 없어 "지금 무슨 단계" 흐름이 끊김(폼·증상입력·대기엔 있음).
- HTML: retry-screen 상단 #retry-steps 추가. JS: showRetry에 stepIdx 인자(기본 없음). 트리아지 추천/애매 두 결과만 stepIdx=1(증상) 전달 → 스텝(정보✓→증상 현재→완료) 표시.
- 위치 안내 흐름(인식실패·재질문)·초진/재진 선택은 인자 미전달 → 스텝 비움(기존 그대로).
- 트리아지 판단 로직·i18n 문자열 불변(제시 구조만). 검증: DPR1 결과화면 위계 렌더 확인, 라이브 콘솔 0, app.js 정상 로드, /triage 정상.

## 2026-09-07 — [사이클7 B·#2] admin 실버그 수정 + 정돈 (ui-dev)
- 실버그: 날짜 입력 color-scheme:dark → light (라이트 UI와 달력 위젯 불일치 해소).
- 예약폼 입력 배경 --bg→--surface, 테두리 --surface-2→--border. 예약 등록 폼 카드 테두리(--border) 추가로 영역 구분.
- 하드코딩 간격 토큰화: sort-btn 5px14px→sp-1 sp-3, li padding 3~4px→sp-1·gap 10px→sp-2, admin-acts gap 6px→sp-1.
- 호출됨(called) 행 강조: rgba 리터럴→--primary-soft + 좌측 4px --primary 액센트(PLAN11 호출 상태 부각).
- CSS만(PIN·정렬·대기 로직 무변경). 검증: DPR1 admin 렌더(달력 라이트·호출행 강조·색규칙), 콘솔 0, 보호 엔드포인트 무인증 403 유지.

## 2026-09-07 — [사이클7 B·#4] 잔여 하드코딩 색 → 토큰화 (ui-dev)
- tokens.css에 rgb 채널 토큰 추가: --primary-rgb / --danger-rgb / --danger-strong-rgb. --focus-ring도 rgba(var(--primary-rgb),.45)로.
- style.css 치환: 마이크 펄스(micpulse), 응급버튼 그림자, 지도 하이라이트(배경/테두리=danger 채널), 경로점(route-dot)=primary 채널. map-wrap 그림자 rgba(0,0,0,.35)→var(--shadow-lg)(라이트 테마 톤).
- 의도적 유지: 로봇 마커 드롭섀도우·모달 스크림(테마색 아닌 대비/딤 용도).
- CSS/토큰만. 검증: rgba(var(--x-rgb)) 치환 스와치 렌더 확인(파랑/빨강/펄스/포커스링 정상), 콘솔 0.

## 2026-09-07 — [사이클7 B·#5] 잔여 자잘한 간격 px → 토큰 (ui-dev)
- disclaimer/form-note 마진 4px → var(--sp-1)(=4px, 값 동일·토큰화만).
- 유지(의도값): ▾ 힌트 margin-top -2px(미세 정렬), step gap 6px(토큰과 불일치—바꾸면 간격 변형), step-sep radius 2px(헤어라인), 테두리 두께·clamp 하한.
- CSS만. 검증: 콘솔 0. 시각 변화 없음.

## 2026-09-08 — [사이클8 A] AI 대화형 문진 — 서버 엔드포인트 (ui-dev)
- 백업: 태그 cycle8-base + backup/cycle8-base.
- A-2 프롬프트 확정(꼬리질문 최대 2개=총 3턴, 진단·병명·약 금지, 응급 시 멈춤, 환자 UI 언어 출력).
- kiosk_server.py 추가(무상태, 클라가 messages 전체 전송):
  · POST /interview → interview_next(): (a) 매 답변 is_emergency() KTAS 선검사(LLM 前) → 응급 즉시 {action:"emergency"} (b) assistant≥2 상한 → {action:"done"} (c) 그 외 LLM(_openai_text, 자유출력) → JSON {action:ask/done/emergency}. 파싱 실패·무효·LLM off → 안전하게 done.
  · POST /interview/summarize → interview_summarize(): 환자발화 합쳐 is_emergency 재확인 → _triage_match(기존 재사용)로 진료과 id + LLM으로 한국어 요약(summary_ko) + 환자언어 리캡(recap). 실패 시 발화 원문 폴백.
  · 헬퍼: _openai_text / _parse_json_obj(코드펜스·잡텍스트 허용) / _transcript / _patient_texts / _last_user_text / _interview_prompt. MAX_FOLLOWUPS=2.
- 재사용: is_emergency(A-3), _triage_match(A-4), _openai_classify 호출패턴, gpt-4o-mini. 기존 /triage·대기·PIN·다국어 무변경.
- 검증: (오프라인, LLM 무) 응급 4개국어 대화중 즉시 감지·상한→done·LLM off 폴백→done·종합 비응급/응급·JSON 파서 견고성 전부 PASS. (실LLM) 1·2턴 유효 JSON·자연질문, 진단회피 OK, 영어입력→영어질문, 종합 internal+한국어요약+리캡 확인. py_compile OK.
- ⚠️ 서버 코드 변경 → 반영하려면 start_ui.sh 재시작 필요(정적 파일 아님).

## 2026-09-08 — [사이클8 B] AI 대화형 문진 화면 (ui-dev)
- intake-screen을 채팅형으로 개조: #interview-log(말풍선 로그, 자동 스크롤) + 통일된 입력창 + "이대로 접수하기"(항상 표시) + 뒤로/처음으로. intake-q·wave 제거.
- app.js: askSymptom/listenSymptom/handleSymptom(단일입력+즉시 트리아지) 제거 → 대화형 함수로 교체:
  · startInterview(): msgs 초기화, 첫 질문(symptomQ, UI 전용) 표시. (첫 질문은 서버 messages에 안 넣어 꼬리질문 상한 2가 "첫 질문 뒤 최대 2"로 정확)
  · submitAnswer(): 응급 클라 선검사 → /interview → ask(말풍선+음성)/done(종합)/emergency(응급화면). interviewBusy로 중복 방지.
  · finishInterview(): /interview/summarize → 추천과+요약+리캡. 실패 폴백(발화 원문).
  · showInterviewResult(): retry 화면 재사용 + 리캡 박스. 추천 강조칩/대안/다시 문진. 대기명단 증상=한국어요약 우선.
- showRetry에 recap 5번째 인자(=#retry-recap). 기존 호출은 recap 없음→빈칸(숨김).
- 초진·재진(예약없음) 진입을 startInterview로. intake-form 제출→submitAnswer. 로딩 스피너 기존 재사용.
- CSS: .chat-log/.chat-msg(ai·me 말풍선)/.interview-recap(토큰만).
- i18n: 'interview.finish' 4개국어 추가.
- 검증: 잔여 참조 없음, 라이브 콘솔 0(app.js 파싱), 채팅·결과 화면 DPR2.4(실기기) 렌더 정상.
- ⚠️ 서버(A)·클라(B) 모두 변경 → start_ui.sh 재시작 필요. 재시작 후 전 흐름 확인 요망.

## 2026-09-08 — [사이클8 A-2 개선] 문진 질문 품질 향상 (ui-dev)
- 문제: gpt-4o-mini가 겉도는/재질문(예: '머리 아파요' 후 부위 재질문) 경향.
- _interview_prompt 개선: (1) 진료과 목록 제시 + '진료과 구분·위험신호에 결정적인 정보 우선순위'(동반증상→발병경과→대상→외상/임신/만성) (2) 이미 말한/자명한 정보 재질문 절대 금지 명시 (3) 진료과 분명해지면 세부 그만 캐고 done, 무의미 세부(두통 앞/뒤 위치 등) 금지 (4) 좋은/나쁜 질문 few-shot (5) 남은 질문 수(remaining) 주입해 마지막엔 결정적 질문.
- 검증(실LLM): 두통→동반증상→(정보충분)done, 배→부위, 무릎→외상vs만성, 아이열→동반, 베임→상처상세, 생리→동반 등 전부 진료과 구분형 질문. 진단회피·응급 중간감지 정상. py_compile OK.
- ⚠️ 서버 변경 → start_ui.sh 재시작 반영.

## 2026-09-08 — [사이클8 A-2 재개선] 확정 시 조기 종료 (ui-dev)
- 문제: 증상이 이미 진료과 확정 가능한데도(예: '발목 접질림'=외과) 질문을 이어감.
- _interview_prompt: 기본 동작을 '질문'→'마침(done)'으로 뒤집음. 질문은 (1)답이 모호 (2)진료과 2개 이상 가능 (3)위험신호 확인 필요일 때만. 첫 답변으로 진료과 분명하면 즉시 done(예시 추가). 확신 시 남은 질문 있어도 done.
- 검증(실LLM): 확정(발목접질림·만성무릎·베임·생리불규칙)→모두 done, 모호(배·몸안좋음·아파요·어지러움)→적절한 질문. 경계(허리 삐끗)만 1질문. py_compile OK.
- ⚠️ 서버 변경 → start_ui.sh 재시작 반영.

## 2026-09-08 — [사이클8 C] 증상 요약 대기명단 연결 (ui-dev)
- waitlist.json 현재 구조 확인: {queues:{dept:[entry]}, counters:{dept:int}}, entry={id,ticket,name,rrn_masked,visit_type,symptom,status,added_at,called_at}.
- C-8: entry에 symptom_summary(한국어 요약) 전용 필드 추가(하위호환, 없으면 ''). waitlist_add·/waitlist/add·클라 addToWaitlist에 인자 배선. 문진 흐름: symptom=짧은 주증상(첫 발화), symptom_summary=종합 한국어 요약. 예약 재진은 요약 ''(→symptom 폴백).
- C-9: admin 대기현황 각 항목에 '📝 요약' 줄 표시(.wait-info/.wait-summary). 요약 없으면 symptom 폴백.
- 검증: py_compile OK, 임시파일로 waitlist_add 요약 저장/폴백 확인, admin 요약 렌더 확인, 라이브 콘솔 0. 기존 대기/호출/삭제·PIN 무변경.
- ⚠️ 서버+클라 변경 → start_ui.sh 재시작.

## 2026-09-08 — [사이클8 D] 안전·검증 (ui-dev)
- D-10 응급 우회: LLM OFF(=규칙기반 증명) 상태에서 4개국어(ko/en/ja/zh) × (1턴/대화중간) 모두 즉시 emergency. 종합 단계 응급 방어도 PASS.
- D-11 진단 회피(실LLM): 4개국어 진단/약 질문 → 진단·병명·약 단어 없이 종료→접수 라우팅. 중간 진단질문도 진단 안 함.
- D-12 중단: 빈 대화/1발화 종합 무크래시. "이대로 접수하기"=finishInterview 즉시 종합.
- D-13 HTTP 레벨(임시 신규 서버 8011): /interview(ask·중간응급), /interview/summarize(발목→외과+한국어요약+리캡), /triage 회귀, /config 정상. (/waitlist 200은 임시 인스턴스 PIN 미설정 탓; 프로덕션은 403 확인됨.)
- 화면(전체화면 조건): 채팅·결과+리캡·admin 요약을 DPR1/DPR2.4 렌더로 확인(앞 기록). 실기기 클릭 전 흐름은 start_ui.sh 재시작 후 사용자 확인 권장.
- 회귀: _triage_match(내과/외과)·is_emergency 무변경, waitlist_add 하위호환 확인.

## 2026-09-08 — [사이클9] UI 분위기: 따뜻한 신뢰 (tokens.css만) (ui-dev)
- 백업: cycle9-base / backup/cycle9-base / backup/cycle9-tokens-pre + before/tokens.before.css.
- A: 현재 값 정리(차가운 코발트 primary·블루그레이 bg·네이비 text·파랑틴트 그림자가 딱딱함 주범). before 5화면(home/form/interview/result/wait) DPR1 저장.
- B-3 색: bg #eef3f9→#f4f1ea(웜 오프화이트), surface #fff→#fffdf8, surface-2 #e3ebf4→#ece6db, border #cdd9e8→#d6cdbf, text #16202e→#29231c(웜 차콜), text-dim #556579→#6a6156, primary #1763c9→#2b6ca0(부드러운 스카이-틸), primary-strong #0f4ea3→#1f5680, primary-soft #e6f0fb→#e6eef4, primary-rgb 43,108,160. success/danger 유지(soft만 살짝 웜). 대비 전 조합 ≥4.5(계산 검증).
- B-4 반경: 8/16/24 → 10/20/28. B-5 그림자: 웜 틴트 rgba(60,48,36,·) + 넓고 옅게.
- B-6: tokens.css 값 교체만. style.css 하드코딩 hex 잔재 없음(전부 토큰 참조) → 전 화면 자동 재테마. dead 토큰(--blue-strong 등)은 미사용이라 무변경.
- C: 대비 재확인(≥4.5), 크기 토큰 무변경(고령친화 유지), after 5화면 렌더(scratchpad/after), 라이브 콘솔 0. 레이아웃·기능·다국어 무변경(CSS만).
- ⚠️ CSS만 → 서버 재시작 불필요, 강력 새로고침으로 반영.

## 2026-09-08 — [버그수정] 재진 본인확인 누락 (ui-dev)
- 문제: 재진 시 환자 데이터셋(patients.json) 등록 여부를 확인하지 않고, 예약만 조회 후 미등록/정보 불일치 환자도 그대로 접수됨.
- 서버: patient_check(name, rrn) 추가 — rrn_hash로 데이터셋 조회 → {found, nameMatch}(이름은 공백무시·소문자 정규화 비교, 개인정보 미반환). 엔드포인트 /patient/check(환자용, PIN 불필요).
- 클라: 재진 흐름에서 예약 조회 '전에' /patient/check 호출 → 미등록(errNotRegistered)·이름 불일치(errNameMismatch)·조회 실패(errCheckFailed)면 접수 차단(해당 필드 강조+포커스). 통과해야 예약/문진 진행. 에러 문구 4개국어.
- 초진 흐름·트리아지·대기·PIN·다국어 무변경.
- 검증: py_compile OK, patient_check 오프라인(일치/공백차이/이름틀림/미등록/짧은주민) 전부 PASS, /patient/check HTTP 라우팅 200, 클라 콘솔 0.
- ⚠️ 서버+클라 변경 → start_ui.sh 재시작 필요.

## 2026-09-08 — [보정] 재진 주민번호 입력 마스킹 (ui-dev)
- 재진 폼에서만 주민번호 뒷자리를 성별자리 1개 빼고 * 처리(예: 900101-1******). 실제 숫자는 f-rrn.dataset.rrn에 보관→조회에 사용. 초진·admin 데이터셋(간호사 관리)은 평문 유지.
- app.js만: rrnMaskFormat/setRrnMask/rrnFieldValue + f-rrn beforeinput 핸들러(insertText·delete·paste 가로채 dataset 갱신, 마스킹 표시, 13자리 상한·비숫자 무시). startPatientForm는 재진이면 setRrnMask(true), submitPatientForm은 rrnFieldValue()로 실제 숫자 사용.
- 검증: 합성 이벤트(실브라우저)로 입력/삭제/초과/비숫자 마스킹 정확, 실제숫자 보존 확인. 라이브 콘솔 0. 서버·HTML·CSS·기능·다국어 무변경.
- CSS/정적만(app.js) → 서버 재시작 불필요, 강력 새로고침으로 반영(단, 직전 patient_check 서버변경 미반영 시 재시작 필요).

## 2026-09-08 — [보정2] 재진 주민번호 앞7자리만 입력(뒷6자리 고정 *) (ui-dev)
- 요청: 재진 시 앞 6자리+뒤 첫자리(성별)=7자리만 입력, 뒷 6자리는 처음부터 *.
- 식별 모델 변경: 재진은 전체 13자리 해시가 아닌 **앞7자리 마스킹값(900101-1******) + 이름**으로 대조.
  · 서버: _rrn_masked_from() 추가. patient_check/reservation_check를 마스킹값+이름 스캔으로. 예약 소비 reservation_clear_match(마스킹+이름). waitlist_add 마스킹 통일(_rrn_masked_from or _rrn_mask)로 초진(13)·재진(7) 모두 900101-1******. /reservation/check에 name 전달. reservation_clear(해시)는 admin용 유지.
  · 클라: 재진 입력 7자리 상한(rrnMaskFormat/beforeinput slice 7). 재진 검증 7자리(errRrnRevisit). 재진 플레이스홀더(ph.rrnRevisit). /reservation/check에 name 포함. 초진은 기존대로 전체 13자리 입력·평문.
- 한계(수용): 생년월일+성별+이름이 모두 같은 동명이인은 구분 못 함(키오스크 수준 허용).
- 검증: 초진등록→재진 7자리 조회/이름틀림/미등록/부족, 예약 7자리 조회·소비, 대기 마스킹 통일, 초진 마스킹 동일 — 오프라인 전부 PASS. 클라 7자리 마스킹(합성 이벤트)·재진 폼 렌더·라이브 콘솔 0.
- ⚠️ 서버+클라 변경 → start_ui.sh 재시작 필요.

## 2026-09-08 — [보정3] 주민번호 세그먼트 입력(숫자당 한 칸) + * 미리 표시 (ui-dev)
- 요청: 초진·재진 모두 주민번호를 숫자당 한 칸으로 입력. 재진 뒷 6칸의 *는 처음부터 표시(갑자기 안 나타나게). 전화번호 칸은 그대로.
- HTML: #f-rrn 를 <input>→<div class="rrn-seg"> 컨테이너로. JS가 칸 생성.
- app.js: 마스킹(단일입력·beforeinput) 방식 제거 → 세그먼트 컴포넌트. buildRrnCells(editable, digits): 13칸 중 앞 editable(초진13/재진7)은 input, 나머지는 * 고정 span(미리 표시), i===6 뒤 하이픈. input 시 숫자 1자리·자동 다음칸 이동, 빈 칸 Backspace는 이전 칸. 값은 f-rrn.dataset.rrn(초진13/재진7). setRrnMask(on)=editable 7/13. rrnFieldValue=dataset. showFormError는 f-rrn이면 첫 빈 칸 포커스.
- CSS: .rrn-seg/.rrn-cell/.rrn-star/.rrn-sep(토큰). .patient-form input 규칙을 이기도록 .rrn-seg 하위로 스코프(padding:0 등). 전화번호 등 다른 입력 무영향.
- 검증: 초진 13자리·재진 7자리 dataset 수집, 자동 이동, 별칸 6개 미리 표시(합성 이벤트) 확인. 초진/재진 폼 렌더 정상(카드 내 수용, 전화칸 그대로), 라이브 콘솔 0.
- 클라(정적)만 → 서버 재시작 불필요, 강력 새로고침.

## 2026-09-08 — [보정4] 초진 전화번호 자동 하이픈 (ui-dev)
- 요청: 초진 전화번호에 -를 일일이 안 찍어도 자동 생성(010-1234-5678).
- app.js: formatPhone(3-4-4, 최대 11자리) + onPhoneInput(입력 시 자동 포맷 + 커서 위치 보정). f-contact input 리스너로 연결(기존 오류표시 해제도 겸함).
- 검증: 순차 타이핑 11자리→010-1234-5678, 7자리→010-1234, 12자리 상한, 포맷 케이스 확인. 라이브 콘솔 0. 검증 로직(숫자 9~11자리) 무변경.
- 클라(정적)만 → 서버 재시작 불필요, 강력 새로고침.

## 2026-09-08 — [보정5] 대기열 비면 순번 리셋 + 테스트 데이터 정리 (ui-dev)
- 증상: 앞 0명인데 순번 5번(이전 테스트로 counter만 증가한 잔재).
- 데이터 정리: waitlist.json 큐·카운터 초기화(백업 scratchpad/data_backup). patients(2명)·reservations 유지.
- 개선: waitlist_remove(완료 포함)에서 해당 진료과 대기열이 비면 counters[dept]=0 + 빈 큐 키 정리 → 다음 접수부터 1번. 대기 중일 땐 카운터 유지(앞사람 수와 어긋나지 않음).
- 검증: 순차 1,2 / 일부삭제 후 3 / 전부 비면 리셋→1 / 완료 후 리셋→1 오프라인 PASS. py_compile OK.
- ⚠️ 서버 변경 → start_ui.sh 재시작 필요(데이터 초기화는 이미 반영).

## 2026-09-08 — [보정6] admin 환자 데이터셋 전체 주민번호 표시(암호화 저장) (ui-dev)
- 요청: 의료진이 확실히 알도록 admin 환자 데이터셋에선 주민번호에 * 없이 전체 표시.
- 정책: 평문 저장 금지 유지. 전체 주민번호는 기기 로컬 키(.rrn_key, gitignore)로 암호화(rrn_enc)해서만 저장, PIN 인증 admin 조회 때만 복호화 표시. 공개 화면·매칭엔 여전히 rrn_masked/rrn_hash 사용.
- 서버: 표준 라이브러리 HMAC-SHA256 CTR + encrypt-then-MAC(_rrn_encrypt/_rrn_decrypt, .rrn_key 자동생성 0600). patient_register가 rrn_enc 저장(초진 13자리, 재등록 시 backfill). patient_list가 rrn_full(복호화, 900101-1234567) 포함 — /waitlist(GET, PIN 보호)로만 전달.
- 클라: renderPatients가 rrn_full 있으면 표시, 없으면 rrn_masked 폴백.
- 한계: 재진은 앞7자리만 받으므로 전체 저장은 초진에서만. 기존 2명은 rrn_enc 없어 마스킹(재등록 시 backfill). 키가 기기에 있어 기기 통째 탈취 시엔 복호 가능(파일만 유출 시엔 보호).
- 검증: 암호화 왕복·변조 None·키불일치 None, 저장파일 평문 없음·rrn_enc 존재, patient_list rrn_full 전체, admin 렌더(전체/마스킹 폴백), 콘솔 0, py_compile OK.
- ⚠️ 서버+클라 변경 → start_ui.sh 재시작. 첫 admin 로드 시 .rrn_key 자동 생성.

## 2026-09-11 — [사이클10 A·B] 진료 상태 흐름 + 의사/콜보드 서버 (ui-dev)
- 백업: cycle10-base + backup/cycle10-base. 결정: 콜보드 순번만·전과, 소프트완료, 의사=ADMIN_PIN 공통.
- 상태 흐름: waiting→called→in_progress→done. 헬퍼 _ACTIVE/_is_active/_ahead_count(진료중 포함)/_reset_counter_if_idle(활성0시 순번 리셋).
- entry 확장(하위호환): memo·in_progress_at·done_at(+memo_at). 기존 entry는 .get 기본값으로 안전.
- 완료=소프트: waitlist_done이 삭제 대신 status=done+done_at 보존. waitlist_remove(하드)는 간호사용 유지, 둘 다 활성0시 카운터 리셋.
- 신규: waitlist_start(in_progress), waitlist_memo, doctor_queue(과별 active/done+요약·메모), callboard_data(전과 호출/진료중 순번만·PII 없음).
- 엔드포인트: POST /waitlist/start·/waitlist/memo(ADMIN_PATHS 추가), GET /doctor/queue?dept=(PIN), GET /callboard(공개). 환자 /waitlist/status는 status만 전달(메모 미노출).
- 검증: 오프라인 15케이스(전환·소프트완료·ahead·메모·의사조회·콜보드 키=ticket/status만·PII 없음·순번리셋) 전부 PASS. HTTP(임시서버): 콜보드200·의사조회 403/200·start/memo 403·status 200. py_compile OK.
- ⚠️ 서버 변경 → 클라(C·D) 완료 후 start_ui.sh 재시작.

## 2026-09-11 — [사이클10 C·D] 의사 화면 + 콜보드 + 3화면 연동 (ui-dev)
- 의사 admin(신규, ?doctor=1): 기존 PIN 게이트 공통 재사용 → 진료과 선택(내과/외과/산부인과/소아/통증) → 대기목록. 각 카드: #순번·이름·주민(마스킹)·초/재진·상태 + 증상요약 + 메모 textarea. 버튼 [재호출]/[진료 시작]/[완료]. "오늘 완료" 접이 목록(메모 읽기). 3초 폴링, 자동잠금(lockAdmin) 공용(의사 폴링도 정지).
- 콜보드(신규, ?callboard=1): 공개, /callboard 폴링(2.5초) → 진료과별 호출/진료중 '순번만' 대형 표시. PII 없음. 빈 상태 안내.
- 간호사 admin: 대기 목록에 진료중(🩺)/완료(✅) 배지 + 스타일. 헤더 인원=활성 기준. 완료(보존) 항목은 호출/완료 버튼 숨김(삭제만).
- 환자 대기화면: in_progress → "🩺 진료 중" 표시(차분한 강조). 소프트완료(status=done)도 완료 처리(감사 인사, 폴링 정지).
- CSS: 의사 카드/버튼/메모, 콜보드 대형 순번, 환자 in-progress, 간호사 배지(토큰만).
- 검증: 라이브 콘솔 0(dev/doctor/callboard/admin), 의사·콜보드 화면 렌더 확인. (서버 로직·엔드포인트는 A·B에서 검증)
- ⚠️ 서버+클라 변경 → start_ui.sh 재시작 후 실기기 전 흐름 확인.

## 2026-09-11 — [사이클10 E] 통합 검증 (ui-dev)
- HTTP 엔드투엔드(임시서버, 데이터 백업/복원): 접수→환자status(waiting)→호출→콜보드(순번만)→진료시작→메모→의사조회(요약·메모)→환자status(in_progress, 메모無)→완료(소프트)→의사조회(active0/done1 메모보존)→환자status(done). 전부 정상.
- 접근통제: PIN 없이 /doctor/queue·/waitlist/memo → 403. 환자 /waitlist/status 응답에 메모·요약 없음(waiting/in_progress/done 모두 확인). 콜보드 PII 없음.
- 무회귀: 라이브 콘솔 0(dev/doctor/callboard/admin). 문진·트리아지·환자검증·주민마스킹/암호화 등 기존 로직 무변경. 실기기 키오스크 전체화면 전 흐름은 재시작 후 사용자 확인 권장.
- 백업: cycle10-done.

## 2026-09-11 — [사이클10 보정] 의사 진료과 목록을 전 진료과로 (ui-dev)
- 문제: 의사 화면 진료과가 트리아지 5개만(하드코딩) 노출.
- 수정: DOCTOR_DEPTS를 LOCATIONS에서 화장실만 제외해 동적 구성 → 7개(산부인과·영상의학과·마취통증의학과·진단검사의학과·내과·외과·소아청소년과). 예약으로 다른 과 대기열에 생긴 환자도 담당 의사가 볼 수 있음.
- 클라(app.js)만. 검증: ?doctor=1 콘솔 0, 진료과 버튼 7개 렌더 확인.

## 2026-09-11 — [사이클10 보정2] 콜보드에 마스킹 이름 추가 (ui-dev)
- 요청: 콜보드 호출 시 환자 이름도 표시. 공용 화면이라 전체 이름 대신 가운데 마스킹(홍길동→홍*동)으로.
- 서버 _mask_name() 추가(2글자 김*, 3글자 홍*동, 4+글자 남**수, 영문 J**n). callboard_data 항목에 name(마스킹)만 포함 — 전체 이름은 공개 엔드포인트로 안 나감.
- 콜보드 렌더: 순번 + 마스킹 이름 + 상태. CSS .callboard-left/.callboard-name.
- 검증: 마스킹 로직·콜보드 렌더·콘솔 0. (전체 이름 원하면 _mask_name만 교체)
- ⚠️ 서버+클라 변경 → start_ui.sh 재시작.

## 2026-09-11 — [응급필터 정밀화] 과민 오탐 축소 (ui-dev)
- 문제: 가벼운 표현도 응급으로 오탐(배가 너무 아파/머리가 깨질·터질/피가 많이/반신(욕)/숨이 안·막/마비(감) 등).
- 조치: 너무 넓은 키워드를 구체화 — 제거/좁힘: "배가 너무 아파","머리가 깨질","머리가 터질","피가 많이","숨이 막" 삭제; "숨이 안"→"숨이 안 쉬"; "반신"→"반신마비/반신불수"; 바 "마비"→"몸이 마비/마비가 왔/마비됐/마비돼". 일본어 "半身"→"半身麻痺/半身不随". "응급·위독"은 접수 문맥 안전측이라 유지.
- 검증: 가벼운 문장 오탐 10→1(드문 비유 "숨이 안 쉬어질 만큼 웃었어요"만), 진짜 응급 0건 놓침, 4개국어(en/ja/zh) 응급 유지. py_compile OK.
- ⚠️ 서버 변경 → start_ui.sh 재시작. 트리아지·문진 양쪽 is_emergency에 적용됨.

## 2026-09-11 — [응급 기능 제거] (ui-dev)
- 요청: 응급 기능 자체 제거(오탐 문제).
- 비활성화(되돌리기 쉽게, 코드/키워드는 보존): 서버 is_emergency()→항상 False, interview_next의 LLM 응급 액션 처리 삭제, 문진 프롬프트의 응급 지시·출력 제거. 클라 isEmergency()→항상 false.
- 결과: 트리아지·문진·종합 어디서도 응급 화면으로 분기하지 않음. 과거 응급 문구도 정상 접수 흐름으로 진행.
- 잔존(미사용, 필요시 완전 삭제 가능): emergency-screen 섹션·showEmergency·emgCallStaff, EMERGENCY_KW/_EMERGENCY_KW.
- 백업 태그: pre-remove-emergency. 검증: is_emergency 전부 False, interview 응급 액션 없음, summarize emergency False, 콘솔 0, py_compile OK.
- ⚠️ 서버+클라 변경 → start_ui.sh 재시작.

## 2026-09-17 — [start_all에 UI 환경 이식] (ui-dev)
- 요청: start_ui의 UI 시스템을 start_all에도 적용. (UI 화면 파일은 두 스크립트가 동일한 src/를 서빙 → 실제 차이는 환경변수뿐)
- 백업: git 태그 start_all-pre-uienv + scripts/start_all.sh.bak(로컬).
- start_all.sh [6.5/7] 블록 추가(run_app 직전): LLM_MATCH_ENABLE=1 + OPENAI_MODEL(기본 gpt-4o-mini) + OPENAI_API_KEY(.openai_key) + ADMIN_PIN(.admin_pin 또는 0000). run_app→serve→kiosk_server로 상속.
- 효과: start_all로 띄워도 AI 문진·트리아지 LLM ON, admin/의사 화면 PIN 보호(콜보드는 공개 유지).
- 검증: bash -n 구문 OK, set -euo 환경에서 블록 무중단 실행(LLM ON·PIN 4자리), 반영 확인. (로봇 스택 부분은 무변경)

## 2026-09-23 — [진단도구] 젯슨 전원/상태 실시간 로거 (ui-dev)
- 목적: start_all 주행 시 "젯슨만 전원 꺼짐" 원인(브라운아웃 의심) 포착.
- scripts/jetson_monitor.py: INA3221(hwmon4/5) 입력 전압(mV)·전류(mA)·전력(mW) + 온도 + loadavg를 0.2s 간격 CSV 기록. 매 샘플 flush+fsync → 전원이 갑자기 끊겨도 마지막 값 보존. 로그는 SSD(NVMe)에 저장(eMMC 92%·전원차단과 분리). tegrastats 병행 기록(CPU/GPU/EMC/온도).
- ★ INA 파일이 root 전용(-r--------)이라 반드시 sudo 실행. 비root면 경고 출력(온도·부하만 기록).
- 사용: 터미널A `sudo python3 scripts/jetson_monitor.py` → 터미널B `./scripts/start_all.sh` 후 이동 → 꺼지면 logs/jetson_monitor_*.csv 마지막 줄 확인/공유.
- 진단 근거(앞서): 정상종료 로그 없이 급단(=하드 전원컷), 온도 정상(열 아님), MAXN+jetson_clocks 피크, 라이다만 계속 회전 → 전원 강하 유력.

## 2026-09-30 — [기동 분리] 브링업=부팅 자동(systemd), start_all=내비부터 (ui-dev)
- 배경: 전원 모드 MAXN→MODE_30W_6CORE(4)로 낮추니 모터 구동 시 젯슨 꺼짐 해결.
- 신규 agv-bringup.service(systemd, 로그인 불필요): ExecStartPre=+ boot_prep_root.sh(root: 전원모드 4 고정·jetson_clocks --fan·장치 권한, 장치 인식 최대 30초 대기) → ExecStart boot_bringup.sh(wjs: ros_env + agv_bringup). Restart=on-failure, KillSignal=SIGINT, 로그 logs/bringup.log.
- install_boot_bringup.sh: sudo 1회 설치(enable --now) / --remove 해제. 수동 브링업 실행 중이면 중복 방지로 중단.
- start_all.sh: 기본은 [1] 건너뜀·[3] 브링업 확인만(최대 60초 대기, 없으면 안내 후 종료) → [4] 내비부터 진행. Ctrl+C 시 내비·복귀감시·앱만 정리, 브링업은 유지. 예전 방식은 --bringup 옵션.
- 검증: bash -n 4개 OK, 서비스 파일 검증 오류 없음(systemd 245), 전원모드 파싱·인자 파싱 확인. 서비스는 아직 미설치(사용자 sudo 필요).

## 2026-09-30 — [수정] 부팅 시 agv-bringup 미실행(의존성 실패) (ui-dev)
- 증상: 설치 후 재부팅했는데 팬·장치권한·브링업 전부 미실행. 서비스 enabled 인데 'Dependency failed'.
- 원인(저널 확인): NVMe 인식(05:29:39) 후 by-uuid 장치가 fstab x-systemd.device-timeout=5 안에 안 떠서 05:29:44 mnt-ssd.mount 실패 → RequiresMountsFor 로 묶인 서비스도 시작 안 됨. SSD 는 1초 뒤(05:29:45) 마운트됐지만 서비스는 재시도 안 함.
- 조치: 유닛에서 RequiresMountsFor 제거 → ExecStartPre(root)로 /mnt/ssd 마운트를 최대 90초 직접 대기(필요 시 mount). StandardOutput=append:(SSD 경로) 제거 — 로그는 스크립트가 직접(bringup.log, boot_prep.log). StartLimitIntervalSec=0.
- install_boot_bringup.sh: fstab /mnt/ssd device-timeout 5→30 (백업·검증·실패 시 원복), 갱신 시 restart 로 즉시 반영.
- 검증: bash -n OK, 유닛 오류 없음, SSD 대기 로직 모의 통과, fstab 치환 사본 모의 findmnt 파싱 OK. 재설치·재부팅 확인은 사용자 필요.

## 2026-09-30 — 병원 안내 전용 기동 스크립트 start_guide.sh (브링업 이후만)
- 신규 scripts/start_guide.sh: [1]ROS 환경 → [2]브링업 확인(부팅 서비스, 최대 60초 대기, 직접 기동 안 함) → [3]내비(amcl 120초·bt_navigator) → [4]초기 위치(실패 시 중단) → [5]복귀 감시 → [6]LLM·PIN 환경 → run_app.sh(STT·TTS·마이크·앱 서버).
- Ctrl+C: 복귀감시·내비·앱 서버만 정리. 브링업(agv-bringup)·STT/TTS 서버는 유지. sudo 불필요.
- start_all.sh는 그대로 유지(--bringup 비상용). 검증: bash -n OK, 참조 파일 존재 확인. 실기기 실행은 사용자 확인 필요.
- 수정: 브링업·ROS2 확인 단계 제거(브링업은 항상 떠 있다는 전제). ros_env.sh source만 남김(ros2 명령용). 4단계: 내비→초기위치→복귀감시→앱(STT/TTS). bash -n OK.
- start_guide.sh: 내비를 use_rviz:=false로 기동(CPU 약 57% 절약). cart_ros2 navigation.launch.py에 use_rviz 옵션 추가(기본 true, 백업 .bak-before-use_rviz-*). 조건 평가 검증 OK.
- 원복: 사용자 요청으로 RViz 다시 켬. start_guide.sh를 6ec4561 이전으로, navigation.launch.py를 백업본으로 되돌림(use_rviz 옵션 제거).

## 2026-10-02 — 껐다 켜면 이전 실패 요청이 뒤늦게 실행되는 버그 방지
- 원인1(Nav2): nav_request_watcher는 Nav2 미준비/거부 시 bus/nav_request/*.json 을 남겨 둠 → 다음 실행 때 집어서 갑자기 주행.
- 원인2(TTS): tts_server는 Ctrl+C 후에도 살아 있고 요청을 순서대로 처리 → 앱이 30초 대기 후 포기한 문장도 나중에 재생.
- tts_server.py: POST /flush(대기 요청 무효화 + 재생 중 aplay 중단), TTS_MAX_AGE_SEC(기본 25초) 넘은 요청은 재생 안 함, 합성·재생을 한 락으로 묶음(WAV 덮어쓰기 방지).
- start_guide.sh: clear_pending() 을 시작 직전과 종료 시 실행 — nav_request/*.json → nav_request_discarded/ 이동(삭제 안 함), TTS /flush, bin/stt 녹음 종료, kiosk_status.json idle. 종료 순서: 복귀감시 → 정리 → 내비.
- 검증: 임시 bus로 clear_pending 모의 OK, 가짜 모델로 stale/flush 드롭 OK. 실행 중인 TTS 서버는 구버전이라 한 번 재시작 필요.
- 신규 scripts/start_voice_ui.sh: UI+STT+TTS만(내비·초기위치·복귀감시 없음). nav_request_watcher 실행 중이면 중단(실주행 방지), 시작·종료 시 clear_pending. bash -n OK, 내비 감지 시 중단 모의 OK.
- TTS 대사별 켜기/끄기: app.js speak 24곳에 대사 ID, robotController가 id 전달·muted면 폴백 안 함, kiosk_server /speak가 TTS_ONLY_FILE 목록 밖이면 무음(요청마다 재읽기, 미지정=전부). tts_enabled.txt(기본 전부 주석=무음), start_voice_ui.sh에서만 지정. 임시 서버로 무음/허용/빈ID/파일없음 확인.
- 무조작 자동 리셋 제외 화면 추가: wait/moving/doctor/callboard(기존 voice/admin/admin-gate). 제외 화면 진입 시 떠 있던 '계속?' 창도 닫음. 헤드리스 크롬 가상시간: 수정 전 콜보드·의사 화면 70초에 창 뜨고 90초에 홈으로 바뀜 → 수정 후 유지 확인.
- 무조작 자동 리셋 기능 전체 끔(IDLE_DISABLED=true): '계속?' 창·idlePrompt TTS·홈 복귀 없음. 제외 목록은 보존. tts_enabled.txt idlePrompt 설명 갱신. 헤드리스 JS 오류 없음.
- 초진/재진 선택 화면 '처음으로' 중복 제거: startIntake 선택지에서 backHome 삭제(하단 고정 버튼만 유지). 헤드리스 스크린샷으로 배치 확인.
- 홈 메뉴: 박스 부제(환자 등록·증상 접수 / 진료과·시설 찾기) 4개 언어 모두 제거(HTML·i18n 키·CSS). 제목 아래 여백 추가(#voice-screen .voice-title margin-bottom). 한/영/일/중 헤드리스 스크린샷 확인.
- 영어만 이질감: 'Noto Sans KR' 미설치 → DejaVu Sans 대체(영어만 DejaVu, 한/일/중은 CJK 폴백), 버튼은 글꼴 미상속. 글꼴 목록에 'Noto Sans CJK KR' 추가 + button/input/select/textarea font-family:inherit. 측정: 4개 언어 제목 h66·박스 top280·버튼글자 h49로 동일(전: 영어만 54/274/39).
- 국기 버튼 세로 정중앙: .lang-flag 에 에모지 글꼴 지정 + inline-flex 가운데 정렬, 펼침 상태 display:flex. 2배 스크린샷 측정 아래 치우침 +2.0px → 0.0px, 버튼 크기 48x34 유지.
- 국기 펼침 시 위치 이동 보정: .lang-bar.open 에 패널 여백+테두리(9px)만큼 음수 margin(위·오른쪽). 측정: 1846x931·1280x800 모두 접힘/펼침 현재 국기 위치 차 9px → 0px.
- 국기 패널 화면 밖 잘림 보정: .lang-bar top/right 최소 8px→15px. 확대 1~2배 재현(뷰포트 축소) 측정: 패널 위 여유 -1.0px → 6.0px, 펼침 시 국기 위치 차 0px 유지, 1배는 변화 없음.
- 국기 펼침 미세 어긋남(확대 시 1px 반올림) 근본 보정: 패널을 padding/border/음수 margin 대신 .lang-bar.open::before 배경층(inset -8px)으로. 배율 1/1.1/1.25/1.5/1.75/2 실픽셀 측정 이동 0px(전: 1.5배에서 1px).
- 초진/재진 질문 → '이전에 방문하신 적이 있으신가요?'(4개 언어), 버튼 → 네(재진)/아니오(초진). 기존 yesBtn/noBtn 재사용, visitFirst/visitRevisit 제거. 헤드리스: 4개 언어 문구, 네→재진 폼·아니오→초진 폼 확인.
- 네/아니오 버튼 같은 크기: #retry-choices.equal(같은 너비 grid 칸 + 최소 너비 clamp(120px,12vw,200px)), startIntake에서만 켜고 showRetry 호출마다 해제. 측정: 한/영/일/중 모두 200x68, 화면 중앙.
- 정보 입력 화면 제목·TTS를 초진/재진 공통 '정보를 입력해 주세요'(4개 언어)로: formTitle/formSpeak 하나로 통합(기존 First/Revisit 4개 키 제거). 헤드리스로 4개 언어×초진/재진 제목·TTS·연락처칸 확인.
- 초진 연락처 칸 예시 잘림: #f-contact-row width 미지정 → 입력칸이 기본 너비(289px)로 줄어 예시 잘림. width:100% 로 이름 칸과 동일(530px). 4개 언어 예시 문구 폭 ≤ 안쪽 486px 확인.
- 접수 폼 주민번호 저장 안내 문구 삭제(사용자 요청): index.html p.form-note, i18n 'form.note'(4개 언어), CSS .form-note. 저장 방식(마스킹·해시·암호화)은 그대로. 헤드리스로 초진/재진·영어에서 문구 없음 확인.

## 2026-10-06 — HANDOFF.md 전면 재작성(논문 집필용 전체 시스템 기술 정리)
- 기존 사이클별 HANDOFF(607줄)를 docs/handoff_archive_2026-07-16_to_09-11.md 로 이동(git mv).
- 새 HANDOFF.md: 개요·환경·기동·브링업·Nav2·파일버스/복귀정렬·음성·AI·병원업무·실증결과·한계·논문구성/측정제안·운영·부록. 코드 근거(파일:줄) 표기, 핵심 수치 직접 대조 확인.

## 2026-10-12 — 사이클 11 착수: 원격 작업 환경 점검 + STT 한국어 고정 위치 보고 (코드 변경 없음)
- PLAN.md가 아직 사이클 10 내용(사이클 11 계획 파일 없음) → 채팅 요청(0번, A-4)만 기준으로 진행.
- 0번: kiosk_server 0.0.0.0:8000 바인딩, ufw 꺼짐, snap tmux 3.7c 안에서 SSD·ROS 환경·오디오·venv 정상(시험 세션), SSH 터널 + tmux + start_voice_ui 절차 정리.
- A-4: STT 언어 고정 = kiosk_server.py:1020 language=ko 한 줄 + 화면이 lang 미전송(real.js:18). 관련 9곳 표로 보고. 구현 방법·검증 계획(원격/보드 앞 구분)을 HANDOFF.md 0장에 정리.

## 2026-10-12 — 사이클 11 PLAN 저장 + 0장 재정리
- PLAN.md를 사이클 11(원격 작업 환경 + 다국어 강화)로 교체(사용자 붙여넣기 원문). 백업 태그 cycle11-base.
- 항목 1·2·4·7 완료(보고): 0.0.0.0 바인딩·ufw 꺼짐·tmux 정상 / STT ko 고정 위치 / TTS는 한국어 모델만, 영·일·중 라이브러리 미설치(MeloTTS 원본은 6개 언어 지원).
- 항목 3: 마이크·스피커가 현재 보드 장치만 사용 → 노트북 장치로 테스트하려면 '노트북 음성 모드' 필요(제안, 승인 대기).
- HANDOFF.md 0장을 PLAN 항목 순서로 재작성: 구현 방법(STT lang 전달, TTS A/B/C안, 언어 섞임), 검증 계획, 결정 필요 3건. 코드 변경 없음.
- HANDOFF 0-10절 추가: 노트북 쪽 SSH 접속 준비(~/.ssh/config·접속 단축 파일·키·VS Code 원격 주의·IP 변경·점검 순서·문제 해결). 보드 SSH 설정은 읽기만(기본값: 비밀번호·포트전달 허용, avahi 동작, ~/.vscode-server 없음).
- CLAUDE.md 1장 환경 갱신: 노트북 VS Code Remote-SSH 작업, jetson+8000 터널로 UI 확인, VS Code 서버 SSD(/mnt/ssd/vscode-server 1.6G, eMMC엔 로그 24K), tmux kiosk + start_voice_ui, 반영 방법, 마이크·스피커는 보드 장치만. 다른 장은 무변경.
- 간호사 화면 주소 ?admin=1 → ?nurse=1 (app.js 진입 판단 1곳, ?admin=1은 호환 유지 + 주소창만 ?nurse=1로 교체). 내부 이름·서버 PIN·.admin_pin·start_all.sh는 무변경. 주석·start_ui/voice_ui/guide 안내·HANDOFF/CLAUDE/SCENARIOS 갱신. 임시 서버(8124) 헤드리스 확인: nurse/admin→간호사(PIN 끔=화면, 켬=게이트), doctor·callboard·홈 그대로, /waitlist PIN 없이 403.
- 문진 화면: 첫 질문 말풍선(symptomQ) 제거, '이대로 접수하기' 버튼 제거(HTML·리스너·CSS·i18n), 재진 예약없음 음성(noResv) 제거. symptomQ는 음성 전용 '어디가 불편하신지 알려주세요.'(4개 언어). AI 꼬리질문 음성 유지, tts_enabled.txt는 켜기 상태 무변경(설명만 갱신). 임시 서버 헤드리스: 초진·재진(예약없음) 모두 문진 화면, 말풍선 0, 음성 visitQ→formIntro→symptomQ, JS 오류 없음.
- 추천 진료과 음성(recommend) 문구 변경: '추천 진료과는 {과}입니다. 해당 진료과로 접수하시거나 다른 진료과를 선택해주세요.' + 영·일·중 같은 뜻으로 맞춤. 화면 제목 문구는 무변경. 페이지 JS 오류 없음 확인.
- 추천 화면: 제목 '추천 진료과는 '{과}'입니다'(4개 언어), 추천 버튼 '✅ {과} (추천)', '진단 아님' 안내 제거(추천 화면만, 과 판단 어려움 화면은 유지). 서버 무음 로그가 앞 40자만 찍던 것 → 전체 출력(TTS 자체는 원래 전체 전송). 임시 서버 헤드리스 한/영 확인.
- 추천/과 판단 어려움 화면에서 환자 확인 문장(recap) 표시 제거(app.js만, 서버는 계속 생성하나 미사용). 의료진용 summary_ko는 대기명단 저장 유지. 임시 서버 헤드리스: 두 화면 확인문장 없음, 대기 등록 시 symptom_summary 저장 확인.
- 문진 화면 제목 '증상을 설명해주세요' 추가(4개 언어, data-i18n interview.title, 다른 화면과 같은 listening-title 스타일). 임시 서버 헤드리스 4개 언어 확인.
- 문진 화면 제목↔입력칸 간격 축소: 빈 대화칸(.chat-log:empty) 숨김. 측정 1846x925 49→25px, 1280x720 40→22px. 꼬리질문 말풍선이 생기면 다시 표시.
- 문진 결과 화면(추천·과 판단 어려움): '증상 다시 말하기' 버튼 제거, 하단 '처음으로' 왼쪽에 '이전으로'(btn.prev 4개 언어) 추가 → 증상 입력부터 다시. retry-screen 공용이라 showRetry 6번째 인자로 넘길 때만 표시. 임시 서버 헤드리스: 두 화면 표시·이동 OK, 방문 질문 화면엔 숨김, 영어 Back.
- 문진 결과 화면 하단 버튼 '이전으로' → '뒤로'(다른 화면과 같은 btn.back), btn.prev 키 제거.
- 대기 화면: 번호표 형식(접수번호 라벨 + 큰 숫자 / '대기인수: N 명', 4개 언어), '예상 진료과'·'곧 순서입니다' 제거(임박 색 강조·호출/진료중 문구는 유지), 음성 waitTicket='접수가 완료되었습니다.' 하나(예약 자동등록 포함). 미사용 STR(waitTicket/waitAhead/waitDept/waitSoon/regDoneMsg)·CSS(.wait-dept) 제거. 임시 서버 헤드리스: 선행 3명 → 번호 4·대기인수 3, 호출 시 음성·문구 OK(한/영).
- 대기 화면 대기인수↔위치안내 간격 축소: 빈 상태 문구(.wait-status:empty) 숨김(호출·진료중일 때만 표시). 1846x925 측정 78→37px.
- 대기 화면 위치 안내 버튼 위 여백 축소(#wait-guide margin-top clamp(6px,1.2vh,12px), 대기 화면만). 1846x925 대기인수→버튼 37→18px.
- 위치 안내 화면 문구 끝 마침표 제거(표시용 located, 4개 언어). 음성(locatedSpeak)은 마침표 유지. 임시 서버 헤드리스 4개 언어 확인.
- 증상 입력 화면만 초진도 재진과 같은 단계 표시(본인 확인/확인/완료): setSteps에 forceVt 인자 추가. 화면 내용·음성은 원래 동일. 헤드리스: 초진 정보입력·추천은 기존 표시, 증상만 재진과 동일 확인.
- 간호사 대기 현황 행을 '#순번 · 이름'만 표시(주민번호·초진/재진·상태 글자·증상 요약 제거). 상태는 행 배경색·호출/재호출 버튼으로 구분 유지. 의사 화면 요약은 그대로. 미사용 .wait-summary CSS 제거. 임시 서버 헤드리스 확인.
- 의사 화면 '진료과를 선택하세요'↔과 버튼 간격 0→16px(#doctor-dept-select .voice-hint margin-bottom). 헤드리스 측정·스크린샷 확인.
- 의료진 화면 제목 변경: '접수 관리 (간호사)'→'관리자 (간호사 전용)', '진료 (의사)'→'관리자 (의사 전용)'.
- 의료진·콜보드 주소 첫 로딩 시 환자 첫 화면이 잠깐 보이던 깜빡임 제거: index.html head에서 주소 확인 → html.staff-boot(환자 첫 화면 visibility:hidden), 첫 showScreen에서 해제. /admin/auth 3초 지연 시험: 대기 중 첫 화면 숨김, 이후 PIN 화면, 환자 주소 무변화.
- STT/TTS 확인용: tts_enabled.txt에서 실제 쓰는 대사 20개 모두 켬(noResv·idlePrompt·emergency·emergencyCalled는 호출 안 돼 주석 유지). 서버 재시작 불필요(요청마다 재읽기).
- 위치 안내 음성 수정: notHeard→'인식하지 못했습니다. 다시 말씀해 주세요.'(음성 전용 문구 분리, 화면 유지), whichPlace→'아래에서 찾으시는 장소를 선택해 주세요.', locatedNotReady·movingStarted 음성 삭제, guideStart→'{과}로 안내를 시작합니다.', arrived 음성→'{과}에 도착했습니다. 안내를 마무리합니다.'(화면 유지). 4개 언어 함께. listenPrompt·locatedConfirm·noResponse·reqFailed 무변경. 헤드리스(가짜 응답) 4가지 흐름 확인.
- 접수 음성: 입력 오류(formError) 음성 삭제(화면 오류 안내는 유지), 과 판단 어려움(triageHard) → '해당 증상만으로는 특정 진료과를 추천하기 어렵습니다. 원하시는 과를 직접 선택해주세요.'(4개 언어). 헤드리스 확인.
- 문진 화면 음성 안 나오던 문제: symptomQ/interviewQ 음성과 녹음을 동시에 요청 → 서버가 녹음을 먼저 잡아(_stt_lock) 말하기 전까지 음성 대기. 음성 끝난 뒤 녹음(listenIfInterviewing, 최신 안내만·화면/타자 상태 확인). 헤드리스(가짜 응답) 정상·타자 먼저·화면 이탈 3경우 확인. 남은 한계: 녹음 중 타자로 답하면 서버 녹음은 말소리 끝날 때까지 계속돼 다음 음성이 지연될 수 있음.
- TTS 지연·막힘 구조 개선 ①②③: ① 녹음 대기 제한(STT_WAIT_SEC 기본 8초, 데이터 없어도 0.2초마다 확인, kiosk_server 자체 녹음기로 교체·임시 WAV 삭제) ② POST /listen/cancel(그 시점까지의 녹음 요청 전부 취소, 락 대기 중 요청 포함), 화면 recognizer.cancel이 서버에도 전달, 문진 화면은 말소리 없으면 다시 듣기 ③ TTS 합성 캐시(문장→WAV, 300문장) + POST /prewarm, 앱 시작 3초 뒤 고정 안내 44문장 미리 합성(/speak/prewarm 중계), aplay 표준입력 재생. 검증: 임시 TTS(5099, null 스피커) 캐시 재생 1.43→0.18s, 가짜 마이크 하네스 무음 3.1s·데이터없음 3.0s 종료, 취소 1.1s, 녹음 중 음성은 취소 후 0.2s 처리, 실제 음성 whisper 1.3s. 헤드리스: 다시 듣기·서버 취소·미리합성 44문장 OK. 서버 재시작 필요(kiosk·tts).
- 호출 음성을 콜보드로 이동: /callboard 항목에 key·calledAt 추가(건강정보 아님), 콜보드가 새 호출·재호출(호출 시각 변화)을 감지해 '{성}, {이름} 님, 진료실로 들어가 주세요.'(복성 남궁·황보 등 처리, 비한글은 '{이름} 님') 차례로 안내. 콜보드 첫 로드 시 이미 호출된 환자는 안내 안 함, 진료중 전환은 무음. 키오스크 대기화면 waitCalled 음성 삭제(화면 표시 유지), 미리 합성 목록에서도 제외. tts_enabled: waitCalled 주석, callboardCall 추가. 임시 서버 헤드리스 확인. 앱 서버 재시작 필요.
- 간호사·의사 흐름 개편: 간호사 대기 현황 = 대기 [호출·삭제] / 호출됨 [재호출·삭제] / 진료중 '🩺 진료 중' 표시+삭제, 의사 '진료 완료' 시 과별 '완료된 환자'로 자동 이동(최근 순, 의사 메모 표시). 간호사 '완료' 버튼 제거. 의사: '완료'→'진료 완료'(메모 저장+완료), '오늘 완료' 칸 제거, 3초 갱신 때 메모 초안·포커스·커서 유지(쓰던 메모 지워지던 버그 수정). 서버 무변경. 임시 서버 헤드리스 전 흐름 확인.
- 의사 화면 호출/재호출 버튼 제거(호출은 간호사 화면 담당). 의사 버튼: 진료 시작·진료 완료.
- 의사 메모 저장 확인 UI: 저장 직후 버튼 '✓ 저장됨'(초록, 2초), 메모칸 아래 상태줄 '✓ 저장됨 · HH:MM'(memo_at) / '● 저장하지 않은 변경 사항이 있습니다' / 실패 시 '⚠ 저장하지 못했습니다'(초안 보존). 서버 메모는 저장 때마다 덮어씀(수정 반영). 헤드리스 확인.
- 음성 끊기: 키오스크 대사는 새 대사가 오면 재생 중 대사를 TTS /flush로 중단·대기 대사는 건너뜀, POST /speak/stop('처음으로' 등 stopSpeak가 호출), 콜보드 호출(callboardCall)은 끊지도 끊기지도 않음. 끊김/오래됨은 skipped로 반환해 브라우저 음성 대체 안 함. 위치 안내 '말씀해 주세요.' 중 화면 이탈 시 녹음 시작 안 함. 가짜 TTS로 5가지 경우 확인.
- 간호사 예약 등록: 시간 입력(adm-time, 10분 단위) 추가 → 날짜와 합쳐 '2026-10-20 14:30'으로 저장(서버 무변경, 표시용 문자열), 증상/사유 칸을 다음 줄 전체 폭으로, 주민번호 숫자만 입력해도 6자리 뒤 '-' 자동(최대 13자리). 헤드리스 확인.
- 문진 화면을 메신저형 채팅창으로: 고정 높이 창(clamp 280~480px, 48vh) + 상단 'AI 접수 도우미' 머리줄 + 아래 입력줄. AI=왼쪽(프로필·이름·흰 말풍선), 환자=오른쪽(노란 말풍선), 말풍선 옆 보낸 시각(언어별 형식). 넘치면 오래된 메시지는 위로 밀려 가려지고 항상 최신이 보임(스크롤바 숨김, 손가락 스크롤 가능). chat.bot 4개 언어. 헤드리스: 8개 말풍선에서 창 높이 고정·맨 아래 유지 확인.
- 문진 대화창을 앱 고유 디자인으로 재정리: 노란 말풍선·청회색 바탕·프로필/이름·시각·머리줄 제거, 웜 팔레트(바탕 --bg, AI=테두리 흰 말풍선, 환자=주색 말풍선). 고정 높이·오래된 메시지 위로 밀림 동작은 유지. 헤드리스 확인.
- 문진 화면 음성 전용: 타자 입력칸 숨김(?dev=1 시험용만 표시), 대화창 아래 상태줄(🔊 안내 중 / 🎤 듣고 있어요(주색+퍼지는 고리, reduced-motion 시 정지) / ⏳ 확인 중 / ⚠ 마이크 사용 불가, 4개 언어). 헤드리스: speaking→listening→processing→speaking→listening, 오류 시 error 확인.
- [사이클11 A-5] STT 다국어: 화면 언어(lang)를 /listen 본문으로 전달(real.js·app.js 2곳), 서버가 Whisper language=lang(ko/en/ja/zh, 없거나 그 외는 ko=예전과 동일), 언어별 초기 프롬프트(장소 이름), 한국어 보정(postprocess)은 ko만. 외국어 장소 별칭(_FOREIGN_ALIASES, 긴 표현 우선)으로 LLM 없이도 매칭. 검증: LLM 끈 임시 서버에서 영·일·중 10문장 매칭 정확, 같은 음성 파일을 언어별로 보내 Whisper 출력 언어가 바뀜(ko/ja/zh/en, 1.2~1.5초). 실제 외국어 발화 인식(항목 6)은 보드 앞 확인 필요.
- [사이클11 A-8] TTS 다국어(B안): MeloTTS 영·중·일 의존성을 TTS venv에 설치(백업: logs/tts_venv_backup_20261013). tts_server가 한국어를 먼저 띄워 바로 준비하고, 영(EN-US)·중·일 모델은 뒤에서 차례로 로드(TTS_LANGS). 요청 lang에 맞는 모델로 합성하고 캐시 키도 (언어, 문장). 아직 안 뜬 언어는 lang_not_ready → 앱은 건너뜀(엉뚱한 언어로 읽지 않음). kiosk /speak·/speak/prewarm이 lang 전달. 화면: robotController.lang=화면 언어, 브라우저 폴백 로케일도 언어별, 녹음 전 '말씀해 주세요.' 다국어화(STR.listenPrompt, 한국어 문구 동일), 언어 바꾸면 그 언어 고정 안내를 미리 합성, 콜보드 호출은 항상 한국어. flush 중단 시 aplay 'Interrupted system call' 로그 숨김. 검증: 임시 서버(5012, 무음 스피커)에서 4개 언어 로드(전체 약 1분, 모델 캐시 후), 합성 0.5~0.9초, Whisper 역인식이 원문과 일치, 로딩 전 ja 요청 lang_not_ready 확인, 일본어 미리 합성 후 캐시 적중 확인.
- 콜보드 호출 음성을 접수 언어로: /waitlist/add에 화면 언어(lang) 저장(대기명단 항목 "lang", 모르는 값은 ko), /callboard 항목에 lang 포함. 콜보드가 그 언어로 호출(en "{이름}, please come into the examination room." · ja "{이름}様、診察室にお入りください。" · zh "{이름}，请进入诊室。"). 이름이 한글이면 외국어 모델이 못 읽으므로 이름("홍, 길동 님")만 한국어 음성 → 이어서 접수 언어 문장. 기존 대기 환자(lang 없음)는 한국어 그대로. 검증: 임시 데이터 파일로 저장·콜보드 출력 확인, 헤드리스로 호출 문장 7가지 확인.
- 콜보드 일본어 호출: 한글 이름이면 "님" 대신 "さま" — "홍, 길동"(한국어 음성) → "さま、診察室にお入りください。"(일본어 음성). 様는 よう로 읽힐 수 있어 가나로 표기. 한국어 접수는 "홍, 길동 님, 진료실로 들어가 주세요." 그대로.
- HANDOFF 2.3절 신설: 마이크(Generalplus, 1b3f:2008)·스피커(Jieli UACDemoV1.0, 4c4a:4155) 상세(형식·레벨·지정 방식·쓰는 곳·미사용 장치·한계). 기존 2.3 소프트웨어 스택 → 2.4, 음성합성 행을 다국어로 갱신.
- [reSpeaker A-1] 인식 확인(18:48): lsusb·aplay -l·arecord -l·/proc/asound/cards 어디에도 XMOS/XVF3800 없음. 17:46 이후 커널 USB 연결 이벤트 0건(꽂았는데 장치 응답 자체가 없음). 17:46에 허브 1-4.4.4(웹캠 STsmart·로지텍 수신기 연결)가 err -71 반복 후 끊김 → 웹캠·로지텍 수신기도 현재 목록에서 사라짐. 설정 변경 없음, 사용자에게 보고(A-2 원인 점검 대기).
- [reSpeaker A-2] 사용자 확인: 카메라가 꽂힌 추가 USB 단자(허브 1-4.4.4, Terminus 1a40:0101)에 꽂음. → 꽂은 시점(17:46) 그 허브 포트3에서 err -71 반복 후 허브 전체가 끊김, 이후 재인식 없음(18:50). 원인 추정: 허브 전력 부족/돌입전류로 허브 다운. 권장: reSpeaker 빼서 허브(웹캠·로지텍) 복구 여부 확인 → Jetson 본체 포트 또는 전원 공급형 허브에 직결. 설정 변경 없음.
- [reSpeaker A-1 ✅] 19:08 재부팅 후 재배선(추가 단자·기존 마이크/스피커 제거 → 허브 A-1 reSpeaker, A-2 웹캠, C-4 로지텍 수신기) → 인식 성공. reSpeaker Flex XVF3800 C16K6Ch (Seeed 2886:001e, USB 2.0 High speed, 400mA): ALSA 카드 이름 C16K6Ch(현재 카드 1), 재생 2ch 16kHz S16_LE / 녹음 6ch 16kHz S16_LE. 믹서 PCM 67%(40/60, −20dB), Headset 캡처 100%. 웹캠 = 카드 0(WEBCAM), /dev/video0·1. 주의: 앱은 아직 예전 설정(TTS=UACDemoV10 이름 지정, STT=번호로 "Usb Audio Device" 검색) → 지금 그대로 띄우면 음성 안 됨(C 단계에서 수정). 재부팅으로 tmux kiosk·서버 모두 꺼진 상태.
- [reSpeaker C-4~6] 사용자 요청으로 B(사람 녹음·재생 확인) 전에 설정 변경. 마이크: serve.sh가 reSpeaker를 카드 이름(C16K6Ch)으로 1순위 감지 → STT_AUDIO_DEVICE=plughw:CARD=C16K6Ch,DEV=0, STT_CHANNELS=6, STT_CHANNEL=0 (예전 "Usb Audio Device"는 2순위). kiosk_server: 6ch로 녹음해 0번 채널만 꺼내 16kHz 모노로 Whisper에 전달(_arecord_cmd/_pick_channel, 주변음 측정도 동일). 스피커: tts_server가 reSpeaker 우선 감지(plughw:CARD=C16K6Ch) — PCM 80%(−12dB). 측정: 6ch 중 0번만 크고(AGC 처리 음성) 2~5번은 원음 수준, -c 1 다운믹스는 오히려 작음(rms 62) → 0번 채택. AEC 확인: 스피커 재생 중 0번 RMS 1661→105로 억제, 원음 채널은 증가. 44.1kHz TTS → 16kHz 장치 재생 정상(plughw 변환). 재부팅으로 꺼진 tmux kiosk 새로 만들어 start_voice_ui 기동 → 4개 언어 TTS 준비, /speak 재생 OK. 사람 발화 인식(7)·말하는 중 끼어들기(8)는 보드 앞 확인 필요.
- reSpeaker 스피커 볼륨: 80%(48/60=−12dB)가 너무 작음 → 즉시 100%(0dB)로 올림. tts_server 기본 볼륨을 reSpeaker 감지 시 100%로(예전 스피커는 80% 유지, TTS_VOLUME으로 강제 가능). 다음 TTS 재기동부터 자동 적용.
- reSpeaker 스피커가 여전히 작음 → 원인: USB 오디오 마스터 볼륨(PCM,1 "Mono")이 따로 있고 기본 −20dB. 채널 볼륨(PCM,0)만 100%였음. PCM,1도 100%(0dB)로 올림(실효 −20dB → 0dB, 약 10배 진폭). tts_server 볼륨 설정이 같은 이름 index 1도 함께 맞추도록(없으면 무시).
- TTS 소프트웨어 증폭: 장치 볼륨(채널·마스터) 모두 최대인데 더 크게 요청 → tts_server가 합성 직후 음성을 +TTS_GAIN_DB(reSpeaker 기본 6dB) 키우고 tanh 소프트 리미터로 클리핑 방지(평균 −19.7→−14.7dBFS, 최고 −2.2dBFS). TTS·앱 서버 재기동, 볼륨 100%/100%·증폭 +6dB 적용 확인. 더 키우려면 TTS_GAIN_DB(9~10 이상은 소리가 뭉개질 수 있음) 또는 12V 전원.
- 환자용 음량 조절 UI: 모든 환자 화면 좌상단 🔈/🔉/🔊 버튼 → 누르면 [−] ▮▮▮▯▯ [+] 패널(5단계, 기본 3=현재 크기, 바깥 누르면 접힘). 의료진·콜보드 화면엔 숨김, 첫 화면 복귀(resetToVoice) 시 기본 3으로. robotController.vol을 /speak에 실어 보냄 → kiosk → TTS 서버가 재생 직전 TTS_GAIN_DB+단계 보정(1:−12,2:−6,3:0,4:+3,5:+6dB) 적용(캐시는 원본 보관 → 단계 바꿔도 재합성 없음). 콜보드 호출은 항상 기본 3. 측정(평균 dBFS): 1 −25.8 · 2 −19.8 · 3 −14.8 · 4 −12.4 · 5 −10.3. 헤드리스(CDP): 펼침·5단계·상한 비활성·접힘, 간호사 화면 숨김, 환자 화면 6개 겹침 없음.
- 음량 버튼을 언어 국기 버튼과 같은 크기·높이로(글자 크기·여백·줄높이 동일, 위쪽 정렬) — 헤드리스 측정 둘 다 top 15px · 48×34.
- 우상단 도구 줄(.top-tools): [음량][국기]를 나란히(간격 12px), 국기를 홈 화면 밖으로 옮겨 모든 환자 화면에 표시(의료진·콜보드 숨김). 음량 아이콘을 에모지 🔉(글리프가 왼쪽으로 치우침) → SVG(스피커+음파 1~3줄, 단계별로 그림 이동해 가로 중앙 정확히 맞춤). 음량 패널은 버튼 아래·오른쪽 끝 맞춤, 국기 펼침과 서로 닫힘. 헤드리스: 두 버튼 48×34·top 15, 아이콘 중심=버튼 중심(1·3·5단계), 환자 화면 8개 겹침 없음.
- 버그 수정: 직전 커밋(3a73c9b)의 HTML 편집에서 </div> 하나가 남아 #app이 일찍 닫힘 → 모든 화면이 #app 밖으로 빠져 "처음으로"(data-nav, #app 위임 클릭) 무반응. 남은 태그 제거, 태그 짝 검사 통과. 언어 섞임 수정: 화면별 글자 다시 그리기 등록(onRelabel) → 언어 바꾸면 현재 화면의 JS 문구를 새 언어로(재질문/방문 여부/추천·트리아지 선택지, 정보 입력 제목·단계, 장소 결과, 이동/도착 안내, 대기 화면 제목·번호표·위치 버튼·단계, 문진 단계·마이크 상태, 응급). 음성·진행 상태는 그대로, 문진 말풍선(대화 기록)은 유지. showRetry가 문자열 대신 함수도 받음. 헤드리스: 일→한 전환 시 재질문·폼 제목·단계 모두 한국어, 뒤로→방문 여부 화면, 처음으로→첫 화면, JS 오류 없음.
- reSpeaker 인식 문제 진단 시작: 녹음기가 들어온 소리의 최대 RMS·길이·종료 이유(말 끝남/최대 길이/말소리 없음)를 로그로 남기게 함. 현재 0번 채널 주변음 RMS≈7~27(노이즈 억제), 기준 350. whisper 단독 1.1초(정상). 높은 CPU는 IMU 노드 stella_ahrs(무관).
- 진단 결과(사용자 터미널 로그): "내과" 녹음 2.2초(말 끝남), 최대 RMS 3309 / 기준 350, whisper 0.99초, 매칭 internal → 정상. 앞선 실패 추정 원인: 서버 시작 때 주변음이 523·534로 측정돼 기준이 1271·1294로 높게 잡힌 적이 있음(reSpeaker 노이즈 억제·AGC가 막 켜졌거나 말소리가 섞인 순간) → 조용한 말은 놓침. 다채널(reSpeaker) 기준 상한 600으로 제한(예전 마이크는 1500 유지).
- 인식 실패 원인 확정("팔이 까졌습니다" → 시청 감사 환각): 서버 시작 때 0번 채널 주변음 867 > 기준 상한 600 → 배경음이 말소리로 감지돼 7.2초 녹음, Whisper가 잡음에서 영상 자막 문구를 지어냄(30초). 조용한 방 10초 측정: 0번(처리, AGC) 150~1940으로 0.5초마다 출렁, 2번(원음) 70~160 안정. 수정: 말소리 감지(VAD·주변음 측정)는 원음 2번(STT_VAD_CHANNEL), Whisper로 보내는 소리는 0번 유지. 600 상한 제거(원음은 안정). Whisper 환각 문구(시청해주셔서/구독·좋아요/thank you for watching/ご視聴/谢谢观看 등) 결과는 버리고 "못 알아들음" 처리.
- 신경망 말소리 감지(Silero VAD v5.1.2, /mnt/ssd/models/silero_vad/silero_vad.onnx 2.3MB) 도입: 멀리서 조곤조곤 말하면 원음 RMS 169~240(배경 71)로 크기 기준(350)을 못 넘어 놓침 → "목소리인지"로 판단. STT venv에 onnxruntime 1.16.3(+coloredlogs·flatbuffers·humanfriendly·mpmath·protobuf·sympy·packaging, 기존 패키지 변경 없음, 백업 logs/stt_venv_backup_20261014). 1.19.2는 꺼진 CPU 코어 때문에 세션 생성 시 비정상 종료 → 1.16.3 + 스레드 1개. scripts/speech_vad.py. 녹음기: 시작=100ms 중 32ms 프레임 2개 이상 확률≥0.5, 이어짐=하나라도 ≥0.35, 인식 채널(0번)로 판단, 원음 채널 확률은 비교 로그. 모델 없거나 STT_VAD=energy면 예전 크기 기준. 검증: 음성 1/15 크기+방 소음 → 감지·인식 "말씀해주세요.", 소음만 8초 → 감지 안 됨(최대 확률 0.57 단발), 프레임당 약 1ms.
- 음량 조절을 5단계 → 0~100 드래그 슬라이더로(기본 60 = 예전 기본 크기). TTS 서버 _vol_gain_db: 60 이하 진폭 비례(30=−6dB, 15=−12dB), 60 위는 100까지 +6dB(예전 5단계 상한), 0 = 무음(재생 안 함, 합성·캐시만). 아이콘 0=스피커+✕, 1~33/34~66/67~100 = 음파 1/2/3줄(가로 중앙 유지). 숫자 표시, 터치용 큰 손잡이, 채운 막대 주색. 첫 화면 복귀 시 60. 측정(평균 dBFS): 15 −25.8 · 30 −19.7 · 60 −14.7 · 80 −12.3 · 100 −10.3. 헤드리스: 기본 60, 0에서 ✕ 아이콘·중앙, 85 반영, 패널 화면 안. TTS·앱 서버 tmux 재기동.
- 음량 슬라이더를 세로로, 국기 펼치기와 같은 방식: 버튼 누르면 뒤에 패널(::before)이 깔리며 아래로 세로 막대(위=100, 아래=0) + 숫자, 접힘이면 ▾ 힌트, 바깥 누르면 접힘, 국기와 동시에 안 열림. 크롬 버전별 세로 range 지원 차이 때문에 직접 구현(pointer capture 드래그, 막대 밖으로 나가도 0/100으로 고정, 키보드 ↑↓5·Home/End). 헤드리스 실제 마우스 드래그: 위로 → 87, 아래 끝 밖 → 0(✕ 아이콘), 바깥 클릭 → 접힘. 버튼은 국기와 같은 48×34·top 15.
- start_guide.sh도 start_voice_ui.sh와 같은 음성 대사 목록(tts_enabled.txt, TTS_ONLY_FILE) 사용 — 마이크·스피커 장치 설정은 원래 둘 다 run_app.sh 경유로 동일했고, 남은 차이는 이것뿐이었음. start_all.sh는 손대지 않음(모든 대사).
- 주행 시(start_guide) 안내 시작·도착 음성 안 나옴 + 인식 둔함 원인: 브링업 재시작 때 boot_prep_root.sh가 전원 모드를 기본 4(30W_6CORE)로 되돌려 CPU 6코어 92~100% 포화 → TTS 한 문장 3~10초(미리 합성 37문장 381초). "안내를 시작합니다"는 미리 합성에 밀려 26.4초 대기 후 stale 폐기, "도착했습니다"는 합성 중 5초 뒤 처음 화면 복귀(stopSpeak→flush)로 폐기. 수정: ① boot_prep_root.sh 기본 전원 모드 3(30W_ALL, 사용자 주행 시험에서 꺼짐 없음 확인) ② TTS 서버: 실제 안내 요청이 기다리면 미리 합성이 다음 문장을 시작하지 않고 양보(_waiting) ③ 도착 화면: 도착 음성이 끝난 뒤 ARRIVE_HOLD_MS 세고 복귀(그 사이 화면 이동 시 타이머 안 검). reSpeaker를 젯슨 본체 USB-C(루트 포트 2, OTG 젠더)로 옮겨 웹캠과 USB 충돌 해소: 웹캠 29fps 수신 중 3초 녹음 정상, buffer overrun 0건(허브 A 공유 시 수백 건).
- 주행 충돌 원인 분석 도구: scripts/record_nav_bag.sh(주행 rosbag 녹화 → /mnt/ssd/bags, 명령·센서·Nav2 경로/costmap/액션/로그 30여 토픽 + 당시 agv.yaml·로그 사본, --deep 시 DWB 후보 궤적 평가·전역 costmap·IMU) · scripts/analyze_nav_bag.py(report.md + 타임라인·지도 궤적·근접 이벤트 그림: 실제 차체 사각형 0.9×0.7 기준 LiDAR 여유 거리, 걸림(명령 전진·바퀴 정지·전류), 이벤트 순간 costmap 반영 여부·원 밖 모서리 접촉, cmd_vel vs odom 지연·급가감속·좌우 흔들림·명령 끊김, 전역 경로~벽 여유, AMCL 튐, Nav2 경고·복구, 전원). 정지 상태 20초 시험 녹화(17MB, 약 0.85MB/s)·분석 확인. 설정만으로 나온 원인 후보: 지역 costmap robot_radius 0.4(실제 모서리 0.57)·전역 0.3(실제 반폭 0.35보다 작음)·DWB BaseObstacle.scale 0.1 vs PathAlign/PathDist 16. 부수 발견: /imu/data 약 908Hz(IMU 1ms 타이머) → CPU 포화 요인 후보.
- 첫 실제 주행 녹화 분석(nav_20261111_221640_충돌재현, 10분 46초, 목표 2개 성공·복구 4/7회): 분석기 수정 — 지역 costmap OccupancyGrid는 0~100(치명 99·100)로 판정, AMCL은 map→odom 보정 크기로, 근접을 정지/주행으로 구분, 경고 로그 숫자 묶음. 결과: AMCL 보정 중앙값 1.9cm·최대 8cm(위치추정 정상), 전역 경로~지도 벽 최소 0.55m(경로 자체는 벽에 안 붙음), 컨트롤러 20Hz 미달 1835회·실제 /cmd_vel 12.4Hz·0.25s 넘는 끊김 18회(최장 0.5s)·플래너 주기 미달 121회, 지역 costmap "센서 원점이 지도 밖" 57회(롤링 창 갱신이 로봇을 못 따라감), LiDAR 병합 스캔 버림 301회, 회전 방향 뒤집힘 38회/분·한도 넘는 가감속 명령 356회·명령→실제 0.3s 지연. 주행 중 근접 9건(앞왼쪽 모서리 4·왼쪽 옆면 3·앞오른쪽 모서리 2, 최소 4cm), 그중 원 밖 모서리에만 치명 칸 걸린 5건·costmap 미반영 4건. 정지 중 근접 8건 = 대기 자리 앞왼쪽 0~7cm 물체(이동 중엔 0%).
- 2026-11-11 중단 시점: Nav2 설정(사각형 footprint·제어 완화·voxel 중복 제거)·LiDAR 병합 허용 0.1s 적용(cart_ros2 커밋), IMU 발행 100Hz 코드 수정은 빌드 전, RViz 켬/끔 스크립트 2개는 미착수. 사용자 급히 전원 내림.
- 2026-11-12 이어서: stella_ahrs 빌드 완료(publish_rate_hz 100 포함, 브링업 재시작 시 적용). navigation.launch.py use_rviz 인자(cart_ros2) + start_guide.sh(RViz 켬, USE_RVIZ 환경변수) / start_guide_norviz.sh(RViz 끔) 분리.
- 2026-11-12 RViz 끈 버전에서 로봇 안 움직임: 원인 = Nav2 Galactic lifecycle_manager_navigation 이 기동 중 bond 경쟁 상태로 죽음("statemap::StateUndefinedException: transition invoked while in transition", 로그상 과거 3회 포함 총 4회) → planner_server·bt_navigator inactive 로 남아 목표 전부 거부. RViz와 무관한 간헐 버그. 수정: navigation.launch.py 에서 nav2 include 를 GroupAction+SetParameter(bond_timeout=0)로 감쌈(cart_ros2), start_guide.sh 에 controller/planner/bt_navigator 활성(active) 확인(90초) 추가 — 실패 시 안내 후 종료. 현재 고장 상태에서 확인 로직 검증(planner·bt inactive 감지). IMU: 재시작 후 /imu/data 101Hz 확인, 그러나 드라이버 CPU 여전히 약 103%(제조사 라이브러리 AHRS_Read 내부 대기로 추정) — 후속 과제.
- 2026-11-12 재실패 원인 = 내 실수: Nav2 활성 확인을 초기 위치 지정 전에 둠 → planner_server(전역 costmap)는 map 좌표(초기 위치 후 AMCL이 발행)가 있어야 활성화 완료 → 서로 대기하다 90초 초과("Timed out waiting for transform base_footprint→map" 222회) 후 스크립트가 내비게이션 종료. 확인을 초기 위치 지정 뒤로 이동. bond_timeout=0 적용 확인(lifecycle manager "connected with bond" 0회, 이전 실행 2회).
- 2026-11-12 마이크·스피커 안 됨: ① 부팅(18:50) 후 reSpeaker가 19:38에야 인식(USB-C 젠더, 부팅 시 미인식 → 재연결) → 19:17에 켜진 TTS 서버가 기본 장치 plughw:0,0(웹캠, 재생 없음)으로 잡혀 매번 aplay 실패. 수정: tts_server 재생 실패(장치 열기 오류) 시 스피커 다시 찾기 + 볼륨·증폭 기본값 재적용 후 한 번 더 시도(_refresh_speaker). 잘못된 장치 상태에서 시험 → reSpeaker 재탐지·재생 확인. 실행 중 TTS 서버는 재시작해야 반영. ② 마이크: start_guide(카메라 사람 감지 노드 실행 중)에서 녹음 2초 → 0.25초만 받고 멈춤, xHCI "buffer overrun slot 17 ep 2" 19:38 이후 4026건(녹음 시에만). reSpeaker가 USB-C 직결인데도 재발 — 어제 USB-C 시험은 카메라 영상만(사람 감지 AI 미실행)이라 통과. 카메라 영상 자체 vs AI의 GPU·메모리 부하 중 어느 쪽인지 확인 필요(사용자 실행 중이라 노드 정지 안 함).
- 마이크 수정(사용자 "시험 없이 바로 고쳐줘"): 녹음하는 동안 bus/mic_active 표시 → vision_obstacle_node 가 AI 추론 쉼(카메라 프레임은 계속 읽음, 30초 넘은 표시 무시). kiosk_server _MicActive(녹음·주변음 측정 감쌈, 중첩 안전, 시작 시 남은 표시 정리), vision 노드 수정 후 hospital_mission 재빌드(설치본은 복사본). 표시 생성·삭제 단위 시험 OK. 실제 효과는 start_guide 재시작 후 확인 필요(가설: GPU 추론의 메모리 대역 경쟁으로 USB 등시 전송 처리 지연 — 미검증).
- 2026-11-12 사용자 요청: start_guide.sh 를 RViz 켬/끔 분리 전(ed8ebc4) 버전으로 되돌리고 start_guide_norviz.sh 삭제(활성 확인 기능도 함께 빠짐). navigation.launch.py(use_rviz 기본 true·bond_timeout=0)는 유지 — 옛 스크립트로 띄워도 RViz 켜짐(예전과 동일). 마이크: reSpeaker 다시 꽂은 뒤(20:20:41)에도 녹음 0.25초·overrun 863 → 부팅 상태 문제 아님, 사람 감지 AI도 아님(일시 정지 중에도 동일). 남은 의심: 카메라 영상 전송과의 USB 충돌(어제 통과 시험은 사람 감지 노드 없이 내 시험 스크립트로 카메라만 열었음).
- 2026-11-12 사용자 요청: RViz 켬/끔 분리 스크립트 다시 복원(623b6c4 상태 — start_guide.sh 켬 + 활성 확인(초기 위치 뒤), start_guide_norviz.sh 끔). 되돌려도 마이크 증상 동일했음 → 스크립트와 무관 확인.
- 2026-11-12 마이크 원인 확정: reSpeaker를 젯슨 본체 USB-C(루트 포트 2, OTG 젠더)에 직결하면 녹음 사양을 125µs·192B로 알림 → 녹음 0.125~0.25초 후 멈춤·xHCI isoch buffer overrun(아무것도 안 켜도 실패). USB 허브 A-1(키보드·마우스 수신기 자리)에 꽂으면 10월과 같은 500µs·96B로 알림 → 3초 녹음 정상·오류 0, 카메라 동시 사용(29fps)에도 4초 정상·오류 0. 배제된 원인: 스크립트(RViz 켬/끔)·사람 감지 AI·카메라·IMU(일시정지 시험)·부팅 상태(재연결). 남은 확인: start_guide(주행+사람 감지) 전체 실행 중 녹음.
- 2026-11-12 "내과 이동 명령이 안 먹힘" 원인: 19:52 모터 컨트롤러 시리얼 응답이 깨져 붙어 옴("Garbage data", 두 응답 연결) → roboteq_controller_node 가 필드 수 초과로 query_pub_ 범위 밖 접근해 Segmentation fault(-11) 사망, 빈 메시지 받은 diff_tf 도 IndexError 로 사망 → 이후 /cmd_vel(제자리 회전 1.0rad/s) 은 나가는데 /odom·모터 명령 0, controller "Failed to make progress". 수정(cart_ros2 d38ab32, 빌드 완료): 필드 수 불일치 응답 버림·해석 실패 채널 미발행, diff_tf 값 2개 미만 메시지 무시, 두 노드 respawn(2초). 적용하려면 브링업 재시작 필요.
- 2026-11-12 저녁 사용자 확인: 마이크·스피커 정상, 주행 슬립 거의 없음(브링업 재시작 후 모터 드라이버 수정·Nav2 새 설정 적용 상태). 진행상황 기억(memory nav-collision-analysis) 갱신.
- 전원 모드가 자꾸 6코어로 돌아가던 원인: /etc/systemd/system/agv-bringup.service 의 Environment=AGV_POWER_MODE=4 가 boot_prep_root.sh 기본값(3)을 덮어씀 → 브링업 재시작마다 4. 프로젝트 원본 scripts/agv-bringup.service 를 3으로. 설치본(/etc) 반영은 sudo 필요(사용자).
- 2026-11-12 "너무 느림(2~3배 빨라야)" 원인: 모터 속도 환산 계수 오류. rosbag(nav_20261111_221640) 안정 구간 회귀 — 실제/명령 = 0.156(좌·우 바퀴, 직진 508·회전 552 표본 모두 동일, 잔차 0.02m/s), odom≈지도 기준 실제 속도(위치 계산은 정확). 즉 설정 0.6 → 실제 0.09m/s. 수정: query.yaml wheel_circumference 0.15→0.0234(=0.15×0.156, 실제 둘레 0.6594÷감속비 약 28과 일치), Nav2 한도를 실제 값으로 max_vel_x 0.30·theta 0.35·acc 0.3/-0.5·theta 0.6/-0.8, 복구 회전 1.0/0.4/3.2→0.5/0.2/1.0, return_home_watcher 정렬 상한 0.8→0.35·최소 0.12→0.08·위글 0.4→0.25(예전 부풀린 값). 백업 agv.yaml.bak_before_speed_calib_20261112. 적용: 브링업 재시작 + start_guide 재실행.
- 2026-11-12 밤 마이크·스피커 다시 먹통 → 근본 원인 정리: reSpeaker가 켜지는 상황에 따라 녹음 사양을 정상(500µs·96B)/비정상(125µs·192B)으로 알림. 비정상이면 실제로는 500µs 단위로 보내 xHCI "buffer overrun"(slot=reSpeaker) → 녹음 멈춤, 오류 누적 시 xHCI 이벤트 큐 넘침("unknown event type 37" 11회) → 장치 끊김 → 스피커도 먹통. 22:21 부팅(허브 A-1)부터 비정상, 22:57 재연결 후 정상. 대책: scripts/respeaker_check.sh(상태 확인, sudo fix 로 USB 재인식 최대 3회), boot_prep_root.sh 가 부팅·브링업 재시작 때 자동 fix, start_guide/start_voice_ui 시작 시 상태 표시·경고, kiosk 녹음 데이터 미수신 시 안내. 소프트웨어 재인식이 실제로 정상 사양을 만드는지는 다음 비정상 발생 때 확인 필요.
- 2026-11-12: 주행 속도 0.30→0.23 m/s(보정 전 실제의 약 2.5배)·회전 0.35→0.30, 회전 가감속 0.6/-0.8→0.4/-0.6, 직진 가속 0.3→0.25, Path/GoalAlign 전방점 0.3→0.4(좌우 흔들림 완화, cart_ros2 a61060c). reSpeaker 사용 중 자동 복구: kiosk 녹음 데이터 미수신 시 sudo -n /usr/local/sbin/respeaker_check.sh fix(2분 1회), start 스크립트도 시작 시 비정상이면 자동 시도. 설치는 sudo scripts/install_respeaker_autofix.sh(root 소유 사본 + sudoers.d/respeaker, visudo 검사). 직전 "fix 후 됨"은 fix가 아니라 22:57 장치 자체 재연결로 이미 정상이었던 것.
- 2026-11-13 주행 개선 보고서 NAV_IMPROVEMENT_20261113.md 작성(수정 전 nav_20261111_221640 vs 수정 후 nav_20261112_235325, scripts/compare_nav_bags.py 로 같은 기준 비교): 같은 25m 코스 292→125s, 실제/명령 0.16→1.00, 제어 주기 미달 170.6→1.3/분, 끊김 17→0, 복구 11→1, costmap 위치 이탈 57→0. 줄지 않은 것도 명시: 실제 좌우 흔들림 0.033→0.062 rad/s RMS(회전이 이제 그대로 전달), 근접 빈도 비슷(2.05→1.91/분), LiDAR 병합 버림 분당 동일, 명령 일정한데 실제 속도 출렁임 구간. 그림 docs/nav_report_20261113/speed_before_after.png. 녹화기: /scan_multi best-effort QoS 지정(수정 후 녹화에서 0개 기록된 문제).
- 2026-11-13 감속 급함: 최종 녹화 분석 — 목표 1 도착 때 명령 0.21→0.00 한 번에 와서 0.15→0 m/s 를 0.15초에(실제 0.98 m/s²). Nav2 는 목표 도착(0.45m 이내) 시 속도 0을 즉시 보내 DWB 감속 한도가 적용 안 됨(복귀 정렬·복구도 같음). 수정(cart_ros2): roboteq 드라이버에 속도 완만화 — /cmd_vel 은 목표값만, 20Hz 타이머가 직진 가속 0.25/감속 0.3 m/s²·회전 0.6/0.8 rad/s² 한도로 따라감, 명령 0.5초 끊기면 완만 정지(예전엔 마지막 명령 유지), 정지 중엔 재전송 안 함. query.yaml smooth_* 파라미터(끄기 smooth_enable false), Nav2 decel_lim_x -0.5→-0.3, 매 명령 INFO 로그→DEBUG(bringup.log 비대 원인). 시뮬: 0.23→0 정지 0.80초·8.3cm, 출발 0.95초. 적용: 브링업 재시작.
- 2026-11-13 환자 화면 음량 기본값(첫 화면 복귀 시) 60 → 30(사용자 요청, TTS 기준 크기보다 약 6dB 작게). 대기실 콜보드 호출은 CALLBOARD_VOL=60 고정(robotController.speak 에 vol 인자 추가). 헤드리스: 첫 화면 음량 30, 오류 없음.
- 2026-11-13 논문용 화면 캡처 scripts/capture_screen.py: 주행 중(kiosk_status moving/returning/arrived)일 때만 N초(기본 3)마다 보드 모니터(:1) 캡처, 대상 full(x11grab)/kiosk·rviz 창(xwd 로 창 자체 내용 — 다른 창에 가려져도 찍힘), --crop-top 으로 브라우저 탭·주소창 제거(87px), 사진별 시각·상태·목적지·남은 거리 index.csv(엑셀용 UTF-8 BOM). 저장 /mnt/ssd/screenshots/screens_시각/. SSH에서 실행해도 :1 사용(XAUTHORITY 자동). xwd 를 ffmpeg 표준입력으로 주면 형식 인식 실패 → 임시 파일 경유.
- 2026-11-13 복귀 후 방향·벽 정렬이 크게 돌며 좌우로 여러 번 오가던 문제: 로그상 방향 정렬이 목표 84° 를 두고 ±60° 를 약 6번 왕복. 원인 ① return_home_watcher 가 루프마다 rclpy.spin_once 로 수신 '1건'만 처리 → TF·스캔이 밀려 몇 초 전 방향으로 제어(속도 보정 후 실제 회전이 6배 빨라져 심해짐) ② '느림' 판단(0.1초 순간값)이 가속 구간·밀린 값에 속아 최소 속도를 최대(0.335)로 올리고 안 내림. 수정: 수신을 백그라운드 executor 스레드로(항상 최신), 회전 제어를 scripts/rotate_ctl.py 로 교체 — 접근(오차 비례 0.8·지연 보상, 멈춤은 1.5초 실제 회전량으로 판단·다시 돌면 원래 속도) + 3° 안에서 멈춰 0.6초 뒤 재측정→남은 각만큼 짧게 미세 회전 반복(지연 0.1~0.8초에도 왕복 없음). 걸림 시 속도 단계 상향→위글(기존 유지). 로그에 데이터 지연(TF·라이다)·소요 시간·미세조정 횟수·벽 정렬 후 지도 방향 추가. 시뮬(가감속 0.6/0.8, 지연): 예전 방식은 지연 0.2초 이상이면 90초 안에 수렴 못 함(왕복 40~100회), 새 방식 152° 11초·40° 5초·벽 65° 6~7초, 왕복 0회, 오차 0.2° 이내. 가짜 로봇에 실제 함수 연결 시험도 통과. 적용: start_guide 재시작(감시 프로그램만 바뀜). 백업 return_home_watcher.py.bak_before_rotctl_20261113.
- 2026-11-13 start_guide(_norviz) 가 [4/4] 'PIN 설정됨' 직후 조용히 종료: 스크립트가 set -euo pipefail 인데 reSpeaker 확인을 RSP_STATE="$(확인)"; RSP_RC=$? 로 받아, reSpeaker 비정상(코드 2)이면 대입문 자체가 실패로 처리돼 경고·자동 복구 전에 종료(내 실수, 24cb405 부터 — 그동안은 reSpeaker 가 정상이라 안 드러남). '|| RSP_RC=$?' 로 수정(start_guide.sh·start_voice_ui.sh). 당시 reSpeaker 는 허브 1-4.1 에 있었으나 부팅 때부터 비정상 125µs, 소프트웨어 재인식 3회로 복구 안 됨 → 손으로 다시 꽂기 필요.
- 2026-11-15 조이스틱 정지 밀림(벽에 박을 뻔): 원인 ① 11-13 모터 드라이버 완만화(감속 0.3 m/s²)가 /cmd_vel 전체에 걸려 조이스틱에도 적용 ② 조이스틱 최고 속도 2.00 m/s·4.80 rad/s 가 11-12 속도 보정 전(실제=명령×0.156 → 실제 0.31 m/s) 값 그대로 → 보정 후엔 실제 2 m/s(모터 한계까지) 요구, 0.3 감속이면 1.2 m/s 에서 4초·2.3m 밀림. 수정(cart_ros2 93dd41f): 드라이버에 조이스틱 전용 입력 /cmd_vel_joy — 가속 0.5/감속 1.0 m/s², 회전 1.5/2.0 rad/s², 조이스틱 명령 중(+놓고 멈출 때까지) /cmd_vel 무시, 신호 0.5초 끊기면 빠른 정지, 모든 입력 공통 안전 상한 0.5 m/s·1.0 rad/s(query.yaml joy_*·max_*_vel). ~/aml_joystick.sh: 0.30 m/s·0.75 rad/s + -r cmd_vel:=/cmd_vel_joy. ~/pub_joycmd.py(예전 조이스틱, max_v 6.0!): max_v 0.5·max_w 0.75·mid 0.25/0.25·/cmd_vel_joy. 백업 *.bak_before_joy_20261115. 시험(새 드라이버 실행 파일을 ROS 도메인 77 + 가짜 시리얼 포트로): 조이스틱 0.30→놓기 0.3초·5.2cm, Nav2 도착 0.8초·9.4cm(유지), Nav2 주행 중 L1 잡으면 정지 유지→놓으면 Nav2 복귀, 2.0 요구→0.5 제한, 신호 끊김 0.5초 뒤 0.3초 정지, 회전 0.75→놓기 0.4초·9°. teleop_node 도 /cmd_vel_joy 로만 0.30/0.75 발행 확인. 적용: 브링업(모터 드라이버) 재시작 필요 — 그 전엔 새 조이스틱 스크립트로는 안 움직임.
- 2026-11-15 '특정 위치에서 회전을 힘들어함': 자료 확인 — 11-13 03:55 복귀 출발(목적지에서 약 180° 뒤돌기)에서 '진행 없음'(10초 안에 0.5m 못 감) 8회 + 대기·후진·회전 복구, 경고는 그 외 없음. 같은 자리에서 완만화 전 녹화(11-12 23:53)·11-13 03:41 도 출발 10초째 1회씩 → 회전 최고 0.30 rad/s 라 180° 에 최소 10.5초, Galactic 진행 판정은 위치만 봐서 매번 회전이 끊김(구조적). 완만화 전 녹화 명령을 드라이버 완만화 계산에 넣어 보면 10초 회전량 130→125°(약 4%)라 완만화 자체 영향은 작음(정지 마찰·방향 전환 같은 폐루프 영향은 녹화 없어 미확인). 수정(cart_ros2): progress_checker movement_time_allowance 10→20초, 드라이버 회전 가감속 0.6/0.8→1.5/2.0 rad/s²(평소 회전은 Nav2 acc_lim_theta 0.4 가 더 작아 영향 없음, 직진 완만화 유지). 복귀 정렬 시뮬(1.5/2.0): 왕복 0회·시간 비슷. 적용: 브링업 재시작(드라이버)+start_guide 재시작(Nav2). 다음 주행 때 record_nav_bag.sh 로 뒤돌기 녹화 권장.
- 2026-11-15 마이크·스피커 또 안 됨: 20:31 부팅 때 reSpeaker 비정상 125µs·부팅 자동 복구 실패 → 20:33 서버들이 비정상 장치로 시작(TTS 'Please speak now.' 5~9초 대기 후 버림) → 20:36:51 사용자가 다시 꽂아 정상 500. 그 뒤 직접 시험: 6채널 2초 녹음 정상(2.00초 분량), TTS /tts 재생 정상. 근본 원인: 11-13 02:59 이후 부팅 4번 모두 비정상으로 켜지는데, respeaker_check.sh fix 의 authorized 0→1 은 드라이버만 떼었다 붙여 장치가 설정을 다시 보고하지 않음(커널 로그상 장치 번호가 부팅 때 그대로 3) → 한 번도 복구 못 함(11-12 '복구됨'도 장치 자체 재연결이었음). 수정: fix 를 USB 리셋(USBDEVFS_RESET, 다시 꽂을 때와 같은 버스 리셋·전원 유지)으로 교체, 리셋 전후 장치 번호 기록. 커널 5.10 이라 포트 끄기 없음. 적용: sudo ./scripts/install_respeaker_autofix.sh 로 관리자 사본 갱신. 확인: 다음 부팅 때 logs/boot_prep.log '리셋 후 장치번호'·'최종 상태'. 안 되면 전원까지 끊어야 함(전원 스위치 달린 허브 등). 백업 respeaker_check.sh.bak_before_usbreset_20261115.
- 2026-11-15 '안 되는데'(재설치·다시 꽂은 뒤): reSpeaker 는 정상 500(20:50:30 다시 꽂음, 장치 18). tts_server.log 에 'aplay 실패: Device or resource busy' 3회 — TTS 는 재생을 잠금으로 하나씩만 하므로 자기 충돌 아님, 스피커를 여는 다른 프로그램은 PulseAudio 뿐(reSpeaker 가 PulseAudio 기본 스피커·마이크였음, 보드 Chromium 20:34:59 실행 중, 다시 꽂을 때 PulseAudio 가 장치 확인). 화면 코드는 서버 TTS 실패 시 브라우저 음성으로 대신 읽어 보드 Chromium 이면 PulseAudio 로 reSpeaker 를 또 잡는 악순환 가능. 수정: pactl set-card-profile <reSpeaker> off(지금 세션 즉시), install_respeaker_autofix.sh 에 udev 규칙 89-respeaker-no-pulseaudio.rules(PULSE_IGNORE=1, 다음 연결부터) 추가 — 재설치 필요. 이후 시험: /tts 재생·/listen 녹음(9초, 무음이라 빈 결과·오류 없음) 정상.
- 2026-11-15 스피커 무음 근본 원인 조사: 사용자 확인 '안 들림'·'말해도 인식 못 함'. 측정 — 마이크 정상(손뼉 원음 채널 최대 17,000~20,000, '아—' 처리 채널 8,547, 음성 감지기도 말 시작 판정), 스피커: 소리 데이터는 장치까지 감(오류 없음·장치 에코 제거 채널 반응)인데 원음 마이크에 거의 안 잡힘. 장치 USB 제어(Seeed 위키: GPO 리소스 20, 읽기 cmd 0·길이 6 — 길이 5 면 상태 66 오류, 값 6개 = 핀 번호 순 X0D11·30·31·32·33·39 를 X0D11·X0D33 토글로 확인)로 앰프 핀 X0D31 읽음 → 21:26 다시 꽂은 뒤 기본값 0 = 앰프 켜짐 → 앰프 핀 원인 아님. 배터리 26.1 V·5V 4.99 V(11-12 정상 때와 같음). 삐 크기별 반응 −24/−12/−1 dBFS → +7.8/+10.2/+22.0 dB, −12→−1 구간 입력 +11 dB 에 출력 +12 dB 로 비례(전원 부족이면 큰 소리에서 안 늘어남) → 앰프는 동작, 스피커가 앰프 출력과 전기적으로 안 이어진 상태(커넥터 접촉·단선)로 판단 — 오늘 reSpeaker 를 6번 넘게 뽑았다 꽂음. 추가: scripts/respeaker_ctl.py(핀 읽기·앰프 켜기, 상태 바이트 확인), scripts/audio_selftest.py(삐를 내고 마이크로 받아 스피커·마이크 실제 동작 판정, 기준 25 dB — 스피커 고친 뒤 정상 값으로 재보정), start_guide·start_voice_ui 시작 때 자가 점검 표시, install_respeaker_autofix.sh 에 장치 제어 권한 udev(90-respeaker-usb.rules)·앰프 켜기. 내 실수: 첫 핀 읽기에서 상태 바이트(66=실패)를 안 보고 '켜짐'이라 판정했다가 바로잡음.
- 2026-11-15 사용자가 붙인 BrokenPipeError(/listen): 결과를 돌려주기 전에 요청한 쪽이 연결을 끊음(화면 뒤로·처음으로·화면 전환 시 recognizer.cancel, 또는 내 시험 curl 38초 제한 — 21:16:28 요청이 화면 요청과 마이크 잠금을 두고 겹쳐 38초 넘게 걸림). 서버는 정상, 결과만 버려짐. _send_json 에서 끊김을 잡아 한 줄 안내로(예전엔 추적 메시지 2번). whisper 직접 측정: 5.3초 한국어 1.9초·정확(GPU) → 인식 엔진은 정상. '말해도 인식 못 함'은 스피커 무음으로 '말씀해 주세요' 안내가 안 들려 녹음 시작(안내 재생 끝난 뒤) 전에 말하게 되는 것이 유력(화면은 안내 재생 중에도 듣기 화면). 적용: 안내 서버 재시작 때.
- 2026-11-15 사용자 요청 '잘 되던 때의 마이크·스피커 방식으로': 마지막 정상 확인 69c7955(11-12 21:33) 이후 오디오 변경 정리 — TTS 재생(tts_server.py)·녹음 설정(run_app.sh·serve.sh)·녹음 판단 로직은 그때와 동일, 추가된 건 자동 복구·점검·PulseAudio 무시·권한뿐. 되돌림: start_guide.sh·start_voice_ui.sh·boot_prep_root.sh 를 69c7955 버전으로(reSpeaker 확인·자동 복구·앰프·자가 점검 호출 제거), kiosk_server.py 의 녹음 미수신 시 자동 복구 호출 제거(BrokenPipe 한 줄 안내는 유지 — 오디오와 무관). 시스템 설정은 scripts/revert_audio_1112.sh(sudo): udev 89·90 규칙·sudoers·관리자 사본 삭제, 재연결 기다려 PulseAudio 에서 reSpeaker 다시 켜고 기본 장치로, 끝에 자가 점검 1회. 음량 기본값 30(사용자 요청)은 유지. audio_selftest.py·respeaker_ctl.py 는 수동 도구로만 남김.
- 2026-11-15 22:13 사용자 '지금은 잘 됨' → 원인 분석. 내 측정 오류 발견: reSpeaker 자기 마이크(원음 채널 2~5 포함)는 에코 제거로 자기 스피커 소리를 지워, 잘 울릴 때도 '삐'가 −2~+10 dB 로만 잡힘 → 21:35 '커넥터 문제' 결론은 틀린 측정에 기댄 것. 독립 감지기로 웹캠 마이크 사용(정상 '삐' +81~+101 dB). PulseAudio A/B(웹캠 마이크): 끔 +84 dB · 켬 +90 dB → PulseAudio 는 스피커 무음 원인 아님. 정리: ① 부팅마다 125µs(다시 꽂기만 해결) ② 20:50 PulseAudio 가 잠깐 장치를 잡아 TTS busy 3회 ③ 21:00~21:44 정상 사양인데 스피커 무음(21:09 사용자 확인) — USB 다시 꽂기 4번(21:01·21:03·21:06·21:26)으로 안 됐고 21:44 스피커 커넥터 다시 꽂기+USB 다시 꽂기 후 해결, 앰프 핀 켜짐·PulseAudio 무관 → 스피커 커넥터 접촉 가능성 가장 큼(증명은 아님) ④ '인식 못 함'은 ①③으로 안내가 안 들려 녹음 전에 말함 + 내 시험 요청 겹침. audio_selftest.py 를 웹캠 마이크 판정으로 수정(기준 40 dB).
- 2026-11-15 주행 '와리가리' 재발(사용자): 드라이버가 20:31 부팅부터 오늘 바꾼 회전 완만화 1.5/2.0 로 돌고 있었음(이전 0.6/0.8). 근본 원인 분석(11-12 23:53 녹화): 직진 111초 동안 Nav2 회전 명령 좌우 방향 바뀜 110회, 0.1초마다 바뀐 크기 39% 가 0.04 rad/s 초과·최대 0.316 — DWB 기본 Standard 생성기는 가속 한도를 sim_time(1.2초) 동안으로 계산해 주기당 ±0.48 까지 허용 → 11-12 에 넣은 acc_lim_theta 0.4 가 실제로는 안 지켜짐. 또 다음 명령 기준인 현재 회전속도를 바퀴 오도메트리(/odom, 연속 값 튐 0.050·9Hz)로 받음(/odometry/filtered 는 0.022·18Hz). 드라이버 완만화 0.6/0.8 은 명령 재생 계산상 흔들림을 약 6% 눌러 주던 것 — '평소 주행 영향 없음'이던 내 판단 틀림. 수정(cart_ros2): FollowPath trajectory_generator_name LimitedAccelGenerator + sim_period 0.1(주기당 0.04 rad/s), controller_server odom_topic /odometry/filtered(지금 20Hz 확인), 드라이버 회전 완만화 0.6/0.8 복귀. 대가: 모서리에서 회전 시작이 조금 늦음(0→0.3 rad/s 0.75초). 적용: 브링업 재시작 + start_guide 재시작. 확인: 넓은 곳 시험 주행 + record_nav_bag.sh 로 녹화해 compare_nav_bags.py 로 11-12 와 비교.
- 2026-11-15 22:36~ 시험 주행 '완전 엉망'(사용자) → 되돌림. navigation.log: Limited 생성기로 'No valid trajectories out of 400!' 반복 → Failed to make progress → Controller patience exceeded → 목표 포기(종료 때 bt_navigator -11). 원인: 주기당 한도(직진 0.025 m/s·회전 0.04 rad/s)가 너무 좁아 정지 상태에서 고를 수 있는 속도가 거의 0 뿐 → 유효 궤적 없음. agv.yaml 을 수정 전과 동일하게(odom_topic·LimitedAccel 제거, cart_ros2 revert 커밋). 드라이버 회전 완만화는 0.6/0.8 유지(11-13~11-15 오후 문제없던 값, 시험 주행 실패와 무관). 와리가리 근본 원인(Standard 생성기 주기당 ±0.48 허용)은 그대로 — 다음엔 Limited 로 바꾸지 말고 Standard 유지한 채 다른 방법(예: 회전 샘플·Oscillation·PathAlign 조정, 또는 Limited + 가속 한도 크게)을 녹화·시뮬로 먼저 검증할 것.
- 2026-11-15 밤 '지금 주행 방식은 유지하고 와리가리만 조금 덜'(사용자): Nav2 는 건드리지 않고 드라이버 회전 완만화만 0.6/0.8 → 0.45/0.6(cart_ros2). 11-12 녹화 명령 재생: 직진 좌우 바뀜 98→74회(−24%), 큰 흔들림 0.228→0.218, 뒤돌기 10초 회전 125→122°. 더 강한 안: 0.35/0.5(−33%)·0.25/0.4(−49%, 회전 굼뜸). 복귀 정렬 시뮬 이상 없음, 조이스틱 무관(joy_* 한도). 재생 계산은 열린 루프라 실주행 확인 필요. 적용: 브링업 재시작.
- 2026-11-15 밤 0.45/0.6 실주행: 회전이 약해져 슬립 잦음(사용자) → '기존 와리가리 버전으로' → 드라이버 회전 완만화 1.5/2.0(오늘 20:29 상태)로 복귀, Nav2(agv.yaml)도 20:29 상태와 동일(Standard 생성기·/odom, 진행 판정 20초). 정리: 드라이버 회전 완만화를 세게 하면 와리가리는 줄지만 회전이 약해져 슬립 — 이 손잡이로는 둘 다 못 잡음. 적용: 브링업 재시작.
- 2026-11-15 밤 '특정 구역 회전 시 슬립·덜컹·회전 못 함' 원인 조사(scripts/analyze_rotation.py 새로 — /odom 회전=바퀴 엔코더, /odometry/filtered 회전=자이로만(ekf.yaml) 비교로 슬립·걸림·덜컹·위치 판별). ① 녹화: 11-12 23:53 회전 4구간 정상(슬립 7~16%), 11-11 9구간 중 1구간 '걸림' — 위치 (-19.2,36.5)=초기 위치(복귀 정렬). 그 구간 상세: 모터 명령 [22,−22] 일정한데 바퀴 실제 속도(홀) 왼쪽 −67→+13→+60→−120→+41 로 앞뒤로 튀고 오른쪽은 자주 0, 전류 작고 부호 바뀜 → 아주 느린 속도 명령에서 모터 컨트롤러 속도 제어가 출렁임(헌팅) = 덜컹·슬립·안 돎. 정상 회전(모터 명령 수백)은 매끈. ② 오늘 복귀 정렬: 22:10(1.5/2.0) 문제없음, 22:43(0.6/0.8)·22:57(0.45/0.6)·23:18(1.5/2.0) 모두 미세 회전 0.06~0.18 rad/s 에서 안 돎 → 캐스터 위글 → 완만화 설정과 무관. ③ Nav2: 같은 목적지(−23.34,57.75)·같은 설정에서 22:10 뒤돌기 정상, 23:18 '진행 없음' → 가끔 발생. 결론: 느린 제자리 회전(모터 수십 rpm 대)에서 Roboteq 폐루프 속도 제어가 불안정(+캐스터 저항) — 드라이버는 MMOD 1·EPPR 1024 만 보내고 PID·피드백 센서(엔코더/홀) 설정은 컨트롤러 저장값. 다음: 모터 드라이버 잠깐 멈추고 컨트롤러 설정(~KP/~KI/~KD/~BLFB/~MAC 등) 읽기 → 조정, 또는 느린 제자리 회전 명령 피하기(최소 회전 속도).
- 2026-11-15 23:47 모터 컨트롤러 설정 읽음(드라이버 시작 때 ~ 명령 읽기만 → bringup.log '컨트롤러 설정(읽기만)'): MMOD=1(폐루프 속도) · **KP=KI=KD=0(공장 기본값)** · BLFB=1(속도 측정 = 홀 센서) · EMOD=0(엔코더 미사용) · MXRPM 1000 · MAC/MDEC 20000 · ALIM 200 · ICAP 100 · CLERD 2 · BLSTD 2 · BPOL 4. Roboteq 매뉴얼 v2.0: KP/KI 'Do not use default values… Use P=0, I=1, D=0 in closed loop speed mode', 'In Speed Mode, the Integral component… is the most important and must be set first', 속도·위치 모드(MMOD 6)는 'especially effective for accurate control at very slow speeds'. → 느린 회전 멈춤·덜컹의 근본 원인 유력: 속도 보정 이득 0 이라 실제 속도가 모자라도 힘을 더 안 줌. 드라이버에 speed_pid_enable/speed_kp/ki/kd(기본 꺼짐, RAM 만·EEPROM 저장 안 함) 추가(cart_ros2), 가짜 포트로 '^KI 1 1000000' 전송 확인. 켜기 전 사용자 승인·주의 시험 필요(출발·정지 반응이 바뀔 수 있음).
- 2026-11-16 00:07 외과 도착 후 복귀 뒤돌기에서 약 80초 못 돎(진행 없음 4회) → Nav2 강제 회전 복구(spin 1.57) 때는 돎(00:08:32~00:09:04). 같은 자리 22:59·23:19 도 같음. → 그 자리에서 Nav2 회전 명령이 약하거나 없을 가능성, 명령값 없이는 판별 불가 → 실시간 감시 도구 scripts/live_drive_monitor.sh(.py): /cmd_vel·/odom·/odometry/filtered(자이로)·/motor_*·/scan_multi 최소 거리·/amcl_pose·Nav2 /rosout 경고·kiosk_status 를 받아 걸림(회전 명령 있는데 안 돎)·명령없음(주행 중 명령 0/안 옴)·슬립·덜컹을 그 자리에서 알리고 앞 20초~뒤 5초를 /mnt/ssd/rotation_events/live_*/NNN_종류_시각.csv 로 저장(읽기만). 시험: 정지 상태 6초 수신(바퀴 10Hz·자이로 20Hz·스캔 12Hz·모터 20Hz), 저장 정상. 모터 PID 는 아직 꺼진 상태.
- 2026-11-16 00:21~00:28 실시간 감시로 외과 왕복 기록(live_20261116_002141). 뒤돌기 멈춤(00:23:48~00:25:35, 1분 47초) 원인 확정: Nav2(DWB)가 복귀 경로가 바로 뒤에서 시작하자 좌/우를 못 정해 ±0.02 rad/s(모터 9rpm)만 번갈아 명령(가끔 −0.30 한 번 냈다가 1초 안에 −0.02 로 줄임) → 정지 마찰 못 이겨 안 돎 → 진행 없음 4번·후진 복구 → 강제 회전 복구(+0.50, 모터 304)에서야 돎. 그 자리 최소 장애물 0.86~0.96 m(차체 회전 반경 0.64 m). 수정: return_home_watcher 가 복귀 요청 직전 Nav2 경로 계획기(compute_path_to_pose)로 복귀 경로만 받아 1 m 앞 점을 향해 먼저 제자리 회전(기존 회전 제어기, 허용 8°), 45° 미만이면·장애물 0.79 m 미만이면·경로 못 받으면 생략, 사용자 새 요청 오면 중단(RETURN_PREROTATE=0 으로 끔). 가짜 로봇 시험 4경우 정상(뒤 경로 166° 10.5초), 실제 경로 계획기 응답 0.1초 확인. 감시 도구: 슬립 거짓 경보 수정(45→5건), '미세명령' 판별 추가. 별도: 외과 가는 길 'Timed out … acknowledge goal'·대기 복구(CPU 부하) — 나중에.
- 2026-11-16 논문 실험 진행 도우미 scripts/experiment.py (1 = 표 1 AI 안내 수용률·응답 시간, 2 = 표 2 자율주행 안내 성공률, 표 = 표 1·2 + summary.md). 기록 /mnt/ssd/experiments/main/(exp1.csv·exp2.csv·config.json, 이어서 기록·u 로 직전 취소). 키오스크에 실험 기록 logs/experiment_events.jsonl 추가(listen 장소·recommend 추천 진료과·nav 안내 시작·register 접수 진료과 + '말이 끝난' 시각) — 개인정보·문장 기록 안 함. 자동: 실험 1 AI 추천·그대로 선택(위치: 같은 장소 /nav, 접수: 같은 진료과 접수)·응답 시간(말 끝 → 결과 응답), 실험 2 상태 전환 시각·Nav2 진행 실패/복구·복귀 정렬, 실측 오차를 넣으면 성공 기준 숫자로 O/X 제안. 가짜 사건·상태로 두 실험 시험 정상. 주의: Nav2 도착 허용 오차 0.45 m·방향 제한 없음 → '30cm·10°' 기준이면 설계상 실패가 나올 수 있음. 적용: 안내 서버 재시작(start_guide).
- 2026-11-18: 실험 2 기록 도우미 추가(scripts/experiment2.py·.sh) — 도착·복귀 단계별 O/X, 전체 한 바퀴 자동 계산, 도착 실패 시 f(옮김)·r(복귀 요청) 흐름, Nav2 실패·복구·정렬 결과·로봇 추정 오차 자동 기록, 표 2(exp2_summary.md) 생성. 키오스크·로봇 코드는 변경 없음
- 2026-11-18: 실험 2 목적지 5곳(내과·외과·소아청소년과·산부인과·마취통증의학과) × 4회 = 20회로 변경 — 메뉴 Enter 는 목록 순서대로 돌아가며 목표 횟수 못 채운 곳 제안, 숫자 1~5 로 직접 선택, 목적지별 진행(n/4) 표시
- 2026-11-19: RViz 자동 녹화 scripts/rviz_recorder.py — Nav2 목표 시작(navigation.log 'Begin navigating') 또는 키오스크 상태 moving~aligning 이면 녹화, 끝나고 5초 뒤 멈춤(안내 1회 = 영상 1개). RViz 창만(가려져도 내용 녹화, 홀수 크기는 1px 잘라 짝수로 — 안 하면 하드웨어 변환이 검은 화면), 못 찾으면 화면 전체. GStreamer ximagesrc → nvv4l2h264enc → 조각 MP4, 1080p·10fps CPU 약 0.3코어·4 Mbps. 저장 /mnt/ssd/rviz_videos/<날짜>/ + index.csv. --now 수동 녹화. 가짜 로그로 자동 시작·종료·Nav2 결과 기록, 수동 Ctrl+C 종료 시험 정상(실제 RViz 창 녹화는 RViz 켜고 확인 필요)
- 2026-11-19: 키오스크 웹 화면 녹화 scripts/ui_recorder.py — 녹화 전용 Chromium(전용 프로필 /mnt/ssd/ui_recorder/profile)을 앱 모드(--app)로 보드 화면(:1)에 띄워 그 X 창만 녹화 → 주소창·탭·창 제목줄 없음. 브라우저 언어 한국어·번역 꺼서 '번역' 팝업 제거(영어 브라우저면 오른쪽 위에 뜸 확인). 기본 1600×900 창, --full 전체 화면(키오스크 모드 1920×1080), 15fps·하드웨어 인코더·조각 MP4, /mnt/ssd/ui_videos/<날짜>/ + index.csv, Ctrl+C 로 녹화 끝·창 닫힘. 주의: 크롬은 명령줄을 한 줄 문자열로 바꿔 /proc cmdline 을 공백으로 검사해야 함. 창 모드·전체 화면 둘 다 시험 정상(장면 확인)
- 2026-11-21: 논문(한국로봇학회_서재원 수정.hwp) 대조용 — 실험 2 시뮬레이션 sim/(fake_robot.py 가짜 로봇·지도 기반 라이다·명령 지연 0.25초·회전 정지마찰, sim_nav.launch.py 실제 agv.yaml·my_map Nav2, nav_request_watcher_sim.py 실제 감시기를 불러 요청 폴더만 시뮬 전용으로(실제 코드는 런치 인자를 무시하고 실제 버스 폴더 고정 — 그대로 띄우면 실제 요청 폴더를 건드림), 실제 return_home_watcher, sim_exp2.py 자동 평가·표 2). ROS_DOMAIN_ID 77·로컬 전용. 1회 시험: 내과 56초(실측 57~60)·한 바퀴 146초(실측 154), 위치 추정 오차 6cm, 멈춘 위치 31cm(Nav2 xy_goal_tolerance 0.45 때문 — 30cm 기준과 충돌). 실제 로그 복원: 11-18·19 왕복 13회 Nav2 26/26 성공·복구 0·정렬 13/13
