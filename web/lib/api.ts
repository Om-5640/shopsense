/**
 * Typed API client for the FastAPI backend.
 * All calls go to NEXT_PUBLIC_API_URL (default: http://localhost:8000).
 */

import axios from 'axios'
import { getSession } from 'next-auth/react'
import type {
  Rubric,
  SearchResult,
  InterviewQuestion,
  QAEntry,
  Criterion,
  ProductPrice,
  UserSignal,
  ProductMemory,
  MemoryContext,
  ProcessMessageResult,
  UserIntent,
  PipelineDiagnostics,
} from './types'

const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

// ---------------------------------------------------------------------------
// Per-browser session ID — isolates memory/signals between different users.
// Generated once, persisted in localStorage, sent on every API request.
// ---------------------------------------------------------------------------
export function getOrCreateSessionId(): string {
  if (typeof window === 'undefined') return 'default'
  const key = 'shopsense_session_id'
  let sid = localStorage.getItem(key)
  if (!sid || sid.length < 8) {
    // Generate a compact UUID-like ID
    sid = 'ss_' + Array.from(crypto.getRandomValues(new Uint8Array(16)))
      .map(b => b.toString(16).padStart(2, '0'))
      .join('')
    localStorage.setItem(key, sid)
  }
  return sid
}

const client = axios.create({ baseURL: BASE })

// Attach session ID and optional auth token on every request (client-side only)
client.interceptors.request.use(async (config) => {
  config.headers['X-Session-ID'] = getOrCreateSessionId()
  if (typeof window !== 'undefined') {
    const session = await getSession()
    if (session?.accessToken) {
      config.headers['Authorization'] = `Bearer ${session.accessToken}`
    }
  }
  return config
})

// Handle rate limiting globally
client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (typeof window !== 'undefined') {
      const status = err?.response?.status
      if (status === 429) {
        import('sonner').then(({ toast }) => {
          toast.error('Too many requests — please wait a moment and try again.')
        })
      }
      // Note: 401 is intentionally NOT handled here. Auto-signOut on any backend
      // 401 caused an infinite login loop: backend token mismatch → 401 → signOut
      // → memory page shows "sign in" → user signs in → same 401 → signOut → loop.
      // Pages that require auth show their own in-page sign-in prompt via useSession().
    }
    return Promise.reject(err)
  }
)

// ── Detection ────────────────────────────────────────────────────────────────

export async function detectCategory(query: string, forcedCategory?: string) {
  const { data } = await client.post('/api/detect', {
    query,
    forced_category: forcedCategory ?? null,
  })
  return data as {
    category: string
    confidence: string
    needs_disambiguation: boolean
    options: { slug: string; label: string }[]
    region: string
    needs_region_clarification: boolean
    primary_noun: string
  }
}

// ── Criteria ─────────────────────────────────────────────────────────────────

export async function getCriteria(category: string) {
  const { data } = await client.post('/api/criteria', { category })
  return data as { category: string; criteria: Criterion[] }
}

// ── Interview ─────────────────────────────────────────────────────────────────

export async function getNextQuestion(
  category: string,
  criteria: Criterion[],
  qaHistory: QAEntry[],
  initialQuery?: string,
  primaryNoun?: string,
): Promise<InterviewQuestion> {
  const { data } = await client.post('/api/interview/next', {
    category,
    criteria,
    qa_history: qaHistory,
    initial_query: initialQuery ?? '',
    primary_noun: primaryNoun ?? '',
  })
  return data
}

export async function processInterviewMessage(body: {
  category: string
  criteria: Criterion[]
  current_question: InterviewQuestion
  message: string
  qa_history: QAEntry[]
}): Promise<ProcessMessageResult> {
  const { data } = await client.post('/api/interview/process_message', body)
  return data as ProcessMessageResult
}

export async function summarizeInterview(
  category: string,
  qaHistory: QAEntry[],
): Promise<{ preferences_summary: string; intent: UserIntent }> {
  const { data } = await client.post('/api/interview/summarize', {
    category,
    qa_history: qaHistory,
  })
  return data
}

// ── Rubric ────────────────────────────────────────────────────────────────────

export async function generateRubric(
  category: string,
  criteria: Criterion[],
  profile: Record<string, unknown>,
): Promise<Rubric> {
  const { data } = await client.post('/api/rubric', { category, criteria, profile })
  return data
}

// ── Search lifecycle ──────────────────────────────────────────────────────────

export async function startSearch(body: {
  query: string
  category: string
  region: string
  profile: Record<string, unknown>
  rubric: Rubric
  options?: Record<string, unknown>
  qa_history?: QAEntry[]
  primary_noun?: string
}): Promise<{ search_id: string; deduplicated?: boolean }> {
  const { data } = await client.post('/api/search', {
    options: {},
    qa_history: [],
    primary_noun: '',
    ...body,
  })
  return data
}

export async function getSearchResult(id: string): Promise<SearchResult> {
  const { data } = await client.get(`/api/search/${id}`)
  return _parseSearch(data)
}

export async function cancelSearch(id: string): Promise<{ cancelled: boolean }> {
  const { data } = await client.post(`/api/search/${id}/cancel`)
  return data
}

export async function getDiagnostics(id: string): Promise<PipelineDiagnostics> {
  const { data } = await client.get(`/api/search/${id}/diagnostics`)
  return data as PipelineDiagnostics
}

export async function listSearches(limit = 50, offset = 0): Promise<SearchResult[]> {
  const { data } = await client.get('/api/searches', { params: { limit, offset } })
  return (data.searches as SearchResult[]).map(_parseSearch)
}

