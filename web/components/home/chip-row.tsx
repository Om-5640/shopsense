'use client'

import { motion } from 'framer-motion'
import { ArrowUpRight } from 'lucide-react'

const exampleQueries = [
  'wireless earbuds for running',
  'standing desk under $500',
  'skincare for sensitive skin',
  'gaming mouse for FPS',
  'laptop for video editing',
]

interface ChipRowProps {
  onChipClick: (query: string) => void
}

export function ChipRow({ onChipClick }: ChipRowProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.4, duration: 0.5 }}
      className="flex flex-col items-center gap-3"
    >
      <span className="text-xs text-[#52525B] uppercase tracking-widest font-medium">Try one of these</span>
      <div className="flex flex-wrap justify-center gap-2">
        {exampleQueries.map((query, index) => (
          <motion.button
            key={query}
            initial={{ opacity: 0, scale: 0.88, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ delay: 0.48 + index * 0.06, type: 'spring', stiffness: 320, damping: 22 }}
            whileHover={{ scale: 1.04, y: -2 }}
            whileTap={{ scale: 0.96 }}
            onClick={() => onChipClick(query)}
            className="group relative inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-sm text-[#A1A1AA] transition-all duration-200 overflow-hidden
              bg-white/[0.03] border border-white/[0.08]
              hover:text-[#FAFAFA] hover:border-violet-500/30 hover:bg-violet-500/[0.06]
              hover:shadow-[0_0_12px_rgba(167,139,250,0.12)]"
          >
            {/* Shimmer scan on hover */}
            <span className="absolute inset-0 opacity-0 group-hover:opacity-100 animate-shimmer pointer-events-none" />
            <span className="relative z-10">{query}</span>
            <ArrowUpRight className="relative z-10 w-3 h-3 opacity-0 group-hover:opacity-60 -translate-x-1 group-hover:translate-x-0 transition-all duration-200" />
          </motion.button>
        ))}
      </div>
    </motion.div>
  )
}
