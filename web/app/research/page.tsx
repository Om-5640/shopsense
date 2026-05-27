'use client'

import { useState, useEffect, useRef, useCallback, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Search,
  Sparkles,
  MessageSquare,
  SlidersHorizontal,
  Globe,
  FileText,
  Brain,
  Zap,
  Check,
  AlertCircle,
} from 'lucide-react'
import { toast } from 'sonner'
import { AnimatedBackground } from '@/components/layout/animated-background'
import { Header } from '@/components/layout/header'
import { CommandPalette } from '@/components/layout/command-palette'
import {
  PipelineTimeline,
  type PipelineStage,
  type StageStatus,
} from '@/components/research/pipeline-timeline'
import { InterviewChat } from '@/components/research/interview-chat'
import { RubricConfirmation } from '@/components/research/rubric-confirmation'
import { AnalyzerAnimation } from '@/components/research/analyzer-animation'
import { RedditFetchGrid } from '@/components/research/reddit-fetch-grid'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { Criterion, QAEntry, Rubric, MemoryContext, InterviewQuestion } from '@/lib/types'
import {
  detectCategory,
  getCriteria,
  getNextQuestion,
  summarizeInterview,
  generateRubric,
  startSearch,
  cancelSearch,
  saveProfile,
  getProfile,
  getMemoryContext,
} from '@/lib/api'
import { connectSSE } from '@/lib/sse'
import { extractWeights } from '@/lib/rerank'

// ─── Pipeline stage config ────────────────────────────────────────────────────

const INIT_STAGES: PipelineStage[] = [
  { id: 'detecting',   name: 'Detecting category',   status: 'running',  icon: Search,          iconColor: 'violet' },
  { id: 'interview',   name: 'Interview',            status: 'pending',  icon: MessageSquare,   iconColor: 'emerald' },
  { id: 'rubric',      name: 'Building rubric',      status: 'pending',  icon: SlidersHorizontal, iconColor: 'amber' },
  { id: 'reddit',      name: 'Fetching Reddit',      status: 'pending',  icon: Globe,           iconColor: 'blue' },
  { id: 'scraping',    name: 'Scraping reviews',     status: 'pending',  icon: FileText,        iconColor: 'cyan' },
  { id: 'summarizing', name: 'Parallel summarization', status: 'pending', icon: Brain,          iconColor: 'purple' },
  { id: 'analyzing',   name: 'Main analyzer',        status: 'pending',  icon: Zap,             iconColor: 'orange' },
  { id: 'scoring',     name: 'Scoring products',     status: 'pending',  icon: Sparkles,        iconColor: 'emerald' },
]

// SSE stage id → sidebar stage id
const SSE_TO_SIDEBAR: Record<string, string> = {
  reddit_fetch:   'reddit',
  review_fetch:   'scraping',
  summarize:      'summarizing',
  analyze:        'analyzing',
  cross_validate: 'analyzing',
  scoring:        'scoring',
  explanations:   'scoring',
}

// ─── Phase type ───────────────────────────────────────────────────────────────

type Phase =
  | 'detecting'
  | 'disambiguation'
  | 'region'
  | 'profile_choice'
  | 'interview'
  | 'rubric_building'
  | 'rubric_confirm'
  | 'running'
  | 'done'
  | 'error'

// ─── Chat message type ────────────────────────────────────────────────────────

interface ChatMessage {
  id: string
  role: 'assistant' | 'user'
  content: string
  isTyping?: boolean
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function stageStatus(phase: Phase, stageId: string): StageStatus {
  const order = ['detecting', 'interview', 'rubric', 'reddit', 'scraping', 'summarizing', 'analyzing', 'scoring']
  const phaseToStage: Record<Phase, string> = {
    detecting:      'detecting',
    disambiguation: 'detecting',
    region:         'detecting',
    profile_choice: 'interview',
    interview:      'interview',
    rubric_building:'rubric',
    rubric_confirm: 'rubric',
    running:        'reddit',
    done:           'scoring',
    error:          'detecting',
  }
  const current = phaseToStage[phase]
  const ci = order.indexOf(current)
  const si = order.indexOf(stageId)
  if (si < ci) return 'complete'
  if (si === ci) return 'running'
  return 'pending'
}

// ─── Main content ─────────────────────────────────────────────────────────────

function categoryLabel(cat: string) {
  if (!cat) return 'this category'
  return cat.charAt(0).toUpperCase() + cat.slice(1).replace(/[-/]/g, ' > ')
}

function ResearchPageContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const query = searchParams.get('q') ?? ''

