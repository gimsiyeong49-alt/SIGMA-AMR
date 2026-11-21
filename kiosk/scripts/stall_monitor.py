#!/usr/bin/env python3
# =========================================================================
# stall_monitor.py — AGV 스톨(캐스터 꼬임/구동륜 슬립) "감지·로그 전용" 노드
#
#   ★ 모터에 절대 명령하지 않는다(순수 관찰자). cmd_vel 발행 없음.
#   목적: "언제·어디서 스톨이 걸리는지 + 그때 전류/IMU/odom 값"을 기록해
#         (1) 신호가 실제로 나오는지 검증하고 (2) 탈출 임계값을 잡는다.
#         → 이 데이터를 본 뒤 Nav2 복구 튜닝/탈출 동작을 활성화한다.
#
#   판정 원리:
#     · 명령 있음      = /cmd_vel 이 신선(<CMD_STALE초)하고 v/ω가 최소치 이상
#     · 실제 안 움직임 = IMU 각속도(슬립 무관)와 융합 odom 속도가 모두 하한 미만
#     · 둘이 STALL_SEC 지속 → '스톨'로 기록
#     · 분류 힌트: 전류 높음=꼬임(jam) / 엔코더는 도는데 실제 정지=슬립(slip)
#
#   실행(ROS 환경 소스 후):
#     python3 scripts/stall_monitor.py
#   로그: logs/stall_monitor.log(전체), logs/stall_events.log(이벤트만)
#
#   환경변수(임계값 튜닝):
#     CMD_V_MIN CMD_W_MIN ACT_V_MIN ACT_W_MIN STALL_SEC CMD_STALE AMPS_JAM_HINT
# =========================================================================
import os
import time
import math
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Imu
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist
try:
    from roboteq_interfaces.msg import ChannelValues
    HAS_AMPS_MSG = True
except Exception:
    HAS_AMPS_MSG = False

# ---- 임계값 (환경변수로 덮어쓰기 가능) ----
CMD_V_MIN = float(os.environ.get("CMD_V_MIN", "0.03"))   # 유효 병진 명령 하한 [m/s]
CMD_W_MIN = float(os.environ.get("CMD_W_MIN", "0.05"))   # 유효 회전 명령 하한 [rad/s]
ACT_V_MIN = float(os.environ.get("ACT_V_MIN", "0.02"))   # 실제 병진 하한 [m/s]
ACT_W_MIN = float(os.environ.get("ACT_W_MIN", "0.03"))   # 실제 회전 하한 [rad/s]
STALL_SEC = float(os.environ.get("STALL_SEC", "1.5"))    # 스톨로 인정할 지속시간 [s]
CMD_STALE = float(os.environ.get("CMD_STALE", "0.5"))    # cmd_vel 신선도 한계 [s]
AMPS_JAM_HINT = float(os.environ.get("AMPS_JAM_HINT", "20"))  # 꼬임 분류 힌트(|amps|합)

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
LOG_DIR.mkdir(exist_ok=True)
EVENTS_FILE = LOG_DIR / "stall_events.log"


