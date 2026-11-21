#!/usr/bin/env python3
# =========================================================================
# audio_selftest.py — reSpeaker 마이크·스피커가 '실제로' 동작하는지 자가 점검
#
#   사용법:  python3 scripts/audio_selftest.py            점검(스피커로 짧은 '삐' 0.4초)
#            python3 scripts/audio_selftest.py --no-amp   스피커 무음이어도 앰프 켜기 시도 안 함
#   종료 코드: 0 = 둘 다 정상 · 2 = 스피커 무음 · 3 = 마이크 이상 · 1 = 장치 없음·사용 중 등
#
#   방법(2026-11-15 수정): 스피커로 2 kHz '삐'를 내면서 **웹캠 마이크**로 녹음해 판정(사람 확인 없이).
#     ※ reSpeaker 자기 마이크로는 판정 불가 — 에코 제거가 원음 채널(2~5번)에서도 자기 스피커 소리를 지워서,
#       스피커가 잘 울릴 때도 +0~10 dB 로만 잡힘(실측: 정상 −2~+10 dB / 무음 때도 +8~10 dB → 구분 안 됨).
#       웹캠 마이크는 reSpeaker 재생을 모르니 그대로 들림(실측: 정상 +84~+101 dB).
#     · 마이크: 1초당 받은 데이터 양(멈춤 없음) + 원음 채널 잡음이 0 이 아님(살아 있음)
#     · 스피커: 웹캠 마이크로 들은 '삐' 구간 2 kHz 세기 ÷ 직전 조용한 구간 ≥ SPEAKER_MIN_DB(기본 40 dB). 웹캠 없으면 판정 불가
#     스피커 무음이면 앰프 핀(X0D31)을 읽어 원인을 구분하고(꺼짐이면 켜고 다시 점검) — respeaker_ctl.py
#   배경: 소리 데이터는 장치까지 가는데(오류 없음) 스피커가 무음인 상태를 키오스크가 알 수 없었음.
# =========================================================================
import argparse
import math
import os
import struct
import subprocess
import sys
import time

DEV = os.environ.get("SELFTEST_DEVICE", "plughw:CARD=C16K6Ch,DEV=0")
DETECT_DEV = os.environ.get("SELFTEST_DETECT_DEVICE", "plughw:CARD=WEBCAM,DEV=0")   # 스피커 판정용 독립 마이크
RATE, CH = 16000, 6
RAW_CH = (2, 3, 4, 5)                     # 원음 마이크(에코 제거 전)
TONE_HZ, TONE_SEC, TONE_AMP = 2000.0, 0.4, 0.25
# 기준(2026-11-15 실측, 웹캠 마이크): 정상 +84~+101 dB → 40 dB 이상이면 '울림'
SPEAKER_MIN_DB = float(os.environ.get("SELFTEST_SPEAKER_MIN_DB", "40"))
HERE = os.path.dirname(os.path.abspath(__file__))


def tone_wav():
    n = int(RATE * TONE_SEC)
    fade = int(RATE * 0.02)
    frames = bytearray()
    for i in range(n):
        env = min(1.0, i / fade, (n - 1 - i) / fade)
        v = int(32767 * TONE_AMP * env * math.sin(2 * math.pi * TONE_HZ * i / RATE))
        frames += struct.pack("<hh", v, v)
    hdr = b"RIFF" + struct.pack("<I", 36 + len(frames)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 2, RATE, RATE * 4, 4, 16)
    return hdr + b"data" + struct.pack("<I", len(frames)) + bytes(frames)


def goertzel(xs, hz):
    k = 2 * math.cos(2 * math.pi * hz / RATE)
    s1 = s2 = 0.0
    for x in xs:
        s1, s2 = x + k * s1 - s2, s1
    return (s1 * s1 + s2 * s2 - k * s1 * s2) / max(1, len(xs)) ** 2


