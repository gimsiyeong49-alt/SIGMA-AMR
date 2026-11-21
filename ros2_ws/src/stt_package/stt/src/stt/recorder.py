import os
import shutil
import signal
import subprocess
import sys
import termios
import time
import tty
import wave
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Deque, Generator, List, Optional

import numpy as np


@dataclass
class RecordConfig:
    sample_rate: int = 16000
    channels: int = 1
    audio_format: str = "S16_LE"
    device: Optional[str] = None
    output_dir: str = "/tmp"


def _resolve_device(cfg: RecordConfig) -> str:
    return (
        os.environ.get("STT_AUDIO_DEVICE")
        or cfg.device
        or "plughw:3,0"
    )


def _save_wav(
    path: Path,
    pcm_chunks: List[bytes],
    sample_rate: int,
    channels: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(pcm_chunks))


def _chunk_rms(chunk: bytes) -> float:
    if not chunk:
        return 0.0

    audio = np.frombuffer(chunk, dtype=np.int16)

    if audio.size == 0:
        return 0.0

    audio_f = audio.astype(np.float32)
    return float(np.sqrt(np.mean(audio_f * audio_f)))


@contextmanager
def _single_key_terminal():
    """터미널을 Enter 없이 한 글자씩 읽을 수 있는 상태로 전환한다."""

    if not sys.stdin.isatty():
        raise RuntimeError(
            "현재 표준 입력이 터미널이 아닙니다. "
            "SSH 또는 일반 터미널에서 직접 실행하세요."
        )

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        # cbreak는 한 글자 입력을 즉시 전달하면서 Ctrl+C 신호는 유지한다.
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _key_matches(key: str, toggle_key: str) -> bool:
    if toggle_key == "space":
        return key == " "

    if toggle_key == "enter":
        return key in ("\n", "\r")

    raise ValueError(f"지원하지 않는 버튼입니다: {toggle_key}")


def _key_display_name(toggle_key: str) -> str:
    if toggle_key == "space":
        return "스페이스바"
    if toggle_key == "enter":
        return "Enter"
    return toggle_key


def _make_wav_path(output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return output_dir / f"stt_input_{timestamp}.wav"


def _stop_arecord(proc: subprocess.Popen) -> str:
    """arecord를 정상 종료하고 stderr 문자열을 반환한다."""

    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)

    try:
        _, err = proc.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, err = proc.communicate()

    if isinstance(err, bytes):
        return err.decode(errors="ignore")

    return err or ""


