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
  AlertTriangle,
  Minus,
  ShieldCheck,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { cn } from '@/lib/utils'

// ─── Interfaces ────────────────────────────────────────────────────────────────

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
  source: 'rule' | 'llm'
}

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
  mentionCount?: number
  positiveMentions?: number
  negativeMentions?: number
  distinctRecommenders?: number
  praise?: string[]
  complaints?: Complaint[]
  representativeQuote?: string
  sources?: string[]
  crossSubredditSignal?: CrossSubredditSignal | null
  sentimentScore?: number | null
  dominantSentiment?: string | null
  sentimentRecords?: SentimentRecord[]
  recencyWeightedMentions?: number | null
  sourcePassages?: SourcePassage[]
  matchScore?: number | null
  dataCoverage?: number | null
  confidence?: 'high' | 'medium' | 'low' | string | null
  overallRank?: number
  gapToLeader?: number
  sourceCoverage?: number | null
}

interface ProductCardProps {
  product: Product
  isSelected: boolean
  onToggleSelect: () => void
  onTogglePurchased: () => void
}

// ─── Pure helpers ──────────────────────────────────────────────────────────────

function SentimentIcon({ sentiment, size = 'sm' }: { sentiment: string; size?: 'sm' | 'xs' }) {
  const cls = size === 'sm' ? 'w-4 h-4' : 'w-3 h-3'
  if (sentiment === 'positive') return <ThumbsUp className={cn(cls, 'text-emerald-400')} />
  if (sentiment === 'negative') return <ThumbsDown className={cn(cls, 'text-rose-400')} />
  return <Minus className={cn(cls, 'text-[#71717A]')} />
}

