#!/usr/bin/env python3
"""
vision_obstacle_node.py
SegFormer 사람 감지 + LiDAR 거리 퓨전 → nav2 costmap 장애물 publish

[논문 Contribution]
1. RGB+LiDAR 센서 퓨전 기반 조기 사람 감지
   - SegFormer semantic segmentation으로 사람 픽셀 추출
   - 해당 방향 LiDAR 거리 매칭 → 정확한 3D 위치
   - nav2 costmap에 등록 → DWB 조기 경로 수정
2. Distance-based Adaptive Speed Control
   - 사람과의 거리에 따라 속도 자동 조절
   - /speed_limit 토픽으로 nav2 실시간 전달
"""

import math
import os
import time
from typing import List, Optional

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan, PointCloud2, PointField, Image
import torch
import torch.nn.functional as F
from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation

# ── 설정 ──────────────────────────────────────────────────
MODEL_ID = "nvidia/segformer-b1-finetuned-ade-512-512"

CAMERA_DEV_CANDIDATES: List[str] = [
    "/dev/v4l/by-id/usb-STsmart_HD_4MP_WEBCAM_USB-video-index0",
    "/dev/v4l/by-id/usb-STsmart_HD_4MP_WEBCAM_USB-video-index1",
    "/dev/v4l/by-id/usb-HD_Web_Camera_HD_Web_Camera_Ucamera001-video-index0",
    "/dev/v4l/by-id/usb-HD_Web_Camera_HD_Web_Camera_Ucamera001-video-index1",
    "/dev/video0",
]

CAP_WIDTH  = 640
CAP_HEIGHT = 480
INPUT_SIZE = 256
PROCESS_EVERY_N_FRAMES = 2

# 2026-11-12: 키오스크가 마이크로 녹음하는 동안(이 파일이 있는 동안) AI 추론을 쉰다.
#  이 노드의 GPU 추론이 도는 동안 reSpeaker 녹음이 0.25초만 받고 멈추고 USB "buffer overrun"이 수천 건 났다
#  (카메라 영상만 받을 땐 정상). 녹음은 로봇이 서서 환자와 대화할 때만 하므로 그 몇 초는 LiDAR만으로 충분.
#  kiosk_server.py 가 녹음 시작 때 만들고 끝나면 지운다. 서버가 죽어 남은 파일은 MIC_FLAG_MAX_AGE 초 뒤 무시.
MIC_FLAG = "/mnt/ssd/cart_ros2/src/llm_package/bus/mic_active"
MIC_FLAG_MAX_AGE = 30.0

# 카메라 파라미터
CAM_HFOV_DEG = 70.0
CAM_HEIGHT_M = 0.60
IMG_WIDTH    = 640

# ──────────────────────────────────────────────────────────
# [변경] LiDAR-카메라 각도 오프셋 재보정 필요
#
# 기존값: 85.0 (이전 로봇 방향 기준 실측값)
#
# 앞뒤양옆 180° 교체 후 scan_multi의 각도 기준이 변경되었으므로
# 아래 값을 다시 실측해야 합니다.
#
# 재보정 방법:
#   1. 로봇 정면 약 2m 지점에 사람(또는 물체)을 세움
#   2. ros2 topic echo /scan_multi 로 해당 방향 각도 확인
#   3. 카메라 이미지 중앙(px=320) 기준으로 LIDAR_CAM_ANGLE_OFFSET_DEG 조정
#   4. person_ratio 로그로 감지 확인
#
# 임시 추정값: 기존 85.0° + 180° = 265.0° → 정규화하면 -95.0°
# → 하지만 scan_multi 구성(병합 방식)에 따라 달라지므로 반드시 실측할 것
# ──────────────────────────────────────────────────────────
LIDAR_CAM_ANGLE_OFFSET_DEG = 63.11  # TODO: 실측 후 조정 필요

# 사람 감지 임계값 (전체 이미지 기준)
PERSON_PIXEL_MIN_RATIO = 0.06

# 안정화 필터
DETECT_CONFIRM_FRAMES = 2
CLEAR_FRAMES          = 3

# 장애물 파라미터
OBSTACLE_FRAME  = "base_footprint"
OBSTACLE_TOPIC  = "/people_obstacles"
OBSTACLE_Z      = 0.0
PERSON_MAX_DIST = 4.5
PERSON_MIN_DIST = 0.3

