#!/usr/bin/env python3
# =========================================================================
# compare_nav_bags.py — 주행 rosbag 여러 개를 같은 기준으로 재서 비교표(마크다운)로
#
#   사용법:  python3 scripts/compare_nav_bags.py <bag폴더1> <bag폴더2> [...] [--json 결과.json]
#            (ROS 환경 필요: source scripts/ros_env.sh)
#   지표는 analyze_nav_bag.py 와 같은 정의(실제 차체 사각형 0.9×0.7 기준 근접 등). '주행 중' = 목표 진행 구간.
# =========================================================================
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_nav_bag as A  # noqa: E402


def metrics(bag):
    D, counts, _ = A.read_bag(bag, keep=("/lidar_F/scan_filtered", "/lidar_R/scan_filtered"))
    tf = A.Tf2D()
    for t, m in D.get("/tf_static", []):
        tf.add(m, True, t)
    for t, m in D.get("/tf", []):
        tf.add(m, False, t)
    tf.finalize()
    y, _ = A.load_cfg(bag)
    F = A.cfgget(y, "controller_server", "ros__parameters", "FollowPath", default={}) or {}
    out = {"bag": os.path.basename(bag)}

    # 목표 구간
    goals = {}
    for t, m in D.get("/navigate_to_pose/_action/status", []):
        for st in m.status_list:
            g = goals.setdefault(bytes(st.goal_info.goal_id.uuid).hex()[:8], {"s": None, "e": None, "r": None})
            if st.status == 2 and g["s"] is None:
                g["s"] = t
            if st.status in (4, 5, 6) and g["e"] is None:
                g["e"], g["r"] = t, st.status
    segs = [(g["s"], g["e"]) for g in goals.values() if g["s"] and g["e"]]
    rec = {}
    for t, m in D.get("/navigate_to_pose/_action/feedback", []):
        gid = bytes(m.goal_id.uuid).hex()[:8]
        rec[gid] = max(rec.get(gid, 0), m.feedback.number_of_recoveries)
    out["goals"] = len(segs)          # 녹화 중 시작(진행 상태가 보인)해서 끝난 목표만
    out["goals_ok"] = sum(1 for g in goals.values() if g["s"] and g["e"] and g["r"] == 4)
    out["drive_sec"] = sum(e - s for s, e in segs)
    out["recoveries"] = sum(rec.values())
    inside = lambda t: any(s <= t <= e for s, e in segs)  # noqa: E731

    cmd = [(t, m.linear.x, m.angular.z) for t, m in D.get("/cmd_vel", []) if inside(t)]
    odo = [(t, m.twist.twist.linear.x, m.twist.twist.angular.z, m.pose.pose.position.x, m.pose.pose.position.y)
           for t, m in D.get("/odom", [])]
    odo_in = [o for o in odo if inside(o[0])]
    out["distance_m"] = sum(math.hypot(b[3] - a[3], b[4] - a[4]) for a, b in zip(odo_in, odo_in[1:]) if b[0] - a[0] < 1)
    v = np.array([o[1] for o in odo_in]) if odo_in else np.zeros(1)
    w = np.array([o[2] for o in odo_in]) if odo_in else np.zeros(1)
    out["v_p95"] = float(np.percentile(np.abs(v), 95))
    out["v_mean_moving"] = float(np.abs(v)[np.abs(v) > 0.02].mean()) if (np.abs(v) > 0.02).any() else 0.0
    out["w_p95"] = float(np.percentile(np.abs(w), 95))
    out["max_vel_x_cfg"] = F.get("max_vel_x")
    out["acc_lim_x_cfg"] = F.get("acc_lim_x")
    out["avg_speed"] = out["distance_m"] / out["drive_sec"] if out["drive_sec"] else 0.0

    # 명령 대비 실제(안정 구간 회귀) — 1.0이면 명령대로 움직임
    if len(cmd) > 20 and len(odo) > 20:
        ct = np.array([c[0] for c in cmd])
        ts = np.arange(ct[0] + 1, ct[-1], 0.1)
        ot = np.array([o[0] for o in odo])
        cv = np.interp(ts - 0.3, ct, [c[1] for c in cmd])
        cv1 = np.interp(ts - 1.0, ct, [c[1] for c in cmd])
        ov = np.interp(ts, ot, [o[1] for o in odo])
        k = (np.abs(cv - cv1) < 0.03) & (np.abs(cv) > 0.08)
        out["actual_over_cmd"] = float((ov[k] * cv[k]).sum() / (cv[k] ** 2).sum()) if k.sum() > 20 else None
        hz = (len(cmd) - 1) / max(ct[-1] - ct[0], 1e-6)
        out["cmd_hz"] = hz
        out["cmd_gaps_025"] = int(sum(1 for a, b in zip(cmd, cmd[1:]) if b[0] - a[0] > 0.25 and (abs(a[1]) > 0.02 or abs(a[2]) > 0.05)))
        sg = [np.sign(c[2]) for c in cmd if abs(c[2]) > 0.05]
        flips = sum(1 for a, b in zip(sg, sg[1:]) if a != b)
        out["w_flips_per_min"] = flips / max(out["drive_sec"] / 60, 1e-6)
    # 실제 움직임의 좌우 흔들림: 실제 회전 속도 부호가 바뀌는 횟수(이동 중, |ω|>0.03)
    sgw = [np.sign(o[2]) for o in odo_in if abs(o[2]) > 0.03 and abs(o[1]) > 0.02]
    out["odom_w_flips_per_min"] = sum(1 for a, b in zip(sgw, sgw[1:]) if a != b) / max(out["drive_sec"] / 60, 1e-6)
    # 실제 가속도 크기(이동 중, 0.2s 간격 미분) 상위 5%
    if len(odo_in) > 10:
        tt = np.array([o[0] for o in odo_in])
        ts = np.arange(tt[0], tt[-1], 0.2)
        vv = np.interp(ts, tt, [o[1] for o in odo_in])
        out["acc_p95"] = float(np.percentile(np.abs(np.diff(vv)) / 0.2, 95))

    # 좌우 흔들림 크기: 전진 중(>0.05 m/s) 실제 회전 속도에서 2초 이동평균(의도한 회전)을 뺀 빠른 출렁임의 RMS(rad/s)
    if len(odo_in) > 30:
        tt = np.array([o[0] for o in odo_in])
        ts = np.arange(tt[0], tt[-1], 0.1)
        ww = np.interp(ts, tt, [o[2] for o in odo_in])
        vv = np.interp(ts, tt, [o[1] for o in odo_in])
        smooth = np.convolve(ww, np.ones(20) / 20, mode="same")
        k = vv > 0.05
        out["wobble_rms"] = float(np.sqrt(np.mean((ww - smooth)[k] ** 2))) if k.sum() > 20 else None
        out["wobble_rel"] = (out["wobble_rms"] / float(np.mean(vv[k]))) if out.get("wobble_rms") else None

    # 근접(주행 중, 차체 사각형 기준). /scan_multi 가 없으면(녹화 QoS 문제) LiDAR 2대 개별 스캔 사용
    clr = []
    scans = D.get("/scan_multi", []) or sorted(D.get("/lidar_F/scan_filtered", []) + D.get("/lidar_R/scan_filtered", []),
                                               key=lambda x: x[0])
    out["scan_src"] = "scan_multi" if D.get("/scan_multi") else "lidar_F+R"
    for t, m in scans:
        if not inside(t):
            continue
        r = np.asarray(m.ranges, dtype=np.float32)
        a = m.angle_min + np.arange(len(r)) * m.angle_increment
        ok = np.isfinite(r) & (r > 0.05) & (r < 12)
        nb = np.zeros_like(ok)
        with np.errstate(invalid="ignore"):
            close = np.abs(r[1:] - r[:-1]) < 0.05
        nb[1:] |= ok[1:] & ok[:-1] & close
        nb[:-1] |= ok[:-1] & ok[1:] & close
        ok &= nb
        T = tf.lookup("base_footprint", m.header.frame_id, t)
        if not ok.any() or T is None:
            continue
        bx, by = A.apply(T, r[ok] * np.cos(a[ok]), r[ok] * np.sin(a[ok]))
        d = A.rect_clearance(bx, by)
        d = d[d > 0]
        if len(d):
            clr.append((t, float(d.min())))
    ev, cur = 0, False
    for _, c in clr:
        if c < A.NEAR_M and not cur:
            ev, cur = ev + 1, True
        elif c >= A.NEAR_M:
            cur = False
    out["near_events"] = ev
    out["min_clearance"] = min((c for _, c in clr), default=None)
    out["near_per_min"] = ev / max(out["drive_sec"] / 60, 1e-6)

    # 로그 경고
    logs = D.get("/rosout", [])
    out["ctrl_missed"] = sum(1 for t, m in logs if "Control loop missed" in m.msg)
    out["ctrl_missed_per_min"] = out["ctrl_missed"] / max((max(t for t, _ in logs) - min(t for t, _ in logs)) / 60, 1e-6) if logs else 0
    out["merge_drops"] = sum(1 for t, m in logs if "Unsynchronized scans" in m.msg)
    out["failed_progress"] = sum(1 for t, m in logs if "Failed to make progress" in m.msg)
    out["out_of_bounds"] = sum(1 for t, m in logs if "out of map bounds" in m.msg)
    out["imu_hz"] = counts.get("/imu/data", 0) / max((max(t for t, _ in logs) - min(t for t, _ in logs)), 1e-6) if logs and counts.get("/imu/data") else None
    out["recording_sec"] = (max(t for t, _ in logs) - min(t for t, _ in logs)) if logs else 0
    return out


