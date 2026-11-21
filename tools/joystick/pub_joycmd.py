#!/usr/bin/env python3
import socket
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def piecewise_unit(
    delta_raw: float,
    dead_raw: float,
    mid_delta_raw: float,
    mid_unit: float,
    max_delta_raw: float
) -> float:
    sign = 1.0 if delta_raw >= 0.0 else -1.0
    a = abs(delta_raw)

    if a <= dead_raw:
        return 0.0

    if a >= max_delta_raw:
        return sign * 1.0

    mid_unit = clamp(mid_unit, 0.0, 1.0)
    mid_delta_raw = clamp(
        mid_delta_raw,
        dead_raw + 1e-6,
        max_delta_raw - 1e-6
    )

    if a <= mid_delta_raw:
        u = (
            mid_unit
            * (a - dead_raw)
            / (mid_delta_raw - dead_raw)
        )
    else:
        u = (
            mid_unit
            + (1.0 - mid_unit)
            * (a - mid_delta_raw)
            / (max_delta_raw - mid_delta_raw)
        )

    return sign * clamp(u, 0.0, 1.0)


def tilt_unit(
    delta_raw: float,
    dead_raw: float,
    sat_delta_raw: float,
    expo: float = 1.0
) -> float:
    a = abs(delta_raw)

    if a <= dead_raw:
        return 0.0

    sign = 1.0 if delta_raw >= 0.0 else -1.0
    sat = max(abs(sat_delta_raw), dead_raw + 1e-6)

    t = (a - dead_raw) / (sat - dead_raw)
    t = clamp(t, 0.0, 1.0)

    expo = max(expo, 1e-6)
    u = t ** expo

    return sign * u


def ramp_update(
    cur: float,
    target: float,
    a_up: float,
    a_down: float,
    dt: float
) -> float:
    if dt <= 0.0:
        return cur

    accel = (
        (abs(target) > abs(cur))
        and (
            (cur * target) >= 0.0
            or abs(cur) < 1e-9
        )
    )

    a = a_up if accel else a_down

    dmax = a * dt

    return cur + clamp(
        target - cur,
        -dmax,
        dmax
    )


