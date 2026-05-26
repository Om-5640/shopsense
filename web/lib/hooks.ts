/**
 * SWR-cached hooks for all GET endpoints.
 *
 * Why: without SWR, navigating back to /history or /memory triggers a full
 * re-fetch on every render. SWR deduplicates, caches in-memory, and re-fetches
 * only on window focus / mount after stale interval.
 *
 * Usage:
 *   const { data: searches, isLoading } = useSearchHistory()
 *   const { data: signals } = useMemorySignals()
 */

'use client'

import useSWR from 'swr'
import axios from 'axios'
import type { SearchResult, UserSignal, ProductMemory, MemoryContext } from './types'

const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

const fetcher = (url: string) =>
  axios.get(`${BASE}${url}`).then((r) => r.data)

// Stale-while-revalidate intervals
const FRESH_30S  = { dedupingInterval: 30_000, revalidateOnFocus: true }
const FRESH_5M   = { dedupingInterval: 300_000, revalidateOnFocus: false }
const IMMUTABLE  = { revalidateOnFocus: false, revalidateOnReconnect: false, dedupingInterval: 3_600_000 }

// ── Searches / history ────────────────────────────────────────────────────────

export function useSearchHistory(limit = 20) {
  return useSWR<{ searches: SearchResult[] }>(
    `/api/searches?limit=${limit}`,
    fetcher,
    FRESH_30S,
  )
}

export function useSearch(searchId: string | null) {
  return useSWR<SearchResult>(
    searchId ? `/api/search/${searchId}` : null,
    fetcher,
    FRESH_5M,
  )
}

// ── Memory ────────────────────────────────────────────────────────────────────

export function useMemorySignals(category?: string) {
  const url = category
    ? `/api/memory/signals?category=${encodeURIComponent(category)}`
    : '/api/memory/signals'
  return useSWR<{ signals: UserSignal[] }>(url, fetcher, FRESH_5M)
}

export function useMemoryProducts(status?: string) {
  const url = status
    ? `/api/memory/products?status=${encodeURIComponent(status)}`
    : '/api/memory/products'
  return useSWR<{ products: ProductMemory[] }>(url, fetcher, FRESH_5M)
}

export function useMemoryContext(category: string | null, query?: string) {
  const url = category
    ? `/api/memory/context?category=${encodeURIComponent(category)}${query ? `&query=${encodeURIComponent(query)}` : ''}`
    : null
  return useSWR<MemoryContext>(url, fetcher, FRESH_5M)
}

// ── Provider status ───────────────────────────────────────────────────────────

export function useProviderStatus() {
  return useSWR<{
    providers: Record<string, {
      configured: boolean
      session_alive: boolean
      circuit_blocked: boolean
      circuit_detail: Record<string, unknown>
    }>
  }>('/api/providers/status', fetcher, FRESH_30S)
}

// ── Profile ───────────────────────────────────────────────────────────────────

export function useProfile(category: string | null) {
  return useSWR(
    category ? `/api/profile/${encodeURIComponent(category)}` : null,
    fetcher,
    FRESH_5M,
  )
}

// ── Health ────────────────────────────────────────────────────────────────────

export function useHealth() {
  return useSWR('/api/health', fetcher, FRESH_30S)
}
