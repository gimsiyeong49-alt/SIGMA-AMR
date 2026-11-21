#!/usr/bin/env python3
# =========================================================================
# analyze_nav_bag.py — 주행 rosbag 정밀 분석 → report.md + 그림(PNG)
#
#   사용법:  python3 scripts/analyze_nav_bag.py /mnt/ssd/bags/nav_YYYYmmdd_HHMMSS[_메모]
#            (ROS 환경 필요: source scripts/ros_env.sh — record_nav_bag.sh 와 같은 터미널이면 이미 됨)
#   결과:    <bag 폴더>/analysis/report.md, timeline.png, trajectory.png, event_XX.png
#
#   무엇을 보나 ("어떻게 박았나"를 시간 순서로 재구성)
#     1) 여유 거리: LiDAR 점과 '실제 차체 사각형(0.9×0.7m)' 사이 최소 거리(매 스캔). 가까워진 구간 = 근접 이벤트
#     2) 걸림(stall): 속도 명령은 앞으로인데 바퀴가 안 움직이고 모터 전류가 튐 → LiDAR에 안 보인 것에 걸렸을 가능성
#     3) 이벤트 순간 costmap: 장애물이 costmap에 있었나 / 실제 차체가 위험 칸에 걸렸는데 원(robot_radius)은 안 걸렸나
#     4) 명령 vs 실제: /cmd_vel 과 바퀴 속도의 지연·급가감속·좌우 흔들림·제어 주기 끊김
#     5) 경로 여유: 전역 경로(/plan)가 지도 벽과 차체 반폭·반대각선보다 가깝게 지나가는 곳
#     6) 위치추정: AMCL·map→odom 이 순간적으로 튀는 곳
#     7) Nav2 경고·복구 동작(/rosout), 목표별 성공/실패, 모터 전류·전압
# =========================================================================
import bisect
import collections
import math
import os
import sys

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# ── 로봇·판정 기준(필요하면 여기만 고친다) ─────────────────────────────
BODY_L, BODY_W = 0.90, 0.70          # 차체 길이(앞뒤)·폭(좌우) [m] — AGV_v6.urdf 충돌 상자, base_footprint 중심
NEAR_M = 0.15                         # 차체~장애물 이 거리 미만 = 근접 이벤트
CONTACT_M = 0.03                      # 이 미만 = 접촉 의심
SELF_M = 0.0                          # 차체 안쪽 점(자기 몸 반사)은 제외
STALL_CMD = 0.08                      # 걸림 판정: 명령 전진 속도 이상인데
STALL_ODOM = 0.02                     #           실제 속도 이하가
STALL_SEC = 0.4                       #           이 시간 넘게 지속
GAP_SEC = 0.25                        # /cmd_vel 이 이 시간 넘게 안 오면(이동 중) = 제어 주기 끊김
AMCL_JUMP_M, AMCL_JUMP_DEG = 0.15, 8.0
MAX_EVENT_FIGS = 10
LETHAL = 99                           # OccupancyGrid(0~100) 기준 치명·내접 칸(원래 비용 253·254)

for f in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"):
    if os.path.exists(f):
        from matplotlib import font_manager
        font_manager.fontManager.addfont(f)
        matplotlib.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
        matplotlib.rcParams["axes.unicode_minus"] = False
        break


def yaw_of(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


def compose(a, b):
    """2D 변환 합성 a∘b (a: parent←mid, b: mid←child) → parent←child. 각 (x, y, yaw)."""
    ax, ay, at = a
    bx, by, bt = b
    c, s = math.cos(at), math.sin(at)
    return (ax + c * bx - s * by, ay + s * bx + c * by, at + bt)


def invert(a):
    x, y, t = a
    c, s = math.cos(t), math.sin(t)
    return (-(c * x + s * y), -(-s * x + c * y), -t)


def apply(tf, xs, ys):
    x, y, t = tf
    c, s = math.cos(t), math.sin(t)
    return x + c * xs - s * ys, y + s * xs + c * ys


class Tf2D:
    """bag의 /tf · /tf_static 으로 만든 2D 변환 조회(가장 가까운 시각). 바닥 평면(x, y, yaw)만."""

    def __init__(self):
        self.static = {}                       # child -> (parent, tf)
        self.dyn = collections.defaultdict(lambda: ([], []))   # child -> ([t], [(parent, tf)])

    def add(self, msg, static, t):
        for tr in msg.transforms:
            v = (tr.transform.translation.x, tr.transform.translation.y, yaw_of(tr.transform.rotation))
            if static:
                self.static[tr.child_frame_id] = (tr.header.frame_id, v)
            else:
                ts, vs = self.dyn[tr.child_frame_id]
                ts.append(t)
                vs.append((tr.header.frame_id, v))

    def finalize(self):
        for k, (ts, vs) in list(self.dyn.items()):
            order = np.argsort(ts)
            self.dyn[k] = ([ts[i] for i in order], [vs[i] for i in order])

    def _parent(self, child, t):
        if child in self.static:
            return self.static[child]
        if child in self.dyn:
            ts, vs = self.dyn[child]
            if not ts:
                return None
            i = bisect.bisect_left(ts, t)
            if i >= len(ts):
                i = len(ts) - 1
            elif i > 0 and t - ts[i - 1] < ts[i] - t:
                i -= 1
            return vs[i]
        return None

    def to_root(self, frame, t):
        tf, f, n = (0.0, 0.0, 0.0), frame, 0
        while n < 20:
            p = self._parent(f, t)
            if p is None:
                return f, tf
            parent, v = p
            tf = compose(v, tf)
            f, n = parent, n + 1
        return f, tf

    def lookup(self, target, source, t):
        """source 좌표 → target 좌표 변환(target←source). 실패 시 None."""
        if target == source:
            return (0.0, 0.0, 0.0)
        r1, a = self.to_root(source, t)
        r2, b = self.to_root(target, t)
        # 공통 조상까지 올려 계산: 둘 다 같은 루트로 올라가면 target←root←source
        if r1 != r2:
            # target 이 source 의 조상인 경우 등은 to_root 경로상에서 해결
            f, tf, n = source, (0.0, 0.0, 0.0), 0
            while n < 20:
                if f == target:
                    return tf
                p = self._parent(f, t)
                if p is None:
                    return None
                f, tf, n = p[0], compose(p[1], tf), n + 1
            return None
        return compose(invert(b), a)


def series(ts, vs, t):
    if not ts:
        return None
    i = bisect.bisect_left(ts, t)
    if i >= len(ts):
        i = len(ts) - 1
    elif i > 0 and t - ts[i - 1] < ts[i] - t:
        i -= 1
    return vs[i]


def rect_clearance(px, py):
    """점들(차체 좌표) → 실제 차체 사각형까지 거리. 사각형 안이면 0."""
    dx = np.maximum(np.abs(px) - BODY_L / 2, 0.0)
    dy = np.maximum(np.abs(py) - BODY_W / 2, 0.0)
    return np.hypot(dx, dy)


def zone_of(x, y):
    fb = "앞" if x > BODY_L / 2 - 0.05 else ("뒤" if x < -BODY_L / 2 + 0.05 else "")
    lr = "왼쪽" if y > BODY_W / 2 - 0.05 else ("오른쪽" if y < -BODY_W / 2 + 0.05 else "")
    if fb and lr:
        return f"{fb}{lr} 모서리"
    return fb + ("면" if fb else "") or (lr + " 옆면" if lr else "차체")


def read_bag(path, keep=()):
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=path, storage_id="sqlite3"),
                rosbag2_py.ConverterOptions(input_serialization_format="cdr", output_serialization_format="cdr"))
    types = {t.name: t.type for t in reader.get_all_topics_and_types()}
    # 분석에 안 쓰는 토픽은 해석(역직렬화)하지 않는다 — 수만 개라 읽기 시간 대부분을 차지(개수는 그대로 셈)
    skip = {"/evaluation", "/marker", "/vision_result/image", "/global_costmap/costmap", "/particle_cloud",
            "/battery_amps", "/feedback", "/hall_speed", "/motor_command", "/local_costmap/published_footprint",
            "/received_global_plan", "/transformed_global_plan", "/diagnostics", "/odometry/filtered",
            "/lidar_F/scan_filtered", "/lidar_R/scan_filtered", "/imu/data", "/people_obstacles"} - set(keep)
    cls = {}
    D = collections.defaultdict(list)       # topic -> [(t, msg)]
    counts = collections.Counter()
    while reader.has_next():
        topic, data, t = reader.read_next()
        counts[topic] += 1
        if topic in skip or topic not in types:
            continue
        if topic not in cls:
            try:
                cls[topic] = get_message(types[topic])
            except Exception:
                cls[topic] = None
        if cls[topic] is None:
            continue
        D[topic].append((t * 1e-9, deserialize_message(data, cls[topic])))
    return D, counts, types


