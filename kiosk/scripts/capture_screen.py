#!/usr/bin/env python3
# =========================================================================
# capture_screen.py — 주행 중 보드 화면을 몇 초마다 캡처(논문 그림용)
#
#   사용법:  python3 scripts/capture_screen.py                  주행 중일 때만, 3초마다, 모니터 전체
#            python3 scripts/capture_screen.py -i 2 -t kiosk     2초마다, 키오스크 앱 창만
#            python3 scripts/capture_screen.py -t rviz           RViz 창만(start_guide.sh 로 RViz 켠 경우)
#            python3 scripts/capture_screen.py -w always         주행과 상관없이 계속
#            python3 scripts/capture_screen.py -d 600            10분 뒤 자동 종료(기본: Ctrl+C 까지)
#   종료: Ctrl+C
#
#   저장: /mnt/ssd/screenshots/screens_YYYYmmdd_HHMMSS/
#         ├─ 0001_주행_내과_20261113_013012.png …   (번호_상태_목적지_시각)
#         └─ index.csv   (번호·시각·파일·상태·목적지·남은 거리·진행률 — 논문 그림 설명용)
#   '주행 중' = 키오스크 상태 파일(bus/kiosk_status.json)의 state 가 moving(목적지로 이동)·returning(초기 위치로 복귀)·arrived(도착 직후)
#   ※ 창만 찍기(-t kiosk/rviz)는 창 자체 내용을 읽어서(xwd) 다른 창에 가려져 있어도 그 창이 찍힌다(최소화는 안 됨).
#     브라우저 탭·주소창을 빼려면 --crop-top 87 처럼 위쪽을 잘라낸다(또는 키오스크를 F11 전체 화면으로).
#   ※ SSH 로 접속해 실행해도 보드 모니터(:1)를 찍는다.
# =========================================================================
import argparse
import csv
import datetime
import json
import os
import re
import subprocess
import sys
import time

STATUS = "/mnt/ssd/cart_ros2/src/llm_package/bus/kiosk_status.json"
OUT_ROOT = "/mnt/ssd/screenshots"
STATE_KO = {"moving": "주행", "returning": "복귀", "arrived": "도착", "idle": "대기", "failed": "실패"}
DRIVING = ("moving", "returning", "arrived")   # return_home_watcher 가 kiosk_status.json 에 쓰는 상태 중 '주행 관련'
WINDOW_KEY = {"kiosk": "병원 안내 로봇", "rviz": "RViz"}


def x_env():
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":1")
    if "XAUTHORITY" not in env:
        for p in (f"/run/user/{os.getuid()}/gdm/Xauthority", os.path.expanduser("~/.Xauthority")):
            if os.path.exists(p):
                env["XAUTHORITY"] = p
                break
    return env


def screen_size(env):
    out = subprocess.run(["xdpyinfo"], capture_output=True, text=True, env=env).stdout
    m = re.search(r"dimensions:\s+(\d+)x(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (1920, 1080)


def window_geometry(title_part, env):
    """창 제목 일부로 (창 id, x, y, w, h). 여러 개면 가장 큰 창. 못 찾으면 None."""
    tree = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True, text=True, env=env).stdout
    best = None
    for line in tree.splitlines():
        m = re.match(r'\s+(0x[0-9a-f]+) "([^"]*)"', line)
        if m and title_part.lower() in m.group(2).lower():
            info = subprocess.run(["xwininfo", "-id", m.group(1)], capture_output=True, text=True, env=env).stdout
            g = {k: int(v) for k, v in re.findall(r"(Absolute upper-left [XY]|Width|Height):\s+(-?\d+)", info)}
            if g.get("Width", 0) > 200 and g.get("Height", 0) > 200:
                cand = (m.group(1), g["Absolute upper-left X"], g["Absolute upper-left Y"], g["Width"], g["Height"])
                if best is None or cand[3] * cand[4] > best[3] * best[4]:
                    best = cand
    return best


