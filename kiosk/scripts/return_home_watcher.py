#!/usr/bin/env python3
# =========================================================================
# return_home_watcher.py — 목적지 도착을 감지해 초기 위치로 자동 복귀시킨다.
#
#   사용법:  ./scripts/return_home_watcher.sh        (Ctrl+C 로 종료)
#
# 동작:
#   [1] nav_request_done/ 에 새 파일 = nav_request_watcher가 goal을 "수락"함
#       → 그 목적지를 추적 대상으로 삼는다.
#   [2] TF(map→base_footprint)로 로봇 위치를 감시해 목표 반경 안에 들어오면 "도착" 판정.
#   [3] 도착 후 RETURN_DELAY_SEC 만큼 대기(안내받은 사람이 확인할 시간).
#   [4] nav_request/ 에 "초기 위치" 요청 파일을 써서 복귀시킨다.
#       (기존 watcher가 그 파일을 읽어 실제 goal을 보낸다)
#
#   · 대기/복귀 중 새 음성 요청이 들어오면 즉시 취소하고 새 목적지를 우선한다.
#   · 목적지가 "초기 위치" 자체이면 복귀를 다시 예약하지 않는다(무한 왕복 방지).
#
# ★ 기존 nav_request_watcher.py 는 수정하지 않는다.
#   (그 watcher는 "goal 수락" 시점에만 파일을 옮기고 실제 도착은 로그만 남기므로,
#    파일버스만으로는 도착을 알 수 없어 TF로 직접 판정한다)
# =========================================================================
import json
import math
import os
import sys
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from sensor_msgs.msg import LaserScan
from rclpy.qos import qos_profile_sensor_data
from tf2_ros import Buffer, TransformListener
from rclpy.executors import SingleThreadedExecutor
import threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rotate_ctl import RotateController   # noqa: E402  (2026-11-13 제자리 회전 제어기)
from rclpy.action import ActionClient     # noqa: E402
from geometry_msgs.msg import PoseStamped  # noqa: E402
try:
    from nav2_msgs.action import ComputePathToPose   # noqa: E402  (2026-11-16 복귀 경로 미리 받기)
except Exception:
    ComputePathToPose = None

# 파일버스 경로. NAV_BUS_DIR 로 덮어쓸 수 있다.
#  · 실제 운용에서는 기본값(llm_package/bus)을 쓴다.
#  · 테스트에서는 임시 디렉토리를 지정해, 실제 로봇에 goal이 나가지 않게 한다.
BUS = Path(os.environ.get("NAV_BUS_DIR", "/mnt/ssd/cart_ros2/src/llm_package/bus"))
REQ_DIR = BUS / "nav_request"
DONE_DIR = BUS / "nav_request_done"
LABELS_PATH = Path("/mnt/ssd/cart_ros2/src/hospital_mission/map/map_labels.json")

HOME_ZONE = "초기 위치"
MAP_FRAME = "map"
BASE_CANDIDATES = ("base_footprint", "base_link")

# 앱(kiosk_server)이 읽는 상태 파일. 도착을 화면에 띄우기 위한 유일한 통로.
#  (kiosk_server는 stt의 .venv에서 돌아 rclpy가 없으므로 TF를 직접 못 본다)
STATUS_FILE = BUS / "kiosk_status.json"

# 튜닝값 (환경변수로 덮어쓸 수 있다)
ARRIVE_RADIUS = float(os.environ.get("ARRIVE_RADIUS", "0.8"))        # m
# 도착 후 대기. 앱의 "도착 화면 → 음성 화면" 전환 시간과 같은 값이어야
# 화면 복귀와 로봇 복귀가 동시에 일어난다.
RETURN_DELAY_SEC = float(os.environ.get("RETURN_DELAY_SEC", "5"))
# 2026-11-16: 복귀 출발 전 '복귀 경로 쪽으로 먼저 제자리 회전'. 실시간 감시(live_drive_monitor) 실측: 외과에서 복귀 경로가
#  로봇 바로 뒤에서 시작하면 Nav2(DWB)가 좌/우를 못 정해 ±0.02 rad/s(모터 9rpm)만 번갈아 명령 → 정지 마찰을 못 이겨
#  1분 47초 멈춤, 강제 회전 복구(0.5 rad/s) 때만 돎. → 경로 계획만 받아(planner) 경로 1m 앞 점을 향해 먼저 돌고 Nav2 에 넘김.
#  끄기: RETURN_PREROTATE=0
PREROTATE_ENABLE = os.environ.get("RETURN_PREROTATE", "1") != "0"
PREROTATE_LOOKAHEAD = float(os.environ.get("PREROTATE_LOOKAHEAD", "1.0"))        # m — 경로에서 이만큼 앞 점을 향함
PREROTATE_MIN_ERR = math.radians(float(os.environ.get("PREROTATE_MIN_ERR_DEG", "45")))   # 이보다 덜 틀어졌으면 그냥 Nav2
PREROTATE_TOL = math.radians(float(os.environ.get("PREROTATE_TOL_DEG", "8")))
# 차체 사각형(0.9×0.7+5cm) 외접원 0.64 m + 여유 0.15 — 가장 가까운 장애물이 이보다 가까우면 제자리 회전 생략
PREROTATE_CLEARANCE = float(os.environ.get("PREROTATE_CLEARANCE", "0.79"))
TRACK_TIMEOUT_SEC = float(os.environ.get("TRACK_TIMEOUT_SEC", "480"))
POLL_SEC = 0.5
LIVE_STATUS_SEC = 0.5    # 이동 중 진행률 갱신 주기(앱 폴링 2Hz에 맞춤)

