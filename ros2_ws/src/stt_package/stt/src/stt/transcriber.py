import json
import os
import tempfile
import wave
from pathlib import Path
from typing import Union

import numpy as np
import requests
import time


def _normalize_server_url(server_url: str) -> str:
    server_url = str(server_url).strip()

    if server_url.endswith("/"):
        server_url = server_url[:-1]

    if not server_url.endswith("/inference"):
        server_url += "/inference"

    return server_url


def _array_to_temp_wav(audio: np.ndarray, sample_rate: int) -> str:
    audio_int16 = np.asarray(audio, dtype=np.int16)

    temp = tempfile.NamedTemporaryFile(
        prefix="stt_array_",
        suffix=".wav",
        delete=False,
    )
    temp.close()

    with wave.open(temp.name, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())

    return temp.name


def _extract_text(response: requests.Response) -> str:
    body = response.text.strip()

    if not body:
        return ""

    try:
        data = response.json()
        if isinstance(data, dict):
            return (
                data.get("text")
                or data.get("transcription")
                or data.get("result")
                or ""
            ).strip()
    except json.JSONDecodeError:
        pass

    return body.strip()


def run_whisper_server(
    server_url: str,
    audio: Union[str, Path, np.ndarray],
    sample_rate: int = 16000,
    language: str = "ko",
) -> str:
    """
    audio가 wav 파일 경로이면 그대로 whisper-server에 전송한다.
    audio가 numpy 배열이면 임시 wav로 변환한 뒤 전송한다.
    """

    server_url = _normalize_server_url(
        os.environ.get("WHISPER_SERVER_URL") or server_url
    )

    temp_created = False

    if isinstance(audio, (str, Path)):
        wav_path = Path(audio)
    else:
        wav_path = Path(_array_to_temp_wav(audio, sample_rate))
        temp_created = True

    if not wav_path.exists():
        raise FileNotFoundError(f"음성 파일이 없습니다: {wav_path}")

    try:
        with open(wav_path, "rb") as f:
            files = {
                "file": (wav_path.name, f, "audio/wav")
            }
            data = {
                "language": language,
                "response_format": "text",
            }

            t0 = time.time()
            response = requests.post(
                server_url,
                files=files,
                data=data,
                timeout=120,
            )
            print(f"[TIMING] whisper-server 요청-응답: {time.time() - t0:.2f}초")

        if response.status_code != 200:
            raise RuntimeError(
                "whisper-server 요청 실패\n"
                f"status={response.status_code}\n"
                f"body={response.text}"
            )

        return _extract_text(response)

    finally:
        if temp_created:
            try:
                os.remove(wav_path)
            except Exception:
                pass
