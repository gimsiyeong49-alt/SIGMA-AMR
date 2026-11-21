#!/usr/bin/env python3
# =========================================================================
# sim_exp2.py — 실험 2(자율주행 안내 성공률)를 시뮬레이션으로 자동 반복하고 표 2 를 만든다.
#
#   실험 절차는 실제와 같다: 키오스크처럼 주행 요청 파일을 쓰면 → 주행 요청 감시기가 Nav2 목표를 보내고 →
#   복귀 감시기가 도착 판정(도착 안내) → 5초 대기 → 미리 돌기 → 초기 위치 복귀 → 방향 정렬(AMCL + 라이다 벽).
#   1회 = 출발 → 도착 → 복귀·정렬. 도착에 실패하면 로봇을 목적지로 옮겨(teleport) 복귀를 시험한다.
#   판정(실험 2 기록 도우미와 같은 기준, 오차는 시뮬레이터의 '실제 위치'로 잼):
#     도착 성공 = 도착 안내가 나오고, 목적지에서 멈춘 위치가 목표점에서 --arr-cm 이내
#     복귀 성공 = 방향 정렬까지 마치고, 초기 위치에서 --ret-cm·--ret-deg 이내
#     전체 성공 = 둘 다 성공(논문 표 2 의 '수동 개입 없이 전체 과정 완료')
#   결과: <out>/sim_exp2_trials.csv, <out>/sim_exp2_summary.md
# =========================================================================
import argparse
import csv
import datetime
import json
import math
import os
import re
import statistics
import sys
import time
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from rclpy.executors import SingleThreadedExecutor
from tf2_ros import Buffer, TransformListener
import threading

HOME = "초기 위치"
RE_RECOV = re.compile(r"\[recoveries_server\]: Attempting (\w+)")
RE_ALIGN = re.compile(r"^방향 정렬 (완료|미완료) .*?오차 ([+-]?\d+(?:\.\d+)?)°")
RE_WALL = re.compile(r"라이다 벽 정렬 (완료|미완료) · 최종 오차 ([+-]?\d+(?:\.\d+)?|nan)°")
RE_PREROT = re.compile(r"복귀 전 미리 돌기 (완료|미완료) .*?오차 ([+-]?\d+(?:\.\d+)?)°")


def zone(labels, name):
    for z in json.loads(Path(labels).read_text(encoding="utf-8")).get("zones", []):
        if z.get("name") == name or name in (z.get("alias") or []):
            ng = z["nav_goal"]
            yaw = (math.atan2(2 * ng["qw"] * ng["qz"], 1 - 2 * ng["qz"] ** 2) if "qz" in ng
                   else math.radians(ng.get("yaw_deg", 0.0)))
            return float(ng["x"]), float(ng["y"]), yaw
    raise SystemExit(f"지도에 없는 목적지: {name}")


def wrap_deg(a):
    return (a + 180.0) % 360.0 - 180.0


class Tail:
    def __init__(self, path):
        self.path = Path(path)
        self.pos = self.path.stat().st_size if self.path.exists() else 0

    def read(self):
        if not self.path.exists():
            return []
        with open(self.path, "rb") as f:
            f.seek(self.pos)
            d = f.read()
            self.pos = f.tell()
        return d.decode("utf-8", "ignore").splitlines()