# ── 최종 방향 정렬 (TF 피드백 제자리 회전) ────────────────────────────────
# Nav2의 yaw_goal_tolerance(0.15rad≈8.6°)로는 "주차했던 방향과 완전히 동일"에
# 못 미치므로, 복귀 도착 후 TF로 각도를 직접 보며 제자리 회전으로 수렴시킨다.
ALIGN_ENABLE = os.environ.get("ALIGN_ENABLE", "1") != "0"
ALIGN_TOL = math.radians(float(os.environ.get("ALIGN_TOL_DEG", "0.5")))   # 목표 정밀도
# 예전 실측: 명령 0.4rad/s → 실제 ~0.048rad/s(약 12%). 원인은 모터 드라이버의 속도→회전수 환산 계수
#  (wheel_circumference) 오류였고 2026-11-12 보정(0.15→0.0234, 실제/명령 0.156 → 1.0). 이제 명령 = 실제 회전이라
#  예전처럼 부풀린 값을 쓰면 6배 빨리 돈다 → 상한 0.8→0.35, 최소 0.12→0.08(실제 4.6°/s, 너무 느리면 아래 로직이 올림)
ALIGN_MAX_W = float(os.environ.get("ALIGN_MAX_W", "0.35"))  # rad/s 상한(안전, 이제 실제 값)
ALIGN_MIN_W = float(os.environ.get("ALIGN_MIN_W", "0.05"))  # 정지마찰 극복 최소속도(멈추면 rotate_ctl 이 잠깐 올림)
ALIGN_K = 0.8                                                # 비례이득(1.2→0.8, 2026-11-13 rotate_ctl 로 교체하며 완화)
# 실제 회전이 느리므로(위 참조) 큰 각도(예:140°)도 완주할 수 있게 넉넉히 잡는다.
ALIGN_TIMEOUT = float(os.environ.get("ALIGN_TIMEOUT", "90"))
# (2026-11-13 rotate_ctl 로 교체 후 미사용 — 멈춤 판단은 rotate_ctl 이 1.5초 실제 회전량으로 함. 환경변수 호환용으로만 남김)
ALIGN_MIN_RATE = math.radians(float(os.environ.get("ALIGN_MIN_RATE_DEG", "8")))
# Nav2가 아직 주행 중일 때 정렬을 시작하면 두 컨트롤러가 /cmd_vel을 두고 다퉈
# 로봇이 제자리에서 떨리기만 한다(실측: 20초간 순 회전 1.12°).
# 그래서 "고정 시간 대기"가 아니라 "로봇이 실제로 멈출 때까지" 기다린다.
ALIGN_SETTLE_SEC = 1.5           # 정지 후 추가 여유
STOP_POS_EPS = 0.02              # m — 이보다 덜 움직이면 정지로 간주
STOP_YAW_EPS = math.radians(1.0) # rad
STOP_STABLE_SEC = 1.5            # 이 시간 동안 정지 상태가 유지되어야 함
STOP_WAIT_TIMEOUT = 40.0         # 그래도 안 멈추면 포기하고 진행
CMD_VEL_TOPIC = os.environ.get("CMD_VEL_TOPIC", "/cmd_vel")

# ── 라이다 기반 벽 정렬 ───────────────────────────────────────────────────
# amcl 방향추정이 이 자리에서 ~20° 부정확 → amcl로 맞추면 물리적으로 틀어짐.
# 라이다로 뒤쪽 벽을 직접 보고 "벽과 수직(등돌림)"이 되게 미세 정렬한다(amcl 무관).
#   순서: align_to_yaw(amcl, 대략) → align_to_wall(라이다, 정밀)
WALL_ALIGN_ENABLE = os.environ.get("WALL_ALIGN_ENABLE", "1") != "0"
WALL_ALIGN_TOL = math.radians(float(os.environ.get("WALL_ALIGN_TOL_DEG", "0.6")))
SCAN_TOPIC = os.environ.get("SCAN_TOPIC", "/scan_multi")   # 프레임이 base와 정렬(yaw0)
WALL_REAR_HALF = math.radians(35)     # 뒤(180°) ±35° 섹터에서 벽 검출
WALL_RMIN, WALL_RMAX = 0.3, 3.5       # 벽 거리 유효 범위(m)
WALL_MIN_PTS = 20                     # 이보다 점 적으면 벽 미검출로 간주
WALL_ALIGN_TIMEOUT = float(os.environ.get("WALL_ALIGN_TIMEOUT", "60"))

