'use client'

import { useEffect, useRef, useState } from 'react'
import { motion, useInView, AnimatePresence } from 'framer-motion'
import {
  MessagesSquare, Sparkles, SlidersHorizontal,
  MessageCircle, Globe, CheckCircle2, Brain,
  ChevronRight, BarChart3, Zap,
} from 'lucide-react'

// ── animated counter ───────────────────────────────────────────────────────────
function CountUp({ to, suffix = '' }: { to: number; suffix?: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const inView = useInView(ref, { once: true })
  const [val, setVal] = useState(0)
  useEffect(() => {
    if (!inView) return
    const dur = 1600
    let start: number | null = null
    const tick = (ts: number) => {
      if (start === null) start = ts
      const p = Math.min((ts - start) / dur, 1)
      setVal(Math.floor((1 - Math.pow(1 - p, 3)) * to))
      if (p < 1) requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  }, [inView, to])
  return <span ref={ref}>{val}{suffix}</span>
}

// ── Feature 1 visual: source pipeline ─────────────────────────────────────────
const REDDIT_THREADS = [
  { sub: 'r/headphones',   comments: 142 },
  { sub: 'r/audiophile',   comments: 89 },
  { sub: 'r/BuyItForLife', comments: 56 },
  { sub: 'r/Earbuds',      comments: 71 },
]

const PIPELINE_STEPS = [
  { Icon: Globe,          label: 'Source discovery',   desc: 'Gemini Grounding + Serper find authoritative URLs' },
  { Icon: MessageCircle,  label: 'Reddit fetch',       desc: 'Arctic Shift archives — 100+ comments in <8s' },
  { Icon: Brain,          label: 'LLM analysis',       desc: 'Per-thread agents extract products, sentiment, quotes' },
  { Icon: CheckCircle2,   label: 'Spam filtered',      desc: 'Bot links, affiliate trackers, promo pages removed' },
]

function SourcePipelineVisual({ inView }: { inView: boolean }) {
  return (
    <div className="space-y-3">
      {/* Reddit panel */}
      <div className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="w-6 h-6 rounded-lg bg-orange-500/15 flex items-center justify-center">
            <MessageCircle className="w-3.5 h-3.5 text-orange-400" />
          </div>
          <span className="text-xs font-medium text-[#A1A1AA]">Reddit threads</span>
          <span className="ml-auto text-xs text-orange-400/70 font-medium">15 fetched</span>
        </div>
        <div className="space-y-2">
          {REDDIT_THREADS.map((t, i) => (
            <motion.div
              key={t.sub}
              initial={{ opacity: 0, x: -12 }}
              animate={inView ? { opacity: 1, x: 0 } : {}}
              transition={{ delay: 0.06 * i, duration: 0.35 }}
              className="flex items-center gap-2"
            >
              <span className="text-xs font-medium text-orange-300/80 w-28 shrink-0">{t.sub}</span>
              <div className="flex-1 h-1 rounded-full bg-white/[0.04] overflow-hidden">
                <motion.div
                  className="h-full rounded-full bg-orange-500/35"
                  initial={{ width: 0 }}
                  animate={inView ? { width: `${(t.comments / 150) * 100}%` } : {}}
                  transition={{ delay: 0.2 + 0.06 * i, duration: 0.55, ease: 'easeOut' }}
                />
              </div>
              <span className="text-xs text-[#52525B] tabular-nums w-10 text-right">{t.comments}c</span>
            </motion.div>
          ))}
        </div>
      </div>

      {/* Connector */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={inView ? { opacity: 1 } : {}}
        transition={{ delay: 0.5, duration: 0.4 }}
        className="flex items-center gap-3 px-2"
      >
        <div className="flex-1 h-px bg-gradient-to-r from-orange-500/20 to-violet-500/20" />
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-violet-500/10 border border-violet-500/20">
          <Brain className="w-3 h-3 text-violet-400" />
          <span className="text-xs text-violet-400">AI analysis</span>
          <motion.div
            animate={inView ? { opacity: [0.3, 1, 0.3] } : {}}
            transition={{ repeat: Infinity, duration: 1.4, delay: 0.7 }}
            className="w-1 h-1 rounded-full bg-violet-400"
          />
        </div>
        <div className="flex-1 h-px bg-gradient-to-r from-violet-500/20 to-emerald-500/20" />
      </motion.div>

      {/* Output grid */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ delay: 0.72, duration: 0.4 }}
        className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-5"
      >
        <div className="flex items-center gap-2 mb-4">
          <div className="w-6 h-6 rounded-lg bg-emerald-500/15 flex items-center justify-center">
            <BarChart3 className="w-3.5 h-3.5 text-emerald-400" />
          </div>
          <span className="text-xs font-medium text-[#A1A1AA]">Extracted signals</span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {[
            { label: 'Products found',  value: '18',   color: 'text-emerald-400' },
            { label: 'Sentiment tags',  value: '240+', color: 'text-emerald-400' },
            { label: 'Expert quotes',   value: '34',   color: 'text-violet-400'  },
            { label: 'Spam filtered',   value: '11',   color: 'text-[#52525B]'   },
          ].map((item, i) => (
            <motion.div
              key={item.label}
              initial={{ opacity: 0 }}
              animate={inView ? { opacity: 1 } : {}}
              transition={{ delay: 0.9 + i * 0.07 }}
              className="rounded-lg bg-white/[0.02] border border-white/[0.04] p-3"
            >
              <div className={`text-lg font-bold ${item.color}`}>{item.value}</div>
              <div className="text-xs text-[#52525B] mt-0.5">{item.label}</div>
            </motion.div>
          ))}
        </div>
      </motion.div>
    </div>
  )
}

// ── Feature 2 visual: interview ────────────────────────────────────────────────
const INTERVIEW_QS = [
  { q: 'How important is battery life to you?',  label: 'Battery Life',      weight: 9 },
  { q: 'Do you need active noise cancellation?', label: 'ANC Effectiveness', weight: 7 },
  { q: 'Are you using these mostly outdoors?',   label: 'Fit & Stability',   weight: 8 },
]

function InterviewVisual({ inView }: { inView: boolean }) {
  const [step, setStep] = useState(0)
  const [done, setDone] = useState(0)

  useEffect(() => {
    if (!inView) return
    const id = setInterval(() => {
      setDone(d => Math.min(d + 1, INTERVIEW_QS.length))
      setStep(s => (s + 1) % INTERVIEW_QS.length)
    }, 2800)
    return () => clearInterval(id)
  }, [inView])

  const current = INTERVIEW_QS[step]

  return (
    <div className="space-y-3">
      {/* Question card */}
      <div className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-5">
        <div className="flex items-center justify-between mb-4">
          <span className="text-xs text-[#52525B] uppercase tracking-widest font-medium">Interview</span>
          <span className="text-xs text-emerald-400 font-medium">Question {step + 1} / 8</span>
        </div>

        <AnimatePresence mode="wait">
          <motion.p
            key={current.q}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.24 }}
            className="text-sm font-medium text-[#FAFAFA] mb-5 min-h-[2.5rem]"
          >
            {current.q}
          </motion.p>
        </AnimatePresence>

        {/* Slider */}
        <div>
          <div className="flex justify-between text-xs text-[#3F3F46] mb-2.5">
            <span>Not important</span>
            <span>Critical</span>
          </div>
          <div className="relative h-2 bg-white/[0.05] rounded-full">
            <motion.div
              className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-emerald-600 to-emerald-400"
              animate={{ width: `${(current.weight / 10) * 100}%` }}
              transition={{ duration: 0.55, ease: 'easeOut' }}
            />
            <motion.div
              className="absolute top-1/2 -translate-y-1/2 w-4 h-4 rounded-full bg-emerald-400 border-2 border-[#08080A] shadow-lg shadow-emerald-500/30"
              animate={{ left: `calc(${(current.weight / 10) * 100}% - 8px)` }}
              transition={{ duration: 0.55, ease: 'easeOut' }}
            />
          </div>
          <div className="text-right mt-2 text-xs font-semibold text-emerald-400">{current.weight} / 10</div>
        </div>
      </div>

      {/* Rubric building */}
      <div className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-5">
        <div className="flex items-center gap-2 mb-4">
          <Zap className="w-3.5 h-3.5 text-emerald-400" />
          <span className="text-xs font-medium text-[#A1A1AA]">Rubric building…</span>
          <span className="ml-auto text-xs text-[#52525B]">{done} / 8 criteria</span>
        </div>
        <div className="space-y-2.5 min-h-[60px]">
          <AnimatePresence>
            {INTERVIEW_QS.slice(0, done).map((q) => (
              <motion.div
                key={q.label}
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.3 }}
                className="flex items-center gap-3 overflow-hidden"
              >
                <span className="text-xs text-[#71717A] w-32 shrink-0 truncate">{q.label}</span>
                <div className="flex-1 h-1.5 bg-white/[0.04] rounded-full overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${(q.weight / 10) * 100}%` }}
                    transition={{ duration: 0.6, delay: 0.1 }}
                    className="h-full rounded-full bg-emerald-400/60"
                  />
                </div>
                <span className="text-xs font-semibold text-emerald-400 w-5 text-right shrink-0">{q.weight}</span>
              </motion.div>
            ))}
          </AnimatePresence>
          {done === 0 && (
            <p className="text-xs text-[#3F3F46] italic text-center py-2">Answer questions to build your rubric</p>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Feature 3 visual: live re-ranking ─────────────────────────────────────────
const PRODUCTS = [
  { id: 'xm5',   name: 'Sony WF-1000XM5',          base: 8.4, battery: 6.8 },
  { id: 'app',   name: 'Apple AirPods Pro 2',       base: 8.1, battery: 6.4 },
  { id: 'anker', name: 'Anker Soundcore Liberty 4', base: 7.3, battery: 9.6 },
  { id: 'jabra', name: 'Jabra Evolve2 Buds',        base: 7.0, battery: 9.0 },
]

function RankingVisual({ inView }: { inView: boolean }) {
  const [w, setW] = useState(2)          // battery weight 2→9→2 loop
  const dirRef = useRef(1)

  useEffect(() => {
    if (!inView) return
    const id = setInterval(() => {
      setW(prev => {
        const next = prev + dirRef.current
        if (next >= 9) dirRef.current = -1
        if (next <= 2) dirRef.current = 1
        return next
      })
    }, 320)
    return () => clearInterval(id)
  }, [inView])

  const scored = [...PRODUCTS]
    .map(p => ({ ...p, score: Number(((p.base * (10 - w) + p.battery * w) / 10).toFixed(1)) }))
    .sort((a, b) => b.score - a.score)

  return (
    <div className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-5 overflow-hidden">
      {/* Weight sliders */}
      <div className="mb-5 pb-5 border-b border-white/[0.06]">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-[#A1A1AA] font-medium">Criteria weights</span>
          <span className="text-xs text-[#52525B]">drag to re-rank</span>
        </div>

        {/* Animated battery slider */}
        <div className="flex items-center gap-3 mb-2">
          <span className="text-xs text-[#A1A1AA] w-24 shrink-0">Battery Life</span>
          <div className="relative flex-1 h-2 bg-white/[0.05] rounded-full">
            <motion.div
              className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-amber-600 to-amber-400"
              animate={{ width: `${(w / 10) * 100}%` }}
              transition={{ duration: 0.32, ease: 'easeOut' }}
            />
            <motion.div
              className="absolute top-1/2 -translate-y-1/2 w-3.5 h-3.5 rounded-full bg-amber-400 border-2 border-[#08080A] shadow shadow-amber-500/30"
              animate={{ left: `calc(${(w / 10) * 100}% - 7px)` }}
              transition={{ duration: 0.32, ease: 'easeOut' }}
            />
          </div>
          <span className="text-xs font-bold text-amber-400 w-4 tabular-nums">{w}</span>
        </div>

        {/* Static secondary sliders for visual depth */}
        {[{ label: 'Sound Quality', val: 6 }, { label: 'ANC', val: 5 }].map(s => (
          <div key={s.label} className="flex items-center gap-3 mb-2">
            <span className="text-xs text-[#3F3F46] w-24 shrink-0">{s.label}</span>
            <div className="relative flex-1 h-1.5 bg-white/[0.03] rounded-full">
              <div
                className="absolute inset-y-0 left-0 rounded-full bg-white/[0.10]"
                style={{ width: `${(s.val / 10) * 100}%` }}
              />
            </div>
            <span className="text-xs text-[#3F3F46] w-4">{s.val}</span>
          </div>
        ))}
      </div>

      {/* Ranked product list — reorders with layout animation */}
      <div className="space-y-2">
        {scored.map((p, i) => (
          <motion.div
            key={p.id}
            layout
            transition={{ duration: 0.45, type: 'spring', stiffness: 180, damping: 22 }}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-xl border transition-colors duration-300 ${
              i === 0
                ? 'bg-amber-500/[0.06] border-amber-500/20'
                : 'bg-white/[0.02] border-white/[0.04]'
            }`}
          >
            <span className={`text-xs font-bold w-4 shrink-0 tabular-nums ${i === 0 ? 'text-amber-400' : 'text-[#3F3F46]'}`}>
              {i + 1}
            </span>
            <span className="text-xs text-[#A1A1AA] flex-1 truncate">{p.name}</span>
            <span className={`text-xs font-semibold tabular-nums ${i === 0 ? 'text-amber-400' : 'text-[#71717A]'}`}>
              {p.score}
            </span>
          </motion.div>
        ))}
      </div>

      <motion.p
        animate={inView ? { opacity: [0.3, 0.55, 0.3] } : {}}
        transition={{ repeat: Infinity, duration: 3.5 }}
        className="text-xs text-[#3F3F46] text-center mt-4"
      >
        Rankings update instantly as you adjust weights
      </motion.p>
    </div>
  )
}

// ── Main export ────────────────────────────────────────────────────────────────
export function LearnMoreSection() {
  const s1 = useRef<HTMLDivElement>(null)
  const s2 = useRef<HTMLDivElement>(null)
  const s3 = useRef<HTMLDivElement>(null)
  const iv1 = useInView(s1, { once: true, margin: '-80px' })
  const iv2 = useInView(s2, { once: true, margin: '-80px' })
  const iv3 = useInView(s3, { once: true, margin: '-80px' })

  return (
    <section id="learn-more" className="py-32 border-t border-white/[0.04]">
      <div className="max-w-6xl mx-auto px-4">

        {/* ── Section header ─────────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="text-center mb-24"
        >
          <span className="text-xs font-medium tracking-widest uppercase text-[#52525B]">
            Under the hood
          </span>
          <h2 className="text-4xl sm:text-5xl font-medium tracking-tight text-[#FAFAFA] mt-4 mb-5 leading-tight">
            Three systems.<br className="hidden sm:block" /> One answer.
          </h2>
          <p className="text-[#71717A] max-w-sm mx-auto text-lg leading-relaxed">
            Each layer surfaces signal, filters noise, and finds the right answer for <em>you</em>.
          </p>
        </motion.div>

        {/* ── 1: Community sourced ───────────────────────────────────── */}
        <div id="learn-more-community" ref={s1} className="mb-28 scroll-mt-24">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-20 items-center">

            {/* Text */}
            <motion.div
              initial={{ opacity: 0, x: -24 }}
              animate={iv1 ? { opacity: 1, x: 0 } : {}}
              transition={{ duration: 0.6 }}
            >
              <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-violet-500/10 border border-violet-500/20 text-xs text-violet-300 mb-6">
                <MessagesSquare className="w-3.5 h-3.5" />
                Community sourced
              </div>

              <h3 className="text-3xl sm:text-4xl font-medium tracking-tight text-[#FAFAFA] leading-tight mb-5">
                Real buyers.<br />Real experiences.
              </h3>
              <p className="text-[#71717A] leading-relaxed mb-8 text-base">
                No single review captures the full picture. We fetch 15+ active Reddit discussions,
                cross-reference with expert editorial reviews, and layer in YouTube transcripts —
                then rank every source by freshness, authority, and query relevance before analysis.
              </p>

              {/* Stats */}
              <div className="grid grid-cols-3 gap-3 mb-8">
                {[
                  { n: 15, s: '+', label: 'Reddit threads' },
                  { n: 100, s: '+', label: 'Comments / thread' },
                  { n: 8, s: '', label: 'Review sites' },
                ].map((stat) => (
                  <div
                    key={stat.label}
                    className="rounded-xl bg-white/[0.02] border border-white/[0.06] p-4 text-center"
                  >
                    <div className="text-2xl font-bold text-violet-400">
                      <CountUp to={stat.n} suffix={stat.s} />
                    </div>
                    <div className="text-xs text-[#52525B] mt-1 leading-tight">{stat.label}</div>
                  </div>
                ))}
              </div>

              {/* Steps */}
              <div className="space-y-3.5">
                {PIPELINE_STEPS.map(({ Icon, label, desc }, i) => (
                  <motion.div
                    key={label}
                    initial={{ opacity: 0, x: -10 }}
                    animate={iv1 ? { opacity: 1, x: 0 } : {}}
                    transition={{ delay: 0.2 + i * 0.08, duration: 0.4 }}
                    className="flex items-start gap-3"
                  >
                    <div className="w-6 h-6 rounded-lg bg-violet-500/10 flex items-center justify-center shrink-0 mt-0.5">
                      <Icon className="w-3.5 h-3.5 text-violet-400" />
                    </div>
                    <div>
                      <span className="text-sm font-medium text-[#FAFAFA]">{label}</span>
                      <span className="text-sm text-[#71717A]"> — {desc}</span>
                    </div>
                  </motion.div>
                ))}
              </div>
            </motion.div>

            {/* Visual */}
            <motion.div
              initial={{ opacity: 0, x: 24 }}
              animate={iv1 ? { opacity: 1, x: 0 } : {}}
              transition={{ duration: 0.6, delay: 0.1 }}
            >
              <SourcePipelineVisual inView={iv1} />
            </motion.div>
          </div>
        </div>

        {/* divider */}
        <div className="w-full h-px bg-gradient-to-r from-transparent via-white/[0.06] to-transparent mb-28" />

        {/* ── 2: Fully personalized ──────────────────────────────────── */}
        <div id="learn-more-interview" ref={s2} className="mb-28 scroll-mt-24">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-20 items-center">

            {/* Visual — LEFT on desktop */}
            <motion.div
              initial={{ opacity: 0, x: -24 }}
              animate={iv2 ? { opacity: 1, x: 0 } : {}}
              transition={{ duration: 0.6 }}
              className="order-2 lg:order-1"
            >
              <InterviewVisual inView={iv2} />
            </motion.div>

            {/* Text — RIGHT on desktop */}
            <motion.div
              initial={{ opacity: 0, x: 24 }}
              animate={iv2 ? { opacity: 1, x: 0 } : {}}
              transition={{ duration: 0.6, delay: 0.1 }}
              className="order-1 lg:order-2"
            >
              <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-300 mb-6">
                <Sparkles className="w-3.5 h-3.5" />
                Fully personalized
              </div>

              <h3 className="text-3xl sm:text-4xl font-medium tracking-tight text-[#FAFAFA] leading-tight mb-5">
                A rubric built<br />around you.
              </h3>
              <p className="text-[#71717A] leading-relaxed mb-8 text-base">
                8 targeted questions reveal what you actually care about. Your answers become
                weights on 8–12 scoring dimensions — so a commuter and a gym-goer researching
                the same earbuds get completely different rankings.
              </p>

              <div className="space-y-5">
                {[
                  {
                    title: 'Adaptive questions',
                    body: "Each question targets a dimension your profile hasn't covered yet — no repetition, no wasted time.",
                  },
                  {
                    title: 'Product-specific criteria',
                    body: "Earbuds get 'ANC Effectiveness', gaming mice get 'Click Latency', sunscreen gets 'Photostability' — never generic boilerplate.",
                  },
                  {
                    title: 'Persistent memory',
                    body: "Preferences are saved. Next time you research the same category, your profile pre-fills automatically.",
                  },
                ].map((item, i) => (
                  <motion.div
                    key={item.title}
                    initial={{ opacity: 0, y: 8 }}
                    animate={iv2 ? { opacity: 1, y: 0 } : {}}
                    transition={{ delay: 0.3 + i * 0.1, duration: 0.4 }}
                    className="flex gap-4"
                  >
                    <div className="w-0.5 rounded-full bg-emerald-500/35 shrink-0 self-stretch" />
                    <div>
                      <p className="text-sm font-semibold text-[#FAFAFA] mb-1">{item.title}</p>
                      <p className="text-sm text-[#71717A] leading-relaxed">{item.body}</p>
                    </div>
                  </motion.div>
                ))}
              </div>
            </motion.div>
          </div>
        </div>

        {/* divider */}
        <div className="w-full h-px bg-gradient-to-r from-transparent via-white/[0.06] to-transparent mb-28" />

        {/* ── 3: Live re-ranking ─────────────────────────────────────── */}
        <div id="learn-more-reranking" ref={s3} className="scroll-mt-24">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-20 items-center">

            {/* Text */}
            <motion.div
              initial={{ opacity: 0, x: -24 }}
              animate={iv3 ? { opacity: 1, x: 0 } : {}}
              transition={{ duration: 0.6 }}
            >
              <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-500/10 border border-amber-500/20 text-xs text-amber-300 mb-6">
                <SlidersHorizontal className="w-3.5 h-3.5" />
                Live re-ranking
              </div>

              <h3 className="text-3xl sm:text-4xl font-medium tracking-tight text-[#FAFAFA] leading-tight mb-5">
                Change what matters.<br />Instantly.
              </h3>
              <p className="text-[#71717A] leading-relaxed mb-8 text-base">
                The results page exposes every scoring dimension as a drag slider. Reweighting
                runs client-side in milliseconds — no page reload, no pipeline re-run.
              </p>

              <div className="space-y-3">
                {[
                  'One slider per criterion in your rubric',
                  'Rankings reorder in real-time as you drag',
                  'Reset to interview weights with one click',
                  'Lock a product in place regardless of score',
                  'Share your exact configuration via a link',
                ].map((line, i) => (
                  <motion.div
                    key={line}
                    initial={{ opacity: 0, x: -8 }}
                    animate={iv3 ? { opacity: 1, x: 0 } : {}}
                    transition={{ delay: 0.18 + i * 0.07, duration: 0.35 }}
                    className="flex items-center gap-2.5"
                  >
                    <ChevronRight className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                    <span className="text-sm text-[#A1A1AA]">{line}</span>
                  </motion.div>
                ))}
              </div>
            </motion.div>

            {/* Visual */}
            <motion.div
              initial={{ opacity: 0, x: 24 }}
              animate={iv3 ? { opacity: 1, x: 0 } : {}}
              transition={{ duration: 0.6, delay: 0.1 }}
            >
              <RankingVisual inView={iv3} />
            </motion.div>
          </div>
        </div>

      </div>
    </section>
  )
}
