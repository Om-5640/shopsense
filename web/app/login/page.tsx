'use client'

import { signIn, useSession } from 'next-auth/react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useEffect, Suspense } from 'react'
import { Loader2, Brain, History, Sliders } from 'lucide-react'
import { motion } from 'framer-motion'
import { AnimatedBackground } from '@/components/layout/animated-background'
import Link from 'next/link'

const FEATURES = [
  {
    icon: Brain,
    title: 'Persistent memory',
    desc: 'Preferences, avoided products, and past signals remembered across every search.',
  },
  {
    icon: History,
    title: 'Full research history',
    desc: 'Every ranked result saved — re-open, re-weight, or re-research on any device.',
  },
  {
    icon: Sliders,
    title: 'Personalized rubrics',
    desc: 'Your interview answers build a weighted scorecard unique to you, not generic rankings.',
  },
]

function LoginContent() {
  const { status } = useSession()
  const router = useRouter()
  const searchParams = useSearchParams()
  const next = searchParams.get('next') ?? '/'

  useEffect(() => {
    if (status === 'authenticated') router.replace(next)
  }, [status, router, next])

  if (status === 'loading' || status === 'authenticated') {
    return (
      <div className="min-h-screen bg-[#08080A] flex items-center justify-center">
        <Loader2 className="w-5 h-5 text-violet-400 animate-spin" />
      </div>
    )
  }

  return (
    <div className="relative min-h-screen bg-[#08080A] flex items-center justify-center px-4 py-12">
      <AnimatedBackground />

      <div className="relative z-10 w-full max-w-sm">
        {/* Logo */}
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="flex items-center justify-center gap-2.5 mb-10"
        >
          <Link href="/" className="flex items-center gap-2.5 group">
            <div className="relative w-9 h-9">
              <div className="absolute inset-0 rounded-full border-2 border-violet-400/70 group-hover:border-violet-400 transition-colors" />
              <div className="absolute inset-[5px] rounded-full border border-violet-400/50" />
              <div className="absolute inset-[9px] rounded-full bg-violet-400/80" />
            </div>
            <span className="font-semibold text-[#FAFAFA] text-lg tracking-tight">ShopResearch</span>
          </Link>
        </motion.div>

        {/* Sign-in card */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, delay: 0.05 }}
          className="bg-[#0D0D10] border border-white/[0.07] rounded-2xl p-7 shadow-2xl"
        >
          <div className="text-center mb-6">
            <h1 className="text-lg font-semibold text-[#FAFAFA] leading-tight">
              Sign in to your account
            </h1>
            <p className="text-sm text-[#52525B] mt-1.5">
              Save your research and preferences across all your devices
            </p>
          </div>

          {/* Google button */}
          <button
            onClick={() => signIn('google', { callbackUrl: next })}
            className="w-full flex items-center justify-center gap-3 bg-white hover:bg-white/90 active:bg-white/80 text-[#111] font-medium h-11 rounded-xl transition-all duration-150 shadow-sm"
          >
            <svg className="w-[18px] h-[18px] flex-shrink-0" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" />
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
            </svg>
            Continue with Google
          </button>

          {/* Divider */}
          <div className="flex items-center gap-3 my-5">
            <div className="flex-1 h-px bg-white/[0.06]" />
            <span className="text-xs text-[#3F3F46]">or</span>
            <div className="flex-1 h-px bg-white/[0.06]" />
          </div>

          {/* Guest option */}
          <Link
            href="/"
            className="w-full flex items-center justify-center h-10 rounded-xl border border-white/[0.07] bg-white/[0.02] text-sm text-[#71717A] hover:text-[#FAFAFA] hover:bg-white/[0.04] hover:border-white/[0.10] transition-all duration-150"
          >
            Continue as guest
          </Link>

          <p className="mt-5 text-center text-xs text-[#3F3F46] leading-relaxed">
            Guest mode works fully — no account required.
            <br />Sign in only to persist memory across devices.
          </p>
        </motion.div>

        {/* Feature highlights */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="mt-6 space-y-2"
        >
          {FEATURES.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.35, delay: 0.25 + i * 0.08 }}
              className="flex items-start gap-3 px-4 py-3 rounded-xl bg-white/[0.015] border border-white/[0.04]"
            >
              <div className="w-7 h-7 rounded-lg bg-violet-500/[0.12] flex items-center justify-center flex-shrink-0 mt-0.5">
                <f.icon className="w-3.5 h-3.5 text-violet-400" />
              </div>
              <div>
                <p className="text-xs font-medium text-[#A1A1AA]">{f.title}</p>
                <p className="text-xs text-[#52525B] mt-0.5 leading-relaxed">{f.desc}</p>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </div>
  )
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-[#08080A] flex items-center justify-center">
          <Loader2 className="w-5 h-5 text-violet-400 animate-spin" />
        </div>
      }
    >
      <LoginContent />
    </Suspense>
  )
}
