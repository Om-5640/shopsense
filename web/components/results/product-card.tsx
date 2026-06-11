'use client'

import { useState, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ChevronDown, ChevronUp, ExternalLink, Star, Check,
  Sparkles, ShoppingCart, ImageOff, ThumbsUp, ThumbsDown,
  AlertTriangle, Minus, ShieldCheck, MessageSquare,
  Zap, VolumeX, Music, Bluetooth as BluetoothIcon,
  Droplets, Speaker, Waves, Users, Quote, TrendingUp,
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

// ─── Spec chip colour map ─────────────────────────────────────────────────────

type SpecStyle = { bg: string; text: string; border: string; Icon: React.ComponentType<{ className?: string }> }

const SPEC_STYLES: Record<string, SpecStyle> = {
  Battery:          { bg: 'bg-amber-500/10',   text: 'text-amber-300',   border: 'border-amber-500/25',   Icon: Zap },
  ANC:              { bg: 'bg-violet-500/10',  text: 'text-violet-300',  border: 'border-violet-500/25',  Icon: VolumeX },
  Codec:            { bg: 'bg-emerald-500/10', text: 'text-emerald-300', border: 'border-emerald-500/25', Icon: Music },
  Bluetooth:        { bg: 'bg-sky-500/10',     text: 'text-sky-300',     border: 'border-sky-500/25',     Icon: BluetoothIcon },
  'IP Rating':      { bg: 'bg-cyan-500/10',    text: 'text-cyan-300',    border: 'border-cyan-500/25',    Icon: Droplets },
  Driver:           { bg: 'bg-rose-500/10',    text: 'text-rose-300',    border: 'border-rose-500/25',    Icon: Speaker },
  Sound:            { bg: 'bg-purple-500/10',  text: 'text-purple-300',  border: 'border-purple-500/25',  Icon: Waves },
  'Personal Sound': { bg: 'bg-teal-500/10',    text: 'text-teal-300',    border: 'border-teal-500/25',    Icon: Waves },
}
const SPEC_FALLBACK: SpecStyle = { bg: 'bg-white/[0.05]', text: 'text-[#A1A1AA]', border: 'border-white/[0.10]', Icon: Sparkles }

// ─── Spec extraction (identical regex logic to previous version) ──────────────

interface SpecRow { label: string; value: string; highlight: boolean }

function extractSpecTable(criteriaScores: Record<string, { score: number; evidence?: string }>): SpecRow[] {
  const rows: SpecRow[] = []
  const seen = new Set<string>()

  const DEFS: Array<{ match: RegExp; label: string; extract: (ev: string) => string | null }> = [
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

// ─── Context tag ──────────────────────────────────────────────────────────────

function computeContextTag(product: Product): { label: string; cls: string } | null {
  const mc = product.mentionCount ?? 0
  const pos = product.positiveMentions ?? 0
  const neg = product.negativeMentions ?? 0
  const total = pos + neg
  const posRatio = total > 0 ? pos / total : 0
  if (mc === 0) return { label: 'Too new for Reddit verdict', cls: 'bg-white/[0.06] text-[#71717A] border-white/[0.10]' }
  if (mc < 5)   return { label: 'New — limited data',         cls: 'bg-amber-500/10 text-amber-400 border-amber-500/20' }
  if (product.rank === 1 && mc >= 15)      return { label: '🏆 Recommended',      cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' }
  if (product.rank === 1)                  return { label: '🏆 Top Reddit pick',   cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' }
  if (product.rank <= 3 && posRatio >= 0.75) return { label: 'Strong contender',  cls: 'bg-violet-500/15 text-violet-300 border-violet-500/25' }
  if (product.rank <= 3)                   return { label: 'Strong contender',     cls: 'bg-violet-500/15 text-violet-300 border-violet-500/25' }
  if (total >= 5 && posRatio >= 0.90)      return { label: 'Community favourite', cls: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20' }
  return { label: 'Solid pick', cls: 'bg-sky-500/10 text-sky-300 border-sky-500/20' }
}

// ─── All comments (sourcePassages + sentimentRecords, deduped + quality-filtered) ──

interface CommentItem { text: string; sentiment: string; source: string; url?: string }

const _intentPhrases = ['will buy', 'going to buy', 'planning to buy', 'about to buy', 'just ordered', 'gonna buy', 'want to buy', 'ordering soon']

function isQualityComment(text: string): boolean {
  if (text.length < 25) return false
  const lower = text.toLowerCase()
  return !(_intentPhrases.some(p => lower.includes(p)) && text.length < 100)
}

function buildAllComments(product: Product): CommentItem[] {
  const seen = new Set<string>()
  const result: CommentItem[] = []

  const addComment = (text: string, sentiment: string, source: string, url?: string) => {
    const key = text.slice(0, 70).toLowerCase().replace(/\s+/g, ' ')
    if (seen.has(key) || !isQualityComment(text)) return
    seen.add(key)
    result.push({ text, sentiment, source, url })
  }

  for (const p of product.sourcePassages ?? []) {
    let src = 'Reddit'
    const m = p.thread_url?.match(/reddit\.com\/r\/([^/]+)/)
    if (m) src = `r/${m[1]}`
    addComment(p.text, p.sentiment, src, p.thread_url || undefined)
  }
  for (const r of product.sentimentRecords ?? []) {
    addComment(r.comment_text, r.sentiment, 'Reddit')
  }
  return result
}

// ─── Thread sources (unique subreddits with links) ───────────────────────────

interface ThreadSource { label: string; url: string; isSpecific: boolean }

function getThreadSources(product: Product): ThreadSource[] {
  const seenSubs = new Set<string>()
  const seenUrls = new Set<string>()
  const result: ThreadSource[] = []

  // Specific thread URLs from sourcePassages (highest quality — link to actual thread)
  for (const p of product.sourcePassages ?? []) {
    if (!p.thread_url || seenUrls.has(p.thread_url)) continue
    const m = p.thread_url.match(/reddit\.com\/r\/([^/]+)/)
    if (!m) continue
    seenUrls.add(p.thread_url)
    const sub = m[1]
    if (!seenSubs.has(sub)) seenSubs.add(sub)
    result.push({ label: `r/${sub}`, url: p.thread_url, isSpecific: true })
  }

  // Subreddit search links from sources array (covers subreddits not in passages)
  for (const s of product.sources ?? []) {
    if (!s.startsWith('reddit:')) continue
    const sub = s.slice(7)
    if (seenSubs.has(sub)) continue
    seenSubs.add(sub)
    result.push({
      label: `r/${sub}`,
      url: `https://www.reddit.com/r/${encodeURIComponent(sub)}/search?q=${encodeURIComponent(product.name)}&sort=top`,
      isSpecific: false,
    })
  }
  return result
}

// ─── Best featured quote ──────────────────────────────────────────────────────

function getBestQuote(product: Product): CommentItem | null {
  const qualityTerms = ['anc', 'battery', 'sound', 'quality', 'bass', 'call', 'hours', 'value', 'worth', 'recommend', 'excellent', 'amazing', 'great', 'terrible', 'disappointing', 'surprised', 'impressive', 'best', 'worst', 'price', 'noise cancel']

  const isGoodQuote = (text: string) => {
    if (text.length < 35 || text.length > 350) return false
    const lower = text.toLowerCase()
    if (_intentPhrases.some(p => lower.includes(p))) return false
    return qualityTerms.some(t => lower.includes(t))
  }

  // Prefer positive sourcePassages with quality content
  for (const pass of product.sourcePassages ?? []) {
    if (pass.sentiment === 'positive' && isGoodQuote(pass.text)) {
      let src = 'Reddit'
      const m = pass.thread_url?.match(/reddit\.com\/r\/([^/]+)/)
      if (m) src = `r/${m[1]}`
      return { text: pass.text.slice(0, 220), sentiment: 'positive', source: src, url: pass.thread_url || undefined }
    }
  }
  // Any quality passage
  for (const pass of product.sourcePassages ?? []) {
    if (isGoodQuote(pass.text)) {
      let src = 'Reddit'
      const m = pass.thread_url?.match(/reddit\.com\/r\/([^/]+)/)
      if (m) src = `r/${m[1]}`
      return { text: pass.text.slice(0, 220), sentiment: pass.sentiment, source: src, url: pass.thread_url || undefined }
    }
  }
  // Representative quote fallback
  if (product.representativeQuote && isGoodQuote(product.representativeQuote)) {
    return { text: product.representativeQuote.slice(0, 220), sentiment: 'positive', source: 'Reddit' }
  }
  // Any positive sentiment record
  for (const r of product.sentimentRecords ?? []) {
    if (r.sentiment === 'positive' && isGoodQuote(r.comment_text)) {
      return { text: r.comment_text.slice(0, 220), sentiment: 'positive', source: 'Reddit' }
    }
  }
  return null
}

// ─── Component ─────────────────────────────────────────────────────────────────

export function ProductCard({ product, isSelected, onToggleSelect, onTogglePurchased }: ProductCardProps) {
  const [showAllComments, setShowAllComments]   = useState(false)
  const [showAllPros, setShowAllPros]           = useState(false)
  const [showAllCons, setShowAllCons]           = useState(false)
  const [showAllThreads, setShowAllThreads]     = useState(false)
  const [showScores, setShowScores]             = useState(false)
  const [showFitReason, setShowFitReason]       = useState(false)

  // ── Sentiment stats ───────────────────────────────────────────────────────
  const pos           = product.positiveMentions ?? 0
  const neg           = product.negativeMentions ?? 0
  const totalSentiment = pos + neg
  const neutralCount  = (product.sentimentRecords ?? []).filter(r => r.sentiment === 'neutral').length
  const posRatio      = totalSentiment > 0 ? pos / totalSentiment : 0
  const recommendPct  = totalSentiment > 0 ? Math.round(posRatio * 100) : null
  const mentionCount  = product.mentionCount ?? 0
  const recommenders  = product.distinctRecommenders ?? 0

  const discount = product.originalPrice && product.originalPrice > product.price && product.price > 0
    ? Math.round((1 - product.price / product.originalPrice) * 100)
    : null

  // ── Memoised derived data ─────────────────────────────────────────────────
  const specs         = useMemo(() => extractSpecTable(product.criteriaScores), [product.criteriaScores])
  const allComments   = useMemo(() => buildAllComments(product), [product])
  const threadSources = useMemo(() => getThreadSources(product), [product])
  const bestQuote     = useMemo(() => getBestQuote(product), [product])

  const visibleComments = showAllComments ? allComments : allComments.slice(0, 3)
  const visibleThreads  = showAllThreads  ? threadSources : threadSources.slice(0, 4)

  // ── Pros / cons ───────────────────────────────────────────────────────────
  const prosList = (product.pros && product.pros.length > 0)
    ? product.pros
    : (product.praise ?? [])
  const consList = (product.cons && product.cons.length > 0)
    ? product.cons
    : (product.complaints ?? []).map(c => (typeof c === 'string' ? c : c.text) ?? '')

  const displayPros = showAllPros ? prosList : prosList.slice(0, 4)
  const displayCons = showAllCons ? consList : consList.slice(0, 3)

  // ── Colours ───────────────────────────────────────────────────────────────
  const contextTag  = computeContextTag(product)
  const scoreColor  = product.score >= 80 ? 'text-emerald-400' : product.score >= 50 ? 'text-amber-400' : 'text-rose-400'
  const scoreBarCls = product.score >= 80
    ? 'bg-gradient-to-r from-emerald-500 to-teal-400'
    : product.score >= 50
    ? 'bg-gradient-to-r from-amber-500 to-orange-400'
    : 'bg-gradient-to-r from-rose-500 to-red-400'
  const sentimentLabelCls = (recommendPct ?? 0) >= 70 ? 'text-emerald-300' : (recommendPct ?? 0) >= 40 ? 'text-amber-300' : 'text-rose-300'
  const sentimentBarCls   = (recommendPct ?? 0) >= 70
    ? 'bg-gradient-to-r from-emerald-500 to-teal-400'
    : (recommendPct ?? 0) >= 40
    ? 'bg-gradient-to-r from-amber-500 to-orange-400'
    : 'bg-gradient-to-r from-rose-500 to-red-400'

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ type: 'spring', damping: 25, stiffness: 200 }}
      className={cn(
        'relative rounded-2xl border bg-[#0F0F14] overflow-hidden transition-all duration-300',
        isSelected
          ? 'border-violet-500/60 shadow-[0_0_0_1px_rgba(139,92,246,0.3),0_4px_24px_rgba(139,92,246,0.12)]'
          : 'border-white/[0.07] hover:border-white/[0.13]',
      )}
    >
      {/* ── HEADER ───────────────────────────────────────────────────────── */}
      <div className={cn(
        'px-5 pt-5 pb-4',
        product.rank === 1 && 'bg-gradient-to-b from-amber-500/[0.05] to-transparent',
      )}>
        {/* Top row: rank + tag + checkbox */}
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-center gap-2.5 flex-wrap">
            <div className={cn(
              'w-8 h-8 rounded-lg flex items-center justify-center font-bold text-sm shrink-0',
              product.rank === 1
                ? 'bg-gradient-to-br from-amber-400 to-orange-500 text-white shadow-lg shadow-amber-500/30'
                : product.rank <= 3
                ? 'bg-gradient-to-br from-violet-600 to-violet-500 text-white shadow-md shadow-violet-500/20'
                : 'bg-white/[0.07] text-[#A1A1AA]',
            )}>
              #{product.rank}
            </div>
            {contextTag && (
              <span className={cn('text-[11px] px-2.5 py-0.5 rounded-full border font-medium whitespace-nowrap', contextTag.cls)}>
                {contextTag.label}
              </span>
            )}
            {product.highSignal && (
              <Badge className="bg-violet-500/20 text-violet-300 border-violet-500/30 text-[10px]">
                <Sparkles className="w-2.5 h-2.5 mr-1" />HIGH SIGNAL
              </Badge>
            )}
          </div>
          <Checkbox
            checked={isSelected}
            onCheckedChange={() => onToggleSelect()}
            className="w-4 h-4 border-white/20 data-[state=checked]:bg-violet-500 data-[state=checked]:border-violet-500 shrink-0"
          />
        </div>

        {/* Image + name + price */}
        <div className="flex items-start gap-3.5">
          {product.imageUrl ? (
            <img
              src={product.imageUrl} alt={product.name}
              className="w-16 h-16 rounded-xl object-contain bg-white/[0.04] border border-white/[0.07] shrink-0"
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
            />
          ) : (
            <div className="w-16 h-16 rounded-xl bg-white/[0.04] border border-white/[0.07] flex items-center justify-center shrink-0">
              <ImageOff className="w-5 h-5 text-[#52525B]" />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <h3 className="text-[17px] font-bold text-[#FAFAFA] leading-tight mb-1.5">{product.name}</h3>
            <div className="flex items-baseline gap-2 flex-wrap">
              {product.price > 0 ? (
                <>
                  <span className="text-xl font-bold text-white">{product.currency}{product.price.toLocaleString()}</span>
                  {product.originalPrice && product.originalPrice > product.price && (
                    <span className="text-sm line-through text-[#3F3F46]">{product.currency}{product.originalPrice.toLocaleString()}</span>
                  )}
                  {discount && discount > 0 && (
                    <span className="text-xs font-semibold text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded border border-emerald-500/20">
                      {discount}% off
                    </span>
                  )}
                  <span className="text-xs text-[#52525B]">on {product.store}</span>
                </>
              ) : (
                <span className="text-sm text-[#52525B] italic">Price unavailable</span>
              )}
            </div>
            {product.alternativePrices && product.alternativePrices.length > 0 && (
              <p className="text-[11px] text-[#52525B] mt-0.5">
                Also:{' '}
                {product.alternativePrices.map((alt, i) => (
                  <span key={alt.store}>
                    {i > 0 && ' · '}
                    {alt.url
                      ? <a href={alt.url} target="_blank" rel="noopener noreferrer" className="text-[#71717A] hover:text-[#A1A1AA] underline underline-offset-2 transition-colors">{alt.store} {product.currency}{alt.price.toLocaleString()}</a>
                      : <span className="text-[#71717A]">{alt.store} {product.currency}{alt.price.toLocaleString()}</span>
                    }
                  </span>
                ))}
              </p>
            )}
          </div>
        </div>

        {/* Badge row */}
        <div className="flex items-center gap-1.5 flex-wrap mt-3">
          {product.rating != null && product.rating > 0 && (
            <div className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-amber-500/10 border border-amber-500/20">
              <Star className="w-3 h-3 text-amber-400 fill-amber-400" />
              <span className="text-xs font-semibold text-amber-300">{product.rating.toFixed(1)}</span>
              {product.reviewCount && product.reviewCount > 0 && (
                <span className="text-[10px] text-[#71717A]">({product.reviewCount.toLocaleString()})</span>
              )}
            </div>
          )}
          {product.confidence && product.dataCoverage != null && (
            <div className={cn(
              'flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md border',
              product.confidence === 'high'   ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
                : product.confidence === 'medium' ? 'bg-amber-500/10 text-amber-300 border-amber-500/20'
                : 'bg-zinc-500/10 text-zinc-300 border-zinc-500/20',
            )}>
              <ShieldCheck className="w-3 h-3" />
              {Math.round(product.dataCoverage * 100)}% data-backed
            </div>
          )}
          {product.matchScore != null && product.matchScore > 0 && (
            <div className={cn(
              'flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md border',
              product.matchScore >= 0.85 ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                : product.matchScore >= 0.65 ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                : 'bg-white/[0.04] text-[#71717A] border-white/[0.08]',
            )}>
              <ShieldCheck className="w-3 h-3" />
              {Math.round(product.matchScore * 100)}% match
            </div>
          )}
          {product.purchased && (
            <div className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
              <Check className="w-3 h-3" />Bought
            </div>
          )}
          {product.crossSubredditSignal?.signal === 'split' && !product.crossSubredditSignal._is_fallback && (
            <div className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-300 border border-amber-500/20">
              <AlertTriangle className="w-3 h-3" />Split opinions
            </div>
          )}
        </div>
      </div>

      {/* ── SPEC CHIPS ────────────────────────────────────────────────────── */}
      {specs.length > 0 && (
        <div className="px-5 py-3 border-t border-white/[0.05]">
          <div className="flex flex-wrap gap-1.5">
            {specs.map(spec => {
              const s = SPEC_STYLES[spec.label] ?? SPEC_FALLBACK
              return (
                <span
                  key={spec.label}
                  className={cn(
                    'inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border font-medium',
                    s.bg, s.text, s.border,
                    spec.highlight && 'shadow-sm',
                  )}
                >
                  <s.Icon className="w-3 h-3 shrink-0" />
                  <span className="text-[#71717A] text-[11px] font-normal">{spec.label}</span>
                  <span className="font-semibold">{spec.value}</span>
                </span>
              )
            })}
          </div>
        </div>
      )}

      {/* ── COMMUNITY VERDICT ─────────────────────────────────────────────── */}
      {(mentionCount > 0 || totalSentiment > 0) && (
        <div className="px-5 py-4 border-t border-white/[0.05]">
          <p className="text-[10px] uppercase tracking-widest text-[#52525B] font-semibold mb-3">Community Verdict</p>

          {recommendPct !== null && (
            <>
              {/* Big % + bar */}
              <div className="flex items-center gap-3 mb-3">
                <span className={cn('text-5xl font-bold tabular-nums leading-none', sentimentLabelCls)}>
                  {recommendPct}%
                </span>
                <div className="flex-1 space-y-1.5">
                  <p className={cn('text-sm font-semibold', sentimentLabelCls)}>
                    {recommendPct >= 80 ? 'Highly recommended'
                      : recommendPct >= 60 ? 'Generally positive'
                      : recommendPct >= 40 ? 'Mixed opinions'
                      : 'Mostly critical'}
                  </p>
                  <div className="h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
                    <motion.div
                      className={cn('h-full rounded-full', sentimentBarCls)}
                      initial={{ width: 0 }}
                      animate={{ width: `${recommendPct}%` }}
                      transition={{ duration: 0.8, ease: 'easeOut' }}
                    />
                  </div>
                </div>
              </div>

              {/* Positive / neutral / negative buckets */}
              <div className="flex items-center gap-2 flex-wrap text-xs mb-2.5">
                {pos > 0 && (
                  <span className="flex items-center gap-1.5 bg-emerald-500/[0.08] border border-emerald-500/20 px-2.5 py-1 rounded-lg font-medium text-emerald-300">
                    <ThumbsUp className="w-3 h-3" />{pos} positive
                  </span>
                )}
                {neutralCount > 0 && (
                  <span className="flex items-center gap-1.5 bg-white/[0.04] border border-white/[0.08] px-2.5 py-1 rounded-lg font-medium text-[#A1A1AA]">
                    <Minus className="w-3 h-3" />{neutralCount} neutral
                  </span>
                )}
                {neg > 0 && (
                  <span className="flex items-center gap-1.5 bg-rose-500/[0.06] border border-rose-500/20 px-2.5 py-1 rounded-lg font-medium text-rose-300">
                    <ThumbsDown className="w-3 h-3" />{neg} critical
                  </span>
                )}
              </div>
            </>
          )}

          {/* Stats row */}
          <div className="flex items-center gap-3 flex-wrap text-xs text-[#71717A]">
            {mentionCount > 0 && (
              <span className="flex items-center gap-1">
                <MessageSquare className="w-3 h-3" />
                {mentionCount} Reddit thread{mentionCount !== 1 ? 's' : ''}
              </span>
            )}
            {recommenders > 0 && (
              <span className="flex items-center gap-1 text-violet-300 font-medium">
                <Users className="w-3 h-3 text-violet-400" />
                {recommenders} recommender{recommenders !== 1 ? 's' : ''}
              </span>
            )}
            {allComments.length > 0 && (
              <span className="flex items-center gap-1">
                <Quote className="w-3 h-3" />{allComments.length} comments analyzed
              </span>
            )}
            {product.gapToLeader != null && product.gapToLeader > 0 && (
              <span className="text-[#3F3F46]">{product.gapToLeader.toFixed(1)} pts behind #1</span>
            )}
          </div>

          {/* Split signal warning */}
          {product.crossSubredditSignal?.signal === 'split'
            && !product.crossSubredditSignal._is_fallback
            && product.crossSubredditSignal.explanation && (
            <div className="mt-3 p-2.5 rounded-xl bg-amber-500/[0.06] border border-amber-500/20">
              <p className="text-xs text-amber-300/80 leading-relaxed">
                <span className="font-semibold text-amber-300">Split across communities: </span>
                {product.crossSubredditSignal.explanation}
              </p>
            </div>
          )}
        </div>
      )}

      {/* ── MATCH SCORE BAR ───────────────────────────────────────────────── */}
      <div className="px-5 py-3 border-t border-white/[0.05]">
        <div className="flex items-center gap-3">
          <span className="text-[10px] uppercase tracking-wide text-[#52525B] font-medium w-16 shrink-0">Match</span>
          <div className="flex-1 h-2 bg-white/[0.06] rounded-full overflow-hidden">
            <motion.div
              className={cn('h-full rounded-full', scoreBarCls)}
              initial={{ width: 0 }}
              animate={{ width: `${product.score}%` }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
            />
          </div>
          <span className={cn('font-mono text-lg font-bold tabular-nums shrink-0', scoreColor)}>{product.score}%</span>
        </div>
      </div>

      {/* ── PROS & CONS ───────────────────────────────────────────────────── */}
      {(prosList.length > 0 || consList.length > 0) && (
        <div className="px-5 py-4 border-t border-white/[0.05]">
          <div className={cn('grid gap-5', prosList.length > 0 && consList.length > 0 ? 'grid-cols-2' : 'grid-cols-1')}>
            {prosList.length > 0 && (
              <div>
                <p className="text-[10px] uppercase tracking-widest text-emerald-500/70 font-semibold mb-2.5">Pros</p>
                <div className="space-y-2">
                  {displayPros.map((p, i) => {
                    const txt = typeof p === 'string' ? p : ''
                    return (
                      <div key={i} className="flex items-start gap-1.5">
                        <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-0.5" />
                        <span className="text-xs text-[#B0B0BA] leading-relaxed">{txt.length > 70 ? txt.slice(0, 69) + '…' : txt}</span>
                      </div>
                    )
                  })}
                  {prosList.length > 4 && (
                    <button onClick={() => setShowAllPros(!showAllPros)}
                      className="text-[10px] text-violet-400 hover:text-violet-300 transition-colors pl-5">
                      {showAllPros ? 'Show less' : `+${prosList.length - 4} more`}
                    </button>
                  )}
                </div>
              </div>
            )}
            {consList.length > 0 && (
              <div>
                <p className="text-[10px] uppercase tracking-widest text-rose-500/70 font-semibold mb-2.5">Cons</p>
                <div className="space-y-2">
                  {displayCons.map((c, i) => {
                    const txt = typeof c === 'string' ? c : ''
                    return (
                      <div key={i} className="flex items-start gap-1.5">
                        <ThumbsDown className="w-3 h-3 text-rose-400 shrink-0 mt-0.5" />
                        <span className="text-xs text-[#B0B0BA] leading-relaxed">{txt.length > 70 ? txt.slice(0, 69) + '…' : txt}</span>
                      </div>
                    )
                  })}
                  {consList.length > 3 && (
                    <button onClick={() => setShowAllCons(!showAllCons)}
                      className="text-[10px] text-violet-400 hover:text-violet-300 transition-colors pl-4">
                      {showAllCons ? 'Show less' : `+${consList.length - 3} more`}
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── REDDIT DISCUSSION + FEATURED QUOTE ────────────────────────────── */}
      {(threadSources.length > 0 || bestQuote) && (
        <div className="px-5 py-3 border-t border-white/[0.05]">
          {/* Thread chips */}
          {threadSources.length > 0 && (
            <div className="mb-3">
              <p className="text-[10px] uppercase tracking-widest text-[#52525B] font-semibold mb-2">Reddit Sources</p>
              <div className="flex flex-wrap gap-1.5">
                {visibleThreads.map((t, i) => (
                  <a key={i} href={t.url} target="_blank" rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg bg-violet-500/[0.07] text-violet-300/90 border border-violet-500/20 hover:bg-violet-500/18 transition-all duration-150">
                    {t.label}<ExternalLink className="w-2.5 h-2.5 opacity-50" />
                  </a>
                ))}
                {threadSources.length > 4 && (
                  <button
                    onClick={() => setShowAllThreads(!showAllThreads)}
                    className="text-xs px-2.5 py-1 rounded-lg bg-white/[0.04] text-[#71717A] border border-white/[0.08] hover:bg-white/[0.07] transition-colors"
                  >
                    {showAllThreads ? 'Less' : `+${threadSources.length - 4} more`}
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Featured quote */}
          {bestQuote && (
            <div className="p-3.5 rounded-xl bg-white/[0.025] border border-white/[0.07] relative">
              <Quote className="absolute top-2.5 right-3 w-4 h-4 text-white/[0.08]" />
              <p className="text-sm text-[#B4B4BE] leading-relaxed italic pr-6">
                &ldquo;{bestQuote.text.length > 260 ? bestQuote.text.slice(0, 259) + '…' : bestQuote.text}&rdquo;
              </p>
              <div className="flex items-center gap-2 mt-2">
                <span className="text-[10px] text-[#52525B] font-medium">— {bestQuote.source}</span>
                {bestQuote.url && (
                  <a href={bestQuote.url} target="_blank" rel="noopener noreferrer"
                    className="text-[10px] text-violet-400/60 hover:text-violet-300 transition-colors inline-flex items-center gap-0.5">
                    <ExternalLink className="w-2.5 h-2.5" />view thread
                  </a>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── ALL COMMENTS ──────────────────────────────────────────────────── */}
      {allComments.length > 0 && (
        <div className="px-5 py-3 border-t border-white/[0.05]">
          <div className="flex items-center justify-between mb-3">
            <p className="text-[10px] uppercase tracking-widest text-[#52525B] font-semibold">
              What People Say
              <span className="ml-1.5 normal-case tracking-normal font-normal text-[#3F3F46]">
                ({allComments.length} comment{allComments.length !== 1 ? 's' : ''})
              </span>
            </p>
            {allComments.length > 3 && (
              <button
                onClick={() => setShowAllComments(!showAllComments)}
                className="text-[11px] text-violet-400 hover:text-violet-300 transition-colors font-medium"
              >
                {showAllComments ? 'Show fewer' : `Read all ${allComments.length}`}
              </button>
            )}
          </div>

          <div className="space-y-2">
            {visibleComments.map((comment, i) => (
              <div key={i} className="flex items-start gap-2.5 p-2.5 rounded-xl bg-white/[0.025] border border-white/[0.05]">
                <div className={cn(
                  'shrink-0 w-5 h-5 rounded-md flex items-center justify-center mt-0.5',
                  comment.sentiment === 'positive' ? 'bg-emerald-500/15'
                    : comment.sentiment === 'negative' ? 'bg-rose-500/15'
                    : 'bg-white/[0.06]',
                )}>
                  {comment.sentiment === 'positive'
                    ? <ThumbsUp className="w-3 h-3 text-emerald-400" />
                    : comment.sentiment === 'negative'
                    ? <ThumbsDown className="w-3 h-3 text-rose-400" />
                    : <Minus className="w-3 h-3 text-[#71717A]" />
                  }
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-[#A1A1AA] leading-relaxed">
                    {comment.text.length > 220 ? comment.text.slice(0, 219) + '…' : comment.text}
                  </p>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-[10px] text-[#52525B]">— {comment.source}</span>
                    {comment.url && (
                      <a href={comment.url} target="_blank" rel="noopener noreferrer"
                        className="text-[10px] text-violet-400/50 hover:text-violet-300 transition-colors inline-flex items-center gap-0.5">
                        <ExternalLink className="w-2 h-2" />thread
                      </a>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── HOW IT SCORED ─────────────────────────────────────────────────── */}
      <div className="px-5 py-1.5 border-t border-white/[0.05]">
        <button
          onClick={() => setShowScores(!showScores)}
          className="flex items-center gap-2 text-xs text-[#71717A] hover:text-[#A1A1AA] transition-colors py-2 w-full"
        >
          <TrendingUp className="w-3.5 h-3.5" />
          How it scored
          <span className="ml-auto">{showScores ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}</span>
        </button>
        <AnimatePresence>
          {showScores && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="pb-3 space-y-3 pt-1">
                {Object.entries(product.criteriaScores).map(([criterion, data]) => (
                  <div key={criterion}>
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-xs text-[#A1A1AA]">{criterion}</span>
                        {data.relative_rank && (
                          <span className={cn(
                            'text-[9px] px-1.5 py-0.5 rounded-md border font-medium',
                            data.relative_rank === 'Best'      ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25'
                              : data.relative_rank === 'Above avg' ? 'bg-teal-500/15 text-teal-300 border-teal-500/25'
                              : data.relative_rank === 'Average'   ? 'bg-blue-500/15 text-blue-300 border-blue-500/25'
                              : data.relative_rank === 'Weakest'   ? 'bg-rose-500/15 text-rose-300 border-rose-500/25'
                              : data.relative_rank === 'Only option'? 'bg-white/[0.08] text-[#71717A] border-white/[0.12]'
                              : 'bg-zinc-500/15 text-zinc-300 border-zinc-500/25',
                          )}>
                            {data.relative_rank}
                          </span>
                        )}
                      </div>
                      <span className={cn(
                        'font-mono text-xs font-bold shrink-0',
                        data.score >= 8 ? 'text-emerald-400' : data.score >= 5 ? 'text-amber-400' : 'text-rose-400',
                      )}>
                        {data.score}/10
                      </span>
                    </div>
                    <div className="h-0.5 bg-white/[0.04] rounded-full overflow-hidden mb-1.5">
                      <div
                        className={cn('h-full rounded-full',
                          data.score >= 8 ? 'bg-emerald-500' : data.score >= 5 ? 'bg-amber-500' : 'bg-rose-500',
                        )}
                        style={{ width: `${data.score * 10}%` }}
                      />
                    </div>
                    {data.evidence && data.evidence !== 'no direct data found' && (
                      <p className="text-[10px] text-[#52525B] leading-relaxed">{data.evidence}</p>
                    )}
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* ── WHY THIS FITS YOU ─────────────────────────────────────────────── */}
      {product.fitReason && (
        <div className="px-5 py-1.5 border-t border-white/[0.05]">
          <button
            onClick={() => setShowFitReason(!showFitReason)}
            className="flex items-center gap-2 text-xs text-[#71717A] hover:text-[#A1A1AA] transition-colors py-2 w-full"
          >
            <Sparkles className="w-3.5 h-3.5 text-violet-400/60" />
            Why this fits you
            <span className="ml-auto">{showFitReason ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}</span>
          </button>
          <AnimatePresence>
            {showFitReason && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden"
              >
                <p className="pb-3 text-sm text-[#A1A1AA] leading-relaxed">{product.fitReason}</p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {/* ── ACTIONS ────────────────────────────────────────────────────────── */}
      <div className="px-5 pb-5 pt-3 flex items-center gap-3 border-t border-white/[0.05]">
        <Button
          variant="ghost"
          size="sm"
          onClick={onTogglePurchased}
          className={cn(
            'text-[#A1A1AA] hover:text-[#FAFAFA] text-xs gap-1.5',
            product.purchased && 'text-emerald-300 hover:text-emerald-200',
          )}
        >
          {product.purchased ? <Check className="w-3.5 h-3.5" /> : <ShoppingCart className="w-3.5 h-3.5" />}
          {product.purchased ? 'Bought' : 'I bought this'}
        </Button>
        <Button size="sm" className="bg-violet-600 hover:bg-violet-500 text-xs ml-auto gap-1.5" asChild>
          <a href={product.storeUrl || '#'} target="_blank" rel="noopener noreferrer">
            Open on {product.store}
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        </Button>
      </div>
    </motion.div>
  )
}