def read_status():
    try:
        with open(STATUS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def grab(path, env, geom, win_id=None, crop_top=0):
    """화면 영역(x11grab) 또는 창 자체 내용(xwd, 가려져도 됨)을 PNG로. crop_top 픽셀만큼 위를 잘라냄."""
    vf = ["-vf", f"crop=iw:ih-{crop_top}:0:{crop_top}"] if crop_top > 0 else []
    if win_id:
        tmp = path + ".xwd"       # ffmpeg 가 표준입력의 xwd 는 형식을 못 알아봐서 임시 파일 경유
        with open(tmp, "wb") as f:
            xw = subprocess.run(["xwd", "-silent", "-id", win_id], stdout=f, stderr=subprocess.PIPE, env=env, timeout=20)
        try:
            if xw.returncode != 0 or os.path.getsize(tmp) == 0:
                return False, "xwd 실패(창이 최소화됐거나 닫힘)"
            r = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "image2pipe", "-vcodec", "xwd", "-i", tmp, *vf,
                                "-frames:v", "1", "-y", path], capture_output=True, text=True, env=env, timeout=20)
            return r.returncode == 0, r.stderr.strip()[:200]
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    x, y, w, h = geom
    w, h = w - w % 2, h - h % 2
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "x11grab", "-video_size", f"{w}x{h}",
                        "-i", f"{env['DISPLAY']}+{x},{y}", *vf, "-frames:v", "1", "-y", path],
                       capture_output=True, text=True, env=env, timeout=20)
    return r.returncode == 0, r.stderr.strip()[:200]


def main():
    ap = argparse.ArgumentParser(description="주행 중 보드 화면 주기 캡처")
    ap.add_argument("-i", "--interval", type=float, default=3.0, help="캡처 간격(초), 기본 3")
    ap.add_argument("-t", "--target", default="full", help="full(모니터 전체) / kiosk / rviz / 창 제목 일부")
    ap.add_argument("-w", "--when", choices=["moving", "always"], default="moving", help="moving=주행 중일 때만(기본)")
    ap.add_argument("-d", "--duration", type=float, default=0, help="이 시간(초) 뒤 종료, 0=Ctrl+C 까지")
    ap.add_argument("-o", "--out", default=OUT_ROOT, help="저장 위치(SSD)")
    ap.add_argument("--crop-top", type=int, default=0, help="위쪽 잘라낼 픽셀(브라우저 탭·주소창 빼기, 예: 87)")
    a = ap.parse_args()

    env = x_env()
    sw, sh = screen_size(env)
    title = WINDOW_KEY.get(a.target, a.target)
    sess = os.path.join(a.out, "screens_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(sess, exist_ok=True)
    idx = open(os.path.join(sess, "index.csv"), "w", newline="", encoding="utf-8-sig")   # 엑셀에서 한글 안 깨지게
    wr = csv.writer(idx)
    wr.writerow(["번호", "시각", "파일", "상태", "목적지", "남은거리_m", "진행률"])
    print(f"[캡처] {sess}\n  대상={a.target} · 간격 {a.interval}초 · {'주행 중일 때만' if a.when == 'moving' else '계속'} · 종료 Ctrl+C",
          flush=True)

    n, t_end, waiting_msg = 0, (time.time() + a.duration) if a.duration > 0 else None, False
    try:
        while t_end is None or time.time() < t_end:
            t0 = time.time()
            st = read_status()
            state = st.get("state", "")
            if a.when == "moving" and state not in DRIVING:
                if not waiting_msg:
                    print("  · 주행 대기 중(이동이 시작되면 찍기 시작)", flush=True)
                    waiting_msg = True
                time.sleep(0.5)
                continue
            waiting_msg = False
            geom, win_id = (0, 0, sw, sh), None
            if a.target != "full":
                g = window_geometry(title, env)
                if g is None:
                    print(f"  ⚠ '{title}' 창을 찾지 못함 → 이번엔 모니터 전체", flush=True)
                else:
                    win_id = g[0]
            n += 1
            now = datetime.datetime.now()
            place = re.sub(r"[^\w가-힣]+", "", str(st.get("place", "")))[:20] or "-"
            fn = f"{n:04d}_{STATE_KO.get(state, state or '상태없음')}_{place}_{now.strftime('%Y%m%d_%H%M%S')}.png"
            ok, err = grab(os.path.join(sess, fn), env, geom, win_id, a.crop_top)
            if ok:
                wr.writerow([n, now.strftime("%Y-%m-%d %H:%M:%S"), fn, STATE_KO.get(state, state), st.get("place", ""),
                             st.get("remaining_m", ""), st.get("progress", "")])
                idx.flush()
                print(f"  {fn}", flush=True)
            else:
                n -= 1
                print(f"  ⚠ 캡처 실패: {err}", flush=True)
            time.sleep(max(0.0, a.interval - (time.time() - t0)))
    except KeyboardInterrupt:
        pass
    idx.close()
    print(f"\n[캡처] 끝 — {n}장 · {sess}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
