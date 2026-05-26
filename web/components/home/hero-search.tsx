'use client'

import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, ArrowRight } from 'lucide-react'
import { Button } from '@/components/ui/button'

const placeholderExamples = [
  'best earbuds under $100',
  'facewash for oily acne-prone skin',
  'mechanical keyboard under $150',
  'office chair for back pain',
  'running shoes for flat feet',
]

interface HeroSearchProps {
  onSearch: (query: string) => void
}

export function HeroSearch({ onSearch }: HeroSearchProps) {
  const [query, setQuery] = useState('')
  const [placeholderIndex, setPlaceholderIndex] = useState(0)
  const [isFocused, setIsFocused] = useState(false)
  
  // Rotate placeholder every 3 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      setPlaceholderIndex((prev) => (prev + 1) % placeholderExamples.length)
    }, 3000)
    return () => clearInterval(interval)
  }, [])
  
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (query.trim()) {
      onSearch(query.trim())
    }
  }
  
  return (
    <form onSubmit={handleSubmit} className="w-full max-w-2xl mx-auto">
      <div
        className={`
          relative flex items-center h-16 rounded-2xl
          bg-white/[0.04] backdrop-blur-xl
          border transition-all duration-300 ease-out
          ${isFocused 
            ? 'border-violet-500/50 shadow-glow' 
            : 'border-white/[0.10] hover:border-white/[0.15]'
          }
        `}
      >
        {/* Search Icon */}
        <div className="pl-5 pr-3">
          <Search className="w-5 h-5 text-[#71717A]" />
        </div>
        
        {/* Input with animated placeholder */}
        <div className="flex-1 relative">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            className="w-full h-full bg-transparent text-[#FAFAFA] text-lg outline-none placeholder:text-transparent"
            aria-label="Search query"
          />
          
          {/* Animated Placeholder */}
          {!query && !isFocused && (
            <div className="absolute inset-0 flex items-center pointer-events-none">
              <AnimatePresence mode="wait">
                <motion.span
                  key={placeholderIndex}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  transition={{ duration: 0.3 }}
                  className="text-lg text-[#71717A]"
                >
                  {placeholderExamples[placeholderIndex]}
                </motion.span>
              </AnimatePresence>
            </div>
          )}
          
          {!query && isFocused && (
            <span className="absolute inset-0 flex items-center text-lg text-[#71717A] pointer-events-none">
              What are you looking for?
            </span>
          )}
        </div>
        
        {/* Keyboard shortcut hint */}
        <div className="hidden sm:flex items-center pr-3">
          <kbd className="h-6 px-2 flex items-center gap-1 rounded-md border border-white/[0.1] bg-white/[0.04] text-xs text-[#71717A]">
            <span className="text-[10px]">⌘</span>K
          </kbd>
        </div>
        
        {/* Search Button */}
        <div className="pr-2">
          <Button
            type="submit"
            disabled={!query.trim()}
            className="h-12 px-6 rounded-xl bg-gradient-to-r from-violet-600 to-violet-500 hover:from-violet-500 hover:to-violet-400 text-white font-medium transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-violet-500/25 hover:shadow-violet-500/40"
          >
            <span className="mr-2">Research</span>
            <ArrowRight className="w-4 h-4" />
          </Button>
        </div>
      </div>
    </form>
  )
}
