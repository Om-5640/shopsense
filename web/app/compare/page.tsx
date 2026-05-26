'use client'

import { Suspense, useState, useEffect } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { ArrowLeft, Trophy, ThumbsUp, ThumbsDown, ExternalLink } from 'lucide-react'
import { AnimatedBackground } from '@/components/layout/animated-background'
import { Header } from '@/components/layout/header'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { getSearchResult } from '@/lib/api'
import { useResultsStore, deriveSidebarCriteria } from '@/lib/store'
import type { ScoredProduct, Rubric } from '@/lib/types'

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
  criteriaScores: Record<string, { score: number; evidence?: string }>
  pros: string[]
  cons: string[]
  verdict: string
}

function toCurrencySymbol(currency: string): string {
  if (currency === 'INR') return '₹'
  if (currency === 'USD') return '$'
  if (currency === 'GBP') return '£'
  if (currency === 'EUR') return '€'
  return currency
}

function toCompareProduct(
  p: ScoredProduct,
  rubric: Rubric,
  weights: Record<string, number>,
): CompareProduct {
  const criteria = deriveSidebarCriteria(rubric, weights)
  const labelMap = Object.fromEntries(criteria.map((c) => [c.id, c.label]))

  const currency = p.price?.currency ?? 'INR'
  const sym = toCurrencySymbol(currency)
  const retailer = p.price?.retailers?.find((r) => !r.is_search) ?? p.price?.retailers?.[0]
  const bestPrice = p.price?.best_price
  const priceNum =
    bestPrice?.price_inr ?? bestPrice?.price_usd ??
    retailer?.price_inr ?? retailer?.price_usd ?? 0

  const criteriaScores: Record<string, { score: number; evidence?: string }> = {}
  p.scores.forEach((s) => {
    const label = labelMap[s.criterion] ?? s.label ?? s.criterion
    criteriaScores[label] = { score: s.score, evidence: s.evidence || undefined }
  })

  const pros = p.scores
    .filter((s) => s.score >= 8)
    .map((s) => {
      const label = labelMap[s.criterion] ?? s.label ?? s.criterion
      return s.evidence ? `${label}: ${s.evidence}` : label
    })

  const cons = p.scores
    .filter((s) => s.score <= 5)
    .map((s) => {
      const label = labelMap[s.criterion] ?? s.label ?? s.criterion
      return s.evidence ? `${label}: ${s.evidence}` : label
    })

  return {
    id: p.name,
    name: p.name,
    score: p.percentage,
    price: priceNum,
    currency: sym,
    store: retailer?.name ?? 'Search',
    storeUrl:
      retailer?.url ??
      `https://www.google.com/search?q=buy+${encodeURIComponent(p.name)}`,
    rating: retailer?.rating,
    reviewCount: retailer?.review_count,
    criteriaScores,
    pros: pros.length > 0 ? pros : ['No standout strengths identified'],
    cons: cons.length > 0 ? cons : ['No significant weaknesses identified'],
    verdict: p.explanation ?? 'No summary available.',
  }
}

function ComparePageContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const [products, setProducts] = useState<CompareProduct[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const rawIds = searchParams.get('ids') ?? ''
  const searchId = searchParams.get('search') ?? ''
  const names = rawIds.split(',').map(decodeURIComponent).filter(Boolean)

  useEffect(() => {
    if (names.length < 2) {
      setError('Select at least 2 products to compare.')
      setLoading(false)
      return
    }

    // Try the in-memory store first (user navigated directly from results page)
    const storeState = useResultsStore.getState()
    if (storeState.products.length > 0 && storeState.rubric) {
      const matched = storeState.products.filter((p) => names.includes(p.name))
      if (matched.length >= 2) {
        setProducts(
          matched.map((p) =>
            toCompareProduct(p, storeState.rubric!, storeState.weights),
          ),
        )
        setLoading(false)
        return
      }
    }

    // Fallback: fetch from API (e.g. direct URL navigation or page refresh)
    if (!searchId) {
      setError('Could not load comparison data. Return to results and try again.')
      setLoading(false)
      return
    }

    getSearchResult(searchId)
      .then((result) => {
        if (!result.rubric || !result.scoredProducts?.length) {
          setError('No product data found for this search.')
          return
        }
        const weights = Object.fromEntries(
          result.rubric.weighted_criteria.map((c) => [c.name, c.weight]),
        )
        const filtered = result.scoredProducts.filter((p) => names.includes(p.name))
        if (filtered.length < 2) {
          setError('Not enough matching products found.')
          return
        }
        setProducts(filtered.map((p) => toCompareProduct(p, result.rubric!, weights)))
      })
      .catch((e) =>
        setError(`Failed to load: ${e instanceof Error ? e.message : String(e)}`),
      )
      .finally(() => setLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawIds, searchId])

  const getScoreColor = (score: number) => {
    if (score >= 8) return 'text-emerald-400 bg-emerald-500/20'
    if (score >= 6) return 'text-amber-400 bg-amber-500/20'
    return 'text-rose-400 bg-rose-500/20'
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#08080A]">
        <div className="w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (error || products.length < 2) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#08080A]">
        <div className="text-center">
          <p className="text-rose-400 mb-4 text-sm">
            {error ?? 'Not enough products to compare.'}
          </p>
          <Button variant="ghost" onClick={() => router.back()}>
            ← Back to results
          </Button>
        </div>
      </div>
    )
  }

  const criteria = Object.keys(products[0].criteriaScores)
  const winner = products.reduce((a, b) => (a.score > b.score ? a : b))

  return (
    <div className="min-h-screen flex flex-col bg-[#08080A]">
      <AnimatedBackground />
      <Header />

      <main className="flex-1 relative z-10">
        <div className="max-w-6xl mx-auto px-4 py-8">
          <Button
            variant="ghost"
            onClick={() => router.back()}
            className="mb-6 text-[#A1A1AA] hover:text-[#FAFAFA]"
          >
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back to results
          </Button>

          <h1 className="text-3xl font-bold text-[#FAFAFA] mb-8">Compare Products</h1>

          {/* Product header row */}
          <div
            className="grid gap-4 mb-8"
            style={{ gridTemplateColumns: `200px repeat(${products.length}, 1fr)` }}
          >
            <div />
            {products.map((product) => (
              <motion.div
                key={product.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className={cn(
                  'p-6 rounded-2xl border text-center',
                  product.id === winner.id
                    ? 'bg-violet-500/10 border-violet-500/30'
                    : 'bg-white/[0.02] border-white/[0.06]',
                )}
              >
                {product.id === winner.id && (
                  <Badge className="mb-3 bg-amber-500/20 text-amber-300 border-amber-500/30">
                    <Trophy className="w-3 h-3 mr-1" />
                    Winner
                  </Badge>
                )}
                <h3 className="text-lg font-semibold text-[#FAFAFA] mb-2">{product.name}</h3>
                {product.price > 0 && (
                  <div className="text-3xl font-bold text-[#FAFAFA] mb-1">
                    {product.currency}{product.price.toLocaleString()}
                  </div>
                )}
                {product.store && (
                  <div className="text-sm text-[#71717A] mb-3">{product.store}</div>
                )}
                <div
                  className={cn(
                    'inline-flex items-center px-3 py-1.5 rounded-full font-mono text-lg font-bold',
                    getScoreColor(product.score / 10),
                  )}
                >
                  {Math.round(product.score)}%
                </div>
              </motion.div>
            ))}
          </div>

          {/* Criteria comparison */}
          {criteria.length > 0 && (
            <div className="rounded-2xl bg-white/[0.02] border border-white/[0.06] overflow-hidden mb-8">
              <div className="p-4 border-b border-white/[0.06]">
                <h2 className="text-lg font-semibold text-[#FAFAFA]">Criteria Comparison</h2>
              </div>

              <div className="divide-y divide-white/[0.06]">
                {criteria.map((criterion) => (
                  <div
                    key={criterion}
                    className="grid gap-4 p-4"
                    style={{ gridTemplateColumns: `200px repeat(${products.length}, 1fr)` }}
                  >
                    <div className="text-sm font-medium text-[#FAFAFA]">{criterion}</div>
                    {products.map((product) => {
                      const scoreData = product.criteriaScores[criterion]
                      if (!scoreData) {
                        return (
                          <div key={product.id} className="text-center text-[#71717A] text-sm">
                            —
                          </div>
                        )
                      }
                      return (
                        <div key={product.id} className="text-center">
                          <div
                            className={cn(
                              'inline-flex items-center justify-center w-10 h-10 rounded-lg font-mono font-bold mb-2',
                              getScoreColor(scoreData.score),
                            )}
                          >
                            {scoreData.score}
                          </div>
                          {scoreData.evidence && (
                            <p className="text-xs text-[#71717A] line-clamp-2">
                              {scoreData.evidence}
                            </p>
                          )}
                        </div>
                      )
                    })}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Pros, Cons, Verdict */}
          <div
            className="grid gap-4"
            style={{ gridTemplateColumns: `repeat(${products.length}, 1fr)` }}
          >
            {products.map((product) => (
              <motion.div
                key={product.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-6"
              >
                <h3 className="font-semibold text-[#FAFAFA] mb-4">{product.name}</h3>

                <div className="mb-4">
                  <div className="flex items-center gap-2 text-emerald-400 text-sm font-medium mb-2">
                    <ThumbsUp className="w-4 h-4" />
                    Pros
                  </div>
                  <ul className="space-y-1">
                    {product.pros.map((pro, i) => (
                      <li key={i} className="text-sm text-[#A1A1AA]">
                        • {pro}
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="mb-4">
                  <div className="flex items-center gap-2 text-rose-400 text-sm font-medium mb-2">
                    <ThumbsDown className="w-4 h-4" />
                    Cons
                  </div>
                  <ul className="space-y-1">
                    {product.cons.map((con, i) => (
                      <li key={i} className="text-sm text-[#A1A1AA]">
                        • {con}
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="pt-4 border-t border-white/[0.06]">
                  <p className="text-sm text-[#A1A1AA] italic">{product.verdict}</p>
                </div>

                <Button className="w-full mt-4 bg-violet-600 hover:bg-violet-500" asChild>
                  <a href={product.storeUrl} target="_blank" rel="noopener noreferrer">
                    Open on {product.store}
                    <ExternalLink className="w-4 h-4 ml-2" />
                  </a>
                </Button>
              </motion.div>
            ))}
          </div>
        </div>
      </main>
    </div>
  )
}

export default function ComparePage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-[#08080A]">
          <div className="w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <ComparePageContent />
    </Suspense>
  )
}
