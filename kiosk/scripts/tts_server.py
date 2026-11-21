#!/usr/bin/env python3
# =========================================================================
# tts_server.py — MeloTTS 다국어(한·영·중·일) 음성합성 상주 서버 (whisper-server와 같은 역할)
#
#   ★ tts_package 의 .venv 로 실행해야 한다 (melo/torch 의존).
#      예: /mnt/ssd/cart_ros2/src/tts_package/tts/.venv/bin/python3 tts_server.py
#
#   시작 시 모델 로드(~8s) + 워밍업 합성(~15s) → 이후 요청마다 ~1s.
#   POST /tts   {"text": "...", "lang": "ko|en|zh|ja"}  → 그 언어 모델로 합성 후 로봇 스피커로 재생 (lang 없으면 ko)
#     · 한국어를 먼저 띄워 바로 준비되고, 영·중·일은 뒤에서 차례로 로드(TTS_LANGS). 아직 안 뜬 언어는 error=lang_not_ready
#   POST /synth {"text": "..."}  → WAV 파일로만 저장(재생 안 함), 경로 반환
#   POST /prewarm {"texts": [...]} → 문장들을 뒤에서 미리 합성해 캐시(즉시 응답). 고정 안내 즉시 재생용.
#   POST /flush  → 대기·재생 중인 요청을 모두 버림(start_guide.sh 종료/시작 시 호출).
#                  앱을 껐다 켰을 때 이전에 밀린 문장이 뒤늦게 재생되던 문제 방지.
#   GET  /       → 200 (헬스체크)
#
#   환경변수:
#     TTS_PORT           기본 5002
#     TTS_SPEAKER_DEVICE 재생 ALSA 장치 (기본 plughw:0,0 = USB 스피커)
#     TTS_SPEED          말하기 속도 (기본 1.0)
#     TTS_MAX_AGE_SEC    요청 후 이 시간(초)이 지나면 재생하지 않음 (기본 25 — 앱 대기 30초보다 짧게)
#     TTS_LANGS          띄울 언어(기본 KR,EN,ZH,JP). 메모리·시작시간을 줄이려면 줄인다(KR은 항상 포함)
# =========================================================================
import json
import os
import subprocess
import sys
import threading
import time
import http.server
import socketserver

PORT = int(os.environ.get("TTS_PORT", "5002"))
SPEED = float(os.environ.get("TTS_SPEED", "1.0"))
OUT_WAV = os.environ.get("TTS_OUT_WAV", "/tmp/tts_out.wav")
# 앱(kiosk_server)은 30초 기다리다 포기하고 브라우저 TTS로 넘어간다. 그보다 늦은 재생은 엉뚱한 때 들리므로 버린다.
MAX_AGE = float(os.environ.get("TTS_MAX_AGE_SEC", "25"))


_RESPEAKER = False   # 감지된 스피커가 reSpeaker인지(볼륨 기본값이 다름)


def _detect_speaker():
    """USB 스피커 ALSA 장치 자동 감지. 카드 번호는 재부팅/재연결마다 바뀔 수 있어
    aplay -l 에서 USB 오디오 출력 카드를 찾는다(reSpeaker 우선, HDMI 제외). TTS_SPEAKER_DEVICE로 강제 가능."""
    env = os.environ.get("TTS_SPEAKER_DEVICE")
    if env:
        return env
    try:
        out = subprocess.run(["aplay", "-l"], capture_output=True, text=True).stdout
        # 1순위: reSpeaker XVF3800(마이크·스피커 일체형). TTS가 이 모듈로 나가야 온보드 에코 제거(AEC)가 동작
        global _RESPEAKER
        _RESPEAKER = False
        for line in out.splitlines():
            if line.startswith("card ") and "reSpeaker" in line:
                name = line.split("card ", 1)[1].split(":", 1)[1].strip().split(" [")[0].strip()  # "C16K6Ch"
                if name:
                    _RESPEAKER = True
                    return f"plughw:CARD={name},DEV=0"
        for line in out.splitlines():
            # 예: "card 1: UACDemoV10 [UACDemoV1.0], device 0: USB Audio [USB Audio]"
            if line.startswith("card ") and "HDMI" not in line and \
               ("USB Audio" in line or "UACDemo" in line or "USB" in line):
                head = line.split("card ", 1)[1]           # "1: UACDemoV10 [...] ..."
                num = head.split(":", 1)[0].strip()        # "1"
                # 카드 '이름'을 우선 사용 → 재부팅으로 번호가 바뀌어도 유지됨
                name = head.split(":", 1)[1].strip().split(" [")[0].strip()  # "UACDemoV10"
                if name:
                    return f"plughw:CARD={name},DEV=0"
                return f"plughw:{num},0"
    except Exception:
        pass
    return "plughw:0,0"