# ── 캐스터 꼬임/슬립 탈출(위글) ──
# 정렬은 제자리 회전인데, 각속도를 최대(ALIGN_MAX_W)까지 올려도 캐스터가 꼬여
# 실제로 안 돌 때가 있다. 그때 "좌우 번갈아 흔들기(위글)"로 캐스터를 털어낸다.
#  · 위글은 정/역 대칭이라 net 회전≈0 → 정렬을 흐트러뜨리지 않음(직후 루프가 재보정).
#  · 병진/후진 없음(자리 안 옮김) → 벽 쪽으로 밀리거나 홈을 벗어날 위험 없음.
#  · 정렬당 최대 UNSTICK_MAX_TRIES회, 실패하면 포기·정지(모터/캐스터 보호). 절대 무한反복 안 함.
UNSTICK_ENABLE = os.environ.get("UNSTICK_ENABLE", "1") != "0"
UNSTICK_MAX_TRIES = int(os.environ.get("UNSTICK_MAX_TRIES", "3"))       # 정렬당 위글 상한
UNSTICK_WIGGLE_W = float(os.environ.get("UNSTICK_WIGGLE_W", "0.25"))    # 위글 각속도(rad/s) — 0.6→0.4→0.25(2026-11-12 환산 보정으로 이제 실제 값)
UNSTICK_WIGGLE_SEC = float(os.environ.get("UNSTICK_WIGGLE_SEC", "0.35"))# 한 방향 지속(s) — 스윙 폭 축소(0.4→0.35)
UNSTICK_WIGGLE_CYCLES = int(os.environ.get("UNSTICK_WIGGLE_CYCLES", "2"))  # 좌우 반복 횟수

# 우리(이 노드)가 만든 복귀 요청임을 표시 — 사용자 새 요청과 구분하기 위해
RETURN_SOURCE = "return_home"

# 상태
IDLE, TRACKING, DWELL, RETURNING = "IDLE", "TRACKING", "DWELL", "RETURNING"


def load_zone_goal(name):
    """zone 이름 → (x, y). 없으면 None."""
    try:
        with open(LABELS_PATH, encoding="utf-8") as f:
            zones = json.load(f).get("zones", [])
    except (OSError, ValueError):
        return None
    for z in zones:
        if z.get("name") == name:
            ng = z.get("nav_goal") or {}
            if "x" in ng and "y" in ng:
                return float(ng["x"]), float(ng["y"])
    return None


def load_zone_yaw(name):
    """zone 이름 → 목표 yaw(rad). qz/qw 우선, 없으면 yaw_deg."""
    try:
        with open(LABELS_PATH, encoding="utf-8") as f:
            zones = json.load(f).get("zones", [])
    except (OSError, ValueError):
        return None
    for z in zones:
        if z.get("name") == name:
            ng = z.get("nav_goal") or {}
            if "qz" in ng and "qw" in ng:
                return math.atan2(2.0 * float(ng["qw"]) * float(ng["qz"]),
                                  1.0 - 2.0 * float(ng["qz"]) ** 2)
            if "yaw_deg" in ng:
                return math.radians(float(ng["yaw_deg"]))
    return None


def norm_angle(a):
    """각도를 [-pi, pi]로 정규화 (179°와 -179°의 차이가 2°가 되도록)."""
    return math.atan2(math.sin(a), math.cos(a))


