'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { Sparkles, MessageSquare, SlidersHorizontal, Globe, FileText, Brain, Zap, Search, AlertCircle, CheckCircle } from 'lucide-react'
import { toast } from 'sonner'
import { AnimatedBackground } from '@/components/layout/animated-background'
import { Header } from '@/components/layout/header'
import { PipelineTimeline, type PipelineStage, type StageStatus } from '@/components/research/pipeline-timeline'
import { ResearchLiveFeed, type ActivityEntry, type ActivityAccent } from '@/components/research/research-live-feed'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cancelSearch, getSearchResult } from '@/lib/api'
import { connectSSE } from '@/lib/sse'

const INIT_STAGES: PipelineStage[] = [
  { id: 'detecting',   name: 'Detecting category',     status: 'complete', icon: Search,            iconColor: 'violet' },
  { id: 'interview',   name: 'Interview',               status: 'complete', icon: MessageSquare,     iconColor: 'emerald' },
  { id: 'rubric',      name: 'Building rubric',         status: 'complete', icon: SlidersHorizontal, iconColor: 'amber' },
  { id: 'reddit',      name: 'Fetching Reddit',         status: 'pending',  icon: Globe,             iconColor: 'blue' },
  { id: 'scraping',    name: 'Scraping reviews',        status: 'pending',  icon: FileText,          iconColor: 'cyan' },
  { id: 'summarizing', name: 'Parallel summarization',  status: 'pending',  icon: Brain,             iconColor: 'purple' },
  { id: 'analyzing',   name: 'Main analyzer',           status: 'pending',  icon: Zap,               iconColor: 'orange' },
  { id: 'scoring',     name: 'Scoring products',        status: 'pending',  icon: Sparkles,          iconColor: 'emerald' },
]

const SSE_TO_SIDEBAR: Record<string, string> = {
  reddit_fetch:     'reddit',
  review_fetch:     'scraping',
  summarize:        'summarizing',
  analyze:          'analyzing',
  cross_validate:   'analyzing',
  mention_counting: 'analyzing',
  scoring:          'scoring',
  explanations:     'scoring',
}

const STAGE_LABELS: Record<string, string> = {
  reddit_fetch:     'Reddit Research',
  review_fetch:     'Expert Reviews',
  summarize:        'Thread Summarization',
  analyze:          'Main Analysis',
  cross_validate:   'Cross-validation',
  mention_counting: 'Mention Analysis',
  constraint_filter:'Constraint Filter',
  scoring:          'Product Scoring',
  explanations:     'Writing Explanations',
}