SPEAKER = _detect_speaker()

# 스피커 크기(ALSA 믹서). 재부팅해도 매 기동 시 이 값으로 맞춘다.
#  reSpeaker는 눈금이 달라(60칸, 1칸=1dB) 80%면 −12dB로 너무 작다 → 기본 100%(0dB). 예전 USB 스피커는 80%(−6.5dB)
TTS_VOLUME = os.environ.get("TTS_VOLUME") or ("100%" if _RESPEAKER else "80%")


def _set_speaker_volume(device, volume):
    """감지된 카드의 재생 볼륨을 volume(예:'100%')으로 설정. 컨트롤명은 기기마다 달라
    흔한 이름을 순서대로 시도한다. 실패해도 무음 원인은 아니므로 조용히 넘어간다."""
    card = None
    if "CARD=" in device:
        card = device.split("CARD=", 1)[1].split(",")[0]
    elif device.startswith("plughw:"):
        card = device.split("plughw:", 1)[1].split(",")[0]
    if not card:
        return
    for ctrl in ("PCM", "Speaker", "Master", "Headphone", "Playback"):
        try:
            r = subprocess.run(["amixer", "-c", card, "sset", ctrl, volume],
                               capture_output=True, text=True)
            if r.returncode == 0:
                # USB 오디오의 '마스터' 볼륨이 같은 이름 index 1로 따로 있는 장치(reSpeaker: PCM,1 기본 −20dB)
                #  → 채널 볼륨만 올리면 마스터에 막혀 작다. 있으면 같은 값으로 맞춘다(없으면 조용히 실패)
                subprocess.run(["amixer", "-c", card, "sset", f"{ctrl},1", volume],
                               capture_output=True, text=True)
                print(f"[tts] 스피커 볼륨 설정: {ctrl}={volume} (card {card})", flush=True)
                return
        except Exception:
            pass

_lock = threading.Lock()   # 합성/재생은 한 번에 하나 (겹침 방지)
# 합성 결과 캐시(문장 → WAV 바이트). 같은 문장은 다시 합성하지 않고 바로 재생(약 0.9초 → 0초).
#  고정 안내는 앱이 시작할 때 /prewarm 으로 미리 채운다. 메모리 상한 TTS_CACHE_MAX(기본 300문장, 수십 MB).
from collections import OrderedDict
CACHE_MAX = int(os.environ.get("TTS_CACHE_MAX", "300"))
_cache = OrderedDict()
_model = None      # 한국어(KR) 모델 — 준비 여부 판단 기준
_spk_id = None
# 언어별 모델: 앱 언어 코드 → (MeloTTS 언어, 화자). 영어는 미국식 화자
_LANG_MAP = {"ko": ("KR", "KR"), "en": ("EN", "EN-US"), "zh": ("ZH", "ZH"), "ja": ("JP", "JP")}
_WARMUP = {"KR": "안녕하세요.", "EN": "Hello.", "ZH": "你好。", "JP": "こんにちは。"}
_models = {}       # MeloTTS 언어 → (모델, 화자 id)
TTS_LANGS = [x.strip().upper() for x in os.environ.get("TTS_LANGS", "KR,EN,ZH,JP").split(",") if x.strip()]
_epoch = 0          # /flush 때마다 +1 — 그 전에 들어온 요청은 버린다
_aplay = None       # 재생 중인 aplay (flush 시 중단)


