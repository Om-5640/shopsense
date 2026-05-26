'use client'

import { motion } from 'framer-motion'
import { 
  Check, 
  X, 
  Loader2, 
  Search, 
  Sparkles, 
  MessageSquare,
  SlidersHorizontal,
  Globe,
  FileText,
  Brain,
  Zap
} from 'lucide-react'
import { cn } from '@/lib/utils'

export type StageStatus = 'pending' | 'running' | 'complete' | 'error'

export interface PipelineStage {
  id: string
  name: string
  description?: string
  status: StageStatus
  elapsedTime?: number
  icon: React.ElementType
  iconColor: string
}

const stageIcons = {
  detecting: { icon: Search, color: 'violet' },
  criteria: { icon: Sparkles, color: 'violet' },
  interview: { icon: MessageSquare, color: 'emerald' },
  rubric: { icon: SlidersHorizontal, color: 'amber' },
  reddit: { icon: Globe, color: 'blue' },
  scraping: { icon: FileText, color: 'cyan' },
  summarizing: { icon: Brain, color: 'purple' },
  analyzing: { icon: Zap, color: 'orange' },
  scoring: { icon: Sparkles, color: 'emerald' },
}

interface PipelineTimelineProps {
  stages: PipelineStage[]
  currentStage: string | null
  elapsedTime: number
  query: string
  onCancel: () => void
}

export function PipelineTimeline({ 
  stages, 
  currentStage, 
  elapsedTime, 
  query, 
  onCancel 
}: PipelineTimelineProps) {
  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }
  
  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-start justify-between mb-2">
          <div>
            <h2 className="text-xl font-semibold text-[#FAFAFA] mb-1">Researching</h2>
            <p className="text-sm text-[#A1A1AA] line-clamp-2">{query}</p>
          </div>
          <button
            onClick={onCancel}
            className="p-2 rounded-lg text-[#71717A] hover:text-[#FAFAFA] hover:bg-white/[0.04] transition-colors"
            aria-label="Cancel research"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        
        {/* Elapsed time */}
        <div className="flex items-center gap-2 mt-4">
          <div className="w-2 h-2 rounded-full bg-violet-500 animate-pulse" />
          <span className="font-mono text-2xl text-[#FAFAFA]">{formatTime(elapsedTime)}</span>
        </div>
      </div>
      
      {/* Timeline */}
      <div className="relative flex-1">
        {/* Connecting line */}
        <div className="absolute left-5 top-0 bottom-0 w-0.5 bg-white/[0.06]" />
        
        {/* Progress fill */}
        <motion.div
          className="absolute left-5 top-0 w-0.5 bg-gradient-to-b from-violet-500 to-emerald-500"
          initial={{ height: 0 }}
          animate={{ 
            height: `${(stages.filter(s => s.status === 'complete').length / stages.length) * 100}%` 
          }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
        />
        
        {/* Stages */}
        <div className="space-y-3">
          {stages.map((stage, index) => {
            const isActive = stage.id === currentStage
            const Icon = stage.icon
            
            return (
              <motion.div
                key={stage.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.05 }}
                className={cn(
                  'relative flex items-start gap-4 p-3 rounded-xl transition-all duration-300',
                  isActive && 'bg-white/[0.02] border border-violet-500/30 shadow-glow-sm',
                  stage.status === 'complete' && 'opacity-70',
                  stage.status === 'error' && 'border border-red-500/30'
                )}
              >
                {/* Icon */}
                <div
                  className={cn(
                    'relative z-10 w-10 h-10 rounded-xl flex items-center justify-center shrink-0 transition-all',
                    stage.status === 'pending' && 'bg-white/[0.04]',
                    stage.status === 'running' && `bg-${stage.iconColor}-500/20`,
                    stage.status === 'complete' && 'bg-emerald-500/20',
                    stage.status === 'error' && 'bg-red-500/20'
                  )}
                >
                  {stage.status === 'running' ? (
                    <Loader2 className={cn('w-5 h-5 animate-spin', `text-${stage.iconColor}-400`)} />
                  ) : stage.status === 'complete' ? (
                    <Check className="w-5 h-5 text-emerald-400" />
                  ) : stage.status === 'error' ? (
                    <X className="w-5 h-5 text-red-400" />
                  ) : (
                    <Icon className="w-5 h-5 text-[#71717A]" />
                  )}
                </div>
                
                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-1">
                    <h3 className={cn(
                      'font-medium',
                      stage.status === 'pending' ? 'text-[#71717A]' : 'text-[#FAFAFA]'
                    )}>
                      {stage.name}
                    </h3>
                    {stage.elapsedTime !== undefined && stage.status === 'complete' && (
                      <span className="text-xs font-mono text-[#71717A]">
                        {stage.elapsedTime}s
                      </span>
                    )}
                  </div>
                  {stage.description && (
                    <p className="text-sm text-[#71717A] line-clamp-1">
                      {stage.description}
                    </p>
                  )}
                  {stage.status === 'error' && (
                    <button className="mt-2 text-xs text-red-400 hover:text-red-300 transition-colors">
                      Retry
                    </button>
                  )}
                </div>
              </motion.div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
