'use client'

import { useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Button } from '@/components/ui/button'

export type ActivityAccent = 'violet' | 'orange' | 'cyan' | 'emerald' | 'amber' | 'dim'

export interface ActivityEntry {
  id: number
  secs: number
  text: string
  accent: ActivityAccent
}

interface Props {
  stageLabel: string
  subreddits: Array<{ name: string; count: number }>
  reviewDomains: string[]
  progressItem: string
  progressFrac: number
  activity: ActivityEntry[]
  elapsedTime: number
  onStop: () => void
  stopping: boolean
}

const ACCENT: Record<ActivityAccent, string> = {
  violet:  'text-violet-300',
  orange:  'text-orange-300',
  cyan:    'text-cyan-300',
  emerald: 'text-emerald-300',
  amber:   'text-amber-300',
  dim:     'text-[#71717A]',
}

function fmt(s: number) {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export function ResearchLiveFeed({
  stageLabel,
  subreddits,
  reviewDomains,
  progressItem,
  progressFrac,
  activity,
  elapsedTime,
  onStop,
  stopping,
}: Props) {
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [activity.length])

  return (
    <div className="rounded-2xl bg-[#0C0C0F] border border-white/[0.07] flex flex-col overflow-hidden shadow-xl">

      {/* ── Header ───────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-5 py-3.5 border-b border-white/[0.05] shrink-0">
        <span className="relative flex h-2.5 w-2.5 shrink-0">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-60" />
          <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-red-500" />
        </span>
        <span className="text-[10px] font-bold tracking-[0.15em] text-red-400 uppercase shrink-0">Live</span>
        <span className="flex-1 text-sm font-medium text-[#E4E4E7] truncate">{stageLabel}</span>
        <span className="font-mono text-sm text-[#52525B] shrink-0 tabular-nums">{fmt(elapsedTime)}</span>
      </div>

      {/* ── Scrollable body ──────────────────────────────── */}
      <div className="flex-1 overflow-y-auto min-h-0">

        {/* Reddit Sources */}
        <AnimatePresence>
          {subreddits.length > 0 && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              transition={{ duration: 0.3 }}
              className="px-5 py-4 border-b border-white/[0.04]"
            >
              <p className="text-[10px] uppercase tracking-[0.12em] text-[#52525B] mb-3 font-semibold flex items-center gap-1.5">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-orange-500/70" />
                Reddit Sources
                <span className="text-[#3F3F46] normal-case tracking-normal font-normal ml-1">
                  — {subreddits.length} {subreddits.length === 1 ? 'community' : 'communities'}
                </span>
              </p>
              <div className="flex flex-wrap gap-2">
                {subreddits.map((s, i) => (
                  <motion.div
                    key={s.name}
                    initial={{ opacity: 0, scale: 0.82, y: 6 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    transition={{ delay: i * 0.055, type: 'spring', stiffness: 340, damping: 22 }}
                    className="flex items-center gap-1.5 bg-orange-500/[0.07] border border-orange-500/[0.18] rounded-lg px-2.5 py-1"
                  >
                    <span className="text-orange-400 text-[11px] font-semibold">r/{s.name}</span>
                    <span className="text-[10px] text-orange-600/70 font-mono">×{s.count}</span>
                  </motion.div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Review Sites */}
        <AnimatePresence>
          {reviewDomains.length > 0 && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              transition={{ duration: 0.3 }}
              className="px-5 py-4 border-b border-white/[0.04]"
            >
              <p className="text-[10px] uppercase tracking-[0.12em] text-[#52525B] mb-3 font-semibold flex items-center gap-1.5">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-cyan-500/70" />
                Expert Review Sites
                <span className="text-[#3F3F46] normal-case tracking-normal font-normal ml-1">
                  — {reviewDomains.length} {reviewDomains.length === 1 ? 'source' : 'sources'}
                </span>
              </p>
              <div className="flex flex-wrap gap-2">
                {reviewDomains.map((d, i) => (
                  <motion.div
                    key={d}
                    initial={{ opacity: 0, scale: 0.82, y: 6 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    transition={{ delay: i * 0.065, type: 'spring', stiffness: 340, damping: 22 }}
                    className="flex items-center gap-1.5 bg-cyan-500/[0.07] border border-cyan-500/[0.18] rounded-lg px-2.5 py-1"
                  >
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-400/50 shrink-0" />
                    <span className="text-cyan-300 text-[11px] font-medium">{d}</span>
                  </motion.div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Now Processing */}
        <AnimatePresence mode="wait">
          {progressItem && (
            <motion.div
              key={progressItem}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 6 }}
              transition={{ duration: 0.22 }}
              className="px-5 py-4 border-b border-white/[0.04]"
            >
              <p className="text-[10px] uppercase tracking-[0.12em] text-[#52525B] mb-3 font-semibold flex items-center gap-1.5">
                <span className="relative flex h-1.5 w-1.5 shrink-0">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-violet-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-violet-500" />
                </span>
                Now Processing
              </p>
              <div className="flex items-center gap-3 mb-2.5">
                <span className="text-sm font-medium text-[#F4F4F5] flex-1 min-w-0 truncate">
                  {progressItem}
                </span>
                {progressFrac > 0 && (
                  <span className="text-xs text-[#71717A] font-mono tabular-nums shrink-0">
                    {Math.round(progressFrac * 100)}%
                  </span>
                )}
              </div>
              {progressFrac > 0 && (
                <div className="w-full bg-white/[0.05] rounded-full h-[3px] overflow-hidden">
                  <motion.div
                    className="h-[3px] rounded-full bg-gradient-to-r from-violet-600 to-violet-400"
                    animate={{ width: `${progressFrac * 100}%` }}
                    transition={{ duration: 0.35, ease: 'easeOut' }}
                  />
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Live Activity Log */}
        <div className="px-5 py-4">
          <p className="text-[10px] uppercase tracking-[0.12em] text-[#52525B] mb-3 font-semibold flex items-center gap-1.5">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#3F3F46]" />
            Activity
          </p>
          <div
            ref={logRef}
            className="space-y-1.5 max-h-60 overflow-y-auto [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]"
          >
            {activity.length === 0 && (
              <div className="flex items-center gap-2.5">
                <span className="text-[#3F3F46] font-mono text-[11px] shrink-0 tabular-nums">0:00</span>
                <span className="text-[#52525B] text-xs">Starting research pipeline…</span>
              </div>
            )}
            <AnimatePresence initial={false}>
              {activity.map((entry) => (
                <motion.div
                  key={entry.id}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.18 }}
                  className="flex items-start gap-2.5"
                >
                  <span className="text-[#3F3F46] font-mono text-[11px] shrink-0 pt-px tabular-nums">
                    {fmt(entry.secs)}
                  </span>
                  <span className="text-[#3F3F46] text-[11px] shrink-0 pt-px select-none">▸</span>
                  <span className={`text-[11px] leading-relaxed break-words min-w-0 ${ACCENT[entry.accent]}`}>
                    {entry.text}
                  </span>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        </div>
      </div>

      {/* ── Footer ───────────────────────────────────────── */}
      <div className="border-t border-white/[0.05] px-5 py-3 flex items-center justify-between shrink-0 bg-white/[0.01]">
        <span className="text-[11px] text-[#3F3F46] font-mono">shopsense · research engine</span>
        <Button
          variant="ghost"
          size="sm"
          onClick={onStop}
          disabled={stopping}
          className="h-7 px-3 text-xs text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 border border-rose-500/[0.2] hover:border-rose-500/40 transition-all"
        >
          {stopping ? (
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 border border-rose-400 border-t-transparent rounded-full animate-spin" />
              Stopping…
            </span>
          ) : (
            '■  Stop Research'
          )}
        </Button>
      </div>
    </div>
  )
}
