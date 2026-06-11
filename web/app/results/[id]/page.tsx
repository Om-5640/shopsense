'use client'

import { useState, useCallback, useMemo, useEffect, useRef, useTransition } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { Clock, MapPin, ArrowUpDown, Menu, RefreshCw, Activity, Download, FileText, FileSpreadsheet, Link, Check, Hash, MessageSquare, Globe } from 'lucide-react'
import { AnimatedBackground } from '@/components/layout/animated-background'
import { Header } from '@/components/layout/header'
import { CommandPalette } from '@/components/layout/command-palette'
import { RubricSidebar } from '@/components/results/rubric-sidebar'
import { ProductCard } from '@/components/results/product-card'
import { InsightsPanel } from '@/components/results/insights-panel'
import { DiagnosticsPanel } from '@/components/results/diagnostics-panel'
import { ProductSpotlight } from '@/components/results/product-spotlight'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { toast } from 'sonner'
import { deleteProductMemory, getSearchResult, fetchPrices, recordPurchase, downloadCSV, downloadPDF, createShareLink } from '@/lib/api'
import { useResultsStore, useAppStore, deriveSidebarCriteria } from '@/lib/store'
import type { ScoredProduct, RetailerPrice, AnalysisProduct, SentimentRecord, ProductPrice, ReviewIntelligence } from '@/lib/types'
import { fmtRelative } from '@/lib/utils'

// ─── Adapters ─────────────────────────────────────────────────────────────────

function toCurrencySymbol(currency: string) {
  if (currency === 'INR') return '₹'
  if (currency === 'USD') return '$'
  if (currency === 'GBP') return '£'
  if (currency === 'EUR') return '€'
  return currency
}

function bestRetailer(p: ScoredProduct): RetailerPrice | undefined {
  return p.price?.retailers?.find((r) => !r.is_search) ?? p.price?.retailers?.[0]
}

function productClientKey(p: ScoredProduct, index: number) {
  return p.clientKey ?? `${p.name}::${index}`
}

