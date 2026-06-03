'use client'

import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, ArrowRight, ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const placeholderExamples = [
  'best earbuds under $100',
  'facewash for oily acne-prone skin',
  'mechanical keyboard under £150',
  'office chair for back pain',
  'running shoes for flat feet',
]

export interface RegionOption {
  key: string
  flag: string
  label: string
  short: string
}

export const REGIONS: RegionOption[] = [
  { key: 'global',    flag: '🌍', label: 'Global (auto-detect)', short: 'Global'    },
  { key: 'india',     flag: '🇮🇳', label: 'India (₹)',           short: 'India'     },
  { key: 'usa',       flag: '🇺🇸', label: 'USA ($)',              short: 'USA'       },
  { key: 'uk',        flag: '🇬🇧', label: 'UK (£)',               short: 'UK'        },
  { key: 'europe',    flag: '🇪🇺', label: 'Europe (€)',           short: 'Europe'    },
  { key: 'canada',    flag: '🇨🇦', label: 'Canada (C$)',          short: 'Canada'    },
  { key: 'australia', flag: '🇦🇺', label: 'Australia (A$)',       short: 'AU'        },
]

interface HeroSearchProps {
  onSearch: (query: string, region: string) => void
}

export function HeroSearch({ onSearch }: HeroSearchProps) {
  const [query, setQuery] = useState('')
  const [placeholderIndex, setPlaceholderIndex] = useState(0)
  const [isFocused, setIsFocused] = useState(false)
  const [region, setRegion] = useState<RegionOption>(REGIONS[0]) // global default
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Rotate placeholder every 3 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      setPlaceholderIndex((prev) => (prev + 1) % placeholderExamples.length)
    }, 3000)
    return () => clearInterval(interval)
  }, [])

  // Close dropdown on outside click
  useEffect(() => {
    function handle(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (query.trim()) {
      onSearch(query.trim(), region.key)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-2xl mx-auto">
      <div
        className={cn(
          'relative flex items-center h-16 rounded-2xl',
          'bg-white/[0.04] backdrop-blur-xl',
          'border transition-all duration-300 ease-out',
          isFocused
            ? 'border-violet-500/50 shadow-glow'
            : 'border-white/[0.10] hover:border-white/[0.15]',
        )}
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

        {/* Region selector */}
        <div className="relative shrink-0 pr-2" ref={dropdownRef}>
          <button
            type="button"
            onClick={() => setDropdownOpen((v) => !v)}
            className={cn(
              'flex items-center gap-1.5 h-9 px-2.5 rounded-xl text-sm transition-all',
              'border border-white/[0.08] hover:border-white/[0.16]',
              'bg-white/[0.04] hover:bg-white/[0.07] text-[#A1A1AA] hover:text-[#FAFAFA]',
              dropdownOpen && 'border-violet-500/30 bg-violet-500/[0.07] text-[#FAFAFA]',
            )}
            aria-label="Select region"
          >
            <span className="text-base leading-none">{region.flag}</span>
            <span className="hidden sm:inline text-xs">{region.short}</span>
            <ChevronDown className={cn('w-3 h-3 transition-transform', dropdownOpen && 'rotate-180')} />
          </button>

          <AnimatePresence>
            {dropdownOpen && (
              <motion.div
                initial={{ opacity: 0, y: -6, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -6, scale: 0.97 }}
                transition={{ duration: 0.15 }}
                className="absolute right-0 top-full mt-1.5 w-52 rounded-xl bg-[#111113] border border-white/[0.10] shadow-2xl overflow-hidden z-50"
              >
                {REGIONS.map((r) => (
                  <button
                    key={r.key}
                    type="button"
                    onClick={() => { setRegion(r); setDropdownOpen(false) }}
                    className={cn(
                      'w-full flex items-center gap-2.5 px-3 py-2.5 text-sm transition-colors text-left',
                      'hover:bg-white/[0.06]',
                      region.key === r.key
                        ? 'text-violet-300 bg-violet-500/[0.08]'
                        : 'text-[#A1A1AA]',
                    )}
                  >
                    <span className="text-base">{r.flag}</span>
                    <span>{r.label}</span>
                  </button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
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

      {/* Region hint below search bar */}
      {region.key !== 'global' && (
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="text-center text-xs text-[#52525B] mt-2"
        >
          Searching {region.label} — prices and reviews will be region-specific
        </motion.p>
      )}
    </form>
  )
}
