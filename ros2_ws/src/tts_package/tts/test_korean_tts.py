#!/usr/bin/env python3

from pathlib import Path
import time

import torch
import soundfile as sf
from melo.api import TTS


TEXT = (
    "안녕하세요. 병원 안내 로봇입니다. "
    "목적지를 말씀해 주시면 안전하게 안내해 드리겠습니다."
)

OUTPUT_PATH = Path(
    "/mnt/ssd/cart_ros2/src/tts_package/tts/output/kr_test.wav"
)


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    device = "cuda:0" if torch.cuda.is_available() else "cpu"

    print("사용 장치:", device)

    if torch.cuda.is_available():
        print("GPU:", torch.cuda.get_device_name(0))

    print("한국어 MeloTTS 모델을 불러오는 중입니다.")
    print("첫 실행에서는 모델 파일이 다운로드될 수 있습니다.")

    load_start = time.time()

    model = TTS(
        language="KR",
        device=device,
    )

    print(
        f"모델 준비 완료: {time.time() - load_start:.2f}초"
    )

    speaker_ids = model.hps.data.spk2id
    print("스피커 정보:", speaker_ids)

    speaker_id = speaker_ids["KR"]

    synthesis_start = time.time()

    model.tts_to_file(
        text=TEXT,
        speaker_id=speaker_id,
        output_path=str(OUTPUT_PATH),
        speed=1.0,
        quiet=False,
    )

    elapsed = time.time() - synthesis_start

    if not OUTPUT_PATH.is_file():
        raise RuntimeError(
            f"WAV 파일이 생성되지 않았습니다: {OUTPUT_PATH}"
        )

    info = sf.info(str(OUTPUT_PATH))

    print()
    print("음성 생성 성공")
    print("파일:", OUTPUT_PATH)
    print("생성 시간:", f"{elapsed:.2f}초")
    print("샘플링 주파수:", info.samplerate)
    print("채널:", info.channels)
    print("길이:", f"{info.duration:.2f}초")
    print("파일 크기:", OUTPUT_PATH.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
