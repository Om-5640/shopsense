/**
 * Pure-JS re-ranking math — mirrors scorer.py's recompute_with_new_weights().
 * Called every time a rubric slider changes. No API call, <100ms response.
 */

import type { ScoredProduct, WeightedCriterion } from './types'

export function rerank(
  products: ScoredProduct[],
  newWeights: Record<string, number>,
): ScoredProduct[] {
  return [...products]
    .map((p) => {
      let weightedTotal = 0
      let maxPossible = 0

      const newScores = p.scores.map((s) => {
        const weight = newWeights[s.criterion] ?? s.weight
        weightedTotal += s.score * weight
        maxPossible += 10 * weight
        return { ...s, weight, weighted_contribution: Math.round(s.score * weight * 10) / 10 }
      })

      const percentage =
        maxPossible > 0 ? Math.round((weightedTotal / maxPossible) * 1000) / 10 : 0

      return {
        ...p,
        scores: newScores,
        weighted_total: Math.round(weightedTotal * 10) / 10,
        max_possible: Math.round(maxPossible * 10) / 10,
        percentage,
      }
    })
    .sort((a, b) => b.weighted_total - a.weighted_total)
}

/** Extract current weights from a rubric into a flat Record for rerank(). */
export function extractWeights(criteria: WeightedCriterion[]): Record<string, number> {
  return Object.fromEntries(criteria.map((c) => [c.name, c.weight]))
}