def _wav_duration_sec(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wf:
            frame_rate = wf.getframerate()
            frame_count = wf.getnframes()

        if frame_rate <= 0:
            return 0.0

        return frame_count / float(frame_rate)
    except (wave.Error, OSError):
        return 0.0


def record_button_to_start_stop(
    cfg: RecordConfig,
    toggle_key: str = "space",
    min_record_sec: float = 0.2,
) -> Optional[str]:
    """
    지정한 키를 한 번 누르면 녹음을 시작하고,
    같은 키를 다시 누르면 녹음을 종료한다.

    대기 중 q를 누르면 None을 반환하여 STT 프로그램을 종료한다.
    """

    if shutil.which("arecord") is None:
        raise RuntimeError(
            "arecord 명령어를 찾을 수 없습니다. "
            "alsa-utils 설치가 필요합니다."
        )

    if toggle_key not in {"space", "enter"}:
        raise ValueError(
            "toggle_key는 'space' 또는 'enter'만 사용할 수 있습니다."
        )

    device = _resolve_device(cfg)
    key_name = _key_display_name(toggle_key)

    output_dir = Path(cfg.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"사용 마이크: {device}")
    print(f"{key_name}를 누르면 녹음을 시작합니다.")
    print("대기 중 q를 누르면 STT를 종료합니다.")
    print()

    with _single_key_terminal():
        while True:
            key = sys.stdin.read(1)

            if key.lower() == "q":
                print("STT 종료를 요청했습니다.")
                return None

            if _key_matches(key, toggle_key):
                break

        wav_path = _make_wav_path(output_dir)

        cmd = [
            "arecord",
            "-D", device,
            "-f", cfg.audio_format,
            "-r", str(cfg.sample_rate),
            "-c", str(cfg.channels),
            "-t", "wav",
            "-q",
            str(wav_path),
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        print()
        print("[REC] 녹음을 시작했습니다.")
        print(f"[REC] 모두 말한 뒤 {key_name}를 다시 누르세요.")
        print("[REC] Ctrl+C를 누르면 프로그램을 종료합니다.")
        print()

        err = ""

        try:
            while True:
                if proc.poll() is not None:
                    err_bytes = b""
                    if proc.stderr is not None:
                        err_bytes = proc.stderr.read()
                    err = err_bytes.decode(errors="ignore")
                    raise RuntimeError(
                        "녹음 도중 arecord가 종료되었습니다.\n"
                        f"stderr={err}"
                    )

                key = sys.stdin.read(1)

                if _key_matches(key, toggle_key):
                    break

        except KeyboardInterrupt:
            _stop_arecord(proc)
            try:
                wav_path.unlink()
            except FileNotFoundError:
                pass
            raise

        finally:
            if proc.poll() is None:
                err = _stop_arecord(proc)

    print("[REC] 녹음을 종료했습니다.")

    if not wav_path.exists():
        raise RuntimeError(
            "녹음 파일이 생성되지 않았습니다.\n"
            f"device={device}\n"
            f"stderr={err}"
        )

    duration_sec = _wav_duration_sec(wav_path)

    if wav_path.stat().st_size < 1024 or duration_sec < min_record_sec:
        size = wav_path.stat().st_size
        try:
            wav_path.unlink()
        except FileNotFoundError:
            pass

        print(
            "[REC] 녹음 시간이 너무 짧아 인식을 건너뜁니다. "
            f"duration={duration_sec:.2f}s size={size}"
        )
        return ""

    print(f"[REC] 녹음 길이: {duration_sec:.2f}초")
    print(f"[REC] 녹음 파일: {wav_path}")

    return str(wav_path)


def record_enter_to_start_stop(cfg: RecordConfig) -> str:
    """기존 Enter 시작/종료 방식과의 호환 함수."""

    while True:
        path = record_button_to_start_stop(
            cfg=cfg,
            toggle_key="enter",
        )

        if path is None:
            raise KeyboardInterrupt

        if path:
            return path


def record_continuous_utterances(
    cfg: RecordConfig,
    vad_threshold: float = 500.0,
    silence_sec: float = 1.0,
    min_record_sec: float = 0.5,
    max_record_sec: float = 10.0,
    chunk_sec: float = 0.1,
    pre_roll_sec: float = 0.3,
) -> Generator[str, None, None]:
    """
    기존 VAD 자동 녹음 모드.

    --vad-mode 옵션으로 실행할 때만 사용한다.
    """

    if shutil.which("arecord") is None:
        raise RuntimeError(
            "arecord 명령어를 찾을 수 없습니다. "
            "alsa-utils 설치가 필요합니다."
        )

    device = _resolve_device(cfg)

    sample_rate = int(cfg.sample_rate)
    channels = int(cfg.channels)

    bytes_per_sample = 2
    samples_per_chunk = max(1, int(sample_rate * chunk_sec))
    chunk_bytes = samples_per_chunk * bytes_per_sample * channels

    output_dir = Path(cfg.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "arecord",
        "-D", device,
        "-f", cfg.audio_format,
        "-r", str(sample_rate),
        "-c", str(channels),
        "-t", "raw",
        "-q",
        "-",
    ]

    print(f"사용 마이크: {device}")
    print("VAD 자동 감시를 시작합니다.")
    print("말하면 자동 녹음되고, 침묵이 감지되면 자동으로 처리됩니다.")
    print("종료하려면 Ctrl+C를 누르세요.")
    print()

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    in_speech = False
    speech_chunks: List[bytes] = []
    speech_start_time = 0.0
    last_voice_time = 0.0

    pre_roll_count = max(1, int(pre_roll_sec / chunk_sec))
    pre_roll: Deque[bytes] = deque(maxlen=pre_roll_count)

    utterance_index = 0

    try:
        while True:
            if proc.stdout is None:
                raise RuntimeError("arecord stdout을 열 수 없습니다.")

            chunk = proc.stdout.read(chunk_bytes)

            if not chunk:
                if proc.poll() is not None:
                    err = b""
                    if proc.stderr is not None:
                        err = proc.stderr.read()
                    raise RuntimeError(
                        "arecord 프로세스가 종료되었습니다.\n"
                        f"stderr={err.decode(errors='ignore')}"
                    )
                continue

            now = time.time()
            rms = _chunk_rms(chunk)
            is_voice = rms >= vad_threshold

            if not in_speech:
                pre_roll.append(chunk)

                if is_voice:
                    in_speech = True
                    speech_start_time = now
                    last_voice_time = now
                    speech_chunks = list(pre_roll)

                    print(f"[VAD] 음성 감지 시작 rms={rms:.1f}")

            else:
                speech_chunks.append(chunk)

                if is_voice:
                    last_voice_time = now

                elapsed = now - speech_start_time
                silence_elapsed = now - last_voice_time

                should_stop_by_silence = silence_elapsed >= silence_sec
                should_stop_by_max = elapsed >= max_record_sec

                if should_stop_by_silence or should_stop_by_max:
                    total_sec = len(speech_chunks) * chunk_sec

                    if total_sec >= min_record_sec:
                        utterance_index += 1
                        wav_path = output_dir / (
                            "stt_input_{}_{:03d}.wav".format(
                                datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
                                utterance_index,
                            )
                        )

                        _save_wav(
                            path=wav_path,
                            pcm_chunks=speech_chunks,
                            sample_rate=sample_rate,
                            channels=channels,
                        )

                        print(f"[VAD] 음성 구간 종료: {wav_path}")
                        yield str(wav_path)
                    else:
                        print("[VAD] 너무 짧은 음성이라 무시합니다.")

                    in_speech = False
                    speech_chunks = []
                    pre_roll.clear()

    except KeyboardInterrupt:
        print()
        print("실시간 STT를 종료합니다.")

    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)

        try:
            proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()

