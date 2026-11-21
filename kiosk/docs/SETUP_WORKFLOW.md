# SETUP_WORKFLOW.md — 웹 기획 ↔ VS Code 실행 연동 셋업 지시서

> 이 파일은 Claude Code(터미널/VS Code 확장)가 읽고 **그대로 실행**하도록 작성된 지시서입니다.
> 목적: claude.ai 웹에서 "기획"하고, VS Code의 Claude Code에서 "실행"하는 왕복 워크플로우의
> 기반이 되는 폴더/파일/워크스페이스를 자동으로 생성하는 것.

---

## 0. 배경 (Claude Code가 알아야 할 맥락)

- 실행 환경: NVIDIA Jetson (arm64, Ubuntu). eMMC(`/`)는 용량이 작고 거의 가득 참.
- 대용량 데이터는 NVMe SSD(`/mnt/ssd`)에 저장한다. eMMC를 채우지 않는다.
- claude.ai 웹과 Claude Code는 대화 기록이 자동 공유되지 않는다.
  따라서 **파일(PLAN.md, CLAUDE.md, PROGRESS.md)과 Git이 두 세계를 잇는 유일한 다리**다.
- 이 워크플로우의 원칙: "대화를 동기화"하지 말고 "문서를 동기화"한다.

---

## 1. 프로젝트를 생성할 위치

프로젝트 루트는 SSD에 만든다 (eMMC 절약):

```
/mnt/ssd/projects/<PROJECT_NAME>/
```

`<PROJECT_NAME>`은 사용자가 지정한다. 지정이 없으면 사용자에게 한 번 물어본다.

---

## 2. 생성할 폴더 구조

다음 구조를 정확히 생성한다:

```
/mnt/ssd/projects/<PROJECT_NAME>/
├── CLAUDE.md              # 프로젝트 상시 맥락 (Claude Code가 자동으로 읽음)
├── PLAN.md                # 웹에서 기획한 내용이 들어오는 곳 (실행 대상)
├── PROGRESS.md            # VS Code에서 실행한 결과/진행 상황 기록
├── HANDOFF.md             # 웹 <-> VS Code 왕복 시 주고받는 요약 (복붙용)
├── src/                   # 실제 소스 코드
├── docs/                  # 기획 문서, 설계 자료
├── scripts/               # 유틸리티 스크립트
└── .gitignore
```

---

## 3. 각 파일의 초기 내용

### 3-1. CLAUDE.md

```markdown
# CLAUDE.md — 프로젝트 상시 맥락

## 프로젝트 개요
(여기에 이 프로젝트가 무엇인지 한두 문단으로 적는다. 웹 기획 단계에서 갱신한다.)

## 현재 목표
(지금 무엇을 향해 가고 있는지. PLAN.md의 상위 요약.)

## 작업 규칙
- 대용량 산출물은 /mnt/ssd 아래에만 저장한다. eMMC(/)를 채우지 않는다.
- 코드 변경 후에는 반드시 PROGRESS.md를 갱신한다.
- 한 작업 단위가 끝나면 git commit 한다.
- 웹으로 넘길 요약은 HANDOFF.md에 작성한다.

## 기술 스택 / 환경
- Jetson (arm64, Ubuntu)
- (사용 언어/프레임워크를 여기 적는다)
```

### 3-2. PLAN.md

```markdown
# PLAN.md — 실행 대상 기획

> 이 파일은 claude.ai 웹에서 기획한 내용을 붙여넣는 곳이다.
> Claude Code는 이 파일을 읽고 그대로 구현한다.

## 이번 사이클의 목표
(웹에서 채운다)

## 작업 항목 (체크리스트)
- [ ] (작업 1)
- [ ] (작업 2)
- [ ] (작업 3)

## 제약 / 주의사항
(웹에서 채운다)
```

### 3-3. PROGRESS.md

```markdown
# PROGRESS.md — 실행 진행 기록

> Claude Code가 작업할 때마다 여기에 무엇을 했는지 append 한다.

## 로그
- (YYYY-MM-DD HH:MM) 초기 셋업 완료.
```

### 3-4. HANDOFF.md

```markdown
# HANDOFF.md — 웹 <-> VS Code 인수인계 요약

> VS Code에서 작업이 끝나면 이 파일에 "웹에 넘길 요약"을 작성한다.
> 사용자는 이 내용을 복사해 claude.ai 웹에 붙여넣고 다음 기획을 이어간다.
> 반대로 웹에서 새 기획이 나오면 PLAN.md로 옮긴다.

## 마지막 사이클 요약
(무엇을 했고, 무엇이 남았고, 다음에 무엇을 기획해야 하는지)

## 웹에 물어볼 질문 / 결정이 필요한 사항
-
```

### 3-5. .gitignore

```
node_modules/
__pycache__/
*.pyc
.venv/
dist/
build/
*.log
.DS_Store
```

---

## 4. VS Code 워크스페이스 파일 생성

프로젝트 루트에 `<PROJECT_NAME>.code-workspace` 파일을 만든다:

```json
{
  "folders": [
    { "path": "." }
  ],
  "settings": {
    "files.exclude": {
      "**/__pycache__": true,
      "**/.venv": true
    }
  }
}
```

---

## 5. Git 초기화

프로젝트 루트에서:

```bash
cd /mnt/ssd/projects/<PROJECT_NAME>
git init
git add .
git commit -m "chore: initial workflow scaffold (web-plan <-> vscode-exec)"
```

(GitHub 연동을 원하면, 사용자가 원격 저장소 URL을 줄 때 `git remote add origin <URL>` 후 push 한다.
현재 단계에서는 로컬 커밋까지만 한다.)

---

## 6. 셋업 완료 후 Claude Code가 보고할 것

셋업이 끝나면 다음을 사용자에게 출력한다:

1. 생성된 전체 폴더 트리 (`tree` 또는 `find` 결과)
2. `df -h /` 와 `df -h /mnt/ssd` 를 실행해, eMMC가 아니라 SSD에 만들어졌음을 확인
3. 다음 사이클을 위해 사용자가 할 일 안내:
   - "웹에서 기획한 내용을 PLAN.md에 붙여넣으세요"
   - "그다음 저에게 'PLAN.md 읽고 구현해줘'라고 말하세요"

---

## 7. 이후 반복 사이클에서 Claude Code의 행동 규칙

- 사용자가 "실행해줘" / "구현해줘"라고 하면:
  1. `CLAUDE.md`와 `PLAN.md`를 먼저 읽는다.
  2. PLAN.md의 체크리스트를 순서대로 구현한다.
  3. 완료 항목은 `- [x]`로 바꾼다.
  4. 한 항목이 끝날 때마다 PROGRESS.md에 로그를 append 한다.
  5. 작업 단위가 끝나면 git commit 한다.
  6. 마지막으로 HANDOFF.md에 "웹에 넘길 요약"을 작성한다.

- 사용자가 "웹에 넘길 요약 줘"라고 하면 HANDOFF.md 내용을 그대로 출력한다.
