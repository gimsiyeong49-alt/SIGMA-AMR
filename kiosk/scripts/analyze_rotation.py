#!/usr/bin/env python3
# =========================================================================
# analyze_rotation.py — 회전 구간의 슬립·걸림·덜컹거림을 녹화(rosbag)에서 찾아 위치와 함께 정리
#
#   사용법:  python3 scripts/analyze_rotation.py /mnt/ssd/bags/<폴더> [<폴더> ...]  [--csv 결과.csv]
#   판별(2026-11-15): EKF(ekf.yaml)는 /odometry/filtered 의 회전을 자이로(IMU)만으로, /odom 회전은 바퀴 엔코더만으로 만든다.
#     · 슬립  : 바퀴 회전(/odom) 이 실제 차체 회전(/odometry/filtered=자이로)보다 크게 많음 → 바퀴가 헛돎
#     · 걸림  : 회전 명령은 있는데 바퀴·차체 모두 거의 안 돎(+ 모터 전류)
#     · 덜컹  : 차체 회전속도(자이로)가 짧은 주기로 출렁임(0.1초 차분의 크기)
#     · 위치  : 그 시각 /amcl_pose(지도 좌표) — 특정 구역에 몰리는지
# =========================================================================
import argparse, bisect, csv, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_nav_bag as A   # read_bag 재사용


def series(D, topic, f):
    return [(t, f(m)) for t, m in D.get(topic, [])]


def at(ts, xs, t):
    i = bisect.bisect_right(ts, t) - 1
    return xs[max(0, min(i, len(xs) - 1))] if xs else None


def analyze(bag):
    D, C, T = A.read_bag(bag, keep=("/odometry/filtered", "/motor_amps", "/hall_speed", "/amcl_pose", "/motor_command"))
    cmd = series(D, "/cmd_vel", lambda m: (m.linear.x, m.angular.z))
    odo = series(D, "/odom", lambda m: (m.twist.twist.linear.x, m.twist.twist.angular.z))
    ekf = series(D, "/odometry/filtered", lambda m: m.twist.twist.angular.z)
    amps = series(D, "/motor_amps", lambda m: list(m.value))
    pose = series(D, "/amcl_pose", lambda m: (m.pose.pose.position.x, m.pose.pose.position.y))
    if not cmd or not odo or not ekf:
        return [], {"bag": os.path.basename(bag.rstrip("/")), "note": "필요한 토픽 없음"}
    ct, cv = [c[0] for c in cmd], [c[1] for c in cmd]
    et, ev = [e[0] for e in ekf], [e[1] for e in ekf]
    at_, av = [a[0] for a in amps], [a[1] for a in amps]
    pt, pv = [p[0] for p in pose], [p[1] for p in pose]
    # 회전 구간: 명령 회전 ≥0.05 rad/s, 직진 < 0.08 m/s 가 0.6초 이상 이어짐(명령 끊김 0.3초까지 허용)
    eps, cur = [], None
    for t, (v, w) in cmd:
        rot = abs(w) >= 0.05 and abs(v) < 0.08
        if rot:
            if cur and t - cur[1] <= 0.3:
                cur[1] = t
            else:
                if cur and cur[1] - cur[0] >= 0.6:
                    eps.append(tuple(cur))
                cur = [t, t]
    if cur and cur[1] - cur[0] >= 0.6:
        eps.append(tuple(cur))
    rows = []
    t0 = cmd[0][0]
    for s, e in eps:
        o = [(t, w) for t, (v, w) in odo if s <= t <= e + 0.3]
        g = [(t, w) for t, w in ekf if s <= t <= e + 0.3]
        if len(o) < 3 or len(g) < 3:
            continue
        cw = sum(abs(at(ct, cv, t)[1]) for t, _ in o) / len(o)
        ow = sum(abs(w) for _, w in o) / len(o)
        gw = sum(abs(w) for _, w in g) / len(g)
        # 덜컹: 자이로 회전속도 0.1초 간격 차분 RMS
        gd = [g[i + 1][1] - g[i][1] for i in range(len(g) - 1) if g[i + 1][0] - g[i][0] < 0.2]
        judder = math.sqrt(sum(d * d for d in gd) / len(gd)) if gd else 0.0
        # 걸린 시간 비율: 명령 있는데 자이로 < 0.02 rad/s
        stuck = sum(1 for t, w in g if abs(at(ct, cv, t)[1]) >= 0.05 and abs(w) < 0.02) / len(g)
        slip = (ow - gw) / ow if ow > 0.02 else 0.0
        am = [a for t, a in zip(at_, av) if s <= t <= e] if amps else []
        amax = max((max(abs(x) for x in a[:2]) for a in am), default=float("nan"))
        p = at(pt, pv, (s + e) / 2) if pose else None
        kind = []
        if slip > 0.3 and ow > 0.05:
            kind.append("슬립")
        if stuck > 0.4:
            kind.append("걸림")
        if judder > 0.06:
            kind.append("덜컹")
        rows.append(dict(bag=os.path.basename(bag.rstrip("/")), t=s - t0, dur=e - s, cmd_w=cw, wheel_w=ow, gyro_w=gw,
                         slip=slip, stuck=stuck, judder=judder, amps_max=amax,
                         x=p[0] if p else float("nan"), y=p[1] if p else float("nan"), kind="·".join(kind) or "정상"))
    return rows, {"bag": os.path.basename(bag.rstrip("/")), "episodes": len(rows)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bags", nargs="+")
    ap.add_argument("--csv")
    a = ap.parse_args()
    allr = []
    for b in a.bags:
        rows, info = analyze(b)
        print(f"== {info['bag']}: 회전 구간 {len(rows)}개" + (f" ({info['note']})" if info.get("note") else ""), flush=True)
        for r in rows:
            print(f"  {r['t']:6.1f}s {r['dur']:4.1f}초 명령 {r['cmd_w']:.2f} · 바퀴 {r['wheel_w']:.2f} · 차체(자이로) {r['gyro_w']:.2f} rad/s"
                  f" · 슬립 {r['slip']*100:4.0f}% · 걸림 {r['stuck']*100:3.0f}% · 덜컹 {r['judder']:.3f} · 전류최대 {r['amps_max']}"
                  f" · 위치({r['x']:.1f},{r['y']:.1f}) → {r['kind']}")
        allr += rows
    if a.csv and allr:
        with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(allr[0].keys()))
            w.writeheader(); w.writerows(allr)
    bad = [r for r in allr if r["kind"] != "정상"]
    print(f"\n합계: 회전 구간 {len(allr)}개 중 문제 {len(bad)}개 (슬립 {sum('슬립' in r['kind'] for r in allr)} · 걸림 {sum('걸림' in r['kind'] for r in allr)} · 덜컹 {sum('덜컹' in r['kind'] for r in allr)})")


if __name__ == "__main__":
    main()