def read_place_name(path):
    """요청 파일 → (place_name, source). 기존 watcher와 같은 키 우선순위."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    for key in ("place_name", "destination", "target", "goal", "text", "user_text"):
        if data.get(key):
            return str(data[key]).strip(), data.get("source")
    return None, data.get("source")


class ReturnHomeWatcher(Node):
    def __init__(self):
        super().__init__("return_home_watcher")
        self.buf = Buffer()
        self.listener = TransformListener(self.buf, self)
        self.cmd_pub = self.create_publisher(Twist, CMD_VEL_TOPIC, 10)
        self.latest_scan = None
        self.create_subscription(LaserScan, SCAN_TOPIC,
                                 lambda m: setattr(self, "latest_scan", m),
                                 qos_profile_sensor_data)

        self.state = IDLE
        self.target_name = None
        self.target_xy = None
        self.track_started = 0.0
        self.dwell_until = 0.0
        self.initial_dist = None
        self.max_progress = 0.0
        self.last_live = 0.0
        self.pending_return = None   # 우리가 낸 복귀 요청(미처리 시 정리용)
        self.align_cancelled = False  # 정렬·회전 중 사용자 새 요청으로 중단됐나
        self.plan_client = ActionClient(self, ComputePathToPose, "compute_path_to_pose") if ComputePathToPose else None

        # 기동 시점에 이미 있던 파일은 "처리済"으로 간주(과거 요청에 반응하지 않도록)
        self.seen_done = self._names(DONE_DIR)
        self.seen_req = self._names(REQ_DIR)

        self.log(f"감시 시작 · 도착반경 {ARRIVE_RADIUS}m · 도착 후 {RETURN_DELAY_SEC:.0f}초 뒤 복귀")
        if load_zone_goal(HOME_ZONE) is None:
            self.log(f"⚠ map_labels.json 에 '{HOME_ZONE}' nav_goal 이 없습니다. 복귀 불가.")

    def log(self, msg):
        print(f"[return] {msg}", flush=True)

    @staticmethod
    def _names(d):
        try:
            return {p.name for p in d.glob("*.json")}
        except OSError:
            return set()

    def robot_xy(self):
        p = self.robot_pose()
        return (p[0], p[1]) if p else None

    def robot_pose(self):
        """(x, y, yaw) — TF map→base. 없으면 None."""
        for cand in BASE_CANDIDATES:
            try:
                tf = self.buf.lookup_transform(MAP_FRAME, cand, rclpy.time.Time())
                self.last_tf_stamp = tf.header.stamp
                t, q = tf.transform.translation, tf.transform.rotation
                yaw = math.atan2(2.0 * q.w * q.z, 1.0 - 2.0 * q.z * q.z)
                return t.x, t.y, yaw
            except Exception:
                continue
        return None

    def data_age(self):
        """정렬에 쓰는 데이터가 몇 초 전 것인지(위치 TF, 라이다). 2026-11-13: 지연이 크면 정렬이 지나침."""
        now = self.get_clock().now().nanoseconds * 1e-9

        def age(stamp):
            return (now - (stamp.sec + stamp.nanosec * 1e-9)) if stamp is not None else float("nan")
        self.robot_pose()
        scan = self.latest_scan
        return age(getattr(self, "last_tf_stamp", None)), age(scan.header.stamp if scan is not None else None)

    def stop_robot(self):
        """정지 명령. 정렬을 끝내거나 중단할 때 반드시 호출한다."""
        for _ in range(3):          # 한 번은 유실될 수 있어 여러 번 보낸다
            self.cmd_pub.publish(Twist())
            time.sleep(0.02)

    def wait_until_stopped(self):
        """로봇이 실제로 멈출 때까지 기다린다.
        Nav2가 주행을 끝내기 전에 정렬을 시작하면 /cmd_vel 명령이 서로 충돌해
        로봇이 떨기만 하고 회전하지 않는다(실측). 정지 확인 후에만 정렬한다."""
        deadline = time.time() + STOP_WAIT_TIMEOUT
        last = None
        stable_since = None
        while time.time() < deadline:
            time.sleep(0.05)
            pose = self.robot_pose()
            if pose is None:
                time.sleep(0.1)
                continue
            if last is not None:
                moved = math.hypot(pose[0] - last[0], pose[1] - last[1])
                turned = abs(norm_angle(pose[2] - last[2]))
                if moved < STOP_POS_EPS and turned < STOP_YAW_EPS:
                    if stable_since is None:
                        stable_since = time.time()
                    elif time.time() - stable_since >= STOP_STABLE_SEC:
                        self.log(f"  로봇 정지 확인 ({time.time() - (deadline - STOP_WAIT_TIMEOUT):.1f}초 대기)")
                        return True
                else:
                    stable_since = None      # 아직 움직이는 중
            last = pose
            time.sleep(0.15)
        self.log("  ⚠ 로봇이 멈추지 않아 대기를 종료하고 정렬을 시도합니다.")
        return False

    def _caster_unstick(self, reason=""):
        """캐스터 꼬임/슬립 탈출: 제자리에서 좌우로 번갈아 흔든다(위글).
        각속도를 최대로 올려도 안 돌 때 1회 호출. 정/역 대칭이라 net 회전≈0,
        병진 없음(자리 안 옮김). 어떤 경로로든 정지로 끝난다.
        새 사용자 요청이 들어오면 즉시 중단."""
        self.log(f"  🔧 캐스터 탈출 위글{(' · ' + reason) if reason else ''} "
                 f"(±{UNSTICK_WIGGLE_W:.2f} rad/s, {UNSTICK_WIGGLE_CYCLES}회)")

        def spin_for(wz, dur):
            t_end = time.time() + dur
            msg = Twist()
            msg.angular.z = float(wz)          # 회전만(병진 0)
            while time.time() < t_end:
                if self.poll_new_user_request():
                    return False
                self.cmd_pub.publish(msg)
                time.sleep(0.05)
            return True

        try:
            for _ in range(UNSTICK_WIGGLE_CYCLES):
                if not spin_for(+UNSTICK_WIGGLE_W, UNSTICK_WIGGLE_SEC):
                    return False
                if not spin_for(-UNSTICK_WIGGLE_W, UNSTICK_WIGGLE_SEC):
                    return False
        finally:
            self.stop_robot()                  # ★ 항상 정지로 종료
        return True

    def _wall_error(self):
        """뒤쪽 벽에 대한 '수직(square) 오차'(rad)를 라이다로 계산.
        벽선이 로봇 x축에 수직(=등돌림 완료)이면 0. 부호 있음.
        벽 미검출이면 None. (SCAN_TOPIC 프레임이 base와 정렬돼 스캔각=로봇각)"""
        scan = self.latest_scan
        if scan is None:
            return None
        amin, ainc = scan.angle_min, scan.angle_increment
        xs, ys = [], []
        for i, r in enumerate(scan.ranges):
            if not math.isfinite(r) or r < WALL_RMIN or r > WALL_RMAX:
                continue
            th = amin + i * ainc                       # 로봇 기준 각도
            if abs(abs(th) - math.pi) <= WALL_REAR_HALF:   # 뒤쪽 섹터
                xs.append(r * math.cos(th)); ys.append(r * math.sin(th))
        if len(xs) < WALL_MIN_PTS:
            return None
        import numpy as np
        P = np.column_stack([xs, ys]); P = P - P.mean(0)
        _, _, vt = np.linalg.svd(P)
        dx, dy = vt[0]                                  # 벽선 방향
        phi = math.atan2(dy, dx)
        # 벽이 로봇 x축에 수직이면 벽선은 y축 방향(±90°). square에서의 편차(-90~90°).
        e = (math.degrees(phi) - 90 + 90) % 180 - 90
        return math.radians(e)

    def align_to_wall(self):
        """라이다로 뒤쪽 벽을 보며 '벽과 수직(등돌림)'이 되게 제자리 회전.
        amcl 방향오차와 무관하게 실제 벽 기준으로 물리적으로 정렬한다.
        전진/후진 없이 angular.z만, 어떤 경우에도 정지로 끝난다."""
        self.wait_until_stopped()
        e0 = self._wall_error()
        if e0 is None:
            self.log("  벽 미검출 → 라이다 정렬 건너뜀(amcl 정렬 결과 유지)")
            return False
        self.log(f"라이다 벽 정렬 시작: 현재 오차 {math.degrees(e0):+.2f}° "
                 f"(허용 {math.degrees(WALL_ALIGN_TOL):.2f}°)")
        deadline = time.time() + WALL_ALIGN_TIMEOUT
        t_begin = time.time()
        ctl = RotateController(WALL_ALIGN_TOL, w_min=ALIGN_MIN_W, w_max=ALIGN_MAX_W, k=ALIGN_K)
        unstick_tries = 0
        aligned = False
        recent = []                      # 벽 오차 잡음 완화: 최근 3개 중앙값
        try:
            while time.time() < deadline:
                time.sleep(0.05)
                if self.poll_new_user_request():
                    self.log("정렬 중 새 요청 감지 → 라이다 정렬 중단"); break
                e = self._wall_error()
                if e is None:
                    continue
                recent = (recent + [e])[-3:]
                e = sorted(recent)[len(recent) // 2]
                now = time.time()
                w, done = ctl.step(e, now)
                for ev in ctl.events:
                    self.log(f"  {ev}")
                ctl.events.clear()
                if done:
                    aligned = True; break
                if ctl.stuck(now):
                    if UNSTICK_ENABLE and unstick_tries < UNSTICK_MAX_TRIES:
                        unstick_tries += 1
                        self._caster_unstick(f"벽정렬 {unstick_tries}/{UNSTICK_MAX_TRIES}")
                        ctl.reset_after_unstick(time.time()); recent = []
                        continue
                    self.log("  ⚠ 위글 반복에도 미해소 → 라이다 정렬 포기(정지)")
                    break
                msg = Twist()
                msg.angular.z = float(w)                     # e>0 → CCW(회전하면 오차 감소)
                self.cmd_pub.publish(msg)
        finally:
            self.stop_robot()
        ef = self._wall_error()
        pose = self.robot_pose()
        self.log(f"라이다 벽 정렬 {'완료' if aligned else '미완료'} · "
                 f"최종 오차 {(math.degrees(ef) if ef is not None else float('nan')):+.2f}° · "
                 f"{time.time() - t_begin:.1f}초 · 미세조정 {ctl.pulses}회 · "
                 f"이때 지도 방향 {(math.degrees(pose[2]) if pose else float('nan')):.2f}°(초기 위치 방향값 보정 참고용)")
        return aligned

    def align_to_yaw(self, target_yaw, tol=None, label="방향 정렬", settle=True):
        """TF를 보며 제자리 회전으로 목표 방향에 수렴시킨다.

        전진/후진은 절대 하지 않고(angular.z만), 어떤 경우에도 정지로 끝난다.
        모터에는 데드밴드가 있어 낮은 각속도 명령으로는 실제로 돌지 않을 수 있다.
        그래서 "명령을 보냈는데 yaw가 안 변하면" 각속도를 단계적으로 올린다.
        (이 보정이 없으면 로봇이 멈춘 채 타임아웃까지 흘러 정렬이 미완성된다)
        """
        tol = ALIGN_TOL if tol is None else tol
        self.align_cancelled = False
        start_pose = self.robot_pose()
        start_yaw = start_pose[2] if start_pose else None
        self.log(f"{label} 시작: 현재 "
                 f"{('%.2f°' % math.degrees(start_yaw)) if start_yaw is not None else '?'} "
                 f"→ 목표 {math.degrees(target_yaw):.2f}° "
                 f"(허용 {math.degrees(tol):.2f}°)")
        self.wait_until_stopped()          # ★ Nav2 주행이 끝난 뒤에만 개입
        if settle:
            time.sleep(ALIGN_SETTLE_SEC)
        tf_age, scan_age = self.data_age()
        self.log(f"  데이터 지연: 위치(TF) {tf_age:.2f}초 · 라이다 {scan_age:.2f}초 (0.5초 넘으면 정렬이 흔들릴 수 있음)")

        deadline = time.time() + ALIGN_TIMEOUT
        t_begin = time.time()
        aligned = False
        ctl = RotateController(tol, w_min=ALIGN_MIN_W, w_max=ALIGN_MAX_W, k=ALIGN_K)
        unstick_tries = 0
        last_report = 0.0

        try:
            while time.time() < deadline:
                time.sleep(0.05)
                if self.poll_new_user_request():
                    self.log(f"{label} 중 새 요청 감지 → 중단")
                    self.align_cancelled = True
                    break
                pose = self.robot_pose()
                if pose is None:
                    continue
                yaw = pose[2]
                err = norm_angle(target_yaw - yaw)
                now = time.time()
                w, done = ctl.step(err, now)
                for ev in ctl.events:
                    self.log(f"  {ev}")
                ctl.events.clear()
                if done:
                    aligned = True
                    break
                if ctl.stuck(now):
                    if UNSTICK_ENABLE and unstick_tries < UNSTICK_MAX_TRIES:
                        unstick_tries += 1          # 최대 속도로도 안 돎 → 캐스터 위글로 탈출
                        self._caster_unstick(f"방향정렬 {unstick_tries}/{UNSTICK_MAX_TRIES}")
                        ctl.reset_after_unstick(time.time())
                        continue
                    self.log("  ⚠ 위글 반복에도 미해소 → 방향 정렬 포기(정지)")
                    break
                if now - last_report > 2.0:          # 진행 상황 기록
                    self.log(f"  정렬 중: 현재 {math.degrees(yaw):7.2f}° 남은각 {math.degrees(err):6.2f}° "
                             f"명령 {w:+.2f} rad/s")
                    last_report = now
                msg = Twist()
                msg.angular.z = float(w)                     # 회전만, 병진 성분 0
                self.cmd_pub.publish(msg)
        finally:
            self.stop_robot()                                # ★ 어떤 경로로든 정지

        pose = self.robot_pose()
        if pose:
            final_err = math.degrees(norm_angle(target_yaw - pose[2]))
            moved = (math.degrees(abs(norm_angle(pose[2] - start_yaw)))
                     if start_yaw is not None else float("nan"))
            self.log(f"{label} {'완료' if aligned else '미완료'} · "
                     f"최종 {math.degrees(pose[2]):.2f}° (목표 {math.degrees(target_yaw):.2f}°) · "
                     f"오차 {final_err:+.2f}° · 실제 회전량 {moved:.2f}° · "
                     f"{time.time() - t_begin:.1f}초 · 미세조정 {ctl.pulses}회")
            if not aligned:
                self.log("  ⚠ 정렬 미완료 — 로봇이 실제로 회전했는지(실제 회전량) 확인 필요. "
                         "회전량이 0에 가까우면 ALIGN_MIN_W를 올리세요.")
        return aligned

    def plan_path(self, goal_xy, timeout=6.0):
        """Nav2 경로 계획기에 '지금 위치 → goal' 경로만 받아 온다(로봇은 안 움직임). 실패하면 None."""
        if self.plan_client is None or not self.plan_client.wait_for_server(timeout_sec=2.0):
            return None
        g = ComputePathToPose.Goal()
        g.goal = PoseStamped()
        g.goal.header.frame_id = "map"
        g.goal.header.stamp = self.get_clock().now().to_msg()
        g.goal.pose.position.x, g.goal.pose.position.y = goal_xy
        g.goal.pose.orientation.w = 1.0
        fut = self.plan_client.send_goal_async(g)
        t_end = time.time() + timeout
        while not fut.done() and time.time() < t_end:
            time.sleep(0.05)
        if not fut.done() or not fut.result() or not fut.result().accepted:
            return None
        rfut = fut.result().get_result_async()
        while not rfut.done() and time.time() < t_end:
            time.sleep(0.05)
        if not rfut.done() or rfut.result() is None:
            return None
        return rfut.result().result.path

    def min_obstacle(self):
        scan = self.latest_scan
        if scan is None:
            return None
        rs = [r for r in scan.ranges if math.isfinite(r) and scan.range_min < r < scan.range_max]
        return min(rs) if rs else None

    def face_return_path(self):
        """복귀 출발 전 복귀 경로 쪽으로 제자리 회전. 반환 False = 사용자 새 요청으로 중단(복귀 요청 쓰지 말 것)."""
        goal = load_zone_goal(HOME_ZONE)
        pose = self.robot_pose()
        if goal is None or pose is None:
            return True
        path = self.plan_path(goal)
        if path is None or not path.poses:
            self.log("  복귀 경로를 미리 받지 못함 → 미리 돌기 생략(Nav2 에 맡김)")
            return True
        tgt = None
        for p in path.poses:
            x, y = p.pose.position.x, p.pose.position.y
            if math.hypot(x - pose[0], y - pose[1]) >= PREROTATE_LOOKAHEAD:
                tgt = (x, y)
                break
        if tgt is None:
            return True
        yaw_t = math.atan2(tgt[1] - pose[1], tgt[0] - pose[0])
        err = norm_angle(yaw_t - pose[2])
        if abs(err) < PREROTATE_MIN_ERR:
            self.log(f"  복귀 경로가 앞쪽(틀어짐 {math.degrees(err):+.0f}°) → 미리 돌기 불필요")
            return True
        o = self.min_obstacle()
        if o is not None and o < PREROTATE_CLEARANCE:
            self.log(f"  주변이 좁음(가장 가까운 장애물 {o:.2f} m < {PREROTATE_CLEARANCE:.2f}) → 미리 돌기 생략(Nav2 에 맡김)")
            return True
        self.log(f"  복귀 경로가 {math.degrees(err):+.0f}° 쪽(장애물 {o if o is not None else float('nan'):.2f} m) → 먼저 제자리 회전")
        self.align_to_yaw(yaw_t, tol=PREROTATE_TOL, label="복귀 전 미리 돌기", settle=False)
        return not self.align_cancelled

    def write_status(self, state, place="", extra=None):
        """앱이 폴링할 상태 파일 갱신. moving / arrived / returning / aligning / idle
        extra: pose·목표·남은거리·진행률 등 실시간 정보(있으면 함께 기록)."""
        payload = {"state": state, "place": place, "updated_at": time.time()}
        if extra:
            payload.update(extra)
        tmp = STATUS_FILE.with_suffix(".json.tmp")
        try:
            STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, STATUS_FILE)   # 부분 기록을 앱이 읽지 않도록 원자적 교체
        except OSError as exc:
            self.log(f"상태 파일 기록 실패: {exc}")

    def write_return_request(self):
        """초기 위치로 복귀하는 요청 파일을 버스에 쓴다."""
        REQ_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = REQ_DIR / f"return_{stamp}.json"
        payload = {
            "place_name": HOME_ZONE,
            "source": RETURN_SOURCE,
            "requested_at": time.time(),
        }
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)          # 부분 기록 파일을 watcher가 읽지 않도록 원자적 교체
        self.seen_req.add(path.name)   # 우리가 쓴 것 → 새 요청으로 오인하지 않도록
        self.pending_return = path
        return path

    def discard_pending_return(self):
        """아직 처리되지 않은 우리 복귀 요청을 무효화한다.
        (Nav2가 이전 목표에 갇혀 있으면 요청이 nav_request/에 남는데, 그대로 두면
         한참 뒤 내비 재시작 시점에 로봇이 예고 없이 움직인다)"""
        p = self.pending_return
        self.pending_return = None
        if p is None or not p.exists():
            return
        try:
            p.rename(p.with_suffix(".json.stale"))   # 삭제 대신 보류(watcher는 *.json만 읽음)
            self.log(f"미처리 복귀 요청 무효화: {p.name} (예고 없는 이동 방지)")
        except OSError as exc:
            self.log(f"복귀 요청 정리 실패: {exc}")

    # ── 새 파일 감지 ────────────────────────────────────────────────────
    def poll_new_accepted(self):
        """nav_request_done/ 의 새 파일 → (place_name, source) 최신 1건."""
        cur = self._names(DONE_DIR)
        new = cur - self.seen_done
        self.seen_done = cur
        if not new:
            return None
        newest = max(new, key=lambda n: (DONE_DIR / n).stat().st_mtime
                     if (DONE_DIR / n).exists() else 0)
        name, source = read_place_name(DONE_DIR / newest)
        return (name, source) if name else None

    def poll_new_user_request(self):
        """nav_request/ 에 우리가 쓰지 않은 새 파일이 생겼는가(= 사용자 새 요청)."""
        cur = self._names(REQ_DIR)
        new = cur - self.seen_req
        self.seen_req = cur
        for n in new:
            _, source = read_place_name(REQ_DIR / n)
            if source != RETURN_SOURCE:
                return True
        return False

    def publish_live(self, state):
        """이동 중 실시간 정보(현재 pose·남은 거리·진행률)를 상태 파일에 갱신한다.
        앱은 이 진행률만으로 안내도 위 로봇 아이콘 위치를 정한다
        (안내도↔맵 좌표 변환은 하지 않는다 — 안내도가 축척도가 아니라 모식도이므로)."""
        pose = self.robot_pose()
        if pose is None or self.target_xy is None:
            return
        remaining = math.hypot(pose[0]-self.target_xy[0], pose[1]-self.target_xy[1])
        if self.initial_dist and self.initial_dist > 0.3:
            prog = 1.0 - remaining / self.initial_dist
        else:
            prog = 1.0 if remaining <= ARRIVE_RADIUS else 0.0
        prog = max(0.0, min(1.0, prog))
        self.max_progress = max(self.max_progress, prog)   # 단조 증가만
        self.write_status(state, self.target_name, {
            "pose": {"x": round(pose[0], 3), "y": round(pose[1], 3),
                     "yaw_deg": round(math.degrees(pose[2]), 2)},
            "goal": {"x": round(self.target_xy[0], 3), "y": round(self.target_xy[1], 3)},
            "remaining_m": round(remaining, 2),
            "progress": round(self.max_progress, 4),
        })

    # ── 상태 전이 ───────────────────────────────────────────────────────
    def start_tracking(self, name):
        xy = load_zone_goal(name)
        if xy is None:
            self.log(f"'{name}' 좌표를 찾을 수 없어 추적하지 않습니다.")
            self.state = IDLE
            self.write_status("idle")
            return
        self.target_name = name
        self.target_xy = xy
        self.track_started = time.time()
        # 진행률 = 1 - 남은거리/처음거리. 처음거리를 여기서 고정한다.
        pos = self.robot_xy()
        self.initial_dist = (math.hypot(pos[0]-xy[0], pos[1]-xy[1])
                             if pos else None)
        self.max_progress = 0.0   # 뒤로 가지 않게(직선거리는 일시적으로 늘 수 있음)
        if name == HOME_ZONE:
            self.state = RETURNING
            self.write_status("returning", name)
            self.log(f"복귀 이동 감지 → '{name}' 도착 대기")
        else:
            self.state = TRACKING
            self.write_status("moving", name)
            self.log(f"목적지 '{name}' 이동 감지 → 도착 감시 시작")

    def tick(self):
        # 1) 사용자 새 요청은 항상 최우선 — 대기/복귀를 즉시 취소
        if self.poll_new_user_request() and self.state in (DWELL, RETURNING):
            self.log("새 요청 감지 → 대기/복귀 취소하고 새 목적지 우선")
            self.state = IDLE
            self.write_status("idle")

        # 2) 새로 수락된 goal 이 있으면 그것을 추적 대상으로
        accepted = self.poll_new_accepted()
        if accepted:
            name, _ = accepted
            self.start_tracking(name)

        if self.state == IDLE:
            return

        # 2-b) 이동 중이면 실시간 진행률을 앱에 전달 (LIVE_STATUS_SEC 주기)
        if self.state in (TRACKING, RETURNING) and \
                time.time() - self.last_live >= LIVE_STATUS_SEC:
            self.last_live = time.time()
            self.publish_live("moving" if self.state == TRACKING else "returning")

        # 3) 도착 판정
        if self.state in (TRACKING, RETURNING):
            if time.time() - self.track_started > TRACK_TIMEOUT_SEC:
                self.log(f"'{self.target_name}' 도착이 확인되지 않아 감시를 종료합니다"
                         f"(제한 {TRACK_TIMEOUT_SEC:.0f}초).")
                self.discard_pending_return()
                self.state = IDLE
                self.write_status("idle")
                return
            pos = self.robot_xy()
            if pos is None:
                return
            dist = math.hypot(pos[0] - self.target_xy[0], pos[1] - self.target_xy[1])
            if dist <= ARRIVE_RADIUS:
                if self.state == RETURNING:
                    self.log(f"초기 위치 도착 (위치 오차 {dist:.2f}m)")
                    # Nav2는 yaw 허용오차 안이면 멈추므로, 여기서 TF를 보며
                    # 주차했던 방향과 동일해질 때까지 제자리 회전으로 마무리한다.
                    if ALIGN_ENABLE:
                        self.write_status("aligning", HOME_ZONE)
                        target_yaw = load_zone_yaw(HOME_ZONE)
                        if target_yaw is None:
                            self.log("초기 위치에 방향 정보가 없어 정렬을 건너뜁니다.")
                        else:
                            # 1차: amcl로 대략 정렬(뒤가 벽 쪽을 향하게)
                            self.align_to_yaw(target_yaw)
                            # 2차: 라이다로 벽과 정확히 수직 (amcl 오차 보정)
                            if WALL_ALIGN_ENABLE:
                                self.align_to_wall()
                    self.pending_return = None
                    self.state = IDLE
                    self.write_status("idle")
                else:
                    self.dwell_until = time.time() + RETURN_DELAY_SEC
                    self.state = DWELL
                    # ★ 앱이 이 상태를 보고 "XX에 도착했습니다"를 띄운다
                    self.write_status("arrived", self.target_name)
                    self.log(f"'{self.target_name}' 도착 (오차 {dist:.2f}m) → "
                             f"{RETURN_DELAY_SEC:.0f}초 뒤 복귀")
            return

        # 4) 대기 종료 → 복귀 요청
        if self.state == DWELL and time.time() >= self.dwell_until:
            if load_zone_goal(HOME_ZONE) is None:
                self.log("복귀 좌표가 없어 복귀하지 않습니다.")
                self.state = IDLE
                return
            if PREROTATE_ENABLE:
                self.write_status("returning", HOME_ZONE)
                if not self.face_return_path():
                    self.state = IDLE                      # 사용자 새 요청 → 복귀 안 함(새 목적지는 다음 tick 에서)
                    return
            path = self.write_return_request()
            self.log(f"초기 위치로 복귀 요청: {path.name}")
            self.start_tracking(HOME_ZONE)


def main():
    rclpy.init()
    node = ReturnHomeWatcher()
    # 2026-11-13: 수신(TF·스캔 콜백)은 백그라운드 스레드에서 계속 처리. 예전엔 루프마다 spin_once 로 '한 건'만
    #  처리하고 0.05초 쉬어 초당 약 10건만 소화 → TF 가 밀려 몇 초 전 방향을 읽음 → 정렬이 ±60° 씩 지나쳤다 되돌아옴.
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    threading.Thread(target=executor.spin, daemon=True).start()
    try:
        while rclpy.ok():
            time.sleep(POLL_SEC)
            node.tick()
    except KeyboardInterrupt:
        node.log("종료")
    finally:
        try:
            node.stop_robot()      # 정렬 중 종료되어도 로봇이 계속 돌지 않도록
        except Exception:
            pass
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