  const [commandOpen, setCommandOpen] = useState(false)
  const [phase, setPhase] = useState<Phase>('detecting')
  const [error, setError] = useState<string | null>(null)
  const [elapsedTime, setElapsedTime] = useState(0)

  // Detection state
  const [detection, setDetection] = useState<{
    category: string
    primary_noun: string
    options: { slug: string; label: string }[]
    region: string
    needs_disambiguation: boolean
    needs_region_clarification: boolean
  } | null>(null)
  const [category, setCategory] = useState('')
  const [primaryNoun, setPrimaryNoun] = useState('')
  const [region, setRegion] = useState('india')

  // Interview state
  const [criteria, setCriteria] = useState<Criterion[]>([])
  const [qaHistory, setQaHistory] = useState<QAEntry[]>([])
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [currentQ, setCurrentQ] = useState(0)
  const [totalQ] = useState(8)
  const [waiting, setWaiting] = useState(false)
  const [currentQuestion, setCurrentQuestion] = useState<InterviewQuestion | null>(null)
  const [memCtx, setMemCtx] = useState<MemoryContext | null>(null)
  const [savedProfile, setSavedProfile] = useState<Record<string, unknown> | null>(null)

  // Rubric state
  const [rubric, setRubric] = useState<Rubric | null>(null)
  const [rubricCriteria, setRubricCriteria] = useState<
    Array<{ id: string; label: string; weight: number; rationale: string }>
  >([])

  // Pipeline stages
  const [stages, setStages] = useState<PipelineStage[]>(INIT_STAGES)
  const [redditThreads, setRedditThreads] = useState<
    Array<{ id: string; subreddit: string; title: string; score: number; status: 'pending' | 'fetching' | 'complete'; commentCount?: number }>
  >([])

  const [activeSearchId, setActiveSearchId] = useState<string | null>(null)
  const [stopping, setStopping] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const sseCleanupRef = useRef<(() => void) | null>(null)
  const profileRef = useRef<Record<string, unknown> | null>(null)
  const pendingProfileSetupRef = useRef<{
    cat: string
    reg: string
    pNoun: string
    criteria: Criterion[]
    preQA: QAEntry[]
  } | null>(null)
  const hasInitRef = useRef(false)

  // Redirect if no query
  useEffect(() => {
    if (!query) { router.push('/'); return }
  }, [query, router])

