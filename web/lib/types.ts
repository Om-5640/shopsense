// Shared TypeScript types mirroring the Python backend data structures

export interface Criterion {
  name: string
  label: string
  description?: string
  high_score_means?: string
  low_score_means?: string
}

export interface WeightedCriterion extends Criterion {
  weight: number
  rationale: string
}

export interface Rubric {
  category?: string
  weighted_criteria: WeightedCriterion[]
  based_on_profile?: string
  last_updated?: string
}

export interface Score {
  criterion: string
  label: string
  weight: number
  score: number
  evidence: string
  weighted_contribution: number
}

export interface RetailerPrice {
  name: string
  price_inr?: number
  price_usd?: number
  mrp_inr?: number
  discount_pct?: number
  url: string
  in_stock?: boolean
  rating?: number
  review_count?: number
  image_url?: string
  title?: string
  is_search?: boolean
}

export interface ProductPrice {
  product_name: string
  retailers: RetailerPrice[]
  best_price?: { retailer: string; price_inr?: number; price_usd?: number }
  price_range?: [number, number]
  currency: string
  fetched_at: string
  is_fallback?: boolean
}

// Rich community data extracted from Reddit + review sources
export interface ProductComplaint {
  text: string
  confidence: 'confirmed' | 'reported' | 'single' | string
}

export interface SentimentRecord {
  comment_text: string
  sentiment: 'positive' | 'negative' | 'neutral'
  confidence: number
  reason: string
}

export interface AnalysisProduct {
  name: string
  mention_count?: number
  distinct_recommenders?: number
  positive_mentions?: number
  negative_mentions?: number
  praise?: string[]
  complaints?: ProductComplaint[]
  representative_quote?: string
  sources?: string[]
  signal_strength?: string
  // v9: precise mention pipeline fields
  sentiment_score?: number
  dominant_sentiment?: string
  sentiment_records?: SentimentRecord[]
}

export interface ScoredProduct {
  clientKey?: string
  name: string
  signal_strength: 'high' | 'medium' | 'low' | string
  scores: Score[]
  weighted_total: number
  max_possible: number
  percentage: number
  explanation?: string
  // Community data (merged from analysis.products)
  mention_count?: number
  distinct_recommenders?: number
  positive_mentions?: number
  negative_mentions?: number
  praise?: string[]
  complaints?: ProductComplaint[]
  representative_quote?: string
  sources?: string[]
  // Enriched by UI
  price?: ProductPrice
  // v7
  cross_subreddit_signal?: CrossSubredditSignal | null
  memory?: ProductMemoryStatus | null
  // v9: precise mention pipeline fields
  sentiment_score?: number | null
  dominant_sentiment?: string | null
  sentiment_records?: SentimentRecord[]
}

export interface SearchResult {
  id: string
  query: string
  category: string
  region: string
  status: string
  createdAt: string
  profile?: Record<string, unknown>
  rubric?: Rubric
  analysis?: {
    summary: string
    products: AnalysisProduct[]
    materials: unknown[]
  }
  scoredProducts?: ScoredProduct[]
}

// SSE event types
export type PipelineEventType =
  | 'stage_start'
  | 'stage_done'
  | 'progress'
  | 'log'
  | 'error'
  | 'done'
  | 'heartbeat'

export interface PipelineEvent {
  type: PipelineEventType
  data: {
    stage?: string
    label?: string
    total?: number
    count?: number
    current?: number
    detail?: string
    products_found?: number
    message?: string
    search_id?: string
    [key: string]: unknown
  }
}

export type StageStatus = 'pending' | 'running' | 'done' | 'error'

export interface StageState {
  id: string
  label: string
  status: StageStatus
  detail?: string
  current?: number
  total?: number
  count?: number
}

// Interview
export interface QAEntry {
  question: string
  answer: string
  why_asked?: string
  targets_criterion?: string
}

export interface InterviewQuestion {
  question: string
  why_asking: string
  targets_criterion: string
  is_done: boolean
}

// Local search history
export interface SearchHistoryItem {
  id: string
  query: string
  category: string
  timestamp: number
  topProduct?: string
  topScore?: number
}

// ── v7: Cross-subreddit signal ────────────────────────────────────────────────
export interface CrossSubredditSignal {
  signal: 'consistent' | 'split' | 'single_source'
  explanation: string
  context_note: string
}

// ── v7: Product memory ────────────────────────────────────────────────────────
export interface ProductMemoryStatus {
  status: 'considered' | 'rejected' | 'purchased' | 'returned'
  userFeedback?: string
  ourScore?: number
}

// ── v7: User signal ───────────────────────────────────────────────────────────
export interface UserSignal {
  id: string
  userId: string
  signalType: 'preference' | 'rejection' | 'purchase' | 'complaint' | string
  productName?: string
  category?: string
  text: string
  strength: 'strong' | 'moderate' | 'weak' | string
  sourceSearchId?: string
  createdAt: string
  similarity?: number
}

export interface ProductMemory {
  id: string
  userId: string
  productName: string
  category: string
  status: 'considered' | 'rejected' | 'purchased' | 'returned'
  ourScore?: number | null
  userFeedback?: string
  createdAt: string
}

export interface MemoryContext {
  signals: UserSignal[]
  profile_summary: string
  has_memory: boolean
}
