#!/usr/bin/env python3
# =========================================================================
# rviz_recorder.py — 자율주행할 때 RViz 화면을 자동으로 동영상 녹화
#
#   사용법:  python3 scripts/rviz_recorder.py            대기하다가 주행이 시작되면 자동 녹화(Ctrl+C 로 종료)
#            python3 scripts/rviz_recorder.py --now      지금 바로 녹화 시작, Ctrl+C 로 끝(시험용)
#   옵션:    --screen      RViz 창 대신 보드 화면 전체를 녹화
#            --fps 10  --bitrate 4(Mbps)  --tail 5(주행 끝난 뒤 더 찍는 초)  --max-min 20(한 파일 최대 분)
#            --out /mnt/ssd/rviz_videos  --display :1
#
#   언제 찍나: Nav2 목표가 시작되면(logs/navigation.log 'Begin navigating') 또는 키오스크 상태가
#             moving/arrived/returning/aligning 이면 녹화를 시작하고, 둘 다 끝난 뒤 --tail 초가 지나면 멈춘다.
#             → 안내 한 번(출발 → 도착 → 대기 → 복귀 → 방향 정렬)이 영상 1개. RViz 에서 직접 준 Nav2 Goal 도 찍힘.
#   무엇을:   RViz 창(다른 창에 가려져 있어도 RViz 내용만 찍힘). 창을 못 찾거나 최소화돼 있으면 화면 전체.
#   어떻게:   GStreamer ximagesrc → 젯슨 하드웨어 인코더(nvv4l2h264enc) → MP4(조각 저장이라 중간에 꺼져도 재생 가능)
#             1920×1080·10fps 기준 CPU 코어 하나의 약 30%, 4 Mbps ≈ 시간당 1.8 GB.
#   저장:     /mnt/ssd/rviz_videos/<날짜>/rviz_<시각>_<목적지>.mp4  + 목록 /mnt/ssd/rviz_videos/index.csv
#   ※ 읽기만 한다(로봇·Nav2 에 명령을 보내지 않음).
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAVLOG = Path(os.environ.get("RVIZ_REC_NAVLOG", ROOT / "logs" / "navigation.log"))
STATUS = Path(os.environ.get("RVIZ_REC_STATUS", "/mnt/ssd/cart_ros2/src/llm_package/bus/kiosk_status.json"))
ACTIVE_STATES = {"moving", "arrived", "returning", "aligning"}
STATUS_STALE_SEC = 600          # 상태 파일이 이보다 오래 안 바뀌면(감시기 꺼짐 등) 주행 중으로 보지 않음
MIN_FREE_GB = 3.0
RE_BEGIN = re.compile(r"\[bt_navigator\]: Begin navigating from current location to \(([-\d.]+), ([-\d.]+)\)")
RE_END = re.compile(r"\[bt_navigator\]: Goal (succeeded|failed|canceled|was canceled)")
RESULT_KO = {"succeeded": "성공", "failed": "실패", "canceled": "취소", "was canceled": "취소"}


def now_s():
    return datetime.datetime.now().strftime("%H:%M:%S")


class Tail:
    def __init__(self, path):
        self.path = Path(path)
        self.pos = self.path.stat().st_size if self.path.exists() else 0

    def read(self):
        if not self.path.exists():
            return []
        size = self.path.stat().st_size
        if size < self.pos:                 # 안내 서버 재시작으로 새 로그
            self.pos = 0
        with open(self.path, "rb") as f:
            f.seek(self.pos)
            data = f.read()
            self.pos = f.tell()
        return data.decode("utf-8", "ignore").splitlines()


