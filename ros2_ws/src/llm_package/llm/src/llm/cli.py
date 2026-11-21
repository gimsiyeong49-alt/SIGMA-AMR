import argparse
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Set, Tuple

from .nav_manager import NavTarget, NavigationRuntime


DEFAULT_STT_OUTPUT_DIR = Path("/mnt/ssd/cart_ros2/src/stt_package/stt/outputs")
DEFAULT_LABELS_PATH = Path("/mnt/ssd/cart_ros2/src/hospital_mission/map/map_labels.json")
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_FILE = PACKAGE_ROOT / ".llm_processed_files.json"


SYSTEM_INSTRUCTION = """
너는 병원 안내 로봇의 짧은 응답 생성기다.

규칙:
- 한국어로 답한다.
- 답변은 1~2문장으로 짧게 한다.
- 위치 정보는 제공된 병원 라벨 정보를 기준으로만 말한다.
- 모르는 정보는 지어내지 않는다.
- 위치를 찾으면 안내할지 물어본다.
""".strip()


YES_WORDS = [
    "응", "네", "예", "그래", "좋아", "맞아",
    "안내해", "안내해줘", "안내해 줘", "가자", "가줘",
    "데려다줘", "데려다 줘", "출발", "이동", "해줘", "해 줘",
]

NO_WORDS = [
    "아니", "아니야", "괜찮아", "됐어", "취소", "가지마",
    "필요없어", "필요 없어", "안 갈래", "멈춰", "정지", "그만",
]

LOCATION_HINT_WORDS = [
    "어디", "위치", "가는", "가려면", "알려줘", "안내",
    "데려다", "찾아", "몇층", "몇 층", "어딨어", "어디야",
]


