'use client'

import { motion } from 'framer-motion'
import { Slider } from '@/components/ui/slider'
import { Button } from '@/components/ui/button'
import { RotateCcw, Save, Info } from 'lucide-react'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

interface RubricCriterion {
  id: string
  label: string
  weight: number
  rationale: string
}

interface RubricSidebarProps {
  criteria: RubricCriterion[]
  onWeightChange: (id: string, weight: number) => void
  onReset: () => void
  onSave: () => void
  activeCriterionId?: string | null
}

export function RubricSidebar({
  criteria,
  onWeightChange,
  onReset,
  onSave,
  activeCriterionId,
}: RubricSidebarProps) {
  const totalWeight = criteria.reduce((sum, c) => sum + c.weight, 0)
  const maxWeight = criteria.length * 10
  
  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="mb-6">
        <h2 className="text-lg font-semibold text-[#FAFAFA] mb-1">Your priorities</h2>
        <p className="text-sm text-[#71717A]">Drag any slider to re-rank</p>
      </div>
      
      {/* Total weight indicator */}
      <div className="mb-6 p-3 rounded-xl bg-white/[0.02] border border-white/[0.06]">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-[#71717A]">Total weight</span>
          <span className="font-mono text-sm text-[#FAFAFA]">
            {totalWeight} / {maxWeight}
          </span>
        </div>
        <div className="h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-gradient-to-r from-violet-600 to-violet-400 rounded-full"
            initial={{ width: 0 }}
            animate={{ width: `${(totalWeight / maxWeight) * 100}%` }}
            transition={{ duration: 0.3 }}
          />
        </div>
      </div>
      
      {/* Criteria list */}
      <div className="flex-1 overflow-y-auto space-y-3 pr-1">
        {criteria.map((criterion) => {
          const isActive = criterion.id === activeCriterionId
          
          return (
            <motion.div
              key={criterion.id}
              layout
              className={`
                p-4 rounded-xl border transition-all duration-300
                ${isActive 
                  ? 'bg-violet-500/10 border-violet-500/30 shadow-glow-sm' 
                  : 'bg-white/[0.02] border-white/[0.06] hover:border-white/[0.1]'
                }
              `}
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-[#FAFAFA] text-sm">{criterion.label}</span>
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button className="text-[#71717A] hover:text-[#A1A1AA] transition-colors">
                          <Info className="w-3.5 h-3.5" />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent side="right" className="max-w-xs">
                        <p className="text-sm">{criterion.rationale}</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>
                <span className={`
                  font-mono text-lg font-bold
                  ${criterion.weight >= 8 ? 'text-emerald-400' : 
                    criterion.weight >= 5 ? 'text-amber-400' : 'text-[#A1A1AA]'}
                `}>
                  {criterion.weight}
                </span>
              </div>
              
              <Slider
                value={[criterion.weight]}
                min={0}
                max={10}
                step={1}
                onValueChange={([value]) => onWeightChange(criterion.id, value)}
                className="[&_[role=slider]]:h-3.5 [&_[role=slider]]:w-3.5 [&_[role=slider]]:bg-violet-500 [&_[role=slider]]:border-0 [&_[role=slider]]:shadow-lg [&_[role=slider]]:shadow-violet-500/25 [&_.relative]:h-1 [&_.relative]:bg-white/[0.1] [&_[data-orientation=horizontal]>.absolute]:bg-violet-500"
              />
            </motion.div>
          )
        })}
      </div>
      
      {/* Footer actions */}
      <div className="mt-6 pt-4 border-t border-white/[0.06] flex gap-3">
        <Button
          variant="ghost"
          onClick={onReset}
          className="flex-1 text-[#71717A] hover:text-[#FAFAFA]"
        >
          <RotateCcw className="w-4 h-4 mr-2" />
          Reset
        </Button>
        <Button
          onClick={onSave}
          className="flex-1 bg-violet-600 hover:bg-violet-500"
        >
          <Save className="w-4 h-4 mr-2" />
          Save
        </Button>
      </div>
    </div>
  )
}