class StallMonitor(Node):
    def __init__(self):
        super().__init__("stall_monitor")
        be = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT,
                        history=HistoryPolicy.KEEP_LAST)
        # 최신 값 + 수신시각
        self.cmd = (0.0, 0.0); self.cmd_t = 0.0
        self.imu_wz = 0.0; self.imu_t = 0.0
        self.filt = (0.0, 0.0); self.filt_t = 0.0
        self.odom = (0.0, 0.0); self.odom_t = 0.0
        self.amps = [0, 0]; self.amps_t = 0.0

        self.create_subscription(Twist, "/cmd_vel", self._cmd, be)
        self.create_subscription(Imu, "/imu/data", self._imu, be)
        self.create_subscription(Odometry, "/odometry/filtered", self._filt, be)
        self.create_subscription(Odometry, "/odom", self._odom, be)
        if HAS_AMPS_MSG:
            self.create_subscription(ChannelValues, "/motor_amps", self._amps, be)

        # 스톨 상태
        self.stall_start = None
        self.flagged = False
        self.peak_amps = 0.0
        self.stall_count = 0
        self.last_heartbeat = time.time()
        self.start_time = time.time()
        self.checked_signals = False

        self.timer = self.create_timer(0.05, self._tick)   # 20 Hz
        self._log("── stall_monitor 시작 (감지·로그 전용, 모터 명령 없음) ──")
        self._log(f"   임계값 cmd(v≥{CMD_V_MIN},ω≥{CMD_W_MIN}) act(v<{ACT_V_MIN},ω<{ACT_W_MIN}) "
                  f"지속≥{STALL_SEC}s / amps_jam_hint={AMPS_JAM_HINT}")

    # ---- 콜백 ----
    def _cmd(self, m):  self.cmd = (m.linear.x, m.angular.z); self.cmd_t = time.time()
    def _imu(self, m):  self.imu_wz = m.angular_velocity.z; self.imu_t = time.time()
    def _filt(self, m): self.filt = (m.twist.twist.linear.x, m.twist.twist.angular.z); self.filt_t = time.time()
    def _odom(self, m): self.odom = (m.twist.twist.linear.x, m.twist.twist.angular.z); self.odom_t = time.time()
    def _amps(self, m): self.amps = list(m.value); self.amps_t = time.time()

    def _log(self, msg, event=False):
        line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg
        print(line, flush=True)
        if event:
            try:
                with open(EVENTS_FILE, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass

    def _amps_abs(self):
        return sum(abs(int(a)) for a in self.amps) if self.amps else 0.0

    def _tick(self):
        now = time.time()

        # 시작 3초 후 신호 가용성 1회 점검
        if not self.checked_signals and now - self.start_time > 3.0:
            self.checked_signals = True
            avail = []
            for name, t in [("cmd_vel", self.cmd_t), ("imu/data", self.imu_t),
                            ("odometry/filtered", self.filt_t), ("odom", self.odom_t),
                            ("motor_amps", self.amps_t)]:
                avail.append(f"{name}={'OK' if t > 0 else '없음'}")
            self._log("신호 가용성: " + ", ".join(avail))
            if self.imu_t == 0 and self.filt_t == 0:
                self._log("⚠ IMU/융합odom 둘 다 없음 → 실제움직임 판정 불가. 토픽 확인 필요.")

        cmd_v, cmd_w = self.cmd
        cmd_fresh = (now - self.cmd_t) < CMD_STALE and self.cmd_t > 0
        commanded = cmd_fresh and (abs(cmd_v) >= CMD_V_MIN or abs(cmd_w) >= CMD_W_MIN)

        # 실제 움직임: IMU 회전(슬립무관) 또는 융합 odom 속도
        act_moving = (abs(self.imu_wz) >= ACT_W_MIN or
                      abs(self.filt[0]) >= ACT_V_MIN or abs(self.filt[1]) >= ACT_W_MIN)
        # 엔코더(원본 odom) 움직임 — 슬립 판별용(엔코더는 도는데 실제 정지)
        enc_moving = abs(self.odom[0]) >= ACT_V_MIN or abs(self.odom[1]) >= ACT_W_MIN

        if commanded and not act_moving:
            amps_abs = self._amps_abs()
            if self.stall_start is None:
                self.stall_start = now
                self.peak_amps = amps_abs
            else:
                self.peak_amps = max(self.peak_amps, amps_abs)
                if (now - self.stall_start) >= STALL_SEC and not self.flagged:
                    self.flagged = True
                    self.stall_count += 1
                    kind = ("회전" if abs(cmd_w) >= abs(cmd_v) * 2 else
                            "병진" if abs(cmd_v) >= abs(cmd_w) * 2 else "복합")
                    if amps_abs >= AMPS_JAM_HINT:
                        cls = "꼬임(jam·전류높음)"
                    elif enc_moving:
                        cls = "슬립(엔코더는 회전, 실제 정지)"
                    else:
                        cls = "정지(전류낮음·엔코더도 정지)"
                    self._log(
                        f"🛑 스톨#{self.stall_count} [{kind}/{cls}] "
                        f"cmd(v={cmd_v:+.3f},ω={cmd_w:+.3f}) "
                        f"실제 imuω={self.imu_wz:+.3f} filt(v={self.filt[0]:+.3f},ω={self.filt[1]:+.3f}) "
                        f"enc(v={self.odom[0]:+.3f},ω={self.odom[1]:+.3f}) "
                        f"amps={self.amps}(|Σ|={amps_abs:.0f})", event=True)
        else:
            if self.flagged:
                dur = now - self.stall_start
                how = "실제 움직임 재개" if act_moving else "명령 해제"
                self._log(f"✅ 스톨#{self.stall_count} 해소({how}) · 지속 {dur:.1f}s "
                          f"peak|amps|={self.peak_amps:.0f}", event=True)
            self.stall_start = None
            self.flagged = False

        # 60초 하트비트(저소음)
        if now - self.last_heartbeat >= 60.0:
            self.last_heartbeat = now
            self._log(f"… 감시 중 (누적 스톨 {self.stall_count}회)")


def main():
    rclpy.init()
    node = StallMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