  // Elapsed timer
  useEffect(() => {
    timerRef.current = setInterval(() => setElapsedTime((t) => t + 1), 1000)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [])

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => { sseCleanupRef.current?.() }
  }, [])

  // ── Update a sidebar stage status ──────────────────────────────────────────
  const updateStage = useCallback((id: string, status: StageStatus, description?: string, elapsed?: number) => {
    setStages((prev) =>
      prev.map((s) =>
        s.id === id ? { ...s, status, description: description ?? s.description, elapsedTime: elapsed ?? s.elapsedTime } : s,
      ),
    )
  }, [])

  // ── Load criteria, profile, memory for a category ─────────────────────────
  // preQA: optional pre-answered entries injected from disambiguation choice
  const loadCriteriaAndStart = useCallback(async (cat: string, reg: string, pNoun: string, preQA: QAEntry[] = []) => {
    try {
      updateStage('detecting', 'complete')
      updateStage('interview', 'running')
      setPhase('interview')

      const [{ criteria: crit }, existing, ctx] = await Promise.all([
        getCriteria(cat),
        getProfile(cat).catch(() => null),
        getMemoryContext(query, cat),
      ])
      setCriteria(crit)
      if (ctx.has_memory) setMemCtx(ctx)

      if (existing) {
        // Skip interview — build rubric directly from saved profile
        pendingProfileSetupRef.current = { cat, reg, pNoun, criteria: crit, preQA }
        setSavedProfile(existing)
        setPhase('profile_choice')
      } else {
        // Start interview — seed with any pre-answered QA from disambiguation
        if (preQA.length > 0) setQaHistory(preQA)
        await askNextQuestion(cat, crit, preQA, preQA.length + 1)
      }
    } catch (e) {
      handleError(`Setup failed: ${e instanceof Error ? e.message : e}`)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query])

  // ── Ask next interview question ────────────────────────────────────────────
  async function handleUseSavedProfile() {
    const setup = pendingProfileSetupRef.current
    if (!setup || !savedProfile) return
    const profile: Record<string, unknown> = {
      ...savedProfile,
      category: setup.cat,
      primary_noun: setup.pNoun || setup.cat.split('/').pop() || '',
    }
    setSavedProfile(null)
    pendingProfileSetupRef.current = null
    profileRef.current = profile
    setQaHistory((profile.interview as QAEntry[] | undefined) ?? [])
    setMessages([])
    await buildRubric(setup.cat, setup.criteria, profile, setup.reg)
  }

  async function handleStartFreshInterview() {
    const setup = pendingProfileSetupRef.current
    if (!setup) return
    setSavedProfile(null)
    pendingProfileSetupRef.current = null
    profileRef.current = null
    setQaHistory(setup.preQA)
    setMessages([])
    setCurrentQuestion(null)
    setCurrentQ(setup.preQA.length)
    setPhase('interview')
    await askNextQuestion(setup.cat, setup.criteria, setup.preQA, setup.preQA.length + 1)
  }

  async function askNextQuestion(cat: string, crit: Criterion[], history: QAEntry[], qNum: number) {
    setWaiting(true)
    try {
      const q = await getNextQuestion(cat, crit, history, query)
      setCurrentQuestion(q)
      setCurrentQ(qNum)
      setMessages((prev) => [
        ...prev.map((m) => ({ ...m, isTyping: false })),
        { id: `q-${qNum}-${Date.now()}`, role: 'assistant', content: q.question, isTyping: true },
      ])
      if (q.is_done) {
        await finishInterview(cat, crit, history)
      }
    } catch (e) {
      handleError(`Interview failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      setWaiting(false)
    }
  }

  // ── Handle user answer ────────────────────────────────────────────────────
  async function handleSendMessage(answer: string) {
    if (!currentQuestion || waiting) return
    const entry: QAEntry = {
      question: currentQuestion.question,
      answer,
      why_asked: currentQuestion.why_asking,
      targets_criterion: currentQuestion.targets_criterion,
    }
    const newHistory = [...qaHistory, entry]
    setQaHistory(newHistory)
    setMessages((prev) => [
      ...prev.map((m) => ({ ...m, isTyping: false })),
      { id: `a-${currentQ}`, role: 'user', content: answer },
    ])
    setCurrentQ((n) => n + 1)

    if (currentQuestion.is_done || currentQ >= totalQ) {
      await finishInterview(category, criteria, newHistory)
    } else {
      await askNextQuestion(category, criteria, newHistory, currentQ + 1)
    }
  }

  async function handleSkip() {
    if (waiting) return
    const entry: QAEntry = {
      question: currentQuestion?.question ?? '',
      answer: '[Skipped]',
    }
    const newHistory = [...qaHistory, entry]
    setQaHistory(newHistory)
    setMessages((prev) => [
      ...prev.map((m) => ({ ...m, isTyping: false })),
      { id: `skip-${currentQ}`, role: 'user', content: '[Skipped]' },
    ])
    if (currentQ >= totalQ) {
      await finishInterview(category, criteria, newHistory)
    } else {
      await askNextQuestion(category, criteria, newHistory, currentQ + 1)
    }
  }

  async function finishInterview(cat: string, crit: Criterion[], history: QAEntry[]) {
    setWaiting(true)
    try {
      const { preferences_summary } = await summarizeInterview(cat, history)
      const prof = {
        category: cat,
        primary_noun: primaryNoun || cat.split('/').pop() || '',
        source_query: query,
        interview: history,
        preferences_summary,
        region,
      }
      profileRef.current = prof
      await saveProfile(cat, prof)
      await buildRubric(cat, crit, prof, region)
    } catch (e) {
      handleError(`Interview summary failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      setWaiting(false)
    }
  }

  // ── Build rubric ──────────────────────────────────────────────────────────
  async function buildRubric(cat: string, crit: Criterion[], prof: Record<string, unknown>, reg: string) {
    updateStage('interview', 'complete')
    updateStage('rubric', 'running')
    setPhase('rubric_building')
    try {
      const r = await generateRubric(cat, crit, { ...prof, region: reg })
      setRubric(r)
      const weights = extractWeights(r.weighted_criteria)
      setRubricCriteria(
        r.weighted_criteria.map((c) => ({
          id: c.name,
          label: c.label,
          weight: weights[c.name] ?? c.weight,
          rationale: c.rationale,
        })),
      )
      setPhase('rubric_confirm')
    } catch (e) {
      handleError(`Rubric generation failed: ${e instanceof Error ? e.message : e}`)
    }
  }

  // ── Rubric weight change ──────────────────────────────────────────────────
  function handleRubricWeightChange(id: string, weight: number) {
    setRubricCriteria((prev) => prev.map((c) => (c.id === id ? { ...c, weight } : c)))
  }

  // ── Approve rubric + launch pipeline ─────────────────────────────────────
  async function handleRubricApprove() {
    if (!rubric) return
    const adjustedRubric: Rubric = {
      ...rubric,
      weighted_criteria: rubric.weighted_criteria.map((c) => ({
        ...c,
        weight: rubricCriteria.find((rc) => rc.id === c.name)?.weight ?? c.weight,
      })),
    }
    updateStage('rubric', 'complete')
    updateStage('reddit', 'running')
    setPhase('running')

    try {
      const { search_id } = await startSearch({
        query,
        category,
        region,
        profile: profileRef.current ?? {},
        rubric: adjustedRubric,
        qa_history: qaHistory,
        primary_noun: primaryNoun || category.split('/').pop() || '',
      })
      setActiveSearchId(search_id)
      // Persist so the user can rejoin from history/home if they navigate away
      try { localStorage.setItem('shopsense_active_search', JSON.stringify({ id: search_id, query, ts: Date.now() })) } catch { /* ignore */ }
      sseCleanupRef.current = connectSSE(search_id, {
        onStageStart(stage) {
          const sid = SSE_TO_SIDEBAR[stage] ?? stage
          updateStage(sid, 'running')
          if (sid === 'reddit') {
            // seed placeholder threads
            setRedditThreads(
              Array.from({ length: 9 }, (_, i) => ({
                id: String(i + 1),
                subreddit: 'loading…',
                title: 'Fetching thread…',
                score: 0,
                status: i < 3 ? 'fetching' : 'pending',
              })),
            )
          }
        },
        onStageDone(stage, count) {
          const sid = SSE_TO_SIDEBAR[stage] ?? stage
          updateStage(sid, 'complete', count !== undefined ? `${count} found` : undefined)
          if (sid === 'reddit') {
            setRedditThreads((prev) => prev.map((t) => ({ ...t, status: 'complete' })))
          }
        },
        onProgress(stage, current, total) {
          const sid = SSE_TO_SIDEBAR[stage] ?? stage
          updateStage(sid, 'running', total ? `${current}/${total}` : undefined)
          if (sid === 'reddit' || stage === 'reddit_fetch') {
            setRedditThreads((prev) =>
              prev.map((t, i) => ({
                ...t,
                status: i < current ? 'complete' : i === current ? 'fetching' : 'pending',
              })),
            )
          }
        },
        onError(message) {
          handleError(message)
        },
        onDone() {
          setPhase('done')
          try { localStorage.removeItem('shopsense_active_search') } catch { /* ignore */ }
          router.push(`/results/${search_id}`)
        },
      })
    } catch (e) {
      handleError(`Failed to start search: ${e instanceof Error ? e.message : e}`)
    }
  }

  // ── Stop / cancel handler ─────────────────────────────────────────────────
  async function handleStop() {
    if (!activeSearchId || stopping) return
    setStopping(true)
    try {
      sseCleanupRef.current?.()
      await cancelSearch(activeSearchId)
      try { localStorage.removeItem('shopsense_active_search') } catch { /* ignore */ }
      toast.info('Research stopped.')
      setPhase('error')
      setError(`Research stopped. Partial results may be available at /results/${activeSearchId}`)
    } catch {
      toast.error('Could not stop research — try again.')
    } finally {
      setStopping(false)
    }
  }

  // ── Error handler ─────────────────────────────────────────────────────────
  function handleError(msg: string) {
    setError(msg)
    setPhase('error')
    toast.error(msg)
    sseCleanupRef.current?.()
  }

  // ── Run detection on mount ────────────────────────────────────────────────
  useEffect(() => {
    if (!query) return
    // Guard against React StrictMode double-invocation
    if (hasInitRef.current) return
    hasInitRef.current = true
    ;(async () => {
      try {
        const d = await detectCategory(query)
        setDetection(d)
        if (d.needs_disambiguation) {
          setPhase('disambiguation')
        } else if (d.needs_region_clarification) {
          setCategory(d.category)
          setPrimaryNoun(d.primary_noun ?? '')
          setPhase('region')
        } else {
          const reg = d.region !== 'global' ? d.region : 'india'
          setCategory(d.category)
          setPrimaryNoun(d.primary_noun ?? '')
          setRegion(reg)
          await loadCriteriaAndStart(d.category, reg, d.primary_noun ?? '')
        }
      } catch (e) {
        handleError(`Category detection failed: ${e instanceof Error ? e.message : e}`)
      }
    })()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query])

  // ── Compute sidebar stage list with live statuses ─────────────────────────
  const liveStages: PipelineStage[] = stages.map((s) => {
    if (phase === 'running' || phase === 'done') return s // SSE drives these
    return { ...s, status: stageStatus(phase, s.id) }
  })

  // ── Right panel content ───────────────────────────────────────────────────
  const renderContent = () => {
    if (phase === 'error') {
      const isStopped = error?.includes('stopped')
      return (
        <motion.div
          key="error"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className={`rounded-2xl border p-8 ${isStopped ? 'bg-amber-500/5 border-amber-500/20' : 'bg-rose-500/5 border-rose-500/20'}`}
        >
          <div className="flex items-center gap-3 mb-3">
            <AlertCircle className={`w-5 h-5 ${isStopped ? 'text-amber-400' : 'text-rose-400'}`} />
            <h3 className={`text-lg font-semibold ${isStopped ? 'text-amber-400' : 'text-rose-400'}`}>
              {isStopped ? 'Research stopped' : 'Something went wrong'}
            </h3>
          </div>
          <p className="text-[#A1A1AA] mb-6">{isStopped ? 'The pipeline was stopped before completing.' : error}</p>
          <div className="flex flex-wrap gap-3">
            {isStopped && activeSearchId && (
              <Button
                variant="ghost"
                onClick={() => router.push(`/results/${activeSearchId}`)}
                className="text-amber-300 hover:text-amber-200 border border-amber-500/20 hover:border-amber-500/40"
              >
                View partial results →
              </Button>
            )}
            <Button variant="ghost" onClick={() => router.push('/')} className="text-[#A1A1AA]">
              ← New search
            </Button>
          </div>
        </motion.div>
      )
    }

    if (phase === 'detecting') {
      return (
        <motion.div
          key="detecting"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-8"
        >
          <div className="flex items-center gap-3">
            <div className="w-5 h-5 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-[#A1A1AA]">Analyzing your query…</span>
          </div>
        </motion.div>
      )
    }

    if (phase === 'disambiguation' && detection?.options) {
      return (
        <motion.div
          key="disambiguation"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-8"
        >
          <h3 className="text-lg font-semibold text-[#FAFAFA] mb-2">Which type did you mean?</h3>
          <p className="text-[#71717A] mb-6">Your query could refer to different product types.</p>
          <div className="space-y-2">
            {detection.options.map((opt) => (
              <button
                key={opt.slug}
                onClick={async () => {
                  const reg = detection.region !== 'global' ? detection.region : region
                  setCategory(opt.slug)
                  setPrimaryNoun(detection.primary_noun ?? '')
                  setRegion(reg)
                  // Inject the user's type choice so the interview doesn't ask it again
                  const preQA: QAEntry[] = [{
                    question: 'What type are you looking for?',
                    answer: opt.label,
                    why_asked: 'Chosen during disambiguation',
                    targets_criterion: 'type',
                  }]
                  if (detection.needs_region_clarification && detection.region === 'global') {
                    setQaHistory(preQA)
                    setPhase('region')
                  } else {
                    await loadCriteriaAndStart(opt.slug, reg, detection.primary_noun ?? '', preQA)
                  }
                }}
                className="w-full text-left px-4 py-3.5 rounded-xl border border-white/[0.07] hover:border-violet-500/30 hover:bg-violet-500/5 transition-all group"
              >
                <div className="font-medium text-[#A1A1AA] group-hover:text-[#FAFAFA]">{opt.label}</div>
                <div className="text-xs text-[#52525B] font-mono mt-0.5">{opt.slug}</div>
              </button>
            ))}
          </div>
        </motion.div>
      )
    }

    if (phase === 'region') {
      return (
        <motion.div
          key="region"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-8"
        >
          <h3 className="text-lg font-semibold text-[#FAFAFA] mb-2">Which region are you shopping in?</h3>
          <p className="text-[#71717A] mb-6">No currency detected — pick the right stores.</p>
          <div className="grid grid-cols-2 gap-2">
            {[
              { key: 'india',     label: 'India (₹)' },
              { key: 'usa',       label: 'USA ($)' },
              { key: 'uk',        label: 'UK (£)' },
              { key: 'europe',    label: 'Europe (€)' },
              { key: 'canada',    label: 'Canada (C$)' },
              { key: 'australia', label: 'Australia (A$)' },
            ].map((r) => (
              <button
                key={r.key}
                onClick={async () => {
                  setRegion(r.key)
                  // qaHistory may already contain disambiguation pre-answers
                  await loadCriteriaAndStart(category, r.key, primaryNoun, qaHistory)
                }}
                className="px-4 py-3 rounded-xl border border-white/[0.07] hover:border-violet-500/30 hover:bg-violet-500/5 text-sm text-[#A1A1AA] transition-all"
              >
                {r.label}
              </button>
            ))}
          </div>
        </motion.div>
      )
    }

    if (phase === 'profile_choice' && savedProfile) {
      const savedAnswers = Array.isArray(savedProfile.interview) ? savedProfile.interview.length : 0
      const savedSummary =
        typeof savedProfile.preferences_summary === 'string'
          ? savedProfile.preferences_summary
          : 'Saved answers are available for this category.'

      return (
        <motion.div
          key="profile_choice"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-8"
        >
          <h3 className="text-lg font-semibold text-[#FAFAFA] mb-2">Use your saved answers?</h3>
          <p className="text-[#A1A1AA] mb-5">
            I found previous feedback for {categoryLabel(category || pendingProfileSetupRef.current?.cat || 'this category')}.
            You can reuse it or answer fresh questions for this search.
          </p>
          <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-4 mb-6">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-[#FAFAFA]">Saved feedback</span>
              <Badge variant="outline" className="border-white/[0.1] text-[#A1A1AA]">
                {savedAnswers} answers
              </Badge>
            </div>
            <p className="text-sm text-[#A1A1AA] line-clamp-4 whitespace-pre-line">{savedSummary}</p>
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            <Button onClick={handleUseSavedProfile} className="h-12 bg-violet-600 hover:bg-violet-500">
              <Check className="w-4 h-4 mr-2" />
              Use saved feedback
            </Button>
            <Button
              variant="ghost"
              onClick={handleStartFreshInterview}
              className="h-12 border border-white/[0.08] text-[#FAFAFA] hover:bg-white/[0.05]"
            >
              <MessageSquare className="w-4 h-4 mr-2" />
              Answer again
            </Button>
          </div>
        </motion.div>
      )
    }

    if (phase === 'interview') {
      return (
        <motion.div
          key="interview"
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -20 }}
          transition={{ duration: 0.2 }}
        >
          {memCtx?.has_memory && (
            <div className="mb-4 p-4 rounded-xl border border-violet-500/20 bg-violet-500/5 flex items-start gap-3">
              <Brain className="w-4 h-4 text-violet-400 mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-medium text-violet-300 mb-1">From your history</p>
                <ul className="space-y-0.5">
                  {memCtx.signals.slice(0, 3).map((s) => (
                    <li key={s.id} className="text-xs text-[#A1A1AA]">· {s.text}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          <InterviewChat
            currentQuestion={currentQ}
            totalQuestions={totalQ}
            messages={messages}
            onSendMessage={handleSendMessage}
            onSkip={handleSkip}
            isWaitingForResponse={waiting}
          />
        </motion.div>
      )
    }

    if (phase === 'rubric_building') {
      return (
        <motion.div
          key="rubric_building"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-8"
        >
          <div className="flex items-center gap-3">
            <div className="w-5 h-5 border-2 border-amber-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-[#A1A1AA]">Building your personalized rubric…</span>
          </div>
        </motion.div>
      )
    }

    if (phase === 'rubric_confirm' && rubricCriteria.length > 0) {
      return (
        <motion.div
          key="rubric_confirm"
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -20 }}
          transition={{ duration: 0.2 }}
          className="h-[calc(100vh-180px)]"
        >
          <RubricConfirmation
            criteria={rubricCriteria}
            onWeightChange={handleRubricWeightChange}
            onApprove={handleRubricApprove}
          />
        </motion.div>
      )
    }

    if (phase === 'running') {
      const showReddit = stages.find((s) => s.id === 'reddit')?.status === 'running'
      return (
        <motion.div
          key="running"
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.2 }}
          className="space-y-4"
        >
          {showReddit && redditThreads.length > 0 ? (
            <RedditFetchGrid threads={redditThreads} />
          ) : (
            <AnalyzerAnimation />
          )}
          <div className="flex justify-end pt-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={handleStop}
              disabled={stopping}
              className="text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 border border-rose-500/20 hover:border-rose-500/40 transition-all"
            >
              {stopping ? (
                <>
                  <div className="w-3.5 h-3.5 border border-rose-400 border-t-transparent rounded-full animate-spin mr-2" />
                  Stopping…
                </>
              ) : (
                'Stop Research'
              )}
            </Button>
          </div>
        </motion.div>
      )
    }

    if (phase === 'done') {
      return (
        <motion.div
          key="done"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-2xl bg-emerald-500/5 border border-emerald-500/20 p-8 text-center"
        >
          <Check className="w-10 h-10 text-emerald-400 mx-auto mb-3" />
          <p className="text-[#FAFAFA] font-medium">Complete — loading results…</p>
        </motion.div>
      )
    }

    return (
      <div className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-8">
        <div className="flex items-center gap-3">
          <div className="w-5 h-5 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-[#A1A1AA]">Processing…</span>
        </div>
      </div>
    )
  }

  if (!query) return null

  return (
    <div className="min-h-screen flex flex-col bg-[#08080A]">
      <AnimatedBackground />
      <Header onOpenCommandPalette={() => setCommandOpen(true)} />
      <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} />

      <main className="flex-1 relative z-10">
        <div className="max-w-7xl mx-auto px-4 py-8">
          {/* Category / region chips */}
          {(category || phase !== 'detecting') && (
            <div className="flex items-center gap-2 mb-6 flex-wrap">
              {category && (
                <Badge className="bg-violet-500/20 text-violet-300 border-violet-500/30 capitalize">
                  {category.replace('/', ' › ')}
                </Badge>
              )}
              {region && region !== 'global' && (
                <Badge variant="outline" className="border-white/[0.1] text-[#71717A] capitalize">
                  {region}
                </Badge>
              )}
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-[350px_1fr] gap-8">
            {/* Left — Pipeline timeline */}
            <div className="lg:sticky lg:top-[76px] lg:h-[calc(100vh-108px)]">
              <PipelineTimeline
                stages={liveStages}
                currentStage={
                  liveStages.find((s) => s.status === 'running')?.id ?? null
                }
                elapsedTime={elapsedTime}
                query={query}
                onCancel={() => router.push('/')}
              />
            </div>

            {/* Right — Stage content */}
            <div className="min-h-[500px]">
              <AnimatePresence mode="wait">
                {renderContent()}
              </AnimatePresence>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

export default function ResearchPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-[#08080A]">
          <div className="w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <ResearchPageContent />
    </Suspense>
  )
}
