'use client'

import { motion } from 'framer-motion'
import { Slider } from '@/components/ui/slider'
import { Button } from '@/components/ui/button'
import { Info, ShieldCheck, Ban, Wallet, CheckCircle2 } from 'lucide-react'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type { UserIntent } from '@/lib/types'

interface RubricCriterion {
  id: string
  label: string
  weight: number
  rationale: string
}

interface RubricConfirmationProps {
  criteria: RubricCriterion[]
  onWeightChange: (id: string, weight: number) => void
  onApprove: () => void
  intent?: UserIntent
}

function IntentSummary({ intent }: { intent: UserIntent }) {
  const hasBudget = !!intent.budget
  const hasConstraints = intent.hard_constraints.length > 0
  const hasExclusions = intent.exclusions.length > 0
  const hasPreferences = intent.preferences.length > 0

  if (!hasBudget && !hasConstraints && !hasExclusions && !hasPreferences) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="mb-5 rounded-xl border border-violet-500/25 bg-violet-500/[0.06] overflow-hidden"
    >
      <div className="px-4 pt-3 pb-1 flex items-center gap-2 border-b border-violet-500/15">
        <CheckCircle2 className="w-3.5 h-3.5 text-violet-400 shrink-0" />
        <span className="text-xs font-medium text-violet-300 tracking-wide">
          What I understood from your answers
        </span>
      </div>
      <div className="px-4 py-3 space-y-2.5">
        {hasBudget && (
          <div className="flex items-start gap-3">
            <Wallet className="w-3.5 h-3.5 text-amber-400 mt-0.5 shrink-0" />
            <div className="flex flex-wrap gap-1">
              <span className="px-2 py-0.5 rounded-md bg-amber-500/15 border border-amber-500/25 text-amber-200 text-xs font-medium">
                {intent.budget}
              </span>
            </div>
          </div>
        )}
        {hasConstraints && (
          <div className="flex items-start gap-3">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 mt-0.5 shrink-0" />
            <div className="flex flex-wrap gap-1">
              {intent.hard_constraints.slice(0, 5).map((c, i) => (
                <span
                  key={i}
                  className="px-2 py-0.5 rounded-md bg-emerald-500/12 border border-emerald-500/25 text-emerald-300 text-xs"
                >
                  {c}
                </span>
              ))}
            </div>
          </div>
        )}
        {hasExclusions && (
          <div className="flex items-start gap-3">
            <Ban className="w-3.5 h-3.5 text-rose-400 mt-0.5 shrink-0" />
            <div className="flex flex-wrap gap-1">
              {intent.exclusions.slice(0, 4).map((e, i) => (
                <span
                  key={i}
                  className="px-2 py-0.5 rounded-md bg-rose-500/12 border border-rose-500/25 text-rose-300 text-xs"
                >
                  {e}
                </span>
              ))}
            </div>
          </div>
        )}
        {!hasConstraints && !hasExclusions && hasPreferences && (
          <div className="flex flex-wrap gap-1">
            {intent.preferences.slice(0, 4).map((p, i) => (
              <span
                key={i}
                className="px-2 py-0.5 rounded-md bg-violet-500/15 border border-violet-500/20 text-violet-300 text-xs"
              >
                {p}
              </span>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  )
}

export function RubricConfirmation({
  criteria,
  onWeightChange,
  onApprove,
  intent,
}: RubricConfirmationProps) {
  const totalWeight = criteria.reduce((sum, c) => sum + c.weight, 0)

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="mb-5">
        <h2 className="text-2xl font-semibold text-[#FAFAFA] mb-2">
          Confirm what matters most
        </h2>
        <p className="text-[#A1A1AA]">
          I built this rubric from your answers. Adjust any weight before we research.
        </p>
      </div>

      {/* Intent summary — shown when structured intent is available */}
      {intent && <IntentSummary intent={intent} />}

      {/* Criteria List */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-2">
        {criteria.map((criterion, index) => (
          <motion.div
            key={criterion.id}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.05 }}
            className="p-4 rounded-xl bg-white/[0.02] border border-white/[0.06]"
          >
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="font-medium text-[#FAFAFA]">{criterion.label}</span>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button className="text-[#71717A] hover:text-[#A1A1AA] transition-colors">
                        <Info className="w-4 h-4" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-xs">
                      <p className="text-sm">{criterion.rationale}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <span className="px-2.5 py-1 rounded-lg bg-violet-500/20 text-violet-300 text-sm font-mono font-medium">
                {criterion.weight}/10
              </span>
            </div>

            <Slider
              value={[criterion.weight]}
              min={0}
              max={10}
              step={1}
              onValueChange={([value]) => onWeightChange(criterion.id, value)}
              className="[&_[role=slider]]:bg-violet-500 [&_[role=slider]]:border-violet-400 [&_[role=slider]]:shadow-lg [&_[role=slider]]:shadow-violet-500/25 [&_.relative]:bg-white/[0.1] [&_[data-orientation=horizontal]>.absolute]:bg-violet-500"
            />

            <p className="text-xs text-[#71717A] mt-3 line-clamp-2">
              {criterion.rationale}
            </p>
            {criterion.weight <= 2 && (
              <p className="text-xs text-amber-500/80 mt-2">
                Low weight — this factor will be nearly ignored in scoring
              </p>
            )}
          </motion.div>
        ))}
      </div>

      {/* Footer */}
      <div className="mt-6 pt-4 border-t border-white/[0.06]">
        <div className="flex items-center justify-between mb-4">
          <span className="text-sm text-[#71717A]">Total weight</span>
          <span className="font-mono text-[#FAFAFA]">{totalWeight} / {criteria.length * 10}</span>
        </div>
        <Button
          onClick={onApprove}
          className="w-full h-12 bg-gradient-to-r from-violet-600 to-violet-500 hover:from-violet-500 hover:to-violet-400 text-white font-medium shadow-lg shadow-violet-500/25"
        >
          Approve & Start Research
        </Button>
      </div>
    </div>
  )
}