def _load_lang(mlang, speaker):
    """MeloTTS 언어 모델 하나를 로드·워밍업해 _models에 등록."""
    import torch
    from melo.api import TTS
    dev = "cuda:0" if torch.cuda.is_available() else "cpu"
    t0 = time.time()
    m = TTS(language=mlang, device=dev)
    sid = m.hps.data.spk2id[speaker]
    t1 = time.time()
    with _lock:   # 워밍업(첫 합성은 느림: CUDA 커널·BERT 초기화)
        m.tts_to_file(_WARMUP.get(mlang, "."), sid, OUT_WAV + f".{mlang}.warm.wav", speed=SPEED, quiet=True)
    _models[mlang] = (m, sid)
    print(f"[tts] {mlang} 준비됨 (로드 {t1-t0:.1f}s · 워밍업 {time.time()-t1:.1f}s)", flush=True)


def _load_model():
    """한국어를 먼저 로드(서버는 이때부터 준비). 나머지 언어는 _load_others()가 뒤에서."""
    global _model, _spk_id
    print("[tts] 모델 로드 시작: KR", flush=True)
    _load_lang("KR", "KR")
    _model, _spk_id = _models["KR"]
    print("[tts] 워밍업 합성 완료 · 준비됨(KR)", flush=True)


def _load_others():
    for mlang in TTS_LANGS:
        if mlang == "KR" or mlang in _models:
            continue
        spk = next((sp for ml, sp in _LANG_MAP.values() if ml == mlang), mlang)
        try:
            _load_lang(mlang, spk)
        except Exception as exc:
            print(f"[tts] ⚠ {mlang} 로드 실패(이 언어는 음성 없음): {exc}", flush=True)


def _drop_reason(epoch, t_arrive):
    if epoch != _epoch:
        return "flushed"
    if time.time() - t_arrive > MAX_AGE:
        return "stale"
    return None


# 소프트웨어 증폭(dB). 장치 볼륨이 이미 최대인데 작을 때 음성 자체를 키운다.
#  큰 소리는 tanh 로 부드럽게 눌러(소프트 리미터) 찢어짐 없이 평균 크기만 올린다. reSpeaker 기본 +6dB, 그 외 0
#  환자 화면 음량(vol 0~100, 기본 60)에 따른 보정이 이 값에 더해진다(_vol_gain_db)
TTS_GAIN_DB = float(os.environ.get("TTS_GAIN_DB") or (6 if _RESPEAKER else 0))


# 환자 화면 음량(드래그 0~100, 기본 60) → 재생 직전 증폭 dB. None = 무음(재생 안 함)
#  · 60 = 기본 크기(TTS_GAIN_DB 그대로)
#  · 60 아래 = 진폭 비례로 작게(30 → −6dB, 15 → −12dB), 0 = 무음
#  · 60 위 = 100까지 최대 +6dB 더(예전 5단계와 같은 상한, 소프트 리미터로 찢어짐 방지)
VOL_DEFAULT = 60


def _vol_gain_db(vol):
    import math
    try:
        v = max(0.0, min(100.0, float(vol)))
    except (TypeError, ValueError):
        v = VOL_DEFAULT
    if v <= 0:
        return None
    if v <= VOL_DEFAULT:
        return TTS_GAIN_DB + 20.0 * math.log10(v / VOL_DEFAULT)
    return TTS_GAIN_DB + (v - VOL_DEFAULT) / (100 - VOL_DEFAULT) * 6.0


def _boost_wav(wav, gain_db):
    """WAV 바이트(16비트) 음량을 gain_db 만큼 바꾼 새 WAV 바이트. 키울 땐 tanh 소프트 리미터로 클리핑 방지.
    캐시에는 원본을 두고 재생 직전에 적용한다(음량 단계가 바뀌어도 다시 합성하지 않게)."""
    if abs(gain_db) < 0.01:
        return wav
    import io
    import wave
    import numpy as np
    with wave.open(io.BytesIO(wav), "rb") as w:
        params = w.getparams()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    g = 10 ** (gain_db / 20.0)
    y = np.tanh(x * g) * 0.98 if gain_db > 0 else x * g
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams(params)
        w.writeframes((y * 32767.0).astype(np.int16).tobytes())
    return out.getvalue()


def _synth_cached(text, mlang="KR"):
    """(락 안에서 호출) 캐시에 있으면 그대로, 없으면 그 언어 모델로 합성해 캐시에 넣는다. 반환: (WAV 바이트, 합성초, 캐시적중)"""
    key = (mlang, text)
    wav = _cache.get(key)
    if wav is not None:
        _cache.move_to_end(key)
        return wav, 0.0, True
    model, sid = _models[mlang]
    t0 = time.time()
    model.tts_to_file(text, sid, OUT_WAV, speed=SPEED, quiet=True)
    dt = time.time() - t0
    with open(OUT_WAV, "rb") as f:
        wav = f.read()
    _cache[key] = wav
    while len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)
    return wav, dt, False