function toProductCardProps(p: ScoredProduct, rank: number, rubricCriteria: { id: string; label: string }[], analysisMap: Record<string, AnalysisProduct> = {}) {
  const currency = p.price?.currency ?? 'INR'
  const sym = toCurrencySymbol(currency)
  const intelConf = p.price?.intelligence?.status === 'confident'
  // When intelligence is confident, use the matched retailer so price and link stay in sync
  const retailer = intelConf
    ? (p.price?.retailers?.find((r) => r.url === p.price?.intelligence?.best_url) ?? bestRetailer(p))
    : bestRetailer(p)
  const bestPrice = p.price?.best_price
  // Price: use retailer price directly when intelligence is confident (avoids showing
  // a cheaper wrong-variant price alongside the correct-variant link)
  const rawPrice = intelConf
    ? (retailer?.price_inr ?? retailer?.price_usd ?? bestPrice?.price_inr ?? bestPrice?.price_usd ?? 0)
    : (bestPrice?.price_inr ?? bestPrice?.price_usd ?? retailer?.price_inr ?? retailer?.price_usd ?? 0)
  const priceNum = rawPrice

  const criteriaScores: Record<string, { score: number; evidence?: string; relative_rank?: string }> = {}
  const labelMap = Object.fromEntries(rubricCriteria.map((c) => [c.id, c.label]))
  p.scores.forEach((s) => {
    const label = labelMap[s.criterion] ?? s.label ?? s.criterion
    criteriaScores[label] = { score: s.score, evidence: s.evidence || undefined, relative_rank: s.relative_rank }
  })

  // Include image from best retailer (populated by price fetch)
  const imageUrl = retailer?.image_url ?? p.price?.retailers?.find((r) => r.image_url)?.image_url

  // Merge community data from analysis (matched by name, case-insensitive)
  const ap = analysisMap[p.name.toLowerCase()] ?? analysisMap[p.name] ?? {}

  return {
    id: p.name,
    rank,
    name: p.name,
    score: p.percentage,
    price: priceNum,
    currency: sym,
    store: retailer?.name ?? 'Search',
    storeUrl: retailer?.url ?? (() => {
      // Only generate a Google fallback URL when the product name looks like a real product.
      // LLM-hallucinated names with special chars get no fallback so users aren't sent on
      // a confusing search. encodeURIComponent prevents URL injection in all cases.
      const words = p.name.trim().split(/\s+/)
      const nameOk = words.length >= 2 && !/[<>{}|\\^`]/.test(p.name)
      return nameOk ? `https://www.google.com/search?q=buy+${encodeURIComponent(p.name)}` : undefined
    })(),
    originalPrice: retailer?.mrp_inr ?? undefined,
    rating: retailer?.rating ?? undefined,
    reviewCount: retailer?.review_count ?? undefined,
    imageUrl: imageUrl ?? undefined,
    highSignal: p.signal_strength === 'high' || p.cross_subreddit_signal?.signal === 'consistent',
    purchased: p.memory?.status === 'purchased',
    criteriaScores,
    fitReason: p.explanation,
    alternativePrices: p.price?.retailers
      ?.filter((r) => r !== retailer && !r.is_search)
      ?.slice(0, 3)
      ?.map((r) => ({ store: r.name, price: r.price_inr ?? r.price_usd ?? 0, url: r.url })),
    // Community signal data
    mentionCount: ap.mention_count ?? p.mention_count,
    positiveMentions: ap.positive_mentions ?? p.positive_mentions,
    negativeMentions: ap.negative_mentions ?? p.negative_mentions,
    distinctRecommenders: ap.distinct_recommenders ?? p.distinct_recommenders,
    praise: ap.praise ?? p.praise ?? [],
    complaints: ap.complaints ?? p.complaints ?? [],
    representativeQuote: ap.representative_quote ?? p.representative_quote,
    sources: ap.sources ?? p.sources ?? [],
    crossSubredditSignal: p.cross_subreddit_signal ?? null,
    // v9: precise sentiment pipeline
    sentimentScore: ap.sentiment_score ?? p.sentiment_score ?? null,
    dominantSentiment: ap.dominant_sentiment ?? p.dominant_sentiment ?? null,
    sentimentRecords: (ap.sentiment_records ?? p.sentiment_records ?? []) as SentimentRecord[],
    // Fix 7: recency-weighted mentions
    recencyWeightedMentions: p.recency_weighted_mentions ?? null,
    // Fix 12: source passages for data lineage
    sourcePassages: p.source_passages ?? [],
    // Link Intelligence match score (from best retailer)
    matchScore: p.price?.intelligence?.match_score ?? null,
    // Evidence reliability (scorer fairness pass + targeted enrichment)
    dataCoverage: p.data_coverage ?? null,
    confidence: p.confidence ?? null,
    // Fix 13: inter-product relative ranking
    overallRank: p.overall_rank ?? undefined,
    gapToLeader: p.gap_to_leader ?? undefined,
    // Fix 17: source coverage count
    sourceCoverage: p.source_coverage ?? null,
  }
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const _PRICES_IDX_KEY = 'shopsense_prices_idx'

/** Cache prices in sessionStorage with LRU eviction when quota is exceeded (Bug 4). */
function _cachePricesSession(key: string, prices: ProductPrice[]): void {
  const value = JSON.stringify(prices)
  const _updateIdx = (k: string) => {
    try {
      const idx: string[] = JSON.parse(sessionStorage.getItem(_PRICES_IDX_KEY) ?? '[]')
      sessionStorage.setItem(_PRICES_IDX_KEY, JSON.stringify([k, ...idx.filter(x => x !== k)].slice(0, 20)))
    } catch { /* ignore */ }
  }
  try {
    sessionStorage.setItem(key, value)
    _updateIdx(key)
  } catch {
    // QuotaExceededError — evict oldest entry and retry once
    try {
      const idx: string[] = JSON.parse(sessionStorage.getItem(_PRICES_IDX_KEY) ?? '[]')
      if (idx.length > 0) {
        sessionStorage.removeItem(idx[idx.length - 1])
        sessionStorage.setItem(_PRICES_IDX_KEY, JSON.stringify(idx.slice(0, -1)))
      }
      sessionStorage.setItem(key, value)
      _updateIdx(key)
    } catch { /* give up silently */ }
  }
}

/** Copy text to clipboard with execCommand fallback for HTTP / older browsers (Bug 3). */
async function _copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(text); return } catch { /* fall through */ }
  }
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.cssText = 'position:fixed;opacity:0;pointer-events:none;'
  document.body.appendChild(ta)
  ta.focus()
  ta.select()
  try { document.execCommand('copy') } finally { document.body.removeChild(ta) }
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ResultsPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const [commandOpen, setCommandOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [searchMeta, setSearchMeta] = useState<{ query: string; category: string; region: string; createdAt: string } | null>(null)
  const [reviewIntelligence, setReviewIntelligence] = useState<ReviewIntelligence | null>(null)
  const [activeCriterionId, setActiveCriterionId] = useState<string | null>(null)
  const [sortBy, setSortBy] = useState<'score' | 'price' | 'rating'>('score')
  const [leftSidebarOpen, setLeftSidebarOpen] = useState(false)
  const [rightSidebarOpen, setRightSidebarOpen] = useState(false)
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false)
  const [copyLinkDone, setCopyLinkDone] = useState(false)
  const [qualityDegraded, setQualityDegraded] = useState(false)  // Fix 8

  const { rubric, weights, products, compareSet, initResults, setWeight, resetWeights, toggleCompare } =
    useResultsStore()
  const { addSearchHistory } = useAppStore()
  const hasLoadedRef = useRef<string | null>(null)
  const mountedRef = useRef(true)                                               // Bug 2: stale price-fetch guard
  const activeCriterionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)  // Bug 1: leak-free timeout
  const [isReweighting, startReweightTransition] = useTransition()

  // Cleanup: mark unmounted + clear pending timers (Bug 1 + Bug 2)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (activeCriterionTimerRef.current) clearTimeout(activeCriterionTimerRef.current)
    }
  }, [])

  // Load result on mount
  useEffect(() => {
    if (!id) return
    // Guard: skip if already loaded this specific search (handles StrictMode double-invoke
    // and navigation back without re-fetching when store already has this search)
    const current = useResultsStore.getState()
    if (hasLoadedRef.current === id) return
    if (current.searchId === id && current.products.length > 0) {
      // Store already has this search's data — use the stored createdAt, not the current time
      setSearchMeta({
        query: current.query,
        category: current.category,
        region: current.region,
        createdAt: current.createdAt ?? new Date().toISOString(),
      })
      setLoading(false)
      hasLoadedRef.current = id
      return
    }
    hasLoadedRef.current = id
    // Only reset store when switching to a different search to avoid stale rubric flash
    if (current.searchId !== id) {
      useResultsStore.setState({ rubric: null, products: [], weights: {}, compareSet: new Set() })
    }
    ;(async () => {
      try {
        const result = await getSearchResult(id)
        if (result.rubric && result.scoredProducts?.length) {
          // Build name → analysis product lookup for community data merge
          const analysisMap: Record<string, AnalysisProduct> = {}
          for (const ap of result.analysis?.products ?? []) {
            analysisMap[ap.name.toLowerCase()] = ap
          }
          // Merge community fields into scored products
          const mergedProducts = result.scoredProducts.map((sp, index) => {
            const ap = analysisMap[sp.name.toLowerCase()] ?? {}
            return {
              ...sp,
              clientKey: productClientKey(sp, index),
              mention_count: ap.mention_count ?? sp.mention_count,
              distinct_recommenders: ap.distinct_recommenders ?? sp.distinct_recommenders,
              positive_mentions: ap.positive_mentions ?? sp.positive_mentions,
              negative_mentions: ap.negative_mentions ?? sp.negative_mentions,
              praise: ap.praise ?? sp.praise,
              complaints: ap.complaints ?? sp.complaints,
              representative_quote: ap.representative_quote ?? sp.representative_quote,
              sources: ap.sources ?? sp.sources,
              // v9: precise sentiment pipeline fields
              sentiment_score: ap.sentiment_score ?? sp.sentiment_score ?? null,
              dominant_sentiment: ap.dominant_sentiment ?? sp.dominant_sentiment ?? null,
              sentiment_records: (ap.sentiment_records ?? sp.sentiment_records ?? []) as SentimentRecord[],
            }
          })
          initResults({
            searchId: id,
            query: result.query,
            category: result.category,
            region: result.region,
            createdAt: result.createdAt,
            rubric: result.rubric,
            products: mergedProducts,
          })
          setSearchMeta({
            query: result.query,
            category: result.category,
            region: result.region,
            createdAt: result.createdAt,
          })
          // Fix 8: surface quality degradation warning if fallback providers were used
          if ((result as any).qualityMetadata?.degraded) {
            setQualityDegraded(true)
          }
          // Review intelligence — embedded in analysis by the pipeline
          if (result.analysis?.review_intelligence) {
            setReviewIntelligence(result.analysis.review_intelligence)
          }
          // Save to home-page history
          const top = result.scoredProducts[0]
          addSearchHistory({
            id,
            query: result.query,
            category: result.category,
            region: result.region,
            timestamp: new Date(result.createdAt).getTime(),
            topProduct: top ? { name: top.name, score: top.percentage } : undefined,
          })
          // Best-effort price fetch — cached in sessionStorage for this search ID
          // so navigating back to this results page doesn't re-fire 8 Serper calls.
          const _priceKey = `shopsense_prices_${id}`
          const _cachedPrices = (() => {
            try {
              const raw = sessionStorage.getItem(_priceKey)
              if (raw) return JSON.parse(raw) as ProductPrice[]
            } catch { /* ignore */ }
            return null
          })()
          if (_cachedPrices) {
            // O2 fix: Map for O(1) lookup instead of O(n²) nested Array.find
            const priceMap = new Map(_cachedPrices.map((pr) => [pr.product_name.toLowerCase(), pr]))
            useResultsStore.setState((state) => ({
              products: state.products.map((p) => {
                const pd = priceMap.get(p.name.toLowerCase())
                return pd ? { ...p, price: pd } : p
              }),
            }))
          } else {
            fetchPrices(result.scoredProducts.slice(0, 15).map((p) => p.name), result.region)
              .then(({ prices }) => {
                if (!mountedRef.current) return  // Bug 2 fix: skip stale update after unmount
                _cachePricesSession(_priceKey, prices)   // Bug 4 fix: LRU eviction on quota error
                const priceMap = new Map(prices.map((pr) => [pr.product_name.toLowerCase(), pr]))
                useResultsStore.setState((state) => ({
                  products: state.products.map((p) => {
                    const pd = priceMap.get(p.name.toLowerCase())
                    return pd ? { ...p, price: pd } : p
                  }),
                }))
              })
              .catch(() => {/* best-effort */})
          }
        } else {
          setLoadError(
            result.status === 'running'
              ? 'Research still in progress — try refreshing in a moment.'
              : 'No products found for this search.',
          )
        }
      } catch (e) {
        setLoadError(`Failed to load results: ${e instanceof Error ? e.message : e}`)
      } finally {
        setLoading(false)
      }
    })()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  // Rubric sidebar criteria (derived from live weights)
  const sidebarCriteria = useMemo(
    () => (rubric ? deriveSidebarCriteria(rubric, weights) : []),
    [rubric, weights],
  )

  const handleWeightChange = useCallback(
    (criterionId: string, value: number) => {
      setActiveCriterionId(criterionId)
      startReweightTransition(() => {
        setWeight(criterionId, value)
      })
      // Bug 1 fix: clear previous timeout to avoid stacking; ref prevents leak on unmount
      if (activeCriterionTimerRef.current) clearTimeout(activeCriterionTimerRef.current)
      activeCriterionTimerRef.current = setTimeout(() => setActiveCriterionId(null), 500)
    },
    [setWeight, startReweightTransition],
  )

  const handleReset = useCallback(() => {
    resetWeights()
    toast.success('Weights reset to original values')
  }, [resetWeights])

  const handleSave = useCallback(() => {
    toast.success('Weights saved')
  }, [])

  const handleTogglePurchased = useCallback(
    async (productName: string, isPurchased: boolean, score: number) => {
      if (!searchMeta) return
      try {
        if (isPurchased) {
          await deleteProductMemory(productName)
        } else {
          await recordPurchase(productName, searchMeta.category, undefined, score)
        }
        toast.success(isPurchased ? 'Purchase mark removed' : 'Marked as purchased!')
        useResultsStore.setState((state) => ({
          products: state.products.map((p) =>
            p.name === productName
              ? {
                  ...p,
                  memory: isPurchased ? null : { ...(p.memory ?? {}), status: 'purchased', ourScore: score },
                }
              : p,
          ),
        }))
      } catch {
        toast.error(isPurchased ? 'Could not remove purchase mark' : 'Could not record purchase')
      }
    },
    [searchMeta],
  )

  const handleExport = useCallback(async (type: 'csv' | 'pdf' | 'share') => {
    if (!id) return
    if (type === 'csv') {
      downloadCSV(id)
      toast.success('CSV download started')
    } else if (type === 'pdf') {
      downloadPDF(id)
      toast.success('PDF download started')
    } else {
      try {
        const shareUrl = await createShareLink(id)
        await _copyToClipboard(shareUrl)   // Bug 3 fix: fallback for HTTP / older browsers
        setCopyLinkDone(true)
        toast.success('Share link copied to clipboard', {
          description: shareUrl,
          duration: 6000,
        })
        setTimeout(() => setCopyLinkDone(false), 3000)
      } catch {
        toast.error('Could not create share link')
      }
    }
  }, [id])

  const handleCompare = useCallback(() => {
    if (compareSet.size >= 2) {
      // O3 fix: encodeURIComponent encodes commas inside names as %2C, so the join
      // comma is unambiguous — no lossy stripping that could produce collisions.
      const names = [...compareSet]
        .map((n) => encodeURIComponent(n))
        .join(',')
      router.push(`/compare?ids=${names}&search=${id}`)
    }
  }, [compareSet, router, id])

  // Detect when user has modified weights from the original rubric values
  const hasCustomWeights = useMemo(() => {
    if (!rubric) return false
    return rubric.weighted_criteria.some(
      (c) => weights[c.name] !== undefined && weights[c.name] !== c.weight,
    )
  }, [rubric, weights])

  // Sorted product list (secondary sort: price or rating)
  // useTransition marks weight changes as non-urgent, so the UI stays responsive
  // during slider drags and the list re-sorts only after input settles.
  const displayProducts = useMemo(() => {
    if (sortBy === 'score') return products
    return [...products].sort((a, b) => {
      if (sortBy === 'price') {
        const ap = a.price?.best_price?.price_inr ?? a.price?.best_price?.price_usd ?? 0
        const bp = b.price?.best_price?.price_inr ?? b.price?.best_price?.price_usd ?? 0
        return ap - bp
      }
      const ar = bestRetailer(a)?.rating ?? 0
      const br = bestRetailer(b)?.rating ?? 0
      return br - ar
    })
  }, [products, sortBy])

  // ── Trust stats — aggregate research breadth from product data ───────────
  const trustStats = useMemo(() => {
    const redditSources = new Set<string>()
    const reviewSources = new Set<string>()
    let totalMentions = 0
    products.forEach((p) => {
      totalMentions += p.mention_count ?? 0
      ;(p.sources ?? []).forEach((s) => {
        if (s.startsWith('reddit:')) redditSources.add(s)
        else if (s.startsWith('review:')) reviewSources.add(s)
      })
    })
    return { communities: redditSources.size, mentions: totalMentions, reviewSources: reviewSources.size }
  }, [products])

  // ── Insights panel — derived from real backend data ──────────────────────
  // Must be here (before early returns) to satisfy Rules of Hooks
  const insightsProps = useMemo(() => {
    // Types: group products by the criterion each one scores highest on
    const criterionGroups: Record<string, string[]> = {}
    products.forEach((p) => {
      if (!p.scores.length) return
      const top = p.scores.reduce((a, b) => (a.score > b.score ? a : b))
      const label = sidebarCriteria.find((c) => c.id === top.criterion)?.label ?? top.label ?? top.criterion
      if (!criterionGroups[label]) criterionGroups[label] = []
      criterionGroups[label].push(p.name)
    })
    const categories = Object.entries(criterionGroups)
      .sort((a, b) => b[1].length - a[1].length)
      .slice(0, 4)
      .map(([name, prods]) => ({ name, products: prods }))

    // Signal: one entry per product, with richer data for the redesigned Signal tab
    const communitySignal = products.map((p, i) => {
      let sentiment: 'positive' | 'neutral' | 'negative' = 'neutral'
      if (p.signal_strength === 'high' || p.cross_subreddit_signal?.signal === 'consistent') {
        sentiment = 'positive'
      } else if (p.signal_strength === 'low') {
        sentiment = 'negative'
      }
      const pos = (p as { positive_mentions?: number }).positive_mentions ?? 0
      const neg = (p as { negative_mentions?: number }).negative_mentions ?? 0
      const total = pos + neg
      const recommendPct = total > 0 ? Math.round((pos / total) * 100) : null
      const sources = ((p as { sources?: string[] }).sources ?? [])
        .filter((s: string) => s.startsWith('reddit:'))
        .map((s: string) => s.slice(7))
      return {
        threadId: p.name,
        sentiment,
        productName: p.name,
        rank: i + 1,
        mentionCount: (p as { mention_count?: number }).mention_count ?? 0,
        recommendPct,
        subreddits: sources.slice(0, 3),
      }
    })

    // Avoid: low signal or very low score
    const toAvoid = products
      .filter((p) => p.signal_strength === 'low' || p.percentage < 40)
      .slice(0, 3)
      .map((p) => ({
        product: p.name,
        reason: p.percentage < 40
          ? `Low match score (${Math.round(p.percentage)}%)`
          : 'Weak community signal — limited reliable data',
      }))

    // Warnings: products with real (non-fallback) split community opinion
    const warnings = products
      .filter((p) => p.cross_subreddit_signal?.signal === 'split' && !p.cross_subreddit_signal?._is_fallback)
      .slice(0, 3)
      .map((p) => ({
        product: p.name,
        warning: p.cross_subreddit_signal?.explanation ?? 'Mixed opinions across communities',
      }))

    return { categories, communitySignal, toAvoid, warnings }
  }, [products, sidebarCriteria])

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#08080A]">
        <div className="w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (loadError) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#08080A]">
        <div className="text-center">
          <p className="text-rose-400 mb-4 text-sm">{loadError}</p>
          <Button variant="ghost" onClick={() => router.push('/')}>← Back to search</Button>
        </div>
      </div>
    )
  }

  if (!rubric || products.length === 0) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#08080A]">
        <div className="text-center">
          <p className="text-[#A1A1AA] mb-4 text-sm">No products found for this search.</p>
          <Button variant="ghost" onClick={() => router.push('/')}>← Back to search</Button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex flex-col bg-[#08080A]">
      <AnimatedBackground />
      <Header onOpenCommandPalette={() => setCommandOpen(true)} />
      <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} />

      <main className="flex-1 relative z-10">
        <div className="max-w-[1600px] mx-auto px-4 py-6">
          {/* Mobile sidebar toggles */}
          <div className="lg:hidden flex justify-between mb-4">
            <Sheet open={leftSidebarOpen} onOpenChange={setLeftSidebarOpen}>
              <SheetTrigger asChild>
                <Button variant="ghost" size="sm" className="text-[#A1A1AA]">
                  <Menu className="w-4 h-4 mr-2" />
                  Priorities
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-[300px] bg-[#0F0F12] border-white/[0.06]">
                <RubricSidebar
                  criteria={sidebarCriteria}
                  onWeightChange={handleWeightChange}
                  onReset={handleReset}
                  onSave={handleSave}
                  activeCriterionId={activeCriterionId}
                />
              </SheetContent>
            </Sheet>

            <Sheet open={rightSidebarOpen} onOpenChange={setRightSidebarOpen}>
              <SheetTrigger asChild>
                <Button variant="ghost" size="sm" className="text-[#A1A1AA]">
                  Insights
                  <Menu className="w-4 h-4 ml-2" />
                </Button>
              </SheetTrigger>
              <SheetContent side="right" className="w-[280px] bg-[#0F0F12] border-white/[0.06]">
                <InsightsPanel {...insightsProps} reviewIntelligence={reviewIntelligence} />
              </SheetContent>
            </Sheet>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-[300px_1fr_260px] gap-6">
            {/* Left — Rubric */}
            <div className="hidden lg:block lg:sticky lg:top-[76px] lg:h-[calc(100vh-108px)] overflow-y-auto pr-2">
              <RubricSidebar
                criteria={sidebarCriteria}
                onWeightChange={handleWeightChange}
                onReset={handleReset}
                onSave={handleSave}
                activeCriterionId={activeCriterionId}
              />
            </div>

            {/* Center — Products */}
            <div>
              {/* Metadata bar */}
              {searchMeta && (
                <div className="flex flex-wrap items-center justify-between gap-4 mb-6 pb-4 border-b border-white/[0.06]">
                  <div className="flex flex-wrap items-center gap-3 text-sm text-[#A1A1AA]">
                    <span className="font-medium text-[#FAFAFA] line-clamp-1 max-w-xs">{searchMeta.query}</span>
                    <Badge variant="outline" className="border-white/[0.1] text-[#71717A]">
                      {searchMeta.category.replace('/', ' › ')}
                    </Badge>
                    <span className="flex items-center gap-1 text-[#71717A]">
                      <MapPin className="w-3.5 h-3.5" />
                      {searchMeta.region}
                    </span>
                    <span className="flex items-center gap-1 text-[#71717A]">
                      <Clock className="w-3.5 h-3.5" />
                      {fmtRelative(searchMeta.createdAt)}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-[#A1A1AA] hover:text-[#FAFAFA]"
                      onClick={() => router.push(`/research?q=${encodeURIComponent(searchMeta.query)}`)}
                    >
                      <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
                      Refine search
                    </Button>

                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-[#A1A1AA] hover:text-violet-300 hover:bg-violet-500/10"
                      onClick={() => setDiagnosticsOpen(true)}
                    >
                      <Activity className="w-3.5 h-3.5 mr-1.5" />
                      Diagnostics
                    </Button>

                    {/* Export dropdown */}
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="sm" className="text-[#A1A1AA] hover:text-[#FAFAFA]">
                          <Download className="w-3.5 h-3.5 mr-1.5" />
                          Export
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="bg-[#0F0F12] border-white/[0.1] w-48">
                        <DropdownMenuItem
                          onClick={() => handleExport('pdf')}
                          className="text-[#FAFAFA] hover:bg-white/[0.06] cursor-pointer gap-2"
                        >
                          <FileText className="w-4 h-4 text-violet-400" />
                          Download PDF
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => handleExport('csv')}
                          className="text-[#FAFAFA] hover:bg-white/[0.06] cursor-pointer gap-2"
                        >
                          <FileSpreadsheet className="w-4 h-4 text-emerald-400" />
                          Download CSV
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => handleExport('share')}
                          className="text-[#FAFAFA] hover:bg-white/[0.06] cursor-pointer gap-2"
                        >
                          {copyLinkDone
                            ? <Check className="w-4 h-4 text-emerald-400" />
                            : <Link className="w-4 h-4 text-sky-400" />}
                          {copyLinkDone ? 'Copied!' : 'Copy share link'}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>

                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="sm" className="text-[#A1A1AA]">
                          <ArrowUpDown className="w-4 h-4 mr-2" />
                          Sort by {sortBy}
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="bg-[#0F0F12] border-white/[0.1]">
                        <DropdownMenuItem onClick={() => setSortBy('score')} className="text-[#FAFAFA]">Score</DropdownMenuItem>
                        <DropdownMenuItem onClick={() => setSortBy('price')} className="text-[#FAFAFA]">Price</DropdownMenuItem>
                        <DropdownMenuItem onClick={() => setSortBy('rating')} className="text-[#FAFAFA]">Rating</DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>
              )}

              {/* Trust Stats Bar — research breadth at a glance */}
              {trustStats.mentions > 0 && (
                <motion.div
                  initial={{ opacity: 0, y: -6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.35, ease: 'easeOut' }}
                  className="mb-5 px-5 py-3.5 rounded-xl border border-white/[0.07] bg-gradient-to-r from-violet-500/[0.04] via-white/[0.02] to-sky-500/[0.04]"
                >
                  <div className="flex items-center justify-center gap-6 flex-wrap">
                    {trustStats.communities > 0 && (
                      <>
                        <div className="flex items-center gap-2 text-sm">
                          <div className="w-6 h-6 rounded-lg bg-violet-500/15 flex items-center justify-center shrink-0">
                            <Hash className="w-3 h-3 text-violet-400" />
                          </div>
                          <span className="font-bold text-[#FAFAFA]">{trustStats.communities}</span>
                          <span className="text-[#71717A]">{trustStats.communities === 1 ? 'community' : 'communities'} analyzed</span>
                        </div>
                        <div className="w-px h-4 bg-white/[0.1] hidden sm:block" />
                      </>
                    )}
                    <div className="flex items-center gap-2 text-sm">
                      <div className="w-6 h-6 rounded-lg bg-indigo-500/15 flex items-center justify-center shrink-0">
                        <MessageSquare className="w-3 h-3 text-indigo-400" />
                      </div>
                      <span className="font-bold text-[#FAFAFA]">{trustStats.mentions.toLocaleString()}</span>
                      <span className="text-[#71717A]">community mentions</span>
                    </div>
                    {trustStats.reviewSources > 0 && (
                      <>
                        <div className="w-px h-4 bg-white/[0.1] hidden sm:block" />
                        <div className="flex items-center gap-2 text-sm">
                          <div className="w-6 h-6 rounded-lg bg-sky-500/15 flex items-center justify-center shrink-0">
                            <Globe className="w-3 h-3 text-sky-400" />
                          </div>
                          <span className="font-bold text-[#FAFAFA]">{trustStats.reviewSources}</span>
                          <span className="text-[#71717A]">{trustStats.reviewSources === 1 ? 'review site' : 'review sites'}</span>
                        </div>
                      </>
                    )}
                  </div>
                </motion.div>
              )}

              {/* Stale-scores banner — shown when weights differ from original rubric */}
              {(hasCustomWeights || isReweighting) && (
                <div className="mb-4 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center gap-2 text-xs text-amber-300">
                  <span className="text-amber-400">⚡</span>
                  {isReweighting
                    ? 'Re-sorting…'
                    : 'Scores re-ranked by adjusted weights — explanations reflect original analysis.'}
                  {hasCustomWeights && !isReweighting && (
                    <button
                      onClick={handleReset}
                      className="ml-auto text-amber-400 hover:text-amber-200 underline underline-offset-2"
                    >
                      Reset weights
                    </button>
                  )}
                </div>
              )}

              {/* Fix 8: Quality degradation warning — shown when fallback LLM providers were used */}
              {qualityDegraded && (
                <div className="flex items-start gap-3 px-4 py-3 mb-4 rounded-xl border border-amber-500/30 bg-amber-500/8 text-amber-300 text-sm">
                  <svg className="w-4 h-4 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                  </svg>
                  <span>
                    <strong className="font-semibold">Degraded quality:</strong> one or more AI providers fell back to alternates during this analysis. Results are complete but may have lower accuracy than usual.
                  </span>
                </div>
              )}

              {/* Product Link Intelligence Spotlight — shown for #1 product when confidence ≥ 0.72 */}
              <AnimatePresence>
                {(() => {
                  const topProduct = displayProducts[0]
                  const intel = topProduct?.price?.intelligence
                  if (!topProduct || !topProduct.price || !intel || intel.status !== 'confident') return null
                  return (
                    <ProductSpotlight
                      key={`spotlight-${topProduct.name}`}
                      productName={topProduct.name}
                      price={topProduct.price}
                      rank={1}
                    />
                  )
                })()}
              </AnimatePresence>

              {/* Product cards */}
              <div className="space-y-4">
                <AnimatePresence mode="popLayout">
                  {displayProducts.map((product, idx) => (
                    <motion.div
                      key={productClientKey(product, idx)}
                      layout
                      transition={{ duration: 0.18, ease: 'easeOut' }}
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, scale: 0.97 }}
                    >
                      <ProductCard
                        product={toProductCardProps(product, idx + 1, sidebarCriteria)}
                        isSelected={compareSet.has(product.name)}
                        onToggleSelect={() => toggleCompare(product.name)}
                        onTogglePurchased={() => handleTogglePurchased(product.name, product.memory?.status === 'purchased', product.percentage)}
                      />
                    </motion.div>
                  ))}
                </AnimatePresence>
              </div>
            </div>

            {/* Right — Insights */}
            <div className="hidden lg:block lg:sticky lg:top-[76px] lg:h-[calc(100vh-108px)] overflow-y-auto pl-2">
              <InsightsPanel {...insightsProps} reviewIntelligence={reviewIntelligence} />
            </div>
          </div>
        </div>
      </main>

      {/* Diagnostics sheet */}
      <Sheet open={diagnosticsOpen} onOpenChange={setDiagnosticsOpen}>
        <SheetContent side="right" className="w-[360px] sm:w-[420px] bg-[#0F0F12] border-white/[0.06] overflow-y-auto">
          <div className="pt-2 pb-6">
            <div className="flex items-center gap-2 mb-1">
              <Activity className="w-4 h-4 text-violet-400" />
              <SheetTitle className="text-base font-semibold text-[#FAFAFA]">Pipeline Diagnostics</SheetTitle>
            </div>
            <p className="text-xs text-[#71717A] mb-6">
              Timing, resource usage, and warnings from this research run.
            </p>
            <DiagnosticsPanel searchId={id} />
          </div>
        </SheetContent>
      </Sheet>

      {/* Compare bar */}
      <AnimatePresence>
        {compareSet.size >= 2 && (
          <motion.div
            initial={{ y: 100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 100, opacity: 0 }}
            className="fixed bottom-0 left-0 right-0 z-50 p-4 bg-[#0F0F12]/95 backdrop-blur-xl border-t border-white/[0.06]"
          >
            <div className="max-w-xl mx-auto flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="text-[#A1A1AA]">{compareSet.size} products selected</span>
                <Button variant="ghost" size="sm" onClick={() => useResultsStore.getState().clearCompare()} className="text-[#71717A]">
                  Clear
                </Button>
              </div>
              <Button onClick={handleCompare} className="bg-violet-600 hover:bg-violet-500">
                Compare {compareSet.size} products →
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
