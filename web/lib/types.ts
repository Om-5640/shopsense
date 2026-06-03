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
  match_score?: number          // product matcher score 0.0–1.0 (additive)
}

// ── Product Link Intelligence (Phases 1–13) ───────────────────────────────────
export interface CanonicalProductData {
  brand: string | null
  model: string | null
  storage: string | null
  ram: string | null
  color: string | null
  variant: string | null
  screen_size?: string | null
  canonical_name: string
  parse_confidence: number
}

export interface LinkIntelligence {
  confidence: number            // 0.0–1.0 combined score
  consensus_score: number       // multi-marketplace agreement
  match_score: number           // best candidate match score
  source_trust: number          // trust of winning source
  price_consistency: number     // price variance score
  status: 'confident' | 'uncertain' | 'fallback' | string
  canonical: CanonicalProductData
  best_url: string | null
  best_title: string | null
  best_image: string | null
  best_rating: number | null
  best_review_count: number | null
}

export interface ProductPrice {
  product_name: string
  retailers: RetailerPrice[]
  best_price?: { retailer: string; price_inr?: number; price_usd?: number }
  price_range?: [number, number]
  currency: string
  fetched_at: string
  is_fallback?: boolean
  intelligence?: LinkIntelligence   // present when Link Intelligence ran successfully
}

// Rich community data extracted from Reddit + review sources
export interface ProductComplaint {
  text: string
  confidence: 'confirmed' | 'reported' | 'single' | string
}

export interface SentimentRecord {
  comment_text: string
  sentiment: 'positive' | 'negative' | 'neutral'
  source: 'rule' | 'llm'   // "rule" = keyword-matched, "llm" = model-classified
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
    review_intelligence?: ReviewIntelligence
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
    from_cache?: boolean        // true when the done event was triggered by a pipeline cache hit
    elapsed_s?: number
    pipeline_warnings?: string[] // provider fallback / infra warnings emitted with the done event
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

// ── Structured user intent (Phase 3) ─────────────────────────────────────────
export interface UserIntent {
  hard_constraints: string[]
  budget: string | null
  preferences: string[]
  exclusions: string[]
  uncertainties: string[]
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
  _is_fallback?: boolean   // true when LLM call failed; suppress split UI in this case
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

export interface ProcessMessageResult {
  intent: 'ANSWER' | 'QUESTION' | 'MIXED' | 'SKIP' | 'COMMAND' | 'UNCLEAR'
  confidence: number
  preference_fragment: string | null
  question_answer: string | null
  clarification_question: string | null
  command_action: string | null
}

// ── Review Intelligence (Phases 1–9) ─────────────────────────────────────────

export interface ReviewSource {
  domain: string
  title: string
  url: string
  trust_score: number          // 0.0–1.0 continuous
  freshness_score: number      // 0.0–1.0 time-decay
  review_rank_score: number    // composite rank
  source_type: 'gemini_grounding' | 'expert_editorial' | 'news' | 'youtube' | 'serper_fallback' | string
  authority_tier: 'trusted' | 'good' | 'unknown' | string
  published_date?: string | null
  rating?: number | null       // extracted by review_extractor (normalized to /10)
  verdict?: string | null      // extracted verdict snippet
  pros?: string[]              // structured pros extracted from review text
  cons?: string[]              // structured cons extracted from review text
  best_for?: string[]          // "best for" use-cases extracted from review text
  not_for?: string[]           // "not for" warnings extracted from review text
  channel_name?: string | null // YouTube only: channel name for self-verification
}

export interface ReviewConflict {
  topic: string
  agreement_score: number      // fraction that agree with majority view
  conflict: boolean            // true when agreement < 0.75
  positive_count: number
  negative_count: number
}

export interface ReviewIntelligenceStats {
  total: number
  trusted_count: number
  editorial_count: number    // gemini_grounding + expert_editorial sources
  youtube_count: number
  avg_trust: number
  avg_freshness: number
  conflicts_found: number
}

export interface ReviewIntelligence {
  sources: ReviewSource[]
  conflict_signals: ReviewConflict[]
  stats: ReviewIntelligenceStats
}

// ── Phase 11: Pipeline diagnostics ───────────────────────────────────────────
export interface PipelineDiagnostics {
  search_id: string
  status: string
  elapsed_s?: number
  stats: {
    stage_timings: Record<string, number>
    product_count: number
    thread_count: number
    dedup_removed: number
    llm_calls_estimated: number
    tokens_estimated: number
    warnings: string[]           // token-budget truncation warnings
    pipeline_warnings?: string[] // provider fallback / infrastructure warnings
    scoring_mode?: string        // "hybrid" | "llm" | "fast"
    providers_used?: string[]    // active providers at pipeline end
  }
}
