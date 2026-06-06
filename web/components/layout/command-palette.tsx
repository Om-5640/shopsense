'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { Command } from 'cmdk'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, History, Brain, Settings, ArrowRight, Sparkles, Home } from 'lucide-react'

interface CommandPaletteProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

const QUICK_ACTIONS = [
  { value: 'home',     label: 'Home',           desc: 'Back to the search page',        icon: Home,     iconBg: 'bg-[#3F3F46]/40',     iconColor: 'text-[#A1A1AA]', href: '/' },
  { value: 'new',      label: 'New search',     desc: 'Start a fresh product search',   icon: Sparkles, iconBg: 'bg-violet-500/15',    iconColor: 'text-violet-400', href: '/' },
  { value: 'history',  label: 'History',        desc: 'Browse past research sessions',  icon: History,  iconBg: 'bg-emerald-500/15',   iconColor: 'text-emerald-400', href: '/history' },
  { value: 'memory',   label: 'My Memory',      desc: 'Preferences and saved signals',  icon: Brain,    iconBg: 'bg-amber-500/15',     iconColor: 'text-amber-400', href: '/memory' },
  { value: 'settings', label: 'Settings',       desc: 'Account, region, providers',     icon: Settings, iconBg: 'bg-blue-500/15',      iconColor: 'text-blue-400', href: '/settings' },
]

const EXAMPLE_QUERIES = [
  'best wireless earbuds under $100',
  'mechanical keyboard for programming',
  'running shoes for flat feet',
  'ergonomic office chair under $400',
]

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const router = useRouter()
  const [search, setSearch] = useState('')

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        onOpenChange(!open)
      }
      if (e.key === 'Escape') onOpenChange(false)
    }
    document.addEventListener('keydown', down)
    return () => document.removeEventListener('keydown', down)
  }, [open, onOpenChange])

  // Reset search when closed
  useEffect(() => {
    if (!open) setSearch('')
  }, [open])

  const go = useCallback((href: string) => {
    router.push(href)
    onOpenChange(false)
  }, [router, onOpenChange])

  const runQuery = useCallback((query: string) => {
    router.push(`/research?q=${encodeURIComponent(query)}`)
    onOpenChange(false)
  }, [router, onOpenChange])

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.12 }}
            className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm"
            onClick={() => onOpenChange(false)}
          />

          {/* Palette */}
          <motion.div
            initial={{ opacity: 0, scale: 0.97, y: -12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -12 }}
            transition={{ type: 'spring', damping: 28, stiffness: 380, mass: 0.6 }}
            className="fixed left-1/2 top-[18%] z-50 w-full max-w-[560px] -translate-x-1/2 px-4"
          >
            <Command
              className="rounded-2xl border border-white/[0.10] bg-[#0F0F12] shadow-[0_32px_80px_rgba(0,0,0,0.6),0_0_0_1px_rgba(255,255,255,0.04)] overflow-hidden"
              loop
            >
              {/* Search input */}
              <div className="flex items-center gap-3 px-4 border-b border-white/[0.06]">
                <Search className="w-4 h-4 text-[#52525B] flex-shrink-0" />
                <Command.Input
                  value={search}
                  onValueChange={setSearch}
                  placeholder="Search or go to…"
                  className="flex-1 bg-transparent py-4 text-[#FAFAFA] placeholder:text-[#3F3F46] outline-none text-sm"
                  autoFocus
                />
                <kbd className="hidden sm:inline-flex h-5 items-center gap-0.5 rounded border border-white/[0.08] bg-white/[0.04] px-1.5 text-[10px] font-medium text-[#3F3F46] flex-shrink-0">
                  ESC
                </kbd>
              </div>

              <Command.List className="max-h-[380px] overflow-y-auto p-2">
                <Command.Empty className="py-8 text-center text-sm text-[#52525B]">
                  No results — press Enter to search for &ldquo;{search}&rdquo;
                </Command.Empty>

                {/* Quick navigation */}
                <Command.Group>
                  <div className="px-2 pt-2 pb-1">
                    <span className="text-[10px] font-medium text-[#3F3F46] uppercase tracking-widest">Navigate</span>
                  </div>
                  {QUICK_ACTIONS.map((item) => (
                    <Command.Item
                      key={item.value}
                      value={item.value}
                      keywords={[item.label, item.desc]}
                      onSelect={() => go(item.href)}
                      className="flex items-center gap-3 px-3 py-2.5 rounded-xl cursor-pointer text-[#A1A1AA] data-[selected=true]:bg-white/[0.06] data-[selected=true]:text-[#FAFAFA] transition-colors"
                    >
                      <div className={`w-8 h-8 rounded-lg ${item.iconBg} flex items-center justify-center flex-shrink-0`}>
                        <item.icon className={`w-4 h-4 ${item.iconColor}`} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <span className="text-sm font-medium block">{item.label}</span>
                        <span className="text-xs text-[#52525B] block truncate">{item.desc}</span>
                      </div>
                      <ArrowRight className="w-3.5 h-3.5 text-[#3F3F46] flex-shrink-0" />
                    </Command.Item>
                  ))}
                </Command.Group>

                <Command.Separator className="my-2 h-px bg-white/[0.05]" />

                {/* Example searches */}
                <Command.Group>
                  <div className="px-2 pt-1 pb-1">
                    <span className="text-[10px] font-medium text-[#3F3F46] uppercase tracking-widest">Try searching</span>
                  </div>
                  {EXAMPLE_QUERIES.map((query) => (
                    <Command.Item
                      key={query}
                      value={`search:${query}`}
                      keywords={query.split(' ')}
                      onSelect={() => runQuery(query)}
                      className="flex items-center gap-3 px-3 py-2 rounded-xl cursor-pointer text-[#52525B] data-[selected=true]:bg-white/[0.06] data-[selected=true]:text-[#A1A1AA] transition-colors"
                    >
                      <Search className="w-3.5 h-3.5 text-[#3F3F46] flex-shrink-0" />
                      <span className="flex-1 truncate text-sm">{query}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              </Command.List>

              {/* Footer hint */}
              <div className="flex items-center justify-between px-4 py-2.5 border-t border-white/[0.05]">
                <div className="flex items-center gap-3 text-[10px] text-[#3F3F46]">
                  <span className="flex items-center gap-1">
                    <kbd className="rounded border border-white/[0.08] bg-white/[0.04] px-1 py-0.5">↑↓</kbd>
                    navigate
                  </span>
                  <span className="flex items-center gap-1">
                    <kbd className="rounded border border-white/[0.08] bg-white/[0.04] px-1 py-0.5">↵</kbd>
                    select
                  </span>
                </div>
                <span className="text-[10px] text-[#3F3F46]">ShopResearch</span>
              </div>
            </Command>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