class BtJoyCmd(Node):

    def __init__(self):
        super().__init__("bt_joycmd")

        self.addr = self.declare_parameter(
            "addr",
            "08:3A:F2:B8:F7:6A"
        ).value

        self.channel = int(
            self.declare_parameter(
                "channel",
                1
            ).value
        )

        self.raw_min = float(
            self.declare_parameter(
                "raw_min",
                0.0
            ).value
        )

        self.raw_max = float(
            self.declare_parameter(
                "raw_max",
                1023.0
            ).value
        )

        self.half_range = (
            self.raw_max - self.raw_min
        ) / 2.0

        self.max_v = float(
            self.declare_parameter(
                "max_v",
                0.5   # 2026-11-15: 6.0→0.5 실제 m/s(속도 보정 후 명령=실제, 드라이버 안전 상한 0.5)
            ).value
        )

        self.max_w = float(
            self.declare_parameter(
                "max_w",
                0.75  # 2026-11-15: 3.0→0.75 실제 rad/s
            ).value
        )

        self.map_mode = str(
            self.declare_parameter(
                "map_mode",
                "tilt"
            ).value
        ).lower()

        self.mid_delta = float(
            self.declare_parameter(
                "mid_delta",
                200.0
            ).value
        )

        self.mid_v = float(
            self.declare_parameter(
                "mid_v",
                0.25  # 2026-11-15: 3.0→0.25(max_v 의 절반 비율 유지)
            ).value
        )

        self.mid_w = float(
            self.declare_parameter(
                "mid_w",
                0.25  # 2026-11-15: 1.0→0.25(max_w 의 1/3 비율 유지)
            ).value
        )

        self.deadzone = float(
            self.declare_parameter(
                "deadzone",
                0.08
            ).value
        )

        self.deadzone_raw = float(
            self.declare_parameter(
                "deadzone_raw",
                45.0
            ).value
        )

        self.sat_delta_v = float(
            self.declare_parameter(
                "sat_delta_v",
                self.half_range
            ).value
        )

        self.sat_delta_w = float(
            self.declare_parameter(
                "sat_delta_w",
                self.half_range
            ).value
        )

        self.expo_v = float(
            self.declare_parameter(
                "expo_v",
                2.2
            ).value
        )

        self.expo_w = float(
            self.declare_parameter(
                "expo_w",
                2.0
            ).value
        )

        self.expo_v_rev = float(
            self.declare_parameter(
                "expo_v_rev",
                2.8
            ).value
        )

        self.stale_timeout = float(
            self.declare_parameter(
                "stale_timeout",
                0.3
            ).value
        )

        self.pub_hz = float(
            self.declare_parameter(
                "pub_hz",
                30.0
            ).value
        )

        self.ramp_time_up_v = float(
            self.declare_parameter(
                "ramp_time_up_v",
                0.6
            ).value
        )

        self.ramp_time_down_v = float(
            self.declare_parameter(
                "ramp_time_down_v",
                0.25
            ).value
        )

        self.ramp_time_up_w = float(
            self.declare_parameter(
                "ramp_time_up_w",
                0.5
            ).value
        )

        self.ramp_time_down_w = float(
            self.declare_parameter(
                "ramp_time_down_w",
                0.2
            ).value
        )

        self.a_lin = (
            self.max_v
            / max(self.ramp_time_up_v, 1e-6)
        )

        self.a_lin_down = (
            self.max_v
            / max(self.ramp_time_down_v, 1e-6)
        )

        self.a_ang = (
            self.max_w
            / max(self.ramp_time_up_w, 1e-6)
        )

        self.a_ang_down = (
            self.max_w
            / max(self.ramp_time_down_w, 1e-6)
        )

        self.w_reduce_with_fwd = float(
            self.declare_parameter(
                "w_reduce_with_fwd",
                0.6
            ).value
        )

        self.v_reduce_with_turn = float(
            self.declare_parameter(
                "v_reduce_with_turn",
                0.4
            ).value
        )

        self.rev_scale = float(
            self.declare_parameter(
                "rev_scale",
                1.0
            ).value
        )

        self.stop_snap_ratio = float(
            self.declare_parameter(
                "stop_snap_ratio",
                0.03
            ).value
        )

        self.invert_fwd = bool(
            self.declare_parameter(
                "invert_fwd",
                True
            ).value
        )

        self.pub = self.create_publisher(
            Twist,
            "/cmd_vel_joy",   # 2026-11-15: 조이스틱 전용 통로(빠른 정지·Nav2 보다 우선)
            10
        )

        self.sock = None
        self.buf = b""

        self.center_x = None
        self.center_y = None

        self.calib_samples = []
        self.calib_needed = 25

        self.turn = 0.0
        self.fwd = 0.0
        self.last_input_time = 0.0

        self.v = 0.0
        self.w = 0.0

        # 수동 입력 상태 추적
        self.manual_active = False
        self.zero_sent_after_release = False

        self.get_logger().info(
            f"BT RFCOMM target: "
            f"{self.addr} ch={self.channel} | "
            f"map_mode={self.map_mode} "
            f"max_v={self.max_v} "
            f"max_w={self.max_w} "
            f"sat_v={self.sat_delta_v:.1f} "
            f"sat_w={self.sat_delta_w:.1f} "
            f"expo_v={self.expo_v} "
            f"expo_v_rev={self.expo_v_rev} "
            f"expo_w={self.expo_w}"
        )

        self.create_timer(
            0.01,
            self.poll_bt
        )

        self.last_pub_t = time.time()

        self.create_timer(
            1.0 / self.pub_hz,
            self.publish_cmd
        )

    def connect(self):
        if self.sock:
            return

        s = socket.socket(
            socket.AF_BLUETOOTH,
            socket.SOCK_STREAM,
            socket.BTPROTO_RFCOMM
        )

        s.settimeout(10.0)

        s.connect(
            (
                self.addr,
                self.channel
            )
        )

        s.settimeout(0.0)

        self.sock = s
        self.buf = b""

        self.get_logger().info(
            "BT connected (RFCOMM socket)"
        )

    def close(self):
        try:
            if self.sock:
                self.sock.close()

        except Exception:
            pass

        self.sock = None

    def parse_line(self, line: str):
        parts = line.strip().split(",")

        if len(parts) < 2:
            return

        try:
            x = float(parts[0])
            y = float(parts[1])

        except ValueError:
            return

        if (
            self.center_x is None
            or self.center_y is None
        ):
            self.calib_samples.append(
                (
                    x,
                    y
                )
            )

            if (
                len(self.calib_samples)
                >= self.calib_needed
            ):
                self.center_x = (
                    sum(
                        p[0]
                        for p in self.calib_samples
                    )
                    / len(self.calib_samples)
                )

                self.center_y = (
                    sum(
                        p[1]
                        for p in self.calib_samples
                    )
                    / len(self.calib_samples)
                )

                self.get_logger().info(
                    f"Calibrated center: "
                    f"({self.center_x:.1f}, "
                    f"{self.center_y:.1f})"
                )

            return

        dx = x - self.center_x
        dy = y - self.center_y

        dead_raw = (
            self.deadzone_raw
            if self.deadzone_raw > 0
            else (
                abs(self.deadzone)
                * self.half_range
            )
        )

        if self.map_mode == "tilt":
            sat_v = max(
                min(
                    self.sat_delta_v,
                    self.half_range
                ),
                dead_raw + 1.0
            )

            sat_w = max(
                min(
                    self.sat_delta_w,
                    self.half_range
                ),
                dead_raw + 1.0
            )

            self.turn = tilt_unit(
                dx,
                dead_raw,
                sat_w,
                self.expo_w
            )

            fwd_delta = (
                -dy
                if self.invert_fwd
                else dy
            )

            expo_fwd = (
                self.expo_v_rev
                if fwd_delta < 0.0
                else self.expo_v
            )

            self.fwd = tilt_unit(
                fwd_delta,
                dead_raw,
                sat_v,
                expo_fwd
            )

        else:
            max_delta_raw = self.half_range

            mid_v_unit = (
                self.mid_v / self.max_v
                if self.max_v != 0
                else 0.0
            )

            mid_w_unit = (
                self.mid_w / self.max_w
                if self.max_w != 0
                else 0.0
            )

            self.turn = piecewise_unit(
                dx,
                dead_raw,
                self.mid_delta,
                mid_w_unit,
                max_delta_raw
            )

            fwd_delta = (
                -dy
                if self.invert_fwd
                else dy
            )

            self.fwd = piecewise_unit(
                fwd_delta,
                dead_raw,
                self.mid_delta,
                mid_v_unit,
                max_delta_raw
            )

        self.last_input_time = time.time()

    def poll_bt(self):
        try:
            if self.sock is None:
                self.connect()

            try:
                data = self.sock.recv(256)

                if not data:
                    raise ConnectionError(
                        "BT disconnected (empty recv)"
                    )

                self.buf += data

            except BlockingIOError:
                return

            while b"\n" in self.buf:
                line, self.buf = self.buf.split(
                    b"\n",
                    1
                )

                self.parse_line(
                    line.decode(
                        errors="ignore"
                    )
                )

        except Exception as e:
            self.get_logger().warn(
                f"BT error: {e}"
            )

            self.close()

            time.sleep(0.1)

    def publish_cmd(self):
        now = time.time()

        dt = now - self.last_pub_t
        self.last_pub_t = now

        if dt <= 0.0:
            return

        if (
            now - self.last_input_time
        ) > self.stale_timeout:
            v_t = 0.0
            w_t = 0.0

        else:
            v_t = (
                self.max_v
                * self.fwd
            )

            w_t = (
                self.max_w
                * self.turn
            )

            v_t *= max(
                0.0,
                1.0
                - self.v_reduce_with_turn
                * abs(self.turn)
            )

            w_t *= max(
                0.0,
                1.0
                - self.w_reduce_with_fwd
                * abs(self.fwd)
            )

            if v_t < 0.0:
                v_t *= self.rev_scale

        self.v = ramp_update(
            self.v,
            v_t,
            self.a_lin,
            self.a_lin_down,
            dt
        )

        self.w = ramp_update(
            self.w,
            w_t,
            self.a_ang,
            self.a_ang_down,
            dt
        )

        v_snap = (
            abs(self.max_v)
            * self.stop_snap_ratio
        )

        w_snap = (
            abs(self.max_w)
            * self.stop_snap_ratio
        )

        if (
            abs(v_t) < 1e-9
            and abs(self.v) < v_snap
        ):
            self.v = 0.0

        if (
            abs(w_t) < 1e-9
            and abs(self.w) < w_snap
        ):
            self.w = 0.0

        msg = Twist()

        msg.linear.x = float(self.v)
        msg.angular.z = float(self.w)

        is_zero_cmd = (
            abs(self.v) < 1e-6
            and abs(self.w) < 1e-6
        )

        # 수동 입력이 살아있을 때
        if not is_zero_cmd:
            self.pub.publish(msg)

            self.manual_active = True
            self.zero_sent_after_release = False

            return

        # 여기부터는 0,0 상태
        # 이전에 수동 주행 중이었다면
        # release 시점에만 정지 1회 publish
        if (
            self.manual_active
            and not self.zero_sent_after_release
        ):
            self.pub.publish(msg)

            self.zero_sent_after_release = True
            self.manual_active = False

            return

        # 그 외에는 0 반복 publish 안 함
        return


def main():
    rclpy.init()

    node = BtJoyCmd()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    node.close()
    node.destroy_node()

    rclpy.shutdown()


if __name__ == "__main__":
    main()
