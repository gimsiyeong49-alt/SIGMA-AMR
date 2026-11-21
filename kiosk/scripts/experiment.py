#!/usr/bin/env python3
# =========================================================================
# experiment.py — 논문 실험 진행·기록 도우미 (표 1: AI 안내 수용률·응답 시간 / 표 2: 자율주행 안내 성공률)
#
#   사용법:  python3 scripts/experiment.py 1        실험 1 진행(접수·위치 안내를 번갈아 반복 기록)
#            python3 scripts/experiment.py 2        실험 2 진행(목적지 A/B 왕복 주행 기록)
#            python3 scripts/experiment.py 표       표 1·2 출력 + summary.md 저장
#   옵션:    --dir /mnt/ssd/experiments/<이름>  (기본 /mnt/ssd/experiments/main — 이어서 기록됨)
#            --goal 20   (항목당 목표 횟수)
#
#   자동으로 채우는 값(키오스크 logs/experiment_events.jsonl · bus/kiosk_status.json · Nav2/복귀 로그):
#     실험 1 · AI 추천 항목(위치: 인식→매칭 장소 / 접수: 문진 종합의 추천 진료과)
#            · 그대로 선택했나(위치: '예'로 안내 시작(/nav)이 같은 장소면 O / 접수: 같은 진료과로 접수하면 O)
#            · 응답 시간 = 녹음기가 '말이 끝난' 순간 → 서버가 결과를 보낸 순간(화면 표시까지 +0.1초 안팎)
#     실험 2 · 출발·도착·복귀·정렬 시각과 소요 시간, Nav2 진행 실패·복구 동작 횟수, 복귀 정렬 결과
#   사람이 확인·입력: 각 시도 끝에 Enter(자동값 그대로) 또는 o/x·숫자로 고침. 실측 오차(테이프)·실패 이유.
#   ※ 개인정보(이름·주민번호·증상)는 어디에도 기록하지 않는다.
# =========================================================================
import argparse
import csv
import datetime
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = Path(os.environ.get("EXP_EVENTS", ROOT / "logs" / "experiment_events.jsonl"))
STATUS = Path(os.environ.get("EXP_STATUS", "/mnt/ssd/cart_ros2/src/llm_package/bus/kiosk_status.json"))
NAVLOG = Path(os.environ.get("EXP_NAVLOG", ROOT / "logs" / "navigation.log"))
RETLOG = Path(os.environ.get("EXP_RETLOG", ROOT / "logs" / "return_home.log"))
LOCJS = ROOT / "src" / "js" / "data" / "locations.js"

E1_FIELDS = ["번호", "시각", "종류", "AI추천", "그대로선택", "응답시간_초", "응답시간_자동_초", "응답시간_수동_초", "판정방법", "메모"]
E2_FIELDS = ["번호", "시각", "목적지", "성공", "실패이유", "출발→도착_초", "전체_초", "Nav2진행실패", "Nav2복구",
             "길못찾음", "복귀정렬", "실측위치오차_cm", "실측방향오차_도", "메모"]
FAIL_REASONS = ["충돌·접촉", "멈춤(진행 못 함·복구 반복)", "목표 지점 오차 초과", "복귀 실패", "사람이 개입함", "음성·화면 문제", "기타"]


def loc_names():
    try:
        s = LOCJS.read_text(encoding="utf-8")
        return dict(re.findall(r"id:\s*'([^']+)',\s*name:\s*'([^']+)'", s))
    except OSError:
        return {}


NAMES = loc_names()


def nm(loc):
    return NAMES.get(loc, loc) if loc else "(없음)"


# ── 파일 꼬리 읽기 ──
class Tail:
    def __init__(self, path):
        self.path = Path(path)
        self.pos = self.path.stat().st_size if self.path.exists() else 0

    def read(self):
        if not self.path.exists():
            return []
        size = self.path.stat().st_size
        if size < self.pos:
            self.pos = 0
        with open(self.path, "rb") as f:
            f.seek(self.pos)
            data = f.read()
            self.pos = f.tell()
        return data.decode("utf-8", "ignore").splitlines()


