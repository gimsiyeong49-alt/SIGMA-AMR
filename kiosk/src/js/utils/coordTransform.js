// =========================================================================
// coordTransform.js — 안내도 이미지 좌표 ↔ 실제 맵 좌표(m) 변환 유틸
//
// 기준 정보:
//  - SLAM 맵: my_map.pgm, 원점 [-39.2, -13.7], 해상도 0.05 m/px
//  - 안내도(flat_map_guide.png)는 SLAM 맵과 별개로 그린 "그림"이라
//    직접 스케일 관계가 없다 → 기준점(anchor) 대응으로 affine을 맞춘다.
//
// ★ 중요(항목 9 검증 결과) ★
//   현재 앵커는 3곳(원무과·내과·외과)뿐이고 안내도가 스타일화된 그림이라,
//   leave-one-out 교차검증 오차가 10~18m로 매우 크다(→ 신뢰 불가).
//   따라서 "알려진 방"의 실제 목표는 이 변환이 아니라 map_labels.json의
//   nav_goal 직접 조회를 쓴다(robotController + 서버 /goal). 이 파일의 변환은
//   "map_labels에 없는 임의 지점"의 근사 추정용이며, 앵커가 늘면 정확해진다.
// =========================================================================

// 앵커: 안내도 방 중심(px, flat_map_guide.png 1804x872) ↔ 실제 맵 좌표(m, nav_goal)
export const ANCHORS = [
  { name: '내과',   px: [1206, 252], map: [-25.02, 47.132] },
  { name: '외과',   px: [1354, 252], map: [-23.335, 57.747] },
  { name: '원무과', px: [1271, 417], map: [-23.19, 51.337] },
];

// 3점으로 affine(2x3) 정확 해: [mx,my] = P·[px,py,1]
function solveAffine(anchors) {
  // G(3x3) · P(3x2) = M(3x2) → P = inv(G)·M
  const G = anchors.map((a) => [a.px[0], a.px[1], 1]);
  const M = anchors.map((a) => [a.map[0], a.map[1]]);
  const inv = invert3(G);
  // P = inv · M  (3x3 · 3x2)
  const P = [[0, 0], [0, 0], [0, 0]];
  for (let i = 0; i < 3; i++)
    for (let j = 0; j < 2; j++)
      for (let k = 0; k < 3; k++) P[i][j] += inv[i][k] * M[k][j];
  return P; // 3x2
}

function invert3(m) {
  const [a, b, c] = m[0], [d, e, f] = m[1], [g, h, i] = m[2];
  const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g;
  const det = a * A + b * B + c * C;
  if (Math.abs(det) < 1e-9) throw new Error('anchor 행렬 특이(변환 불가)');
  const D = -(b * i - c * h), E = a * i - c * g, F = -(a * h - b * g);
  const Gg = b * f - c * e, H = -(a * f - c * d), I = a * e - b * d;
  return [[A / det, D / det, Gg / det], [B / det, E / det, H / det], [C / det, F / det, I / det]];
}

const _P = solveAffine(ANCHORS);

/**
 * 안내도 이미지 좌표(px) → 실제 맵 좌표(m). (근사 — 위 주의 참고)
 * @param {number} px @param {number} py
 * @returns {{x:number,y:number}}
 */
export function guideToMap(px, py) {
  return {
    x: _P[0][0] * px + _P[1][0] * py + _P[2][0],
    y: _P[0][1] * px + _P[1][1] * py + _P[2][1],
  };
}

/** 안내도 방 사각(%)의 중심 px → 맵 좌표. locations.js rect(%)를 받는다. */
export function guideRectToMap(rect, imgW = 1804, imgH = 872) {
  const px = (rect.x + rect.w / 2) / 100 * imgW;
  const py = (rect.y + rect.h / 2) / 100 * imgH;
  return guideToMap(px, py);
}
