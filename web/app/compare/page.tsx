'use client'

import { Suspense, useState, useEffect, useMemo } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ArrowLeft, Trophy, ExternalLink, GitCompare, Home, BarChart3,
  Star, ThumbsUp, ChevronDown, ChevronUp, ShieldCheck,
} from 'lucide-react'
import { AnimatedBackground } from '@/components/layout/animated-background'
import { Header } from '@/components/layout/header'
import { Footer } from '@/components/layout/footer'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { getSearchResult } from '@/lib/api'
import { useResultsStore, deriveSidebarCriteria } from '@/lib/store'
import type { ScoredProduct, Rubric } from '@/lib/types'

// ─── Types ─────────────────────────────────────────────────────────────────────

interface CompareProduct {
  id: string
  name: string
  score: number
  price: number
  currency: string
  store: string
  storeUrl: string
  rating?: number
  reviewCount?: number
  imageUrl?: string
  criteriaScores: Record<string, { score: number; evidence?: string }>
  fitReason: string
  mentionCount?: number
  positiveMentions?: number
  negativeMentions?: number
  dominantSentiment?: string
  sentimentScore?: number | null
  praise?: string[]
  complaints?: Array<{ text: string }>
  representativeQuote?: string
  sources?: string[]
  highSignal?: boolean
}

interface SpecRow { label: string; value: string }

// ─── Adapters ──────────────────────────────────────────────────────────────────

function toCurrencySymbol(c: string) {
  return c === 'INR' ? '₹' : c === 'USD' ? '$' : c === 'GBP' ? '£' : c === 'EUR' ? '€' : c
}

function toCompareProduct(p: ScoredProduct, rubric: Rubric, weights: Record<string, number>): CompareProduct {
  const criteria = deriveSidebarCriteria(rubric, weights)
  const labelMap = Object.fromEntries(criteria.map(c => [c.id, c.label]))
  const sym = toCurrencySymbol(p.price?.currency ?? 'INR')
  const retailer = p.price?.retailers?.find(r => !r.is_search) ?? p.price?.retailers?.[0]
  const best = p.price?.best_price
  const priceNum = best?.price_inr ?? best?.price_usd ?? retailer?.price_inr ?? retailer?.price_usd ?? 0
  const criteriaScores: Record<string, { score: number; evidence?: string }> = {}
  p.scores.forEach(s => {
    const label = labelMap[s.criterion] ?? s.label ?? s.criterion
    criteriaScores[label] = { score: s.score, evidence: s.evidence || undefined }
  })
  return {
    id: p.name, name: p.name, score: p.percentage,
    price: priceNum, currency: sym,
    store: retailer?.name ?? 'Search',
    storeUrl: retailer?.url ?? `https://www.google.com/search?q=buy+${encodeURIComponent(p.name)}`,
    rating: retailer?.rating, reviewCount: retailer?.review_count,
    imageUrl: retailer?.image_url ?? p.price?.retailers?.find(r => r.image_url)?.image_url,
    criteriaScores, fitReason: p.explanation ?? '',
    mentionCount: p.mention_count, positiveMentions: p.positive_mentions, negativeMentions: p.negative_mentions,
    dominantSentiment: p.dominant_sentiment ?? undefined, sentimentScore: p.sentiment_score ?? null,
    praise: p.praise ?? [], complaints: p.complaints ?? [],
    representativeQuote: p.representative_quote, sources: p.sources ?? [],
    highSignal: p.signal_strength === 'high',
  }
}

// ─── Spec extraction ───────────────────────────────────────────────────────────

