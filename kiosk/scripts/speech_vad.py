# speech_vad.py — Silero VAD(신경망 말소리 감지) 래퍼. 소리 '크기'가 아니라 '사람 목소리인지'로 판단한다.
#
#   · 조용히·멀리서 말해도(원음 RMS가 배경음의 2~3배뿐) 목소리면 잡고, 크게 울리는 소음·기계음은 덜 잡는다.
#   · 모델: /mnt/ssd/models/silero_vad/silero_vad.onnx (Silero VAD v5.1.2, 약 2MB, CPU 실시간)
#   · 런타임: onnxruntime 1.16.3 (STT venv). 1.19는 이 보드(꺼진 CPU 코어 6·7)에서 세션 생성 때 비정상 종료.
#   · 입력: 16kHz 모노 S16_LE. 512샘플(32ms) 단위로 확률(0~1) 계산, 상태(RNN)를 이어 가며 처리.
import os

import numpy as np

MODEL_PATH = os.environ.get("SILERO_VAD_MODEL", "/mnt/ssd/models/silero_vad/silero_vad.onnx")
FRAME = 512          # 16kHz 기준 32ms
_CONTEXT = 64        # v5 모델은 앞 프레임 끝 64샘플을 붙여 넣는다(공식 래퍼와 동일)


class SileroVAD:
    def __init__(self, path=MODEL_PATH):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1      # 스레드 수를 지정하지 않으면 꺼진 코어에 affinity 를 걸다 실패
        so.inter_op_num_threads = 1
        so.log_severity_level = 3        # 모델 로드 경고(사용 안 하는 initializer) 숨김
        self._sess = ort.InferenceSession(path, sess_options=so, providers=["CPUExecutionProvider"])
        self._sr = np.array(16000, dtype=np.int64)
        self.reset()

    def reset(self):
        """녹음 한 번마다 초기화(이전 발화의 RNN 상태가 남지 않게)."""
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._ctx = np.zeros(_CONTEXT, dtype=np.float32)
        self._rest = np.zeros(0, dtype=np.float32)

    def probs(self, pcm16):
        """S16_LE 바이트(임의 길이) → 이번에 완성된 512샘플 프레임들의 말소리 확률 리스트. 남는 샘플은 다음 호출로 이월."""
        x = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        x = np.concatenate([self._rest, x])
        out = []
        n = len(x) // FRAME
        for i in range(n):
            frame = x[i * FRAME:(i + 1) * FRAME]
            inp = np.concatenate([self._ctx, frame])[None, :]
            p, self._state = self._sess.run(None, {"input": inp, "state": self._state, "sr": self._sr})
            self._ctx = frame[-_CONTEXT:]
            out.append(float(p[0][0]))
        self._rest = x[n * FRAME:]
        return out