def read_status():
    try:
        return json.loads(STATUS.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── 화면(X) 찾기 ──
def rviz_pids():
    out = []
    for p in Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                if (p / "comm").read_text().strip() == "rviz2":
                    out.append(int(p.name))
            except OSError:
                pass
    return out


def x_env(display_opt):
    """녹화에 쓸 DISPLAY·XAUTHORITY. RViz 가 떠 있으면 그 값, 아니면 지정값·로그인 화면 기본값."""
    env = dict(os.environ)
    for pid in rviz_pids():
        try:
            kv = dict(x.split("=", 1) for x in Path(f"/proc/{pid}/environ").read_text().split("\0") if "=" in x)
        except OSError:
            continue
        if kv.get("DISPLAY"):
            env["DISPLAY"] = display_opt or kv["DISPLAY"]
            if kv.get("XAUTHORITY"):
                env["XAUTHORITY"] = kv["XAUTHORITY"]
            return env
    env["DISPLAY"] = display_opt or env.get("DISPLAY") or ":1"
    gdm = Path(f"/run/user/{os.getuid()}/gdm/Xauthority")
    if "XAUTHORITY" not in env and gdm.exists():
        env["XAUTHORITY"] = str(gdm)
    return env


def find_rviz_window(env):
    """(xid, 제목, 너비, 높이) 또는 None — 화면에 보이는(IsViewable) RViz 창 중 가장 큰 것."""
    try:
        out = subprocess.run(["xwininfo", "-root", "-tree"], env=env, capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    cands = []
    for line in out.splitlines():
        m = re.match(r'\s*(0x[0-9a-f]+) "(.*)": \("([^"]*)" "([^"]*)"\)\s+(\d+)x(\d+)\+', line)
        if not m:
            continue
        xid, title, c1, c2, w, h = m.group(1), m.group(2), m.group(3), m.group(4), int(m.group(5)), int(m.group(6))
        if ("rviz" in (c1 + c2).lower() or "RViz" in title) and w >= 300 and h >= 200:
            cands.append((("RViz" in title), w * h, xid, title, w, h))
    for _, _, xid, title, w, h in sorted(cands, reverse=True):
        try:
            info = subprocess.run(["xwininfo", "-id", xid], env=env, capture_output=True, text=True, timeout=5).stdout
        except Exception:
            continue
        if "IsViewable" in info:
            return xid, title, w, h
    return None


def screen_size(env):
    try:
        out = subprocess.run(["xwininfo", "-root"], env=env, capture_output=True, text=True, timeout=5).stdout
        w = int(re.search(r"Width: (\d+)", out).group(1))
        h = int(re.search(r"Height: (\d+)", out).group(1))
        return w, h
    except Exception:
        return None


# ── 녹화 ──
class Recording:
    def __init__(self, args, place):
        self.args = args
        self.env = x_env(args.display)
        self.place = place
        self.results = []
        self.t0 = time.time()
        day = datetime.datetime.now().strftime("%Y-%m-%d")
        d = Path(args.out) / day
        d.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w가-힣.-]+", "_", place or "주행").strip("_") or "주행"
        self.path = d / f"rviz_{datetime.datetime.now():%Y%m%d_%H%M%S}_{safe}.mp4"
        win = None if args.screen else find_rviz_window(self.env)
        if win:
            self.xid, title, w, h = win
            self.target = f"RViz 창 '{title[:40]}' {w}×{h}"
        else:
            self.xid = None
            sz = screen_size(self.env) or (1920, 1080)
            w, h = sz
            self.target = f"화면 전체 {w}×{h}" + ("" if args.screen else " (RViz 창을 못 찾음 — 꺼져 있거나 최소화)")
        src = ["ximagesrc", f"display-name={self.env['DISPLAY']}", "use-damage=false", "show-pointer=true"]
        if self.xid:
            src.append(f"xid={self.xid}")
        el = src + ["!", f"video/x-raw,framerate={args.fps}/1"]
        if w % 2 or h % 2:                  # 하드웨어 변환은 홀수 크기에서 검은 화면 → 1픽셀 잘라 짝수로
            el += ["!", "videocrop", f"right={w % 2}", f"bottom={h % 2}"]
        el += ["!", "nvvidconv", "!", "video/x-raw(memory:NVMM),format=NV12",
               "!", "nvv4l2h264enc", f"bitrate={int(args.bitrate * 1_000_000)}", f"iframeinterval={args.fps * 2}",
               "insert-sps-pps=true", "!", "h264parse", "!", "mp4mux", "fragment-duration=1000",
               "!", "filesink", f"location={self.path}"]
        self.err_path = self.path.with_suffix(".log")
        self.err = open(self.err_path, "w")
        self.proc = subprocess.Popen(["gst-launch-1.0", "-q", "-e"] + el, env=self.env, stdout=self.err,
                                     stderr=subprocess.STDOUT, start_new_session=True)
        print(f"[{now_s()}] ● 녹화 시작 — {self.target}\n           → {self.path}", flush=True)

    def alive(self):
        return self.proc.poll() is None

    def stop(self, why=""):
        if self.alive():
            try:
                os.killpg(self.proc.pid, signal.SIGINT)        # -e: 끝 표시를 보내 MP4 를 깔끔하게 마무리
                self.proc.wait(timeout=15)
            except Exception:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except Exception:
                    pass
        self.err.close()
        dur = time.time() - self.t0
        size = self.path.stat().st_size / 1e6 if self.path.exists() else 0.0
        res = " · ".join(self.results) or "-"
        ok = size > 0.05
        print(f"[{now_s()}] ■ 녹화 끝 {('(' + why + ') ') if why else ''}— {dur:.0f}초 · {size:.1f} MB · Nav2 결과: {res}"
              + ("" if ok else f"\n           ⚠ 영상이 비었습니다. 오류 기록: {self.err_path}"), flush=True)
        if ok:
            try:
                txt = self.err_path.read_text(errors="ignore")
                if "ERROR" not in txt:
                    self.err_path.unlink()               # 정상이면 오류 기록 파일은 지움(우리가 만든 빈 기록)
            except OSError:
                pass
        idx = Path(self.args.out) / "index.csv"
        new = not idx.exists()
        with open(idx, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["시작", "끝", "길이_초", "목적지", "Nav2결과", "대상", "크기_MB", "파일", "메모"])
            w.writerow([datetime.datetime.fromtimestamp(self.t0).strftime("%Y-%m-%d %H:%M:%S"),
                        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), f"{dur:.0f}", self.place, res,
                        self.target, f"{size:.1f}", str(self.path), why])


