#!/usr/bin/env python3
# =========================================================================
# jetson_monitor.py — 젯슨 보드 실시간 상태 기록 (브라운아웃/전원 진단용)
#
#   목적: start_all.sh 로 주행 시 "젯슨만 전원이 꺼지는" 원인을 잡기 위해,
#         입력 전압·전류·전력(INA3221) + 온도 + 부하를 고빈도로 기록한다.
#         ★ 매 샘플을 flush+fsync 해서, 전원이 갑자기 끊겨도 '마지막 값'이 디스크에 남는다.
#         ★ 로그는 SSD(NVMe)에 저장 — eMMC(루트, 92% 참)와 분리되어 전원 차단에도 안전.
#
#   ★ 전압/전류(INA3221) 파일은 root 전용이라 반드시 sudo 로 실행해야 값이 찍힘.
#
#   사용법:
#     1) 터미널 A:  sudo python3 scripts/jetson_monitor.py   (기록 시작, Ctrl+C 로 정지)
#     2) 터미널 B:  ./scripts/start_all.sh                    (그리고 이동 시도)
#     3) 보드가 꺼지면 → 다시 켠 뒤, 화면에 찍힌 로그 파일 경로를 열어 마지막 줄들을 확인/공유.
#
#   샘플 간격 기본 0.2초. 인자로 바꿀 수 있음:  sudo python3 jetson_monitor.py 0.1
# =========================================================================
import os, sys, time, glob, subprocess, datetime, signal

INTERVAL = float(sys.argv[1]) if len(sys.argv) > 1 else 0.2   # 초
LOG_DIR = "/mnt/ssd/projects/myproject/logs"
os.makedirs(LOG_DIR, exist_ok=True)
STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
CSV_PATH = os.path.join(LOG_DIR, f"jetson_monitor_{STAMP}.csv")
INFO_PATH = os.path.join(LOG_DIR, f"jetson_monitor_{STAMP}.info.txt")
TEGRA_PATH = os.path.join(LOG_DIR, f"jetson_monitor_{STAMP}.tegrastats.txt")


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return ""


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception as e:
        return f"(실패: {e})"


# ── INA3221 전력센서 채널 자동 탐색 (hwmon) ──────────────────────────────
# inN_input=버스전압(mV), currN_input=전류(mA). 라벨 있으면 사용.
channels = []   # (tag, vfile, cfile, crit_alarm, max_alarm)
for hw in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
    if _read(os.path.join(hw, "name")) != "ina3221":
        continue
    hwn = os.path.basename(hw)
    for ch in range(0, 8):
        vf = f"{hw}/in{ch}_input"
        cf = f"{hw}/curr{ch}_input"
        if os.path.exists(vf) and os.path.exists(cf):
            lab = _read(f"{hw}/in{ch}_label") or f"{hwn}_ch{ch}"
            lab = lab.replace(" ", "_").replace(",", "")
            channels.append((lab, vf, cf,
                             f"{hw}/curr{ch}_crit_alarm", f"{hw}/curr{ch}_max_alarm"))

# ── 온도(주요 존) ────────────────────────────────────────────────────────
temps = []   # (name, path)
for tz in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
    nm = _read(os.path.join(tz, "type"))
    if nm:
        temps.append((nm, os.path.join(tz, "temp")))

# ── 정적 정보 기록(.info) ────────────────────────────────────────────────
with open(INFO_PATH, "w") as f:
    f.write(f"# jetson_monitor 시작: {datetime.datetime.now()}\n")
    f.write(f"model: {_read('/proc/device-tree/model')}\n")
    f.write(f"nvpmodel: {_run(['nvpmodel','-q']).splitlines()[:2]}\n")
    f.write(f"uname: {_run(['uname','-a'])}\n")
    f.write(f"interval_s: {INTERVAL}\n")
    f.write(f"INA 채널: {[c[0] for c in channels]}\n")
    f.write("초기 전압/전류 읽기:\n")
    for tag, vf, cf, _, _ in channels:
        f.write(f"  {tag}: {_read(vf)}mV {_read(cf)}mA\n")
    f.flush(); os.fsync(f.fileno())

