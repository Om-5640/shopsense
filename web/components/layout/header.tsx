'use client'

import { usePathname } from 'next/navigation'
import Link from 'next/link'
import { Search, Sun, Moon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { UserMenu } from '@/components/auth/user-menu'
import { useTheme } from 'next-themes'
import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'

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
  const [mounted, setMounted]   = useState(false)
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => { setMounted(true) }, [])

  useEffect(() => {
    const handle = () => setScrolled(window.scrollY > 8)
    window.addEventListener('scroll', handle, { passive: true })
    handle()
    return () => window.removeEventListener('scroll', handle)
  }, [])

  const isDark = !mounted || theme === 'dark'

  return (
    <header
      className={cn(
        'sticky top-0 z-50 h-[60px] border-b transition-all duration-300',
        scrolled
          ? 'backdrop-blur-2xl bg-black/65 border-white/[0.09] shadow-[0_1px_30px_rgba(0,0,0,0.55)]'
          : 'backdrop-blur-xl  bg-black/40 border-white/[0.06]',
      )}
    >
      <div className="max-w-7xl mx-auto h-full px-4 flex items-center justify-between">

        {/* Logo */}
        <Link href="/" className="flex items-center gap-2.5 group flex-shrink-0">
          <motion.div
            className="relative w-8 h-8"
            whileHover={{ scale: 1.1 }}
            transition={{ type: 'spring', stiffness: 400, damping: 17 }}
          >
            <div className="absolute inset-0 rounded-full border-2 border-violet-400/80 group-hover:border-violet-400 transition-colors duration-200" />
            <div className="absolute inset-1.5 rounded-full border border-violet-400/60" />
            <div className="absolute inset-3 rounded-full bg-violet-400/80 group-hover:bg-violet-400 transition-colors duration-200" />
            {/* Subtle glow on hover */}
            <div className="absolute inset-0 rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-300"
              style={{ boxShadow: '0 0 16px rgba(167,139,250,0.5)' }} />
          </motion.div>
          <span className="font-semibold text-[#FAFAFA] tracking-tight group-hover:text-violet-200 transition-colors duration-200">
            ShopResearch
          </span>
        </Link>

        {/* Center Navigation — sliding active pill */}
        <nav className="hidden md:flex items-center gap-0.5">
          {navItems.map((item) => {
            const isActive = pathname === item.href
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'relative px-3.5 py-1.5 rounded-full text-sm font-medium transition-colors duration-200',
                  isActive
                    ? 'text-[#FAFAFA]'
                    : 'text-[#A1A1AA] hover:text-[#FAFAFA]',
                )}
              >
                {isActive && (
                  <motion.span
                    layoutId="nav-active-pill"
                    className="absolute inset-0 rounded-full bg-white/[0.09] border border-white/[0.08]"
                    transition={{ type: 'spring', stiffness: 380, damping: 30, mass: 0.8 }}
                  />
                )}
                <span className="relative z-10">{item.label}</span>
              </Link>
            )
          })}
        </nav>

        {/* Right section */}
        <div className="flex items-center gap-2">

          {/* ⌘K search pill */}
          <motion.button
            onClick={onOpenCommandPalette}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className="hidden sm:flex items-center gap-2 h-8 px-3 rounded-lg border border-white/[0.08] bg-white/[0.03] text-[#71717A] hover:text-[#A1A1AA] hover:border-white/[0.13] hover:bg-white/[0.06] transition-colors duration-200"
          >
            <Search className="w-3.5 h-3.5" />
            <span className="text-xs hidden lg:inline text-[#52525B]">Search…</span>
            <kbd className="hidden lg:inline-flex items-center ml-1 rounded border border-white/[0.1] bg-white/[0.04] px-1.5 py-0.5 text-[10px] font-medium text-[#3F3F46]">
              ⌘K
            </kbd>
          </motion.button>

          {/* Live status dot */}
          <div className="hidden sm:block relative">
            <div className="w-2 h-2 rounded-full bg-emerald-500" />
            <div className="absolute inset-0 w-2 h-2 rounded-full bg-emerald-500 animate-ping opacity-60" />
          </div>

          {/* Theme toggle */}
          <motion.button
            onClick={() => setTheme(isDark ? 'light' : 'dark')}
            whileHover={{ scale: 1.08, rotate: isDark ? 15 : -15 }}
            whileTap={{ scale: 0.92 }}
            className="w-9 h-9 flex items-center justify-center rounded-lg text-[#71717A] hover:text-[#FAFAFA] hover:bg-white/[0.06] transition-colors duration-200"
            aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {mounted && (isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />)}
          </motion.button>

          {/* User account */}
          <UserMenu />
        </div>
      </div>
    </header>
  )
}