class Evaluator:
    def __init__(self, a):
        self.a = a
        rclpy.init()
        self.node = rclpy.create_node("sim_exp2")
        self.gt = None
        self.node.create_subscription(PoseStamped, "/sim/ground_truth", self._gt, 10)
        self.tele = self.node.create_publisher(PoseStamped, "/sim/teleport", 10)
        self.init_pub = self.node.create_publisher(PoseWithCovarianceStamped, "/initialpose", 10)
        self.buf = Buffer()
        self.tl = TransformListener(self.buf, self.node)
        ex = SingleThreadedExecutor()
        ex.add_node(self.node)
        threading.Thread(target=ex.spin, daemon=True).start()
        self.bus = Path(a.bus)
        self.status = self.bus / "kiosk_status.json"

    def _gt(self, m):
        q = m.pose.orientation
        self.gt = (m.pose.position.x, m.pose.position.y,
                   math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z)), time.time())

    def amcl(self):
        try:
            t = self.buf.lookup_transform("map", "base_footprint", rclpy.time.Time())
            q = t.transform.rotation
            return t.transform.translation.x, t.transform.translation.y, math.atan2(2 * q.w * q.z, 1 - 2 * q.z * q.z)
        except Exception:
            return None

    def status_state(self):
        try:
            d = json.loads(self.status.read_text(encoding="utf-8"))
            return d.get("state", ""), d.get("place", "")
        except Exception:
            return "", ""

    def set_pose(self, x, y, yaw, teleport=True):
        if teleport:
            p = PoseStamped()
            p.header.frame_id = "map"
            p.pose.position.x, p.pose.position.y = x, y
            p.pose.orientation.z, p.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
            self.tele.publish(p)
            time.sleep(0.5)
        m = PoseWithCovarianceStamped()
        m.header.frame_id = "map"
        m.header.stamp = self.node.get_clock().now().to_msg()
        m.pose.pose.position.x, m.pose.pose.position.y = x, y
        m.pose.pose.orientation.z, m.pose.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
        m.pose.covariance[0] = m.pose.covariance[7] = 0.02
        m.pose.covariance[35] = 0.01
        for _ in range(3):
            self.init_pub.publish(m)
            time.sleep(0.5)

    def request(self, place, source="kiosk"):
        d = self.bus / "nav_request"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{source}_{datetime.datetime.now():%Y%m%d_%H%M%S_%f}.json"
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"place_name": place, "source": source, "requested_at": time.time()},
                                  ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)

    def wait_ready(self):
        print("준비: Nav2·AMCL 기다리는 중…", flush=True)
        home = zone(self.a.labels, HOME)
        t0 = time.time()
        while self.gt is None and time.time() - t0 < 60:
            time.sleep(0.5)
        if self.gt is None:
            raise SystemExit("가짜 로봇 위치가 안 들어옵니다.")
        while time.time() - t0 < 240:
            self.set_pose(*home, teleport=False)
            time.sleep(2)
            if self.amcl():
                print(f"  준비 완료({time.time() - t0:.0f}초)", flush=True)
                return
        raise SystemExit("AMCL(map→base_footprint)이 4분 안에 안 떴습니다.")

    # ── 1회 ──
    def trial(self, dest):
        a = self.a
        goal, home = zone(a.labels, dest), zone(a.labels, HOME)
        nav, ret = Tail(a.navlog), Tail(a.retlog)
        T, cnt = {}, {ph: {"prog": 0, "recov": [], "fail": 0} for ph in ("도착", "복귀")}
        win, arr_stop, closest, ret_lines = [], None, None, []
        phase, manual_arr, manual_ret = "도착", False, False
        t0 = time.time()
        self.request(dest)
        prev = None
        while True:
            now = time.time()
            s, place = self.status_state()
            if s != prev:
                if s and s != "idle" and s not in T:
                    T[s] = now
                print(f"   {now - t0:6.1f}s 상태 {s} {place}", flush=True)
                if s == "returning" and phase == "도착":
                    phase = "복귀"
                prev = s
            for ln in nav.read():
                c = cnt[phase]
                c["prog"] += "Failed to make progress" in ln
                m = RE_RECOV.search(ln)
                if m:
                    c["recov"].append(m.group(1))
                c["fail"] += "]: Goal failed" in ln
            for ln in ret.read():
                if "[return]" in ln:
                    txt = ln.split("[return]", 1)[1].strip()
                    ret_lines.append(txt)
                    if "초기 위치로 복귀 요청" in txt:
                        T.setdefault("ret_req", now)
            g = self.gt
            if g:
                win.append((now, g))
                win = [w for w in win if now - w[0] <= 1.5]
                dg = math.hypot(g[0] - goal[0], g[1] - goal[1])
                if phase == "도착" and (closest is None or dg < closest[0]):
                    closest = (dg, g, self.amcl())
                if "arrived" in T and "ret_req" not in T and len(win) >= 5 and win[-1][0] - win[0][0] >= 1.0:
                    xs, ys = [w[1][0] for w in win], [w[1][1] for w in win]
                    if max(xs) - min(xs) < 0.02 and max(ys) - min(ys) < 0.02 and dg < 1.5:
                        arr_stop = (dg, g, self.amcl())
            # 도착 실패: 제한 시간 넘음 → 로봇을 목적지로 옮기고 복귀 요청(사람이 옮기는 것 흉내)
            if phase == "도착" and "arrived" not in T and now - t0 > a.phase_timeout:
                print("   ⚠ 도착 제한 시간 초과 → 목적지로 옮기고 복귀 시험", flush=True)
                manual_arr = True
                self.set_pose(*goal)
                time.sleep(6)
                self.request(HOME, source="experiment")
                manual_ret = True
                phase = "복귀"
                T["returning_manual"] = time.time()
            if phase == "복귀" and s == "idle" and ("returning" in T or "aligning" in T) and \
                    (not manual_ret or now - T.get("returning_manual", now) > 3):
                T["idle"] = now
                time.sleep(1.0)
                for ln in ret.read():
                    if "[return]" in ln:
                        ret_lines.append(ln.split("[return]", 1)[1].strip())
                break
            t_ret0 = T.get("returning") or T.get("returning_manual")
            if phase == "복귀" and t_ret0 and now - t_ret0 > a.phase_timeout:
                print("   ⚠ 복귀 제한 시간 초과", flush=True)
                T["ret_timeout"] = now
                break
            time.sleep(0.2)
        end_gt, end_amcl = self.gt, self.amcl()
        # 다음 회차를 위해 복귀 실패면 초기 위치로 옮겨 둠
        if "ret_timeout" in T:
            self.set_pose(*home)
            time.sleep(3)
        # 판정
        st = arr_stop or closest
        arr_cm = st[0] * 100 if st else None
        loc_err_cm = (math.hypot(st[1][0] - st[2][0], st[1][1] - st[2][1]) * 100) if st and st[2] else None
        arrived = "arrived" in T and not manual_arr
        arr_ok = arrived and arr_cm is not None and arr_cm <= a.arr_cm
        al = wl = pr = None
        for ln in ret_lines:
            al = RE_ALIGN.search(ln) or al
            wl = RE_WALL.search(ln) or wl
            pr = RE_PREROT.search(ln) or pr
        ret_cm = math.hypot(end_gt[0] - home[0], end_gt[1] - home[1]) * 100 if end_gt else None
        ret_deg = wrap_deg(math.degrees(end_gt[2] - home[2])) if end_gt else None
        done = "aligning" in T and "idle" in T
        align_ok = bool(al and al.group(1) == "완료")
        ret_ok = done and align_ok and ret_cm is not None and ret_cm <= a.ret_cm and abs(ret_deg) <= a.ret_deg
        why_a = "" if arr_ok else ("도착 제한 시간 초과(옮겨서 복귀 시험)" if manual_arr else
                                  ("목표 지점 오차 초과" if arrived else "도착 안내 안 나옴"))
        why_r = "" if ret_ok else ("복귀 제한 시간 초과" if "ret_timeout" in T else
                                  ("방향 정렬 미완료" if done and not align_ok else
                                   ("초기 위치 오차 초과" if done and ret_cm is not None and ret_cm > a.ret_cm else
                                    ("방향 오차 초과" if done else "정렬까지 못 마침"))))
        f1 = lambda v: "" if v is None else f"{v:.1f}"
        return {
            "목적지": dest, "도착": "O" if arr_ok else "X", "복귀": "O" if ret_ok else "X",
            "전체": "O" if arr_ok and ret_ok else "X", "도착_실패이유": why_a, "복귀_실패이유": why_r,
            "도착안내": "예" if arrived else "아니오", "정렬완료": "예" if done and align_ok else "아니오",
            "도착_소요_초": f1(T["arrived"] - t0 if "arrived" in T else None),
            "복귀_소요_초": f1(T["idle"] - (T.get("returning") or T.get("returning_manual")) if "idle" in T else None),
            "전체_소요_초": f1((T.get("idle") or time.time()) - t0),
            "도착_실제오차_cm": f1(arr_cm), "도착_위치추정오차_cm": f1(loc_err_cm),
            "복귀_실제위치오차_cm": f1(ret_cm), "복귀_실제방향오차_도": f1(ret_deg),
            "복귀_정렬기록": " · ".join(x for x in (
                f"미리 돌기 {pr.group(1)} {pr.group(2)}°" if pr else "", f"방향 정렬 {al.group(1)} {al.group(2)}°" if al else "",
                f"벽 정렬 {wl.group(1)} {wl.group(2)}°" if wl else "") if x),
            "도착_Nav2진행실패": cnt["도착"]["prog"], "도착_Nav2복구": len(cnt["도착"]["recov"]),
            "도착_Nav2목표실패": cnt["도착"]["fail"], "복귀_Nav2진행실패": cnt["복귀"]["prog"],
            "복귀_Nav2복구": len(cnt["복귀"]["recov"]), "복귀_Nav2목표실패": cnt["복귀"]["fail"],
        }

    def run(self):
        a = self.a
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        path = out / "sim_exp2_trials.csv"
        rows = []
        self.wait_ready()
        order = [d for _ in range(a.reps) for d in a.dests]       # 내과→외과→…→마취통증의학과 를 reps 번
        for i, dest in enumerate(order, 1):
            # 직전 회차가 완전히 끝나 멈출 때까지
            t_w = time.time()
            while self.status_state()[0] not in ("idle", "") and time.time() - t_w < 60:
                time.sleep(0.5)
            time.sleep(3)
            print(f"[{datetime.datetime.now():%H:%M:%S}] {i}/{len(order)} {dest}", flush=True)
            r = self.trial(dest)
            r = {"번호": i, "시각": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **r}
            rows.append(r)
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=list(r.keys()))
                w.writeheader()
                w.writerows(rows)
            print(f"   → 도착 {r['도착']}({r['도착_실제오차_cm']}cm, {r['도착_소요_초']}s) · 복귀 {r['복귀']}"
                  f"({r['복귀_실제위치오차_cm']}cm, {r['복귀_실제방향오차_도']}°, {r['복귀_소요_초']}s) · 전체 {r['전체']}"
                  + (f" · {r['도착_실패이유']}" if r['도착_실패이유'] else "") + (f" · {r['복귀_실패이유']}" if r['복귀_실패이유'] else ""),
                  flush=True)
            summary(rows, a, out)
        print("끝.", flush=True)


