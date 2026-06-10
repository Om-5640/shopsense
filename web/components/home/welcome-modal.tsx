'use client'

import { useEffect, useState } from 'react'
import { signIn, useSession } from 'next-auth/react'
import { motion, AnimatePresence } from 'framer-motion'
import { Brain, History, Sliders, ArrowRight, X } from 'lucide-react'

const STORAGE_KEY = 'shopsense_welcome_seen'

const PERKS = [
  {
    icon: Brain,
    label: 'Persistent memory',
    desc: 'Preferences & signals saved across every search.',
  },
  {
    icon: History,
    label: 'Full research history',
    desc: 'Revisit every result on any device, any time.',
  },
  {
    icon: Sliders,
    label: 'Personalized rubrics',
    desc: 'Your interview builds a unique weighted scorecard.',
  },
]

export function WelcomeModal() {
  const { status } = useSession()
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (status === 'loading') return
    if (status === 'authenticated') return
    try {
      if (localStorage.getItem(STORAGE_KEY)) return
    } catch { /* ignore */ }
    // Small delay so the page paints first
    const t = setTimeout(() => setVisible(true), 500)
    return () => clearTimeout(t)
  }, [status])

  function dismiss() {
    try { localStorage.setItem(STORAGE_KEY, '1') } catch { /* ignore */ }
    setVisible(false)
  }

  function handleSignIn() {
    try { localStorage.setItem(STORAGE_KEY, '1') } catch { /* ignore */ }
    signIn('google', { callbackUrl: '/' })
  }

  return (
    <AnimatePresence>
      {visible && (
        <>
          {/* Backdrop */}
          <motion.div
            key="backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm"
            onClick={dismiss}
          />

          {/* Card */}
          <motion.div
            key="card"
            initial={{ opacity: 0, scale: 0.92, y: 24 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 16 }}
            transition={{ duration: 0.35, ease: [0.23, 1, 0.32, 1] }}
            className="fixed inset-0 z-[61] flex items-center justify-center px-4 pointer-events-none"
          >
            <div
              className="relative w-full max-w-[400px] rounded-2xl overflow-hidden pointer-events-auto"
              style={{
                background: '#0E0E13',
                boxShadow: '0 32px 80px rgba(0,0,0,0.9), 0 0 0 1px rgba(255,255,255,0.07)',
              }}
            >
              {/* Gradient header strip */}
              <div
                className="relative px-7 pt-8 pb-6 overflow-hidden"
                style={{
                  background: 'linear-gradient(135deg, rgba(109,40,217,0.22) 0%, rgba(168,85,247,0.10) 55%, rgba(79,70,229,0.16) 100%)',
                  borderBottom: '1px solid rgba(255,255,255,0.07)',
                }}
              >
                {/* Dot grid */}
                <div
                  className="absolute inset-0 opacity-[0.04]"
                  style={{
                    backgroundImage: 'radial-gradient(circle, #A78BFA 1px, transparent 1px)',
                    backgroundSize: '14px 14px',
                  }}
                />
                {/* Close */}
                <button
                  onClick={dismiss}
                  className="absolute top-4 right-4 w-7 h-7 rounded-lg flex items-center justify-center text-[#52525B] hover:text-[#A1A1AA] hover:bg-white/[0.06] transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>

                {/* Logo mark */}
                <div className="relative flex items-center gap-2.5 mb-4">
                  <div className="relative w-8 h-8">
                    <div className="absolute inset-0 rounded-full border-2 border-violet-400/80" />
                    <div className="absolute inset-[5px] rounded-full border border-violet-400/50" />
                    <div className="absolute inset-[9px] rounded-full bg-violet-400/80" />
                  </div>
                  <span className="font-semibold text-[#FAFAFA] tracking-tight">ShopResearch</span>
                </div>

                <h2 className="text-xl font-bold text-white leading-tight">
                  Welcome! How would<br />you like to continue?
                </h2>
                <p className="text-sm text-[#6B7280] mt-2 leading-relaxed">
                  Sign in to unlock memory & history, or jump straight in as a guest.
                </p>
              </div>

              {/* Body */}
              <div className="px-5 py-5 space-y-3">
                {/* Sign in button */}
                <button
                  onClick={handleSignIn}
                  className="group w-full flex items-center gap-3 bg-white hover:bg-white/90 active:bg-white/80 h-12 rounded-xl px-4 transition-all duration-150 shadow-sm"
                >
                  <svg className="w-[18px] h-[18px] flex-shrink-0" viewBox="0 0 24 24">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" />
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                  </svg>
                  <span className="flex-1 text-left text-sm font-semibold text-[#111]">
                    Continue with Google
                  </span>
                  <ArrowRight className="w-3.5 h-3.5 text-[#555] group-hover:translate-x-0.5 transition-transform" />
                </button>

                {/* Guest button */}
                <button
                  onClick={dismiss}
                  className="w-full flex items-center justify-center h-11 rounded-xl text-sm text-[#71717A] hover:text-[#FAFAFA] transition-all duration-150"
                  style={{
                    background: 'rgba(255,255,255,0.03)',
                    border: '1px solid rgba(255,255,255,0.08)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'rgba(255,255,255,0.05)'
                    e.currentTarget.style.borderColor = 'rgba(255,255,255,0.13)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'rgba(255,255,255,0.03)'
                    e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)'
                  }}
                >
                  Continue as guest
                </button>
              </div>

              {/* Perks */}
              <div
                className="px-5 pb-5 space-y-2"
                style={{ borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '16px' }}
              >
                <p className="text-[11px] text-[#3F3F46] mb-3 font-medium uppercase tracking-wider">
                  Why sign in?
                </p>
                {PERKS.map((p) => (
                  <div key={p.label} className="flex items-start gap-3">
                    <div
                      className="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0 mt-0.5"
                      style={{ background: 'rgba(139,92,246,0.14)', border: '1px solid rgba(139,92,246,0.22)' }}
                    >
                      <p.icon className="w-3 h-3 text-violet-400" />
                    </div>
                    <div>
                      <span className="text-xs font-medium text-[#A1A1AA]">{p.label}</span>
                      <span className="text-xs text-[#52525B]"> — {p.desc}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
