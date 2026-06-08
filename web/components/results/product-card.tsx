'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Star,
  Check,
  Sparkles,
  ShoppingCart,
  ImageOff,
  MessageSquare,
  ThumbsUp,
  ThumbsDown,
  Users,
  AlertTriangle,
  Quote,
  LayoutGrid,
  Minus,
  ShieldCheck,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { cn } from '@/lib/utils'

interface Complaint {
  text: string
  confidence: 'confirmed' | 'reported' | 'single' | string
}

interface CrossSubredditSignal {
  signal: 'consistent' | 'split' | 'single_source'
  explanation: string
  context_note: string
  _is_fallback?: boolean
}

interface SentimentRecord {
  comment_text: string
  sentiment: 'positive' | 'negative' | 'neutral'
  source: 'rule' | 'llm'   // "rule" = keyword-matched, "llm" = model-classified
}

// Fix 12: traceable source passage
interface SourcePassage {
  text: string
  sentiment: 'positive' | 'negative' | 'neutral'
  thread_url: string
}

interface Product {
  id: string
  rank: number
  name: string
  score: number
  price: number
  currency: string
  store: string
  storeUrl?: string
  originalPrice?: number
  rating?: number
  reviewCount?: number
  alternativePrices?: { store: string; price: number; url?: string }[]
  highSignal?: boolean
  purchased?: boolean
  criteriaScores: Record<string, { score: number; evidence?: string; relative_rank?: string }>
  pros?: string[]
  cons?: string[]
  fitReason?: string
  imageUrl?: string
  // Community data
  mentionCount?: number
  positiveMentions?: number
  negativeMentions?: number
  distinctRecommenders?: number
  praise?: string[]
  complaints?: Complaint[]
  representativeQuote?: string
  sources?: string[]
  crossSubredditSignal?: CrossSubredditSignal | null
  // v9: precise sentiment pipeline
  sentimentScore?: number | null
  dominantSentiment?: string | null
  sentimentRecords?: SentimentRecord[]
  // Fix 7: recency-weighted mentions
  recencyWeightedMentions?: number | null
  // Fix 12: traceable source passages
  sourcePassages?: SourcePassage[]
  // Link Intelligence
  matchScore?: number | null
  // Evidence reliability (scorer fairness + enrichment)
  dataCoverage?: number | null      // 0–1: fraction of weighted criteria backed by real evidence
  confidence?: 'high' | 'medium' | 'low' | string | null
  // Fix 13: inter-product relative ranking
  overallRank?: number
  gapToLeader?: number
  // Fix 17: source coverage count
  sourceCoverage?: number | null
}

interface ProductCardProps {
  product: Product
  isSelected: boolean
  onToggleSelect: () => void
  onTogglePurchased: () => void
}

function confidenceBadge(c: string) {
  if (c === 'confirmed') return 'bg-rose-500/20 text-rose-300 border-rose-500/30'
  if (c === 'reported') return 'bg-amber-500/20 text-amber-300 border-amber-500/30'
  return 'bg-white/[0.08] text-[#A1A1AA] border-white/[0.12]'
}

function confidenceLabel(c: string) {
  if (c === 'confirmed') return 'confirmed'
  if (c === 'reported') return 'reported'
  return 'single mention'
}

function SentimentIcon({ sentiment, size = 'sm' }: { sentiment: string; size?: 'sm' | 'xs' }) {
  const cls = size === 'sm' ? 'w-4 h-4' : 'w-3 h-3'
  if (sentiment === 'positive') return <ThumbsUp className={cn(cls, 'text-emerald-400')} />
  if (sentiment === 'negative') return <ThumbsDown className={cn(cls, 'text-rose-400')} />
  return <Minus className={cn(cls, 'text-[#71717A]')} />
}

