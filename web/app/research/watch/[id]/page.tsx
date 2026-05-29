'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { Sparkles, MessageSquare, SlidersHorizontal, Globe, FileText, Brain, Zap, Search, AlertCircle, CheckCircle } from 'lucide-react'
import { toast } from 'sonner'
import { AnimatedBackground } from '@/components/layout/animated-background'
import { Header } from '@/components/layout/header'
import { PipelineTimeline, type PipelineStage, type StageStatus } from '@/components/research/pipeline-timeline'
import { AnalyzerAnimation } from '@/components/research/analyzer-animation'
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
  reddit_fetch:   'reddit',
  review_fetch:   'scraping',
  summarize:      'summarizing',
  analyze:        'analyzing',
  cross_validate: 'analyzing',
  scoring:        'scoring',
  explanations:   'scoring',
}

export default function WatchPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()

  const [stages, setStages] = useState<PipelineStage[]>(INIT_STAGES)
  const [elapsedTime, setElapsedTime] = useState(0)
  const [status, setStatus] = useState<'loading' | 'running' | 'done' | 'error' | 'cancelled' | 'already_done'>('loading')
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [stopping, setStopping] = useState(false)

  const sseCleanupRef = useRef<(() => void) | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const updateStage = useCallback((sid: string, st: StageStatus, description?: string) => {
    setStages((prev) => prev.map((s) => s.id === sid ? { ...s, status: st, description: description ?? s.description } : s))
  }, [])

  useEffect(() => {
    timerRef.current = setInterval(() => setElapsedTime((t) => t + 1), 1000)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [])

  useEffect(() => {
    return () => { sseCleanupRef.current?.() }
  }, [])

  useEffect(() => {
    if (!id) return
    // Check current DB status first
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
        // Connect SSE in reconnect mode to replay missed events
        setStatus('running')
        sseCleanupRef.current = connectSSE(id, {
          onStageStart(stage) {
            const s = SSE_TO_SIDEBAR[stage] ?? stage
            updateStage(s, 'running')
          },
          onStageDone(stage, count) {
            const s = SSE_TO_SIDEBAR[stage] ?? stage
            updateStage(s, 'complete', count !== undefined ? `${count} found` : undefined)
          },
          onProgress(stage, current, total) {
            const s = SSE_TO_SIDEBAR[stage] ?? stage
            updateStage(s, 'running', total ? `${current}/${total}` : undefined)
          },
          onError(message) {
            setError(message)
            setStatus('error')
            toast.error(message)
          },
          onDone() {
            setStatus('done')
            try { localStorage.removeItem('shopsense_active_search') } catch { /* ignore */ }
            setTimeout(() => router.push(`/results/${id}`), 800)
          },
          onWarning() {
            toast.warning('Research data trimmed', {
              id: 'token-budget-warning',
              description: 'Some context was trimmed to fit AI token limits. Results may be slightly less comprehensive.',
              duration: 8000,
            })
          },
        }, /* reconnect */ true)
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
                Live
              </Badge>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-[350px_1fr] gap-8">
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

            {/* Right — Status content */}
            <div className="min-h-[400px]">
              {status === 'loading' && (
                <div className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-8 flex items-center gap-3">
                  <div className="w-5 h-5 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
                  <span className="text-[#A1A1AA]">Connecting to research session…</span>
                </div>
              )}

              {status === 'running' && (
                <motion.div
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="space-y-4"
                >
                  <AnalyzerAnimation />
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
              )}

              {status === 'done' && (
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="rounded-2xl bg-emerald-500/5 border border-emerald-500/20 p-8 text-center"
                >
                  <CheckCircle className="w-10 h-10 text-emerald-400 mx-auto mb-3" />
                  <p className="text-[#FAFAFA] font-medium">Complete — loading results…</p>
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