def stat(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "-"
    return f"{statistics.mean(xs):.1f} ± {statistics.stdev(xs):.1f} ({min(xs):.1f} ~ {max(xs):.1f})" if len(xs) > 1 else f"{xs[0]:.1f}"


def summary(rows, a, out):
    num = lambda v: float(v) if v not in ("", None) else None
    pct = lambda k, n: f"{k / n * 100:.1f}%" if n else "-"
    n = len(rows)
    L = ["## 시뮬레이션 표 2. 목적지별 자율주행 안내 성공률(전체 과정 = 도착 + 복귀·정렬)", "",
         "| 목적지 | 시도 | 성공 | 성공률 | 도착 성공 | 복귀 성공 |", "|---|---|---|---|---|---|"]
    for d in a.dests:
        rr = [r for r in rows if r["목적지"] == d]
        if not rr:
            continue
        k = sum(r["전체"] == "O" for r in rr)
        L.append(f"| {d} | {len(rr)} | {k} | {pct(k, len(rr))} | {sum(r['도착'] == 'O' for r in rr)} | "
                 f"{sum(r['복귀'] == 'O' for r in rr)} |")
    k = sum(r["전체"] == "O" for r in rows)
    L.append(f"| **합계** | {n} | {k} | {pct(k, n)} | {sum(r['도착'] == 'O' for r in rows)} | {sum(r['복귀'] == 'O' for r in rows)} |")
    L += ["", "## 단계별", "", "| 단계 | 시도 | 성공 | 성공률 |", "|---|---|---|---|"]
    for ph, key in (("목적지 도착", "도착"), ("초기 위치 복귀·정렬", "복귀"), ("전체 한 바퀴", "전체")):
        k = sum(r[key] == "O" for r in rows)
        L.append(f"| {ph} | {n} | {k} | {pct(k, n)} |")
    L += ["", "## 시간·오차(평균 ± 표준편차 (최소 ~ 최대))", "", "| 항목 | 값 |", "|---|---|",
          f"| 출발 → 도착 안내(초) | {stat([num(r['도착_소요_초']) for r in rows])} |",
          f"| 복귀 시작 → 정렬 완료(초) | {stat([num(r['복귀_소요_초']) for r in rows])} |",
          f"| 한 바퀴 전체(초) | {stat([num(r['전체_소요_초']) for r in rows])} |",
          f"| 도착 위치 오차(실제, cm) | {stat([num(r['도착_실제오차_cm']) for r in rows])} |",
          f"| 도착 때 위치 추정(AMCL) 오차(cm) | {stat([num(r['도착_위치추정오차_cm']) for r in rows])} |",
          f"| 복귀 위치 오차(실제, cm) | {stat([num(r['복귀_실제위치오차_cm']) for r in rows])} |",
          f"| 복귀 방향 오차(실제, °, 절댓값) | {stat([abs(num(r['복귀_실제방향오차_도'])) if num(r['복귀_실제방향오차_도']) is not None else None for r in rows])} |",
          f"| Nav2 복구 동작(회, 도착/복귀 합) | {sum(int(r['도착_Nav2복구']) for r in rows)} / {sum(int(r['복귀_Nav2복구']) for r in rows)} |"]
    # 같은 주행을 다른 허용 오차로 판정(Nav2 도착 허용 오차 0.45 m 와 맞춘 기준 포함)
    L += ["", "## 허용 위치 오차별 성공률(같은 주행 기록, 방향 기준은 동일)", "",
          "| 허용 위치 오차 | 도착 성공 | 복귀 성공 | 전체 성공 |", "|---|---|---|---|"]
    for cm in sorted({a.arr_cm, *a.alt_cm}):
        ao = [r["도착안내"] == "예" and num(r["도착_실제오차_cm"]) is not None and num(r["도착_실제오차_cm"]) <= cm for r in rows]
        ro = [r["정렬완료"] == "예" and num(r["복귀_실제위치오차_cm"]) is not None and num(r["복귀_실제위치오차_cm"]) <= cm
              and abs(num(r["복귀_실제방향오차_도"])) <= a.ret_deg for r in rows]
        fo = [x and y for x, y in zip(ao, ro)]
        L.append(f"| {cm:g} cm{' (계획 기준)' if cm == a.arr_cm else ''} | {sum(ao)}/{n} ({pct(sum(ao), n)}) | "
                 f"{sum(ro)}/{n} ({pct(sum(ro), n)}) | {sum(fo)}/{n} ({pct(sum(fo), n)}) |")
    fails = [f"{r['번호']}번 {r['목적지']}: " + " / ".join(x for x in (r['도착_실패이유'], r['복귀_실패이유']) if x)
             for r in rows if r["전체"] == "X"]
    L += ["", "## 실패 회차", ""] + ([f"- {x}" for x in fails] or ["- 없음"])
    L += ["", f"- 판정 기준: 도착 {a.arr_cm:g} cm 이내 + 도착 안내 / 복귀 방향 정렬 완료 + {a.ret_cm:g} cm·{a.ret_deg:g}° 이내 / "
              f"단계별 제한 시간 {a.phase_timeout:g}초",
          "- 오차는 시뮬레이터의 실제 위치 기준(실험에서는 테이프 실측에 해당)."]
    (out / "sim_exp2_summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bus", required=True)
    ap.add_argument("--labels", default="/mnt/ssd/cart_ros2/src/hospital_mission/map/map_labels.json")
    ap.add_argument("--navlog", required=True)
    ap.add_argument("--retlog", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dests", default="내과,외과,소아청소년과,산부인과,마취통증의학과")
    ap.add_argument("--reps", type=int, default=4)
    ap.add_argument("--arr-cm", type=float, default=30.0)
    ap.add_argument("--ret-cm", type=float, default=30.0)
    ap.add_argument("--ret-deg", type=float, default=10.0)
    ap.add_argument("--phase-timeout", type=float, default=480.0)
    ap.add_argument("--alt-cm", default="40,50", help="함께 계산할 다른 허용 위치 오차(cm, 쉼표)")
    a = ap.parse_args()
    a.dests = [d.strip() for d in a.dests.split(",") if d.strip()]
    a.alt_cm = [float(x) for x in a.alt_cm.split(",") if x.strip()]
    Evaluator(a).run()


if __name__ == "__main__":
    main()