def channel(raw, c, start_s, end_s):
    a = struct.unpack("<%dh" % (len(raw) // 2), raw[: len(raw) // 12 * 12])
    i0, i1 = int(start_s * RATE), int(end_s * RATE)
    return a[i0 * CH + c: i1 * CH: CH]


def run_once():
    """→ (mic_ok, mic_msg, spk_ok, spk_msg, ratio_db)"""
    rec = subprocess.Popen(["arecord", "-q", "-D", DEV, "-f", "S16_LE", "-r", str(RATE), "-c", str(CH), "-d", "3", "-t", "raw", "-"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    cam = subprocess.Popen(["arecord", "-q", "-D", DETECT_DEV, "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-d", "3", "-t", "raw", "-"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(1.2)
    play_err = ""
    for _ in range(3):                    # TTS 가 재생 중이면 잠깐 기다렸다 다시
        p = subprocess.run(["aplay", "-q", "-D", DEV, "-"], input=tone_wav(), capture_output=True)
        play_err = p.stderr.decode("utf-8", "ignore").strip()
        if p.returncode == 0:
            break
        time.sleep(0.8)
    raw, err = rec.communicate(timeout=10)
    craw, cerr = cam.communicate(timeout=10)
    got = len(raw) / (RATE * CH * 2)
    if rec.returncode not in (0, None) and got < 0.5:
        return False, f"녹음 실패: {err.decode('utf-8', 'ignore').strip()[:100]}", False, "판정 불가", 0.0
    # 마이크: 데이터 양 + 원음 잡음
    noise = [math.sqrt(sum(x * x for x in channel(raw, c, 0.2, 1.0)) / (0.8 * RATE)) for c in RAW_CH]
    mic_ok = got >= 2.7 and min(noise) > 1.0
    mic_msg = f"데이터 {got:.2f}/3초 · 원음 마이크 잡음 {min(noise):.0f}~{max(noise):.0f}"
    if got < 2.7:
        mic_msg += " ← 녹음이 중간에 멈춤(비정상 사양·USB 문제)"
    elif min(noise) <= 1.0:
        mic_msg += " ← 마이크 신호 없음(음소거 버튼·하드웨어 확인)"
    if play_err and p.returncode != 0:
        return mic_ok, mic_msg, False, f"재생 실패: {play_err[:100]}", 0.0
    # 스피커: 웹캠 마이크로 들은 '삐'(1.2~1.6초 근처) 2 kHz 세기 ÷ 조용한 구간(0.2~1.0초)
    if len(craw) < RATE * 2 * 2:
        return mic_ok, mic_msg, False, f"판정 불가 — 웹캠 마이크({DETECT_DEV}) 녹음 실패: {cerr.decode('utf-8', 'ignore').strip()[:80]}", 0.0
    ca = struct.unpack("<%dh" % (len(craw) // 2), craw[: len(craw) // 2 * 2])
    seg = lambda s, e: ca[int(s * RATE): int(e * RATE)]
    base = goertzel(seg(0.2, 1.0), TONE_HZ) + 1e-9
    tone = max(goertzel(seg(t, t + 0.3), TONE_HZ) for t in (1.2, 1.3, 1.4, 1.5, 1.6))
    best = 10 * math.log10(tone / base + 1e-12)
    spk_ok = best >= SPEAKER_MIN_DB
    spk_msg = f"웹캠 마이크로 들은 '삐' {best:+.1f} dB (기준 {SPEAKER_MIN_DB:.0f} dB 이상)"
    if not spk_ok:
        spk_msg += " ← 소리 데이터는 보냈는데 스피커에서 소리가 안 남"
    return mic_ok, mic_msg, spk_ok, spk_msg, best


def amp_state():
    """앰프 핀 읽기 → (값 또는 None, 메시지). 값 1 = 꺼짐, 0 = 켜짐"""
    r = subprocess.run([sys.executable, os.path.join(HERE, "respeaker_ctl.py"), "status"], capture_output=True, text=True)
    if r.returncode != 0:
        return None, (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else "읽기 실패"
    for line in r.stdout.splitlines():
        if "X0D31" in line:
            v = line.rsplit(":", 1)[-1].strip()
            return (int(v) if v.isdigit() else None), line.strip()
    return None, (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else "읽기 실패"


def main():
    ap = argparse.ArgumentParser(description="reSpeaker 마이크·스피커 자가 점검")
    ap.add_argument("--no-amp", action="store_true", help="스피커 무음이어도 앰프 켜기 시도 안 함")
    a = ap.parse_args()
    mic_ok, mic_msg, spk_ok, spk_msg, _ = run_once()
    print(f"[점검] 마이크  {'정상' if mic_ok else '이상'} — {mic_msg}", flush=True)
    print(f"[점검] 스피커  {'정상' if spk_ok else '무음'} — {spk_msg}", flush=True)
    if not spk_ok and "재생 실패" not in spk_msg and "판정 불가" not in spk_msg:
        v, msg = amp_state()
        if v is None:
            print(f"[점검]   앰프 핀 확인 불가: {msg}", flush=True)
        elif v == 0:
            print("[점검]   앰프 핀 X0D31 = 0(켜짐) — 앰프는 켜져 있는데 무음 → 스피커 커넥터 접촉·선 확인(11-15 21:44 커넥터를"
                  " 다시 꽂은 뒤 해결된 전례)", flush=True)
        else:
            print("[점검]   앰프 핀 X0D31 = 1(꺼짐) ← 무음 원인(장치가 앰프를 끈 채 시작)", flush=True)
            if not a.no_amp:
                subprocess.run([sys.executable, os.path.join(HERE, "respeaker_ctl.py"), "amp-on"], capture_output=True)
                time.sleep(0.3)
                mic_ok, mic_msg, spk_ok, spk_msg, _ = run_once()
                print(f"[점검]   앰프 켠 뒤 스피커 {'정상' if spk_ok else '여전히 무음'} — {spk_msg}", flush=True)
    if not mic_ok:
        return 3
    return 0 if spk_ok else 2


if __name__ == "__main__":
    sys.exit(main())
