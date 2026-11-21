#!/usr/bin/env python3
# =========================================================================
# live_drive_monitor.py — 주행 중 회전 걸림·슬립·덜컹·명령 없음을 '실시간'으로 잡아 알리고 앞뒤 데이터를 저장
#
#   사용법:  ./scripts/live_drive_monitor.sh            (ROS 환경을 잡고 이 파일 실행 · 종료 Ctrl+C)
#   저장:    /mnt/ssd/rotation_events/live_YYYYmmdd_HHMMSS/
#              ├─ events.log                  (화면에 나온 사건 줄 그대로)
#              └─ 001_걸림_HHMMSS.csv …       (사건 앞 20초 ~ 뒤 5초, 0.1초 간격: 명령·바퀴·자이로·모터·장애물·Nav2 메시지)
#   판별(2026-11-16):
#     · 걸림      : 제자리 회전 명령(|w|≥0.05, |v|<0.08)이 1초 넘게 있는데 차체(자이로) 회전 < 0.02 rad/s
#     · 명령 없음 : 안내·복귀 중인데 Nav2 명령이 2초 넘게 0(또는 안 옴)이고 로봇이 서 있음 → Nav2 가 갈 길을 못 찾는 쪽
#     · 슬립      : 한 방향으로 꾸준히 돌 때(1.5초) 바퀴 회전(/odom)이 차체(/odometry/filtered = 자이로만)보다 30% 넘게 큼
#     · 미세명령  : 주행 중 로봇은 서 있는데 Nav2 가 ±0.06 rad/s 이하 회전만 3초 넘게 명령(방향 못 정함 → 정지 마찰 못 이김)
#     · 덜컹      : 1초 동안 자이로 회전속도 0.1초 차분 크기(RMS) > 0.08
#     · Nav2      : controller/planner/recoveries/bt_navigator 의 경고·오류·진행 실패·복구 메시지
#   ※ 읽기만 한다(아무 명령도 내지 않음). CPU 를 아끼려고 스캔은 최소 거리만 계산.
# =========================================================================
import collections
import csv
import datetime
import json
import math
import os
import sys
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from geometry_msgs.msg import Twist, PoseWithCovarianceStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from rcl_interfaces.msg import Log
try:
    from roboteq_interfaces.msg import ChannelValues
except Exception:            # cart_ros2 환경을 안 잡았으면 모터 값 없이
    ChannelValues = None

STATUS = "/mnt/ssd/cart_ros2/src/llm_package/bus/kiosk_status.json"
OUT_ROOT = "/mnt/ssd/rotation_events"
KEEP_SEC = 40.0
NAV_NODES = ("controller_server", "planner_server", "recoveries_server", "bt_navigator")
STATE_KO = {"moving": "안내 주행", "returning": "복귀 주행", "arrived": "도착", "idle": "대기"}