_waiting_lock = threading.Lock()
_waiting = 0   # 지금 락을 기다리는 실제 안내 요청 수(_waiting_lock 으로 보호) — 있으면 미리 합성(prewarm)이 다음 문장을 시작하지 않고 양보


def speak(text, out_path, do_play, epoch, t_arrive, mlang="KR", vol=VOL_DEFAULT):
    """텍스트 → WAV (+재생). 합성·재생을 락으로 함께 직렬화.
    flush 됐거나 너무 오래된 요청은 합성/재생하지 않는다. 반환: (합성초, 버린이유|None, 캐시적중)"""
    global _waiting
    with _waiting_lock:
        _waiting += 1
    try:
        _lock.acquire()
    finally:
        with _waiting_lock:
            _waiting -= 1
    try:
        return _speak_locked(text, out_path, do_play, epoch, t_arrive, mlang, vol)
    finally:
        _lock.release()


def _speak_locked(text, out_path, do_play, epoch, t_arrive, mlang, vol):
    why = _drop_reason(epoch, t_arrive)
    if why:
        return 0.0, why, False
    wav, dt, hit = _synth_cached(text, mlang)
    gain = _vol_gain_db(vol)
    if gain is None and do_play:         # 음량 0 = 무음: 합성(캐시)만 하고 재생 안 함
        return dt, None, hit
    wav = _boost_wav(wav, gain or 0.0)
    if not do_play:                      # /synth: 파일로 남겨 경로 반환
        with open(out_path, "wb") as f:
            f.write(wav)
        return dt, None, hit
    why = _drop_reason(epoch, t_arrive)
    if why:
        return dt, why, hit
    play(wav)
    return dt, None, hit


def prewarm(texts, mlang="KR"):
    """뒤에서 미리 합성해 캐시에 채운다. 문장 사이마다 락을 놓아 실제 요청이 오래 기다리지 않게.
    그 언어 모델이 아직 로드 중이면 로드될 때까지 기다린다(최대 10분)."""
    t0, n = time.time(), 0
    while mlang not in _models and time.time() - t0 < 600:
        time.sleep(2)
    if mlang not in _models:
        return
    for t in texts:
        if (mlang, t) in _cache:
            continue
        while _waiting > 0:              # 실제 안내가 기다리는 중 → 그쪽 먼저(CPU가 바쁘면 한 문장 합성이 수 초)
            time.sleep(0.05)
        with _lock:
            if (mlang, t) not in _cache:
                _synth_cached(t, mlang)
                n += 1
        time.sleep(0.05)
    print(f"[tts] 미리 합성 완료({mlang}): 새로 {n}문장 · {time.time()-t0:.1f}s · 캐시 {len(_cache)}문장", flush=True)


def _refresh_speaker():
    """스피커를 다시 찾는다(USB 재연결·서버가 먼저 켜진 경우). 바뀌었으면 볼륨·증폭 기본값도 맞춘다. 반환: 장치가 바뀌었나."""
    global SPEAKER, TTS_VOLUME, TTS_GAIN_DB
    was = SPEAKER
    SPEAKER = _detect_speaker()
    if not os.environ.get("TTS_VOLUME"):
        TTS_VOLUME = "100%" if _RESPEAKER else "80%"
    if not os.environ.get("TTS_GAIN_DB"):
        TTS_GAIN_DB = 6.0 if _RESPEAKER else 0.0
    _set_speaker_volume(SPEAKER, TTS_VOLUME)   # 재연결되면 장치 볼륨이 기본(마스터 −20dB)으로 돌아가 있음
    if SPEAKER != was:
        print(f"[tts] 스피커 다시 찾음: {was} → {SPEAKER} · 볼륨={TTS_VOLUME} · 증폭=+{TTS_GAIN_DB:g}dB", flush=True)
    return SPEAKER != was


