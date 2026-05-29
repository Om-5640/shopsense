/**
 * Two stores:
 *  - useAppStore: persisted to localStorage. Holds search history for the home page
 *    RecentSearches section and user signals.
 *  - useResultsStore: transient. Holds the live rubric weights + ranked products
 *    for the results page; re-ranking happens here with no API call.
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ScoredProduct, Rubric, WeightedCriterion } from './types'
import { rerank, extractWeights } from './rerank'

// ─── lightweight history entry (what RecentSearches renders) ─────────────────

export interface HistoryEntry {
  id: string
  query: string
  category: string
  region: string
  timestamp: number // epoch ms
  topProduct?: { name: string; score: number }
}

// ─── useAppStore — persisted ──────────────────────────────────────────────────

interface AppState {
  searchHistory: HistoryEntry[]
  addSearchHistory: (entry: HistoryEntry) => void
  removeSearchHistory: (id: string) => void
  clearHistory: () => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      searchHistory: [],

      addSearchHistory: (entry) =>
        set((state) => ({
          searchHistory: [
            entry,
            ...state.searchHistory.filter((h) => h.id !== entry.id),
          ].slice(0, 50),
        })),

      removeSearchHistory: (id) =>
        set((state) => ({
          searchHistory: state.searchHistory.filter((h) => h.id !== id),
        })),

      clearHistory: () => set({ searchHistory: [] }),
    }),
    {
      name: 'shopresearch-history',
    },
  ),
)

// ─── useResultsStore — transient ──────────────────────────────────────────────

interface ResultsState {
  searchId: string | null
  query: string
  category: string
  region: string
  createdAt: string | null

  rubric: Rubric | null
  // Live weights — user can slide these without touching the original rubric
  weights: Record<string, number>
  products: ScoredProduct[]

  // Initialize from API response
  initResults: (data: {
    searchId: string
    query: string
    category: string
    region: string
    createdAt: string
    rubric: Rubric
    products: ScoredProduct[]
  }) => void

  // Called by slider — triggers instant re-rank via rerank()
  setWeight: (criterionName: string, value: number) => void

  // Reset all weights to rubric defaults
  resetWeights: () => void

  // Selected products for comparison (keyed by product name)
  compareSet: Set<string>
  toggleCompare: (productName: string) => void
  clearCompare: () => void
}

export const useResultsStore = create<ResultsState>((set, get) => ({
  searchId: null,
  query: '',
  category: '',
  region: '',
  createdAt: null,
  rubric: null,
  weights: {},
  products: [],
  compareSet: new Set(),

  initResults({ searchId, query, category, region, createdAt, rubric, products }) {
    const weights = extractWeights(rubric.weighted_criteria)
    set({ searchId, query, category, region, createdAt, rubric, weights, products })
  },

  setWeight(criterionName, value) {
    const weights = { ...get().weights, [criterionName]: value }
    const products = rerank(get().products, weights)
    set({ weights, products })
  },

  resetWeights() {
    const rubric = get().rubric
    if (!rubric) return
    const weights = extractWeights(rubric.weighted_criteria)
    const products = rerank(get().products, weights)
    set({ weights, products })
  },

  toggleCompare(productName) {
    const s = new Set(get().compareSet)
    if (s.has(productName)) {
      s.delete(productName)
    } else if (s.size < 3) {
      s.add(productName)
    }
    set({ compareSet: s })
  },

  clearCompare() {
    set({ compareSet: new Set() })
  },
}))

// ─── helper: derive RubricSidebar-compatible criteria from store ──────────────

export function deriveSidebarCriteria(
  rubric: Rubric,
  weights: Record<string, number>,
): Array<{ id: string; label: string; weight: number; rationale: string }> {
  return rubric.weighted_criteria.map((c: WeightedCriterion) => ({
    id: c.name,
    label: c.label,
    weight: weights[c.name] ?? c.weight,
    rationale: c.rationale,
  }))
}
