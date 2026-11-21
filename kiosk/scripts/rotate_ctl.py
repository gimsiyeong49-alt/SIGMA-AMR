# rotate_ctl.py — 제자리 회전 정렬 제어기(ROS 없는 순수 로직, return_home_watcher.py 가 사용)
#
# 2026-11-13: 복귀 후 방향 정렬이 ±60° 를 6번쯤 오가다 끝나던 문제(로그 확인) 대응.
#   예전 방식: 회전 속도 = max(하한, 1.2×오차), '회전이 느리다'(0.1초 순간 측정)면 하한을 올리고 다시 내리지 않음
#   → 출발 순간(모터 드라이버 가속 구간)이나 밀린 측정값을 '멈춤'으로 오인해 하한이 최대(0.335 rad/s)로 고정
#   → 목표 근처에서도 최대 속도로 돌며 크게 지나쳤다 되돌아오기 반복.
# 새 방식(두 단계):
#   ① 접근: 오차 비례 속도(목표에 가까울수록 느리게) + 지연 보상. 멈춤 판단은 1.5초 동안의 실제 회전량으로만.
#   ② 미세: 목표 fine_zone(3°) 안에 들어오면 멈추고 settle(0.6초) 기다려 '정확히' 다시 잰 뒤,
#      남은 각만큼만 느린 속도로 짧게 한 번 돌리고(펄스) 다시 멈춰서 잰다. 허용 오차 안이면 끝.
#      → 측정 지연이 얼마든(0.1~1초) 목표 근처에서 좌우로 왔다 갔다 하지 않는다.
import math


def norm_angle(a):
    return math.atan2(math.sin(a), math.cos(a))