# 논문 결과 화면용 디버그 이미지
DEBUG_IMAGE_TOPIC = "/vision_result/image"
DEBUG_SAVE_DIR = "/mnt/ssd/cart_ros2/result_outputs"
DEBUG_SAVE_INTERVAL_SEC = 2.0


# ──────────────────────────────────────────────────────────


def pick_device() -> torch.device:
    return torch.device("cuda:0") if torch.cuda.is_available() else torch.device("cpu")


def open_camera() -> cv2.VideoCapture:
    for dev in CAMERA_DEV_CANDIDATES:
        cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAP_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAP_HEIGHT)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        ret, _ = cap.read()
        if ret:
            return cap
        cap.release()
    raise RuntimeError("카메라 열기 실패")


def make_pointcloud2(points: np.ndarray, frame_id: str, stamp) -> PointCloud2:
    msg = PointCloud2()
    msg.header.frame_id = frame_id
    msg.header.stamp    = stamp
    msg.height = 1
    msg.width  = len(points)
    msg.is_dense    = True
    msg.is_bigendian = False
    msg.point_step  = 12
    msg.row_step    = msg.point_step * msg.width
    msg.fields = [
        PointField(name='x', offset=0,  datatype=PointField.FLOAT32, count=1),
        PointField(name='y', offset=4,  datatype=PointField.FLOAT32, count=1),
        PointField(name='z', offset=8,  datatype=PointField.FLOAT32, count=1),
    ]
    msg.data = points.astype(np.float32).tobytes()
    return msg




def cv2_to_imgmsg_bgr8(img: np.ndarray, frame_id: str, stamp) -> Image:
    """cv_bridge 없이 OpenCV BGR 이미지를 sensor_msgs/Image로 변환"""
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