def read_status():
    try:
        return json.loads(STATUS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def ask(prompt, default=""):
    try:
        v = input(prompt).strip()
    except EOFError:
        v = ""
    return v if v else default


def load_rows(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_rows(path, fields, rows):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def pct(a, b):
    return f"{a / b * 100:.1f}%" if b else "-"


# ═════════════════════ 실험 1 ═════════════════════
def wait_events(tail, pred, timeout, label):
    """이벤트 파일에서 pred(ev) 가 참인 첫 이벤트. Ctrl+C 면 None(수동 입력)."""
    t_end = time.time() + timeout
    print(f"   … {label} (Ctrl+C = 자동 감지 건너뛰고 직접 입력)", flush=True)
    seen = []
    try:
        while time.time() < t_end:
            for line in tail.read():
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                seen.append(ev)
                if pred(ev, seen):
                    return ev, seen
            time.sleep(0.2)
    except KeyboardInterrupt:
        print()
    return None, seen


def exp1(d, goal):
    path = d / "exp1.csv"
    rows = load_rows(path)
    if not EVENTS.parent.exists():
        print(f"⚠ 키오스크 기록 폴더 없음: {EVENTS.parent}")
    print("\n[실험 1] AI 안내 수용률·응답 시간 — 키오스크에서 사용자가 말로 요청 → AI 결과 → 사용자 선택")
    print("  응답 시간 = '말을 끝낸 순간 → 결과가 처음 뜬 순간'. 자동값은 서버 기준(화면 표시까지 +0.1초 안팎).")
    print("  화면 녹화로 잰 값이 있으면 그 숫자를 입력하면 그걸 씁니다.\n")
    while True:
        a = [r for r in rows if r["종류"] == "접수"]
        b = [r for r in rows if r["종류"] == "위치"]
        print(f"── 진행: 접수 {len(a)}/{goal} (O {sum(r['그대로선택'] == 'O' for r in a)}) · "
              f"위치 {len(b)}/{goal} (O {sum(r['그대로선택'] == 'O' for r in b)})")
        k = ask("  다음 시도 [1] 접수  [2] 위치  [u] 직전 기록 지우기  [t] 표 보기  [q] 끝 > ").lower()
        if k == "q":
            break
        if k == "t":
            summary(d, goal, save=False)
            continue
        if k == "u":
            if rows:
                r = rows.pop()
                save_rows(path, E1_FIELDS, rows)
                print(f"  지움: {r['번호']}번 {r['종류']} {r['AI추천']}")
            continue
        if k not in ("1", "2"):
            continue
        kind = "접수" if k == "1" else "위치"
        tail = Tail(EVENTS)
        t0 = time.time()
        if kind == "위치":
            print("  ▶ 키오스크 첫 화면에서 마이크를 누르고 목적지를 말해 주세요(예: '내과 어디예요').")
            ev, _ = wait_events(tail, lambda e, s: e.get("ev") == "listen" and e.get("loc"), 600, "AI 인식 결과 기다리는 중")
        else:
            print("  ▶ 키오스크에서 접수를 진행해 주세요(증상 말하기 → AI 문진 → 추천 진료과).")
            ev, _ = wait_events(tail, lambda e, s: e.get("ev") == "recommend", 900, "AI 추천 진료과 기다리는 중")
        auto_item, auto_rt, auto_ok, method = "", None, None, "수동"
        if ev:
            auto_item = nm(ev.get("loc"))
            if ev.get("speech_end"):
                auto_rt = round(ev["t"] - ev["speech_end"], 2)
            elif ev.get("t_req"):
                auto_rt = round(ev["t"] - ev["t_req"], 2)
            print(f"   AI 추천: {auto_item}" + (f" · 응답 시간(자동) {auto_rt:.2f}초" if auto_rt is not None else " · 응답 시간 자동 측정 없음(타자 입력?)"))
            # 사용자 선택 감지
            want = ev.get("loc")
            if kind == "위치":
                # '예/아니오'를 말로 답하면 장소 없는 listen 이 먼저 올 수 있음 → 장소가 있는 listen(다시 요청)만 X 로
                sel, _ = wait_events(tail, lambda e, s: e.get("ev") == "nav" or (e.get("ev") == "listen" and e.get("loc")), 120,
                                     "사용자가 '예'(안내 시작) 또는 다시 말하기를 하는지 보는 중")
                if sel:
                    auto_ok = "O" if sel.get("ev") == "nav" and sel.get("loc") == want else "X"
            else:
                sel, _ = wait_events(tail, lambda e, s: e.get("ev") in ("register", "recommend"), 300,
                                     "사용자가 어떤 진료과로 접수하는지 보는 중")
                if sel:
                    auto_ok = "O" if sel.get("ev") == "register" and sel.get("dept") == want else "X"
                    if sel.get("ev") == "register" and sel.get("dept") != want:
                        print(f"   접수 진료과: {nm(sel.get('dept'))} (추천과 다름)")
            method = "자동"
        item = ask(f"  AI 추천 항목 [Enter={auto_item}] > " if auto_item else "  AI 추천 항목(직접 입력) > ", auto_item)
        ok = ask(f"  사용자가 그대로 선택? o/x [Enter={auto_ok or '?'}] > ", auto_ok or "").upper()
        while ok not in ("O", "X"):
            ok = ask("  o 또는 x 로 입력 > ").upper()
        if auto_ok and ok != auto_ok:
            method = "자동+수정"
        man = ask(f"  응답 시간(초) — 화면 녹화로 잰 값 입력, Enter={'자동 ' + str(auto_rt) if auto_rt is not None else '없음'} > ")
        man_v = None
        if man:
            try:
                man_v = float(man)
            except ValueError:
                print("   숫자가 아니라 무시")
        rt = man_v if man_v is not None else auto_rt
        memo = ask("  메모(선택) > ")
        rows.append({"번호": len(rows) + 1, "시각": datetime.datetime.fromtimestamp(t0).strftime("%Y-%m-%d %H:%M:%S"),
                     "종류": kind, "AI추천": item, "그대로선택": ok,
                     "응답시간_초": "" if rt is None else f"{rt:.2f}",
                     "응답시간_자동_초": "" if auto_rt is None else f"{auto_rt:.2f}",
                     "응답시간_수동_초": "" if man_v is None else f"{man_v:.2f}", "판정방법": method, "메모": memo})
        save_rows(path, E1_FIELDS, rows)
        print(f"  ✓ 기록 {len(rows)}번 저장 ({path})\n")


# ═════════════════════ 실험 2 ═════════════════════
def exp2(d, goal, dests, criterion):
    path = d / "exp2.csv"
    rows = load_rows(path)
    print(f"\n[실험 2] 자율주행 안내 성공률 — 1회 = 출발 → 도착 안내 → 초기 위치 복귀(정렬까지)")
    print(f"  목적지 A = {dests[0]} · B = {dests[1]} · 성공 기준: {criterion}")
    print("  ※ 현재 Nav2 도착 허용 오차는 위치 0.45 m·방향 제한 없음(agv.yaml) — 기준이 이보다 엄하면 실측해서 판정하세요.\n")
    while True:
        for i, dn in enumerate(dests):
            rr = [r for r in rows if r["목적지"] == dn]
            print(f"── {'AB'[i]} {dn}: {len(rr)}/{goal}회 · 성공 {sum(r['성공'] == 'O' for r in rr)}", end="   ")
        print()
        k = ask("  다음 시도 [a] A  [b] B  [u] 직전 기록 지우기  [t] 표 보기  [q] 끝 > ").lower()
        if k == "q":
            break
        if k == "t":
            summary(d, goal, save=False)
            continue
        if k == "u":
            if rows:
                r = rows.pop()
                save_rows(path, E2_FIELDS, rows)
                print(f"  지움: {r['번호']}번 {r['목적지']}")
            continue
        if k not in ("a", "b"):
            continue
        dest = dests[0] if k == "a" else dests[1]
        nav_t, ret_t = Tail(NAVLOG), Tail(RETLOG)
        print(f"  ▶ 키오스크에서 '{dest}' 안내를 시작해 주세요. 상태를 자동으로 따라갑니다(Ctrl+C = 중단하고 바로 기록).")
        marks, last, t_start = {}, None, time.time()
        nav_lines, ret_lines = [], []
        try:
            while time.time() - t_start < 1200:
                st = read_status()
                s = st.get("state", "")
                if s != last:
                    now = time.time()
                    if s == "moving" and "moving" not in marks:
                        marks["moving"] = now
                    elif s and s not in marks and "moving" in marks:
                        marks[s] = now
                    if "moving" in marks:
                        print(f"   {datetime.datetime.now():%H:%M:%S} 상태: {s} {st.get('place', '')}", flush=True)
                    last = s
                    if s == "idle" and "moving" in marks and ("returning" in marks or "aligning" in marks):
                        break
                nav_lines += nav_t.read()
                ret_lines += ret_t.read()
                time.sleep(0.3)
        except KeyboardInterrupt:
            print("\n   중단 — 지금까지 자료로 기록")
        nav_lines += nav_t.read()
        ret_lines += ret_t.read()
        fail_prog = sum("Failed to make progress" in l for l in nav_lines)
        recov = sum("Attempting" in l and "recoveries_server" in l for l in nav_lines)
        novalid = sum("No valid trajectories" in l for l in nav_lines)
        goal_failed = sum("Goal failed" in l for l in nav_lines)
        align = next((l.split("[return]")[-1].strip() for l in reversed(ret_lines) if "벽 정렬 완료" in l or "벽 정렬 미완료" in l), "")
        t_arr = (marks["arrived"] - marks["moving"]) if "arrived" in marks and "moving" in marks else None
        t_all = ((marks.get("idle") or time.time()) - marks["moving"]) if "moving" in marks else None
        print(f"   자동 기록: 출발→도착 {t_arr:.0f}초" if t_arr else "   자동 기록: 도착 확인 못 함", end="")
        print(f" · 전체 {t_all:.0f}초" if t_all else "", end="")
        print(f" · Nav2 진행 실패 {fail_prog} · 복구 {recov} · 길 못 찾음 {novalid}" + (f" · 목표 실패 {goal_failed}" if goal_failed else ""))
        if align:
            print(f"   복귀 정렬: {align[:90]}")
        auto_fail = goal_failed > 0 or "arrived" not in marks or "idle" not in marks
        pe = ask("  목표 지점 실측 위치 오차 cm (테이프, 선택 Enter=건너뜀) > ")
        ye = ask("  실측 방향 오차 ° (선택) > ")
        over = criterion_exceeded(criterion, pe, ye)
        if over:
            print(f"   성공 기준 초과: {over}")
        dflt = "X" if (auto_fail or over) else "O"
        ok = ask(f"  사람 손 안 대고 끝까지 완료 + 기준 충족? o/x [Enter={dflt}] > ", dflt).upper()
        while ok not in ("O", "X"):
            ok = ask("  o 또는 x > ").upper()
        reason = ""
        if ok == "X":
            sug = 3 if over else (2 if (fail_prog or recov) else (4 if "arrived" in marks and "idle" not in marks else 7))
            print("  실패 이유: " + " · ".join(f"[{i + 1}] {r}" for i, r in enumerate(FAIL_REASONS)))
            c = ask(f"   번호 [Enter={sug}] > ", str(sug))
            reason = FAIL_REASONS[int(c) - 1] if c.isdigit() and 1 <= int(c) <= len(FAIL_REASONS) else c
            if reason == "기타":
                reason = "기타: " + ask("   내용 > ")
        memo = ask("  메모(선택) > ")
        rows.append({"번호": len(rows) + 1, "시각": datetime.datetime.fromtimestamp(t_start).strftime("%Y-%m-%d %H:%M:%S"),
                     "목적지": dest, "성공": ok, "실패이유": reason,
                     "출발→도착_초": f"{t_arr:.1f}" if t_arr else "", "전체_초": f"{t_all:.1f}" if t_all else "",
                     "Nav2진행실패": fail_prog, "Nav2복구": recov, "길못찾음": novalid, "복귀정렬": align[:80],
                     "실측위치오차_cm": pe, "실측방향오차_도": ye, "메모": memo})
        save_rows(path, E2_FIELDS, rows)
        print(f"  ✓ 기록 {len(rows)}번 저장 ({path})\n")


def criterion_exceeded(criterion, pe, ye):
    """성공 기준 글('30cm 이내, 방향 10° 이내')의 숫자와 실측값 비교 → 넘었으면 설명, 아니면 ''"""
    out = []
    mc = re.search(r"(\d+(?:\.\d+)?)\s*cm", criterion)
    md = re.search(r"(\d+(?:\.\d+)?)\s*(?:°|도)", criterion)
    try:
        if mc and pe and float(pe) > float(mc.group(1)):
            out.append(f"위치 {pe}cm > {mc.group(1)}cm")
        if md and ye and abs(float(ye)) > float(md.group(1)):
            out.append(f"방향 {ye}° > {md.group(1)}°")
    except ValueError:
        pass
    return ", ".join(out)


# ═════════════════════ 표 ═════════════════════
def summary(d, goal, save=True):
    r1, r2 = load_rows(d / "exp1.csv"), load_rows(d / "exp2.csv")
    out = ["## 표 1. AI 안내 수용률·응답 시간", "",
           "| 항목 | 횟수 | 그대로 선택(O) | 수용률 | 응답 시간 평균(초) | 표준편차 | 최소~최대 |", "|---|---|---|---|---|---|---|"]
    for label, kind in (("Item A · 접수 안내(진료과 추천)", "접수"), ("Item B · 위치 안내(목적지)", "위치")):
        rr = [r for r in r1 if r["종류"] == kind]
        o = sum(r["그대로선택"] == "O" for r in rr)
        ts = [float(r["응답시간_초"]) for r in rr if r["응답시간_초"]]
        out.append(f"| {label} | {len(rr)} | {o} | {pct(o, len(rr))} | "
                   f"{statistics.mean(ts):.2f} | {statistics.stdev(ts):.2f} | {min(ts):.2f}~{max(ts):.2f} |" if len(ts) >= 2 else
                   f"| {label} | {len(rr)} | {o} | {pct(o, len(rr))} | {ts[0]:.2f} | - | - |" if ts else
                   f"| {label} | {len(rr)} | {o} | {pct(o, len(rr))} | - | - | - |")
    out += ["", "## 표 2. 자율주행 안내 성공률", "",
            "| 목적지 | 횟수 | 성공 | 성공률 | 평균 소요(출발→도착, 초) | 실패 이유 |", "|---|---|---|---|---|---|"]
    dests = list(dict.fromkeys(r["목적지"] for r in r2))
    for dn in dests:
        rr = [r for r in r2 if r["목적지"] == dn]
        s = sum(r["성공"] == "O" for r in rr)
        ta = [float(r["출발→도착_초"]) for r in rr if r["출발→도착_초"]]
        reasons = {}
        for r in rr:
            if r["성공"] == "X":
                reasons[r["실패이유"] or "미기재"] = reasons.get(r["실패이유"] or "미기재", 0) + 1
        out.append(f"| {dn} | {len(rr)} | {s} | {pct(s, len(rr))} | {statistics.mean(ta):.1f} | "
                   f"{', '.join(f'{k} {v}' for k, v in reasons.items()) or '-'} |" if ta else
                   f"| {dn} | {len(rr)} | {s} | {pct(s, len(rr))} | - | {', '.join(f'{k} {v}' for k, v in reasons.items()) or '-'} |")
    if r2:
        s = sum(r["성공"] == "O" for r in r2)
        out.append(f"| 합계 | {len(r2)} | {s} | {pct(s, len(r2))} | | |")
    cfg = load_cfg(d)
    out += ["", f"- 항목당 목표 {goal}회 · 성공 기준: {cfg.get('criterion', '-')} · 기록: {d}",
            "- 응답 시간: 화면 녹화로 잰 값이 있으면 그 값, 없으면 서버 자동값(녹음기가 말 끝을 들은 순간 → 결과 응답)"]
    text = "\n".join(out)
    print("\n" + text + "\n")
    if save:
        (d / "summary.md").write_text(text + "\n", encoding="utf-8")
        print(f"저장: {d / 'summary.md'}")


def load_cfg(d):
    try:
        return json.loads((d / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser(description="논문 실험 진행·기록 도우미")
    ap.add_argument("what", choices=["1", "2", "표", "table"])
    ap.add_argument("--dir", default="/mnt/ssd/experiments/main")
    ap.add_argument("--goal", type=int, default=20)
    a = ap.parse_args()
    d = Path(a.dir)
    d.mkdir(parents=True, exist_ok=True)
    cfg = load_cfg(d)
    if a.what == "2" and ("dests" not in cfg or "criterion" not in cfg):
        print("[처음 한 번 설정] 실험 2 목적지와 성공 기준")
        A = ask("  목적지 A 이름 [Enter=외과] > ", "외과")
        B = ask("  목적지 B 이름 [Enter=내과] > ", "내과")
        c = ask("  성공 기준 [Enter=사람 개입 없이 출발→도착 안내→복귀 완료, 목표 지점 30cm 이내] > ",
                "사람 개입 없이 출발→도착 안내→복귀 완료, 목표 지점 30cm 이내")
        cfg.update({"dests": [A, B], "criterion": c})
        (d / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.what == "1":
        exp1(d, a.goal)
    elif a.what == "2":
        exp2(d, a.goal, cfg["dests"], cfg["criterion"])
    summary(d, a.goal, save=True)


if __name__ == "__main__":
    sys.exit(main())
