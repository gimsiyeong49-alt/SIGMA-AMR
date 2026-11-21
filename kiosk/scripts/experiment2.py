#!/usr/bin/env python3
# =========================================================================
# experiment2.py — 논문 실험 2(자율주행 단계별 성공률) 진행·기록 도우미
#
#   사용법:  ./scripts/experiment2.sh             실험 진행(ROS 환경을 불러 로봇 위치 오차까지 자동 기록)
#            ./scripts/experiment2.sh 표          표 2 출력 + exp2_summary.md 저장
#   옵션:    --dir /mnt/ssd/experiments/main   --goal 20   --no-ros(위치 자동 기록 끔)
#
#   1회 = 출발 → 목적지 도착(도착 안내) → 초기 위치 복귀(방향 정렬까지). 도착·복귀를 각각 O/X 로 기록하고
#   전체 한 바퀴(둘 다 O)는 자동 계산.
#     · 도착 성공: 목표 지점 기준 이내 + 도착 안내(상태 arrived)가 나옴
#     · 복귀 성공: 초기 위치로 돌아와 방향 정렬까지 마침(+ 기준 이내)
#     · 도착에 실패해도 로봇을 조이스틱·손으로 목적지에 옮겨 놓고 복귀를 시험 → 두 단계 시도 횟수가 같아짐
#     · 목적지 5곳(내과·외과·소아청소년과·산부인과·마취통증의학과) × 4회 = 20회.
#       메뉴에서 Enter 만 누르면 목록 순서대로 돌아가며 제안(목표 횟수를 채운 곳은 건너뜀), 숫자로 직접 선택도 가능
#
#   자동 기록: 상태(moving→arrived→returning→aligning→idle) 시각과 소요 시간,
#             단계별 Nav2 진행 실패·복구 동작·목표 실패 횟수(logs/navigation.log),
#             복귀 정렬 결과(logs/return_home.log),
#             로봇 추정 위치 오차(TF map→base, 지도 좌표 기준 — 테이프 실측이 아님)
#   사람 입력: 실측 오차(선택), 도착·복귀 O/X(Enter = 자동 제안), 실패 이유, 메모
#   ※ 읽기만 한다. 단 진행 중 r 을 누르고 확인하면 '초기 위치' 복귀 요청을 보낸다(도착 실패 후 복귀 시험용).
# =========================================================================
import argparse
import datetime
import json
import math
import os
import re
import select
import statistics
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from experiment import Tail, read_status, ask, load_rows, save_rows, pct, NAVLOG, RETLOG  # noqa: E402

LABELS = Path("/mnt/ssd/cart_ros2/src/hospital_mission/map/map_labels.json")
BUS = Path(os.environ.get("NAV_BUS_DIR", "/mnt/ssd/cart_ros2/src/llm_package/bus"))
HOME = "초기 위치"
CSV_NAME, CFG_NAME, SUM_NAME = "exp2_trials.csv", "exp2_config.json", "exp2_summary.md"
DEFAULT_DESTS = ["내과", "외과", "소아청소년과", "산부인과", "마취통증의학과"]   # 20회 = 5곳 × 4회

FIELDS = ["번호", "시각", "목적지", "도착", "복귀", "전체", "도착_실패이유", "복귀_실패이유",
          "도착_소요_초", "복귀_소요_초", "전체_소요_초",
          "도착_추정오차_cm", "도착_실측오차_cm",
          "복귀_추정위치오차_cm", "복귀_추정방향오차_도", "복귀_실측위치오차_cm", "복귀_실측방향오차_도", "복귀_정렬기록",
          "도착_Nav2진행실패", "도착_Nav2복구", "도착_Nav2목표실패", "복귀_Nav2진행실패", "복귀_Nav2복구", "복귀_Nav2목표실패",
          "도착_사람개입", "복귀_시작", "복귀_사람개입", "메모"]
ARR_REASONS = ["목표 지점 오차 초과", "멈춤·진행 못 함(복구 반복)", "길을 못 찾음(경로 실패)",
               "충돌 위험·사람이 개입함", "도착 안내가 안 나옴", "기타"]
RET_REASONS = ["초기 위치 오차 초과", "방향 정렬 실패", "멈춤·진행 못 함(복구 반복)",
               "출발 회전 못 함", "충돌 위험·사람이 개입함", "기타"]
