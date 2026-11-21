#!/usr/bin/env python3
# =========================================================================
# ui_recorder.py — 키오스크 웹 화면(UI)을 주소창·탭 없이 실시간 동영상 녹화
#
#   사용법:  python3 scripts/ui_recorder.py              녹화 전용 창(1600×900)을 띄우고 바로 녹화, Ctrl+C 로 끝
#            python3 scripts/ui_recorder.py --full       전체 화면(키오스크 모드, 1920×1080)으로 띄워 녹화
#   옵션:    --url http://localhost:8000/ (예: '?nurse=1' 화면)  --size 1600x900  --fps 15  --bitrate 4(Mbps)
#            --max-min 30(한 파일 최대 분)  --no-pointer(마우스 커서 안 찍음)  --keep-open(끝나도 창 유지)
#            --out /mnt/ssd/ui_videos  --display :1
#
#   주소창이 안 나오게 하는 방법:
#     · 보드 화면(:1)에 '녹화 전용' Chromium 을 앱 모드(--app)로 띄운다 → 탭·주소창·북마크 줄 자체가 없다.
#     · 그 창(X 창 id)만 녹화한다 → 창 제목줄(창 관리자가 그리는 테두리)과 바탕화면 위쪽 막대도 안 찍힌다.
#       다른 창에 가려져 있어도 키오스크 화면 내용만 찍힌다.
#     · 브라우저 언어를 한국어로, 번역 기능을 꺼서 '번역할까요?' 팝업이 안 뜨게 한다(영어 브라우저면 위에 뜸).
#     · 평소 쓰는 Chromium 과 섞이지 않게 전용 프로필(/mnt/ssd/ui_recorder/profile)을 쓴다.
#   녹화: GStreamer ximagesrc → 젯슨 하드웨어 인코더(nvv4l2h264enc) → MP4(조각 저장이라 중간에 꺼져도 재생 가능)
#   저장: /mnt/ssd/ui_videos/<날짜>/ui_<시각>.mp4  + 목록 /mnt/ssd/ui_videos/index.csv
#   ※ 화면 조작은 보드 화면(모니터·터치)에서 이 창으로 한다. 노트북 브라우저 화면은 녹화되지 않는다.
#   ※ 소리는 녹화하지 않는다(화면만).
# =========================================================================
import argparse
import csv
import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROFILE = Path("/mnt/ssd/ui_recorder/profile")
WM_CLASS = "KioskRecorder"
DEBUG_PORT = 9223


def now_s():
    return datetime.datetime.now().strftime("%H:%M:%S")


def x_env(display):
    env = dict(os.environ)
    env["DISPLAY"] = display or env.get("DISPLAY") or ":1"
    gdm = Path(f"/run/user/{os.getuid()}/gdm/Xauthority")
    if "XAUTHORITY" not in env and gdm.exists():
        env["XAUTHORITY"] = str(gdm)
    return env


def prepare_profile():
    """번역 팝업·첫 실행 안내·'페이지 복구' 말풍선이 안 뜨게 전용 프로필 설정."""
    pf = PROFILE / "Default" / "Preferences"
    pf.parent.mkdir(parents=True, exist_ok=True)
    try:
        d = json.loads(pf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("translate", {})["enabled"] = False
    d["translate_blocked_languages"] = ["ko", "en"]
    d.setdefault("intl", {}).update({"selected_languages": "ko-KR,ko,en-US,en", "accept_languages": "ko-KR,ko,en-US,en"})
    prof = d.setdefault("profile", {})
    prof["exit_type"] = "Normal"
    prof["exited_cleanly"] = True
    prof["password_manager_enabled"] = False
    d["credentials_enable_service"] = False
    d.setdefault("browser", {})["has_seen_welcome_page"] = True
    pf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def browser_pids():
    """전용 프로필로 뜬 Chromium 주 프로세스 pid 목록(크롬은 명령줄을 한 줄 문자열로 바꿔 둠)."""
    out = []
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            s = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "ignore")
        except OSError:
            continue
        if f"--user-data-dir={PROFILE}" in s and "--type=" not in s and s.split(" ")[0].endswith("chrome"):
            out.append(int(p.name))
    return out


