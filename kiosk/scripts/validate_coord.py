#!/usr/bin/env python3
# =========================================================================
# validate_coord.py — 안내도↔실제맵 좌표 변환 검증 (로봇 미이동)
# 앵커(원무과·내과·외과)로 affine을 맞추고, leave-one-out 교차검증으로
# "임의 지점 변환"의 기대 오차를 미터로 측정한다.
# =========================================================================
import numpy as np

# 안내도 방 중심 (flat_map_guide.png px, 1804x872)
GUIDE = {"내과": (1206, 252), "외과": (1354, 252), "원무과": (1271, 417)}
# map_labels.json 실제 좌표 (nav_goal)
NAV = {"원무과": (-23.19, 51.337), "내과": (-25.02, 47.132), "외과": (-23.335, 57.747)}


def fit_similarity(n2, gmap):
    g = np.array([GUIDE[n] for n in n2], float)
    m = np.array([gmap[n] for n in n2], float)
    dg, dm = g[1] - g[0], m[1] - m[0]
    s = np.linalg.norm(dm) / np.linalg.norm(dg)
    ang = np.arctan2(dm[1], dm[0]) - np.arctan2(dg[1], dg[0])
    R = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
    t = m[0] - s * R @ g[0]
    return lambda p: s * R @ np.array(p, float) + t


def main():
    names = list(GUIDE.keys())
    print("=== leave-one-out (2점 similarity로 held-out 예측) ===")
    errs = []
    for hold in names:
        others = [n for n in names if n != hold]
        f = fit_similarity(others, NAV)
        e = float(np.linalg.norm(f(GUIDE[hold]) - np.array(NAV[hold])))
        errs.append(e)
        print(f"  {hold}: 예측오차 {e:.2f} m")
    print(f"평균 {np.mean(errs):.2f} m  → 임의 지점 변환 신뢰도 낮음")
    print("결론: 알려진 방은 map_labels.json nav_goal 직접 조회를 사용.")


if __name__ == "__main__":
    main()
