'use client'

import { useSession, signIn, signOut } from 'next-auth/react'
import { LogIn, LogOut, Brain, Settings, Sparkles, Shield } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import Image from 'next/image'
import Link from 'next/link'
import { motion } from 'framer-motion'

function getInitials(name: string | null | undefined): string {
  if (!name) return '?'
  return name.split(' ').filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('')
}

function UserAvatar({ src, name, size = 36 }: { src?: string | null; name?: string | null; size?: number }) {
  if (src) {
    return (
      <Image
        src={src}
        alt={name ?? 'User'}
        width={size}
        height={size}
        className="object-cover w-full h-full"
      />
    )
  }
  const initials = getInitials(name)
  return (
    <div
      className="w-full h-full flex items-center justify-center select-none"
      style={{
        background: 'linear-gradient(135deg, #6D28D9 0%, #7C3AED 35%, #A855F7 65%, #4F46E5 100%)',
      }}
    >
      <span
        className="font-bold text-white tracking-wide"
        style={{ fontSize: Math.round(size * 0.37), textShadow: '0 1px 4px rgba(0,0,0,0.5)' }}
      >
        {initials}
      </span>
    </div>
  )
}

export function UserMenu() {
  const { data: session, status } = useSession()

  if (status === 'loading') {
    return <div className="w-9 h-9 rounded-full bg-white/[0.06] animate-pulse" />
  }

  if (!session) {
    return (
      <Button
        variant="ghost"
        size="sm"
        onClick={() => signIn('google')}
        className="flex items-center gap-2 text-[#71717A] hover:text-[#FAFAFA] hover:bg-white/[0.05] rounded-xl px-3 h-9 transition-all"
      >
        <LogIn className="w-3.5 h-3.5" />
        <span className="text-xs hidden sm:inline font-medium">Sign in</span>
      </Button>
    )
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <motion.button
          whileHover={{ scale: 1.07 }}
          whileTap={{ scale: 0.93 }}
          className="relative group focus:outline-none"
          aria-label="Account menu"
        >
          {/* Gradient glow ring — appears on hover */}
          <div
            className="absolute -inset-[3px] rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-300 blur-[1px]"
            style={{ background: 'linear-gradient(135deg, #7C3AED, #A855F7, #6366F1)' }}
          />
          {/* Avatar container */}
          <div
            className="relative w-9 h-9 rounded-full overflow-hidden ring-1 ring-white/[0.14] group-hover:ring-transparent transition-all duration-200 z-10"
          >
            <UserAvatar src={session.user.image} name={session.user.name} />
          </div>
          {/* Online dot */}
          <div
            className="absolute bottom-0 right-0 w-2.5 h-2.5 rounded-full bg-emerald-400 z-20"
            style={{ border: '2px solid #08080A' }}
          />
        </motion.button>
      </DropdownMenuTrigger>

      <DropdownMenuContent
        align="end"
        sideOffset={12}
        className="w-[268px] p-0 rounded-2xl overflow-hidden !bg-[#0E0E13] border-0"
        style={{
          background: '#0E0E13',
          colorScheme: 'dark',
          boxShadow: '0 24px 64px rgba(0,0,0,0.85), 0 0 0 1px rgba(255,255,255,0.07)',
        }}
      >
        {/* ── Header ─────────────────────────────────────────────────── */}
        <div
          className="relative px-4 py-4 overflow-hidden"
          style={{
            background: 'linear-gradient(135deg, rgba(109,40,217,0.20) 0%, rgba(168,85,247,0.10) 55%, rgba(79,70,229,0.14) 100%)',
            borderBottom: '1px solid rgba(255,255,255,0.06)',
          }}
        >
          {/* Dot grid texture */}
          <div
            className="absolute inset-0 opacity-[0.035]"
            style={{
              backgroundImage: 'radial-gradient(circle, #A78BFA 1px, transparent 1px)',
              backgroundSize: '14px 14px',
            }}
          />
          <div className="relative flex items-center gap-3.5">
            {/* Avatar with glow */}
            <div
              className="relative w-11 h-11 rounded-full overflow-hidden flex-shrink-0"
              style={{
                boxShadow: '0 0 0 2px rgba(167,139,250,0.5), 0 0 18px rgba(167,139,250,0.18)',
              }}
            >
              <UserAvatar src={session.user.image} name={session.user.name} size={44} />
            </div>
            {/* Identity */}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-white truncate leading-snug">
                {session.user.name}
              </p>
              <p className="text-xs text-[#6B7280] truncate mt-0.5">{session.user.email}</p>
              {/* Plan badge */}
              <div className="inline-flex items-center gap-1 mt-1.5 px-2 py-0.5 rounded-full border"
                style={{ background: 'rgba(139,92,246,0.12)', borderColor: 'rgba(139,92,246,0.28)' }}>
                <Sparkles className="w-2.5 h-2.5 text-violet-400" />
                <span className="text-[10px] font-semibold text-violet-300 tracking-wide uppercase">Free</span>
              </div>
            </div>
          </div>
        </div>

        {/* ── Nav items ──────────────────────────────────────────────── */}
        <div className="p-1.5 space-y-0.5">
          <DropdownMenuItem
            asChild
            className="rounded-xl px-3 py-2.5 cursor-pointer focus:!bg-white/[0.06] data-[highlighted]:!bg-white/[0.06] transition-colors"
          >
            <Link href="/memory" className="flex items-center gap-3 no-underline">
              <div
                className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                style={{ background: 'rgba(139,92,246,0.15)', border: '1px solid rgba(139,92,246,0.25)' }}
              >
                <Brain className="w-3.5 h-3.5 text-violet-400" />
              </div>
              <div className="flex flex-col min-w-0">
                <span className="text-sm font-medium text-[#E4E4E7] leading-snug">My Memory</span>
                <span className="text-[11px] text-[#52525B] mt-0.5">Signals &amp; preferences</span>
              </div>
            </Link>
          </DropdownMenuItem>

          <DropdownMenuItem
            asChild
            className="rounded-xl px-3 py-2.5 cursor-pointer focus:!bg-white/[0.06] data-[highlighted]:!bg-white/[0.06] transition-colors"
          >
            <Link href="/settings" className="flex items-center gap-3 no-underline">
              <div
                className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.09)' }}
              >
                <Settings className="w-3.5 h-3.5 text-[#71717A]" />
              </div>
              <div className="flex flex-col min-w-0">
                <span className="text-sm font-medium text-[#E4E4E7] leading-snug">Settings</span>
                <span className="text-[11px] text-[#52525B] mt-0.5">Account preferences</span>
              </div>
            </Link>
          </DropdownMenuItem>
        </div>

        {/* ── Divider ────────────────────────────────────────────────── */}
        <div className="mx-3 h-px" style={{ background: 'rgba(255,255,255,0.06)' }} />

        {/* ── Sign out ───────────────────────────────────────────────── */}
        <div className="p-1.5">
          <DropdownMenuItem
            onClick={() => signOut({ callbackUrl: '/' })}
            className="rounded-xl px-3 py-2.5 cursor-pointer focus:!bg-rose-500/[0.10] data-[highlighted]:!bg-rose-500/[0.10] transition-colors"
          >
            <div className="flex items-center gap-3 w-full">
              <div
                className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                style={{ background: 'rgba(239,68,68,0.10)', border: '1px solid rgba(239,68,68,0.20)' }}
              >
                <LogOut className="w-3.5 h-3.5 text-rose-400" />
              </div>
              <span className="text-sm font-medium text-rose-400/80">Sign out</span>
            </div>
          </DropdownMenuItem>
        </div>

        {/* ── Footer ─────────────────────────────────────────────────── */}
        <div
          className="flex items-center justify-center gap-1.5 py-2.5"
          style={{ borderTop: '1px solid rgba(255,255,255,0.04)', background: 'rgba(255,255,255,0.01)' }}
        >
          <Shield className="w-2.5 h-2.5 text-[#3F3F46]" />
          <span className="text-[10px] text-[#3F3F46]">Secured via Google OAuth</span>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