def find_window(env):
    """(xid, 너비, 높이) — 전용 창(클래스 KioskRecorder) 중 화면에 보이는 가장 큰 것."""
    try:
        out = subprocess.run(["xwininfo", "-root", "-tree"], env=env, capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    cands = []
    for line in out.splitlines():
        m = re.match(r'\s*(0x[0-9a-f]+) "(.*)": \("([^"]*)" "([^"]*)"\)\s+(\d+)x(\d+)\+', line)
        if m and m.group(4) == WM_CLASS and int(m.group(5)) >= 300 and int(m.group(6)) >= 200:
            cands.append((int(m.group(5)) * int(m.group(6)), m.group(1), int(m.group(5)), int(m.group(6))))
    for _, xid, w, h in sorted(cands, reverse=True):
        try:
            info = subprocess.run(["xwininfo", "-id", xid], env=env, capture_output=True, text=True, timeout=5).stdout
        except Exception:
            continue
        if "IsViewable" in info:
            w = int(re.search(r"Width: (\d+)", info).group(1))
            h = int(re.search(r"Height: (\d+)", info).group(1))
            return xid, w, h
    return None


def launch_browser(a, env, log):
    prepare_profile()
    args = ["chromium-browser", f"--user-data-dir={PROFILE}", f"--remote-debugging-port={DEBUG_PORT}",
            "--no-first-run", "--no-default-browser-check", "--disable-session-crashed-bubble",
            "--disable-features=Translate,TranslateUI", "--lang=ko-KR", "--accept-lang=ko-KR,ko",
            "--password-store=basic", f"--class={WM_CLASS}"]
    if a.full:
        args += ["--kiosk"]
    else:
        w, h = a.size
        args += [f"--window-size={w},{h}", "--window-position=80,60"]
    args += [f"--app={a.url}"]
    return subprocess.Popen(args, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def close_browser():
    for pid in browser_pids():
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    t0 = time.time()
    while browser_pids() and time.time() - t0 < 8:
        time.sleep(0.3)


class Recording:
    def __init__(self, a, env, xid, w, h, part):
        self.a, self.t0 = a, time.time()
        d = Path(a.out) / datetime.datetime.now().strftime("%Y-%m-%d")
        d.mkdir(parents=True, exist_ok=True)
        self.path = d / f"ui_{datetime.datetime.now():%Y%m%d_%H%M%S}{'_' + str(part) if part > 1 else ''}.mp4"
        self.size = f"{w - w % 2}×{h - h % 2}"
        el = ["ximagesrc", f"display-name={env['DISPLAY']}", f"xid={xid}", "use-damage=false",
              f"show-pointer={'false' if a.no_pointer else 'true'}", "!", f"video/x-raw,framerate={a.fps}/1"]
        if w % 2 or h % 2:                      # 하드웨어 변환은 홀수 크기에서 검은 화면 → 1픽셀 잘라 짝수로
            el += ["!", "videocrop", f"right={w % 2}", f"bottom={h % 2}"]
        el += ["!", "nvvidconv", "!", "video/x-raw(memory:NVMM),format=NV12",
               "!", "nvv4l2h264enc", f"bitrate={int(a.bitrate * 1_000_000)}", f"iframeinterval={a.fps * 2}",
               "insert-sps-pps=true", "!", "h264parse", "!", "mp4mux", "fragment-duration=1000",
               "!", "filesink", f"location={self.path}"]
        self.err_path = self.path.with_suffix(".log")
        self.err = open(self.err_path, "w")
        self.proc = subprocess.Popen(["gst-launch-1.0", "-q", "-e"] + el, env=env, stdout=self.err,
                                     stderr=subprocess.STDOUT, start_new_session=True)
        print(f"[{now_s()}] ● 녹화 시작 {self.size} → {self.path}", flush=True)

    def alive(self):
        return self.proc.poll() is None

    def stop(self, why=""):
        if self.alive():
            try:
                os.killpg(self.proc.pid, signal.SIGINT)        # -e: MP4 를 깔끔하게 마무리
                self.proc.wait(timeout=15)
            except Exception:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except Exception:
                    pass
        self.err.close()
        dur = time.time() - self.t0
        mb = self.path.stat().st_size / 1e6 if self.path.exists() else 0.0
        ok = mb > 0.05
        print(f"[{now_s()}] ■ 녹화 끝{(' (' + why + ')') if why else ''} — {dur:.0f}초 · {mb:.1f} MB"
              + ("" if ok else f"\n           ⚠ 영상이 비었습니다. 오류 기록: {self.err_path}"), flush=True)
        if ok:
            try:
                if "ERROR" not in self.err_path.read_text(errors="ignore"):
                    self.err_path.unlink()
            except OSError:
                pass
        idx = Path(self.a.out) / "index.csv"
        new = not idx.exists()
        with open(idx, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["시작", "끝", "길이_초", "크기", "주소", "용량_MB", "파일", "메모"])
            w.writerow([datetime.datetime.fromtimestamp(self.t0).strftime("%Y-%m-%d %H:%M:%S"),
                        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), f"{dur:.0f}", self.size,
                        self.a.url, f"{mb:.1f}", str(self.path), why])
        return ok


def main():
    ap = argparse.ArgumentParser(description="키오스크 웹 화면을 주소창 없이 녹화")
    ap.add_argument("--url", default="http://localhost:8000/")
    ap.add_argument("--full", action="store_true", help="전체 화면(키오스크 모드)")
    ap.add_argument("--size", default="1600x900", help="창 크기(전체 화면이 아닐 때)")
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--bitrate", type=float, default=4.0, help="Mbps")
    ap.add_argument("--max-min", type=float, default=30.0, help="한 파일 최대 분(넘으면 새 파일)")
    ap.add_argument("--no-pointer", action="store_true", help="마우스 커서 안 찍음")
    ap.add_argument("--keep-open", action="store_true", help="녹화가 끝나도 창을 닫지 않음")
    ap.add_argument("--out", default="/mnt/ssd/ui_videos")
    ap.add_argument("--display", default=None)
    a = ap.parse_args()
    try:
        a.size = tuple(int(x) for x in a.size.lower().split("x"))
    except ValueError:
        print("⚠ --size 는 1600x900 처럼 입력")
        return 1
    if not str(Path(a.out).resolve()).startswith("/mnt/ssd"):
        print("⚠ 저장 위치는 /mnt/ssd 아래여야 합니다(eMMC 가 거의 가득 참).")
        return 1
    Path(a.out).mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(a.out).free / 1e9 < 3:
        print("⚠ SSD 여유가 3 GB 미만이라 녹화하지 않습니다.")
        return 1
    try:
        urllib.request.urlopen(a.url, timeout=3)
    except Exception as exc:
        print(f"⚠ {a.url} 에 연결이 안 됩니다({exc}). 안내 서버(start_guide/start_voice_ui)가 켜져 있는지 확인하세요.")
        return 1

    stop = {"v": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("v", True))
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__("v", True))
    env = x_env(a.display)

    win = find_window(env)
    log = open(Path(a.out) / "chromium.log", "a")
    if win and not a.full:
        print(f"[{now_s()}] 이미 떠 있는 녹화 전용 창을 씁니다.")
    else:
        if browser_pids():
            close_browser()                      # 창 모드↔전체 화면 바꿀 때 새로 띄움
        print(f"[{now_s()}] 녹화 전용 창을 띄웁니다: {a.url} ({'전체 화면' if a.full else f'{a.size[0]}×{a.size[1]}'}, 화면 {env['DISPLAY']})")
        launch_browser(a, env, log)
        t0 = time.time()
        win = None
        while time.time() - t0 < 25 and not stop["v"]:
            win = find_window(env)
            if win and (not a.full or win[1] >= 1000):
                break
            time.sleep(0.5)
        if not win:
            print("⚠ 창이 뜨지 않았습니다. 기록: " + str(Path(a.out) / "chromium.log"))
            return 1
        time.sleep(2.0)                          # 첫 화면이 다 그려질 때까지
        win = find_window(env) or win
    print("  화면 조작은 보드 화면의 이 창에서 하세요. 끝내려면 이 터미널에서 Ctrl+C"
          + (" (전체 화면은 Alt+F4 로도 닫힘)." if a.full else "."), flush=True)

    part, rec, fails = 1, None, 0
    while not stop["v"]:
        if rec is None:
            win = find_window(env)
            if not win:
                print(f"[{now_s()}] 창이 닫혔습니다 → 끝냅니다.")
                break
            rec = Recording(a, env, win[0], win[1], win[2], part)
        time.sleep(0.5)
        if not rec.alive():                      # 창 크기를 바꾸거나 창을 닫으면 녹화기가 멈춤
            ok = rec.stop("창 크기 바뀜·창 닫힘")
            rec = None
            part += 1
            fails = 0 if ok else fails + 1
            if fails >= 3:
                print("⚠ 녹화가 연달아 실패해 끝냅니다.")
                break
            time.sleep(1.0)
        elif time.time() - rec.t0 > a.max_min * 60:
            rec.stop(f"{a.max_min:g}분 넘어 새 파일로")
            rec = None
            part += 1
    if rec:
        rec.stop("Ctrl+C")
    if not a.keep_open:
        close_browser()
    log.close()
    print("종료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