const SPEC_DEFS: Array<{ match: RegExp; label: string; extract: (ev: string) => string | null }> = [
  {
    match: /anc|noise cancel|noise reduc/i, label: 'ANC',
    extract: ev => {
      const m = ev.match(/(\d+)\s*dB/i); if (m) return `${m[1]} dB`
      if (/\bno\b|none|not present/i.test(ev)) return 'No'
      if (/yes|active|good|great|excellent|support/i.test(ev)) return 'Yes'
      return null
    },
  },
  {
    match: /battery|playtime|playback.*time|endurance/i, label: 'Battery',
    extract: ev => { const m = ev.match(/(\d+(?:\.\d+)?)\s*(?:hrs?|hours?)/i); return m ? `${m[1]} hrs` : null },
  },
  {
    match: /codec(?!\s*support.*quality)|audio.*codec/i, label: 'Codec',
    extract: ev => {
      for (const kw of ['LDAC', 'aptX HD', 'aptX Adaptive', 'aptX Lossless', 'aptX', 'LC3plus', 'LC3', 'AAC', 'SBC'])
        if (ev.includes(kw)) return kw
      return null
    },
  },
  {
    match: /bluetooth.*ver|bt.*ver|wireless.*connect|connectivity/i, label: 'Bluetooth',
    extract: ev => {
      const m = ev.match(/(?:BT|Bluetooth)\s*v?(\d+\.\d+)/i)
        ?? ev.match(/v?(\d+\.\d+)\s*(?:BT|Bluetooth)/i)
        ?? ev.match(/\b(\d+\.\d+)\b/)
      return m ? m[1] : null
    },
  },
  {
    match: /water.*resist|ip\s*rating|ipx|splash|dust.*proof/i, label: 'IP Rating',
    extract: ev => { const m = ev.match(/ip[x]?\s*\d+[a-z]?/i); return m ? m[0].replace(/\s+/g, '').toUpperCase() : null },
  },
  {
    match: /driver|speaker.*config|transducer/i, label: 'Driver',
    extract: ev => {
      const m = ev.match(/(\d+mm[^,\.;\n]{0,20})/i); if (m) return m[1].trim()
      for (const kw of ['Planar', 'BA driver', 'Balanced Armature', 'Dual', 'Triple', 'Single 12mm', 'Single 10mm'])
        if (ev.toLowerCase().includes(kw.toLowerCase())) return kw
      return null
    },
  },
  {
    match: /sound.*sig|tuning|sound.*profile|audio.*character/i, label: 'Sound',
    extract: ev => {
      for (const kw of ['V-shaped', 'V-shape', 'Warm, bassy', 'Balanced, clear', 'Balanced', 'Bright', 'Bass-heavy', 'Neutral', 'Musical', 'Analytical', 'Warm', 'Clear'])
        if (ev.toLowerCase().includes(kw.toLowerCase())) return kw
      return null
    },
  },
  {
    match: /personal.*sound|adaptive.*eq|audiodo|dirac|auto.*eq/i, label: 'Personal Sound',
    extract: ev => {
      if (/no\b|none|not present|doesn't|does not/i.test(ev)) return 'No'
      const m = ev.match(/Yes\s*\(([^)]+)\)/i); if (m) return `Yes (${m[1]})`
      if (/yes|supported|available|audiodo|dirac/i.test(ev)) return 'Yes'
      return null
    },
  },
]

const SPEC_ORDER = ['ANC', 'Battery', 'Codec', 'Bluetooth', 'IP Rating', 'Driver', 'Sound', 'Personal Sound']

function extractSpecs(cs: Record<string, { score: number; evidence?: string }>): SpecRow[] {
  const rows: SpecRow[] = []; const seen = new Set<string>()
  for (const [criterion, data] of Object.entries(cs)) {
    if (!data.evidence || data.evidence === 'no direct data found') continue
    for (const def of SPEC_DEFS) {
      if (!def.match.test(criterion) || seen.has(def.label)) continue
      const val = def.extract(data.evidence)
      if (val) { rows.push({ label: def.label, value: val }); seen.add(def.label) }
      break
    }
  }
  rows.sort((a, b) => (SPEC_ORDER.indexOf(a.label) === -1 ? 99 : SPEC_ORDER.indexOf(a.label)) - (SPEC_ORDER.indexOf(b.label) === -1 ? 99 : SPEC_ORDER.indexOf(b.label)))
  return rows
}

// ─── Spec comparison ───────────────────────────────────────────────────────────

function compareSpecValues(label: string, a: string, b: string): 'a' | 'b' | 'equal' {
  if (a === b) return 'equal'
  const na = parseFloat(a.replace(/[^\d.]/g, '')); const nb = parseFloat(b.replace(/[^\d.]/g, ''))
  if (!isNaN(na) && !isNaN(nb) && na !== nb) return na > nb ? 'a' : 'b'
  if (label === 'Codec') {
    const R: Record<string, number> = { 'LDAC': 6, 'aptX Adaptive': 5, 'aptX Lossless': 5, 'aptX HD': 4, 'aptX': 3, 'LC3plus': 4, 'LC3': 3, 'AAC': 2, 'SBC': 1 }
    const ra = R[a] ?? 0; const rb = R[b] ?? 0
    if (ra !== rb) return ra > rb ? 'a' : 'b'
  }
  if (label === 'IP Rating') {
    const parse = (s: string) => parseInt(s.replace(/[^0-9]/g, '').slice(-2) || '0')
    const ia = parse(a); const ib = parse(b)
    if (ia !== ib) return ia > ib ? 'a' : 'b'
  }
  return 'equal'
}

// Compute winner for every spec across products
function computeSpecWinners(products: CompareProduct[], allSpecs: SpecRow[][]): Map<string, string | null> {
  const m = new Map<string, string | null>()
  const labels = new Set(allSpecs.flat().map(s => s.label))
  for (const label of labels) {
    const vals = products.map((p, i) => ({ name: p.name, val: allSpecs[i]?.find(s => s.label === label)?.value ?? null }))
    const present = vals.filter(v => v.val !== null) as Array<{ name: string; val: string }>
    if (present.length < 2) { m.set(label, null); continue }
    if (products.length === 2) {
      const res = compareSpecValues(label, present[0].val, present[1].val)
      m.set(label, res === 'a' ? present[0].name : res === 'b' ? present[1].name : null)
    } else {
      m.set(label, null)
    }
  }
  return m
}