RE_RECOV = re.compile(r"\[recoveries_server\]: Attempting (\w+)")
RE_ALIGN = re.compile(r"^방향 정렬 (완료|미완료) .*?오차 ([+-]?\d+(?:\.\d+)?)°")   # '[return]' 뒤를 잘라낸 줄 기준
RE_WALL = re.compile(r"라이다 벽 정렬 (완료|미완료) · 최종 오차 ([+-]?\d+(?:\.\d+)?|nan)°")
RE_PREROT = re.compile(r"복귀 전 미리 돌기 (완료|미완료) .*?오차 ([+-]?\d+(?:\.\d+)?)°")


# ── 지도 좌표 ──
def zone(name):
    """zone 이름(별칭 포함) → (x, y, yaw 또는 None). 없으면 None."""
    try:
        zs = json.loads(LABELS.read_text(encoding="utf-8")).get("zones", [])
    except (OSError, ValueError):
        return None
    for z in zs:
        if z.get("name") == name or name in (z.get("alias") or []):
            ng = z.get("nav_goal") or {}
            if "x" not in ng or "y" not in ng:
                return None
            yaw = None
            if "qz" in ng and "qw" in ng:
                yaw = math.atan2(2.0 * float(ng["qw"]) * float(ng["qz"]), 1.0 - 2.0 * float(ng["qz"]) ** 2)
            elif "yaw_deg" in ng:
                yaw = math.radians(float(ng["yaw_deg"]))
            return float(ng["x"]), float(ng["y"]), yaw
    return None


def wrap_deg(a):
    return (a + 180.0) % 360.0 - 180.0


# ── 로봇 위치(TF) — 읽기만 ──
class PoseSource:
    def __init__(self, enable):
        self.ok, self.msg = False, ""
        if not enable:
            self.msg = "꺼짐(--no-ros)"
            return
        try:
            import rclpy
            from rclpy.executors import SingleThreadedExecutor
            from tf2_ros import Buffer, TransformListener
        except Exception:
            self.msg = "ROS 환경 없음 — ./scripts/experiment2.sh 로 실행하면 위치 오차도 자동 기록됩니다"
            return
        try:
            rclpy.init()
            self.rclpy = rclpy
            self.node = rclpy.create_node("experiment2_recorder")
            self.buf = Buffer()
            self.tl = TransformListener(self.buf, self.node)
            ex = SingleThreadedExecutor()
            ex.add_node(self.node)
            threading.Thread(target=ex.spin, daemon=True).start()
            self.ok = True
        except Exception as exc:
            self.msg = f"ROS 연결 실패: {exc}"

    def get(self):
        """(x, y, yaw) 또는 None"""
        if not self.ok:
            return None
        for base in ("base_footprint", "base_link"):
            try:
                tf = self.buf.lookup_transform("map", base, self.rclpy.time.Time())
                t, q = tf.transform.translation, tf.transform.rotation
                return t.x, t.y, math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
            except Exception:
                continue
        return None

    def close(self):
        if self.ok:
            try:
                self.node.destroy_node()
                self.rclpy.shutdown()
            except Exception:
                pass


# ── 진행 중 키 입력(막지 않음) ──
def poll_key():
    try:
        r, _, _ = select.select([sys.stdin], [], [], 0)
    except (OSError, ValueError):
        return ""
    if not r:
        return ""
    try:
        data = os.read(sys.stdin.fileno(), 1024).decode("utf-8", "ignore").strip().lower()
    except OSError:
        return ""
    return data[:1]


def request_return():
    """'초기 위치' 복귀 요청 파일(키오스크·복귀 감시기와 같은 형식)을 버스에 쓴다."""
    d = BUS / "nav_request"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"experiment_{time.strftime('%Y%m%d_%H%M%S')}.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"place_name": HOME, "source": "experiment", "requested_at": time.time()},
                              ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return p


def hms():
    return datetime.datetime.now().strftime("%H:%M:%S")


