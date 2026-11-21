#!/usr/bin/env python3
# =========================================================================
# fake_robot.py — 실험 2 시뮬레이션용 '가짜 로봇 몸체 + 라이다' (실제 Nav2·감시기 코드는 그대로 씀)
#
#   하는 일: /cmd_vel 을 받아 차동 구동 로봇을 움직이고(실제 모터 드라이버와 같은 가감속 제한·안전 상한·명령 끊김 정지),
#            /odom + TF(odom→base_footprint), 지도 기반 가상 라이다 /scan_multi, 실제 위치 /sim/ground_truth 를 낸다.
#   현실 반영: 명령→바퀴 반응 지연 0.25초(실측), 바퀴 오도메트리 오차(배율·잡음), 라이다 거리 잡음,
#             제자리 회전 정지 마찰(작은 회전 명령은 안 돎).
#   ※ 바닥 슬립·사람·문 같은 움직이는 장애물은 없다(지도 = 세계). 결과는 '이상에 가까운 조건'의 상한으로 해석.
# =========================================================================
import math
import random
import sys

import numpy as np
import rclpy
import yaml
from geometry_msgs.msg import PoseStamped, TransformStamped, Twist
from nav_msgs.msg import Odometry
from PIL import Image
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from tf2_ros import StaticTransformBroadcaster, TransformBroadcaster


def yaw_q(yaw):
    return 0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)