// Compute winner for each criterion score
function computeCriteriaWinners(products: CompareProduct[]): Map<string, string | null> {
  const m = new Map<string, string | null>()
  const labels = new Set(products.flatMap(p => Object.keys(p.criteriaScores)))
  for (const label of labels) {
    const scores = products.map(p => ({ name: p.name, score: p.criteriaScores[label]?.score ?? -1 }))
    const sorted = [...scores].sort((a, b) => b.score - a.score)
    if (sorted[0].score === sorted[1].score) m.set(label, null)
    else m.set(label, sorted[0].score > 0 ? sorted[0].name : null)
  }
  return m
}

// ─── Who wins what ─────────────────────────────────────────────────────────────

interface WinRow { winner: string; scenario: string }

const CRITERION_SCENARIOS: Record<string, string> = {
  'ANC': 'you need the best noise cancellation',
  'Battery': 'you need the longest battery life',
  'Codec': 'you use Hi-Res audio streaming (LDAC / aptX)',
  'Sound Quality': 'you prioritize pure audio fidelity',
  'Audio Quality': 'you prioritize pure audio fidelity',
  'Comfort': 'wearing comfort is your top priority',
  'Microphone': 'you take calls or record voice frequently',
  'App': 'you want a companion app with EQ and controls',
  'Build Quality': 'durability and premium build matter',
  'Value': 'you want the best price-to-performance ratio',
  'Connectivity': 'you need rock-solid Bluetooth reliability',
  'Water Resistance': 'you use headphones while working out or in rain',
  'Bass': 'you want deep, punchy bass',
  'Soundstage': 'you want a wide, immersive soundstage',
  'Call Quality': 'call clarity matters more than music',
}

function generateWhoWinsRows(products: CompareProduct[], criteriaWinners: Map<string, string | null>): WinRow[] {
  if (products.length !== 2) return []
  const rows: WinRow[] = []
  const used = new Set<string>()

  // Criterion-based rows (gap >= 2)
  const [a, b] = products
  const allCriteria = [...new Set([...Object.keys(a.criteriaScores), ...Object.keys(b.criteriaScores)])]
  for (const crit of allCriteria) {
    if (rows.length >= 5) break
    const sa = a.criteriaScores[crit]?.score ?? 0
    const sb = b.criteriaScores[crit]?.score ?? 0
    if (Math.abs(sa - sb) < 2) continue
    const winner = criteriaWinners.get(crit)
    if (!winner) continue
    const scenario = CRITERION_SCENARIOS[crit] ?? `you care about ${crit.toLowerCase()}`
    if (!used.has(scenario)) { rows.push({ winner, scenario }); used.add(scenario) }
  }

  // Price
  if (a.price > 0 && b.price > 0) {
    const diff = Math.abs(a.price - b.price)
    if (diff > a.price * 0.04) {
      const cheaper = a.price < b.price ? a.name : b.name
      const sym = a.currency
      rows.push({ winner: cheaper, scenario: `you want to save ${sym}${diff.toLocaleString()} upfront` })
    }
  }

  // Reddit volume
  const mca = a.mentionCount ?? 0; const mcb = b.mentionCount ?? 0
  if (Math.abs(mca - mcb) >= 10) {
    const more = mca > mcb ? a.name : b.name
    rows.push({ winner: more, scenario: 'you trust heavily community-tested products' })
  }

  return rows.slice(0, 6)
}

// ─── Honest verdict ────────────────────────────────────────────────────────────

interface VerdictSection { heading: string; body: string }

