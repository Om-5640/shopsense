'use client'

import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, ArrowRight, ChevronDown } from 'lucide-react'
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
  const [query, setQuery]               = useState('')
  const [placeholderIndex, setPlaceholderIndex] = useState(0)
  const [isFocused, setIsFocused]       = useState(false)
  const [region, setRegion]             = useState<RegionOption>(REGIONS[0])
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const id = setInterval(() => {
      setPlaceholderIndex((p) => (p + 1) % placeholderExamples.length)
    }, 3000)
    return () => clearInterval(id)
  }, [])

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
    if (query.trim()) onSearch(query.trim(), region.key)
  }

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-2xl mx-auto">
      {/* Outer wrapper carries the aurora glow */}
      <div className="relative">

        {/* Aurora glow ring — brightens on focus */}
        <motion.div
          className="absolute -inset-4 rounded-[32px] pointer-events-none"
          animate={{ opacity: isFocused ? 1 : 0 }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          style={{
            background: 'radial-gradient(ellipse at 50% 50%, rgba(139,92,246,0.18) 0%, rgba(139,92,246,0.06) 50%, transparent 75%)',
            filter: 'blur(16px)',
          }}
        />

        {/* Second, tighter glow ring */}
        <motion.div
          className="absolute -inset-1 rounded-[26px] pointer-events-none"
          animate={{ opacity: isFocused ? 1 : 0 }}
          transition={{ duration: 0.4 }}
          style={{
            background: 'linear-gradient(135deg, rgba(139,92,246,0.12) 0%, transparent 50%, rgba(167,139,250,0.08) 100%)',
            filter: 'blur(6px)',
          }}
        />

        {/* Search bar */}
        <div
          className={cn(
            'relative flex items-center h-16 rounded-2xl z-10',
            'bg-white/[0.04] backdrop-blur-xl',
            'border transition-all duration-300 ease-out',
            isFocused
              ? 'border-violet-500/55 shadow-[0_0_0_1px_rgba(167,139,250,0.15),0_8px_32px_rgba(139,92,246,0.2)]'
              : 'border-white/[0.10] hover:border-white/[0.16] shadow-[0_4px_24px_rgba(0,0,0,0.3)]',
          )}
        >
          {/* Search icon */}
          <motion.div
            className="pl-5 pr-3"
            animate={{ color: isFocused ? '#A78BFA' : '#71717A' }}
            transition={{ duration: 0.25 }}
          >
            <Search className="w-5 h-5" />
          </motion.div>

          {/* Input */}
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

            {/* Animated cycling placeholder */}
            {!query && !isFocused && (
              <div className="absolute inset-0 flex items-center pointer-events-none">
                <AnimatePresence mode="wait">
                  <motion.span
                    key={placeholderIndex}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.28 }}
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
                'flex items-center gap-1.5 h-9 px-2.5 rounded-xl text-sm transition-all duration-200',
                'border hover:border-white/[0.18]',
                'bg-white/[0.04] hover:bg-white/[0.08] text-[#A1A1AA] hover:text-[#FAFAFA]',
                dropdownOpen
                  ? 'border-violet-500/35 bg-violet-500/[0.08] text-[#FAFAFA]'
                  : 'border-white/[0.08]',
              )}
              aria-label="Select region"
            >
              <span className="text-base leading-none">{region.flag}</span>
              <span className="hidden sm:inline text-xs">{region.short}</span>
              <ChevronDown className={cn('w-3 h-3 transition-transform duration-200', dropdownOpen && 'rotate-180')} />
            </button>

            <AnimatePresence>
              {dropdownOpen && (
                <motion.div
                  initial={{ opacity: 0, y: -6, scale: 0.96 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -6, scale: 0.96 }}
                  transition={{ duration: 0.15, ease: 'easeOut' }}
                  className="absolute right-0 top-full mt-2 w-52 rounded-xl bg-[#111113] border border-white/[0.10] shadow-[0_16px_48px_rgba(0,0,0,0.6)] overflow-hidden z-50"
                >
                  {REGIONS.map((r) => (
                    <button
                      key={r.key}
                      type="button"
                      onClick={() => { setRegion(r); setDropdownOpen(false) }}
                      className={cn(
                        'w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-left transition-colors duration-150',
                        'hover:bg-white/[0.06]',
                        region.key === r.key
                          ? 'text-violet-300 bg-violet-500/[0.09]'
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

          {/* Submit button */}
          <div className="pr-2">
            <motion.button
              type="submit"
              disabled={!query.trim()}
              whileHover={query.trim() ? { scale: 1.03 } : {}}
              whileTap={query.trim()   ? { scale: 0.97 } : {}}
              transition={{ type: 'spring', stiffness: 400, damping: 17 }}
              className="h-12 px-6 rounded-xl bg-gradient-to-r from-violet-600 to-violet-500 hover:from-violet-500 hover:to-violet-400 text-white font-medium text-sm transition-all duration-200 disabled:opacity-45 disabled:cursor-not-allowed shadow-lg shadow-violet-500/30 hover:shadow-violet-500/45 flex items-center gap-2"
            >
              <span>Research</span>
              <motion.div
                animate={query.trim() ? { x: [0, 3, 0] } : {}}
                transition={{ repeat: Infinity, duration: 1.6, ease: 'easeInOut' }}
              >
                <ArrowRight className="w-4 h-4" />
              </motion.div>
            </motion.button>
          </div>
        </div>
      </div>

      {/* Region hint */}
      <AnimatePresence>
        {region.key !== 'global' && (
          <motion.p
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.2 }}
            className="text-center text-xs text-[#52525B] mt-2.5"
          >
            Searching {region.label} — prices and reviews will be region-specific
          </motion.p>
        )}
      </AnimatePresence>
    </form>
  )
}
