'use client'

import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

const analyzerPhrases = [
  'Comparing recommendations...',
  'Detecting consensus...',
  'Filtering noise...',
  'Cross-validating across subreddits...',
  'Identifying outliers...',
  'Weighing expert opinions...',
  'Analyzing sentiment patterns...',
  'Building product profiles...',
]

export function AnalyzerAnimation() {
  const [phraseIndex, setPhraseIndex] = useState(0)
  
  useEffect(() => {
    const interval = setInterval(() => {
      setPhraseIndex((prev) => (prev + 1) % analyzerPhrases.length)
    }, 2000)
    return () => clearInterval(interval)
  }, [])
  
  return (
    <div className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-8 overflow-hidden">
      {/* Animated wave pattern */}
      <div className="relative h-32 mb-8 overflow-hidden rounded-xl bg-gradient-to-br from-violet-500/10 to-indigo-500/10">
        <svg
          className="absolute inset-0 w-full h-full"
          viewBox="0 0 400 100"
          preserveAspectRatio="none"
        >
          <motion.path
            d="M0,50 Q100,20 200,50 T400,50"
            fill="none"
            stroke="url(#gradient)"
            strokeWidth="2"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}
          />
          <motion.path
            d="M0,50 Q100,80 200,50 T400,50"
            fill="none"
            stroke="url(#gradient2)"
            strokeWidth="2"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 2.5, repeat: Infinity, ease: 'linear', delay: 0.5 }}
          />
          <defs>
            <linearGradient id="gradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#8B5CF6" stopOpacity="0.3" />
              <stop offset="50%" stopColor="#A78BFA" stopOpacity="0.8" />
              <stop offset="100%" stopColor="#8B5CF6" stopOpacity="0.3" />
            </linearGradient>
            <linearGradient id="gradient2" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#34D399" stopOpacity="0.3" />
              <stop offset="50%" stopColor="#10B981" stopOpacity="0.8" />
              <stop offset="100%" stopColor="#34D399" stopOpacity="0.3" />
            </linearGradient>
          </defs>
        </svg>
        
        {/* Floating particles */}
        {[...Array(8)].map((_, i) => (
          <motion.div
            key={i}
            className="absolute w-2 h-2 rounded-full bg-violet-400/40"
            initial={{ 
              x: Math.random() * 400, 
              y: Math.random() * 100,
              scale: 0 
            }}
            animate={{ 
              x: Math.random() * 400,
              y: Math.random() * 100,
              scale: [0, 1, 0],
            }}
            transition={{ 
              duration: 3,
              repeat: Infinity,
              delay: i * 0.3,
              ease: 'easeInOut'
            }}
          />
        ))}
      </div>
      
      {/* Rotating phrase */}
      <div className="text-center">
        <AnimatePresence mode="wait">
          <motion.p
            key={phraseIndex}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.3 }}
            className="text-lg text-[#FAFAFA] font-medium"
          >
            {analyzerPhrases[phraseIndex]}
          </motion.p>
        </AnimatePresence>
        <p className="text-sm text-[#71717A] mt-2">
          Our AI is synthesizing insights from all sources
        </p>
      </div>
    </div>
  )
}
