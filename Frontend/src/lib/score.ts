/**
 * 백엔드 similarity_score는 BGE 리랭커 원점수(로짓)라 0~1 범위가 아니다 (예: -3, 0.73, 6.2).
 * 출처 판단 기준값(0.7 등)은 이 원점수 척도로 맞춰져 있으므로 백엔드 값은 그대로 두고,
 * 화면에 보여줄 때만 시그모이드로 0~100% 범위로 바꾼다.
 */
export function formatRelevance(score: number): string {
  const pct = 100 / (1 + Math.exp(-score))
  return `${pct.toFixed(1)}%`
}
