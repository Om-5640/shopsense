'use client'

import { usePathname } from 'next/navigation'
import Link from 'next/link'
import { Command, Sun, Moon, Activity } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useState, useEffect } from 'react'

const navItems = [
  { label: 'Home', href: '/' },
  { label: 'History', href: '/history' },
  { label: 'Compare', href: '/compare' },
  { label: 'Memory', href: '/memory' },
  { label: 'Settings', href: '/settings' },
]

export function Header({ onOpenCommandPalette }: { onOpenCommandPalette?: () => void }) {
  const pathname = usePathname()
  const [mounted, setMounted] = useState(false)
  
  useEffect(() => {
    setMounted(true)
  }, [])
  
  return (
    <header className="sticky top-0 z-50 h-[60px] backdrop-blur-xl bg-black/40 border-b border-white/[0.06]">
      <div className="max-w-7xl mx-auto h-full px-4 flex items-center justify-between">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2.5 group">
          {/* Geometric logo mark - nested circles */}
          <div className="relative w-8 h-8">
            <div className="absolute inset-0 rounded-full border-2 border-violet-400/80" />
            <div className="absolute inset-1.5 rounded-full border border-violet-400/60" />
            <div className="absolute inset-3 rounded-full bg-violet-400/80" />
          </div>
          <span className="font-semibold text-[#FAFAFA] tracking-tight">ShopResearch</span>
        </Link>
        
        {/* Center Navigation */}
        <nav className="hidden md:flex items-center gap-1">
          {navItems.map((item) => {
            const isActive = pathname === item.href
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'px-4 py-1.5 rounded-full text-sm font-medium transition-all duration-200',
                  isActive
                    ? 'bg-white/[0.08] text-[#FAFAFA]'
                    : 'text-[#A1A1AA] hover:text-[#FAFAFA] hover:bg-white/[0.04]'
                )}
              >
                {item.label}
              </Link>
            )
          })}
        </nav>
        
        {/* Right Section */}
        <div className="flex items-center gap-3">
          {/* Command Palette Hint */}
          <Button
            variant="ghost"
            size="sm"
            onClick={onOpenCommandPalette}
            className="hidden sm:flex items-center gap-2 text-[#71717A] hover:text-[#FAFAFA] hover:bg-white/[0.04] rounded-lg px-3"
          >
            <Command className="w-3.5 h-3.5" />
            <span className="text-xs">K</span>
          </Button>
          
          {/* Theme Toggle (visual only for now) */}
          <Button
            variant="ghost"
            size="icon"
            className="w-9 h-9 text-[#71717A] hover:text-[#FAFAFA] hover:bg-white/[0.04] rounded-lg"
            aria-label="Toggle theme"
          >
            {mounted ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
          </Button>
          
          {/* Status Indicator */}
          <div className="hidden sm:flex items-center gap-2 text-xs text-[#71717A]">
            <div className="relative">
              <div className="w-2 h-2 rounded-full bg-emerald-500" />
              <div className="absolute inset-0 w-2 h-2 rounded-full bg-emerald-500 animate-ping opacity-75" />
            </div>
            <span className="hidden lg:inline">All systems operational</span>
          </div>
        </div>
      </div>
    </header>
  )
}
