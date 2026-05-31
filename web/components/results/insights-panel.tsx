'use client'

import { motion } from 'framer-motion'
import {
  AlertTriangle,
  ThumbsDown,
  Sparkles,
  Shield,
  Clock,
  ExternalLink,
  BookOpen,
  Youtube,
  Globe,
  Zap,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { ReviewIntelligence, ReviewSource, ReviewConflict } from '@/lib/types'

interface InsightsPanelProps {
  categories: Array<{ name: string; products: string[] }>
  communitySignal: Array<{ threadId: string; sentiment: 'positive' | 'neutral' | 'negative' }>
  toAvoid: Array<{ product: string; reason: string }>
  warnings: Array<{ product: string; warning: string }>
  reviewIntelligence?: ReviewIntelligence | null
}

// ── Review Intelligence helpers ───────────────────────────────────────────────

function TrustBar({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color =
    score >= 0.90 ? 'bg-emerald-500' :
    score >= 0.65 ? 'bg-amber-500' :
    'bg-rose-500'
  return (
    <div className="flex items-center gap-1.5 flex-1 min-w-0">
      <div className="flex-1 h-1 bg-white/[0.06] rounded-full overflow-hidden">
        <div className={cn('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-[#71717A] shrink-0 font-mono w-6 text-right">{pct}</span>
    </div>
  )
}

function FreshnessBar({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color =
    score >= 0.80 ? 'bg-violet-500' :
    score >= 0.50 ? 'bg-amber-500' :
    'bg-rose-500/60'
  return (
    <div className="flex items-center gap-1.5 flex-1 min-w-0">
      <div className="flex-1 h-1 bg-white/[0.06] rounded-full overflow-hidden">
        <div className={cn('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-[#71717A] shrink-0 font-mono w-6 text-right">{pct}</span>
    </div>
  )
}

function SourceTypeIcon({ type }: { type: string }) {
  if (type === 'youtube') return <Youtube className="w-3 h-3 text-rose-400 shrink-0" />
  if (type === 'expert_editorial') return <BookOpen className="w-3 h-3 text-violet-400 shrink-0" />
  if (type === 'news') return <Globe className="w-3 h-3 text-sky-400 shrink-0" />
  return <Zap className="w-3 h-3 text-amber-400 shrink-0" />  // gemini_grounding
}

function AuthorityBadge({ tier }: { tier: string }) {
  if (tier === 'trusted')
    return <span className="text-[9px] px-1.5 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-medium">TRUSTED</span>
  if (tier === 'good')
    return <span className="text-[9px] px-1.5 py-0.5 rounded-md bg-amber-500/20 text-amber-300 border border-amber-500/30 font-medium">GOOD</span>
  return null
}

function SourceRow({ source }: { source: ReviewSource }) {
  return (
    <div className="flex flex-col gap-1.5 p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.05] hover:border-white/[0.10] transition-colors">
      <div className="flex items-center gap-1.5 min-w-0">
        <SourceTypeIcon type={source.source_type} />
        <span className="text-xs font-medium text-[#FAFAFA] truncate flex-1">{source.domain}</span>
        <AuthorityBadge tier={source.authority_tier} />
        {source.url && (
          <a href={source.url} target="_blank" rel="noopener noreferrer" className="shrink-0">
            <ExternalLink className="w-3 h-3 text-[#52525B] hover:text-[#A1A1AA] transition-colors" />
          </a>
        )}
      </div>

      {source.title && (
        <p className="text-[10px] text-[#71717A] leading-relaxed line-clamp-1 pl-4">{source.title}</p>
      )}

      <div className="pl-4 flex items-center gap-3">
        <div className="flex items-center gap-1 flex-1">
          <Shield className="w-2.5 h-2.5 text-[#52525B] shrink-0" />
          <TrustBar score={source.trust_score} />
        </div>
        <div className="flex items-center gap-1 flex-1">
          <Clock className="w-2.5 h-2.5 text-[#52525B] shrink-0" />
          <FreshnessBar score={source.freshness_score} />
        </div>
      </div>

      {source.rating != null && (
        <p className="text-[10px] text-amber-300/80 pl-4">
          Rating extracted: {source.rating}/10
        </p>
      )}
    </div>
  )
}

function ConflictRow({ conflict }: { conflict: ReviewConflict }) {
  const topic = conflict.topic.replace(/_/g, ' ')
  const majority = Math.round(conflict.agreement_score * 100)
  return (
    <div className="p-2.5 rounded-xl bg-amber-500/[0.06] border border-amber-500/20">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-xs font-medium text-amber-300 capitalize">{topic}</span>
        <span className="text-[10px] text-[#71717A]">{majority}% agree</span>
      </div>
      <div className="flex items-center gap-2 text-[10px] text-[#A1A1AA]">
        <span className="text-emerald-400">+{conflict.positive_count} positive</span>
        <span className="text-[#52525B]">vs</span>
        <span className="text-rose-400">−{conflict.negative_count} negative</span>
      </div>
    </div>
  )
}

function ReviewSourcesTab({ intel }: { intel: ReviewIntelligence }) {
  const { sources, conflict_signals, stats } = intel
  const conflicts = conflict_signals.filter(c => c.conflict)

  return (
    <div className="space-y-4">
      {/* Stats row */}
      {stats.total > 0 && (
        <div className="grid grid-cols-3 gap-2">
          <div className="text-center p-2 rounded-lg bg-violet-500/10 border border-violet-500/20">
            <div className="text-lg font-bold text-violet-400">{stats.total}</div>
            <div className="text-[10px] text-[#71717A] mt-0.5">Sources</div>
          </div>
          <div className="text-center p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
            <div className="text-lg font-bold text-emerald-400">{stats.trusted_count}</div>
            <div className="text-[10px] text-[#71717A] mt-0.5">Trusted</div>
          </div>
          <div className="text-center p-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
            <div className="text-lg font-bold text-amber-400">{Math.round(stats.avg_trust * 100)}</div>
            <div className="text-[10px] text-[#71717A] mt-0.5">Avg trust</div>
          </div>
        </div>
      )}

      {/* Trust / freshness summary bars */}
      {stats.total > 0 && (
        <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.06] space-y-2">
          <div className="flex items-center gap-2">
            <Shield className="w-3.5 h-3.5 text-[#52525B]" />
            <span className="text-[10px] text-[#71717A] uppercase tracking-wide w-16">Avg trust</span>
            <div className="flex-1 h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
              <div
                className={cn('h-full rounded-full', stats.avg_trust >= 0.80 ? 'bg-emerald-500' : stats.avg_trust >= 0.60 ? 'bg-amber-500' : 'bg-rose-500')}
                style={{ width: `${Math.round(stats.avg_trust * 100)}%` }}
              />
            </div>
            <span className="text-[10px] text-[#71717A] font-mono w-8 text-right">{Math.round(stats.avg_trust * 100)}%</span>
          </div>
          <div className="flex items-center gap-2">
            <Clock className="w-3.5 h-3.5 text-[#52525B]" />
            <span className="text-[10px] text-[#71717A] uppercase tracking-wide w-16">Freshness</span>
            <div className="flex-1 h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
              <div
                className={cn('h-full rounded-full', stats.avg_freshness >= 0.75 ? 'bg-violet-500' : stats.avg_freshness >= 0.50 ? 'bg-amber-500' : 'bg-rose-500/60')}
                style={{ width: `${Math.round(stats.avg_freshness * 100)}%` }}
              />
            </div>
            <span className="text-[10px] text-[#71717A] font-mono w-8 text-right">{Math.round(stats.avg_freshness * 100)}%</span>
          </div>
          {stats.youtube_count > 0 && (
            <div className="flex items-center gap-2 pt-1 border-t border-white/[0.04]">
              <Youtube className="w-3.5 h-3.5 text-rose-400" />
              <span className="text-[10px] text-[#71717A]">{stats.youtube_count} YouTube transcript{stats.youtube_count > 1 ? 's' : ''} included</span>
            </div>
          )}
        </div>
      )}

      {/* Expert disagreements */}
      {conflicts.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-xs text-amber-400">
            <AlertTriangle className="w-3.5 h-3.5" />
            <span className="font-medium">Expert disagreements</span>
          </div>
          {conflicts.map(c => <ConflictRow key={c.topic} conflict={c} />)}
        </div>
      )}

      {/* Source list */}
      {sources.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[10px] text-[#52525B] uppercase tracking-wide">
            Sources consulted · ranked by trust
          </p>
          {[...sources]
            .sort((a, b) => b.trust_score - a.trust_score)
            .map((src) => (
              <SourceRow key={src.url || src.domain} source={src} />
            ))}
        </div>
      )}

      {sources.length === 0 && (
        <p className="text-xs text-[#52525B] text-center py-4">
          No expert review sources were scraped for this search.
        </p>
      )}
    </div>
  )
}

// ── Main Panel ────────────────────────────────────────────────────────────────

export function InsightsPanel({
  categories,
  communitySignal,
  toAvoid,
  warnings,
  reviewIntelligence,
}: InsightsPanelProps) {
  const getSentimentColor = (sentiment: 'positive' | 'neutral' | 'negative') => {
    switch (sentiment) {
      case 'positive': return 'bg-emerald-500'
      case 'neutral': return 'bg-amber-500'
      case 'negative': return 'bg-rose-500'
    }
  }

  const hasReviewData = reviewIntelligence && (reviewIntelligence.stats?.total ?? 0) > 0

  return (
    <div className="h-full flex flex-col">
      <h2 className="text-lg font-semibold text-[#FAFAFA] mb-4">Insights</h2>

      <Tabs defaultValue="categories" className="flex-1 flex flex-col">
        <TabsList className={cn(
          'grid bg-white/[0.04] rounded-lg p-1 mb-4',
          hasReviewData ? 'grid-cols-4' : 'grid-cols-3',
        )}>
          <TabsTrigger
            value="categories"
            className="text-xs data-[state=active]:bg-white/[0.08] data-[state=active]:text-[#FAFAFA] rounded-md"
          >
            Types
          </TabsTrigger>
          <TabsTrigger
            value="signal"
            className="text-xs data-[state=active]:bg-white/[0.08] data-[state=active]:text-[#FAFAFA] rounded-md"
          >
            Signal
          </TabsTrigger>
          <TabsTrigger
            value="avoid"
            className="text-xs data-[state=active]:bg-white/[0.08] data-[state=active]:text-[#FAFAFA] rounded-md"
          >
            Avoid
          </TabsTrigger>
          {hasReviewData && (
            <TabsTrigger
              value="sources"
              className="text-xs data-[state=active]:bg-white/[0.08] data-[state=active]:text-[#FAFAFA] rounded-md relative"
            >
              Sources
              {(reviewIntelligence!.stats?.conflicts_found ?? 0) > 0 && (
                <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-amber-400" />
              )}
            </TabsTrigger>
          )}
        </TabsList>

        <TabsContent value="categories" className="flex-1 mt-0">
          <div className="space-y-4">
            {categories.map((category) => (
              <div key={category.name} className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.06]">
                <Badge className="mb-2 bg-violet-500/20 text-violet-300 border-violet-500/30">
                  {category.name}
                </Badge>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {category.products.slice(0, 3).map((product) => (
                    <span
                      key={product}
                      className="text-xs px-2 py-1 rounded-md bg-white/[0.04] text-[#A1A1AA]"
                    >
                      {product}
                    </span>
                  ))}
                  {category.products.length > 3 && (
                    <span className="text-xs px-2 py-1 text-[#71717A]">
                      +{category.products.length - 3} more
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="signal" className="flex-1 mt-0">
          <div className="space-y-3">
            <div className="flex items-center gap-2 mb-1">
              <Sparkles className="w-4 h-4 text-violet-400" />
              <span className="text-sm font-medium text-[#FAFAFA]">Reddit community sentiment</span>
            </div>
            <p className="text-xs text-[#71717A] mb-3">
              How Reddit users feel about each product in the results
            </p>

            {(() => {
              const pos = communitySignal.filter(s => s.sentiment === 'positive').length
              const neu = communitySignal.filter(s => s.sentiment === 'neutral').length
              const neg = communitySignal.filter(s => s.sentiment === 'negative').length
              return (
                <div className="grid grid-cols-3 gap-2 mb-4">
                  <div className="text-center p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                    <div className="text-lg font-bold text-emerald-400">{pos}</div>
                    <div className="text-[10px] text-[#71717A] mt-0.5">Highly recommended</div>
                  </div>
                  <div className="text-center p-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
                    <div className="text-lg font-bold text-amber-400">{neu}</div>
                    <div className="text-[10px] text-[#71717A] mt-0.5">Mixed opinions</div>
                  </div>
                  <div className="text-center p-2 rounded-lg bg-rose-500/10 border border-rose-500/20">
                    <div className="text-lg font-bold text-rose-400">{neg}</div>
                    <div className="text-[10px] text-[#71717A] mt-0.5">Weak signal</div>
                  </div>
                </div>
              )
            })()}

            <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.06]">
              <p className="text-[10px] text-[#52525B] mb-2 uppercase tracking-wide">
                One dot per product
              </p>
              <TooltipProvider>
                <div className="flex flex-wrap gap-1.5">
                  {communitySignal.map((signal, index) => (
                    <Tooltip key={index}>
                      <TooltipTrigger asChild>
                        <motion.div
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          transition={{ delay: index * 0.04 }}
                          className={`w-3.5 h-3.5 rounded-full cursor-default ${getSentimentColor(signal.sentiment)}`}
                        />
                      </TooltipTrigger>
                      <TooltipContent side="top">
                        <p className="text-xs capitalize">
                          {signal.sentiment === 'positive' ? 'Highly recommended on Reddit'
                            : signal.sentiment === 'negative' ? 'Weak or negative signal'
                            : 'Mixed community opinions'}
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  ))}
                </div>
              </TooltipProvider>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="avoid" className="flex-1 mt-0">
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm text-rose-400 mb-2">
              <ThumbsDown className="w-4 h-4" />
              <span className="font-medium">Products to avoid</span>
            </div>

            {toAvoid.map((item) => (
              <div
                key={item.product}
                className="p-3 rounded-xl bg-rose-500/5 border border-rose-500/20"
              >
                <p className="text-sm font-medium text-[#FAFAFA] mb-1">{item.product}</p>
                <p className="text-xs text-[#A1A1AA]">{item.reason}</p>
              </div>
            ))}

            {warnings.length > 0 && (
              <>
                <div className="flex items-center gap-2 text-sm text-amber-400 mt-4 mb-2">
                  <AlertTriangle className="w-4 h-4" />
                  <span className="font-medium">Split opinions</span>
                </div>

                {warnings.map((item) => (
                  <div
                    key={item.product}
                    className="p-3 rounded-xl bg-amber-500/5 border border-amber-500/20"
                  >
                    <p className="text-sm font-medium text-[#FAFAFA] mb-1">{item.product}</p>
                    <p className="text-xs text-[#A1A1AA]">{item.warning}</p>
                  </div>
                ))}
              </>
            )}
          </div>
        </TabsContent>

        {hasReviewData && (
          <TabsContent value="sources" className="flex-1 mt-0 overflow-y-auto">
            <ReviewSourcesTab intel={reviewIntelligence!} />
          </TabsContent>
        )}
      </Tabs>
    </div>
  )
}
