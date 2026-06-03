'use client'

import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Clock, Package, MessageSquare, Zap, GitMerge, AlertTriangle, CheckCircle2, Loader2, Cpu, Wifi } from 'lucide-react'
import { getDiagnostics } from '@/lib/api'
import type { PipelineDiagnostics } from '@/lib/types'

const STAGE_LABELS: Record<string, string> = {
  reddit_fetch:     'Reddit Research',
  review_fetch:     'Review Scraping',
  summarize:        'Summarization',
  analyze:          'Analysis',
  cross_validate:   'Cross-validation',
  mention_counting: 'Mention Pipeline',
  scoring:          'Scoring',
  explanations:     'Explanations',
  cache_hit:        'Cache Hit',
}

const STAGE_ORDER = [
  'reddit_fetch', 'review_fetch', 'summarize', 'analyze',
  'cross_validate', 'mention_counting', 'scoring', 'explanations', 'cache_hit',
]

function TimingBar({ label, seconds, maxSeconds }: { label: string; seconds: number; maxSeconds: number }) {
  const pct = maxSeconds > 0 ? Math.max(4, Math.round((seconds / maxSeconds) * 100)) : 4
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-[#A1A1AA]">{label}</span>
        <span className="font-mono text-[#71717A]">{seconds.toFixed(1)}s</span>
      </div>
      <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          className="h-full rounded-full bg-violet-500/70"
        />
      </div>
    </div>
  )
}

function StatCard({ icon: Icon, label, value, sub }: {
  icon: React.ElementType
  label: string
  value: string | number
  sub?: string
}) {
  return (
    <div className="flex items-start gap-3 p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
      <div className="w-7 h-7 rounded-lg bg-violet-500/15 flex items-center justify-center shrink-0 mt-0.5">
        <Icon className="w-3.5 h-3.5 text-violet-400" />
      </div>
      <div className="min-w-0">
        <p className="text-[11px] text-[#71717A] leading-none mb-1">{label}</p>
        <p className="text-sm font-semibold text-[#FAFAFA]">{value}</p>
        {sub && <p className="text-[11px] text-[#52525B] mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

function parseWarning(raw: string): string {
  return raw
    .replace('[token_budget]', '')
    .replace('Trimming to fit.', '')
    .trim()
}

interface DiagnosticsPanelProps {
  searchId: string
}

export function DiagnosticsPanel({ searchId }: DiagnosticsPanelProps) {
  const [data, setData] = useState<PipelineDiagnostics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!searchId) return
    setLoading(true)
    getDiagnostics(searchId)
      .then(setData)
      .catch(() => setError('Could not load diagnostics.'))
      .finally(() => setLoading(false))
  }, [searchId])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-32">
        <Loader2 className="w-5 h-5 text-violet-400 animate-spin" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex items-center gap-2 text-[#71717A] text-sm py-6">
        <AlertTriangle className="w-4 h-4 text-amber-500" />
        {error ?? 'No diagnostics available.'}
      </div>
    )
  }

  const stats = data.stats
  const timings = stats.stage_timings ?? {}
  const orderedTimings = STAGE_ORDER
    .filter((s) => timings[s] !== undefined)
    .map((s) => ({ key: s, label: STAGE_LABELS[s] ?? s, seconds: timings[s] }))

  const totalTime = Object.values(timings).reduce((a, b) => a + b, 0)
  const maxTime = Math.max(...orderedTimings.map((t) => t.seconds), 1)

  const tokensK = stats.tokens_estimated ? Math.round(stats.tokens_estimated / 1000) : null

  return (
    <div className="space-y-6 py-1">
      {/* Run overview */}
      <div>
        <p className="text-xs font-medium text-[#71717A] uppercase tracking-wide mb-3">Run Overview</p>
        <div className="grid grid-cols-2 gap-2">
          <StatCard
            icon={Package}
            label="Products Scored"
            value={stats.product_count}
          />
          <StatCard
            icon={MessageSquare}
            label="Threads Researched"
            value={stats.thread_count}
            sub={stats.dedup_removed > 0 ? `${stats.dedup_removed} dupes removed` : undefined}
          />
          <StatCard
            icon={Zap}
            label="LLM Calls (est.)"
            value={stats.llm_calls_estimated}
          />
          <StatCard
            icon={Clock}
            label="Total Pipeline Time"
            value={data.elapsed_s !== undefined ? `${data.elapsed_s}s` : `${totalTime.toFixed(1)}s`}
          />
          {tokensK !== null && (
            <StatCard
              icon={GitMerge}
              label="Tokens Processed (est.)"
              value={`~${tokensK}K`}
              sub="research context"
            />
          )}
          {stats.scoring_mode && (
            <StatCard
              icon={Cpu}
              label="Scoring Mode"
              value={stats.scoring_mode}
              sub={stats.providers_used && stats.providers_used.length > 0
                ? stats.providers_used.join(', ')
                : undefined}
            />
          )}
        </div>
      </div>

      {/* Stage timings */}
      {orderedTimings.length > 0 && (
        <div>
          <p className="text-xs font-medium text-[#71717A] uppercase tracking-wide mb-3">Stage Timings</p>
          <div className="space-y-3">
            {orderedTimings.map((t, i) => (
              <motion.div
                key={t.key}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.05 }}
              >
                <TimingBar label={t.label} seconds={t.seconds} maxSeconds={maxTime} />
              </motion.div>
            ))}
          </div>
        </div>
      )}

      {/* Provider / infrastructure warnings */}
      {stats.pipeline_warnings && stats.pipeline_warnings.length > 0 && (
        <div>
          <p className="text-xs font-medium text-[#71717A] uppercase tracking-wide mb-3">Provider Warnings</p>
          <div className="space-y-2">
            {stats.pipeline_warnings.map((w, i) => (
              <div key={i} className="flex items-start gap-2 p-3 rounded-xl bg-orange-500/[0.07] border border-orange-500/20">
                <Wifi className="w-3.5 h-3.5 text-orange-400 mt-0.5 shrink-0" />
                <p className="text-xs text-orange-200/80 leading-relaxed">{w}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Token budget warnings */}
      {stats.warnings && stats.warnings.length > 0 ? (
        <div>
          <p className="text-xs font-medium text-[#71717A] uppercase tracking-wide mb-3">Token Budget Warnings</p>
          <div className="space-y-2">
            {stats.warnings.map((w, i) => (
              <div key={i} className="flex items-start gap-2 p-3 rounded-xl bg-amber-500/[0.07] border border-amber-500/20">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-400 mt-0.5 shrink-0" />
                <p className="text-xs text-amber-200/80 leading-relaxed">{parseWarning(w)}</p>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2 p-3 rounded-xl bg-emerald-500/[0.07] border border-emerald-500/20">
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
          <p className="text-xs text-emerald-300/80">No token budget warnings — all context fit within limits.</p>
        </div>
      )}
    </div>
  )
}