# ═════════════════════ 1회 진행 ═════════════════════
def run_trial(dest, pose):
    goal = zone(dest)
    home = zone(HOME)
    nav_t, ret_t = Tail(NAVLOG), Tail(RETLOG)
    T = {}                                   # 상태별 처음 본 시각
    cnt = {ph: {"prog": 0, "recov": [], "fail": 0, "succ": 0} for ph in ("도착", "복귀")}
    flags = {"arr_human": False, "ret_manual": False, "ret_human": False, "watch_timeout": False}
    ret_lines = []
    win = deque()                            # 최근 1.5초 위치(멈춤 판정)
    arr_pose, closest = None, None           # 목적지에서 멈춘 위치 / 가장 가까이 간 위치
    phase, prev, started = "도착", None, False
    ret_active = False                       # 복귀 이동(returning/aligning)을 실제로 봤는가 — 이걸 본 뒤의 idle 만 '끝'
    print(f"  ▶ 키오스크에서 '{dest}' 안내를 시작해 주세요. 상태를 자동으로 따라갑니다.")
    print("    진행 중 입력(글자 + Enter):  f = 도착 실패(로봇을 목적지로 옮길 때)  r = 지금 복귀 시작"
          "  h = 복귀 중 사람이 개입함  s = 여기서 끝내고 기록   (Ctrl+C = s)")
    try:
        while True:
            now = time.time()
            st = read_status()
            s, place = st.get("state", ""), st.get("place", "")
            if not started:
                if s == "moving" and place != HOME:
                    started = True
                    T["moving"] = now
                    if place and place != dest:
                        print(f"   ⚠ 실제 목적지가 '{place}' 입니다(계획 '{dest}') → '{place}' 로 기록합니다.")
                        dest, goal = place, zone(place)
                    print(f"   {hms()} 출발: {dest}", flush=True)
                    prev = s
                else:
                    nav_t.read(), ret_t.read()          # 출발 전 줄은 버림
                    if poll_key() == "s":
                        print("   출발 전에 끝냄 — 기록하지 않습니다.")
                        return None
                    time.sleep(0.3)
                    continue
            if s in ("returning", "aligning"):
                ret_active = True
            if s != prev:
                if s and s != "idle" and s not in T:       # idle 은 끝날 때만 기록(도착 감시 시간 초과 idle 과 구분)
                    T[s] = now
                print(f"   {hms()} 상태: {s} {place}", flush=True)
                if s == "returning" and phase == "도착":
                    phase = "복귀"
                prev = s
            for line in nav_t.read():
                c = cnt[phase]
                if "Failed to make progress" in line:
                    c["prog"] += 1
                    print(f"   {hms()} [{phase}] Nav2 진행 실패", flush=True)
                m = RE_RECOV.search(line)
                if m:
                    c["recov"].append(m.group(1))
                    print(f"   {hms()} [{phase}] Nav2 복구 동작: {m.group(1)}", flush=True)
                if "]: Goal failed" in line:
                    c["fail"] += 1
                    print(f"   {hms()} [{phase}] Nav2 목표 실패", flush=True)
                if "]: Goal succeeded" in line:
                    c["succ"] += 1
            for line in ret_t.read():
                if "[return]" not in line:
                    continue
                txt = line.split("[return]", 1)[1].strip()
                ret_lines.append(txt)
                if "도착이 확인되지 않아 감시를 종료" in txt:
                    flags["watch_timeout"] = True
                    print(f"   {hms()} ⚠ {txt}\n      → 로봇을 목적지로 옮긴 뒤 r 로 복귀를 시작하거나, s 로 끝내세요.", flush=True)
                elif "초기 위치로 복귀 요청" in txt:
                    T.setdefault("ret_req", now)
                    print(f"   {hms()} {txt}", flush=True)
                elif any(k in txt for k in ("도착 (", "미리 돌기 완료", "미리 돌기 미완료", "미리 돌기 불필요",
                                             "정렬 완료", "정렬 미완료", "정렬 포기", "벽 미검출", "새 요청 감지")):
                    print(f"   {hms()} {txt[:110]}", flush=True)
            p = pose.get()
            if p and goal:
                win.append((now, p))
                while win and now - win[0][0] > 1.5:
                    win.popleft()
                dg = math.hypot(p[0] - goal[0], p[1] - goal[1])
                if phase == "도착" and (closest is None or dg < closest[0]):
                    closest = (dg, p)
                # 목적지에서 멈춘 위치: 도착 안내 뒤 ~ 복귀 이동 시작 전, 1초 넘게 2cm 안에 머문 마지막 위치
                if "arrived" in T and "ret_req" not in T and dg < 1.5 and len(win) >= 3 \
                        and win[-1][0] - win[0][0] >= 1.0:
                    xs = [q[1][0] for q in win]
                    ys = [q[1][1] for q in win]
                    if max(xs) - min(xs) < 0.02 and max(ys) - min(ys) < 0.02:
                        arr_pose = (dg, p)
            k = poll_key()
            if k == "f":
                flags["arr_human"] = True
                print(f"   {hms()} 도착 실패 표시 → 로봇을 조이스틱·손으로 목적지에 옮겨 주세요. 목적지 0.8 m 안에 들어오면"
                      " 도착으로 감지되고 5초 뒤 자동 복귀합니다. 자동 복귀가 안 되면 r 을 누르세요.", flush=True)
            elif k == "r":
                if ask("   로봇을 지금 '초기 위치'로 보낼까요? 주변을 확인하고 y > ").lower() == "y":
                    rp = request_return()
                    flags["ret_manual"] = True
                    T.setdefault("ret_req", time.time())   # 복귀 소요 시간은 상태가 returning 으로 바뀐 때부터
                    phase = "복귀"
                    print(f"   {hms()} 복귀 요청 보냄: {rp.name} (미리 돌기 없이 Nav2 로 바로 복귀)", flush=True)
            elif k == "h":
                if phase == "복귀":
                    flags["ret_human"] = True
                    print(f"   {hms()} 복귀 중 사람 개입 표시", flush=True)
                else:
                    flags["arr_human"] = True
                    print(f"   {hms()} 도착 중 사람 개입 표시", flush=True)
            elif k == "s":
                print("   여기서 끝내고 기록합니다.")
                break
            if s == "idle" and ret_active:
                T["idle"] = now
                time.sleep(0.5)
                for line in ret_t.read():                 # 정렬 마지막 줄까지
                    if "[return]" in line:
                        ret_lines.append(line.split("[return]", 1)[1].strip())
                break
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\n   중단 — 지금까지 자료로 기록합니다.")
    if not started:
        return None
    end_pose = pose.get()
    return {"dest": dest, "goal": goal, "home": home, "T": T, "cnt": cnt, "flags": flags, "ret_lines": ret_lines,
            "arr_pose": arr_pose, "closest": closest, "end_pose": end_pose, "t_end": time.time()}


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def pick_reason(reasons, sug):
    print("   " + " · ".join(f"[{i + 1}] {r}" for i, r in enumerate(reasons)))
    c = ask(f"   번호 [Enter={sug}] > ", str(sug))
    r = reasons[int(c) - 1] if c.isdigit() and 1 <= int(c) <= len(reasons) else c
    if r == "기타":
        r = "기타: " + ask("   내용 > ")
    return r