ROWS = [
    ("목표 수(성공/전체)", lambda m: f"{m['goals_ok']}/{m['goals']}"),
    ("주행 시간 합(s)", lambda m: f"{m['drive_sec']:.0f}"),
    ("주행 거리(m, 바퀴)", lambda m: f"{m['distance_m']:.1f}"),
    ("평균 속도(m/s, 거리÷시간)", lambda m: f"{m['avg_speed']:.3f}"),
    ("움직일 때 평균 속도(m/s)", lambda m: f"{m['v_mean_moving']:.3f}"),
    ("실제 속도 상위 5%(m/s)", lambda m: f"{m['v_p95']:.3f}"),
    ("설정 최고 속도 max_vel_x", lambda m: f"{m['max_vel_x_cfg']}"),
    ("실제 / 명령 속도 비율", lambda m: "-" if m.get("actual_over_cmd") is None else f"{m['actual_over_cmd']:.2f}"),
    ("속도 명령 주기(Hz)", lambda m: f"{m.get('cmd_hz', 0):.1f}"),
    ("제어 주기 미달 경고(회/분)", lambda m: f"{m['ctrl_missed_per_min']:.1f} (총 {m['ctrl_missed']})"),
    ("이동 중 명령 끊김 >0.25s", lambda m: f"{m.get('cmd_gaps_025', '-')}"),
    ("명령 회전 방향 뒤집힘(회/분)", lambda m: f"{m.get('w_flips_per_min', 0):.1f}"),
    ("실제 회전 방향 뒤집힘(회/분)", lambda m: f"{m['odom_w_flips_per_min']:.1f}"),
    ("직진 중 좌우 흔들림 크기(rad/s RMS)", lambda m: "-" if m.get("wobble_rms") is None else f"{m['wobble_rms']:.3f}"),
    ("흔들림 ÷ 전진 속도(rad/m)", lambda m: "-" if m.get("wobble_rel") is None else f"{m['wobble_rel']:.2f}"),
    ("실제 가속도 상위 5%(m/s², 바퀴 잡음 포함)", lambda m: f"{m.get('acc_p95', 0):.2f}"),
    ("근접 이벤트(<0.15m, 주행 중)", lambda m: f"{m['near_events']} ({m['near_per_min']:.2f}/분)"),
    ("주행 중 최소 여유 거리(m)", lambda m: "-" if m["min_clearance"] is None else f"{m['min_clearance']:.3f}"),
    ("(근접 계산에 쓴 스캔)", lambda m: m["scan_src"]),
    ("복구 동작 횟수", lambda m: f"{m['recoveries']}"),
    ("'진행 못 함' 실패", lambda m: f"{m['failed_progress']}"),
    ("지역 costmap 센서 원점 밖", lambda m: f"{m['out_of_bounds']}"),
    ("LiDAR 병합 스캔 버림", lambda m: f"{m['merge_drops']}"),
]


def main():
    args = sys.argv[1:]
    jpath = None
    if "--json" in args:
        i = args.index("--json")
        jpath = args[i + 1]
        args = args[:i] + args[i + 2:]
    res = []
    for b in args:
        print(f"[비교] {b} 분석 중…", file=sys.stderr, flush=True)
        res.append(metrics(os.path.abspath(b.rstrip("/"))))
    head = "| 지표 | " + " | ".join(r["bag"] for r in res) + " |"
    print(head)
    print("|---|" + "---|" * len(res))
    for name, fn in ROWS:
        print(f"| {name} | " + " | ".join(fn(r) for r in res) + " |")
    if jpath:
        json.dump(res, open(jpath, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