# ── tegrastats 병행 기록(부가 컨텍스트: CPU/GPU 부하·EMC·온도). line-buffered ──
tegra_proc = None
try:
    tf = open(TEGRA_PATH, "w")
    tegra_proc = subprocess.Popen(
        ["stdbuf", "-oL", "tegrastats", "--interval", str(int(INTERVAL * 1000))],
        stdout=tf, stderr=subprocess.DEVNULL)
except Exception:
    tegra_proc = None

# ── CSV 헤더 ─────────────────────────────────────────────────────────────
cols = ["t_iso", "t_epoch", "uptime_s", "load1"]
for tag, *_ in channels:
    cols += [f"{tag}_mV", f"{tag}_mA", f"{tag}_mW"]
for nm, _ in temps:
    cols += [f"{nm}_C"]
cols += ["alarms"]

csv = open(CSV_PATH, "w")
csv.write(",".join(cols) + "\n")
csv.flush(); os.fsync(csv.fileno())

# 전압/전류 읽기 가능 여부(root 권한) 점검
ina_ok = any(_read(vf) for _, vf, *_ in channels)

print("=" * 60)
if channels and not ina_ok:
    print(" ⚠⚠  전압/전류(INA)가 안 읽힙니다 — root 권한이 없습니다.")
    print("     지금은 온도·부하만 기록됩니다. 전원 진단을 하려면 정지 후 sudo 로 다시 실행:")
    print("         sudo python3 scripts/jetson_monitor.py")
    print("=" * 60)
print(" 젯슨 상태 기록 시작 (Ctrl+C 로 정지)")
print(f"  · CSV     : {CSV_PATH}")
print(f"  · tegrastats: {TEGRA_PATH}")
print(f"  · info    : {INFO_PATH}")
print(f"  · 간격    : {INTERVAL}s   · INA 채널 {len(channels)}개")
print("  이 창은 그대로 두고, 다른 터미널에서 start_all.sh 실행 후 이동해 보세요.")
print("=" * 60)

_run_flag = {"on": True}
def _stop(*_):
    _run_flag["on"] = False
signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)

last_beat = 0.0
try:
    while _run_flag["on"]:
        now = time.time()
        row = [datetime.datetime.now().isoformat(timespec="milliseconds"), f"{now:.3f}",
               _read("/proc/uptime").split(" ")[0] or "",
               (_read("/proc/loadavg").split(" ") or [""])[0]]
        alarms = []
        main_v = 0
        tot_i = 0
        for tag, vf, cf, ca, ma in channels:
            v = _read(vf); c = _read(cf)
            try:
                vi = int(v); ci = int(c); p = vi * ci // 1000   # mV*mA/1000 = mW
            except ValueError:
                vi = ci = ""; p = ""
            row += [v, c, str(p)]
            if isinstance(vi, int):
                main_v = max(main_v, vi)
            if isinstance(ci, int):
                tot_i += ci
            if _read(ca) == "1": alarms.append(f"{tag}:CRIT")
            if _read(ma) == "1": alarms.append(f"{tag}:MAX")
        for nm, tp in temps:
            t = _read(tp)
            row += [f"{int(t)/1000:.1f}" if t.isdigit() else ""]
        row += ["|".join(alarms)]
        csv.write(",".join(row) + "\n")
        csv.flush(); os.fsync(csv.fileno())     # ★ 매 샘플 디스크에 확정 → 전원차단에도 마지막 값 보존

        if now - last_beat >= 2.0:               # 콘솔 하트비트(2초마다)
            beat = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 최고전압 {main_v}mV  총전류 {tot_i}mA"
            if alarms: beat += "  ⚠ " + " ".join(alarms)
            print(beat, flush=True)
            last_beat = now

        # 다음 샘플까지 대기(작업시간 보정)
        dt = time.time() - now
        if dt < INTERVAL:
            time.sleep(INTERVAL - dt)
finally:
    csv.flush(); os.fsync(csv.fileno()); csv.close()
    if tegra_proc:
        tegra_proc.terminate()
    print(f"\n기록 종료. 로그 파일:\n  {CSV_PATH}\n  {TEGRA_PATH}")