def record(res, cfg):
    T, cnt, fl = res["T"], res["cnt"], res["flags"]
    goal, home = res["goal"], res["home"]
    t_arr = T["arrived"] - T["moving"] if "arrived" in T else None
    t_ret = T["idle"] - T["returning"] if "idle" in T and "returning" in T else None
    t_all = (T.get("idle") or res["t_end"]) - T["moving"]
    # 도착 추정 오차
    arr_est, arr_basis = None, ""
    if res["arr_pose"]:
        arr_est, arr_basis = res["arr_pose"][0] * 100, "멈춘 위치"
    elif res["closest"]:
        arr_est, arr_basis = res["closest"][0] * 100, "가장 가까이 간 위치(멈춤 감지 못 함)"
    # 복귀 추정 오차
    ret_cm = ret_deg = None
    if "aligning" in T and res["end_pose"] and home:
        ep = res["end_pose"]
        ret_cm = math.hypot(ep[0] - home[0], ep[1] - home[1]) * 100
        if home[2] is not None:
            ret_deg = wrap_deg(math.degrees(ep[2] - home[2]))
    # 정렬 기록
    al = wl = pr = None
    for ln in res["ret_lines"]:
        al = RE_ALIGN.search(ln) or al
        wl = RE_WALL.search(ln) or wl
        pr = RE_PREROT.search(ln) or pr
    parts = []
    if pr:
        parts.append(f"미리 돌기 {pr.group(1)} {pr.group(2)}°")
    if al:
        parts.append(f"방향 정렬 {al.group(1)} {al.group(2)}°")
    if wl:
        parts.append(f"벽 정렬 {wl.group(1)} {wl.group(2)}°")
    if any("벽 미검출" in ln for ln in res["ret_lines"]):
        parts.append("벽 미검출")
    align_txt = " · ".join(parts)
    align_ok = bool(al and al.group(1) == "완료")

    ca, cr = cnt["도착"], cnt["복귀"]
    print(f"\n   ── 자동 기록 ({res['dest']}) ──")
    print(f"   도착 안내: {'나옴' if 'arrived' in T else '안 나옴'}"
          + (f" · 출발→도착 {t_arr:.0f}초" if t_arr else "")
          + (f" · 추정 오차 {arr_est:.0f}cm({arr_basis})" if arr_est is not None else "")
          + f" · Nav2 진행 실패 {ca['prog']} · 복구 {len(ca['recov'])} · 목표 실패 {ca['fail']}"
          + (" · 사람 개입" if fl["arr_human"] else ""))
    print(f"   복귀: {'수동 요청(r)' if fl['ret_manual'] else ('자동' if 'returning' in T else '시작 안 됨')}"
          + (f" · 소요 {t_ret:.0f}초" if t_ret else "")
          + (f" · 추정 위치 오차 {ret_cm:.0f}cm" if ret_cm is not None else "")
          + (f" · 추정 방향 오차 {ret_deg:+.1f}°" if ret_deg is not None else "")
          + f" · Nav2 진행 실패 {cr['prog']} · 복구 {len(cr['recov'])} · 목표 실패 {cr['fail']}"
          + (" · 사람 개입" if fl["ret_human"] else ""))
    if align_txt:
        print(f"   정렬: {align_txt}")
    print("   ※ 추정 오차 = 로봇이 지도에서 생각하는 자기 위치 기준(실측 아님). 실측값을 넣으면 판정에 그 값을 씁니다.")

    # ── 도착 판정 ──
    crit_a = cfg.get("arr_cm")
    m_arr = ask(f"  도착 실측 오차 cm (테이프·바닥 표시, Enter=건너뜀) > ")
    a_val = num(m_arr) if num(m_arr) is not None else arr_est
    a_over = crit_a is not None and a_val is not None and a_val > crit_a
    a_sug = "O" if ("arrived" in T and not fl["arr_human"] and not a_over) else "X"
    why = []
    if "arrived" not in T:
        why.append("도착 안내 없음")
    if fl["arr_human"]:
        why.append("사람 개입")
    if a_over:
        why.append(f"오차 {a_val:.0f}cm > 기준 {crit_a:.0f}cm")
    arr = ask(f"  도착 성공? o/x [Enter={a_sug}{' — ' + ', '.join(why) if why else ''}] > ", a_sug).upper()
    while arr not in ("O", "X"):
        arr = ask("  o 또는 x > ").upper()
    arr_reason = ""
    if arr == "X":
        sug = 1 if a_over else (4 if fl["arr_human"] else (3 if ca["fail"] and not ca["prog"] else
                                                           (2 if ca["prog"] or ca["recov"] else (5 if "arrived" not in T else 6))))
        print("  도착 실패 이유:")
        arr_reason = pick_reason(ARR_REASONS, sug)

    # ── 복귀 판정 ──
    crit_rc, crit_rd = cfg.get("ret_cm"), cfg.get("ret_deg")
    m_rc = ask("  복귀 실측 위치 오차 cm (Enter=건너뜀) > ")
    m_rd = ask("  복귀 실측 방향 오차 ° (Enter=건너뜀) > ")
    rc_val = num(m_rc) if num(m_rc) is not None else ret_cm
    rd_val = num(m_rd) if num(m_rd) is not None else ret_deg
    rc_over = crit_rc is not None and rc_val is not None and rc_val > crit_rc
    rd_over = crit_rd is not None and rd_val is not None and abs(rd_val) > crit_rd
    done = "aligning" in T and "idle" in T
    r_sug = "O" if (done and align_ok and not fl["ret_human"] and not rc_over and not rd_over) else "X"
    why = []
    if not done:
        why.append("정렬까지 못 마침")
    elif not align_ok:
        why.append("방향 정렬 미완료")
    if fl["ret_human"]:
        why.append("사람 개입")
    if rc_over:
        why.append(f"위치 {rc_val:.0f}cm > {crit_rc:.0f}cm")
    if rd_over:
        why.append(f"방향 {abs(rd_val):.1f}° > {crit_rd:.0f}°")
    ret = ask(f"  복귀 성공? o/x [Enter={r_sug}{' — ' + ', '.join(why) if why else ''}] > ", r_sug).upper()
    while ret not in ("O", "X"):
        ret = ask("  o 또는 x > ").upper()
    ret_reason = ""
    if ret == "X":
        prerot_stuck = bool(pr and pr.group(1) == "미완료")
        sug = (1 if rc_over else (2 if (rd_over or (done and not align_ok)) else
               (5 if fl["ret_human"] else (4 if prerot_stuck else (3 if cr["prog"] or cr["recov"] or cr["fail"] else 6)))))
        print("  복귀 실패 이유:")
        ret_reason = pick_reason(RET_REASONS, sug)
    memo = ask("  메모(선택) > ")
    f1 = lambda v: "" if v is None else f"{v:.1f}"
    return {"목적지": res["dest"], "도착": arr, "복귀": ret, "전체": "O" if arr == "O" and ret == "O" else "X",
            "도착_실패이유": arr_reason, "복귀_실패이유": ret_reason,
            "도착_소요_초": f1(t_arr), "복귀_소요_초": f1(t_ret), "전체_소요_초": f1(t_all),
            "도착_추정오차_cm": f1(arr_est), "도착_실측오차_cm": m_arr,
            "복귀_추정위치오차_cm": f1(ret_cm), "복귀_추정방향오차_도": f1(ret_deg),
            "복귀_실측위치오차_cm": m_rc, "복귀_실측방향오차_도": m_rd, "복귀_정렬기록": align_txt,
            "도착_Nav2진행실패": ca["prog"], "도착_Nav2복구": len(ca["recov"]), "도착_Nav2목표실패": ca["fail"],
            "복귀_Nav2진행실패": cr["prog"], "복귀_Nav2복구": len(cr["recov"]), "복귀_Nav2목표실패": cr["fail"],
            "도착_사람개입": "예" if fl["arr_human"] else "", "복귀_시작": "수동(r)" if fl["ret_manual"] else "자동",
            "복귀_사람개입": "예" if fl["ret_human"] else "", "메모": memo}


