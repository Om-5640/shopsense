'use client'

import { motion } from 'framer-motion'

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
      <span className="text-sm text-[#71717A]">Try one of these:</span>
      <div className="flex flex-wrap justify-center gap-2">
        {exampleQueries.map((query, index) => (
          <motion.button
            key={query}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.5 + index * 0.05 }}
            onClick={() => onChipClick(query)}
            className="px-4 py-2 rounded-full bg-white/[0.04] border border-white/[0.08] text-sm text-[#A1A1AA] hover:bg-white/[0.08] hover:text-[#FAFAFA] hover:border-white/[0.12] transition-all duration-200"
          >
            {query}
          </motion.button>
        ))}
      </div>
    </motion.div>
  )
}