def _aplay_once(wav):
    global _aplay
    _aplay = subprocess.Popen(["aplay", "-q", "-D", SPEAKER, "-"],
                              stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    err = _aplay.communicate(input=wav)[1]
    rc = _aplay.returncode
    _aplay = None
    return rc, err.decode('utf-8', 'ignore')


def play(wav):
    """WAV 바이트를 로봇 스피커로 재생 (동기, aplay 표준입력). 실패 시 로그로 남긴다(무음 원인 추적용).
    장치를 못 열면(USB 스피커가 빠졌다 다시 꽂힘·서버가 스피커보다 먼저 켜짐) 스피커를 다시 찾아 한 번 더 시도."""
    rc, msg = _aplay_once(wav)
    # -15 = flush 로 중단. aplay 가 SIGTERM 을 잡아 rc=1 + "Interrupted system call" 로 끝나는 경우도 정상 중단
    if rc in (0, -15) or "Interrupted system call" in msg:
        return
    if ("open error" in msg or "No such" in msg or "No such device" in msg) and _refresh_speaker():
        rc, msg = _aplay_once(wav)
        if rc in (0, -15) or "Interrupted system call" in msg:
            return
    print(f"[tts] ⚠ aplay 실패(device={SPEAKER}): {msg.strip()[:120]}", flush=True)


def flush():
    """대기 중 요청은 epoch 로 무효화, 재생 중이면 중단."""
    global _epoch
    _epoch += 1
    p = _aplay
    if p is not None and p.poll() is None:
        p.terminate()


class Handler(http.server.BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self._json({"ok": True, "ready": _model is not None, "langs": sorted(_models)})
        else:
            self.send_error(404)

    def do_POST(self):
        t_arrive = time.time()
        epoch = _epoch
        if self.path == "/flush":
            flush()
            print("[tts] flush — 밀린 요청 버림", flush=True)
            self._json({"ok": True, "flushed": True})
            return
        if self.path == "/prewarm":
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                pdata = json.loads(self.rfile.read(n)) if n else {}
                texts = [str(t).strip() for t in (pdata.get("texts") or []) if str(t).strip()][:CACHE_MAX]
                pml = _LANG_MAP.get(str(pdata.get("lang") or "ko"), ("KR",))[0]
            except Exception as exc:
                self._json({"ok": False, "error": f"bad request: {exc}"}, 400)
                return
            threading.Thread(target=prewarm, args=(texts, pml), daemon=True).start()
            self._json({"ok": True, "queued": len(texts)})
            return
        if self.path not in ("/tts", "/synth"):
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            data = json.loads(self.rfile.read(n)) if n else {}
            text = (data.get("text") or "").strip()
            mlang = _LANG_MAP.get(str(data.get("lang") or "ko"), ("KR",))[0]
            vol = data.get("vol", VOL_DEFAULT)       # 환자 화면 음량(0~100)
        except Exception as exc:
            self._json({"ok": False, "error": f"bad request: {exc}"}, 400)
            return
        if not text:
            self._json({"ok": False, "error": "empty text"}, 400)
            return
        if _model is None:
            self._json({"ok": False, "error": "model not ready"}, 503)
            return
        if mlang not in _models:                 # 그 언어 모델이 아직 로드 중/실패 → 엉뚱한 언어로 읽지 않음
            self._json({"ok": False, "error": "lang_not_ready"})
            return
        try:
            dt, why, hit = speak(text, OUT_WAV, self.path == "/tts", epoch, t_arrive, mlang, vol)
            if why:
                print(f"[tts] 재생 안 함({why}, {time.time()-t_arrive:.1f}s): {text[:30]}", flush=True)
                self._json({"ok": False, "error": why})
                return
            self._json({"ok": True, "synth_sec": round(dt, 2), "cached": hit, "wav": OUT_WAV})
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, 500)

    def log_message(self, *a):
        pass


def main():
    _set_speaker_volume(SPEAKER, TTS_VOLUME)   # 시작 시 스피커 볼륨을 TTS_VOLUME(기본 80%)로
    _load_model()
    threading.Thread(target=_load_others, daemon=True).start()   # 영·중·일은 뒤에서(한국어는 이미 준비됨)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler) as srv:
        print(f"[tts] http://127.0.0.1:{PORT}/  (POST /tts, /synth) · 스피커={SPEAKER} · 볼륨={TTS_VOLUME} · 증폭=+{TTS_GAIN_DB:g}dB", flush=True)
        srv.serve_forever()


if __name__ == "__main__":
    main()