# ═════════════════════ 진행 ═════════════════════
def run(d, goal_n, cfg, pose):
    path = d / CSV_NAME
    rows = load_rows(path)
    dests = cfg["dests"]
    per = math.ceil(goal_n / len(dests))                 # 목적지당 목표 횟수(20회 ÷ 5곳 = 4회)
    print(f"\n[실험 2] 자율주행 단계별 성공률 — 1회 = 출발 → 목적지 도착 → 초기 위치 복귀(방향 정렬까지)")
    print(f"  목적지 {len(dests)}곳 × {per}회: {', '.join(dests)}")
    print(f"  기준: 도착 {fmt_crit(cfg.get('arr_cm'), 'cm')} · "
          f"복귀 {fmt_crit(cfg.get('ret_cm'), 'cm')}, 방향 {fmt_crit(cfg.get('ret_deg'), '°')}")
    print(f"  로봇 위치 자동 기록: {'켜짐' if pose.ok else pose.msg}")
    print("  ※ Nav2 는 목표 0.45 m 안이면 도착으로 멈추고, 복귀 감시기는 0.8 m 안에서 '도착 안내' 후 5초 뒤 복귀를 시작합니다.")
    print("    테이프 실측은 시간이 짧으니 목적지에 기준 반경 원을 미리 그려 두거나 휴대폰으로 찍어 두세요.\n")
    if subprocess.run(["pgrep", "-f", "return_home_watcher.py"], capture_output=True).returncode != 0:
        print("  ⚠ 복귀 감시기(return_home_watcher)가 안 떠 있습니다 — 안내 서버(start_guide)를 먼저 켜 주세요.\n")
    while True:
        n = len(rows)
        a = sum(r["도착"] == "O" for r in rows)
        r_ = sum(r["복귀"] == "O" for r in rows)
        f = sum(r["전체"] == "O" for r in rows)
        nxt = next_dest(rows, dests, per)
        print(f"── 진행 {n}/{goal_n}회 · 도착 성공 {a} · 복귀 성공 {r_} · 둘 다 {f}")
        print("   목적지별: " + " · ".join(f"{dn} {sum(r['목적지'] == dn for r in rows)}/{per}" for dn in dests))
        k = ask(f"  [Enter] {nxt}로 시작  " + "  ".join(f"[{i + 1}] {dn}" for i, dn in enumerate(dests))
                + "  [u] 직전 기록 지우기  [t] 표 보기  [q] 끝 > ").lower()
        if k == "q":
            break
        if k == "t":
            summary(d, goal_n, save=False)
            continue
        if k == "u":
            if rows:
                x = rows.pop()
                save_rows(path, FIELDS, rows)
                print(f"  지움: {x['번호']}번 {x['목적지']} (도착 {x['도착']} · 복귀 {x['복귀']})")
            continue
        if k == "":
            dest = nxt
        elif k.isdigit() and 1 <= int(k) <= len(dests):
            dest = dests[int(k) - 1]
        else:
            continue
        t0 = time.time()
        res = run_trial(dest, pose)
        if res is None:
            continue
        row = record(res, cfg)
        row = {"번호": len(rows) + 1, "시각": datetime.datetime.fromtimestamp(res["T"].get("moving", t0))
               .strftime("%Y-%m-%d %H:%M:%S"), **row}
        rows.append(row)
        save_rows(path, FIELDS, rows)
        print(f"  ✓ 기록 {len(rows)}번 저장: {row['목적지']} · 도착 {row['도착']} · 복귀 {row['복귀']} · 전체 {row['전체']} ({path})\n")