class Monitor(Node):
    def __init__(self, out_dir):
        super().__init__("live_drive_monitor")
        self.out = out_dir
        self.lock = threading.Lock()
        self.buf = collections.defaultdict(lambda: collections.deque())
        self.create_subscription(Twist, "/cmd_vel", lambda m: self.put("cmd", (m.linear.x, m.angular.z)), 20)
        self.create_subscription(Odometry, "/odom", lambda m: self.put("wheel", (m.twist.twist.linear.x, m.twist.twist.angular.z)), 20)
        self.create_subscription(Odometry, "/odometry/filtered", lambda m: self.put("gyro", m.twist.twist.angular.z), 20)
        self.create_subscription(PoseWithCovarianceStamped, "/amcl_pose",
                                 lambda m: self.put("pose", (m.pose.pose.position.x, m.pose.pose.position.y)), 5)
        self.create_subscription(LaserScan, "/scan_multi", self.on_scan, qos_profile_sensor_data)
        self.create_subscription(Log, "/rosout", self.on_log, 50)
        if ChannelValues is not None:
            for topic, key in (("/motor_amps", "amps"), ("/motor_command", "mcmd"), ("/hall_speed", "hall")):
                self.create_subscription(ChannelValues, topic, lambda m, k=key: self.put(k, list(m.value)[:2]), 20)
        self.state, self.place = "", ""
        self.active = {}          # 사건 종류 → 시작 시각(진행 중인 것)
        self.pending_dump = []    # (저장 시각, 사건 번호, 종류, 시작 시각)
        self.n_events = 0
        self.log_f = open(os.path.join(out_dir, "events.log"), "a", encoding="utf-8")
        self.create_timer(0.1, self.tick)
        self.create_timer(0.5, self.read_status)
        self.say(f"[감시] 시작 — 저장 위치 {out_dir}" + ("" if ChannelValues else " (모터 값 없음: cart_ros2 환경 필요)"))

    # ── 수신 ──
    def put(self, key, val):
        now = time.time()
        with self.lock:
            d = self.buf[key]
            d.append((now, val))
            while d and now - d[0][0] > KEEP_SEC:
                d.popleft()

    def on_scan(self, m):
        rs = [r for r in m.ranges if m.range_min < r < m.range_max]
        self.put("obst", min(rs) if rs else float("nan"))

    def on_log(self, m):
        if not any(n in m.name for n in NAV_NODES):
            return
        txt = m.msg.strip()
        important = m.level >= 30 or any(k in txt for k in ("Failed to make progress", "Attempting", "Turning", "No valid",
                                                              "Reached the goal", "Begin navigating", "Goal succeeded",
                                                              "Goal failed", "patience", "completed"))
        if important and "missed its desired rate" not in txt:
            self.put("nav", f"{m.name}: {txt[:90]}")
            self.say(f"  · Nav2 {m.name.split('.')[-1]}: {txt[:90]}")

    def read_status(self):
        try:
            with open(STATUS, encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            return
        s, p = st.get("state", ""), st.get("place", "")
        if s != self.state:
            self.say(f"[상태] {STATE_KO.get(self.state, self.state or '-')} → {STATE_KO.get(s, s)}{(' · ' + p) if p else ''}")
        self.state, self.place = s, p

    # ── 도우미 ──
    def say(self, text):
        line = f"{datetime.datetime.now().strftime('%H:%M:%S')} {text}"
        print(line, flush=True)
        self.log_f.write(line + "\n"); self.log_f.flush()

    def window(self, key, sec, now):
        with self.lock:
            return [(t, v) for t, v in self.buf.get(key, ()) if now - t <= sec]

    def last(self, key):
        with self.lock:
            d = self.buf.get(key)
            return d[-1] if d else None

    # ── 판별(0.1초마다) ──
    def tick(self):
        now = time.time()
        cmd1 = self.window("cmd", 1.0, now)
        gyro1 = self.window("gyro", 1.0, now)
        wheel05 = self.window("wheel", 0.5, now)
        gyro05 = self.window("gyro", 0.5, now)
        driving = self.state in ("moving", "returning")
        found = {}
        # 걸림: 1초 내내 제자리 회전 명령, 차체 회전 거의 없음
        if len(cmd1) >= 5 and len(gyro1) >= 5 and now - cmd1[0][0] >= 0.8 and \
                all(abs(w) >= 0.05 and abs(v) < 0.08 for _, (v, w) in cmd1) and \
                max(abs(w) for _, w in gyro1) < 0.02:
            found["걸림"] = f"회전 명령 평균 {sum(abs(w) for _, (v, w) in cmd1)/len(cmd1):.2f} rad/s 인데 차체 회전 {max(abs(w) for _, w in gyro1):.3f}"
        # 명령 없음: 주행 중인데 2초 동안 명령이 0 이거나 안 옴, 로봇 정지
        cmd2 = self.window("cmd", 2.0, now)
        gyro2 = self.window("gyro", 2.0, now)
        wheel2 = self.window("wheel", 2.0, now)
        if driving and all(abs(v) < 0.01 and abs(w) < 0.01 for _, (v, w) in cmd2) and \
                (not gyro2 or max(abs(w) for _, w in gyro2) < 0.02) and \
                (not wheel2 or max(abs(v) for _, (v, w) in wheel2) < 0.01):
            found["명령없음"] = "Nav2 명령이 2초 넘게 0" if cmd2 else "Nav2 명령이 2초 넘게 안 옴"
        # 미세 명령(방향 못 정함): 주행 중 3초 동안 로봇은 서 있고 Nav2 는 직진 0·회전 ±0.06 이하만 명령(부호도 오락가락)
        #  2026-11-16 외과 뒤돌기 실측: ±0.02 rad/s(모터 9rpm)만 반복 → 정지 마찰을 못 이겨 1분 47초 멈춤, 강제 회전 복구 때만 돎
        cmd3 = self.window("cmd", 3.0, now)
        gyro3 = self.window("gyro", 3.0, now)
        wheel3 = self.window("wheel", 3.0, now)
        if driving and len(cmd3) >= 15 and gyro3 and max(abs(w) for _, w in gyro3) < 0.03 and \
                (not wheel3 or max(abs(v) for _, (v, w) in wheel3) < 0.01) and \
                sum(1 for _, (v, w) in cmd3 if abs(v) < 0.01 and 0 < abs(w) <= 0.06) >= 0.8 * len(cmd3):
            flips = sum(1 for a, b in zip(cmd3, cmd3[1:]) if a[1][1] * b[1][1] < 0)
            found["미세명령"] = f"Nav2 가 3초 동안 아주 약한 회전만 명령(±0.06 이하, 방향 바뀜 {flips}회) — 로봇이 못 돎"
        # 슬립(2026-11-16 수정): 0.5초 평균은 와리가리처럼 빠르게 좌우로 오갈 때 자이로(필터로 늦고 작음)와 비교돼 거짓 경보가
        #  45건 났음 → 1.5초 동안 한 방향으로 꾸준히 도는(바퀴 회전 0.1 이상, 부호 일정) 때만 판정
        wheel15 = self.window("wheel", 1.5, now)
        gyro15 = self.window("gyro", 1.5, now)
        if len(wheel15) >= 10 and len(gyro15) >= 20 and \
                (all(w > 0.1 for _, (v, w) in wheel15) or all(w < -0.1 for _, (v, w) in wheel15)):
            ww = sum(abs(w) for _, (v, w) in wheel15) / len(wheel15)
            gw = sum(abs(w) for _, w in gyro15) / len(gyro15)
            if (ww - gw) / ww > 0.3:
                found["슬립"] = f"바퀴 회전 {ww:.2f} · 차체 {gw:.2f} rad/s ({(ww-gw)/ww*100:.0f}% 헛돎, 1.5초 꾸준히)"
        # 덜컹
        if len(gyro1) >= 8:
            d = [gyro1[i + 1][1] - gyro1[i][1] for i in range(len(gyro1) - 1)]
            j = math.sqrt(sum(x * x for x in d) / len(d))
            if j > 0.08:
                found["덜컹"] = f"차체 회전속도 출렁임 {j:.3f} rad/s"
        for kind, why in found.items():
            if kind not in self.active:
                self.active[kind] = now
                self.n_events += 1
                ctx = self.ctx_text(now)
                self.say(f"⚠ [{self.n_events:03d} {kind}] {why} · {ctx}")
                self.pending_dump.append((now + 5.0, self.n_events, kind, now))
        for kind in list(self.active):
            if kind not in found:
                dur = now - self.active.pop(kind)
                self.say(f"  └ {kind} 끝 ({dur:.1f}초 지속)")
        # 사건 5초 뒤 앞뒤 데이터 저장
        for item in list(self.pending_dump):
            if now >= item[0]:
                self.pending_dump.remove(item)
                self.dump(*item[1:])

    def ctx_text(self, now):
        p, o, mc, am = self.last("pose"), self.last("obst"), self.last("mcmd"), self.last("amps")
        cmd = self.window("cmd", 3.0, now)
        cw = [w for _, (v, w) in cmd]
        parts = [STATE_KO.get(self.state, self.state or "-") + (f"({self.place})" if self.place else "")]
        if p:
            parts.append(f"위치({p[1][0]:.1f},{p[1][1]:.1f})")
        if o:
            parts.append(f"가장 가까운 장애물 {o[1]:.2f} m")
        if cw:
            parts.append(f"최근 3초 회전 명령 {min(cw):+.2f}~{max(cw):+.2f}")
        if mc:
            parts.append(f"모터 명령 {mc[1]}")
        if am:
            parts.append(f"전류 {am[1]}")
        return " · ".join(parts)

    def dump(self, n, kind, t_ev):
        t0, t1 = t_ev - 20.0, t_ev + 5.0
        with self.lock:
            snap = {k: [(t, v) for t, v in d if t0 <= t <= t1] for k, d in self.buf.items()}

        def at(key, t):
            xs = snap.get(key, [])
            best = None
            for tt, v in xs:
                if tt <= t:
                    best = v
                else:
                    break
            return best
        path = os.path.join(self.out, f"{n:03d}_{kind}_{datetime.datetime.fromtimestamp(t_ev).strftime('%H%M%S')}.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["사건기준초", "명령_v", "명령_w", "바퀴_v", "바퀴_w", "자이로_w", "모터명령_좌", "모터명령_우",
                        "홀속도_좌", "홀속도_우", "전류_좌", "전류_우", "최소장애물_m", "x", "y", "Nav2메시지"])
            navs = snap.get("nav", [])
            t = t0
            while t <= t1:
                c, wh, g = at("cmd", t), at("wheel", t), at("gyro", t)
                mc, hs, am, ob, p = at("mcmd", t), at("hall", t), at("amps", t), at("obst", t), at("pose", t)
                msg = " | ".join(v for tt, v in navs if t - 0.1 < tt <= t)
                w.writerow([f"{t - t_ev:+.1f}",
                            *(f"{x:.3f}" for x in (c or (float('nan'),) * 2)),
                            *(f"{x:.3f}" for x in (wh or (float('nan'),) * 2)),
                            f"{g:.3f}" if g is not None else "",
                            *((mc or ["", ""])[:2]), *((hs or ["", ""])[:2]), *((am or ["", ""])[:2]),
                            f"{ob:.2f}" if ob is not None else "",
                            *((f"{p[0]:.2f}", f"{p[1]:.2f}") if p else ("", "")), msg])
                t += 0.1
        self.say(f"  └ 저장: {path}")


def main():
    out = os.path.join(OUT_ROOT, "live_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out, exist_ok=True)
    rclpy.init()
    node = Monitor(out)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.say(f"[감시] 끝 — 사건 {node.n_events}개 · {out}")
    node.destroy_node()
    rclpy.try_shutdown()


if __name__ == "__main__":
    sys.exit(main())
