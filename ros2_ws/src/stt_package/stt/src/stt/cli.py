import argparse
from pathlib import Path
from typing import Optional

from stt.config import STTConfig
from stt.postprocess import postprocess_stt_text
from stt.recorder import (
    RecordConfig,
    record_button_to_start_stop,
    record_continuous_utterances,
)
from stt.transcriber import run_whisper_server
from stt.writer import save_text


LINE = "=" * 60

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PACKAGE_ROOT / "outputs"


def _delete_audio_file(audio_path: str) -> None:
    try:
        Path(audio_path).unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"[STT] 임시 WAV 삭제 실패: {exc}")


def _process_one_audio(
    config: STTConfig,
    audio_path: str,
    keep_audio: bool = False,
) -> None:
    try:
        text = run_whisper_server(
            server_url=config.server_url,
            audio=audio_path,
            sample_rate=config.sample_rate,
            language=config.language,
        ).replace("[끝]", "").strip()

        corrected_text = postprocess_stt_text(text)

        if not corrected_text:
            print("[STT] 인식 결과가 비어 있어서 txt 저장을 건너뜁니다.")
            return

        txt_path = save_text(
            text=corrected_text,
            out_dir=config.output_dir,
        )

        print()
        print(f"원본 인식: {text}")
        print(f"후처리 결과: {corrected_text}")
        print(f"텍스트 파일 생성: {txt_path}")
        print()

    finally:
        if not keep_audio:
            _delete_audio_file(audio_path)


def _run_button_mode(
    config: STTConfig,
    record_config: RecordConfig,
    button_key: str,
    min_record_sec: float,
    keep_audio: bool,
) -> None:
    key_name = "스페이스바" if button_key == "space" else "Enter"

    print("버튼 녹음 모드입니다.")
    print(f"{key_name} 한 번: 녹음 시작")
    print(f"{key_name} 다시 한 번: 녹음 종료 및 STT 처리")
    print("대기 중 q: 프로그램 종료")
    print("Ctrl+C: 프로그램 종료")
    print()

    while True:
        audio_path: Optional[str] = record_button_to_start_stop(
            cfg=record_config,
            toggle_key=button_key,
            min_record_sec=min_record_sec,
        )

        if audio_path is None:
            break

        if not audio_path:
            print()
            continue

        print()
        print(LINE)
        print()

        try:
            _process_one_audio(
                config=config,
                audio_path=audio_path,
                keep_audio=keep_audio,
            )
        except Exception as exc:
            print(f"[STT ERROR] {exc}")

        print(LINE)
        print()


def _run_vad_mode(
    config: STTConfig,
    record_config: RecordConfig,
    vad_threshold: float,
    silence_sec: float,
    min_record_sec: float,
    max_record_sec: float,
    keep_audio: bool,
) -> None:
    for audio_path in record_continuous_utterances(
        cfg=record_config,
        vad_threshold=vad_threshold,
        silence_sec=silence_sec,
        min_record_sec=min_record_sec,
        max_record_sec=max_record_sec,
    ):
        print()
        print(LINE)
        print()

        try:
            _process_one_audio(
                config=config,
                audio_path=audio_path,
                keep_audio=keep_audio,
            )
        except Exception as exc:
            print(f"[STT ERROR] {exc}")

        print(LINE)
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="stt",
        description=(
            "마이크 음성을 whisper.cpp server로 인식하는 STT 패키지"
        ),
    )

    parser.add_argument(
        "--server-url",
        default="http://127.0.0.1:8080/inference",
        help="whisper-server 요청 주소",
    )

    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="변환된 txt 파일 저장 폴더",
    )

    parser.add_argument(
        "--lang",
        default="ko",
        help="인식 언어",
    )

    parser.add_argument(
        "--device",
        default=None,
        help="ALSA 녹음 장치. 예: plughw:0,0",
    )

    parser.add_argument(
        "--button-key",
        choices=("space", "enter"),
        default="space",
        help="녹음 시작/종료 버튼. 기본값: space",
    )

    parser.add_argument(
        "--vad-mode",
        action="store_true",
        help="버튼 방식 대신 기존 VAD 자동 녹음 모드 사용",
    )

    parser.add_argument(
        "--vad-threshold",
        type=float,
        default=500.0,
        help="VAD 모드 음성 감지 임계값",
    )

    parser.add_argument(
        "--silence-sec",
        type=float,
        default=1.0,
        help="VAD 모드에서 이 시간만큼 조용하면 녹음 종료",
    )

    parser.add_argument(
        "--min-sec",
        type=float,
        default=0.2,
        help="이보다 짧은 녹음은 인식하지 않음",
    )

    parser.add_argument(
        "--max-sec",
        type=float,
        default=10.0,
        help="VAD 모드 한 번 녹음 최대 길이",
    )

    parser.add_argument(
        "--keep-audio",
        action="store_true",
        help="Whisper 처리 후 /tmp WAV 파일을 삭제하지 않음",
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = STTConfig(
        output_dir=output_dir,
        language=args.lang,
        server_url=args.server_url,
    )

    record_config = RecordConfig(
        sample_rate=config.sample_rate,
        channels=1,
        audio_format="S16_LE",
        device=args.device,
        output_dir="/tmp",
    )

    print()
    print(LINE)
    print("STT 실행 시작")
    print(f"텍스트 저장 폴더: {config.output_dir}")
    print(f"Whisper server: {config.server_url}")
    print(LINE)
    print()

    try:
        if args.vad_mode:
            _run_vad_mode(
                config=config,
                record_config=record_config,
                vad_threshold=args.vad_threshold,
                silence_sec=args.silence_sec,
                min_record_sec=args.min_sec,
                max_record_sec=args.max_sec,
                keep_audio=args.keep_audio,
            )
        else:
            _run_button_mode(
                config=config,
                record_config=record_config,
                button_key=args.button_key,
                min_record_sec=args.min_sec,
                keep_audio=args.keep_audio,
            )

    except KeyboardInterrupt:
        print()
        print("STT를 종료합니다.")


if __name__ == "__main__":
    main()