class VisionObstacleNode(Node):
    def __init__(self):
        super().__init__('vision_obstacle_node')
        self.get_logger().info("VisionObstacleNode starting...")

        # ── LiDAR 구독 ──
        self.latest_scan: Optional[LaserScan] = None
        scan_qos = rclpy.qos.QoSProfile(
            reliability=rclpy.qos.ReliabilityPolicy.BEST_EFFORT,
            history=rclpy.qos.HistoryPolicy.KEEP_LAST,
            depth=10)
        self.scan_sub = self.create_subscription(
            LaserScan, '/scan_multi', self._scan_callback, scan_qos)

        # ── Publishers ──
        self.obstacle_pub = self.create_publisher(PointCloud2, OBSTACLE_TOPIC, 10)

        # ── 논문 결과 화면용 디버그 이미지 Publisher ──
        self.debug_pub = self.create_publisher(Image, DEBUG_IMAGE_TOPIC, 10)
        os.makedirs(DEBUG_SAVE_DIR, exist_ok=True)
        self.last_debug_save_time = 0.0
        self.debug_save_idx = 0

        # ── 카메라 오픈 ──
        self.cap = open_camera()
        self.get_logger().info("Camera opened")

        # ── SegFormer 로드 ──
        self.device = pick_device()
        self.get_logger().info(f"Device: {self.device}")

        self.processor = AutoImageProcessor.from_pretrained(MODEL_ID)
        dtype = torch.float16 if self.device.type == "cuda" else torch.float32
        self.model = AutoModelForSemanticSegmentation.from_pretrained(
            MODEL_ID,
            torch_dtype=(dtype if self.device.type == "cuda" else None),
        ).to(self.device).eval()

        self.person_id = self._find_label_id("person")
        self.floor_id  = self._find_label_id("floor")
        self.get_logger().info(
            f"Label IDs → person:{self.person_id}, floor:{self.floor_id}")

        # ── 카메라 파라미터 ──
        self.hfov_rad = math.radians(CAM_HFOV_DEG)
        self.fx = (IMG_WIDTH / 2.0) / math.tan(self.hfov_rad / 2.0)

        # ── 안정화 필터 상태 ──
        self.detect_count      = 0
        self.clear_count       = 0
        self.is_publishing     = False

        # ── 타이머 ──
        self.frame_idx = 0
        self.last_seg  = np.zeros((INPUT_SIZE, INPUT_SIZE), dtype=np.uint8)
        self.timer = self.create_timer(0.25, self._camera_loop)

        self.get_logger().info(f"Ready! Publishing to {OBSTACLE_TOPIC}")

    def _find_label_id(self, name: str) -> Optional[int]:
        for k, v in self.model.config.id2label.items():
            if str(v).strip().lower() == name.strip().lower():
                return int(k)
        return None

    def _scan_callback(self, msg: LaserScan):
        self.latest_scan = msg

    def _mic_active(self) -> bool:
        try:
            age = time.time() - os.path.getmtime(MIC_FLAG)
        except OSError:
            return False
        return 0 <= age < MIC_FLAG_MAX_AGE

    def _camera_loop(self):
        # 키오스크 녹음 중이면 AI 추론·발행을 쉰다(카메라 프레임은 계속 읽어 버퍼를 최신으로 유지)
        if self._mic_active():
            if not getattr(self, "_mic_paused", False):
                self._mic_paused = True
                self.get_logger().info("키오스크 녹음 중 → 사람 감지 일시 정지")
            self.cap.read()
            return
        if getattr(self, "_mic_paused", False):
            self._mic_paused = False
            self.get_logger().info("녹음 끝 → 사람 감지 재개")

        ret, frame = self.cap.read()
        if not ret:
            return

        self.frame_idx += 1

        # ── SegFormer 추론 ──
        if (self.frame_idx % PROCESS_EVERY_N_FRAMES) == 0:
            h0, w0 = frame.shape[:2]
            s = min(h0, w0)
            y0c = (h0 - s) // 2
            x0c = (w0 - s) // 2
            frame_sq = frame[y0c:y0c+s, x0c:x0c+s]
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
                out.logits, size=(INPUT_SIZE, INPUT_SIZE),
                mode="bilinear", align_corners=False)
            self.last_seg = logits.argmax(dim=1)[0].cpu().numpy().astype(np.uint8)

        if self.person_id is None:
            return

        # ── 사람 감지 ──
        person_mask  = (self.last_seg == self.person_id)
        person_ratio = float(person_mask.mean())

        self.get_logger().info(
            f"person_ratio={person_ratio:.4f} threshold={PERSON_PIXEL_MIN_RATIO}",
            throttle_duration_sec=1.0)

        # ── 안정화 필터 ──
        person_detected = person_ratio >= PERSON_PIXEL_MIN_RATIO

        if person_detected:
            self.detect_count += 1
            self.clear_count   = 0
        else:
            self.clear_count  += 1
            self.detect_count  = 0

        if self.detect_count >= DETECT_CONFIRM_FRAMES:
            self.is_publishing = True
        if self.clear_count >= CLEAR_FRAMES:
            self.is_publishing = False

        # ── 장애물 없음 ──
        if not self.is_publishing:
            empty = np.zeros((0, 3), dtype=np.float32)
            self.obstacle_pub.publish(
                make_pointcloud2(empty, OBSTACLE_FRAME, self.get_clock().now().to_msg()))
            self._publish_debug_image(
                frame, person_mask, person_ratio,
                center_px=None, obs_point=None,
                decision="NO PERSON / CLEAR COSTMAP")
            return

        # ── 발 위치 추출 (하단 30%) ──
        h, w = person_mask.shape
        foot_region = person_mask[int(h * 0.7):, :]
        if not foot_region.any():
            foot_region = person_mask

        person_cols = np.where(foot_region.any(axis=0))[0]
        if len(person_cols) == 0:
            return

        obstacle_points = []
        clusters = self._find_clusters(person_cols, gap=10)
        min_dist = float('inf')

        # 디버그 표시용 대표 사람 위치
        debug_center_px = None
        debug_obs_point = None

        for cluster_cols in clusters:
            center_px = float(np.mean(cluster_cols))
            obs_point = self._pixel_to_world(center_px)
            if obs_point is None:
                continue

            if debug_obs_point is None:
                debug_center_px = center_px
                debug_obs_point = obs_point

            cx, cy = obs_point[0], obs_point[1]
            dist = math.sqrt(cx**2 + cy**2)
            min_dist = min(min_dist, dist)

            obstacle_points.append(obs_point)

            # 좌우 팽창 포인트
            for angle_offset in [-0.2, 0.2]:
                a = math.atan2(cy, cx)
                if dist > 0.1:
                    obstacle_points.append([
                        dist * math.cos(a + angle_offset),
                        dist * math.sin(a + angle_offset),
                        OBSTACLE_Z
                    ])


        if not obstacle_points:
            self._publish_debug_image(
                frame, person_mask, person_ratio,
                center_px=None, obs_point=None,
                decision="PERSON DETECTED / LIDAR NO MATCH")
            return

        pts = np.array(obstacle_points, dtype=np.float32)
        self.obstacle_pub.publish(
            make_pointcloud2(pts, OBSTACLE_FRAME, self.get_clock().now().to_msg()))

        decision = self._make_decision_text(debug_center_px, debug_obs_point)
        self._publish_debug_image(
            frame, person_mask, person_ratio,
            center_px=debug_center_px,
            obs_point=debug_obs_point,
            decision=decision)

        self.get_logger().info(
            f"Person detected (ratio={person_ratio:.2f}), "
            f"publishing {len(obstacle_points)} pts",
            throttle_duration_sec=1.0)


    # ===== MERGED VISUALIZATION METHODS START =====
    def _make_decision_text(self, center_px, obs_point):
        if obs_point is None:
            return "PERSON DETECTED / LIDAR NO MATCH"

        x, y = float(obs_point[0]), float(obs_point[1])
        dist = math.sqrt(x * x + y * y)

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

    def _debug_info_from_point(self, center_px, obs_point):
        if center_px is None or obs_point is None:
            return None

        x, y = float(obs_point[0]), float(obs_point[1])
        distance = math.sqrt(x * x + y * y)
        bearing_deg = math.degrees(math.atan2(y, x))

        normalized = (float(center_px) - INPUT_SIZE / 2.0) / self.fx
        cam_angle = math.atan(normalized)
        raw_lidar_angle_deg = math.degrees(cam_angle + math.radians(LIDAR_CAM_ANGLE_OFFSET_DEG))

        while raw_lidar_angle_deg > 180.0:
            raw_lidar_angle_deg -= 360.0
        while raw_lidar_angle_deg < -180.0:
            raw_lidar_angle_deg += 360.0

        return {
            "px": float(center_px),
            "cam_angle_deg": math.degrees(cam_angle),
            "raw_lidar_angle_deg": raw_lidar_angle_deg,
            "bearing_deg": bearing_deg,
            "distance": distance,
            "x": x,
            "y": y,
        }

    def _publish_debug_image(self, frame, person_mask, person_ratio, center_px=None, obs_point=None, decision=""):
        info = self._debug_info_from_point(center_px, obs_point)
        result = self._draw_result(frame, person_mask, person_ratio, info, decision)

        stamp = self.get_clock().now().to_msg()
        self.debug_pub.publish(cv2_to_imgmsg_bgr8(result, "camera_debug", stamp))

        now = time.time()
        if now - self.last_debug_save_time >= DEBUG_SAVE_INTERVAL_SEC:
            self.debug_save_idx += 1
            out_path = os.path.join(DEBUG_SAVE_DIR, f"vision_obstacle_debug_{self.debug_save_idx:03d}.png")
            cv2.imwrite(out_path, result)
            self.last_debug_save_time = now

    def _draw_result(self, frame, person_mask, person_ratio, info, decision):
        vis = frame.copy()
        h0, w0 = vis.shape[:2]

        s = min(h0, w0)
        y0c = (h0 - s) // 2
        x0c = (w0 - s) // 2

        # SegFormer mask overlay
        mask_u8 = (person_mask.astype(np.uint8) * 255)
        mask_resized = cv2.resize(mask_u8, (s, s), interpolation=cv2.INTER_NEAREST) > 0

        roi = vis[y0c:y0c + s, x0c:x0c + s]
        overlay = roi.copy()
        overlay[mask_resized] = (0, 0, 255)
        roi[:] = cv2.addWeighted(overlay, 0.23, roi, 0.77, 0)

        ys, xs = np.where(person_mask)
        detected_by_seg = person_ratio >= PERSON_PIXEL_MIN_RATIO

        if len(xs) > 0 and len(ys) > 0 and detected_by_seg:
            x1 = x0c + int(xs.min() / INPUT_SIZE * s)
            x2 = x0c + int(xs.max() / INPUT_SIZE * s)
            y1 = y0c + int(ys.min() / INPUT_SIZE * s)
            y2 = y0c + int(ys.max() / INPUT_SIZE * s)
            cv2.rectangle(vis, (x1, y1), (x2, y2), (245, 245, 245), 2)

        if info is not None:
            cx_img = x0c + int(info["px"] / INPUT_SIZE * s)
            cy_img = y0c + int(0.82 * s)
            cv2.circle(vis, (cx_img, cy_img), 6, (0, 0, 255), -1)
            cv2.line(vis, (w0 // 2, h0 - 28), (cx_img, cy_img), (0, 0, 255), 2)

        if info is None:
            distance_text = "-"
            lidar_angle_text = "-"
            camera_angle_text = "-"
            point_text = "(-, -)"
            bearing = None
        else:
            distance_text = f"{info['distance']:.2f} m"
            bearing = info.get("bearing_deg", None)
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

        # Compact status panel
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

        label_x = px + 18
        colon_x = px + 165
        value_x = px + 190
        row_y = py + 112
        row_gap = 23

        for name, val in rows:
            cv2.putText(vis, name, (label_x, row_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (235, 235, 235), 1, cv2.LINE_AA)
            cv2.putText(vis, ":", (colon_x, row_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (235, 235, 235), 1, cv2.LINE_AA)
            cv2.putText(vis, val, (value_x, row_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
            row_y += row_gap

        # LiDAR bearing gauge
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
            cv2.putText(vis, str(deg), (tx - 12, bar_y + 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.43, (230, 230, 230), 1, cv2.LINE_AA)

        if bearing is not None:
            b = max(-90.0, min(90.0, float(bearing)))
            bx = int(x1 + (b + 90.0) / 180.0 * (x2 - x1))
            cv2.circle(vis, (bx, bar_y), 7, (0, 0, 255), -1)
            cv2.putText(vis, "LiDAR angle", (bx - 42, bar_y - 13),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

        return vis
    # ===== MERGED VISUALIZATION METHODS END =====


    def _pixel_to_world(self, px: float) -> Optional[List[float]]:
        """픽셀 x → 수평 각도 → LiDAR 거리 → (x, y) 좌표"""
        if self.latest_scan is None:
            return None

        scan = self.latest_scan
        normalized  = (px - INPUT_SIZE / 2.0) / self.fx
        cam_angle   = math.atan(normalized)
        lidar_angle = cam_angle + math.radians(LIDAR_CAM_ANGLE_OFFSET_DEG)

        # 각도 정규화 (-π ~ +π) → scan_multi 범위와 매칭 보장
        while lidar_angle >  math.pi: lidar_angle -= 2 * math.pi
        while lidar_angle < -math.pi: lidar_angle += 2 * math.pi

        if not (scan.angle_min <= lidar_angle <= scan.angle_max):
            return None

        idx = int((lidar_angle - scan.angle_min) / scan.angle_increment)
        idx = max(0, min(idx, len(scan.ranges) - 1))

        idx_range = range(max(0, idx - 3), min(len(scan.ranges), idx + 4))
        valid_ranges = [scan.ranges[i] for i in idx_range
                        if scan.range_min < scan.ranges[i] < scan.range_max]

        if not valid_ranges:
            return None

        distance = float(np.median(valid_ranges))

        if distance < PERSON_MIN_DIST or distance > PERSON_MAX_DIST:
            return None

        x = distance * math.cos(lidar_angle)
        y = -distance * math.sin(lidar_angle)
        return [x, y, OBSTACLE_Z]

    def _find_clusters(self, cols: np.ndarray, gap: int = 10) -> List[np.ndarray]:
        if len(cols) == 0:
            return []
        clusters, current = [], [cols[0]]
        for c in cols[1:]:
            if c - current[-1] <= gap:
                current.append(c)
            else:
                clusters.append(np.array(current))
                current = [c]
        clusters.append(np.array(current))
        return clusters

    def destroy_node(self):
        if self.cap.isOpened():
            self.cap.release()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = VisionObstacleNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