class RotateController:
    def __init__(self, tol, w_min=0.05, w_max=0.35, k=0.8, latency=0.25,
                 fine_zone_deg=3.0, w_fine=0.06, settle=0.6,
                 stall_window=1.5, stall_deg=1.0, stuck_sec=4.0, max_pulses=8):
        self.tol, self.w_min, self.w_max, self.k, self.latency = tol, w_min, w_max, k, latency
        self.fine_zone, self.w_fine, self.settle = math.radians(fine_zone_deg), w_fine, settle
        self.stall_window, self.stall_rad, self.stuck_sec = stall_window, math.radians(stall_deg), stuck_sec
        self.max_pulses = max_pulses
        self.mode = "approach"           # approach(접근) / settle(멈춰서 측정 대기) / pulse(미세 회전)
        self.until = 0.0
        self.boost = 0.0                 # 접근 중 멈춤 감지 시 최소 속도에 더하는 값(다시 돌면 0)
        self.fine_boost = 0.0            # 미세 회전이 안 먹을 때 미세 속도에 더하는 값
        self.fine_fail = 0               # 연속으로 안 먹은 미세 회전 횟수
        self.pulses = 0
        self.pulse_w = 0.0
        self.pulse_dur = 0.0
        self.pulse_err0 = None          # 미세 회전 직전 오차(효과 확인용)
        self.hist = []                   # (시각, 오차) — 접근 중 멈춤 판단
        self.last_w = 0.0
        self.t_start = None
        self.last_progress_t = None
        self._stuck = False
        self.events = []                 # 로그용 메시지(호출 측이 꺼내 쓰고 비움)

    # ── 내부 도우미 ──
    def _out(self, w):
        self.last_w = w
        return w, False

    def _start_settle(self, now):
        self.mode, self.until = "settle", now + self.settle
        return self._out(0.0)

    # ── 메인 ──
    def step(self, err, now):
        """오차(rad, 목표-현재)와 시각 → (명령 각속도 rad/s, 끝났나)"""
        if self.t_start is None:
            self.t_start = self.last_progress_t = now

        if self.mode == "pulse":
            if now < self.until:
                return self._out(self.pulse_w)
            return self._start_settle(now)

        if self.mode == "settle":
            if now < self.until:
                return self._out(0.0)
            # 멈춘 채 settle 초 지남 → 측정값이 최신이 됐다고 보고 판단
            if self.pulse_err0 is not None:                       # 직전 미세 회전이 먹었나
                expected = abs(self.pulse_w) * self.pulse_dur
                moved = abs(self.pulse_err0) - abs(err) if self.pulse_err0 * err > 0 \
                    else abs(self.pulse_err0) + abs(err)          # 넘어갔으면 지나간 만큼 합산
                if moved < 0.3 * expected:
                    self.fine_fail += 1
                    self.fine_boost = min(self.w_max - self.w_fine, self.fine_boost + 0.03)
                    self.events.append(f"미세 회전이 거의 안 됨({math.degrees(moved):.2f}°) "
                                       f"→ 미세 속도 {self.w_fine + self.fine_boost:.2f}")
                    if self.fine_fail >= 3:
                        self._stuck = True
                else:
                    self.fine_fail = 0
                    self.last_progress_t = now
                self.pulse_err0 = None
            if abs(err) <= self.tol or (self.pulses >= self.max_pulses and abs(err) <= 2 * self.tol):
                return 0.0, True
            if abs(err) < self.fine_zone:
                if self.pulses >= self.max_pulses + 4:            # 잡음 등으로 끝없이 미세 조정 방지
                    self.events.append(f"미세 조정 {self.pulses}회 — 오차 {math.degrees(err):+.2f}° 에서 마침")
                    return 0.0, True
                w = self.w_fine + self.fine_boost
                self.pulse_dur = max(0.08, min(2.0, abs(err) / w))
                self.pulse_w = math.copysign(w, err)
                self.pulse_err0 = err
                self.pulses += 1
                self.mode, self.until = "pulse", now + self.pulse_dur
                return self._out(self.pulse_w)
            self.events.append(f"정지 후 측정 오차 {math.degrees(err):+.2f}° → 다시 접근 회전")
            self.mode = "approach"
            self.hist.clear()
            self.boost = 0.0

        # ── ① 접근 ──
        if abs(err) < self.fine_zone:                              # 가까워짐 → 멈추고 정확히 잼
            return self._start_settle(now)
        self.hist.append((now, err))
        while self.hist and now - self.hist[0][0] > self.stall_window:
            self.hist.pop(0)
        if len(self.hist) >= 3 and self.hist[-1][0] - self.hist[0][0] >= self.stall_window * 0.8:
            progress = abs(norm_angle(self.hist[0][1] - self.hist[-1][1]))
            if progress >= self.stall_rad:
                self.last_progress_t = now
                if progress > 3 * self.stall_rad:
                    self.boost = 0.0                               # 잘 돎 → 원래 최소 속도로
            elif abs(self.last_w) >= self.w_min * 0.9:
                floor = self.w_min + self.boost
                if floor < self.w_max:
                    new_floor = min(self.w_max, floor * 1.5 + 0.03)
                    self.boost = new_floor - self.w_min
                    self.events.append(f"회전 멈춤 감지(1.5초 {math.degrees(progress):.1f}°) → 최소 속도 {new_floor:.2f}")
                    self.hist.clear()
                elif now - self.last_progress_t > self.stuck_sec:
                    self._stuck = True
        w_floor = self.w_min + self.boost
        w = min(self.w_max, max(w_floor, self.k * abs(err)))
        predicted = abs(err) - abs(self.last_w) * self.latency     # 지연 동안 더 돌 양을 빼 본 남은 각
        if predicted < self.fine_zone:
            w = w_floor
        return self._out(math.copysign(w, err))

    def stuck(self, now=None):
        """속도를 올려도 실제로 안 돎(캐스터 꼬임 등) → 호출 측이 위글로 탈출"""
        return self._stuck

    def reset_after_unstick(self, now):
        self.mode, self.boost, self.fine_boost, self.fine_fail = "approach", 0.0, 0.0, 0
        self.pulse_err0, self.last_w, self._stuck = None, 0.0, False
        self.hist.clear()
        self.last_progress_t = now