function SentimentBar({ sentimentScore, dominantSentiment }: { sentimentScore: number; dominantSentiment: string }) {
  // Map -1.0..+1.0 to 0%..100% for indicator position
  const pct = ((sentimentScore + 1) / 2) * 100
  // "unknown" means no sentiment data was collected — treat as neutral center
  const effectiveSentiment = dominantSentiment === 'unknown' ? 'neutral' : dominantSentiment

  const indicatorColor =
    effectiveSentiment === 'positive'
      ? 'bg-emerald-400 shadow-emerald-400/40'
      : effectiveSentiment === 'negative'
      ? 'bg-rose-400 shadow-rose-400/40'
      : 'bg-amber-400 shadow-amber-400/40'

  const labelColor =
    effectiveSentiment === 'positive'
      ? 'text-emerald-400'
      : effectiveSentiment === 'negative'
      ? 'text-rose-400'
      : 'text-amber-400'

  return (
    <div className="space-y-1.5">
      {/* Bar */}
      <div className="relative h-2 rounded-full overflow-visible bg-white/[0.06]">
        {/* Negative half */}
        <div className="absolute left-0 top-0 h-full w-1/2 rounded-l-full bg-gradient-to-r from-rose-500/50 to-rose-500/10" />
        {/* Positive half */}
        <div className="absolute right-0 top-0 h-full w-1/2 rounded-r-full bg-gradient-to-r from-emerald-500/10 to-emerald-500/50" />
        {/* Center divider */}
        <div className="absolute left-1/2 top-0 h-full w-px bg-white/20 -translate-x-px" />
        {/* Indicator pill */}
        <motion.div
          className={cn(
            'absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-3 rounded-full shadow-lg',
            indicatorColor,
          )}
          style={{ left: `${pct}%` }}
          initial={{ left: '50%' }}
          animate={{ left: `${pct}%` }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
        />
      </div>
      {/* Label */}
      <div className="flex items-center justify-between text-xs">
        <span className="text-[#52525B]">negative</span>
        <span className={cn('font-medium capitalize', labelColor)}>
          {dominantSentiment === 'unknown' ? 'no data' : dominantSentiment}
          {dominantSentiment !== 'unknown' && <> &middot; {sentimentScore >= 0 ? '+' : ''}{sentimentScore.toFixed(2)}</>}
        </span>
        <span className="text-[#52525B]">positive</span>
      </div>
    </div>
  )
}

export function ProductCard({
  product,
  isSelected,
  onToggleSelect,
  onTogglePurchased,
}: ProductCardProps) {
  const [showScores, setShowScores] = useState(false)
  const [showPeopleSay, setShowPeopleSay] = useState(false)
  const [showFitReason, setShowFitReason] = useState(false)
  const [showSentiment, setShowSentiment] = useState(false)
  const [showMoreSentiment, setShowMoreSentiment] = useState(false)

  const discount =
    product.originalPrice && product.originalPrice > product.price && product.price > 0
      ? Math.round((1 - product.price / product.originalPrice) * 100)
      : null

  const getScoreColor = (score: number) => {
    if (score >= 80) return 'text-emerald-400'
    if (score >= 50) return 'text-amber-400'
    return 'text-rose-400'
  }

  const getScoreBarColor = (score: number) => {
    if (score >= 80) return 'from-emerald-500 to-teal-400'
    if (score >= 50) return 'from-amber-500 to-orange-400'
    return 'from-rose-500 to-red-400'
  }

  const total = (product.positiveMentions ?? 0) + (product.negativeMentions ?? 0)
  const posRatio = total > 0 ? (product.positiveMentions ?? 0) / total : 0
  const hasCommunityData =
    (product.mentionCount ?? 0) > 0 ||
    (product.praise?.length ?? 0) > 0 ||
    (product.complaints?.length ?? 0) > 0

  const hasPeopleSay =
    (product.praise?.length ?? 0) > 0 ||
    (product.complaints?.length ?? 0) > 0 ||
    !!product.representativeQuote

  // Community Sentiment section visibility
  const sentimentTotal =
    (product.positiveMentions ?? 0) + (product.negativeMentions ?? 0)
  const hasSentimentBar =
    product.sentimentScore != null && product.dominantSentiment != null
  const hasSentimentRecords = (product.sentimentRecords?.length ?? 0) > 0
  const showSentimentSection = hasSentimentBar || sentimentTotal > 0 || hasSentimentRecords

  // Displayed sentiment records (first 5, then show-more)
  const allRecords = product.sentimentRecords ?? []
  const visibleRecords = showMoreSentiment ? allRecords : allRecords.slice(0, 5)

  // Format source labels (reddit:Bedding → r/Bedding, review:wirecutter.com → wirecutter.com)
  const formattedSources = (product.sources ?? []).map((s) => {
    if (s.startsWith('reddit:')) return `r/${s.slice(7)}`
    if (s.startsWith('review:')) return s.slice(7)
    return s
  }).slice(0, 6)

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ type: 'spring', damping: 25, stiffness: 200 }}
      className={cn(
        'relative rounded-2xl border bg-white/[0.02] p-6 transition-all duration-300',
        isSelected
          ? 'border-violet-500/50 shadow-glow-sm'
          : 'border-white/[0.06] hover:border-white/[0.12]',
      )}
    >
      {/* Rank Badge */}
      <div className="absolute -left-3 top-6">
        <div
          className={cn(
            'w-10 h-10 rounded-xl flex items-center justify-center font-mono text-lg font-bold',
            product.rank === 1
              ? 'bg-gradient-to-br from-amber-500 to-orange-500 text-white shadow-lg shadow-amber-500/30'
              : product.rank <= 3
              ? 'bg-gradient-to-br from-violet-600 to-violet-500 text-white shadow-lg shadow-violet-500/30'
              : 'bg-white/[0.08] text-[#A1A1AA]',
          )}
        >
          #{product.rank}
        </div>
      </div>

      {/* Selection checkbox */}
      <div className="absolute top-4 right-4">
        <Checkbox
          checked={isSelected}
          onCheckedChange={() => onToggleSelect()}
          className="w-5 h-5 border-white/20 data-[state=checked]:bg-violet-500 data-[state=checked]:border-violet-500"
        />
      </div>

      {/* Header */}
      <div className="ml-6 mb-4">
        <div className="flex items-start gap-4 pr-8">
          {product.imageUrl ? (
            <img
              src={product.imageUrl}
              alt={product.name}
              className="w-16 h-16 rounded-xl object-contain bg-white/[0.04] border border-white/[0.06] shrink-0"
              onError={(e) => {
                ;(e.currentTarget as HTMLImageElement).style.display = 'none'
              }}
            />
          ) : (
            <div className="w-16 h-16 rounded-xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center shrink-0">
              <ImageOff className="w-6 h-6 text-[#52525B]" />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <h3 className="text-xl font-semibold text-[#FAFAFA] mb-2">{product.name}</h3>
            <div className="flex items-center gap-2 flex-wrap">
              {product.highSignal && (
                <Badge className="bg-violet-500/20 text-violet-300 border-violet-500/30">
                  <Sparkles className="w-3 h-3 mr-1" />
                  HIGH SIGNAL
                </Badge>
              )}
              {product.confidence && product.dataCoverage != null && (
                <Badge
                  title={`${Math.round(product.dataCoverage * 100)}% of the weighted criteria are backed by real research evidence; the rest are estimated from comparable products.`}
                  className={
                    product.confidence === 'high'
                      ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                      : product.confidence === 'medium'
                      ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                      : 'bg-zinc-500/15 text-zinc-300 border-zinc-500/30'
                  }
                >
                  <ShieldCheck className="w-3 h-3 mr-1" />
                  {Math.round(product.dataCoverage * 100)}% data-backed
                </Badge>
              )}
              {product.sourceCoverage != null && product.sourceCoverage === 1 && (
                <Badge
                  title="Based on a single source — treat score with extra caution."
                  className="bg-amber-500/15 text-amber-300 border-amber-500/30"
                >
                  1 source
                </Badge>
              )}
              {product.purchased && (
                <Badge className="bg-emerald-500/20 text-emerald-300 border-emerald-500/30">
                  <Check className="w-3 h-3 mr-1" />
                  You bought this
                </Badge>
              )}
              {product.crossSubredditSignal?.signal === 'split' && !product.crossSubredditSignal._is_fallback && (
                <Badge className="bg-amber-500/20 text-amber-300 border-amber-500/30">
                  <AlertTriangle className="w-3 h-3 mr-1" />
                  Mixed community signal
                </Badge>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Score Bar */}
      <div className="ml-6 mb-4">
        <div className="flex items-center gap-4">
          <div className="flex-1 h-3 bg-white/[0.06] rounded-full overflow-hidden">
            <motion.div
              className={`h-full bg-gradient-to-r ${getScoreBarColor(product.score)} rounded-full`}
              initial={{ width: 0 }}
              animate={{ width: `${product.score}%` }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
            />
          </div>
          <span className={`font-mono text-2xl font-bold ${getScoreColor(product.score)}`}>
            {product.score}%
          </span>
        </div>
        {product.gapToLeader != null && product.gapToLeader > 0 && (
          <p className="text-xs text-[#52525B] mt-1">{product.gapToLeader.toFixed(1)} pts behind leader</p>
        )}
      </div>

      {/* Community Signal Row */}
      {hasCommunityData && (
        <div className="ml-6 mb-4 flex items-center gap-4 flex-wrap">
          {(product.mentionCount ?? 0) > 0 && (
            <div className="flex items-center gap-1.5 text-sm text-[#A1A1AA]">
              <MessageSquare className="w-3.5 h-3.5 text-violet-400" />
              <span className="text-[#FAFAFA] font-medium">{product.mentionCount}</span>
              <span>mentions</span>
            </div>
          )}
          {(product.distinctRecommenders ?? 0) > 0 && (
            <div className="flex items-center gap-1.5 text-sm text-[#A1A1AA]">
              <Users className="w-3.5 h-3.5 text-violet-400" />
              <span className="text-[#FAFAFA] font-medium">{product.distinctRecommenders}</span>
              <span>recommenders</span>
            </div>
          )}
          {total > 0 && (
            <div className="flex items-center gap-2 text-sm">
              <div className="flex items-center gap-1 text-emerald-400">
                <ThumbsUp className="w-3.5 h-3.5" />
                <span className="font-medium">{product.positiveMentions}</span>
              </div>
              <div className="flex items-center gap-1 text-rose-400">
                <ThumbsDown className="w-3.5 h-3.5" />
                <span className="font-medium">{product.negativeMentions}</span>
              </div>
              {/* Mini sentiment bar */}
              <div className="w-16 h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
                <div
                  className="h-full bg-emerald-500 rounded-full"
                  style={{ width: `${posRatio * 100}%` }}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Community Sentiment Section (v9) ──────────────────────────────── */}
      {showSentimentSection && (
        <div className="ml-6 mb-4 space-y-3">
          {/* Sentiment Score Bar */}
          {hasSentimentBar && (
            <div className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
              <SentimentBar
                sentimentScore={product.sentimentScore!}
                dominantSentiment={product.dominantSentiment!}
              />
            </div>
          )}

          {/* Breakdown pills */}
          {sentimentTotal > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              {(product.positiveMentions ?? 0) > 0 && (
                <span className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg bg-emerald-500/15 text-emerald-300">
                  <ThumbsUp className="w-3 h-3" />
                  Positive: {product.positiveMentions}
                </span>
              )}
              {(product.negativeMentions ?? 0) > 0 && (
                <span className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg bg-rose-500/15 text-rose-300">
                  <ThumbsDown className="w-3 h-3" />
                  Negative: {product.negativeMentions}
                </span>
              )}
              {product.sentimentRecords && product.sentimentRecords.filter(r => r.sentiment === 'neutral').length > 0 && (
                <span className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg bg-white/[0.06] text-[#A1A1AA]">
                  <Minus className="w-3 h-3" />
                  Neutral: {product.sentimentRecords.filter(r => r.sentiment === 'neutral').length}
                </span>
              )}
            </div>
          )}

          {/* Collapsible comment records */}
          {hasSentimentRecords && (
            <>
              <button
                onClick={() => setShowSentiment(!showSentiment)}
                className="flex items-center gap-2 text-sm text-[#A1A1AA] hover:text-[#FAFAFA] transition-colors py-0.5"
              >
                {showSentiment ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                What people are saying
                <span className="text-xs text-[#52525B]">({allRecords.length} comments)</span>
              </button>
              <AnimatePresence>
                {showSentiment && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    className="overflow-hidden"
                  >
                    <div className="pl-4 py-2 space-y-3">
                      {visibleRecords.map((record, i) => (
                        <div key={i} className="flex items-start gap-2.5">
                          <div className="shrink-0 mt-0.5">
                            <SentimentIcon sentiment={record.sentiment} size="sm" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-start justify-between gap-2">
                              <p className="text-sm text-[#A1A1AA] leading-relaxed line-clamp-2">
                                &ldquo;{record.comment_text.slice(0, 200)}{record.comment_text.length > 200 ? '…' : ''}&rdquo;
                              </p>
                              {/* source badge: "Rule-based" = keyword pattern matched, "AI analysis" = LLM classified */}
                              <span className={cn(
                                'text-[9px] px-1.5 py-0.5 rounded-md border shrink-0 font-medium',
                                record.source === 'rule'
                                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                                  : 'bg-violet-500/10 text-violet-400 border-violet-500/20',
                              )}>
                                {record.source === 'rule' ? 'Rule' : 'AI'}
                              </span>
                            </div>
                          </div>
                        </div>
                      ))}

                      {allRecords.length > 5 && (
                        <button
                          onClick={() => setShowMoreSentiment(!showMoreSentiment)}
                          className="text-xs text-violet-400 hover:text-violet-300 transition-colors py-1"
                        >
                          {showMoreSentiment
                            ? 'Show less'
                            : `Show ${allRecords.length - 5} more comments`}
                        </button>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </>
          )}
        </div>
      )}

      {/* Fix 12: Source Evidence — traceable passages that backed this ranking */}
      {(product.sourcePassages?.length ?? 0) > 0 && (
        <div className="ml-6 mb-4">
          <details className="group">
            <summary className="flex items-center gap-2 text-xs text-[#71717A] cursor-pointer hover:text-[#A1A1AA] transition-colors list-none select-none">
              <svg className="w-3.5 h-3.5 transition-transform group-open:rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
              </svg>
              Evidence trail
              <span className="text-[#52525B]">({product.sourcePassages!.length} source{product.sourcePassages!.length > 1 ? 's' : ''})</span>
            </summary>
            <div className="mt-2 pl-4 space-y-2">
              {product.sourcePassages!.map((passage, i) => (
                <div key={i} className="flex items-start gap-2 group/passage">
                  <SentimentIcon sentiment={passage.sentiment} size="xs" />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-[#71717A] leading-relaxed line-clamp-2 italic">
                      &ldquo;{passage.text.slice(0, 180)}{passage.text.length > 180 ? '…' : ''}&rdquo;
                    </p>
                    {passage.thread_url && (
                      <a
                        href={passage.thread_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 mt-0.5 text-[9px] text-violet-400/70 hover:text-violet-300 transition-colors"
                      >
                        <ExternalLink className="w-2.5 h-2.5" />
                        {(() => {
                          try {
                            const m = passage.thread_url.match(/reddit\.com\/r\/([^/]+)/)
                            return m ? `r/${m[1]}` : 'Source'
                          } catch { return 'Source' }
                        })()}
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </details>
        </div>
      )}

      {/* Representative Quote */}
      {product.representativeQuote && (
        <div className="ml-6 mb-4 flex gap-2">
          <Quote className="w-4 h-4 text-violet-400/60 shrink-0 mt-0.5" />
          <p className="text-sm text-[#A1A1AA] italic leading-relaxed">
            &ldquo;{product.representativeQuote}&rdquo;
          </p>
        </div>
      )}

      {/* Sources */}
      {formattedSources.length > 0 && (
        <div className="ml-6 mb-4 flex items-center gap-1.5 flex-wrap">
          <LayoutGrid className="w-3 h-3 text-[#52525B] shrink-0" />
          {formattedSources.map((src) => (
            <span
              key={src}
              className="text-xs px-1.5 py-0.5 rounded-md bg-white/[0.05] text-[#71717A] border border-white/[0.06]"
            >
              {src}
            </span>
          ))}
        </div>
      )}

      {/* Cross-subreddit split warning — only shown for real LLM-produced explanations */}
      {product.crossSubredditSignal?.signal === 'split'
        && !product.crossSubredditSignal._is_fallback
        && product.crossSubredditSignal.explanation && (
        <div className="ml-6 mb-4 p-3 rounded-xl bg-amber-500/[0.06] border border-amber-500/20">
          <p className="text-xs text-amber-300/80 leading-relaxed">
            <span className="font-medium text-amber-300">Community split:</span>{' '}
            {product.crossSubredditSignal.explanation}
          </p>
          {product.crossSubredditSignal.context_note && (
            <p className="text-xs text-[#A1A1AA] mt-1">{product.crossSubredditSignal.context_note}</p>
          )}
        </div>
      )}

      {/* Price & Store */}
      <div className="ml-6 mb-4">
        <div className="flex items-baseline gap-2 flex-wrap mb-1">
          {product.price > 0 ? (
            <>
              <span className="text-2xl font-bold text-[#FAFAFA]">
                {product.currency}{product.price.toLocaleString()}
              </span>
              {product.originalPrice && product.originalPrice > product.price && (
                <span className="text-sm text-[#71717A] line-through">
                  {product.currency}{product.originalPrice.toLocaleString()}
                </span>
              )}
              {discount && discount > 0 && (
                <Badge variant="secondary" className="bg-emerald-500/20 text-emerald-400 border-0">
                  {discount}% off
                </Badge>
              )}
            </>
          ) : (
            <span className="text-sm text-[#71717A] italic">Price unavailable</span>
          )}
        </div>

        {/* Store + Rating row */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm text-[#A1A1AA]">on {product.store}</span>

          {product.rating != null && product.rating > 0 && (
            <>
              <span className="text-[#3F3F46]">•</span>
              {/* Star row */}
              <div className="flex items-center gap-1.5">
                <div className="flex items-center gap-0.5">
                  {[1, 2, 3, 4, 5].map((i) => (
                    <Star
                      key={i}
                      className={cn(
                        'w-3.5 h-3.5',
                        i <= Math.floor(product.rating!)
                          ? 'text-amber-400 fill-amber-400'
                          : i === Math.ceil(product.rating!) && product.rating! % 1 >= 0.5
                          ? 'text-amber-400 fill-amber-400/50'
                          : 'text-white/10',
                      )}
                    />
                  ))}
                </div>
                <span className="text-sm font-semibold text-amber-300">
                  {product.rating.toFixed(1)}
                </span>
                {product.reviewCount != null && product.reviewCount > 0 && (
                  <span className="text-xs text-[#71717A]">
                    ({product.reviewCount.toLocaleString()} ratings)
                  </span>
                )}
              </div>
            </>
          )}

          {/* Match confidence badge — shown when intelligence data present */}
          {product.matchScore != null && product.matchScore > 0 && (
            <>
              <span className="text-[#3F3F46]">•</span>
              <span
                className={cn(
                  'flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border',
                  product.matchScore >= 0.85
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25'
                    : product.matchScore >= 0.65
                    ? 'bg-amber-500/10 text-amber-400 border-amber-500/25'
                    : 'bg-white/[0.05] text-[#71717A] border-white/[0.10]',
                )}
              >
                <ShieldCheck className="w-3 h-3" />
                {Math.round(product.matchScore * 100)}% match
              </span>
            </>
          )}
        </div>

        {product.alternativePrices && product.alternativePrices.length > 0 && (
          <div className="mt-2 text-sm text-[#71717A]">
            Also:{' '}
            {product.alternativePrices.map((alt, i) => (
              <span key={alt.store}>
                {i > 0 && ' • '}
                {alt.store} {product.currency}{alt.price.toLocaleString()}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Expandable sections */}
      <div className="ml-6 space-y-1">

        {/* What people say (praise + complaints) */}
        {hasPeopleSay && (
          <>
            <button
              onClick={() => setShowPeopleSay(!showPeopleSay)}
              className="flex items-center gap-2 text-sm text-[#A1A1AA] hover:text-[#FAFAFA] transition-colors py-1"
            >
              {showPeopleSay ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              What people say
            </button>
            <AnimatePresence>
              {showPeopleSay && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="overflow-hidden"
                >
                  <div className="pl-4 py-3 space-y-3">
                    {(product.praise?.length ?? 0) > 0 && (
                      <div className="space-y-1.5">
                        {product.praise!.slice(0, 4).map((p, i) => (
                          <div key={i} className="flex items-start gap-2">
                            <div className="w-4 h-4 rounded-full bg-emerald-500/20 flex items-center justify-center shrink-0 mt-0.5">
                              <Check className="w-2.5 h-2.5 text-emerald-400" />
                            </div>
                            <span className="text-sm text-[#A1A1AA]">{p}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {(product.complaints?.length ?? 0) > 0 && (
                      <div className="space-y-1.5">
                        {product.complaints!.slice(0, 4).map((c, i) => (
                          <div key={i} className="flex items-start gap-2">
                            <div className="w-4 h-4 rounded-full bg-rose-500/20 flex items-center justify-center shrink-0 mt-0.5">
                              <span className="text-rose-400 text-xs font-bold leading-none">✕</span>
                            </div>
                            <div className="flex-1 min-w-0">
                              <span className="text-sm text-[#A1A1AA]">{c.text}</span>
                              {c.confidence && c.confidence !== 'single' && (
                                <span className={cn(
                                  'ml-2 text-xs px-1.5 py-0.5 rounded-md border inline-block',
                                  confidenceBadge(c.confidence),
                                )}>
                                  {confidenceLabel(c.confidence)}
                                </span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </>
        )}

        {/* How it scored */}
        <button
          onClick={() => setShowScores(!showScores)}
          className="flex items-center gap-2 text-sm text-[#A1A1AA] hover:text-[#FAFAFA] transition-colors py-1"
        >
          {showScores ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          How it scored
        </button>
        <AnimatePresence>
          {showScores && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="pl-4 py-3 space-y-3">
                {Object.entries(product.criteriaScores).map(([criterion, data]) => (
                  <div key={criterion}>
                    <div className="flex items-center justify-between mb-0.5">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm text-[#A1A1AA]">{criterion}</span>
                        {data.relative_rank && (
                          <span className={cn(
                            'text-[10px] px-1.5 py-0.5 rounded-md border font-medium',
                            data.relative_rank === 'Best'
                              ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25'
                              : data.relative_rank === 'Above avg'
                              ? 'bg-teal-500/15 text-teal-300 border-teal-500/25'
                              : data.relative_rank === 'Average'
                              ? 'bg-blue-500/15 text-blue-300 border-blue-500/25'
                              : data.relative_rank === 'Weakest'
                              ? 'bg-rose-500/15 text-rose-300 border-rose-500/25'
                              : data.relative_rank === 'Only option'
                              ? 'bg-white/[0.08] text-[#71717A] border-white/[0.12]'
                              : 'bg-zinc-500/15 text-zinc-300 border-zinc-500/25',
                          )}>
                            {data.relative_rank}
                          </span>
                        )}
                      </div>
                      <span
                        className={cn(
                          'font-mono text-sm font-medium',
                          data.score >= 8
                            ? 'text-emerald-400'
                            : data.score >= 5
                            ? 'text-amber-400'
                            : 'text-rose-400',
                        )}
                      >
                        {data.score}/10
                      </span>
                    </div>
                    {data.evidence && data.evidence !== 'no direct data found' && (
                      <p className="text-xs text-[#52525B] leading-relaxed">{data.evidence}</p>
                    )}
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Why this fits you */}
        {product.fitReason && (
          <>
            <button
              onClick={() => setShowFitReason(!showFitReason)}
              className="flex items-center gap-2 text-sm text-[#A1A1AA] hover:text-[#FAFAFA] transition-colors py-1"
            >
              {showFitReason ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              Why this fits you
            </button>
            <AnimatePresence>
              {showFitReason && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="overflow-hidden"
                >
                  <div className="pl-4 py-3">
                    <p className="text-sm text-[#A1A1AA] leading-relaxed">{product.fitReason}</p>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </>
        )}
      </div>

      {/* Actions */}
      <div className="ml-6 mt-5 flex items-center gap-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={onTogglePurchased}
          className={cn(
            'text-[#A1A1AA] hover:text-[#FAFAFA]',
            product.purchased && 'text-emerald-300 hover:text-emerald-200',
          )}
        >
          {product.purchased ? <Check className="w-4 h-4 mr-1.5" /> : <ShoppingCart className="w-4 h-4 mr-1.5" />}
          {product.purchased ? 'Bought' : 'I bought this'}
        </Button>
        <Button size="sm" className="bg-violet-600 hover:bg-violet-500" asChild>
          <a href={product.storeUrl || '#'} target="_blank" rel="noopener noreferrer">
            Open on {product.store}
            <ExternalLink className="w-4 h-4 ml-1.5" />
          </a>
        </Button>
      </div>
    </motion.div>
  )
}
