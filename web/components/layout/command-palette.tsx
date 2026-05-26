'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { Command } from 'cmdk'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  Search, 
  History, 
  Brain, 
  Settings, 
  Moon, 
  Sun,
  ArrowRight,
  Sparkles
} from 'lucide-react'

interface CommandPaletteProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

const recentSearches = [
  'best wireless earbuds under $100',
  'mechanical keyboard for programming',
  'running shoes for flat feet',
  'laptop backpack for 15 inch',
  'ergonomic office chair',
]

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const router = useRouter()
  const [search, setSearch] = useState('')
  
  // Handle keyboard shortcut
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        onOpenChange(!open)
      }
      if (e.key === 'Escape') {
        onOpenChange(false)
      }
    }
    
    document.addEventListener('keydown', down)
    return () => document.removeEventListener('keydown', down)
  }, [open, onOpenChange])
  
  const handleSelect = useCallback((value: string) => {
    if (value === 'new-search') {
      router.push('/')
      onOpenChange(false)
    } else if (value === 'history') {
      router.push('/history')
      onOpenChange(false)
    } else if (value === 'memory') {
      router.push('/memory')
      onOpenChange(false)
    } else if (value === 'settings') {
      router.push('/settings')
      onOpenChange(false)
    } else if (value.startsWith('search:')) {
      const query = value.replace('search:', '')
      router.push(`/research?q=${encodeURIComponent(query)}`)
      onOpenChange(false)
    }
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
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
            onClick={() => onOpenChange(false)}
          />
          
          {/* Command Dialog */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: -20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -20 }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
            className="fixed left-1/2 top-[20%] z-50 w-full max-w-xl -translate-x-1/2"
          >
            <Command
              className="rounded-2xl border border-white/[0.1] bg-[#0F0F12] shadow-2xl overflow-hidden"
              loop
            >
              <div className="flex items-center gap-3 border-b border-white/[0.06] px-4">
                <Search className="w-4 h-4 text-[#71717A]" />
                <Command.Input
                  value={search}
                  onValueChange={setSearch}
                  placeholder="Search or type a command..."
                  className="flex-1 bg-transparent py-4 text-[#FAFAFA] placeholder:text-[#71717A] outline-none text-sm"
                />
                <kbd className="hidden sm:inline-flex h-5 items-center gap-1 rounded border border-white/[0.1] bg-white/[0.04] px-1.5 text-[10px] font-medium text-[#71717A]">
                  ESC
                </kbd>
              </div>
              
              <Command.List className="max-h-[300px] overflow-y-auto p-2">
                <Command.Empty className="py-6 text-center text-sm text-[#71717A]">
                  No results found.
                </Command.Empty>
                
                <Command.Group heading="Quick Actions" className="px-2 py-1.5 text-xs text-[#71717A]">
                  <Command.Item
                    value="new-search"
                    onSelect={() => handleSelect('new-search')}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer text-[#FAFAFA] data-[selected=true]:bg-white/[0.06]"
                  >
                    <div className="w-8 h-8 rounded-lg bg-violet-500/20 flex items-center justify-center">
                      <Sparkles className="w-4 h-4 text-violet-400" />
                    </div>
                    <span className="flex-1">Start new search</span>
                    <ArrowRight className="w-4 h-4 text-[#71717A]" />
                  </Command.Item>
                  
                  <Command.Item
                    value="history"
                    onSelect={() => handleSelect('history')}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer text-[#FAFAFA] data-[selected=true]:bg-white/[0.06]"
                  >
                    <div className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center">
                      <History className="w-4 h-4 text-emerald-400" />
                    </div>
                    <span className="flex-1">Search history</span>
                  </Command.Item>
                  
                  <Command.Item
                    value="memory"
                    onSelect={() => handleSelect('memory')}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer text-[#FAFAFA] data-[selected=true]:bg-white/[0.06]"
                  >
                    <div className="w-8 h-8 rounded-lg bg-amber-500/20 flex items-center justify-center">
                      <Brain className="w-4 h-4 text-amber-400" />
                    </div>
                    <span className="flex-1">Your memory</span>
                  </Command.Item>
                  
                  <Command.Item
                    value="settings"
                    onSelect={() => handleSelect('settings')}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer text-[#FAFAFA] data-[selected=true]:bg-white/[0.06]"
                  >
                    <div className="w-8 h-8 rounded-lg bg-slate-500/20 flex items-center justify-center">
                      <Settings className="w-4 h-4 text-slate-400" />
                    </div>
                    <span className="flex-1">Settings</span>
                  </Command.Item>
                </Command.Group>
                
                <Command.Separator className="my-2 h-px bg-white/[0.06]" />
                
                <Command.Group heading="Recent Searches" className="px-2 py-1.5 text-xs text-[#71717A]">
                  {recentSearches.map((query) => (
                    <Command.Item
                      key={query}
                      value={`search:${query}`}
                      onSelect={() => handleSelect(`search:${query}`)}
                      className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer text-[#A1A1AA] data-[selected=true]:bg-white/[0.06] data-[selected=true]:text-[#FAFAFA]"
                    >
                      <Search className="w-4 h-4 text-[#71717A]" />
                      <span className="flex-1 truncate">{query}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              </Command.List>
            </Command>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