def free_gb(path):
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(p).free / 1e9


def main():
    ap = argparse.ArgumentParser(description="자율주행할 때 RViz 화면 자동 녹화")
    ap.add_argument("--now", action="store_true", help="지금 바로 녹화, Ctrl+C 로 끝")
    ap.add_argument("--screen", action="store_true", help="RViz 창 대신 화면 전체")
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--bitrate", type=float, default=4.0, help="Mbps")
    ap.add_argument("--tail", type=float, default=5.0, help="주행이 끝난 뒤 더 찍는 초")
    ap.add_argument("--max-min", type=float, default=20.0, help="한 파일 최대 분(넘으면 새 파일)")
    ap.add_argument("--out", default="/mnt/ssd/rviz_videos")
    ap.add_argument("--display", default=None, help="예: :1 (기본: RViz 가 떠 있는 화면)")
    a = ap.parse_args()
    if not str(Path(a.out).resolve()).startswith("/mnt/ssd"):
        print("⚠ 저장 위치는 /mnt/ssd 아래여야 합니다(eMMC 가 거의 가득 참).")
        return 1
    if shutil.which("gst-launch-1.0") is None:
        print("⚠ gst-launch-1.0 이 없습니다.")
        return 1

    stop_flag = {"v": False}
    signal.signal(signal.SIGINT, lambda *_: stop_flag.__setitem__("v", True))
    signal.signal(signal.SIGTERM, lambda *_: stop_flag.__setitem__("v", True))

    if a.now:
        rec = Recording(a, "수동")
        while not stop_flag["v"] and rec.alive():
            time.sleep(0.3)
        rec.stop("수동 종료" if rec.alive() else "녹화 프로그램이 멈춤")
        return 0

    env = x_env(a.display)
    win = None if a.screen else find_rviz_window(env)
    print(f"[RViz 자동 녹화] 화면 {env['DISPLAY']} · 대상: "
          + ("화면 전체" if a.screen else (f"RViz 창 {win[2]}×{win[3]}" if win else "RViz 창(지금은 안 보임 — 녹화 시작 때 다시 찾음)"))
          + f" · {a.fps}fps · {a.bitrate:g} Mbps · 저장 {a.out} (여유 {free_gb(a.out):.0f} GB)")
    print("  주행이 시작되면 자동으로 녹화합니다. 끝내려면 Ctrl+C.", flush=True)
    nav = Tail(NAVLOG)
    nav_active, nav_since, goal_xy = False, 0.0, None
    rec, last_active, fails = None, 0.0, 0
    while not stop_flag["v"]:
        t = time.time()
        for line in nav.read():
            m = RE_BEGIN.search(line)
            if m:
                nav_active, nav_since, goal_xy = True, t, (float(m.group(1)), float(m.group(2)))
                continue
            m = RE_END.search(line)
            if m:
                nav_active = False
                if rec:                                     # 목표마다 결과(가는 길·복귀 길 순서대로)
                    rec.results.append(RESULT_KO.get(m.group(1), m.group(1)))
        if nav_active and t - nav_since > a.max_min * 60:      # 끝 줄을 못 봤으면(로그 끊김) 계속 찍지 않게
            nav_active = False
        st = read_status()
        fresh = t - float(st.get("updated_at", 0) or 0) < STATUS_STALE_SEC
        kiosk_active = fresh and st.get("state") in ACTIVE_STATES
        active = nav_active or kiosk_active
        if active:
            last_active = t
        if rec is None and active:
            if free_gb(a.out) < MIN_FREE_GB:
                print(f"[{now_s()}] ⚠ SSD 여유 {free_gb(a.out):.1f} GB — {MIN_FREE_GB:g} GB 미만이라 녹화하지 않습니다.", flush=True)
                time.sleep(30)
                continue
            place = st.get("place") if kiosk_active and st.get("place") else (
                f"목표_{goal_xy[0]:.1f}_{goal_xy[1]:.1f}" if goal_xy else "주행")
            rec = Recording(a, place)
        elif rec is not None:
            if kiosk_active and st.get("place") and rec.place.startswith("목표_") and st.get("place") != "초기 위치":
                rec.place = st["place"]
            if not rec.alive():
                rec.stop("녹화 프로그램이 멈춤")
                rec = None
                fails += 1
                if fails >= 3:
                    print(f"[{now_s()}] ⚠ 녹화가 연달아 멈춰 1분 쉬었다가 다시 시도합니다.", flush=True)
                    time.sleep(60)
                    fails = 0
                continue
            if not active and t - last_active >= a.tail:
                rec.stop()
                rec, fails = None, 0
            elif t - rec.t0 > a.max_min * 60:
                rec.stop(f"{a.max_min:g}분 넘어 새 파일로")
                rec = None
            elif free_gb(a.out) < 1.0:
                rec.stop("SSD 여유 부족")
                rec = None
        time.sleep(0.5)
    if rec:
        rec.stop("Ctrl+C")
    print("종료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