function generateVerdict(products: CompareProduct[]): VerdictSection[] {
  if (products.length !== 2) return []
  const [a, b] = products
  const sections: VerdictSection[] = []

  const diff = Math.abs(a.score - b.score)
  const winner = a.score > b.score ? a : b
  const loser = a.score > b.score ? b : a

  if (diff >= 3) {
    sections.push({
      heading: `On paper — ${winner.name} wins.`,
      body: `${winner.name} scores ${winner.score}% vs ${loser.name}'s ${loser.score}% — a ${diff.toFixed(0)} point gap. ${winner.fitReason.slice(0, 220)}${winner.fitReason.length > 220 ? '…' : ''}`,
    })
  } else if (diff >= 1) {
    sections.push({
      heading: `On paper — ${winner.name} edges ahead.`,
      body: `A narrow ${diff.toFixed(0)}-point margin (${a.name}: ${a.score}%, ${b.name}: ${b.score}%). Both are strong options — the right choice depends on which specs matter to you personally.`,
    })
  } else {
    sections.push({
      heading: 'On paper — it\'s a dead heat.',
      body: `Both score identically at ${a.score}%. The decision comes down to specs, price, and your specific use case rather than any overall ranking.`,
    })
  }

  // Reddit sentiment
  const posA = a.positiveMentions ?? 0; const negA = a.negativeMentions ?? 0
  const posB = b.positiveMentions ?? 0; const negB = b.negativeMentions ?? 0
  const tA = posA + negA; const tB = posB + negB
  if (tA > 0 && tB > 0) {
    const pA = Math.round(posA / tA * 100); const pB = Math.round(posB / tB * 100)
    const rWinner = pA > pB ? a : pB > pA ? b : null
    const mcA = a.mentionCount ?? 0; const mcB = b.mentionCount ?? 0
    if (rWinner) {
      const rLoser = rWinner === a ? b : a
      const pctW = rWinner === a ? pA : pB; const pctL = rWinner === a ? pB : pA
      const mcW = rWinner === a ? mcA : mcB; const mcL = rWinner === a ? mcB : mcA
      const longerNote = Math.abs(mcW - mcL) > 15
        ? ` Keep in mind ${mcW > mcL ? rWinner.name : rLoser.name} has ${Math.abs(mcW - mcL)} more Reddit mentions, so sample sizes differ.`
        : ''
      sections.push({
        heading: `Reddit leans ${rWinner.name}`,
        body: `${rWinner.name} has ${pctW}% positive sentiment from ${mcW} mentions vs ${rLoser.name}'s ${pctL}% from ${mcL} mentions.${longerNote}`,
      })
    } else {
      sections.push({
        heading: 'Reddit is evenly split',
        body: `Both products have near-identical community sentiment (${a.name}: ${pA}% positive, ${b.name}: ${pB}% positive). Reddit data doesn't tip the scales either way.`,
      })
    }
  }

  // Price
  if (a.price > 0 && b.price > 0 && a.price !== b.price) {
    const cheaper = a.price < b.price ? a : b
    const pricier = cheaper === a ? b : a
    const gap = Math.abs(a.price - b.price)
    const pct = Math.round(gap / Math.min(a.price, b.price) * 100)
    sections.push({
      heading: `Price — ${cheaper.name} is cheaper`,
      body: `${cheaper.name} costs ${cheaper.currency}${cheaper.price.toLocaleString()} vs ${pricier.currency}${pricier.price.toLocaleString()} — ${cheaper.currency}${gap.toLocaleString()} less (${pct}% cheaper). The premium for ${pricier.name} is justified if its stronger criteria align with your priorities.`,
    })
  }

  // Bottom line
  const loserHighlights = loser.fitReason ? loser.fitReason.toLowerCase().slice(0, 80) : 'it offers specific advantages'
  sections.push({
    heading: 'The bottom line',
    body: `${winner.name} is the stronger all-around option. ${loser.name} is worth it if ${loserHighlights}${loserHighlights.endsWith('.') ? '' : '.'}`,
  })

  return sections
}

// ─── Loading / error states ────────────────────────────────────────────────────

function LoadingView() {
  return (
    <div className="min-h-screen flex flex-col bg-[#08080A]">
      <AnimatedBackground /><Header />
      <main className="flex-1 relative z-10 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="relative">
            <div className="w-12 h-12 rounded-full border-2 border-violet-500/30" />
            <div className="absolute inset-0 w-12 h-12 rounded-full border-2 border-violet-500 border-t-transparent animate-spin" />
          </div>
          <p className="text-sm text-[#71717A]">Loading comparison…</p>
        </div>
      </main>
      <Footer />
    </div>
  )
}