def next_dest(rows, dests, per):
    """목록 순서대로 돌아가며, 직전 목적지 다음부터 목표 횟수(per)를 못 채운 첫 목적지를 제안."""
    cnt = {dn: sum(r["목적지"] == dn for r in rows) for dn in dests}
    last = rows[-1]["목적지"] if rows else None
    start = (dests.index(last) + 1) % len(dests) if last in dests else 0
    order = dests[start:] + dests[:start]
    return next((dn for dn in order if cnt[dn] < per), order[0])


def fmt_crit(v, unit):
    return "-" if v is None else f"{v:g}{unit} 이내"


# ═════════════════════ 표 2 ═════════════════════
def stat(xs, unit="", nd=1):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "-", "-", 0
    m = f"{statistics.mean(xs):.{nd}f}" + (f" ± {statistics.stdev(xs):.{nd}f}" if len(xs) >= 2 else "")
    return m + unit, f"{min(xs):.{nd}f} ~ {max(xs):.{nd}f}", len(xs)


def summary(d, goal_n, save=True):
    rows = load_rows(d / CSV_NAME)
    cfg = load_cfg(d)
    n = len(rows)
    a = sum(r["도착"] == "O" for r in rows)
    r_ = sum(r["복귀"] == "O" for r in rows)
    f = sum(r["전체"] == "O" for r in rows)
    out = ["## 표 2. 자율주행 단계별 성공률", "",
           "| 단계 (Phase) | 시도 (Trials) | 성공 (Success) | 성공률 (Success Rate) |", "|---|---|---|---|",
           f"| 목적지 도착 (Arrival at destination) | {n} | {a} | {pct(a, n)} |",
           f"| 초기 위치 복귀 (Return to initial position) | {n} | {r_} | {pct(r_, n)} |",
           f"| 전체 한 바퀴 (Full cycle) | {n} | {f} | {pct(f, n)} |", "",
           "## 표 2-1. 목적지별", "",
           "| 목적지 | 시도 | 도착 성공 | 복귀 성공 | 전체 성공 |", "|---|---|---|---|---|"]
    for dn in list(dict.fromkeys([x for x in cfg.get("dests", []) if any(r["목적지"] == x for r in rows)]
                                 + [r["목적지"] for r in rows])):          # 설정 순서대로, 그 밖의 목적지는 뒤에
        rr = [r for r in rows if r["목적지"] == dn]
        m = len(rr)
        out.append(f"| {dn} | {m} | {sum(r['도착'] == 'O' for r in rr)} ({pct(sum(r['도착'] == 'O' for r in rr), m)}) | "
                   f"{sum(r['복귀'] == 'O' for r in rr)} ({pct(sum(r['복귀'] == 'O' for r in rr), m)}) | "
                   f"{sum(r['전체'] == 'O' for r in rr)} ({pct(sum(r['전체'] == 'O' for r in rr), m)}) |")
    out += ["", "## 표 2-2. 실패 이유", "", "| 단계 | 실패 이유 | 횟수 |", "|---|---|---|"]
    any_fail = False
    for ph, key in (("도착", "도착_실패이유"), ("복귀", "복귀_실패이유")):
        cnt = {}
        for r in rows:
            if r[ph] == "X":
                cnt[r[key] or "미기재"] = cnt.get(r[key] or "미기재", 0) + 1
        for k, v in sorted(cnt.items(), key=lambda kv: -kv[1]):
            out.append(f"| {ph} | {k} | {v} |")
            any_fail = True
    if not any_fail:
        out.append("| - | - | 0 |")
    ok_a = [r for r in rows if r["도착"] == "O"]
    ok_r = [r for r in rows if r["복귀"] == "O"]
    auto_a = [r for r in rows if not r["도착_사람개입"]]
    lines = [
        ("출발 → 도착 안내(초) · 도착 성공", [num(r["도착_소요_초"]) for r in ok_a], ""),
        ("복귀 시작 → 정렬 완료(초) · 복귀 성공", [num(r["복귀_소요_초"]) for r in ok_r], ""),
        ("한 바퀴 전체(초) · 둘 다 성공", [num(r["전체_소요_초"]) for r in rows if r["전체"] == "O"], ""),
        ("도착 위치 오차 · 실측(cm)", [num(r["도착_실측오차_cm"]) for r in rows], ""),
        ("도착 위치 오차 · 로봇 추정(cm)", [num(r["도착_추정오차_cm"]) for r in auto_a], ""),
        ("복귀 위치 오차 · 실측(cm)", [num(r["복귀_실측위치오차_cm"]) for r in rows], ""),
        ("복귀 위치 오차 · 로봇 추정(cm)", [num(r["복귀_추정위치오차_cm"]) for r in rows], ""),
        ("복귀 방향 오차 · 실측(°, 절댓값)", [abs(x) if (x := num(r["복귀_실측방향오차_도"])) is not None else None for r in rows], ""),
        ("복귀 방향 오차 · 로봇 추정(°, 절댓값)", [abs(x) if (x := num(r["복귀_추정방향오차_도"])) is not None else None for r in rows], ""),
    ]
    out += ["", "## 표 2-3. 소요 시간·오차", "", "| 항목 | 평균 ± 표준편차 | 최소 ~ 최대 | 횟수 |", "|---|---|---|---|"]
    for label, xs, unit in lines:
        m, rng, k = stat(xs, unit)
        if k:
            out.append(f"| {label} | {m} | {rng} | {k} |")
    na = sum(int(r["도착_Nav2복구"] or 0) for r in rows)
    nr = sum(int(r["복귀_Nav2복구"] or 0) for r in rows)
    out += ["", f"- 목표 {goal_n}회 · 기준: 도착 {fmt_crit(cfg.get('arr_cm'), 'cm')} + 도착 안내 / "
                f"복귀 방향 정렬 완료 + 위치 {fmt_crit(cfg.get('ret_cm'), 'cm')}, 방향 {fmt_crit(cfg.get('ret_deg'), '°')}",
            "- 도착에 실패한 회차도 로봇을 목적지로 옮겨 복귀를 시험했으므로 두 단계 시도 횟수가 같습니다.",
            f"- Nav2 복구 동작 합계: 도착 단계 {na}회 · 복귀 단계 {nr}회",
            "- 로봇 추정 오차 = 지도 위 자기 위치(TF map→base) 기준이며 실측과 다를 수 있습니다.",
            f"- 기록: {d / CSV_NAME}"]
    text = "\n".join(out)
    print("\n" + text + "\n")
    if save:
        (d / SUM_NAME).write_text(text + "\n", encoding="utf-8")
        print(f"저장: {d / SUM_NAME}")