def normalize_text(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", "", text)
    text = text.replace(".", "").replace("?", "").replace("!", "")
    return text


def load_processed(state_file: Path) -> Set[str]:
    if not state_file.exists():
        return set()

    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(data)
    except Exception:
        pass

    return set()


def save_processed(state_file: Path, processed: Set[str]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(sorted(processed), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def mark_processed(state_file: Path, processed: Set[str], resolved: str) -> None:
    processed.add(resolved)
    save_processed(state_file, processed)


def wait_until_file_stable(path: Path, timeout: float = 3.0) -> bool:
    start = time.time()
    last_size = -1

    while time.time() - start < timeout:
        if not path.exists():
            return False

        current_size = path.stat().st_size

        if current_size > 0 and current_size == last_size:
            return True

        last_size = current_size
        time.sleep(0.2)

    return path.exists() and path.stat().st_size > 0


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def load_map_labels(labels_path: Path) -> List[dict]:
    if not labels_path.exists():
        raise FileNotFoundError(f"map_labels.json 파일이 없습니다: {labels_path}")

    data = json.loads(labels_path.read_text(encoding="utf-8"))
    zones = data.get("zones", [])

    if not isinstance(zones, list):
        raise ValueError("map_labels.json의 zones 형식이 올바르지 않습니다.")

    return zones


def build_label_index(zones: List[dict]) -> List[Tuple[str, dict, str]]:
    items: List[Tuple[str, dict, str]] = []

    for zone in zones:
        name = zone.get("name", "")
        if name:
            items.append((normalize_text(name), zone, name))

        for alias in zone.get("alias", []) or []:
            if alias:
                items.append((normalize_text(alias), zone, alias))

    items.sort(key=lambda x: len(x[0]), reverse=True)
    return items


def match_location(
    user_text: str,
    label_index: List[Tuple[str, dict, str]],
) -> Optional[Tuple[dict, str]]:
    normalized = normalize_text(user_text)

    for keyword, zone, original_keyword in label_index:
        if keyword and keyword in normalized:
            return zone, original_keyword

    return None


def is_location_question(user_text: str) -> bool:
    normalized = normalize_text(user_text)
    return any(normalize_text(word) in normalized for word in LOCATION_HINT_WORDS)


def contains_word(user_text: str, words: List[str]) -> bool:
    normalized = normalize_text(user_text)
    return any(normalize_text(word) in normalized for word in words)


def is_yes(user_text: str) -> bool:
    return contains_word(user_text, YES_WORDS)


def is_no(user_text: str) -> bool:
    return contains_word(user_text, NO_WORDS)


def describe_location(zone: dict) -> str:
    name = zone.get("name", "해당 위치")
    description = zone.get("description", "")

    if description:
        return f"{name}는 {description}에 있습니다. 안내해드릴까요?"

    return f"{name} 위치를 찾았습니다. 안내해드릴까요?"


def ask_openai(model: str, user_text: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        return "OPENAI_API_KEY가 설정되어 있지 않습니다."

    payload = {
        "model": model,
        "instructions": SYSTEM_INSTRUCTION,
        "input": user_text,
        "temperature": 0.4,
        "max_output_tokens": 120,
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        url="https://api.openai.com/v1/responses",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="ignore")
        return f"OpenAI API 요청 실패: {exc.code} {err_body}"
    except Exception as exc:
        return f"OpenAI API 요청 실패: {exc}"

    try:
        result = json.loads(body)
    except json.JSONDecodeError:
        return "OpenAI API 응답을 해석하지 못했습니다."

    output_text = result.get("output_text", "")
    if output_text:
        return output_text.strip()

    texts = []
    for item in result.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in ("output_text", "text"):
                text = content.get("text", "")
                if text:
                    texts.append(text)

    if texts:
        return "\n".join(texts).strip()

    return "죄송합니다. 답변을 생성하지 못했습니다."


def yaw_deg_to_quaternion_z_w(yaw_deg: float) -> Tuple[float, float]:
    yaw_rad = math.radians(float(yaw_deg))
    return math.sin(yaw_rad / 2.0), math.cos(yaw_rad / 2.0)


def zone_to_nav_target(zone: dict) -> NavTarget:
    name = str(zone.get("name") or "목적지")
    nav_goal = zone.get("nav_goal")

    if not isinstance(nav_goal, dict):
        raise ValueError(f"{name}: nav_goal 정보가 없습니다.")

    if "x" not in nav_goal or "y" not in nav_goal:
        raise ValueError(f"{name}: nav_goal에 x 또는 y가 없습니다.")

    try:
        x = float(nav_goal["x"])
        y = float(nav_goal["y"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: nav_goal x/y가 숫자가 아닙니다.") from exc

    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError(f"{name}: nav_goal x/y가 유효한 숫자가 아닙니다.")

    frame_id = str(
        zone.get("frame_id")
        or nav_goal.get("frame_id")
        or "map"
    ).strip()

    if not frame_id:
        raise ValueError(f"{name}: frame_id가 비어 있습니다.")

    qz_raw = nav_goal.get("qz")
    qw_raw = nav_goal.get("qw")

    if qz_raw is None or qw_raw is None:
        try:
            yaw_deg = float(nav_goal.get("yaw_deg", 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name}: yaw_deg가 숫자가 아닙니다.") from exc
        qz, qw = yaw_deg_to_quaternion_z_w(yaw_deg)
    else:
        try:
            qz = float(qz_raw)
            qw = float(qw_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name}: qz/qw가 숫자가 아닙니다.") from exc

    if not math.isfinite(qz) or not math.isfinite(qw):
        raise ValueError(f"{name}: qz/qw가 유효한 숫자가 아닙니다.")

    norm = math.hypot(qz, qw)
    if norm < 1.0e-6:
        raise ValueError(f"{name}: quaternion 크기가 0에 가깝습니다.")

    qz /= norm
    qw /= norm

    return NavTarget(
        name=name,
        frame_id=frame_id,
        x=x,
        y=y,
        qz=qz,
        qw=qw,
    )


def print_nav_status(event: str, message: str) -> None:
    print(f"[NAV:{event.upper()}] {message}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="llm",
        description=(
            "Watch STT outputs, answer with map labels, and keep a Nav2 goal "
            "active until arrival."
        ),
    )

    parser.add_argument(
        "--watch-dir",
        default=str(DEFAULT_STT_OUTPUT_DIR),
        help="STT txt 파일이 생성되는 폴더",
    )
    parser.add_argument(
        "--labels",
        default=str(DEFAULT_LABELS_PATH),
        help="map_labels.json 경로",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        help="OpenAI 모델",
    )
    parser.add_argument(
        "--poll-sec",
        type=float,
        default=0.5,
        help="폴더 감시 주기",
    )
    parser.add_argument(
        "--process-existing",
        action="store_true",
        help="실행 전 이미 있던 txt도 처리",
    )
    parser.add_argument(
        "--state-file",
        default=str(DEFAULT_STATE_FILE),
        help="처리 완료 파일 목록 저장 경로",
    )
    parser.add_argument(
        "--no-nav",
        action="store_true",
        help="Nav2 goal 전송 없이 답변만 출력",
    )
    parser.add_argument(
        "--nav-action",
        default="/navigate_to_pose",
        help="Nav2 NavigateToPose action 이름",
    )
    parser.add_argument(
        "--nav-retry-sec",
        type=float,
        default=2.0,
        help="goal 실패·취소 후 동일 목적지 재전송 대기 시간",
    )
    parser.add_argument(
        "--nav-stall-sec",
        type=float,
        default=15.0,
        help="목적지까지 거리 진전이 없을 때 재전송하기까지의 시간",
    )
    parser.add_argument(
        "--nav-feedback-timeout-sec",
        type=float,
        default=10.0,
        help="Nav2 feedback이 없을 때 goal을 재시도하기까지의 시간",
    )
    parser.add_argument(
        "--arrival-distance",
        type=float,
        default=0.45,
        help="이 거리 이하를 도착으로 판단하는 임계값(m)",
    )
    parser.add_argument(
        "--arrival-hold-sec",
        type=float,
        default=1.0,
        help="도착 거리 안에 머물러야 하는 시간",
    )
    parser.add_argument(
        "--nav-progress-epsilon",
        type=float,
        default=0.05,
        help="거리 진전으로 인정할 최소 변화량(m)",
    )
    parser.add_argument(
        "--nav-max-retries",
        type=int,
        default=0,
        help="최대 전송 횟수. 0은 목적지 도착까지 무제한",
    )

    args = parser.parse_args()

    watch_dir = Path(args.watch_dir)
    labels_path = Path(args.labels)
    state_file = Path(args.state_file)

    watch_dir.mkdir(parents=True, exist_ok=True)

    zones = load_map_labels(labels_path)
    label_index = build_label_index(zones)
    labels_mtime_ns = labels_path.stat().st_mtime_ns

    processed = load_processed(state_file)

    if not args.process_existing:
        for path in watch_dir.glob("*.txt"):
            processed.add(str(path.resolve()))
        save_processed(state_file, processed)

    nav_runtime: Optional[NavigationRuntime] = None

    if not args.no_nav:
        nav_runtime = NavigationRuntime(
            action_name=args.nav_action,
            retry_sec=args.nav_retry_sec,
            stall_sec=args.nav_stall_sec,
            feedback_timeout_sec=args.nav_feedback_timeout_sec,
            arrival_distance=args.arrival_distance,
            arrival_hold_sec=args.arrival_hold_sec,
            progress_epsilon=args.nav_progress_epsilon,
            max_retries=args.nav_max_retries,
            status_callback=print_nav_status,
        )

    pending_zone: Optional[dict] = None

    print("=" * 60)
    print("LLM + map label watcher 실행 시작")
    print(f"STT 감시 폴더: {watch_dir}")
    print(f"라벨 파일: {labels_path}")
    print(f"OpenAI 모델: {args.model}")
    print(f"Nav2 사용: {not args.no_nav}")
    if not args.no_nav:
        print(
            "Nav2 재시도: "
            f"실패·취소 후 {args.nav_retry_sec:.1f}초, "
            f"무진전 {args.nav_stall_sec:.1f}초, "
            f"도착 거리 {args.arrival_distance:.2f}m"
        )
    print("종료하려면 Ctrl+C")
    print("=" * 60)
    print()

    print("[LABELS]")
    for zone in zones:
        aliases = zone.get("alias", [])
        if aliases:
            print(f"- {zone.get('name')}  alias={aliases}")
        else:
            print(f"- {zone.get('name')}")
    print()

    try:
        while True:
            try:
                current_mtime_ns = labels_path.stat().st_mtime_ns
                if current_mtime_ns != labels_mtime_ns:
                    zones = load_map_labels(labels_path)
                    label_index = build_label_index(zones)
                    labels_mtime_ns = current_mtime_ns
                    print("[LABELS] map_labels.json 변경 감지: 자동 재로드 완료")
            except Exception as exc:
                print(f"[LABEL ERROR] 라벨 자동 재로드 실패: {exc}")

            txt_files = sorted(
                watch_dir.glob("*.txt"),
                key=lambda path: path.stat().st_mtime,
            )

            for path in txt_files:
                resolved = str(path.resolve())

                if resolved in processed:
                    continue

                if not wait_until_file_stable(path):
                    continue

                try:
                    user_text = read_text_file(path)

                    if not user_text:
                        mark_processed(state_file, processed, resolved)
                        continue

                    print()
                    print("-" * 60)
                    print(f"[STT FILE] {path.name}")
                    print(f"[USER] {user_text}")

                    matched = match_location(user_text, label_index)

                    # 확인 대기 중에는 부정 응답을 긍정보다 먼저 처리한다.
                    if pending_zone is not None and is_no(user_text):
                        print("[LLM] 알겠습니다. 안내 요청을 취소하겠습니다.")
                        pending_zone = None
                        print("-" * 60)
                        mark_processed(state_file, processed, resolved)
                        continue

                    if pending_zone is not None and is_yes(user_text) and matched is None:
                        dest_name = pending_zone.get("name", "목적지")
                        print(f"[LLM] 네, {dest_name}로 안내를 시작하겠습니다.")

                        if args.no_nav:
                            print("[NAV] --no-nav 모드라 goal 전송은 하지 않습니다.")
                        elif nav_runtime is not None:
                            try:
                                target = zone_to_nav_target(pending_zone)
                                nav_runtime.node.start_navigation(target)
                            except ValueError as exc:
                                print(f"[NAV ERROR] {exc}")
                                print("[LLM] 목적지 좌표 정보가 올바르지 않아 안내를 시작하지 못했습니다.")

                        pending_zone = None
                        print("-" * 60)
                        mark_processed(state_file, processed, resolved)
                        continue

                    if matched is not None:
                        zone, matched_keyword = matched
                        pending_zone = zone
                        answer = describe_location(zone)

                        print(
                            f"[MATCH] keyword={matched_keyword}, "
                            f"destination={zone.get('name')}"
                        )
                        print(f"[LLM] {answer}")
                        print("-" * 60)
                        mark_processed(state_file, processed, resolved)
                        continue

                    if (
                        pending_zone is None
                        and is_no(user_text)
                        and nav_runtime is not None
                        and nav_runtime.node.is_navigating()
                    ):
                        destination = (
                            nav_runtime.node.current_destination_name()
                            or "목적지"
                        )
                        nav_runtime.node.cancel_navigation(reason="음성 취소 명령")
                        print(f"[LLM] 알겠습니다. {destination} 안내를 중단하겠습니다.")
                        print("-" * 60)
                        mark_processed(state_file, processed, resolved)
                        continue

                    if is_location_question(user_text):
                        pending_zone = None
                        print("[LLM] 해당 장소는 현재 등록된 병원 지도 라벨에서 찾지 못했습니다.")
                        print("-" * 60)
                        mark_processed(state_file, processed, resolved)
                        continue

                    answer = ask_openai(
                        model=args.model,
                        user_text=user_text,
                    )

                    print(f"[LLM] {answer}")
                    print("-" * 60)
                    mark_processed(state_file, processed, resolved)

                except Exception as exc:
                    # 실패한 STT 파일은 처리 목록에 넣지 않아 다음 반복에서 재시도한다.
                    print(f"[LLM ERROR] {path.name} 처리 실패: {exc}")

            time.sleep(max(0.1, args.poll_sec))

    except KeyboardInterrupt:
        print()
        print("LLM watcher를 종료합니다.")

    finally:
        if nav_runtime is not None:
            nav_runtime.shutdown()


if __name__ == "__main__":
    main()