function ErrorView({ msg, isNoSelection, router }: { msg: string; isNoSelection: boolean; router: ReturnType<typeof useRouter> }) {
  return (
    <div className="min-h-screen flex flex-col bg-[#08080A]">
      <AnimatedBackground /><Header />
      <main className="flex-1 relative z-10 flex items-center justify-center px-4">
        <motion.div initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }} className="w-full max-w-md">
          <div className="rounded-2xl bg-white/[0.02] border border-white/[0.08] p-10 text-center shadow-[0_24px_64px_rgba(0,0,0,0.4)]">
            <div className="mx-auto mb-6 w-16 h-16 rounded-2xl bg-violet-500/10 border border-violet-500/20 flex items-center justify-center">
              <GitCompare className="w-7 h-7 text-violet-400" />
            </div>
            <h2 className="text-xl font-semibold text-[#FAFAFA] mb-3">{isNoSelection ? 'No products selected' : 'Comparison unavailable'}</h2>
            <p className="text-sm text-[#71717A] leading-relaxed mb-2">{isNoSelection ? 'You need to select at least 2 products from a results page before comparing.' : msg}</p>
            {isNoSelection && (
              <div className="mt-5 mb-7 p-4 rounded-xl bg-white/[0.03] border border-white/[0.06] text-left">
                <p className="text-xs text-[#52525B] uppercase tracking-widest mb-3 font-medium">How to compare</p>
                <div className="space-y-2.5">
                  {[
                    { n: '1', text: 'Run a search and open the results page' },
                    { n: '2', text: 'Tick the checkbox on 2 or more product cards' },
                    { n: '3', text: 'Click "Compare selected" to open this page' },
                  ].map(step => (
                    <div key={step.n} className="flex items-start gap-3">
                      <span className="w-5 h-5 rounded-full bg-violet-500/15 text-violet-400 text-xs font-bold flex items-center justify-center shrink-0 mt-0.5">{step.n}</span>
                      <p className="text-xs text-[#A1A1AA] leading-relaxed">{step.text}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div className={`flex gap-3 ${isNoSelection ? '' : 'mt-7'}`}>
              <Button variant="ghost" onClick={() => router.back()} className="flex-1 h-10 border border-white/[0.08] text-[#A1A1AA] hover:text-[#FAFAFA] hover:bg-white/[0.04]">
                <ArrowLeft className="w-4 h-4 mr-2" />Go back
              </Button>
              <Button onClick={() => router.push('/')} className="flex-1 h-10 bg-violet-600 hover:bg-violet-500 text-white shadow-lg shadow-violet-500/25">
                <Home className="w-4 h-4 mr-2" />New search
              </Button>
            </div>
            <button onClick={() => router.push('/history')} className="mt-4 flex items-center justify-center gap-1.5 w-full text-xs text-[#52525B] hover:text-[#A1A1AA] transition-colors">
              <BarChart3 className="w-3.5 h-3.5" />View past research sessions
            </button>
          </div>
        </motion.div>
      </main>
      <Footer />
    </div>
  )
}

// ─── Main page ─────────────────────────────────────────────────────────────────

function ComparePageContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const [products, setProducts] = useState<CompareProduct[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCriteria, setShowCriteria] = useState(false)

  const rawIds = searchParams.get('ids') ?? ''
  const searchId = searchParams.get('search') ?? ''
  const names = rawIds.split(',').map(decodeURIComponent).filter(Boolean)

  useEffect(() => {
    if (names.length < 2) { setError('Select at least 2 products to compare.'); setLoading(false); return }
    const storeState = useResultsStore.getState()
    if (storeState.products.length > 0 && storeState.rubric) {
      const matched = storeState.products.filter(p => names.includes(p.name))
      if (matched.length >= 2) {
        setProducts(matched.map(p => toCompareProduct(p, storeState.rubric!, storeState.weights)))
        setLoading(false); return
      }
    }
    if (!searchId) { setError('Could not load comparison data. Return to results and try again.'); setLoading(false); return }
    getSearchResult(searchId)
      .then(result => {
        if (!result.rubric || !result.scoredProducts?.length) { setError('No product data found.'); return }
        const weights = Object.fromEntries(result.rubric.weighted_criteria.map(c => [c.name, c.weight]))
        const filtered = result.scoredProducts.filter(p => names.includes(p.name))
        if (filtered.length < 2) { setError('Not enough matching products found.'); return }
        setProducts(filtered.map(p => toCompareProduct(p, result.rubric!, weights)))
      })
      .catch(e => setError(`Failed to load: ${e instanceof Error ? e.message : String(e)}`))
      .finally(() => setLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawIds, searchId])

  const allSpecs = useMemo(() => products.map(p => extractSpecs(p.criteriaScores)), [products])

  const specWinners = useMemo(() => {
    if (products.length < 2) return new Map<string, string | null>()
    return computeSpecWinners(products, allSpecs)
  }, [products, allSpecs])

  const criteriaWinners = useMemo(() => {
    if (products.length < 2) return new Map<string, string | null>()
    return computeCriteriaWinners(products)
  }, [products])

  const whoWins = useMemo(() => generateWhoWinsRows(products, criteriaWinners), [products, criteriaWinners])
  const verdict = useMemo(() => generateVerdict(products), [products])

  if (loading) return <LoadingView />
  if (error || products.length < 2) return <ErrorView msg={error ?? 'Not enough products.'} isNoSelection={names.length < 2} router={router} />

  const scoreWinner = products.reduce((a, b) => a.score >= b.score ? a : b)

  // Union of all spec labels
  const allSpecLabels = [...new Set(allSpecs.flat().map(s => s.label))]
    .sort((a, b) => (SPEC_ORDER.indexOf(a) === -1 ? 99 : SPEC_ORDER.indexOf(a)) - (SPEC_ORDER.indexOf(b) === -1 ? 99 : SPEC_ORDER.indexOf(b)))

  // Union of all criteria
  const allCriteria = [...new Set(products.flatMap(p => Object.keys(p.criteriaScores)))]

  // PRODUCT CARD colors (index-based for 3+ products)
  const CARD_ACCENTS = ['violet', 'sky', 'emerald', 'amber']
  function getCardAccent(idx: number, isWinner: boolean) {
    if (isWinner) return 'border-violet-500/40 bg-violet-500/[0.04]'
    return 'border-white/[0.08] bg-white/[0.02]'
  }

  return (
    <div className="min-h-screen flex flex-col bg-[#08080A]">
      <AnimatedBackground />
      <Header />
      <main className="flex-1 relative z-10">
        <div className="max-w-5xl mx-auto px-4 py-8">

          {/* Back */}
          <Button variant="ghost" onClick={() => router.back()} className="mb-6 text-[#A1A1AA] hover:text-[#FAFAFA] -ml-2">
            <ArrowLeft className="w-4 h-4 mr-2" />Back to results
          </Button>

          {/* Title */}
          <div className="mb-8">
            <h1 className="text-2xl font-bold text-[#FAFAFA]">Compare Products</h1>
            <p className="text-sm text-[#71717A] mt-1">{products.length} products · scored against the same criteria</p>
          </div>

          {/* ── SIDE-BY-SIDE SPEC CARDS ────────────────────────────── */}
          <div
            className="grid gap-4 mb-0"
            style={{ gridTemplateColumns: `repeat(${products.length}, minmax(0,1fr))` }}
          >
            {products.map((product, idx) => {
              const isWinner = product.name === scoreWinner.name
              const pos = product.positiveMentions ?? 0
              const neg = product.negativeMentions ?? 0
              const total = pos + neg
              const sentPct = total > 0 ? Math.round(pos / total * 100) : null
              const neutralCt = (product.mentionCount ?? 0) - pos - neg
              const sentimentColor = product.dominantSentiment === 'positive' ? 'text-emerald-400'
                : product.dominantSentiment === 'negative' ? 'text-rose-400'
                : 'text-amber-400'
              const mySpecs = allSpecs[idx] ?? []
              const quote = product.representativeQuote ?? product.praise?.[0] ?? null
              return (
                <motion.div
                  key={product.id}
                  initial={{ opacity: 0, y: 24 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.45, delay: idx * 0.08, ease: [0.16, 1, 0.3, 1] }}
                  className={cn('rounded-2xl border overflow-hidden', getCardAccent(idx, isWinner))}
                >
                  {/* Card header */}
                  <div className="px-5 pt-5 pb-4 border-b border-white/[0.06]">
                    <div className="flex items-start justify-between gap-2 mb-3">
                      <div className="flex-1 min-w-0">
                        <h3 className="text-base font-semibold text-[#FAFAFA] leading-snug">{product.name}</h3>
                        <p className="text-sm text-[#71717A] mt-0.5 flex items-center gap-1.5">
                          <span>{product.price > 0 ? `${product.currency}${product.price.toLocaleString()}` : '–'}</span>
                          {product.store && <span className="text-[#3F3F46]">· {product.store}</span>}
                        </p>
                      </div>
                      {isWinner && (
                        <Badge className="bg-amber-500/20 text-amber-300 border-amber-500/30 shrink-0 text-[10px]">
                          <Trophy className="w-2.5 h-2.5 mr-1" />Winner
                        </Badge>
                      )}
                    </div>

                    {/* Score bar */}
                    <div className="space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] text-[#52525B] uppercase tracking-widest font-semibold">Overall score</span>
                        <span className={cn('font-mono text-lg font-bold',
                          product.score >= 80 ? 'text-emerald-400' : product.score >= 50 ? 'text-amber-400' : 'text-rose-400'
                        )}>{product.score}%</span>
                      </div>
                      <div className="h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
                        <motion.div
                          className={cn('h-full rounded-full', product.score >= 80 ? 'bg-gradient-to-r from-emerald-500 to-teal-400' : product.score >= 50 ? 'bg-gradient-to-r from-amber-500 to-orange-400' : 'bg-gradient-to-r from-rose-500 to-red-400')}
                          initial={{ width: 0 }}
                          animate={{ width: `${product.score}%` }}
                          transition={{ duration: 0.8, delay: idx * 0.1, ease: 'easeOut' }}
                        />
                      </div>
                    </div>
                  </div>

                  {/* Spec table */}
                  {mySpecs.length > 0 && (
                    <div className="px-5 border-b border-white/[0.06]">
                      {mySpecs.map((spec, si) => {
                        const winner = specWinners.get(spec.label)
                        const isBetter = winner === product.name
                        const isWorse = winner !== null && winner !== product.name
                        return (
                          <div key={spec.label} className={cn('flex items-center justify-between py-[7px] text-sm', si < mySpecs.length - 1 && 'border-b border-white/[0.04]')}>
                            <span className="text-[#71717A]">{spec.label}</span>
                            <span className={cn('font-semibold', isBetter ? 'text-emerald-300' : isWorse ? 'text-[#71717A]' : 'text-[#FAFAFA]')}>
                              {spec.value}
                            </span>
                          </div>
                        )
                      })}
                    </div>
                  )}

                  {/* Sentiment */}
                  {sentPct !== null && (
                    <div className="px-5 py-3 border-b border-white/[0.06]">
                      <div className="flex items-center gap-3">
                        <span className={cn('text-3xl font-bold tabular-nums', sentimentColor)}>{sentPct}%</span>
                        <div>
                          <p className={cn('text-xs font-medium', sentimentColor)}>
                            {product.dominantSentiment === 'positive' ? 'Reddit positive' : product.dominantSentiment === 'negative' ? 'Reddit negative' : 'Reddit mixed'}
                          </p>
                          <div className="flex items-center gap-2 text-[11px] mt-0.5 flex-wrap">
                            {pos > 0 && <span className="text-emerald-300 font-medium">✅ {pos}</span>}
                            {neutralCt > 0 && <span className="text-[#A1A1AA] font-medium">😐 {neutralCt}</span>}
                            {neg > 0 && <span className="text-rose-300 font-medium">❌ {neg}</span>}
                            {(product.mentionCount ?? 0) > 0 && <span className="text-[#52525B]">· {product.mentionCount} mentions</span>}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Rating */}
                  {product.rating != null && product.rating > 0 && (
                    <div className="px-5 py-2.5 border-b border-white/[0.06] flex items-center gap-2">
                      <div className="flex items-center gap-0.5">
                        {[1,2,3,4,5].map(i => (
                          <Star key={i} className={cn('w-3 h-3', i <= Math.floor(product.rating!) ? 'text-amber-400 fill-amber-400' : i === Math.ceil(product.rating!) && product.rating! % 1 >= 0.5 ? 'text-amber-400 fill-amber-400/50' : 'text-white/10')} />
                        ))}
                      </div>
                      <span className="text-sm font-semibold text-amber-300">{product.rating.toFixed(1)}</span>
                      {product.reviewCount != null && <span className="text-xs text-[#52525B]">({product.reviewCount.toLocaleString()})</span>}
                    </div>
                  )}

                  {/* Quote box */}
                  {quote && (
                    <div className="px-5 py-3 border-b border-white/[0.06]">
                      <div className="rounded-xl bg-white/[0.03] border border-white/[0.05] px-3.5 py-2.5">
                        <p className="text-xs text-[#A1A1AA] leading-relaxed">
                          &ldquo;{quote.slice(0, 130)}{quote.length > 130 ? '…' : ''}&rdquo;
                          {' '}<span className="text-[#52525B]">— Reddit</span>
                        </p>
                      </div>
                    </div>
                  )}

                  {/* CTA */}
                  <div className="px-5 py-3.5">
                    <Button size="sm" className="w-full bg-violet-600 hover:bg-violet-500 text-xs" asChild>
                      <a href={product.storeUrl} target="_blank" rel="noopener noreferrer">
                        Open on {product.store}
                        <ExternalLink className="w-3.5 h-3.5 ml-1.5" />
                      </a>
                    </Button>
                  </div>
                </motion.div>
              )
            })}
          </div>

          {/* ── SPEC HEAD-TO-HEAD (shared aligned table) ────────────── */}
          {allSpecLabels.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.25 }}
              className="mt-6 rounded-2xl border border-white/[0.06] bg-white/[0.02] overflow-hidden"
            >
              {/* Header row */}
              <div className="grid border-b border-white/[0.08]" style={{ gridTemplateColumns: `160px repeat(${products.length}, 1fr)` }}>
                <div className="px-4 py-3 text-[10px] text-[#52525B] uppercase tracking-widest font-semibold">Spec</div>
                {products.map(p => (
                  <div key={p.id} className="px-4 py-3 text-xs font-semibold text-[#A1A1AA] border-l border-white/[0.06]">
                    {p.name}
                  </div>
                ))}
              </div>
              {allSpecLabels.map(label => (
                <div key={label} className="grid border-b border-white/[0.04] last:border-b-0" style={{ gridTemplateColumns: `160px repeat(${products.length}, 1fr)` }}>
                  <div className="px-4 py-2.5 text-sm text-[#71717A]">{label}</div>
                  {products.map((p, idx) => {
                    const val = allSpecs[idx]?.find(s => s.label === label)?.value
                    const winner = specWinners.get(label)
                    const isBetter = winner === p.name
                    const isWorse = winner !== null && winner !== p.name
                    return (
                      <div key={p.id} className="px-4 py-2.5 border-l border-white/[0.04]">
                        {val ? (
                          <span className={cn('text-sm font-semibold', isBetter ? 'text-emerald-300' : isWorse ? 'text-[#71717A]' : 'text-[#FAFAFA]')}>
                            {val}
                            {isBetter && <span className="ml-1.5 text-[9px] text-emerald-400/70">▲</span>}
                          </span>
                        ) : (
                          <span className="text-[#3F3F46] text-sm">—</span>
                        )}
                      </div>
                    )
                  })}
                </div>
              ))}
            </motion.div>
          )}

          {/* ── WHO WINS WHAT ──────────────────────────────────────── */}
          {whoWins.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.35 }}
              className="mt-8"
            >
              <div className="flex items-center gap-4 mb-5">
                <div className="flex-1 h-px bg-white/[0.06]" />
                <span className="text-sm text-[#52525B] font-medium">— who wins what —</span>
                <div className="flex-1 h-px bg-white/[0.06]" />
              </div>

              <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] overflow-hidden">
                <div className="px-5 py-3.5 border-b border-white/[0.06]">
                  <p className="text-sm font-semibold text-[#FAFAFA]">Pick by what matters to you</p>
                </div>
                <div className="divide-y divide-white/[0.04]">
                  {whoWins.map((row, i) => (
                    <motion.div
                      key={i}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.3, delay: 0.4 + i * 0.05 }}
                      className="flex items-center gap-4 px-5 py-3"
                    >
                      <span className="shrink-0 text-xs font-semibold px-2.5 py-1 rounded-full bg-violet-500/15 text-violet-300 border border-violet-500/25 whitespace-nowrap">
                        {row.winner.split(' ').slice(0, 3).join(' ')}
                      </span>
                      <span className="text-sm text-[#A1A1AA]">
                        You {row.scenario.startsWith('you') ? row.scenario.slice(3) : row.scenario}
                      </span>
                    </motion.div>
                  ))}
                </div>
              </div>
            </motion.div>
          )}

          {/* ── HONEST VERDICT ─────────────────────────────────────── */}
          {verdict.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.45 }}
              className="mt-8"
            >
              <h2 className="text-base font-semibold text-[#FAFAFA] mb-4">The honest verdict in plain words</h2>
              <div className="space-y-4">
                {verdict.map((section, i) => (
                  <p key={i} className="text-sm text-[#A1A1AA] leading-relaxed">
                    <span className="font-semibold text-[#FAFAFA]">{section.heading}</span>{' '}
                    {section.body}
                  </p>
                ))}
              </div>
            </motion.div>
          )}

          {/* ── CRITERIA SCORES (collapsible) ──────────────────────── */}
          {allCriteria.length > 0 && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.4, delay: 0.5 }}
              className="mt-8"
            >
              <button
                onClick={() => setShowCriteria(!showCriteria)}
                className="flex items-center gap-2 text-sm text-[#71717A] hover:text-[#A1A1AA] transition-colors mb-3"
              >
                {showCriteria ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                Full criteria breakdown ({allCriteria.length} criteria)
              </button>
              <AnimatePresence>
                {showCriteria && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    className="overflow-hidden"
                  >
                    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] overflow-hidden">
                      {/* Header */}
                      <div className="grid border-b border-white/[0.08]" style={{ gridTemplateColumns: `minmax(120px,200px) repeat(${products.length}, 1fr)` }}>
                        <div className="px-4 py-3 text-[10px] text-[#52525B] uppercase tracking-widest font-semibold">Criterion</div>
                        {products.map(p => (
                          <div key={p.id} className="px-4 py-3 text-xs font-semibold text-[#A1A1AA] border-l border-white/[0.06] truncate">{p.name}</div>
                        ))}
                      </div>
                      {allCriteria.map(criterion => (
                        <div key={criterion} className="grid border-b border-white/[0.04] last:border-b-0" style={{ gridTemplateColumns: `minmax(120px,200px) repeat(${products.length}, 1fr)` }}>
                          <div className="px-4 py-3 text-xs text-[#71717A] leading-snug">{criterion}</div>
                          {products.map(p => {
                            const data = p.criteriaScores[criterion]
                            const winner = criteriaWinners.get(criterion)
                            const isBetter = winner === p.name
                            const isWorse = winner !== null && winner !== p.name
                            return (
                              <div key={p.id} className="px-4 py-3 border-l border-white/[0.04]">
                                {data ? (
                                  <>
                                    <div className="flex items-center gap-1.5 mb-1">
                                      <span className={cn('font-mono text-sm font-bold', isBetter ? 'text-emerald-400' : isWorse ? 'text-rose-400' : 'text-[#A1A1AA]')}>{data.score}/10</span>
                                      {isBetter && <span className="text-[9px] text-emerald-400/60 font-medium">BEST</span>}
                                    </div>
                                    {data.evidence && data.evidence !== 'no direct data found' && (
                                      <p className="text-[11px] text-[#52525B] leading-relaxed line-clamp-2">{data.evidence}</p>
                                    )}
                                  </>
                                ) : (
                                  <span className="text-[#3F3F46] text-sm">—</span>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          )}

          {/* ── BOTTOM CTA ROW ──────────────────────────────────────── */}
          <div className="mt-8 pt-6 border-t border-white/[0.06]">
            <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${products.length}, 1fr)` }}>
              {products.map(p => (
                <Button key={p.id} className="bg-violet-600 hover:bg-violet-500" asChild>
                  <a href={p.storeUrl} target="_blank" rel="noopener noreferrer">
                    Open {p.name.split(' ').slice(0, 3).join(' ')}
                    <ExternalLink className="w-4 h-4 ml-1.5" />
                  </a>
                </Button>
              ))}
            </div>
          </div>

        </div>
      </main>
      <Footer />
    </div>
  )
}

export default function ComparePage() {
  return (
    <Suspense fallback={<LoadingView />}>
      <ComparePageContent />
    </Suspense>
  )
}