def load_cfg(d):
    try:
        return json.loads((d / CFG_NAME).read_text(encoding="utf-8"))
    except Exception:
        return {}


def setup_cfg(d):
    print("[처음 한 번 설정] 실험 2 목적지와 성공 기준 (나중에 바꾸려면 " + str(d / CFG_NAME) + " 삭제 후 다시 실행)")
    while True:
        v = ask(f"  목적지 목록(쉼표로 구분, 이 순서대로 돌아가며 제안) [Enter={', '.join(DEFAULT_DESTS)}] > ",
                ", ".join(DEFAULT_DESTS))
        dests = list(dict.fromkeys(x.strip() for x in v.split(",") if x.strip()))
        bad = [x for x in dests if not zone(x)]
        if dests and not bad:
            break
        print(f"   지도 목적지 목록(map_labels.json)에 없는 이름: {', '.join(bad) or '(비어 있음)'} — 다시 입력해 주세요.")

    def num_or_none(prompt, dflt):
        v = ask(prompt, dflt)
        return None if v in ("-", "없음") else num(v)
    cfg = {"dests": dests,
           "arr_cm": num_or_none("  도착 기준: 목표 지점에서 몇 cm 이내? [Enter=30, '-'=기준 없음] > ", "30"),
           "ret_cm": num_or_none("  복귀 기준: 초기 위치에서 몇 cm 이내? [Enter=30, '-'=기준 없음] > ", "30"),
           "ret_deg": num_or_none("  복귀 기준: 방향 몇 ° 이내? [Enter=10, '-'=기준 없음] > ", "10")}
    (d / CFG_NAME).write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return cfg


def main():
    ap = argparse.ArgumentParser(description="실험 2(자율주행 단계별 성공률) 진행·기록 도우미")
    ap.add_argument("what", nargs="?", default="진행", choices=["진행", "표", "table"])
    ap.add_argument("--dir", default="/mnt/ssd/experiments/main")
    ap.add_argument("--goal", type=int, default=20)
    ap.add_argument("--no-ros", action="store_true", help="로봇 위치(TF) 자동 기록 끔")
    a = ap.parse_args()
    d = Path(a.dir)
    d.mkdir(parents=True, exist_ok=True)
    if a.what in ("표", "table"):
        summary(d, a.goal, save=True)
        return 0
    cfg = load_cfg(d)
    if "dests" not in cfg:
        cfg = setup_cfg(d)
    pose = PoseSource(not a.no_ros)
    try:
        run(d, a.goal, cfg, pose)
    finally:
        pose.close()
    summary(d, a.goal, save=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