// Compute smart contextual tag shown in the top-right corner
function computeContextTag(product: Product): { label: string; cls: string } | null {
  const mc = product.mentionCount ?? 0
  const pos = product.positiveMentions ?? 0
  const neg = product.negativeMentions ?? 0
  const total = pos + neg
  const posRatio = total > 0 ? pos / total : 0

  if (mc === 0) return { label: 'Too new for Reddit verdict', cls: 'bg-white/[0.06] text-[#71717A] border-white/[0.10]' }
  if (mc < 5)  return { label: 'New — limited data',         cls: 'bg-amber-500/10 text-amber-400 border-amber-500/20' }

  if (product.rank === 1 && mc >= 15)             return { label: '🏆 Recommended',    cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' }
  if (product.rank === 1)                          return { label: '🏆 Top Reddit pick', cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' }
  if (product.rank <= 3 && posRatio >= 0.75)       return { label: 'Strong contender',  cls: 'bg-violet-500/15 text-violet-300 border-violet-500/25' }
  if (product.rank <= 3)                           return { label: 'Strong contender',  cls: 'bg-violet-500/15 text-violet-300 border-violet-500/25' }
  if (total >= 5 && posRatio >= 0.90)              return { label: 'Community favourite', cls: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20' }
  return { label: 'Solid pick', cls: 'bg-sky-500/10 text-sky-300 border-sky-500/20' }
}

// Extract a second modifier tag (e.g. "Older · proven" / "Newer · limited data")
function computeModifierTag(product: Product): { label: string; cls: string } | null {
  const mc = product.mentionCount ?? 0
  if (mc === 0) return null
  if (mc >= 30) return { label: 'Older · proven',      cls: 'bg-white/[0.05] text-[#71717A] border-white/[0.08]' }
  if (mc < 8)   return { label: 'Newer · less reviewed', cls: 'bg-white/[0.05] text-[#71717A] border-white/[0.08]' }
  return null
}

// ─── Spec-table extraction ─────────────────────────────────────────────────────

interface SpecRow { label: string; value: string; highlight: boolean }

function extractSpecTable(
  criteriaScores: Record<string, { score: number; evidence?: string }>
): SpecRow[] {
  const rows: SpecRow[] = []
  const seen = new Set<string>()

  const DEFS: Array<{
    match: RegExp
    label: string
    extract: (ev: string) => string | null
  }> = [
    {
      match: /anc|noise cancel|noise reduc/i,
      label: 'ANC',
      extract: (ev) => {
        const m = ev.match(/(\d+)\s*dB/i)
        if (m) return `${m[1]} dB`
        if (/\bno\b|none|not present/i.test(ev)) return 'No'
        if (/yes|active|good|great|excellent|support/i.test(ev)) return 'Yes'
        return null
      },
    },
    {
      match: /battery|playtime|playback.*time|endurance/i,
      label: 'Battery',
      extract: (ev) => {
        const m = ev.match(/(\d+(?:\.\d+)?)\s*(?:hrs?|hours?)/i)
        return m ? `${m[1]} hrs` : null
      },
    },
    {
      match: /codec(?!\s*support.*quality)|audio.*codec/i,
      label: 'Codec',
      extract: (ev) => {
        for (const kw of ['LDAC', 'aptX HD', 'aptX Adaptive', 'aptX Lossless', 'aptX', 'LC3plus', 'LC3', 'AAC', 'SBC']) {
          if (ev.includes(kw)) return kw
        }
        return null
      },
    },
    {
      match: /bluetooth.*ver|bt.*ver|wireless.*connect|connectivity/i,
      label: 'Bluetooth',
      extract: (ev) => {
        const m = ev.match(/(?:BT|Bluetooth)\s*v?(\d+\.\d+)/i)
          ?? ev.match(/v?(\d+\.\d+)\s*(?:BT|Bluetooth)/i)
          ?? ev.match(/\b(\d+\.\d+)\b/)
        return m ? m[1] : null
      },
    },
    {
      match: /water.*resist|ip\s*rating|ipx|splash|dust|dust.*proof/i,
      label: 'IP Rating',
      extract: (ev) => {
        const m = ev.match(/ip[x]?\s*\d+[a-z]?/i)
        return m ? m[0].replace(/\s+/g, '').toUpperCase() : null
      },
    },
    {
      match: /driver|speaker.*config|transducer/i,
      label: 'Driver',
      extract: (ev) => {
        const m = ev.match(/(\d+mm[^,\.;\n]{0,20})/i)
        if (m) return m[1].trim()
        for (const kw of ['Planar', 'BA driver', 'Balanced Armature', 'Dual', 'Triple', 'Single 10mm', 'Single 12mm']) {
          if (ev.toLowerCase().includes(kw.toLowerCase())) return kw
        }
        return null
      },
    },
    {
      match: /sound.*sig|tuning|sound.*profile|audio.*character/i,
      label: 'Sound',
      extract: (ev) => {
        for (const kw of ['V-shaped', 'V-shape', 'Warm, bassy', 'Balanced, clear', 'Balanced', 'Bright', 'Bass-heavy', 'Neutral', 'Musical', 'Analytical', 'Warm', 'Clear']) {
          if (ev.toLowerCase().includes(kw.toLowerCase())) return kw
        }
        return null
      },
    },
    {
      match: /personal.*sound|adaptive.*eq|ai.*eq|audiodo|dirac|auto.*eq/i,
      label: 'Personal Sound',
      extract: (ev) => {
        if (/no\b|none|not present|doesn't|does not/i.test(ev)) return 'No'
        const m = ev.match(/Yes\s*\(([^)]+)\)/i)
        if (m) return `Yes (${m[1]})`
        if (/yes|supported|available|audiodo|dirac/i.test(ev)) return 'Yes'
        return null
      },
    },
  ]

  for (const [criterion, data] of Object.entries(criteriaScores)) {
    if (!data.evidence || data.evidence === 'no direct data found') continue
    for (const def of DEFS) {
      if (!def.match.test(criterion)) continue
      if (seen.has(def.label)) continue
      const val = def.extract(data.evidence)
      if (val) {
        rows.push({ label: def.label, value: val, highlight: data.score >= 8 })
        seen.add(def.label)
      }
      break
    }
  }

  const ORDER = ['ANC', 'Battery', 'Codec', 'Bluetooth', 'IP Rating', 'Driver', 'Sound', 'Personal Sound']
  rows.sort((a, b) => {
    const ai = ORDER.indexOf(a.label); const bi = ORDER.indexOf(b.label)
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi)
  })
  return rows
}

// Build up to 3 quote strings for the testimonials box
function buildQuotes(product: Product): Array<{ text: string; source: string }> {
  const quotes: Array<{ text: string; source: string }> = []

  // Prefer sourcePassages (they have a thread URL we can turn into attribution)
  const passages = product.sourcePassages ?? []
  for (const p of passages) {
    if (quotes.length >= 3) break
    const trimmed = p.text.slice(0, 140).trim()
    if (trimmed.length < 20) continue
    let src = 'Reddit'
    try {
      const m = p.thread_url?.match(/reddit\.com\/r\/([^/]+)/)
      if (m) src = `r/${m[1]}`
    } catch { /* ignore */ }
    quotes.push({ text: trimmed + (p.text.length > 140 ? '…' : ''), source: src })
  }

  // Fall back to sentiment records
  if (quotes.length < 2) {
    const records = product.sentimentRecords ?? []
    for (const r of records) {
      if (quotes.length >= 3) break
      const trimmed = r.comment_text.slice(0, 140).trim()
      if (trimmed.length < 20) continue
      quotes.push({ text: trimmed + (r.comment_text.length > 140 ? '…' : ''), source: 'Reddit' })
    }
  }

  // Final fallback: representative quote
  if (quotes.length === 0 && product.representativeQuote) {
    quotes.push({ text: product.representativeQuote.slice(0, 140), source: 'Reddit' })
  }

  return quotes
}

// ─── Component ─────────────────────────────────────────────────────────────────

export function ProductCard({
  product,
  isSelected,
  onToggleSelect,
  onTogglePurchased,
}: ProductCardProps) {
  const [showScores, setShowScores]         = useState(false)
  const [showFitReason, setShowFitReason]   = useState(false)
  const [showDiscussions, setShowDiscussions] = useState(false)
  const [showAllComments, setShowAllComments] = useState(false)

  // ── Derived values ──────────────────────────────────────────────────────────
  const discount = product.originalPrice && product.originalPrice > product.price && product.price > 0
    ? Math.round((1 - product.price / product.originalPrice) * 100)
    : null

  const pos     = product.positiveMentions ?? 0
  const neg     = product.negativeMentions ?? 0
  const total   = pos + neg
  const posRatio = total > 0 ? pos / total : 0
  const neutralCount = (product.sentimentRecords ?? []).filter(r => r.sentiment === 'neutral').length
  const recommendPct = total > 0 ? Math.round(posRatio * 100) : null

  const hasPraise    = (product.praise?.length ?? 0) > 0
  const hasComplaints = (product.complaints?.length ?? 0) > 0

  const allRecords    = product.sentimentRecords ?? []
  const visibleRecords = showAllComments ? allRecords : allRecords.slice(0, 3)

  const contextTag  = computeContextTag(product)
  const modifierTag = computeModifierTag(product)
  const specs       = extractSpecTable(product.criteriaScores)
  const quotes      = buildQuotes(product)

  const redditDiscussions = (product.sources ?? [])
    .filter(s => s.startsWith('reddit:'))
    .map(s => {
      const sub = s.slice(7)
      return {
        label: `r/${sub}`,
        url: `https://www.reddit.com/r/${encodeURIComponent(sub)}/search?q=${encodeURIComponent(product.name)}&sort=top`,
      }
    })
  const reviewLinks = (product.sources ?? [])
    .filter(s => s.startsWith('review:'))
    .map(s => ({ label: s.slice(7), url: `https://www.${s.slice(7)}` }))

  const scoreColor = product.score >= 80 ? 'text-emerald-400' : product.score >= 50 ? 'text-amber-400' : 'text-rose-400'
  const scoreBar   = product.score >= 80 ? 'from-emerald-500 to-teal-400' : product.score >= 50 ? 'from-amber-500 to-orange-400' : 'from-rose-500 to-red-400'

  // Sentiment label color (from recommendPct or dominantSentiment)
  const sentimentPct    = recommendPct
  const sentimentLabel  = (() => {
    const dominant = product.dominantSentiment
    if (!dominant || dominant === 'unknown') return recommendPct !== null ? 'Reddit sentiment' : null
    const allReviews = pos + neg + neutralCount
    const suffix = allReviews > 0 && allReviews < 5 ? ` (only ${allReviews} reviews)` : ''
    if (dominant === 'positive') return `Reddit positive${suffix}`
    if (dominant === 'negative') return `Reddit negative${suffix}`
    return `Reddit mixed${suffix}`
  })()
  const sentimentColor = (() => {
    const dominant = product.dominantSentiment
    if (dominant === 'positive') return 'text-emerald-400'
    if (dominant === 'negative') return 'text-rose-400'
    return 'text-amber-400'
  })()

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ type: 'spring', damping: 25, stiffness: 200 }}
      className={cn(
        'relative rounded-2xl border bg-white/[0.02] transition-all duration-300',
        isSelected ? 'border-violet-500/50 shadow-glow-sm' : 'border-white/[0.06] hover:border-white/[0.10]',
      )}
    >
      {/* ─── HEADER ──────────────────────────────────────────────────────── */}
      <div className="px-5 pt-5 pb-4 border-b border-white/[0.05]">
        {/* Rank + context tag row */}
        <div className="flex items-start justify-between gap-2 mb-3">
          {/* Rank badge */}
          <div className={cn(
            'shrink-0 w-9 h-9 rounded-xl flex items-center justify-center font-mono text-sm font-bold',
            product.rank === 1
              ? 'bg-gradient-to-br from-amber-500 to-orange-500 text-white shadow-md shadow-amber-500/30'
              : product.rank <= 3
              ? 'bg-gradient-to-br from-violet-600 to-violet-500 text-white shadow-md shadow-violet-500/30'
              : 'bg-white/[0.08] text-[#A1A1AA]',
          )}>
            #{product.rank}
          </div>

          {/* Context tags */}
          <div className="flex items-center gap-1.5 flex-wrap justify-end flex-1">
            {contextTag && (
              <span className={cn('text-[11px] px-2.5 py-0.5 rounded-full border font-medium whitespace-nowrap', contextTag.cls)}>
                {contextTag.label}
              </span>
            )}
            {modifierTag && (
              <span className={cn('text-[11px] px-2.5 py-0.5 rounded-full border font-medium whitespace-nowrap', modifierTag.cls)}>
                {modifierTag.label}
              </span>
            )}
            {/* Selection checkbox */}
            <Checkbox
              checked={isSelected}
              onCheckedChange={() => onToggleSelect()}
              className="w-4 h-4 border-white/20 data-[state=checked]:bg-violet-500 data-[state=checked]:border-violet-500"
            />
          </div>
        </div>

        {/* Image + name row */}
        <div className="flex items-center gap-3">
          {product.imageUrl ? (
            <img
              src={product.imageUrl}
              alt={product.name}
              className="w-14 h-14 rounded-xl object-contain bg-white/[0.04] border border-white/[0.06] shrink-0"
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
            />
          ) : (
            <div className="w-14 h-14 rounded-xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center shrink-0">
              <ImageOff className="w-5 h-5 text-[#52525B]" />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <h3 className="text-[17px] font-semibold text-[#FAFAFA] leading-snug">{product.name}</h3>
            {/* Price line under name */}
            {product.price > 0 && (
              <p className="text-sm text-[#71717A] mt-0.5">
                {product.currency}{product.price.toLocaleString()}
                {product.originalPrice && product.originalPrice > product.price && (
                  <span className="ml-1.5 line-through text-[#3F3F46]">
                    {product.currency}{product.originalPrice.toLocaleString()}
                  </span>
                )}
                {discount && discount > 0 && (
                  <span className="ml-1.5 text-emerald-400 font-medium">{discount}% off</span>
                )}
              </p>
            )}
            {!product.price && <p className="text-xs text-[#52525B] italic mt-0.5">Price unavailable</p>}
          </div>
        </div>

        {/* Quality badges */}
        <div className="flex items-center gap-1.5 flex-wrap mt-3">
          {product.highSignal && (
            <Badge className="bg-violet-500/20 text-violet-300 border-violet-500/30 text-[10px]">
              <Sparkles className="w-2.5 h-2.5 mr-1" />HIGH SIGNAL
            </Badge>
          )}
          {product.confidence && product.dataCoverage != null && (
            <Badge
              title={`${Math.round(product.dataCoverage * 100)}% of criteria backed by real research evidence`}
              className={cn(
                'text-[10px]',
                product.confidence === 'high' ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                  : product.confidence === 'medium' ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                  : 'bg-zinc-500/15 text-zinc-300 border-zinc-500/30',
              )}
            >
              <ShieldCheck className="w-2.5 h-2.5 mr-1" />
              {Math.round(product.dataCoverage * 100)}% data-backed
            </Badge>
          )}
          {product.sourceCoverage != null && product.sourceCoverage === 1 && (
            <Badge title="Based on a single source" className="bg-amber-500/15 text-amber-300 border-amber-500/30 text-[10px]">1 source</Badge>
          )}
          {product.purchased && (
            <Badge className="bg-emerald-500/20 text-emerald-300 border-emerald-500/30 text-[10px]">
              <Check className="w-2.5 h-2.5 mr-1" />You bought this
            </Badge>
          )}
          {product.crossSubredditSignal?.signal === 'split' && !product.crossSubredditSignal._is_fallback && (
            <Badge className="bg-amber-500/20 text-amber-300 border-amber-500/30 text-[10px]">
              <AlertTriangle className="w-2.5 h-2.5 mr-1" />Mixed signal
            </Badge>
          )}
        </div>
      </div>

      {/* ─── SPEC TABLE ──────────────────────────────────────────────────── */}
      {specs.length > 0 && (
        <div className="px-5 py-3 border-b border-white/[0.05]">
          <div className="space-y-0">
            {specs.map((spec, i) => (
              <div
                key={spec.label}
                className={cn(
                  'flex items-center justify-between py-[7px] text-sm',
                  i < specs.length - 1 && 'border-b border-white/[0.04]',
                )}
              >
                <span className="text-[#71717A]">{spec.label}</span>
                <span className={cn(
                  'font-semibold text-right',
                  spec.highlight ? 'text-emerald-300' : 'text-[#FAFAFA]',
                )}>
                  {spec.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ─── SENTIMENT % + EMOJI BREAKDOWN ───────────────────────────────── */}
      {(sentimentPct !== null || (product.mentionCount ?? 0) > 0) && (
        <div className="px-5 py-4 border-b border-white/[0.05]">
          <div className="flex items-center gap-4">
            {/* Big % */}
            {sentimentPct !== null && (
              <div className="shrink-0">
                <span className={cn('text-4xl font-bold tabular-nums', sentimentColor)}>
                  {sentimentPct}%
                </span>
              </div>
            )}
            <div className="flex-1 min-w-0 space-y-1.5">
              {/* Sentiment label */}
              {sentimentLabel && (
                <p className={cn('text-sm font-medium', sentimentColor)}>{sentimentLabel}</p>
              )}
              {/* Emoji breakdown */}
              <div className="flex items-center gap-3 text-sm flex-wrap">
                {pos > 0 && (
                  <span className="flex items-center gap-1 text-emerald-300 font-medium">
                    ✅ <span>{pos}</span>
                  </span>
                )}
                {neutralCount > 0 && (
                  <span className="flex items-center gap-1 text-[#A1A1AA] font-medium">
                    😐 <span>{neutralCount}</span>
                  </span>
                )}
                {neg > 0 && (
                  <span className="flex items-center gap-1 text-rose-300 font-medium">
                    ❌ <span>{neg}</span>
                  </span>
                )}
                {(product.mentionCount ?? 0) > 0 && (
                  <span className="text-[#52525B] text-xs">
                    · {product.mentionCount} Reddit mention{(product.mentionCount ?? 0) !== 1 ? 's' : ''}
                  </span>
                )}
                {product.overallRank && (
                  <span className="text-[#52525B] text-xs">· #{product.overallRank} overall</span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ─── SCORE BAR ───────────────────────────────────────────────────── */}
      <div className="px-5 py-3 border-b border-white/[0.05]">
        <div className="flex items-center gap-3">
          <div className="flex-1 h-2 bg-white/[0.06] rounded-full overflow-hidden">
            <motion.div
              className={`h-full bg-gradient-to-r ${scoreBar} rounded-full`}
              initial={{ width: 0 }}
              animate={{ width: `${product.score}%` }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
            />
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className={cn('font-mono text-xl font-bold', scoreColor)}>{product.score}%</span>
            {recommendPct !== null && (
              <motion.div
                initial={{ opacity: 0, scale: 0.85 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.3, delay: 0.5 }}
                className={cn(
                  'flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border font-semibold whitespace-nowrap',
                  recommendPct >= 70 ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                    : recommendPct >= 40 ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                    : 'bg-rose-500/15 text-rose-300 border-rose-500/30',
                )}
              >
                <ThumbsUp className="w-2.5 h-2.5" />
                {recommendPct}% recommend
              </motion.div>
            )}
          </div>
        </div>
        {product.gapToLeader != null && product.gapToLeader > 0 && (
          <p className="text-[11px] text-[#52525B] mt-1">{product.gapToLeader.toFixed(1)} pts behind leader</p>
        )}
      </div>

      {/* ─── TAG CLOUDS ──────────────────────────────────────────────────── */}
      {(hasPraise || hasComplaints) && (
        <div className="px-5 py-3 border-b border-white/[0.05] space-y-2">
          {hasPraise && (
            <div className="flex flex-wrap gap-1.5">
              {product.praise!.slice(0, 5).map((p, i) => (
                <span key={i} className="text-[11px] px-2.5 py-1 rounded-full bg-emerald-500/[0.08] text-emerald-300 border border-emerald-500/20 font-medium leading-none">
                  ✓ {p.length > 38 ? p.slice(0, 37) + '…' : p}
                </span>
              ))}
              {(product.praise!.length) > 5 && (
                <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/[0.04] text-[#71717A] border border-white/[0.08] leading-none">
                  +{product.praise!.length - 5}
                </span>
              )}
            </div>
          )}
          {hasComplaints && (
            <div className="flex flex-wrap gap-1.5">
              {product.complaints!.slice(0, 4).map((c, i) => (
                <span key={i} className="text-[11px] px-2.5 py-1 rounded-full bg-rose-500/[0.06] text-rose-300 border border-rose-500/20 font-medium leading-none">
                  ✕ {c.text.length > 38 ? c.text.slice(0, 37) + '…' : c.text}
                </span>
              ))}
              {(product.complaints!.length) > 4 && (
                <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/[0.04] text-[#71717A] border border-white/[0.08] leading-none">
                  +{product.complaints!.length - 4}
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* ─── QUOTES BOX ──────────────────────────────────────────────────── */}
      {quotes.length > 0 && (
        <div className="px-5 py-3 border-b border-white/[0.05]">
          <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] px-4 py-3 space-y-2.5">
            {quotes.map((q, i) => (
              <p key={i} className="text-sm text-[#A1A1AA] leading-relaxed">
                &ldquo;{q.text}&rdquo;{' '}
                <span className="text-[#52525B] text-xs font-medium">— {q.source}</span>
              </p>
            ))}
          </div>
        </div>
      )}

      {/* ─── TOP REDDIT COMMENTS ─────────────────────────────────────────── */}
      {allRecords.length > 0 && quotes.length === 0 && (
        <div className="px-5 py-3 border-b border-white/[0.05]">
          <p className="text-[10px] uppercase tracking-widest text-[#52525B] font-semibold mb-2">
            Reddit comments
          </p>
          <div className="space-y-2">
            {visibleRecords.map((record, i) => (
              <div key={i} className="flex items-start gap-2">
                <SentimentIcon sentiment={record.sentiment} size="xs" />
                <p className="text-xs text-[#71717A] leading-relaxed">
                  &ldquo;{record.comment_text.slice(0, 160)}{record.comment_text.length > 160 ? '…' : ''}&rdquo;
                </p>
              </div>
            ))}
          </div>
          {allRecords.length > 3 && (
            <button
              onClick={() => setShowAllComments(!showAllComments)}
              className="mt-2 text-xs text-violet-400 hover:text-violet-300 transition-colors"
            >
              {showAllComments ? 'Show fewer' : `Load ${allRecords.length - 3} more comments`}
            </button>
          )}
        </div>
      )}

      {/* ─── SOURCE EVIDENCE TRAIL ───────────────────────────────────────── */}
      {(product.sourcePassages?.length ?? 0) > 0 && quotes.length === 0 && (
        <div className="px-5 py-3 border-b border-white/[0.05]">
          <details className="group">
            <summary className="flex items-center gap-2 text-xs text-[#71717A] cursor-pointer hover:text-[#A1A1AA] transition-colors list-none select-none">
              <svg className="w-3 h-3 transition-transform group-open:rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
              </svg>
              Evidence trail
              <span className="text-[#52525B]">({product.sourcePassages!.length} source{product.sourcePassages!.length > 1 ? 's' : ''})</span>
            </summary>
            <div className="mt-2 pl-4 space-y-2">
              {product.sourcePassages!.map((passage, i) => (
                <div key={i} className="flex items-start gap-2">
                  <SentimentIcon sentiment={passage.sentiment} size="xs" />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-[#71717A] leading-relaxed italic">
                      &ldquo;{passage.text.slice(0, 180)}{passage.text.length > 180 ? '…' : ''}&rdquo;
                    </p>
                    {passage.thread_url && (
                      <a
                        href={passage.thread_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 mt-0.5 text-[9px] text-violet-400/70 hover:text-violet-300 transition-colors"
                      >
                        <ExternalLink className="w-2 h-2" />
                        {(() => {
                          try { const m = passage.thread_url.match(/reddit\.com\/r\/([^/]+)/); return m ? `r/${m[1]}` : 'Source' }
                          catch { return 'Source' }
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

      {/* ─── COMMUNITY DISCUSSIONS ───────────────────────────────────────── */}
      {(redditDiscussions.length > 0 || reviewLinks.length > 0) && (
        <div className="px-5 py-3 border-b border-white/[0.05]">
          <button
            onClick={() => setShowDiscussions(!showDiscussions)}
            className="flex items-center gap-2 text-xs text-[#71717A] hover:text-[#A1A1AA] transition-colors group w-full"
          >
            <MessageSquare className="w-3.5 h-3.5 group-hover:text-violet-400 transition-colors" />
            <span className="flex-1 text-left">
              Discussed in{' '}
              {redditDiscussions.length > 0 && (
                <span className="text-[#A1A1AA] font-medium">{redditDiscussions.length} {redditDiscussions.length === 1 ? 'community' : 'communities'}</span>
              )}
              {redditDiscussions.length > 0 && reviewLinks.length > 0 && <span className="text-[#3F3F46]"> · </span>}
              {reviewLinks.length > 0 && (
                <span className="text-[#A1A1AA] font-medium">{reviewLinks.length} {reviewLinks.length === 1 ? 'review site' : 'review sites'}</span>
              )}
            </span>
            {showDiscussions ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
          <AnimatePresence>
            {showDiscussions && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden"
              >
                <div className="mt-2.5 space-y-3">
                  {redditDiscussions.length > 0 && (
                    <div className="space-y-1.5">
                      <p className="text-[10px] uppercase tracking-widest text-[#52525B] font-semibold">Reddit</p>
                      <div className="flex flex-wrap gap-1.5">
                        {redditDiscussions.map(d => (
                          <a key={d.label} href={d.url} target="_blank" rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg bg-violet-500/[0.08] text-violet-300/90 border border-violet-500/20 hover:bg-violet-500/20 transition-all duration-150">
                            {d.label}<ExternalLink className="w-2.5 h-2.5 opacity-50" />
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
                  {reviewLinks.length > 0 && (
                    <div className="space-y-1.5">
                      <p className="text-[10px] uppercase tracking-widest text-[#52525B] font-semibold">Review sites</p>
                      <div className="flex flex-wrap gap-1.5">
                        {reviewLinks.map(r => (
                          <a key={r.label} href={r.url} target="_blank" rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg bg-sky-500/[0.08] text-sky-300/90 border border-sky-500/20 hover:bg-sky-500/20 transition-all duration-150">
                            {r.label}<ExternalLink className="w-2.5 h-2.5 opacity-50" />
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {/* ─── CROSS-SUBREDDIT WARNING ──────────────────────────────────────── */}
      {product.crossSubredditSignal?.signal === 'split'
        && !product.crossSubredditSignal._is_fallback
        && product.crossSubredditSignal.explanation && (
        <div className="px-5 py-3 border-b border-white/[0.05]">
          <div className="p-3 rounded-xl bg-amber-500/[0.06] border border-amber-500/20">
            <p className="text-xs text-amber-300/80 leading-relaxed">
              <span className="font-medium text-amber-300">Community split:</span>{' '}
              {product.crossSubredditSignal.explanation}
            </p>
            {product.crossSubredditSignal.context_note && (
              <p className="text-xs text-[#A1A1AA] mt-1">{product.crossSubredditSignal.context_note}</p>
            )}
          </div>
        </div>
      )}

      {/* ─── PRICE / STORE / RATING ───────────────────────────────────────── */}
      <div className="px-5 py-3 border-b border-white/[0.05]">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm text-[#A1A1AA]">on {product.store}</span>
          {product.rating != null && product.rating > 0 && (
            <>
              <span className="text-[#3F3F46]">·</span>
              <div className="flex items-center gap-1.5">
                <div className="flex items-center gap-0.5">
                  {[1,2,3,4,5].map(i => (
                    <Star key={i} className={cn(
                      'w-3 h-3',
                      i <= Math.floor(product.rating!) ? 'text-amber-400 fill-amber-400'
                        : i === Math.ceil(product.rating!) && product.rating! % 1 >= 0.5 ? 'text-amber-400 fill-amber-400/50'
                        : 'text-white/10',
                    )} />
                  ))}
                </div>
                <span className="text-sm font-semibold text-amber-300">{product.rating.toFixed(1)}</span>
                {product.reviewCount != null && product.reviewCount > 0 && (
                  <span className="text-xs text-[#71717A]">({product.reviewCount.toLocaleString()} ratings)</span>
                )}
              </div>
            </>
          )}
          {product.matchScore != null && product.matchScore > 0 && (
            <>
              <span className="text-[#3F3F46]">·</span>
              <span className={cn(
                'flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border',
                product.matchScore >= 0.85 ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25'
                  : product.matchScore >= 0.65 ? 'bg-amber-500/10 text-amber-400 border-amber-500/25'
                  : 'bg-white/[0.05] text-[#71717A] border-white/[0.10]',
              )}>
                <ShieldCheck className="w-2.5 h-2.5" />
                {Math.round(product.matchScore * 100)}% match
              </span>
            </>
          )}
        </div>
        {product.alternativePrices && product.alternativePrices.length > 0 && (
          <p className="mt-1.5 text-xs text-[#71717A]">
            Also: {product.alternativePrices.map((alt, i) => (
              <span key={alt.store}>{i > 0 && ' · '}{alt.store} {product.currency}{alt.price.toLocaleString()}</span>
            ))}
          </p>
        )}
      </div>

      {/* ─── VERDICT ─────────────────────────────────────────────────────── */}
      {product.fitReason && (
        <div className="px-5 py-3 border-b border-white/[0.05]">
          <p className="text-[10px] uppercase tracking-widest text-[#52525B] font-semibold mb-1.5">Verdict</p>
          <p className="text-sm text-[#A1A1AA] leading-relaxed italic">
            {product.fitReason.length > 160 ? product.fitReason.slice(0, 159) + '…' : product.fitReason}
          </p>
          {product.fitReason.length > 160 && (
            <>
              <button
                onClick={() => setShowFitReason(!showFitReason)}
                className="mt-1.5 text-xs text-violet-400 hover:text-violet-300 transition-colors"
              >
                {showFitReason ? 'Show less' : 'Read full verdict'}
              </button>
              <AnimatePresence>
                {showFitReason && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    className="overflow-hidden"
                  >
                    <p className="mt-2 text-sm text-[#A1A1AA] leading-relaxed italic">{product.fitReason}</p>
                  </motion.div>
                )}
              </AnimatePresence>
            </>
          )}
        </div>
      )}

      {/* ─── EXPANDABLE: HOW IT SCORED ───────────────────────────────────── */}
      <div className="px-5 py-2">
        <button
          onClick={() => setShowScores(!showScores)}
          className="flex items-center gap-2 text-xs text-[#71717A] hover:text-[#A1A1AA] transition-colors py-1 w-full"
        >
          {showScores ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
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
              <div className="pb-3 space-y-2.5">
                {Object.entries(product.criteriaScores).map(([criterion, data]) => (
                  <div key={criterion}>
                    <div className="flex items-center justify-between mb-0.5">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-xs text-[#A1A1AA]">{criterion}</span>
                        {data.relative_rank && (
                          <span className={cn(
                            'text-[9px] px-1.5 py-0.5 rounded-md border font-medium',
                            data.relative_rank === 'Best' ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25'
                              : data.relative_rank === 'Above avg' ? 'bg-teal-500/15 text-teal-300 border-teal-500/25'
                              : data.relative_rank === 'Average' ? 'bg-blue-500/15 text-blue-300 border-blue-500/25'
                              : data.relative_rank === 'Weakest' ? 'bg-rose-500/15 text-rose-300 border-rose-500/25'
                              : data.relative_rank === 'Only option' ? 'bg-white/[0.08] text-[#71717A] border-white/[0.12]'
                              : 'bg-zinc-500/15 text-zinc-300 border-zinc-500/25',
                          )}>
                            {data.relative_rank}
                          </span>
                        )}
                      </div>
                      <span className={cn(
                        'font-mono text-xs font-medium shrink-0',
                        data.score >= 8 ? 'text-emerald-400' : data.score >= 5 ? 'text-amber-400' : 'text-rose-400',
                      )}>
                        {data.score}/10
                      </span>
                    </div>
                    {data.evidence && data.evidence !== 'no direct data found' && (
                      <p className="text-[11px] text-[#52525B] leading-relaxed">{data.evidence}</p>
                    )}
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* ─── ACTIONS ─────────────────────────────────────────────────────── */}
      <div className="px-5 pb-5 pt-1 flex items-center gap-3 border-t border-white/[0.05] mt-1">
        <Button
          variant="ghost"
          size="sm"
          onClick={onTogglePurchased}
          className={cn(
            'text-[#A1A1AA] hover:text-[#FAFAFA] text-xs',
            product.purchased && 'text-emerald-300 hover:text-emerald-200',
          )}
        >
          {product.purchased ? <Check className="w-3.5 h-3.5 mr-1.5" /> : <ShoppingCart className="w-3.5 h-3.5 mr-1.5" />}
          {product.purchased ? 'Bought' : 'I bought this'}
        </Button>
        <Button size="sm" className="bg-violet-600 hover:bg-violet-500 text-xs ml-auto" asChild>
          <a href={product.storeUrl || '#'} target="_blank" rel="noopener noreferrer">
            Open on {product.store}
            <ExternalLink className="w-3.5 h-3.5 ml-1.5" />
          </a>
        </Button>
      </div>
    </motion.div>
  )
}