// ── Profile ───────────────────────────────────────────────────────────────────

export async function getProfile(category: string) {
  const { data } = await client.get(`/api/profile/${encodeURIComponent(category)}`)
  return data
}

export async function saveProfile(category: string, profile: Record<string, unknown>) {
  await client.post(`/api/profile/${encodeURIComponent(category)}`, { profile })
}

// ── Prices ────────────────────────────────────────────────────────────────────

export async function fetchPrices(
  products: string[],
  region: string,
): Promise<{ prices: ProductPrice[] }> {
  const { data } = await client.post('/api/prices', { products, region })
  return data
}

// ── Health / Providers ────────────────────────────────────────────────────────

export async function getHealth() {
  const { data } = await client.get('/api/health')
  return data
}

const _PROVIDER_LABELS: Record<string, { name: string; model: string }> = {
  groq: { name: 'Groq', model: 'llama-3.3-70b-versatile' },
  gemini: { name: 'Google Gemini', model: 'gemini-2.5-flash' },
  mistral: { name: 'Mistral', model: 'mistral-small-latest' },
  cerebras: { name: 'Cerebras', model: 'llama-3.3-70b' },
  openrouter: { name: 'OpenRouter', model: 'mixed' },
}

export async function getProvidersStatus(): Promise<{
  providers: Array<{
    id: string
    name: string
    model: string
    status: 'active' | 'quota' | 'inactive' | 'error'
    requests_today?: number
    last_error?: string | null
  }>
}> {
  const { data } = await client.get('/api/providers/status')
  // Backend returns {providers: {groq: {configured, session_alive, circuit_blocked, ...}, ...}}
  const raw: Record<string, { configured: boolean; session_alive: boolean; circuit_blocked: boolean }> =
    data.providers ?? {}
  const providers = Object.entries(raw).map(([id, info]) => ({
    id,
    name: _PROVIDER_LABELS[id]?.name ?? id,
    model: _PROVIDER_LABELS[id]?.model ?? 'unknown',
    status: (!info.configured
      ? 'inactive'
      : info.circuit_blocked
      ? 'error'
      : info.session_alive
      ? 'active'
      : 'quota') as 'active' | 'quota' | 'inactive' | 'error',
    last_error: null,
  }))
  return { providers }
}

// ── Memory ────────────────────────────────────────────────────────────────────

export async function getMemoryContext(query: string, category: string): Promise<MemoryContext> {
  try {
    const { data } = await client.get('/api/memory/context', { params: { q: query, category } })
    return data
  } catch {
    return { signals: [], profile_summary: '', has_memory: false }
  }
}

export async function listMemorySignals(limit = 100): Promise<{ signals: UserSignal[]; count: number }> {
  const { data } = await client.get('/api/memory/signals', { params: { limit } })
  return data
}

export async function deleteMemorySignal(id: string): Promise<void> {
  await client.delete(`/api/memory/signals/${id}`)
}

export async function listProductMemories(limit = 100): Promise<{ products: ProductMemory[]; count: number }> {
  const { data } = await client.get('/api/memory/products', { params: { limit } })
  return data
}

export async function updateProductStatus(
  productName: string,
  status: string,
  category: string,
  feedback?: string,
  ourScore?: number,
): Promise<void> {
  await client.post(`/api/memory/products/${encodeURIComponent(productName)}/status`, {
    status,
    category,
    feedback: feedback ?? null,
    our_score: ourScore ?? null,
  })
}

export async function deleteProductMemory(productName: string): Promise<void> {
  await client.delete(`/api/memory/products/${encodeURIComponent(productName)}`)
}

export async function recordPurchase(
  productName: string,
  category: string,
  feedback?: string,
  ourScore?: number,
): Promise<{ signals_extracted: number }> {
  const { data } = await client.post('/api/memory/bought', {
    product_name: productName,
    category,
    feedback: feedback ?? null,
    our_score: ourScore ?? null,
  })
  return data
}

export async function wipeAllMemory(): Promise<void> {
  await client.delete('/api/memory/all')
}

// ── Export & Sharing ─────────────────────────────────────────────────────────

/** Trigger a CSV download for the given search result. */
export function downloadCSV(searchId: string): void {
  const url = `${BASE}/api/search/${searchId}/csv`
  const a = document.createElement('a')
  a.href = url
  a.download = `shopsense_${searchId.slice(0, 8)}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

/** Trigger a PDF download for the given search result. */
export function downloadPDF(searchId: string): void {
  const url = `${BASE}/api/search/${searchId}/pdf`
  const a = document.createElement('a')
  a.href = url
  a.download = `shopsense_${searchId.slice(0, 8)}.pdf`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

/** Create a shareable short link and return the URL. */
export async function createShareLink(searchId: string): Promise<string> {
  const { data } = await client.post(`/api/search/${searchId}/share`)
  return data.share_url as string
}

/** Resolve a share token to a search_id (used by /s/[token] page). */
export async function resolveShareToken(token: string): Promise<string> {
  const { data } = await client.get(`/api/share/${token}`)
  return data.search_id as string
}

// ── Parse JSON string fields from SQLite rows ─────────────────────────────────

function _parseSearch(row: SearchResult): SearchResult {
  const jsonCols = ['profile', 'rubric', 'analysis', 'scoredProducts'] as const
  const out = { ...row } as Record<string, unknown>
  for (const col of jsonCols) {
    if (typeof out[col] === 'string') {
      try {
        out[col] = JSON.parse(out[col] as string)
      } catch {
        // leave as-is
      }
    }
  }
  return out as unknown as SearchResult
}
