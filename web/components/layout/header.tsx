'use client'

import { usePathname } from 'next/navigation'
import Link from 'next/link'
import { Search, Sun, Moon, Menu, Home, Clock, BarChart3, Brain, Settings, X, LogIn, LogOut } from 'lucide-react'
import { cn } from '@/lib/utils'
import { UserMenu } from '@/components/auth/user-menu'
import { useTheme } from 'next-themes'
import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { useSession, signIn, signOut } from 'next-auth/react'
import Image from 'next/image'

// ── Nav items (shared between desktop + mobile sheet) ─────────────────────────

const NAV_ITEMS = [
  { label: 'Home',     href: '/',         icon: Home     },
  { label: 'History',  href: '/history',  icon: Clock    },
  { label: 'Compare',  href: '/compare',  icon: BarChart3 },
  { label: 'Memory',   href: '/memory',   icon: Brain    },
  { label: 'Settings', href: '/settings', icon: Settings },
]

// ── Mobile sheet nav ──────────────────────────────────────────────────────────

function MobileSheet({
  open,
  onClose,
  onOpenCommandPalette,
}: {
  open: boolean
  onClose: () => void
  onOpenCommandPalette?: () => void
}) {
  const pathname   = usePathname()
  const { theme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)
  const { data: session, status } = useSession()
  useEffect(() => { setMounted(true) }, [])

  const isDark = !mounted || theme === 'dark'

  function getInitials(name: string | null | undefined) {
    if (!name) return '?'
    return name.split(' ').filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('')
  }

  return (
    <Sheet open={open} onOpenChange={(v) => { if (!v) onClose() }}>
      <SheetContent
        side="right"
        className="w-[300px] bg-[#09090C]/95 backdrop-blur-2xl border-l border-white/[0.07] p-0 flex flex-col shadow-2xl [&>button]:hidden"
      >
        {/* Visually-hidden title for screen readers */}
        <SheetTitle className="sr-only">Navigation menu</SheetTitle>

        {/* Header row */}
        <div className="flex items-center justify-between px-5 h-[60px] border-b border-white/[0.06] flex-shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="relative w-6 h-6">
              <div className="absolute inset-0 rounded-full border border-violet-400/70" />
              <div className="absolute inset-[3px] rounded-full border border-violet-400/50" />
              <div className="absolute inset-[6px] rounded-full bg-violet-400/80" />
            </div>
            <span className="font-semibold text-[#FAFAFA] text-sm tracking-tight">ShopResearch</span>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg text-[#52525B] hover:text-[#FAFAFA] hover:bg-white/[0.06] transition-colors duration-150"
            aria-label="Close menu"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* User identity */}
        <div className="px-4 py-3.5 border-b border-white/[0.06] flex-shrink-0">
          {status === 'loading' ? (
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-full bg-white/[0.06] animate-pulse flex-shrink-0" />
              <div className="space-y-1.5 flex-1">
                <div className="h-3 w-24 rounded bg-white/[0.06] animate-pulse" />
                <div className="h-2.5 w-32 rounded bg-white/[0.04] animate-pulse" />
              </div>
            </div>
          ) : session ? (
            <div className="flex items-center gap-3">
              <div className="relative w-9 h-9 rounded-full overflow-hidden ring-1 ring-white/[0.12] flex-shrink-0">
                {session.user.image ? (
                  <Image
                    src={session.user.image}
                    alt={session.user.name ?? 'Avatar'}
                    width={36} height={36}
                    className="object-cover w-full h-full"
                  />
                ) : (
                  <div className="w-full h-full bg-gradient-to-br from-violet-500 to-purple-700 flex items-center justify-center">
                    <span className="text-xs font-semibold text-white">
                      {getInitials(session.user.name)}
                    </span>
                  </div>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-[#FAFAFA] truncate leading-tight">
                  {session.user.name}
                </p>
                <p className="text-xs text-[#52525B] truncate mt-0.5">{session.user.email}</p>
              </div>
            </div>
          ) : (
            <button
              onClick={() => { signIn('google'); onClose() }}
              className="w-full flex items-center justify-center gap-2.5 h-10 rounded-xl border border-white/[0.08] bg-white/[0.03] text-sm text-[#A1A1AA] hover:text-[#FAFAFA] hover:bg-white/[0.06] hover:border-white/[0.13] transition-all duration-150"
            >
              <LogIn className="w-4 h-4" />
              Sign in with Google
            </button>
          )}
        </div>

        {/* Nav links */}
        <nav className="flex-1 px-3 py-3 space-y-0.5 overflow-y-auto">
          {/* ⌘K search shortcut */}
          <button
            onClick={() => { onClose(); onOpenCommandPalette?.() }}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-[#71717A] hover:text-[#FAFAFA] hover:bg-white/[0.05] transition-colors duration-150 group"
          >
            <div className="w-8 h-8 rounded-lg bg-white/[0.03] border border-white/[0.06] flex items-center justify-center flex-shrink-0 group-hover:border-white/[0.10] transition-colors">
              <Search className="w-3.5 h-3.5" />
            </div>
            <span className="flex-1 text-left">Quick Search</span>
            <kbd className="inline-flex items-center rounded border border-white/[0.08] bg-white/[0.03] px-1.5 py-0.5 text-[10px] font-medium text-[#3F3F46]">
              ⌘K
            </kbd>
          </button>

          {/* Divider */}
          <div className="h-px bg-white/[0.05] mx-3 my-2" />

          {/* Page links */}
          {NAV_ITEMS.map((item) => {
            const isActive = pathname === item.href
            const Icon = item.icon
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onClose}
                className={cn(
                  'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-colors duration-150 group',
                  isActive
                    ? 'text-[#FAFAFA] bg-violet-500/[0.12] border border-violet-500/[0.18]'
                    : 'text-[#71717A] hover:text-[#FAFAFA] hover:bg-white/[0.05]',
                )}
              >
                <div className={cn(
                  'w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 transition-colors',
                  isActive
                    ? 'bg-violet-500/[0.18] border border-violet-500/[0.25]'
                    : 'bg-white/[0.03] border border-white/[0.06] group-hover:border-white/[0.10]',
                )}>
                  <Icon className={cn('w-3.5 h-3.5', isActive ? 'text-violet-400' : '')} />
                </div>
                <span>{item.label}</span>
                {isActive && (
                  <div className="ml-auto w-1.5 h-1.5 rounded-full bg-violet-400" />
                )}
              </Link>
            )
          })}
        </nav>

        {/* Footer: theme + sign-out */}
        <div className="px-4 py-4 border-t border-white/[0.06] flex-shrink-0 space-y-2">
          {/* Theme toggle row */}
          <button
            onClick={() => setTheme(isDark ? 'light' : 'dark')}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-[#71717A] hover:text-[#FAFAFA] hover:bg-white/[0.05] transition-colors duration-150"
          >
            <div className="w-8 h-8 rounded-lg bg-white/[0.03] border border-white/[0.06] flex items-center justify-center flex-shrink-0">
              {mounted && (isDark
                ? <Sun  className="w-3.5 h-3.5" />
                : <Moon className="w-3.5 h-3.5" />
              )}
            </div>
            <span>{mounted && (isDark ? 'Light mode' : 'Dark mode')}</span>
          </button>

          {/* Sign out (only when authenticated) */}
          {session && (
            <button
              onClick={() => { signOut({ callbackUrl: '/' }); onClose() }}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-rose-400/70 hover:text-rose-300 hover:bg-rose-500/[0.07] transition-colors duration-150"
            >
              <div className="w-8 h-8 rounded-lg bg-white/[0.03] border border-white/[0.06] flex items-center justify-center flex-shrink-0">
                <LogOut className="w-3.5 h-3.5" />
              </div>
              <span>Sign out</span>
            </button>
          )}

          {/* Live status */}
          <div className="flex items-center gap-2 px-3 pt-1">
            <div className="relative">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              <div className="absolute inset-0 w-1.5 h-1.5 rounded-full bg-emerald-500 animate-ping opacity-60" />
            </div>
            <span className="text-[11px] text-[#3F3F46]">Live research active</span>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}

// ── Main header ───────────────────────────────────────────────────────────────

export function Header({ onOpenCommandPalette }: { onOpenCommandPalette?: () => void }) {
  const pathname = usePathname()
  const { theme, setTheme } = useTheme()
  const [mounted, setMounted]   = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => { setMounted(true) }, [])

  useEffect(() => {
    const handle = () => setScrolled(window.scrollY > 8)
    window.addEventListener('scroll', handle, { passive: true })
    handle()
    return () => window.removeEventListener('scroll', handle)
  }, [])

  // Close mobile sheet whenever the route changes
  useEffect(() => { setMobileOpen(false) }, [pathname])

  const isDark = !mounted || theme === 'dark'

  return (
    <>
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
              <div className="absolute inset-0 rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-300"
                style={{ boxShadow: '0 0 16px rgba(167,139,250,0.5)' }} />
            </motion.div>
            <span className="font-semibold text-[#FAFAFA] tracking-tight group-hover:text-violet-200 transition-colors duration-200">
              ShopResearch
            </span>
          </Link>

          {/* Center Navigation — desktop only, sliding active pill */}
          <nav className="hidden md:flex items-center gap-0.5">
            {NAV_ITEMS.map((item) => {
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

            {/* ⌘K search pill — desktop */}
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

            {/* Live status dot — desktop */}
            <div className="hidden sm:block relative">
              <div className="w-2 h-2 rounded-full bg-emerald-500" />
              <div className="absolute inset-0 w-2 h-2 rounded-full bg-emerald-500 animate-ping opacity-60" />
            </div>

            {/* Theme toggle — desktop */}
            <motion.button
              onClick={() => setTheme(isDark ? 'light' : 'dark')}
              whileHover={{ scale: 1.08, rotate: isDark ? 15 : -15 }}
              whileTap={{ scale: 0.92 }}
              className="hidden md:flex w-9 h-9 items-center justify-center rounded-lg text-[#71717A] hover:text-[#FAFAFA] hover:bg-white/[0.06] transition-colors duration-200"
              aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {mounted && (isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />)}
            </motion.button>

            {/* User account — desktop */}
            <div className="hidden md:block">
              <UserMenu />
            </div>

            {/* Hamburger — mobile only */}
            <motion.button
              onClick={() => setMobileOpen(true)}
              whileHover={{ scale: 1.06 }}
              whileTap={{ scale: 0.94 }}
              className="md:hidden w-9 h-9 flex items-center justify-center rounded-lg text-[#71717A] hover:text-[#FAFAFA] hover:bg-white/[0.06] transition-colors duration-200"
              aria-label="Open navigation menu"
            >
              <AnimatePresence mode="wait" initial={false}>
                <motion.span
                  key={mobileOpen ? 'x' : 'menu'}
                  initial={{ opacity: 0, rotate: mobileOpen ? -90 : 90, scale: 0.7 }}
                  animate={{ opacity: 1, rotate: 0, scale: 1 }}
                  exit={{ opacity: 0, rotate: mobileOpen ? 90 : -90, scale: 0.7 }}
                  transition={{ duration: 0.18, ease: 'easeOut' }}
                  className="flex items-center justify-center"
                >
                  {mobileOpen ? <X className="w-4.5 h-4.5" /> : <Menu className="w-4.5 h-4.5" />}
                </motion.span>
              </AnimatePresence>
            </motion.button>

          </div>
        </div>
      </header>

      {/* Mobile sheet nav */}
      <MobileSheet
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        onOpenCommandPalette={onOpenCommandPalette}
      />
    </>
  )
}
