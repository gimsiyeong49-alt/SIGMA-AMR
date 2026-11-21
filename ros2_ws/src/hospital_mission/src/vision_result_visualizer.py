#!/usr/bin/env python3
import math
import os
import time
from typing import List, Optional

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan, Image

import torch
import torch.nn.functional as F
from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation


MODEL_ID = "nvidia/segformer-b1-finetuned-ade-512-512"

CAMERA_DEV_CANDIDATES: List[str] = [
    "/dev/v4l/by-id/usb-STsmart_HD_4MP_WEBCAM_USB-video-index0",
    "/dev/v4l/by-id/usb-STsmart_HD_4MP_WEBCAM_USB-video-index1",
    "/dev/v4l/by-id/usb-HD_Web_Camera_HD_Web_Camera_Ucamera001-video-index0",
    "/dev/v4l/by-id/usb-HD_Web_Camera_HD_Web_Camera_Ucamera001-video-index1",
    "/dev/video0",
    "/dev/video1",
    "/dev/video2",
]

CAP_WIDTH = 640
CAP_HEIGHT = 480
INPUT_SIZE = 256
PROCESS_EVERY_N_FRAMES = 2

CAM_HFOV_DEG = 70.0
IMG_WIDTH = 640

# 기존 vision_obstacle_node.py 값과 동일하게 시작
FRONT_SCAN_RAW_DEG = -90.0  # /scan_multi에서 로봇 정면 raw 각도 기준
LIDAR_CAM_ANGLE_OFFSET_DEG = -95.0

PERSON_PIXEL_MIN_RATIO = 0.04
PERSON_MIN_DIST = 0.3
PERSON_MAX_DIST = 4.5

DEBUG_TOPIC = "/vision_result/image"
SAVE_DIR = "/mnt/ssd/cart_ros2/result_outputs"
SAVE_INTERVAL_SEC = 2.0


def pick_device():
    return torch.device("cuda:0") if torch.cuda.is_available() else torch.device("cpu")


def open_camera():
    for dev in CAMERA_DEV_CANDIDATES:
        cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            continue

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAP_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAP_HEIGHT)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

        ret, frame = cap.read()
        if ret and frame is not None:
            print(f"[CAMERA] opened: {dev}, shape={frame.shape}")
            return cap

        cap.release()

    raise RuntimeError("카메라 열기 실패")


def cv2_to_imgmsg_bgr8(img, frame_id, stamp):
    msg = Image()
    msg.header.frame_id = frame_id
    msg.header.stamp = stamp
    msg.height = int(img.shape[0])
    msg.width = int(img.shape[1])
    msg.encoding = "bgr8"
    msg.is_bigendian = False
    msg.step = int(msg.width * 3)
    msg.data = np.ascontiguousarray(img).tobytes()
    return msg



def normalize_deg(a: float) -> float:
    while a > 180.0:
        a -= 360.0
    while a < -180.0:
        a += 360.0
    return a

