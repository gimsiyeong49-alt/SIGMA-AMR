# SIGMA-AMR — 다국어 AI 에이전트 기반 자율주행 안내 로봇 (병원 안내)

한국로봇학회 논문 「공공기관에서 다국어 지원 AI 에이전트를 활용한 자율주행 안내 로봇 시스템」의
로봇 코드, 실험 기록, 시뮬레이션을 한곳에 모은 저장소입니다.

- 논문 내용과 코드의 대조, 실험 2 정리, 시뮬레이션 결과는 **[docs/논문_코드_대조_및_실험2.md](docs/논문_코드_대조_및_실험2.md)**를 보세요.

## 폴더 구성

| 폴더 | 내용 |
|---|---|
| `kiosk/` | 사용자 화면(웹 UI), 음성·AI 에이전트 서버, TTS 서버, 복귀·방향 정렬 감시기, 실험 기록 도구, 화면 녹화 도구 |
| `kiosk/sim/` | 실험 2 시뮬레이션(가짜 로봇·라이다 + 실제 Nav2 설정·지도·감시기 코드 그대로) |
| `ros2_ws/src/` | ROS 2 Galactic 패키지: 주행(Nav2 설정·지도·목적지), 라이다, 모터 컨트롤러, IMU, 지도 작성 등 |
| `experiments/real/` | 실측 기록: 실험 1(표 1), 실험 2(표 2), 키오스크 실험 사건 기록 |
| `experiments/sim/` | 실험 2 시뮬레이션 결과 |
| `tools/joystick/` | 수동 조종(조이스틱) 스크립트 |
| `docs/` | 논문·코드 대조 정리 |

## 하드웨어

- 연산: NVIDIA Jetson AGX Xavier (Ubuntu 20.04, ROS 2 Galactic)
- 주행: 차동 구동 AGV, Roboteq 모터 컨트롤러(`roboteq_controller`), 홀 센서 오도메트리 + IMU(Ntrex AHRS) → EKF
- 센서: RPLIDAR 2대(`sllidar_ros2`) → 병합(`ira_laser_tools`) → `/scan_multi`, 웹캠(사람 장애물 보조)
- 음성: reSpeaker XVF3800 마이크 어레이(칩 안에서 반향 제거·소음 억제), 스피커는 reSpeaker 출력에 연결

## 동작 흐름

**음성·AI 에이전트** (`kiosk/scripts/kiosk_server.py`)

1. 화면에서 언어(한·영·일·중)와 안내 유형(접수 안내 / 위치 안내)을 고른다.
2. reSpeaker 처리 채널(반향 제거·소음 억제 적용) → **Silero VAD**(신경망 말소리 감지)로 발화 구간 판별
3. **whisper.cpp**(ggml-medium, 언어별 진료과 어휘 프롬프트)로 받아쓰기 → 잡음·무음에서 생기는 환각 문구 필터
4. AI 에이전트(OpenAI `gpt-4o-mini`)
   - 위치 안내: 다국어 별칭 사전으로 먼저 찾고, 못 찾으면 AI 판단 → 목적지 결정
   - 접수 안내: 증상 문진 → 추천 진료과 + 다른 진료과 함께 제시
5. 결과를 선택한 언어의 화면과 **MeloTTS**(`kiosk/scripts/tts_server.py`) 음성으로 출력

**자율주행 안내**

1. 키오스크 → 요청 파일(`bus/nav_request/*.json`) → `nav_request_watcher` → Nav2 `NavigateToPose`
   (AMCL 위치 추정, NavFn 경로, DWB 제어, 설정 `ros2_ws/src/hospital_mission/config/agv.yaml`)
2. `kiosk/scripts/return_home_watcher.py`: 목적지 0.8 m 안 → 도착 안내 → 5초 뒤 복귀 경로 쪽으로 먼저 제자리 회전
   → 초기 위치 복귀 → 방향 정렬(AMCL 방향 → 라이다 벽 기준 미세 정렬)
3. 목적지 좌표: `ros2_ws/src/hospital_mission/map/map_labels.json`, 지도: `my_map.yaml/pgm`

## 실행 (로봇에서)

```bash
# 브링업(센서·모터·EKF)은 부팅 서비스로 먼저 떠 있어야 함
./kiosk/scripts/start_guide.sh          # 주행 + 초기 위치 지정 + 복귀 감시 + 음성·화면 서버 (RViz 켬)
./kiosk/scripts/start_guide_norviz.sh   # RViz 끔
# 화면: http://localhost:8000/
```

실험 기록 도구:

```bash
python3 kiosk/scripts/experiment.py 1     # 실험 1(표 1) 진행·기록
./kiosk/scripts/experiment2.sh            # 실험 2(표 2) 진행·기록
./kiosk/sim/run_sim_exp2.sh               # 실험 2 시뮬레이션(5곳 × 4회, 약 1~2시간)
```

## 이 저장소에 넣지 않은 것 (용량·보안·개인정보)

| 빠진 것 | 이유 / 받는 곳 |
|---|---|
| whisper.cpp 소스·빌드, `ggml-medium.bin` | 용량(약 2 GB) — whisper.cpp 공식 저장소에서 빌드·모델 받기 |
| MeloTTS 모델, 파이썬 가상환경(`.venv`) | 용량 — 설치 시 자동으로 받음 |
| OpenAI API 키(`.openai_key`), 주민번호 암호화 키, 관리자 PIN | 보안 |
| 실행 기록(`logs/`, `bus/`), 음성 받아쓰기 기록, 카메라 사진, 환자 데이터(`data/`) | 개인정보 |
| URDF 메시 `agv_body/urdf/cart_body.dae`(56 MB), 건물 안내도 사진 | 용량 / 개인 이름 포함 |

## 원본

- `kiosk/` ← 키오스크 프로젝트(`ui-dev` 브랜치, `c0b0b8e` 시점, 시뮬레이션 포함)
- `ros2_ws/src/` ← 로봇 ROS 2 작업공간(`db7b28d` 시점 + 그 뒤 작업 중 변경 포함)
