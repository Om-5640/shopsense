'use client'

import { usePathname } from 'next/navigation'
import Link from 'next/link'
import { Search, Sun, Moon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { UserMenu } from '@/components/auth/user-menu'
import { useTheme } from 'next-themes'
import { useEffect, useState } from 'react'

const navItems = [
  { label: 'Home',     href: '/' },
  { label: 'History',  href: '/history' },
  { label: 'Compare',  href: '/compare' },
  { label: 'Memory',   href: '/memory' },
  { label: 'Settings', href: '/settings' },
]

export function Header({ onOpenCommandPalette }: { onOpenCommandPalette?: () => void }) {
  const pathname = usePathname()
  const { theme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)

  useEffect(() => { setMounted(true) }, [])

  const isDark = !mounted || theme === 'dark'

  return (
    <header className="sticky top-0 z-50 h-[60px] backdrop-blur-xl bg-black/40 border-b border-white/[0.06]">
      <div className="max-w-7xl mx-auto h-full px-4 flex items-center justify-between">

        {/* Logo */}
        <Link href="/" className="flex items-center gap-2.5 group flex-shrink-0">
          <div className="relative w-8 h-8">
            <div className="absolute inset-0 rounded-full border-2 border-violet-400/80 group-hover:border-violet-400 transition-colors" />
            <div className="absolute inset-1.5 rounded-full border border-violet-400/60" />
            <div className="absolute inset-3 rounded-full bg-violet-400/80" />
          </div>
          <span className="font-semibold text-[#FAFAFA] tracking-tight">ShopResearch</span>
        </Link>

        {/* Center Navigation */}
        <nav className="hidden md:flex items-center gap-0.5">
          {navItems.map((item) => {
            const isActive = pathname === item.href
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'px-3.5 py-1.5 rounded-full text-sm font-medium transition-all duration-200',
                  isActive
                    ? 'bg-white/[0.08] text-[#FAFAFA]'
                    : 'text-[#A1A1AA] hover:text-[#FAFAFA] hover:bg-white/[0.04]',
                )}
              >
                {item.label}
              </Link>
            )
          })}
        </nav>

        {/* Right Section */}
        <div className="flex items-center gap-2">

          {/* ⌘K search pill */}
          <button
            onClick={onOpenCommandPalette}
            className="hidden sm:flex items-center gap-2 h-8 px-3 rounded-lg border border-white/[0.08] bg-white/[0.03] text-[#71717A] hover:text-[#A1A1AA] hover:border-white/[0.12] hover:bg-white/[0.05] transition-all duration-200"
          >
            <Search className="w-3.5 h-3.5" />
            <span className="text-xs hidden lg:inline text-[#52525B]">Search…</span>
            <kbd className="hidden lg:inline-flex items-center gap-0.5 ml-1 rounded border border-white/[0.1] bg-white/[0.04] px-1.5 py-0.5 text-[10px] font-medium text-[#3F3F46]">
              ⌘K
            </kbd>
          </button>

          {/* Live status dot */}
          <div className="hidden sm:block relative">
            <div className="w-2 h-2 rounded-full bg-emerald-500" />
            <div className="absolute inset-0 w-2 h-2 rounded-full bg-emerald-500 animate-ping opacity-60" />
          </div>

          {/* Theme toggle — real dark/light switch */}
          <button
            onClick={() => setTheme(isDark ? 'light' : 'dark')}
            className="w-9 h-9 flex items-center justify-center rounded-lg text-[#71717A] hover:text-[#FAFAFA] hover:bg-white/[0.05] transition-all duration-200"
            aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {mounted && (
              isDark
                ? <Sun className="w-4 h-4" />
                : <Moon className="w-4 h-4" />
            )}
          </button>

          {/* User account */}
          <UserMenu />
        </div>
      </div>
    </header>
  )
}