def load_cfg(bagdir):
    import yaml
    for p in (os.path.join(bagdir, "context", "agv.yaml"), "/mnt/ssd/cart_ros2/src/hospital_mission/config/agv.yaml"):
        if os.path.exists(p):
            try:
                y = yaml.safe_load(open(p))
                return y, p
            except Exception:
                pass
    return {}, None


def cfgget(y, *keys, default=None):
    cur = y
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def main():
    if len(sys.argv) < 2:
        print(__doc__ or "사용법: analyze_nav_bag.py <bag 폴더>")
        sys.exit(1)
    bag = os.path.abspath(sys.argv[1].rstrip("/"))
    out = os.path.join(bag, "analysis")
    os.makedirs(out, exist_ok=True)
    print(f"[분석] {bag} 읽는 중…", flush=True)
    D, counts, types = read_bag(bag)
    if not counts:
        print("메시지가 없습니다.")
        return
    tf = Tf2D()
    for t, m in D.get("/tf_static", []):
        tf.add(m, True, t)
    for t, m in D.get("/tf", []):
        tf.add(m, False, t)
    tf.finalize()

    t_all = [t for k in D for t, _ in D[k][:1]] + [t for k in D for t, _ in D[k][-1:]]
    T0, T1 = min(t_all), max(t_all)
    rel = lambda t: t - T0  # noqa: E731
    R = []   # 보고서 줄
    H = []   # 자동 진단 소견
    y, cfgpath = load_cfg(bag)

    # ── 0) 설정 점검: 차체 크기 vs Nav2 가 아는 로봇 크기 ─────────────────
    half_diag = math.hypot(BODY_L / 2, BODY_W / 2)
    lr = cfgget(y, "local_costmap", "local_costmap", "ros__parameters", "robot_radius")
    gr = cfgget(y, "global_costmap", "global_costmap", "ros__parameters", "robot_radius")
    lfp = cfgget(y, "local_costmap", "local_costmap", "ros__parameters", "footprint")
    gfp = cfgget(y, "global_costmap", "global_costmap", "ros__parameters", "footprint")
    linf = cfgget(y, "local_costmap", "local_costmap", "ros__parameters", "inflation_layer", "inflation_radius")
    ginf = cfgget(y, "global_costmap", "global_costmap", "ros__parameters", "inflation_layer", "inflation_radius")
    dwb = cfgget(y, "controller_server", "ros__parameters", "FollowPath", default={}) or {}
    R += ["## 0. 설정 점검 — 실제 차체 vs Nav2가 아는 로봇 크기", "",
          f"- 실제 차체: {BODY_L}×{BODY_W} m → 중심에서 앞뒤 {BODY_L/2:.2f} m · 좌우 {BODY_W/2:.2f} m · **모서리 {half_diag:.2f} m**",
          f"- 설정 파일: `{cfgpath}`",
          f"- 지역 costmap(회피용): footprint={lfp!r} · robot_radius={lr} · inflation_radius={linf}",
          f"- 전역 costmap(경로 생성): footprint={gfp!r} · robot_radius={gr} · inflation_radius={ginf}",
          f"- DWB: max_vel_x={dwb.get('max_vel_x')} · acc_lim_x={dwb.get('acc_lim_x')} · decel_lim_x={dwb.get('decel_lim_x')} · "
          f"BaseObstacle.scale={dwb.get('BaseObstacle.scale')} · PathAlign={dwb.get('PathAlign.scale')} · PathDist={dwb.get('PathDist.scale')}", ""]
    if not lfp and isinstance(lr, (int, float)) and lr < half_diag:
        H.append(f"**[설정] 지역 costmap이 로봇을 반지름 {lr} m 원으로 봄** — 실제 모서리는 {half_diag:.2f} m라 "
                 f"모서리가 원 밖으로 {half_diag - lr:.2f} m 튀어나옴(앞뒤 끝도 {BODY_L/2 - lr:+.2f} m). "
                 f"회전·근접 통과 때 모서리가 부딪혀도 Nav2는 '안 닿는다'고 판단할 수 있음 → 사각형 footprint 지정 권장")
    if not gfp and isinstance(gr, (int, float)) and gr < BODY_W / 2:
        H.append(f"**[설정] 전역 costmap은 로봇을 반지름 {gr} m 원으로 봄** — 실제 반폭 {BODY_W/2:.2f} m보다도 작음 → "
                 f"경로가 실제로는 못 지나갈 만큼 벽·문틀에 붙어서 생성될 수 있음")
    bo = dwb.get("BaseObstacle.scale")
    pa = dwb.get("PathAlign.scale")
    if isinstance(bo, (int, float)) and isinstance(pa, (int, float)) and bo * 20 < pa:
        H.append(f"**[설정] 지역 제어(DWB)가 장애물 근접을 거의 무시**: BaseObstacle.scale={bo} vs 경로 추종 PathAlign/PathDist={pa} "
                 f"(약 {pa/bo:.0f}배) → 충돌만 아니면 장애물 옆에 바짝 붙어서라도 경로를 따라가는 성향")

    # ── 1) 토픽 수신 주기 ─────────────────────────────────────────────
    dur = T1 - T0
    R += ["## 1. 녹화 개요", "", f"- 길이 {dur:.1f}초 ({dur/60:.1f}분)", "", "| 토픽 | 메시지 수 | 평균 Hz |", "|---|---|---|"]
    for k in sorted(counts):
        R.append(f"| `{k}` | {counts[k]} | {counts[k]/max(dur,1e-6):.1f} |")
    R.append("")

    # ── 목표(goal) 구간 ───────────────────────────────────────────────
    goals = collections.OrderedDict()   # id -> dict
    STAT = {1: "수락", 2: "진행", 3: "취소중", 4: "성공", 5: "취소", 6: "실패(abort)"}
    for t, m in D.get("/navigate_to_pose/_action/status", []):
        for st in m.status_list:
            gid = bytes(st.goal_info.goal_id.uuid).hex()[:8]
            g = goals.setdefault(gid, {"start": None, "end": None, "result": None})
            if st.status == 2 and g["start"] is None:
                g["start"] = t
            if st.status in (4, 5, 6) and g["end"] is None:
                g["end"], g["result"] = t, STAT[st.status]
    fb = D.get("/navigate_to_pose/_action/feedback", [])
    rec_by_goal = {}
    for t, m in fb:
        gid = bytes(m.goal_id.uuid).hex()[:8]
        rec_by_goal[gid] = max(rec_by_goal.get(gid, 0), m.feedback.number_of_recoveries)
    active = lambda t: any(g["start"] and g["start"] <= t <= (g["end"] or T1) for g in goals.values())  # noqa: E731

    # ── 2) 속도 명령 vs 실제 ─────────────────────────────────────────
    cmd = [(t, m.linear.x, m.angular.z) for t, m in D.get("/cmd_vel", [])]
    odo = [(t, m.twist.twist.linear.x, m.twist.twist.angular.z) for t, m in D.get("/odom", [])]
    cmd_t = [c[0] for c in cmd]
    odo_t = [o[0] for o in odo]
    R += ["## 3. 속도 명령(/cmd_vel) vs 실제 움직임(/odom)", ""]
    gaps, jerk_x, osc = [], 0, 0
    lag = None
    if len(cmd) > 5 and len(odo) > 5:
        for (ta, va, wa), (tb, vb, wb) in zip(cmd, cmd[1:]):
            if tb - ta > GAP_SEC and (abs(va) > 0.05 or abs(wa) > 0.05):
                gaps.append((ta, tb - ta))
        ax = [(tb, (vb - va) / max(tb - ta, 1e-3)) for (ta, va, _), (tb, vb, _) in zip(cmd, cmd[1:]) if tb - ta > 0.02]
        acc_lim = float(dwb.get("acc_lim_x") or 1.5)
        dec_lim = abs(float(dwb.get("decel_lim_x") or -2.0))
        jerk_x = sum(1 for _, a in ax if a > acc_lim * 1.2 or a < -dec_lim * 1.2)
        sgn = [np.sign(w) for _, _, w in cmd if abs(w) > 0.1]
        osc = sum(1 for a, b in zip(sgn, sgn[1:]) if a != b)
        # 지연: 50Hz로 다시 표본화해 교차상관(최대 1.5초)
        ts = np.arange(max(cmd_t[0], odo_t[0]), min(cmd_t[-1], odo_t[-1]), 0.02)
        if len(ts) > 100:
            cv = np.interp(ts, cmd_t, [c[1] for c in cmd])
            ov = np.interp(ts, odo_t, [o[1] for o in odo])
            if np.std(cv) > 0.01 and np.std(ov) > 0.01:
                best = max(range(0, 76), key=lambda k: np.corrcoef(cv[:len(cv) - k], ov[k:])[0, 1] if len(cv) - k > 50 else -1)
                lag = best * 0.02
        hz = (len(cmd) - 1) / max(cmd_t[-1] - cmd_t[0], 1e-6)
        R += [f"- /cmd_vel 평균 {hz:.1f} Hz (설정 controller_frequency={cfgget(y,'controller_server','ros__parameters','controller_frequency')})",
              f"- 이동 중 명령 끊김(>{GAP_SEC}s): **{len(gaps)}회**" + (f" — 최장 {max(g[1] for g in gaps):.2f}s" if gaps else ""),
              f"- 급가감속 명령(가속 한도 {acc_lim}·감속 한도 {dec_lim} m/s²의 1.2배 초과): **{jerk_x}회**",
              f"- 회전 방향 뒤집힘(|wz|>0.1에서 좌↔우): **{osc}회** ({osc / max(dur / 60, 1e-6):.1f}회/분)",
              f"- 명령→실제 속도 지연(교차상관): **{lag:.2f}s**" if lag is not None else "- 명령→실제 지연: 계산 불가(움직임 부족)", ""]
        if len(gaps) >= 3:
            H.append(f"**[제어] 이동 중 속도 명령이 {GAP_SEC}초 넘게 끊긴 적 {len(gaps)}회** — 컨트롤러가 제 주기(20Hz)를 못 지킴(CPU 포화 의심). "
                     f"끊긴 동안 로봇은 마지막 명령으로 계속 움직임")
        if lag is not None and lag >= 0.3:
            H.append(f"**[구동] 명령→실제 속도 지연 {lag:.2f}초** — DWB가 예측한 궤적과 실제 움직임이 어긋남(모터 드라이버 가감속 램프·폐루프 응답). "
                     f"멈추라 해도 늦게 멈추고, 늦게 출발")
        if osc / max(dur / 60, 1e-6) > 20:
            H.append(f"**[제어] 좌우 회전 명령이 분당 {osc / max(dur / 60, 1e-6):.0f}번 뒤집힘** — 경로 추종 비평가끼리 다투며 흔들리는 '꿀렁임'")
        if jerk_x > 10:
            H.append(f"**[제어] 한도를 넘는 급가감속 명령 {jerk_x}회** — 주행이 부드럽지 않은 직접 원인 후보")
    else:
        R += ["- /cmd_vel 또는 /odom 데이터 부족", ""]

    # 걸림(stall): 명령은 전진, 바퀴는 정지, 지속
    stalls = []
    if cmd and odo:
        run_s = None
        for t, v, _ in cmd:
            ov = series(odo_t, odo, t)
            if ov is None:
                continue
            stuck = v > STALL_CMD and abs(ov[1]) < STALL_ODOM
            if stuck and run_s is None:
                run_s = t
            elif not stuck and run_s is not None:
                if t - run_s >= STALL_SEC:
                    stalls.append((run_s, t))
                run_s = None
    amps = [(t, max(abs(v) for v in m.value) if len(m.value) else 0) for t, m in D.get("/motor_amps", [])]
    amps_t = [a[0] for a in amps]
    volts = [(t, (m.value[0] if len(m.value) else 0)) for t, m in D.get("/volts", [])]

    # ── 3) 여유 거리(LiDAR ↔ 실제 차체) ──────────────────────────────
    scans = D.get("/scan_multi", [])
    clr_t, clr_v, clr_pt = [], [], []
    self_hits = 0
    base = "base_footprint"
    for t, m in scans:
        n = len(m.ranges)
        r = np.asarray(m.ranges, dtype=np.float32)
        a = m.angle_min + np.arange(n) * m.angle_increment
        ok = np.isfinite(r) & (r > max(m.range_min, 0.05)) & (r < min(m.range_max if m.range_max > 0 else 30, 12.0))
        # 외톨이 점(잡음) 제외: 바로 옆 각도 점과 5 cm 안에서 이어지는 점만 장애물로 본다
        nb = np.zeros_like(ok)
        with np.errstate(invalid="ignore"):
            close = np.abs(r[1:] - r[:-1]) < 0.05
        nb[1:] |= ok[1:] & ok[:-1] & close
        nb[:-1] |= ok[:-1] & ok[1:] & close
        ok = ok & nb
        if not ok.any():
            continue
        xs, ys = r[ok] * np.cos(a[ok]), r[ok] * np.sin(a[ok])
        T = tf.lookup(base, m.header.frame_id, t)
        if T is None:
            continue
        bx, by = apply(T, xs, ys)
        d = rect_clearance(bx, by)
        inside = d <= SELF_M
        self_hits += int(inside.sum())
        d = np.where(inside, np.inf, d)
        i = int(np.argmin(d))
        clr_t.append(t)
        clr_v.append(float(d[i]))
        clr_pt.append((float(bx[i]), float(by[i])))
    # 근접 이벤트 = NEAR_M 미만 연속 구간
    events = []
    cur = None
    for k, (t, v) in enumerate(zip(clr_t, clr_v)):
        if v < NEAR_M:
            if cur is None:
                cur = {"t0": t, "t1": t, "min": v, "k": k}
            cur["t1"] = t
            if v < cur["min"]:
                cur["min"], cur["k"] = v, k
        elif cur is not None:
            events.append(cur)
            cur = None
    if cur:
        events.append(cur)

    # 이벤트 순간 costmap 확인
    cms = D.get("/local_costmap/costmap", [])
    cm_t = [c[0] for c in cms]

    def costmap_check(t, ob_xy):
        c = series(cm_t, cms, t)
        if c is None:
            return None
        c = c[1]
        info = c.info
        w, h, res = info.width, info.height, info.resolution
        ox, oy = info.origin.position.x, info.origin.position.y
        grid = np.asarray(c.data, dtype=np.int16).reshape(h, w)
        Tcb = tf.lookup(c.header.frame_id, base, t)
        if Tcb is None:
            return None

        def cost_at(px, py):
            gx, gy = apply(Tcb, np.asarray(px), np.asarray(py))
            ix = ((gx - ox) / res).astype(int)
            iy = ((gy - oy) / res).astype(int)
            okm = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
            vals = np.full(ix.shape, -1)
            vals[okm] = grid[iy[okm], ix[okm]]
            return vals
        ob = int(cost_at([ob_xy[0]], [ob_xy[1]])[0])
        g = np.arange(-BODY_L / 2, BODY_L / 2 + 1e-6, res / 2)
        hh = np.arange(-BODY_W / 2, BODY_W / 2 + 1e-6, res / 2)
        RX, RY = np.meshgrid(g, hh)
        rect = cost_at(RX.ravel(), RY.ravel())
        rad = lr if isinstance(lr, (int, float)) else 0.4
        circ_mask = np.hypot(RX.ravel(), RY.ravel()) <= rad
        # /local_costmap/costmap 은 OccupancyGrid 라 비용이 0~100 으로 바뀌어 옴(254 치명→100, 253 내접→99)
        lethal_rect = int((rect >= LETHAL).sum())
        lethal_out = int(((rect >= LETHAL) & ~circ_mask).sum())
        return {"ob": ob, "rect_max": int(rect.max()), "lethal_rect": lethal_rect, "lethal_outside_circle": lethal_out, "msg": c, "Tcb": Tcb}

    R += ["## 4. 근접 이벤트 — LiDAR가 본 장애물과 '실제 차체 사각형' 사이 거리", "",
          f"- 스캔 {len(clr_v)}개 분석, 차체 안쪽으로 찍힌 점(자기 몸 반사) {self_hits}개 제외",
          f"- 최소 여유 거리: **{min(clr_v):.3f} m**" if clr_v else "- /scan_multi 없음",
          f"- {NEAR_M} m 미만 근접 구간 **{len(events)}개**, 그중 {CONTACT_M} m 미만(접촉 의심) "
          f"**{sum(1 for e in events if e['min'] < CONTACT_M)}개**", ""]
    ev_rows = []
    not_in_costmap = 0
    corner_only = 0
    for e in events:
        k = e["k"]
        t = clr_t[k]
        px, py = clr_pt[k]
        ov = series(odo_t, odo, t)
        cv = series(cmd_t, cmd, t)
        cc = costmap_check(t, (px, py))
        # 구간 전체에서 실제로 움직였나(정지 중 근접 = 대기·복귀 자리 주변 물체 / 주행 중 근접 = 진짜 위험)
        mv = [abs(o[1]) + abs(o[2]) for o in odo if e["t0"] - 0.2 <= o[0] <= e["t1"] + 0.2]
        e["moving"] = bool(mv) and max(mv) > 0.05
        e.update({"t": t, "pt": (px, py), "zone": zone_of(px, py), "v": ov[1] if ov else None, "w": ov[2] if ov else None,
                  "cmd": (cv[1], cv[2]) if cv else None, "cc": cc, "goal": active(t)})
        if cc:
            if cc["ob"] < LETHAL and e["moving"]:
                not_in_costmap += 1
            if cc["lethal_outside_circle"] > 0 and e["moving"]:
                corner_only += 1
        ev_rows.append(e)
    if ev_rows:
        R += ["| # | 시각(s) | 길이(s) | 최소 거리(m) | 부위 | 실제 속도 v/ω | 명령 v/ω | 장애물 칸 비용 | 차체에 걸린 위험칸(원 밖) | 주행 중 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for i, e in enumerate(sorted(ev_rows, key=lambda e: e["min"])[:40]):
            cc = e["cc"] or {}
            R.append(f"| {i+1} | {rel(e['t']):.1f} | {e['t1']-e['t0']:.1f} | {e['min']:.3f} | {e['zone']} | "
                     f"{e['v']:.2f}/{e['w']:.2f} | " if e["v"] is not None else f"| {i+1} | {rel(e['t']):.1f} | {e['t1']-e['t0']:.1f} | {e['min']:.3f} | {e['zone']} | - | ")
            R[-1] += (f"{e['cmd'][0]:.2f}/{e['cmd'][1]:.2f} | " if e["cmd"] else "- | ")
            R[-1] += (f"{cc.get('ob','-')} | {cc.get('lethal_rect','-')}({cc.get('lethal_outside_circle','-')}) | "
                      f"{'예' if e['goal'] else '아니오'}{'' if e['moving'] else ' (정지)'} |")
        R += ["", f"- 장애물 칸 비용(0~100으로 변환된 값): 0=빈칸 … {LETHAL} 이상=치명. **주행 중인데 {LETHAL} 미만 = costmap에 장애물이 반영 안 됨**",
              "- 차체에 걸린 위험칸: 실제 사각형 안의 치명 칸 수(괄호=그중 robot_radius 원 **밖** = Nav2가 모르는 모서리 접촉)", ""]
        zc = collections.Counter(e["zone"] for e in ev_rows if e["moving"])
        n_still = sum(1 for e in ev_rows if not e["moving"])
        R.append(f"- 정지 중 근접 {n_still}건(로봇이 서 있는 자리 옆 물체) · 주행 중 근접 {len(ev_rows) - n_still}건(아래 부위 집계는 주행 중만)")
        R.append("- 부위별 근접 횟수: " + ", ".join(f"{k} {v}회" for k, v in zc.most_common()))
        R.append("")
        if not_in_costmap:
            H.append(f"**[인식] 근접 {not_in_costmap}건에서 LiDAR는 장애물을 봤는데 그 칸이 지역 costmap에 치명으로 없음** — "
                     f"costmap 갱신 지연·레이트레이싱으로 지워짐·obstacle_min/max_range 범위 밖 등으로 회피 대상에서 빠짐")
        if corner_only:
            H.append(f"**[형상] 근접 {corner_only}건에서 실제 차체 모서리가 치명 칸에 걸렸지만 robot_radius 원은 안 걸림** — "
                     f"Nav2 기준으로는 '충돌 아님'이라 회피·감속을 안 함 → 원 대신 사각형 footprint 필요")
        if zc:
            top, n = zc.most_common(1)[0]
            if "모서리" in top and n >= max(2, len(ev_rows) // 3):
                H.append(f"**[형상] 근접이 '{top}'에 몰림({n}/{len(ev_rows)})** — 회전하며 모서리가 쓸고 지나가는 패턴")

    R += ["## 5. 걸림(stall) — 명령은 전진인데 바퀴가 멈춘 구간", ""]
    if stalls:
        R += ["| 시각(s) | 지속(s) | 최대 모터 전류 | 그 순간 LiDAR 최소 거리(m) |", "|---|---|---|---|"]
        blind = 0
        for s0, s1 in stalls:
            am = max([a for t, a in amps if s0 <= t <= s1] or [0])
            cl = min([v for t, v in zip(clr_t, clr_v) if s0 - 0.5 <= t <= s1] or [float("nan")])
            R.append(f"| {rel(s0):.1f} | {s1-s0:.1f} | {am} | {cl:.3f} |")
            if not (cl < 0.2):
                blind += 1
        R.append("")
        if blind:
            H.append(f"**[사각지대] 바퀴가 막힌 {blind}건은 그 순간 LiDAR에 가까운 장애물이 없음** — LiDAR 높이(지면 0.14 m)보다 낮거나 높은 것"
                     f"(문턱·침대 다리·테이블 상판·유리)에 걸렸을 가능성")
    else:
        R += ["- 없음", ""]

    # ── 6) 경로 여유(전역 경로 ↔ 지도 벽) ────────────────────────────
    R += ["## 6. 전역 경로 여유 — /plan 이 지도 벽에 얼마나 붙어서 생성됐나", ""]
    maps = D.get("/map", [])
    plans = D.get("/plan", [])
    if maps and plans:
        from scipy import ndimage
        mp = maps[-1][1]
        mi = mp.info
        grid = np.asarray(mp.data, dtype=np.int16).reshape(mi.height, mi.width)
        occ = grid >= 65
        dist = ndimage.distance_transform_edt(~occ) * mi.resolution
        tight_w, tight_d, worst = 0, 0, (9.9, None)
        all_d = []
        for t, p in plans:
            for ps in p.poses[::2]:
                ix = int((ps.pose.position.x - mi.origin.position.x) / mi.resolution)
                iy = int((ps.pose.position.y - mi.origin.position.y) / mi.resolution)
                if 0 <= ix < mi.width and 0 <= iy < mi.height:
                    dd = float(dist[iy, ix])
                    all_d.append(dd)
                    if dd < worst[0]:
                        worst = (dd, (ps.pose.position.x, ps.pose.position.y), t)
        if all_d:
            ad = np.array(all_d)
            tight_w = float((ad < BODY_W / 2).mean() * 100)
            tight_d = float((ad < half_diag).mean() * 100)
            R += [f"- 경로 {len(plans)}개 · 점 {len(ad)}개 · 경로~벽 최소 {ad.min():.2f} m (지도 좌표 {worst[1][0]:.2f}, {worst[1][1]:.2f})",
                  f"- 벽까지 **반폭 {BODY_W/2:.2f} m 미만**(차체 옆면이 닿는 거리)인 경로 점: **{tight_w:.1f}%**",
                  f"- 벽까지 **반대각선 {half_diag:.2f} m 미만**(회전하면 모서리가 닿는 거리)인 경로 점: **{tight_d:.1f}%**", ""]
            if tight_w > 0.5:
                H.append(f"**[경로] 전역 경로 점의 {tight_w:.1f}%가 벽에서 차체 반폭({BODY_W/2:.2f} m)보다 가까움** — 경로부터 벽에 붙어서 생성됨"
                         f"(전역 robot_radius·inflation이 작음)")
            elif tight_d > 5:
                H.append(f"**[경로] 전역 경로 점의 {tight_d:.1f}%가 벽에서 반대각선({half_diag:.2f} m) 안쪽** — 그 구간에서 제자리 회전하면 모서리 접촉 위험")
    else:
        R += ["- /map 또는 /plan 없음(주행 목표가 없었거나 녹화 시작 전에 지도가 이미 발행됨)", ""]

    # ── 7) 위치추정 튐 ───────────────────────────────────────────────
    R += ["## 7. 위치추정(AMCL) 튐", ""]
    # AMCL 은 일정 거리 움직일 때마다 갱신 → 연속 위치 차이는 '이동'이 섞임. 대신 map→odom 보정값의 변화(= AMCL이 위치를 고쳐 잡은 크기)를 본다
    am = D.get("/amcl_pose", [])
    corr = []
    for t, m in am:
        T_mb = (m.pose.pose.position.x, m.pose.pose.position.y, yaw_of(m.pose.pose.orientation))
        T_ob = tf.lookup("odom", base, t)
        if T_ob is not None:
            corr.append((t, compose(T_mb, invert(T_ob))))      # map←odom 보정
    jumps = []
    for (ta, a), (tb, b) in zip(corr, corr[1:]):
        # 보정 변화를 로봇 위치에서 본 이동량으로: map←odom 이 바뀌면 로봇의 지도 위치가 그만큼 순간 이동
        T_ob = tf.lookup("odom", base, tb)
        pa, pb = compose(a, T_ob), compose(b, T_ob)
        jumps.append((tb, math.hypot(pb[0] - pa[0], pb[1] - pa[1]),
                      abs(math.degrees(math.atan2(math.sin(pb[2] - pa[2]), math.cos(pb[2] - pa[2]))))))
    big = [j for j in jumps if j[1] > AMCL_JUMP_M or j[2] > AMCL_JUMP_DEG]
    if jumps:
        R += [f"- AMCL 보정 {len(jumps)}회 · 한 번 보정 크기 중앙값 {np.median([j[1] for j in jumps]):.3f} m / {np.median([j[2] for j in jumps]):.1f}° · "
              f"최대 {max(j[1] for j in jumps):.2f} m / {max(j[2] for j in jumps):.1f}°"]
    R += [f"- {AMCL_JUMP_M} m 또는 {AMCL_JUMP_DEG}° 넘게 위치를 고쳐 잡은(순간 이동) 횟수 **{len(big)}회**"]
    for t, dm, dd in big[:15]:
        R.append(f"  - {rel(t):.1f}s: {dm:.2f} m · {dd:.1f}°")
    R.append("")
    if len(big) >= 2:
        H.append(f"**[위치] AMCL 위치가 {len(big)}번 크게 튐** — 로봇이 아는 자기 위치가 순간 이동 → 지도상 벽과의 거리 판단이 틀어져 경로·회피가 어긋남")

    # ── 8) 목표·경고·복구 ────────────────────────────────────────────
    R += ["## 2. 목표(주행 요청)별 결과", ""]
    if goals:
        R += ["| 목표 | 시작(s) | 소요(s) | 결과 | 복구 동작 횟수 |", "|---|---|---|---|---|"]
        for gid, g in goals.items():
            if g["start"] is None:
                continue
            R.append(f"| {gid} | {rel(g['start']):.1f} | {((g['end'] or T1) - g['start']):.1f} | {g['result'] or '진행 중(녹화 종료)'} | {rec_by_goal.get(gid, '-')} |")
    else:
        R.append("- 녹화 중 주행 목표 없음")
    R.append("")
    logs = []
    KEY = ("recover", "spin", "backup", "back up", "wait", "fail", "abort", "collision", "progress", "stuck", "oscillat",
           "no valid", "unable", "invalid", "transform", "timeout", "exceed", "clear")
    NAV = ("controller_server", "planner_server", "bt_navigator", "recoveries_server", "local_costmap", "global_costmap",
           "amcl", "map_server", "nav_request", "lifecycle")
    for t, m in D.get("/rosout", []):
        nm, txt = m.name, m.msg
        if m.level >= 30 or (any(n in nm for n in NAV) and any(k in txt.lower() for k in KEY)):
            logs.append((t, m.level, nm, txt))
    R += ["## 8. Nav2 경고·복구 로그(/rosout)", ""]
    if logs:
        import re
        cnt = collections.Counter((nm, re.sub(r"[-+]?\d+(\.\d+)?", "#", txt)[:90]) for _, _, nm, txt in logs)
        R += ["| 횟수 | 노드 | 메시지 |", "|---|---|---|"]
        for (nm, txt), c in cnt.most_common(25):
            R.append(f"| {c} | {nm} | {txt.replace('|', '/')} |")
        R += ["", "<details><summary>시간순 전체(최대 200줄)</summary>", "", "```"]
        LV = {10: "D", 20: "I", 30: "W", 40: "E", 50: "F"}
        for t, lv, nm, txt in logs[:200]:
            R.append(f"{rel(t):7.1f}s [{LV.get(lv, lv)}] {nm}: {txt}")
        R += ["```", "</details>", ""]
        nrec = sum(1 for _, _, nm, txt in logs if any(k in txt.lower() for k in ("spin", "backup", "back up", "recover")))
        if nrec >= 3:
            H.append(f"**[복구] 복구 동작(제자리 회전·후진 등) 관련 로그 {nrec}건** — 막혀서 복구하다 주변을 긁는 패턴 확인 필요")
    else:
        R += ["- 경고·복구 로그 없음", ""]

    # ── 9) 전원 ─────────────────────────────────────────────────────
    R += ["## 9. 모터·전원", ""]
    if amps:
        R.append(f"- 모터 전류 최대 {max(a for _, a in amps)} (드라이버 단위, 보통 0.1 A)")
    if volts:
        vv = [v for _, v in volts]
        R.append(f"- 배터리 전압(드라이버 ?V 첫 값, 단위 0.1 V) 최저 {min(vv)} · 최고 {max(vv)}")
    flt = [(t, m.value) for t, m in D.get("/fault_flag", []) if any(v != 0 for v in m.value)]
    R.append(f"- 모터 드라이버 고장 플래그 0이 아닌 메시지: {len(flt)}건")
    R.append("")

    # ── 그림 ────────────────────────────────────────────────────────
    figs = []
    fig, axs = plt.subplots(4, 1, figsize=(14, 11), sharex=True)
    if cmd:
        axs[0].plot([rel(c[0]) for c in cmd], [c[1] for c in cmd], label="명령 v (/cmd_vel)", lw=1)
        axs[1].plot([rel(c[0]) for c in cmd], [c[2] for c in cmd], label="명령 ω", lw=1)
    if odo:
        axs[0].plot([rel(o[0]) for o in odo], [o[1] for o in odo], label="실제 v (/odom)", lw=1)
        axs[1].plot([rel(o[0]) for o in odo], [o[2] for o in odo], label="실제 ω", lw=1)
    for s0, s1 in stalls:
        axs[0].axvspan(rel(s0), rel(s1), color="red", alpha=0.2)
    for g0, d in gaps:
        axs[0].axvline(rel(g0), color="orange", lw=0.6)
    axs[0].set_ylabel("전진 속도 m/s")
    axs[1].set_ylabel("회전 속도 rad/s")
    if clr_v:
        axs[2].plot([rel(t) for t in clr_t], np.minimum(clr_v, 1.5), lw=0.8, color="k")
        axs[2].axhline(NEAR_M, color="orange", ls="--", lw=0.8)
        axs[2].axhline(CONTACT_M, color="red", ls="--", lw=0.8)
    axs[2].set_ylabel("차체~장애물 m")
    if amps:
        axs[3].plot([rel(t) for t, _ in amps], [a for _, a in amps], lw=0.8, label="모터 전류")
    if volts:
        ax2 = axs[3].twinx()
        ax2.plot([rel(t) for t, _ in volts], [v for _, v in volts], lw=0.8, color="g", label="전압")
        ax2.set_ylabel("전압(0.1V)")
    axs[3].set_ylabel("전류")
    axs[3].set_xlabel("녹화 시작 후 초")
    for g in goals.values():
        if g["start"]:
            for a in axs:
                a.axvspan(rel(g["start"]), rel(g["end"] or T1), color="tab:blue", alpha=0.05)
    for a in axs[:2]:
        a.legend(loc="upper right", fontsize=8)
    for e in ev_rows:
        axs[2].plot(rel(e["t"]), e["min"], "rv", ms=5)
    fig.suptitle("주행 타임라인 — 빨간 띠=걸림, 주황 선=명령 끊김, 빨간 ▼=근접, 옅은 파랑=목표 진행 중")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "timeline.png"), dpi=110)
    plt.close(fig)
    figs.append("timeline.png")

    # 궤적(지도 좌표)
    if maps:
        mp = maps[-1][1]
        mi = mp.info
        grid = np.asarray(mp.data, dtype=np.int16).reshape(mi.height, mi.width)
        path = []
        for t, _ in D.get("/odom", [])[::5]:
            T = tf.lookup(mp.header.frame_id or "map", base, t)
            if T:
                path.append((T[0], T[1]))
        fig, ax = plt.subplots(figsize=(10, 10))
        img = np.where(grid < 0, 0.7, np.where(grid >= 65, 0.0, 1.0))
        ext = [mi.origin.position.x, mi.origin.position.x + mi.width * mi.resolution,
               mi.origin.position.y, mi.origin.position.y + mi.height * mi.resolution]
        ax.imshow(img, cmap="gray", origin="lower", extent=ext, vmin=0, vmax=1)
        for t, p in plans[-6:]:
            ax.plot([q.pose.position.x for q in p.poses], [q.pose.position.y for q in p.poses], lw=0.8, alpha=0.7)
        if path:
            P = np.array(path)
            ax.plot(P[:, 0], P[:, 1], "b-", lw=1.2, label="실제 이동")
            ax.set_xlim(P[:, 0].min() - 3, P[:, 0].max() + 3)
            ax.set_ylim(P[:, 1].min() - 3, P[:, 1].max() + 3)
        for e in ev_rows:
            T = tf.lookup(mp.header.frame_id or "map", base, e["t"])
            if T:
                ex, ey = apply(T, np.array([e["pt"][0]]), np.array([e["pt"][1]]))
                ax.plot(ex, ey, "rx", ms=8)
        ax.set_aspect("equal")
        ax.set_title("지도 위 실제 이동(파랑)·전역 경로(색선)·근접 지점(빨간 ×)")
        fig.tight_layout()
        fig.savefig(os.path.join(out, "trajectory.png"), dpi=110)
        plt.close(fig)
        figs.append("trajectory.png")

    # 근접 이벤트 확대 그림(가까운 순)
    for i, e in enumerate(sorted(ev_rows, key=lambda e: e["min"])[:MAX_EVENT_FIGS]):
        cc = e["cc"]
        fig, ax = plt.subplots(figsize=(7, 7))
        t = e["t"]
        if cc:
            c = cc["msg"]
            ci = c.info
            g = np.asarray(c.data, dtype=np.int16).reshape(ci.height, ci.width).astype(float)
            g[g < 0] = np.nan          # 값은 0~100(OccupancyGrid)
            Tbc = invert(cc["Tcb"])     # costmap → 차체 좌표로 그리기
            ys_, xs_ = np.nonzero(np.nan_to_num(g) > 0)
            gx = ci.origin.position.x + (xs_ + 0.5) * ci.resolution
            gy = ci.origin.position.y + (ys_ + 0.5) * ci.resolution
            bx, by = apply(Tbc, gx, gy)
            sc = ax.scatter(bx, by, c=g[ys_, xs_], s=9, marker="s", cmap="YlOrRd", vmin=0, vmax=100)
            fig.colorbar(sc, ax=ax, fraction=0.04, label="costmap 비용")
        s = series([x[0] for x in scans], scans, t)
        if s:
            m = s[1]
            r = np.asarray(m.ranges, dtype=np.float32)
            a = m.angle_min + np.arange(len(r)) * m.angle_increment
            ok = np.isfinite(r) & (r > 0.05) & (r < 6)
            T = tf.lookup(base, m.header.frame_id, t)
            if T:
                px, py = apply(T, r[ok] * np.cos(a[ok]), r[ok] * np.sin(a[ok]))
                ax.plot(px, py, "b.", ms=2, label="LiDAR")
        for topic, col in (("/local_plan", "m"), ("/plan", "c")):
            pl = series([x[0] for x in D.get(topic, [])], D.get(topic, []), t)
            if pl and pl[1].poses:
                T = tf.lookup(base, pl[1].header.frame_id, t)
                if T:
                    X = np.array([q.pose.position.x for q in pl[1].poses])
                    Y = np.array([q.pose.position.y for q in pl[1].poses])
                    px, py = apply(T, X, Y)
                    ax.plot(px, py, col + "-", lw=1.5, label=topic)
        ax.add_patch(plt.Rectangle((-BODY_L / 2, -BODY_W / 2), BODY_L, BODY_W, fill=False, ec="k", lw=2, label="실제 차체"))
        if isinstance(lr, (int, float)):
            ax.add_patch(plt.Circle((0, 0), lr, fill=False, ec="g", ls="--", lw=1.5, label=f"Nav2 원 r={lr}"))
        ax.plot(*e["pt"], "r*", ms=14, label="가장 가까운 점")
        ax.arrow(0, 0, 0.35, 0, head_width=0.06, color="k")
        ax.set_xlim(-2, 2)
        ax.set_ylim(-2, 2)
        ax.set_aspect("equal")
        ax.grid(alpha=0.3)
        ax.legend(loc="lower left", fontsize=7)
        vtxt = f"v={e['v']:.2f} ω={e['w']:.2f}" if e["v"] is not None else ""
        ax.set_title(f"근접 #{i+1}  {rel(t):.1f}s  {e['min']:.3f} m  {e['zone']}  {vtxt}\n(로봇 기준, 화살표=앞)", fontsize=10)
        fn = f"event_{i+1:02d}.png"
        fig.tight_layout()
        fig.savefig(os.path.join(out, fn), dpi=100)
        plt.close(fig)
        figs.append(fn)

    # ── 보고서 쓰기 ──────────────────────────────────────────────────
    head = [f"# 주행 rosbag 분석 — `{os.path.basename(bag)}`", "",
            "## ★ 자동 진단 소견 (근거 수치는 아래 각 절)", ""]
    head += [f"{i+1}. {h}" for i, h in enumerate(H)] if H else ["- 뚜렷한 이상 징후 없음(근접·걸림 이벤트를 그림으로 직접 확인)"]
    head += ["", "> 소견은 규칙 기반 자동 판정이라 '원인 후보'다. event_XX.png 그림과 RViz 재생(`ros2 bag play`)으로 확인할 것.", ""]
    # 절 번호 순서로 정렬(계산 순서와 보고 순서가 달라서)
    blocks, cur = [], None
    for line in R:
        if line.startswith("## "):
            cur = [line]
            blocks.append(cur)
        elif cur is not None:
            cur.append(line)
    def _num(b):
        try:
            return float(b[0][3:].split(".")[0])
        except ValueError:
            return 99
    R = [ln for b in sorted(blocks, key=_num) for ln in b]
    with open(os.path.join(out, "report.md"), "w") as f:
        f.write("\n".join(head + R + ["## 그림", ""] + [f"- ![{x}]({x})" for x in figs]) + "\n")
    print(f"[분석] 완료 → {os.path.join(out, 'report.md')} (그림 {len(figs)}개)")
    for h in H:
        print("  ·", h.replace("**", ""))


if __name__ == "__main__":
    main()
