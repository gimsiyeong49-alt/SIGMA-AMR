import math
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import rclpy
from action_msgs.msg import GoalStatus
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node


@dataclass(frozen=True)
class NavTarget:
    name: str
    frame_id: str
    x: float
    y: float
    qz: float
    qw: float


StatusCallback = Callable[[str, str], None]


class NavigationManager(Node):
    """NavigateToPose goal을 성공 또는 도착 판정까지 유지·재시도한다."""

    def __init__(
        self,
        action_name: str = "/navigate_to_pose",
        retry_sec: float = 2.0,
        stall_sec: float = 15.0,
        feedback_timeout_sec: float = 10.0,
        arrival_distance: float = 0.45,
        arrival_hold_sec: float = 1.0,
        progress_epsilon: float = 0.05,
        max_retries: int = 0,
        status_callback: Optional[StatusCallback] = None,
    ) -> None:
        super().__init__("llm_navigation_manager")

        self._action_client = ActionClient(
            self,
            NavigateToPose,
            action_name,
        )

        self._action_name = action_name
        self._retry_sec = max(0.1, float(retry_sec))
        self._stall_sec = max(1.0, float(stall_sec))
        self._feedback_timeout_sec = max(1.0, float(feedback_timeout_sec))
        self._arrival_distance = max(0.0, float(arrival_distance))
        self._arrival_hold_sec = max(0.0, float(arrival_hold_sec))
        self._progress_epsilon = max(0.0, float(progress_epsilon))
        self._max_retries = max(0, int(max_retries))
        self._status_callback = status_callback

        self._lock = threading.RLock()
        self._mission_id = 0
        self._target: Optional[NavTarget] = None
        self._goal_handle = None
        self._state = "idle"
        self._attempt = 0
        self._next_retry_at = 0.0
        self._cancel_started_at = 0.0
        self._retry_after_cancel = False
        self._retry_reason = ""

        self._last_feedback_at = 0.0
        self._last_progress_at = 0.0
        self._best_distance = math.inf
        self._last_distance = math.inf
        self._within_arrival_since: Optional[float] = None

        self._last_server_notice_at = 0.0
        self._timer = self.create_timer(0.25, self._tick)

    def start_navigation(self, target: NavTarget) -> None:
        old_goal_handle = None

        with self._lock:
            old_goal_handle = self._goal_handle

            self._mission_id += 1
            self._target = target
            self._goal_handle = None
            self._state = "retry_wait"
            self._attempt = 0
            self._next_retry_at = time.monotonic()
            self._cancel_started_at = 0.0
            self._retry_after_cancel = False
            self._retry_reason = ""
            self._reset_attempt_feedback_locked()

            mission_id = self._mission_id

        if old_goal_handle is not None:
            try:
                old_goal_handle.cancel_goal_async()
            except Exception as exc:
                self._emit("warn", f"이전 goal 취소 요청 실패: {exc}")

        self._emit(
            "started",
            (
                f"{target.name} 안내 mission 시작 "
                f"(x={target.x:.3f}, y={target.y:.3f}, mission={mission_id})"
            ),
        )

    def cancel_navigation(self, reason: str = "사용자 요청") -> bool:
        goal_handle = None
        target_name = "목적지"

        with self._lock:
            if self._target is None and self._goal_handle is None:
                return False

            if self._target is not None:
                target_name = self._target.name

            goal_handle = self._goal_handle

            self._mission_id += 1
            self._target = None
            self._goal_handle = None
            self._state = "idle"
            self._retry_after_cancel = False
            self._retry_reason = ""
            self._reset_attempt_feedback_locked()

        if goal_handle is not None:
            try:
                goal_handle.cancel_goal_async()
            except Exception as exc:
                self._emit("warn", f"goal 취소 요청 실패: {exc}")

        self._emit("canceled", f"{target_name} 안내 취소: {reason}")
        return True

    def is_navigating(self) -> bool:
        with self._lock:
            return self._target is not None and self._state != "idle"

    def current_destination_name(self) -> Optional[str]:
        with self._lock:
            if self._target is None:
                return None
            return self._target.name

    def _tick(self) -> None:
        now = time.monotonic()
        send_target = None
        send_mission_id = 0
        cancel_goal_handle = None
        arrived_target = None

        with self._lock:
            if self._target is None:
                return

            if self._state in ("retry_wait", "waiting_server"):
                if now < self._next_retry_at:
                    return

                if not self._action_client.server_is_ready():
                    self._state = "waiting_server"
                    self._next_retry_at = now + self._retry_sec

                    if now - self._last_server_notice_at >= 5.0:
                        self._last_server_notice_at = now
                        self._emit(
                            "waiting",
                            f"Nav2 action server 대기 중: {self._action_name}",
                        )
                    return

                if self._max_retries > 0 and self._attempt >= self._max_retries:
                    failed_name = self._target.name
                    self._target = None
                    self._state = "idle"
                    self._emit(
                        "failed",
                        f"{failed_name} 안내 최대 재시도 횟수 초과",
                    )
                    return

                self._attempt += 1
                self._state = "sending"
                self._reset_attempt_feedback_locked(now)
                send_target = self._target
                send_mission_id = self._mission_id

            elif self._state == "active":
                if (
                    self._within_arrival_since is not None
                    and now - self._within_arrival_since >= self._arrival_hold_sec
                ):
                    arrived_target = self._target
                    cancel_goal_handle = self._goal_handle
                    self._complete_arrival_locked()

                elif now - self._last_feedback_at >= self._feedback_timeout_sec:
                    cancel_goal_handle = self._begin_retry_cancel_locked(
                        now,
                        "Nav2 feedback이 일정 시간 들어오지 않음",
                    )

                elif now - self._last_progress_at >= self._stall_sec:
                    cancel_goal_handle = self._begin_retry_cancel_locked(
                        now,
                        (
                            f"목적지까지 거리 진전이 {self._stall_sec:.1f}초 동안 없음 "
                            f"(최근 거리={self._format_distance(self._last_distance)})"
                        ),
                    )

            elif self._state == "canceling_for_retry":
                if now - self._cancel_started_at >= 5.0:
                    self._goal_handle = None
                    self._schedule_retry_locked(
                        "goal 취소 결과 대기 시간 초과",
                        now,
                    )

        if send_target is not None:
            self._send_goal(send_mission_id, send_target)

        if cancel_goal_handle is not None:
            try:
                cancel_goal_handle.cancel_goal_async()
            except Exception as exc:
                with self._lock:
                    if self._target is not None:
                        self._goal_handle = None
                        self._schedule_retry_locked(
                            f"goal 취소 요청 예외: {exc}",
                            time.monotonic(),
                        )

        if arrived_target is not None:
            self._emit(
                "arrived",
                (
                    f"{arrived_target.name} 도착 판정 "
                    f"(남은 거리 {self._arrival_distance:.2f} m 이하 유지)"
                ),
            )

    def _send_goal(self, mission_id: int, target: NavTarget) -> None:
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = target.frame_id
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = target.x
        goal_msg.pose.pose.position.y = target.y
        goal_msg.pose.pose.position.z = 0.0
        goal_msg.pose.pose.orientation.x = 0.0
        goal_msg.pose.pose.orientation.y = 0.0
        goal_msg.pose.pose.orientation.z = target.qz
        goal_msg.pose.pose.orientation.w = target.qw
        goal_msg.behavior_tree = ""

        with self._lock:
            attempt = self._attempt

        self._emit(
            "goal_sent",
            f"{target.name} Nav2 goal 전송 시도 #{attempt}",
        )

        try:
            future = self._action_client.send_goal_async(
                goal_msg,
                feedback_callback=(
                    lambda feedback_msg, mid=mission_id, aid=attempt:
                    self._feedback_callback(mid, aid, feedback_msg)
                ),
            )
            future.add_done_callback(
                lambda done_future, mid=mission_id, aid=attempt:
                self._goal_response_callback(mid, aid, done_future)
            )
        except Exception as exc:
            with self._lock:
                if mission_id == self._mission_id and self._target is not None:
                    self._schedule_retry_locked(
                        f"goal 전송 예외: {exc}",
                        time.monotonic(),
                    )

    def _goal_response_callback(
        self,
        mission_id: int,
        attempt_id: int,
        future,
    ) -> None:
        try:
            goal_handle = future.result()
        except Exception as exc:
            with self._lock:
                if (
                    mission_id == self._mission_id
                    and attempt_id == self._attempt
                    and self._target is not None
                ):
                    self._schedule_retry_locked(
                        f"goal 응답 예외: {exc}",
                        time.monotonic(),
                    )
            return

        with self._lock:
            if (
                mission_id != self._mission_id
                or attempt_id != self._attempt
                or self._target is None
            ):
                if goal_handle is not None and goal_handle.accepted:
                    try:
                        goal_handle.cancel_goal_async()
                    except Exception:
                        pass
                return

            if goal_handle is None or not goal_handle.accepted:
                self._schedule_retry_locked(
                    "Nav2가 goal을 거절함",
                    time.monotonic(),
                )
                return

            self._goal_handle = goal_handle
            self._state = "active"
            now = time.monotonic()
            self._last_feedback_at = now
            self._last_progress_at = now

            target_name = self._target.name
            attempt = self._attempt

        self._emit(
            "accepted",
            f"{target_name} goal 승인됨 (시도 #{attempt})",
        )

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            lambda done_future, mid=mission_id, aid=attempt_id:
            self._result_callback(mid, aid, done_future)
        )

    def _feedback_callback(
        self,
        mission_id: int,
        attempt_id: int,
        feedback_msg,
    ) -> None:
        try:
            distance = float(feedback_msg.feedback.distance_remaining)
        except Exception:
            return

        if not math.isfinite(distance):
            return

        now = time.monotonic()

        with self._lock:
            if (
                mission_id != self._mission_id
                or attempt_id != self._attempt
                or self._target is None
                or self._state != "active"
            ):
                return

            self._last_feedback_at = now
            self._last_distance = distance

            if distance + self._progress_epsilon < self._best_distance:
                self._best_distance = distance
                self._last_progress_at = now

            if distance <= self._arrival_distance:
                if self._within_arrival_since is None:
                    self._within_arrival_since = now
            else:
                self._within_arrival_since = None

    def _result_callback(
        self,
        mission_id: int,
        attempt_id: int,
        future,
    ) -> None:
        try:
            wrapped_result = future.result()
            status = int(wrapped_result.status)
        except Exception as exc:
            with self._lock:
                if (
                    mission_id == self._mission_id
                    and attempt_id == self._attempt
                    and self._target is not None
                ):
                    self._goal_handle = None
                    self._schedule_retry_locked(
                        f"result 응답 예외: {exc}",
                        time.monotonic(),
                    )
            return

        arrived_target = None

        with self._lock:
            if (
                mission_id != self._mission_id
                or attempt_id != self._attempt
                or self._target is None
            ):
                return

            target_name = self._target.name
            self._goal_handle = None

            if status == GoalStatus.STATUS_SUCCEEDED:
                arrived_target = self._target
                self._complete_arrival_locked()

            elif self._retry_after_cancel:
                reason = self._retry_reason or "재시도를 위한 goal 취소"
                self._retry_after_cancel = False
                self._retry_reason = ""
                self._schedule_retry_locked(reason, time.monotonic())
            else:
                status_name = self._status_name(status)
                reason = f"Nav2 결과={status_name}"
                self._schedule_retry_locked(reason, time.monotonic())
        if arrived_target is not None:
            self._emit("arrived", f"{arrived_target.name} 도착 완료")

    def _begin_retry_cancel_locked(self, now: float, reason: str):
        if self._goal_handle is None:
            self._schedule_retry_locked(reason, now)
            return None

        goal_handle = self._goal_handle
        self._state = "canceling_for_retry"
        self._cancel_started_at = now
        self._retry_after_cancel = True
        self._retry_reason = reason

        self._emit("stalled", f"{reason}; 현재 goal 취소 후 재전송")
        return goal_handle

    def _schedule_retry_locked(self, reason: str, now: float) -> None:
        if self._target is None:
            self._state = "idle"
            return

        self._goal_handle = None
        self._state = "retry_wait"
        self._next_retry_at = now + self._retry_sec
        self._retry_after_cancel = False
        self._retry_reason = ""
        self._reset_attempt_feedback_locked(now)

        self._emit(
            "retry",
            f"{self._retry_sec:.1f}초 후 동일 goal 재전송: {reason}",
        )

    def _complete_arrival_locked(self) -> None:
        self._mission_id += 1
        self._target = None
        self._goal_handle = None
        self._state = "idle"
        self._retry_after_cancel = False
        self._retry_reason = ""
        self._reset_attempt_feedback_locked()

    def _reset_attempt_feedback_locked(self, now: Optional[float] = None) -> None:
        if now is None:
            now = time.monotonic()

        self._last_feedback_at = now
        self._last_progress_at = now
        self._best_distance = math.inf
        self._last_distance = math.inf
        self._within_arrival_since = None

    def _emit(self, event: str, message: str) -> None:
        if self._status_callback is not None:
            try:
                self._status_callback(event, message)
                return
            except Exception:
                pass

        print(f"[NAV:{event}] {message}", flush=True)

    @staticmethod
    def _status_name(status: int) -> str:
        names = {
            GoalStatus.STATUS_UNKNOWN: "UNKNOWN",
            GoalStatus.STATUS_ACCEPTED: "ACCEPTED",
            GoalStatus.STATUS_EXECUTING: "EXECUTING",
            GoalStatus.STATUS_CANCELING: "CANCELING",
            GoalStatus.STATUS_SUCCEEDED: "SUCCEEDED",
            GoalStatus.STATUS_CANCELED: "CANCELED",
            GoalStatus.STATUS_ABORTED: "ABORTED",
        }
        return names.get(status, str(status))

    @staticmethod
    def _format_distance(distance: float) -> str:
        if not math.isfinite(distance):
            return "알 수 없음"
        return f"{distance:.2f} m"


class NavigationRuntime:
    """NavigationManager용 ROS executor를 백그라운드 thread에서 실행한다."""

    def __init__(self, **manager_kwargs) -> None:
        if not rclpy.ok():
            rclpy.init(args=[])

        self.node = NavigationManager(**manager_kwargs)
        self.executor = MultiThreadedExecutor(num_threads=2)
        self.executor.add_node(self.node)
        self._thread = threading.Thread(
            target=self.executor.spin,
            name="llm-nav-executor",
            daemon=True,
        )
        self._thread.start()

    def shutdown(self) -> None:
        try:
            self.node.cancel_navigation(reason="프로그램 종료")
        except Exception:
            pass

        try:
            self.executor.shutdown()
        except Exception:
            pass

        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

        try:
            self.node.destroy_node()
        except Exception:
            pass

        if rclpy.ok():
            rclpy.shutdown()