class FakeRobot(Node):
    def __init__(self):
        super().__init__("fake_robot")
        p = self.declare_parameter
        map_yaml = p("map_yaml", "").value
        self.x, self.y, self.th = p("x", 0.0).value, p("y", 0.0).value, p("yaw", 0.0).value
        # 실제 roboteq 드라이버(query.yaml) 값
        self.acc_v, self.dec_v = p("max_lin_acc", 0.25).value, p("max_lin_dec", 0.3).value
        self.acc_w, self.dec_w = p("max_ang_acc", 1.5).value, p("max_ang_dec", 2.0).value
        self.cap_v, self.cap_w = p("max_lin_vel", 0.5).value, p("max_ang_vel", 1.0).value
        self.cmd_timeout = p("cmd_timeout", 0.5).value
        # 명령 → 바퀴 반응 지연(실제 로봇 실측값: 회전 제어기 rotate_ctl.py 의 latency=0.25 초)
        self.cmd_delay = p("cmd_delay", 0.25).value
        self.cmd_buf = []                                         # (도착 시각, v, w)
        self.deadband_w = p("rot_deadband", 0.04).value          # 제자리 회전 정지 마찰(실측: 0.02 rad/s 명령엔 안 돎)
        self.odom_scale = 1.0 + p("odom_scale_err", 0.01).value  # 바퀴 오도메트리 배율 오차
        self.odom_noise = p("odom_noise", 0.01).value            # 속도 잡음(상대)
        self.range_noise = p("range_noise", 0.01).value
        self.range_max, self.beams = p("range_max", 12.0).value, int(p("beams", 360).value)
        seed = int(p("seed", 1).value)
        random.seed(seed)
        self.rng = np.random.default_rng(seed)

        # 지도 → 점유 격자(벽 = True)
        with open(map_yaml) as f:
            m = yaml.safe_load(f)
        img_path = m["image"] if m["image"].startswith("/") else map_yaml.rsplit("/", 1)[0] + "/" + m["image"]
        img = np.array(Image.open(img_path).convert("L"), dtype=np.float32)
        occ = (255.0 - img) / 255.0 if not m.get("negate", 0) else img / 255.0
        self.grid = np.flipud(occ > m.get("occupied_thresh", 0.65))   # [row=y, col=x], 원점 아래
        self.res = float(m["resolution"])
        self.ox, self.oy = float(m["origin"][0]), float(m["origin"][1])
        self.h, self.w = self.grid.shape
        self.ang = np.linspace(-math.pi, math.pi, self.beams, endpoint=False)
        self.steps = np.arange(0.15, self.range_max, self.res / 2.0)

        # 오도메트리 좌표(odom)는 시작 위치에서 0
        self.ox_odom = self.oy_odom = self.th_odom = 0.0
        self.v = self.w_ = 0.0
        self.cmd_v = self.cmd_w = 0.0
        self.cmd_t = -1e9

        self.tfb = TransformBroadcaster(self)
        st = StaticTransformBroadcaster(self)
        st.sendTransform([self._tf("base_footprint", "base_link", 0, 0, 0, 0),
                          self._tf("base_footprint", "laser_sim", 0, 0, 0.2, 0)])
        self.odom_pub = self.create_publisher(Odometry, "/odom", 10)
        self.scan_pub = self.create_publisher(LaserScan, "/scan_multi", 10)
        self.gt_pub = self.create_publisher(PoseStamped, "/sim/ground_truth", 10)
        self.create_subscription(Twist, "/cmd_vel", self.on_cmd, 10)
        # '사람이 로봇을 옮겨 놓기' 흉내(도착 실패 시 목적지로 옮겨 복귀 시험): 실제 위치만 바꾼다(오도메트리는 그대로)
        self.create_subscription(PoseStamped, "/sim/teleport", self.on_teleport, 10)
        self.dt = 0.02
        self.create_timer(self.dt, self.step)
        self.create_timer(0.1, self.publish_scan)
        self.get_logger().info(f"가짜 로봇 시작 ({self.x:.2f}, {self.y:.2f}, {math.degrees(self.th):.1f}°) · "
                               f"지도 {self.w}×{self.h} · 회전 정지마찰 {self.deadband_w} rad/s")

    def _tf(self, parent, child, x, y, z, yaw, stamp=None):
        t = TransformStamped()
        t.header.stamp = stamp or self.get_clock().now().to_msg()
        t.header.frame_id, t.child_frame_id = parent, child
        t.transform.translation.x, t.transform.translation.y, t.transform.translation.z = float(x), float(y), float(z)
        q = yaw_q(yaw)
        t.transform.rotation.x, t.transform.rotation.y, t.transform.rotation.z, t.transform.rotation.w = q
        return t

    def on_cmd(self, msg):
        v = max(-self.cap_v, min(self.cap_v, msg.linear.x))
        w = max(-self.cap_w, min(self.cap_w, msg.angular.z))
        self.cmd_buf.append((self.get_clock().now().nanoseconds * 1e-9, v, w))

    def _apply_delayed(self, t):
        """지연(cmd_delay)이 지난 명령만 '도착한 명령'으로 반영."""
        while self.cmd_buf and t - self.cmd_buf[0][0] >= self.cmd_delay:
            t0, self.cmd_v, self.cmd_w = self.cmd_buf.pop(0)
            self.cmd_t = t0 + self.cmd_delay

    def on_teleport(self, msg):
        q = msg.pose.orientation
        self.x, self.y = msg.pose.position.x, msg.pose.position.y
        self.th = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        self.v = self.w_ = 0.0
        self.get_logger().info(f"옮김 → ({self.x:.2f}, {self.y:.2f}, {math.degrees(self.th):.1f}°)")

    @staticmethod
    def _ramp(cur, tgt, acc, dec, dt):
        lim = (acc if abs(tgt) > abs(cur) and cur * tgt >= 0 else dec) * dt
        return cur + max(-lim, min(lim, tgt - cur))

    def step(self):
        now = self.get_clock().now()
        t = now.nanoseconds * 1e-9
        self._apply_delayed(t)
        tv, tw = (self.cmd_v, self.cmd_w) if t - self.cmd_t < self.cmd_timeout else (0.0, 0.0)
        self.v = self._ramp(self.v, tv, self.acc_v, self.dec_v, self.dt)
        self.w_ = self._ramp(self.w_, tw, self.acc_w, self.dec_w, self.dt)
        w_act = 0.0 if (abs(self.v) < 0.02 and abs(self.w_) < self.deadband_w) else self.w_   # 정지 마찰
        # 실제 움직임
        self.x += self.v * math.cos(self.th) * self.dt
        self.y += self.v * math.sin(self.th) * self.dt
        self.th = math.atan2(math.sin(self.th + w_act * self.dt), math.cos(self.th + w_act * self.dt))
        # 바퀴가 잰 움직임(오차 포함)
        vo = self.v * self.odom_scale * (1 + self.odom_noise * self.rng.standard_normal())
        wo = w_act * self.odom_scale * (1 + self.odom_noise * self.rng.standard_normal())
        self.ox_odom += vo * math.cos(self.th_odom) * self.dt
        self.oy_odom += vo * math.sin(self.th_odom) * self.dt
        self.th_odom = math.atan2(math.sin(self.th_odom + wo * self.dt), math.cos(self.th_odom + wo * self.dt))
        stamp = now.to_msg()
        self.tfb.sendTransform(self._tf("odom", "base_footprint", self.ox_odom, self.oy_odom, 0.0, self.th_odom, stamp))
        o = Odometry()
        o.header.stamp, o.header.frame_id, o.child_frame_id = stamp, "odom", "base_footprint"
        o.pose.pose.position.x, o.pose.pose.position.y = self.ox_odom, self.oy_odom
        q = yaw_q(self.th_odom)
        o.pose.pose.orientation.x, o.pose.pose.orientation.y, o.pose.pose.orientation.z, o.pose.pose.orientation.w = q
        o.twist.twist.linear.x, o.twist.twist.angular.z = vo, wo
        self.odom_pub.publish(o)
        g = PoseStamped()
        g.header.stamp, g.header.frame_id = stamp, "map"
        g.pose.position.x, g.pose.position.y = self.x, self.y
        q = yaw_q(self.th)
        g.pose.orientation.x, g.pose.orientation.y, g.pose.orientation.z, g.pose.orientation.w = q
        self.gt_pub.publish(g)

    def publish_scan(self):
        a = self.th + self.ang[:, None]
        xs = self.x + np.cos(a) * self.steps[None, :]
        ys = self.y + np.sin(a) * self.steps[None, :]
        cx = ((xs - self.ox) / self.res).astype(np.int32)
        cy = ((ys - self.oy) / self.res).astype(np.int32)
        inside = (cx >= 0) & (cx < self.w) & (cy >= 0) & (cy < self.h)
        hit = np.zeros_like(inside)
        hit[inside] = self.grid[cy[inside], cx[inside]]
        first = np.where(hit.any(axis=1), hit.argmax(axis=1), -1)
        r = np.where(first >= 0, self.steps[np.clip(first, 0, None)], np.inf)
        r = np.where(np.isfinite(r), r + self.range_noise * self.rng.standard_normal(r.shape), r)
        s = LaserScan()
        s.header.stamp, s.header.frame_id = self.get_clock().now().to_msg(), "laser_sim"
        s.angle_min, s.angle_max = float(self.ang[0]), float(self.ang[-1])
        s.angle_increment = float(self.ang[1] - self.ang[0])
        s.scan_time, s.time_increment = 0.1, 0.0
        s.range_min, s.range_max = 0.15, float(self.range_max)
        s.ranges = [float(v) for v in r]
        self.scan_pub.publish(s)


def main():
    rclpy.init(args=sys.argv)
    n = FakeRobot()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        n.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