class VisionResultVisualizer(Node):
    def __init__(self):
        super().__init__("vision_result_visualizer")
        self.get_logger().info("VisionResultVisualizer starting...")

        self.latest_scan: Optional[LaserScan] = None

        scan_qos = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.BEST_EFFORT,
            history=rclpy.qos.HistoryPolicy.KEEP_LAST,
            depth=10,
        )

        self.scan_sub = self.create_subscription(
            LaserScan,
            "/scan_multi",
            self.scan_callback,
            scan_qos,
        )

        self.image_pub = self.create_publisher(Image, DEBUG_TOPIC, 10)

        self.cap = open_camera()

        self.device = pick_device()
        self.get_logger().info(f"Device: {self.device}")

        self.processor = AutoImageProcessor.from_pretrained(MODEL_ID)

        dtype = torch.float16 if self.device.type == "cuda" else torch.float32
        self.model = AutoModelForSemanticSegmentation.from_pretrained(
            MODEL_ID,
            torch_dtype=(dtype if self.device.type == "cuda" else None),
        ).to(self.device).eval()

        self.person_id = self.find_label_id("person")
        self.get_logger().info(f"person_id={self.person_id}")

        self.hfov_rad = math.radians(CAM_HFOV_DEG)

        # 기존 vision_obstacle_node.py와 같은 기준
        self.fx = (IMG_WIDTH / 2.0) / math.tan(self.hfov_rad / 2.0)

        self.frame_idx = 0
        self.last_seg = np.zeros((INPUT_SIZE, INPUT_SIZE), dtype=np.uint8)

        os.makedirs(SAVE_DIR, exist_ok=True)
        self.last_save_time = 0.0
        self.save_idx = 0

        self.timer = self.create_timer(0.25, self.loop)

        self.get_logger().info(f"Ready. debug topic: {DEBUG_TOPIC}")

    def find_label_id(self, name):
        for k, v in self.model.config.id2label.items():
            if str(v).strip().lower() == name:
                return int(k)
        return None

    def scan_callback(self, msg):
        self.latest_scan = msg

    def find_clusters(self, cols, gap=10):
        if len(cols) == 0:
            return []

        clusters = []
        current = [cols[0]]

        for c in cols[1:]:
            if c - current[-1] <= gap:
                current.append(c)
            else:
                clusters.append(np.array(current))
                current = [c]

        clusters.append(np.array(current))
        return clusters

    def pixel_to_world_debug(self, px):
        if self.latest_scan is None:
            return None

        scan = self.latest_scan

        normalized = (px - INPUT_SIZE / 2.0) / self.fx
        cam_angle = math.atan(normalized)

        lidar_angle = cam_angle + math.radians(LIDAR_CAM_ANGLE_OFFSET_DEG)

        while lidar_angle > math.pi:
            lidar_angle -= 2 * math.pi
        while lidar_angle < -math.pi:
            lidar_angle += 2 * math.pi

        if not (scan.angle_min <= lidar_angle <= scan.angle_max):
            return None

        idx = int((lidar_angle - scan.angle_min) / scan.angle_increment)
        idx = max(0, min(idx, len(scan.ranges) - 1))

        idx_range = range(max(0, idx - 3), min(len(scan.ranges), idx + 4))

        valid_ranges = [
            scan.ranges[i]
            for i in idx_range
            if scan.range_min < scan.ranges[i] < scan.range_max
        ]

        if not valid_ranges:
            return None

        distance = float(np.median(valid_ranges))

        if distance < PERSON_MIN_DIST or distance > PERSON_MAX_DIST:
            return None

        raw_lidar_angle_deg = math.degrees(lidar_angle)

        # raw LiDAR 각도를 로봇 정면 기준 사람 방향각으로 변환
        # 예: raw -90도 근처가 정면이면 bearing 0도 근처
        bearing_deg = normalize_deg(raw_lidar_angle_deg - FRONT_SCAN_RAW_DEG)
        bearing_rad = math.radians(bearing_deg)

        # 로봇 기준 좌표: x 전방+, y 좌측+
        x = distance * math.cos(bearing_rad)
        y = distance * math.sin(bearing_rad)

        return {
            "px": px,
            "cam_angle_deg": math.degrees(cam_angle),
            "raw_lidar_angle_deg": raw_lidar_angle_deg,
            "bearing_deg": bearing_deg,
            "distance": distance,
            "x": x,
            "y": y,
        }

    def decision_text(self, info):
        if info is None:
            return "PERSON DETECTED / LIDAR NO MATCH"

        dist = info["distance"]
        y = info["y"]

        if dist < 0.6:
            if y > 0.15:
                return "CLOSE LEFT -> NAV2 AVOID RIGHT"
            elif y < -0.15:
                return "CLOSE RIGHT -> NAV2 AVOID LEFT"
            else:
                return "FRONT CLOSE -> STOP / REPLAN"
        elif dist < 1.2:
            return "SLOW DOWN / NAV2 REPLAN"
        else:
            return "PERSON OBSTACLE PUBLISHED"


    def _side_label(self, angle_deg):
        if angle_deg is None:
            return "-"
        if angle_deg < -10:
            return "RIGHT"
        elif angle_deg > 10:
            return "LEFT"
        return "CENTER"

    def _status_color(self, decision: str):
        d = (decision or "").upper()
        if "NO PERSON" in d or "CLEAR" in d:
            return (80, 200, 120)   # green
        if "STOP" in d or "CLOSE" in d:
            return (70, 70, 230)    # red-ish (BGR)
        return (0, 200, 255)        # yellow

    def _draw_angle_gauge(self, vis, x, y, w, h, cam_angle_deg=None, lidar_angle_deg=None):
        """
        -90 ~ +90 기준의 시각화 바
        cam_angle_deg: 카메라 기준 각도
        lidar_angle_deg: LiDAR 기준 각도 (표시용으로 -90~+90 클램프)
        """
        overlay = vis.copy()
        cv2.rectangle(overlay, (x, y), (x + w, y + h), (20, 20, 20), -1)
        vis[:] = cv2.addWeighted(overlay, 0.55, vis, 0.45, 0)
        cv2.rectangle(vis, (x, y), (x + w, y + h), (180, 180, 180), 1)

        bar_y = y + h // 2
        x1 = x + 20
        x2 = x + w - 20
        cv2.line(vis, (x1, bar_y), (x2, bar_y), (220, 220, 220), 2)

        # tick
        for deg in [-90, -45, 0, 45, 90]:
            tx = int(x1 + (deg + 90) / 180.0 * (x2 - x1))
            cv2.line(vis, (tx, bar_y - 8), (tx, bar_y + 8), (220, 220, 220), 1)
            cv2.putText(vis, str(deg), (tx - 12, bar_y + 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (220,220,220), 1, cv2.LINE_AA)

        def clamp90(v):
            if v is None:
                return None
            return max(-90.0, min(90.0, float(v)))

        cam_c = clamp90(cam_angle_deg)
        lidar_c = clamp90(lidar_angle_deg)

        if cam_c is not None:
            cx = int(x1 + (cam_c + 90) / 180.0 * (x2 - x1))
            cv2.circle(vis, (cx, bar_y), 6, (0, 255, 255), -1)
            cv2.putText(vis, "CAM", (cx - 18, bar_y - 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0,255,255), 1, cv2.LINE_AA)

        if lidar_c is not None:
            lx = int(x1 + (lidar_c + 90) / 180.0 * (x2 - x1))
            cv2.circle(vis, (lx, bar_y), 6, (255, 180, 0), -1)
            cv2.putText(vis, "LIDAR", (lx - 22, bar_y + 42),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255,180,0), 1, cv2.LINE_AA)



    def draw_result(self, frame, person_mask, person_ratio, info, decision):
        """
        논문 결과 화면용 간결 시각화.
        표시 항목:
        - Status
        - Distance
        - LiDAR angle
        - Camera angle
        - Point(x,y)
        - Decision
        """
        vis = frame.copy()
        h0, w0 = vis.shape[:2]

        s = min(h0, w0)
        y0c = (h0 - s) // 2
        x0c = (w0 - s) // 2

        # ── SegFormer mask overlay: red ──
        mask_u8 = (person_mask.astype(np.uint8) * 255)
        mask_resized = cv2.resize(mask_u8, (s, s), interpolation=cv2.INTER_NEAREST) > 0

        roi = vis[y0c:y0c + s, x0c:x0c + s]
        overlay = roi.copy()
        overlay[mask_resized] = (0, 0, 255)  # BGR red
        roi[:] = cv2.addWeighted(overlay, 0.23, roi, 0.77, 0)

        # ── bbox: thin white box ──
        ys, xs = np.where(person_mask)
        detected_by_seg = person_ratio >= PERSON_PIXEL_MIN_RATIO

        if len(xs) > 0 and len(ys) > 0 and detected_by_seg:
            x1 = x0c + int(xs.min() / INPUT_SIZE * s)
            x2 = x0c + int(xs.max() / INPUT_SIZE * s)
            y1 = y0c + int(ys.min() / INPUT_SIZE * s)
            y2 = y0c + int(ys.max() / INPUT_SIZE * s)
            cv2.rectangle(vis, (x1, y1), (x2, y2), (245, 245, 245), 2)

        # ── person direction line ──
        if info is not None:
            cx_img = x0c + int(info["px"] / INPUT_SIZE * s)
            cy_img = y0c + int(0.82 * s)
            cv2.circle(vis, (cx_img, cy_img), 6, (0, 0, 255), -1)
            cv2.line(vis, (w0 // 2, h0 - 28), (cx_img, cy_img), (0, 0, 255), 2)

        # ── values ──
        if info is None:
            distance_text = "-"
            lidar_angle_text = "-"
            camera_angle_text = "-"
            point_text = "(-, -)"
            bearing = None
        else:
            distance_text = f"{info['distance']:.2f} m"
            bearing = info.get("bearing_deg", info.get("robot_angle_deg", None))
            cam = info.get("cam_angle_deg", None)

            lidar_angle_text = "-" if bearing is None else f"{bearing:+.1f} deg"
            camera_angle_text = "-" if cam is None else f"{cam:+.1f} deg"
            point_text = f"({info['x']:.2f}, {info['y']:.2f})"

        if not detected_by_seg:
            status = "NO PERSON"
            status_color = (80, 180, 80)
            short_decision = "CLEAR"
        elif info is None:
            status = "PERSON DETECTED"
            status_color = (0, 180, 255)
            short_decision = "NO LIDAR MATCH"
        else:
            status = "PERSON DETECTED"
            status_color = (0, 0, 220)
            if "CLOSE" in decision or "STOP" in decision:
                short_decision = "STOP / REPLAN"
            elif "SLOW" in decision:
                short_decision = "SLOW / REPLAN"
            else:
                short_decision = "COSTMAP PUBLISH"

        # ── compact translucent panel ──
        px, py = 20, 20
        pw, ph = 430, 218

        bg = vis.copy()
        cv2.rectangle(bg, (px, py), (px + pw, py + ph), (18, 18, 18), -1)
        vis[:] = cv2.addWeighted(bg, 0.62, vis, 0.38, 0)
        cv2.rectangle(vis, (px, py), (px + pw, py + ph), (230, 230, 230), 1)

        cv2.putText(
            vis, "SegFormer + 2D LiDAR",
            (px + 16, py + 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.72, (255, 255, 255), 2, cv2.LINE_AA
        )

        # status bar
        cv2.rectangle(vis, (px + 16, py + 50), (px + 235, py + 80), status_color, -1)
        cv2.putText(
            vis, status,
            (px + 28, py + 71),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58, (255, 255, 255), 1, cv2.LINE_AA
        )

        rows = [
            ("Distance", distance_text),
            ("LiDAR angle", lidar_angle_text),
            ("Camera angle", camera_angle_text),
            ("Point(x,y)", point_text),
            ("Decision", short_decision),
        ]

        # 두 칸으로 분리해서 정렬
        label_x = px + 18
        colon_x = px + 165
        value_x = px + 190
        row_y = py + 112
        row_gap = 23

        for name, val in rows:
            cv2.putText(
                vis, name,
                (label_x, row_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55, (235, 235, 235), 1, cv2.LINE_AA
            )
            cv2.putText(
                vis, ":",
                (colon_x, row_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55, (235, 235, 235), 1, cv2.LINE_AA
            )
            cv2.putText(
                vis, val,
                (value_x, row_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55, (255, 255, 255), 1, cv2.LINE_AA
            )
            row_y += row_gap

        # ── simple angle gauge: LiDAR angle only ──
        gx, gy = 120, h0 - 72
        gw, gh = w0 - 240, 44

        gbg = vis.copy()
        cv2.rectangle(gbg, (gx, gy), (gx + gw, gy + gh), (25, 25, 25), -1)
        vis[:] = cv2.addWeighted(gbg, 0.50, vis, 0.50, 0)
        cv2.rectangle(vis, (gx, gy), (gx + gw, gy + gh), (190, 190, 190), 1)

        bar_y = gy + 22
        x1 = gx + 25
        x2 = gx + gw - 25
        cv2.line(vis, (x1, bar_y), (x2, bar_y), (230, 230, 230), 2)

        for deg in [-45, 0, 45]:
            tx = int(x1 + (deg + 90) / 180.0 * (x2 - x1))
            cv2.line(vis, (tx, bar_y - 7), (tx, bar_y + 7), (230, 230, 230), 1)
            cv2.putText(
                vis, str(deg),
                (tx - 12, bar_y + 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.43, (230, 230, 230), 1, cv2.LINE_AA
            )

        if bearing is not None:
            b = max(-90.0, min(90.0, float(bearing)))
            bx = int(x1 + (b + 90.0) / 180.0 * (x2 - x1))
            cv2.circle(vis, (bx, bar_y), 7, (0, 0, 255), -1)
            cv2.putText(
                vis, "LiDAR angle",
                (bx - 42, bar_y - 13),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45, (255, 255, 255), 1, cv2.LINE_AA
            )

        return vis


    def loop(self):
        ret, frame = self.cap.read()
        if not ret or frame is None:
            self.get_logger().warn("camera frame read failed", throttle_duration_sec=1.0)
            return

        self.frame_idx += 1

        if self.frame_idx % PROCESS_EVERY_N_FRAMES == 0:
            h0, w0 = frame.shape[:2]
            s = min(h0, w0)
            y0c = (h0 - s) // 2
            x0c = (w0 - s) // 2

            frame_sq = frame[y0c:y0c + s, x0c:x0c + s]
            inp = cv2.resize(frame_sq, (INPUT_SIZE, INPUT_SIZE))
            inp_rgb = cv2.cvtColor(inp, cv2.COLOR_BGR2RGB)

            with torch.no_grad():
                inputs = self.processor(images=inp_rgb, return_tensors="pt")

            pixel_values = inputs["pixel_values"].to(self.device)

            if self.device.type == "cuda":
                pixel_values = pixel_values.to(torch.float16)
                with torch.cuda.amp.autocast(dtype=torch.float16):
                    out = self.model(pixel_values=pixel_values)
            else:
                out = self.model(pixel_values=pixel_values)

            logits = F.interpolate(
                out.logits,
                size=(INPUT_SIZE, INPUT_SIZE),
                mode="bilinear",
                align_corners=False,
            )

            self.last_seg = logits.argmax(dim=1)[0].cpu().numpy().astype(np.uint8)

        if self.person_id is None:
            return

        person_mask = self.last_seg == self.person_id
        person_ratio = float(person_mask.mean())

        info = None
        decision = "NO PERSON"

        if person_ratio >= PERSON_PIXEL_MIN_RATIO:
            h, w = person_mask.shape
            foot_region = person_mask[int(h * 0.7):, :]

            if not foot_region.any():
                foot_region = person_mask

            person_cols = np.where(foot_region.any(axis=0))[0]

            if len(person_cols) > 0:
                clusters = self.find_clusters(person_cols, gap=10)
                if len(clusters) > 0:
                    cluster = max(clusters, key=len)
                    center_px = float(np.mean(cluster))
                    info = self.pixel_to_world_debug(center_px)
                    decision = self.decision_text(info)
                else:
                    decision = "PERSON DETECTED / NO CLUSTER"
            else:
                decision = "PERSON DETECTED / NO FOOT REGION"

        result = self.draw_result(frame, person_mask, person_ratio, info, decision)

        stamp = self.get_clock().now().to_msg()
        self.image_pub.publish(cv2_to_imgmsg_bgr8(result, "camera_debug", stamp))

        now = time.time()
        if now - self.last_save_time >= SAVE_INTERVAL_SEC:
            self.save_idx += 1
            out_path = os.path.join(SAVE_DIR, f"vision_result_{self.save_idx:03d}.png")
            cv2.imwrite(out_path, result)
            self.last_save_time = now

        # 필요한 로그만 출력:
        # - NO PERSON은 출력하지 않음
        # - 사람 감지 + LiDAR 매칭 성공 또는 LIDAR NO MATCH만 출력
        if info is not None:
            lidar_deg = info.get("raw_lidar_angle_deg", info.get("lidar_angle_deg", None))
            bearing_deg = info.get("bearing_deg", info.get("robot_angle_deg", None))

            lidar_txt = "-" if lidar_deg is None else f"{lidar_deg:+.1f}deg"
            bearing_txt = "-" if bearing_deg is None else f"{bearing_deg:+.1f}deg"

            self.get_logger().info(
                f"[RESULT] DETECTED ratio={person_ratio:.4f}, "
                f"dist={info['distance']:.2f}m, "
                f"lidar={lidar_txt}, bearing={bearing_txt}, "
                f"x={info['x']:.2f}, y={info['y']:.2f}, "
                f"decision={decision}",
                throttle_duration_sec=2.0,
            )
        elif decision != "NO PERSON":
            self.get_logger().warn(
                f"[RESULT] {decision}, ratio={person_ratio:.4f}",
                throttle_duration_sec=2.0,
            )

    def destroy_node(self):
        if self.cap.isOpened():
            self.cap.release()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = VisionResultVisualizer()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