export default function WatchPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()

  // Pipeline timeline state
  const [stages, setStages] = useState<PipelineStage[]>(INIT_STAGES)
  const [elapsedTime, setElapsedTime] = useState(0)
  const [status, setStatus] = useState<'loading' | 'running' | 'done' | 'error' | 'cancelled' | 'already_done'>('loading')
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [stopping, setStopping] = useState(false)

  // Live feed state
  const [liveStageLabel, setLiveStageLabel] = useState('Initializing…')
  const [liveSubreddits, setLiveSubreddits] = useState<Array<{ name: string; count: number }>>([])
  const [liveReviewDomains, setLiveReviewDomains] = useState<string[]>([])
  const [liveProgressItem, setLiveProgressItem] = useState('')
  const [liveProgressFrac, setLiveProgressFrac] = useState(0)
  const [liveActivity, setLiveActivity] = useState<ActivityEntry[]>([])

  const sseCleanupRef = useRef<(() => void) | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const elapsedRef = useRef(0)
  const activityCounterRef = useRef(0)

  const addActivity = useCallback((text: string, accent: ActivityAccent = 'dim') => {
    const secs = elapsedRef.current
    setLiveActivity((prev) => {
      const entry: ActivityEntry = { id: activityCounterRef.current++, secs, text, accent }
      return [...prev.slice(-99), entry]
    })
  }, [])

  const updateStage = useCallback((sid: string, st: StageStatus, description?: string) => {
    setStages((prev) => prev.map((s) => s.id === sid ? { ...s, status: st, description: description ?? s.description } : s))
  }, [])

  useEffect(() => {
    timerRef.current = setInterval(() => {
      setElapsedTime((t) => {
        elapsedRef.current = t + 1
        return t + 1
      })
    }, 1000)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [])

  useEffect(() => {
    return () => { sseCleanupRef.current?.() }
  }, [])

  useEffect(() => {
    if (!id) return
    getSearchResult(id)
      .then((row) => {
        setQuery(row.query ?? '')
        if (row.status === 'done') {
          setStatus('already_done')
          return
        }
        if (row.status === 'cancelled') {
          setStatus('cancelled')
          return
        }
        setStatus('running')
        sseCleanupRef.current = connectSSE(id, {
          onStageStart(stage, label) {
            const s = SSE_TO_SIDEBAR[stage] ?? stage
            updateStage(s, 'running')
            setLiveStageLabel(label || STAGE_LABELS[stage] || stage)
            setLiveProgressItem('')
            setLiveProgressFrac(0)
            addActivity(`${label || STAGE_LABELS[stage] || stage}…`, 'amber')
          },
          onStageDone(stage, count) {
            const s = SSE_TO_SIDEBAR[stage] ?? stage
            updateStage(s, 'complete', count !== undefined ? `${count} found` : undefined)
            const lbl = STAGE_LABELS[stage] ?? stage
            if (count !== undefined) {
              addActivity(`${lbl}: ${count} found`, 'emerald')
            } else {
              addActivity(`${lbl} complete`, 'emerald')
            }
          },
          onProgress(stage, current, total, detail) {
            const s = SSE_TO_SIDEBAR[stage] ?? stage
            updateStage(s, 'running', total ? `${current}/${total}` : undefined)
            if (detail) setLiveProgressItem(detail)
            if (total && total > 0) setLiveProgressFrac(current / total)
          },
          onLog(msg) {
            if (msg.startsWith('[sources] ')) {
              try {
                const data = JSON.parse(msg.slice('[sources] '.length)) as Array<[string, number]>
                const subs = data.map(([name, count]) => ({ name, count }))
                setLiveSubreddits(subs)
                const preview = subs.slice(0, 3).map((s) => `r/${s.name}`).join(', ')
                addActivity(
                  `${subs.length} subreddits: ${preview}${subs.length > 3 ? ` +${subs.length - 3} more` : ''}`,
                  'orange',
                )
              } catch { /* ignore */ }
            } else if (msg.startsWith('[reviews] ')) {
              try {
                const domains = JSON.parse(msg.slice('[reviews] '.length)) as string[]
                setLiveReviewDomains(domains)
                const preview = domains.slice(0, 3).join(', ')
                addActivity(
                  `${domains.length} review sites: ${preview}${domains.length > 3 ? ` +${domains.length - 3} more` : ''}`,
                  'cyan',
                )
              } catch { /* ignore */ }
            } else if (msg.startsWith('[dedup] ')) {
              addActivity(msg.slice('[dedup] '.length), 'dim')
            } else if (msg.startsWith('[retrieval] ')) {
              addActivity(msg.slice('[retrieval] '.length), 'violet')
            }
          },
          onCacheHit() {
            setStages((prev) => prev.map((s) =>
              ['reddit', 'scraping', 'summarizing', 'analyzing', 'scoring'].includes(s.id)
                ? { ...s, status: 'complete' }
                : s
            ))
            setLiveStageLabel('Loaded from cache')
            addActivity('Results loaded from cache', 'emerald')
            toast.success('Loaded from cache', {
              description: 'Results are from a recent identical search.',
              duration: 3000,
            })
          },
          onError(message) {
            setError(message)
            setStatus('error')
            addActivity(`Error: ${message}`, 'dim')
            toast.error(message)
          },
          onDone(_sid, _fromCache, warnings) {
            setStatus('done')
            setLiveStageLabel('Research complete')
            setLiveProgressItem('')
            addActivity('Research complete — loading results…', 'emerald')
            try { localStorage.removeItem('shopsense_active_search') } catch { /* ignore */ }
            if (warnings && warnings.length > 0) {
              warnings.forEach((w, i) => {
                setTimeout(() => {
                  toast.warning(w, { duration: 12000, id: `provider-warning-${i}` })
                }, i * 300)
              })
            }
            setTimeout(() => router.push(`/results/${id}`), 800)
          },
          onWarning() {
            toast.warning('Research data trimmed', {
              id: 'token-budget-warning',
              description: 'Some context was trimmed to fit AI token limits. Results may be slightly less comprehensive.',
              duration: 8000,
            })
          },
          onReconnecting(attempt) {
            addActivity(`Reconnecting… (attempt ${attempt})`, 'dim')
          },
        })
      })
      .catch(() => {
        setError('Could not load this search session. It may have expired.')
        setStatus('error')
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  async function handleStop() {
    if (stopping) return
    setStopping(true)
    try {
      sseCleanupRef.current?.()
      await cancelSearch(id)
      try { localStorage.removeItem('shopsense_active_search') } catch { /* ignore */ }
      toast.info('Research stopped.')
      setStatus('cancelled')
    } catch {
      toast.error('Could not stop research.')
    } finally {
      setStopping(false)
    }
  }

  const currentStage = stages.find((s) => s.status === 'running')?.id ?? null

  return (
    <div className="min-h-screen flex flex-col bg-[#08080A]">
      <AnimatedBackground />
      <Header onOpenCommandPalette={() => {}} />

      <main className="flex-1 relative z-10">
        <div className="max-w-7xl mx-auto px-4 py-8">
          {query && (
            <div className="flex items-center gap-2 mb-6">
              <Badge className="bg-violet-500/20 text-violet-300 border-violet-500/30">
                {query}
              </Badge>
              <Badge variant="outline" className="border-white/[0.1] text-[#71717A]">
                {status === 'running' ? 'Live' : status === 'done' ? 'Complete' : status}
              </Badge>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-6">
            {/* Left — Pipeline timeline */}
            <div className="lg:sticky lg:top-[76px] lg:h-[calc(100vh-108px)]">
              <PipelineTimeline
                stages={stages}
                currentStage={currentStage}
                elapsedTime={elapsedTime}
                query={query}
                onCancel={() => router.push('/')}
              />
            </div>

            {/* Right — Live research feed or status content */}
            <div className="min-h-[400px]">
              {status === 'loading' && (
                <div className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-8 flex items-center gap-3">
                  <div className="w-5 h-5 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
                  <span className="text-[#A1A1AA]">Connecting to research session…</span>
                </div>
              )}

              {(status === 'running' || status === 'done') && (
                <motion.div
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.3 }}
                >
                  <ResearchLiveFeed
                    stageLabel={liveStageLabel}
                    subreddits={liveSubreddits}
                    reviewDomains={liveReviewDomains}
                    progressItem={liveProgressItem}
                    progressFrac={liveProgressFrac}
                    activity={liveActivity}
                    elapsedTime={elapsedTime}
                    onStop={handleStop}
                    stopping={stopping}
                  />
                </motion.div>
              )}

              {status === 'already_done' && (
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="rounded-2xl bg-violet-500/5 border border-violet-500/20 p-8"
                >
                  <CheckCircle className="w-8 h-8 text-violet-400 mb-3" />
                  <h3 className="text-lg font-semibold text-[#FAFAFA] mb-2">Research complete</h3>
                  <p className="text-[#A1A1AA] mb-6">This search finished. View the full results below.</p>
                  <Button onClick={() => router.push(`/results/${id}`)} className="bg-violet-600 hover:bg-violet-500">
                    View Results →
                  </Button>
                </motion.div>
              )}

              {(status === 'error' || status === 'cancelled') && (
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={`rounded-2xl border p-8 ${status === 'cancelled' ? 'bg-amber-500/5 border-amber-500/20' : 'bg-rose-500/5 border-rose-500/20'}`}
                >
                  <AlertCircle className={`w-8 h-8 mb-3 ${status === 'cancelled' ? 'text-amber-400' : 'text-rose-400'}`} />
                  <h3 className={`text-lg font-semibold mb-2 ${status === 'cancelled' ? 'text-amber-400' : 'text-rose-400'}`}>
                    {status === 'cancelled' ? 'Research stopped' : 'Something went wrong'}
                  </h3>
                  <p className="text-[#A1A1AA] mb-6">
                    {status === 'cancelled' ? 'Partial results may still be available.' : error}
                  </p>
                  <div className="flex gap-3">
                    <Button
                      variant="ghost"
                      onClick={() => router.push(`/results/${id}`)}
                      className={status === 'cancelled' ? 'text-amber-300 border border-amber-500/20' : 'text-[#A1A1AA]'}
                    >
                      View partial results →
                    </Button>
                    <Button variant="ghost" onClick={() => router.push('/')} className="text-[#A1A1AA]">
                      ← New search
                    </Button>
                  </div>
                </motion.div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
