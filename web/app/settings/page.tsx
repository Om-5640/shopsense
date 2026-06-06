'use client'

import { useState, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import { useSession, signIn, signOut } from 'next-auth/react'
import {
  Globe, Cpu, Database, Trash2, Download, ExternalLink,
  Github, FileText, AlertCircle, LogIn, LogOut,
  ShieldCheck, RefreshCw, Star, Brain,
} from 'lucide-react'
import { AnimatedBackground } from '@/components/layout/animated-background'
import { Header } from '@/components/layout/header'
import { CommandPalette } from '@/components/layout/command-palette'
import { Footer } from '@/components/layout/footer'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader,
  AlertDialogTitle, AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { toast } from 'sonner'
import { getProvidersStatus, wipeAllMemory } from '@/lib/api'
import { useAppStore } from '@/lib/store'
import Image from 'next/image'
import Link from 'next/link'

interface ProviderStatus {
  id: string
  name: string
  model: string
  status: 'active' | 'quota' | 'inactive' | 'error'
  requests_today?: number
  last_error?: string | null
}

const FADE_UP = { initial: { opacity: 0, y: 20 }, animate: { opacity: 1, y: 0 } }

function SectionCard({
  children, delay = 0, className = '',
}: { children: React.ReactNode; delay?: number; className?: string }) {
  return (
    <motion.section
      {...FADE_UP}
      transition={{ duration: 0.4, delay }}
      className={`rounded-2xl bg-white/[0.025] border border-white/[0.06] p-6 ${className}`}
    >
      {children}
    </motion.section>
  )
}

function SectionHeader({
  icon, iconBg, iconColor, title, subtitle,
}: {
  icon: React.ReactNode
  iconBg: string
  iconColor: string
  title: string
  subtitle: string
}) {
  return (
    <div className="flex items-center gap-3 mb-6">
      <div className={`w-10 h-10 rounded-xl ${iconBg} flex items-center justify-center flex-shrink-0`}>
        <div className={iconColor}>{icon}</div>
      </div>
      <div>
        <h2 className="text-base font-semibold text-[#FAFAFA]">{title}</h2>
        <p className="text-sm text-[#52525B]">{subtitle}</p>
      </div>
    </div>
  )
}

export default function SettingsPage() {
  const [commandOpen, setCommandOpen] = useState(false)
  const [region, setRegion] = useState('us')
  const [providers, setProviders] = useState<ProviderStatus[]>([])

  // Load persisted region on mount
  useEffect(() => {
    const saved = typeof window !== 'undefined' ? localStorage.getItem('shopsense_region') : null
    if (saved) setRegion(saved)
  }, [])

  const handleRegionChange = (val: string) => {
    setRegion(val)
    localStorage.setItem('shopsense_region', val)
  }
  const [providersLoading, setProvidersLoading] = useState(true)
  const { data: session, status: authStatus } = useSession()
  const { clearHistory } = useAppStore()

  const loadProviders = useCallback(async () => {
    try {
      const { providers: ps } = await getProvidersStatus()
      setProviders(ps)
    } catch {
      // silently fail — provider endpoint may not be available
    } finally {
      setProvidersLoading(false)
    }
  }, [])

  useEffect(() => {
    loadProviders()
    const interval = setInterval(loadProviders, 10_000)
    return () => clearInterval(interval)
  }, [loadProviders])

  const handleExportData = () => {
    const data = {
      searchHistory: useAppStore.getState().searchHistory,
      exportedAt: new Date().toISOString(),
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'shopresearch-data.json'
    a.click()
    URL.revokeObjectURL(url)
    toast.success('Data exported successfully')
  }

  const handleClearAllData = async () => {
    try {
      await wipeAllMemory()
    } catch { /* best-effort */ }
    clearHistory()
    toast.success('All data cleared')
  }

  const getStatusBadge = (status: string) => {
    const variants: Record<string, { dot: string; text: string; label: string }> = {
      active:   { dot: 'bg-emerald-500', text: 'text-emerald-400', label: 'Active' },
      quota:    { dot: 'bg-amber-500',   text: 'text-amber-400',   label: 'Quota exceeded' },
      inactive: { dot: 'bg-[#3F3F46]',   text: 'text-[#71717A]',  label: 'Inactive' },
      error:    { dot: 'bg-rose-500',    text: 'text-rose-400',    label: 'Error' },
    }
    const v = variants[status] ?? variants.inactive
    return (
      <span className={`inline-flex items-center gap-1.5 text-xs ${v.text}`}>
        <span className={`w-1.5 h-1.5 rounded-full ${v.dot}`} />
        {v.label}
      </span>
    )
  }

  const isAuthenticated = authStatus === 'authenticated' && !!session
  const isLoading = authStatus === 'loading'

  return (
    <div className="min-h-screen flex flex-col bg-[#08080A]">
      <AnimatedBackground />
      <Header onOpenCommandPalette={() => setCommandOpen(true)} />
      <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} />

      <main className="flex-1 relative z-10">
        <div className="max-w-3xl mx-auto px-4 py-10">
          <motion.h1
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-2xl font-bold text-[#FAFAFA] mb-8"
          >
            Settings
          </motion.h1>

          <div className="space-y-6">

            {/* ── Account ── */}
            <SectionCard delay={0}>
              <SectionHeader
                icon={<Star className="w-5 h-5" />}
                iconBg="bg-violet-500/15"
                iconColor="text-violet-400"
                title="Account"
                subtitle={isAuthenticated ? 'Your profile and preferences' : 'Sign in for cross-device access'}
              />

              {isLoading ? (
                <div className="flex items-center gap-3 py-2">
                  <div className="w-4 h-4 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
                  <span className="text-sm text-[#52525B]">Loading account…</span>
                </div>
              ) : isAuthenticated ? (
                <>
                  {/* Profile row */}
                  <div className="flex items-start gap-4 mb-6">
                    <div className="relative w-16 h-16 rounded-full overflow-hidden ring-2 ring-violet-500/30 flex-shrink-0 shadow-lg">
                      {session.user.image ? (
                        <Image
                          src={session.user.image}
                          alt={session.user.name ?? 'User'}
                          fill
                          sizes="64px"
                          className="object-cover"
                        />
                      ) : (
                        <div className="w-full h-full bg-gradient-to-br from-violet-500 to-purple-700 flex items-center justify-center">
                          <span className="text-lg font-bold text-white">
                            {(session.user.name ?? '?')[0].toUpperCase()}
                          </span>
                        </div>
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="text-lg font-semibold text-[#FAFAFA] truncate leading-tight">
                        {session.user.name}
                      </h3>
                      <p className="text-sm text-[#71717A] truncate mt-0.5">{session.user.email}</p>
                      <div className="flex items-center gap-2 mt-2.5">
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-white/[0.04] border border-white/[0.08] text-xs text-[#A1A1AA]">
                          <svg className="w-3 h-3" viewBox="0 0 24 24">
                            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" />
                            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                          </svg>
                          Google account
                        </span>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => signOut({ callbackUrl: '/' })}
                      className="flex-shrink-0 text-[#52525B] hover:text-rose-400 hover:bg-rose-500/[0.06] gap-1.5 text-xs rounded-lg"
                    >
                      <LogOut className="w-3.5 h-3.5" />
                      Sign out
                    </Button>
                  </div>

                  {/* Cross-device sync notice */}
                  <div className="flex items-start gap-3 px-4 py-3 rounded-xl bg-violet-500/[0.06] border border-violet-500/[0.15] mb-6">
                    <ShieldCheck className="w-4 h-4 text-violet-400 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="text-sm font-medium text-violet-300">Cross-device sync active</p>
                      <p className="text-xs text-[#71717A] mt-0.5">
                        Your searches, memory, and preferences are tied to your Google account and accessible on any device you sign in to.
                      </p>
                    </div>
                  </div>
                </>
              ) : (
                /* Guest state */
                <div className="flex items-start gap-4 mb-6 p-4 rounded-xl bg-white/[0.02] border border-white/[0.05]">
                  <div className="w-12 h-12 rounded-full bg-white/[0.05] border border-white/[0.08] flex items-center justify-center flex-shrink-0">
                    <Brain className="w-5 h-5 text-[#52525B]" />
                  </div>
                  <div className="flex-1">
                    <p className="text-sm font-medium text-[#FAFAFA]">Browsing as guest</p>
                    <p className="text-xs text-[#52525B] mt-0.5">
                      Searches are session-only. Sign in to save your memory and history across devices.
                    </p>
                    <Button
                      size="sm"
                      onClick={() => signIn('google')}
                      className="mt-3 h-8 bg-violet-600 hover:bg-violet-500 text-white text-xs gap-2 rounded-lg"
                    >
                      <LogIn className="w-3.5 h-3.5" />
                      Sign in with Google
                    </Button>
                  </div>
                </div>
              )}

              {/* Region preference */}
              <div>
                <Label htmlFor="region" className="text-sm text-[#A1A1AA] font-normal mb-2 block">
                  Default region
                </Label>
                <Select value={region} onValueChange={handleRegionChange}>
                  <SelectTrigger
                    id="region"
                    className="w-full sm:w-[220px] bg-white/[0.03] border-white/[0.07] text-[#FAFAFA] rounded-xl h-10"
                  >
                    <Globe className="w-4 h-4 mr-2 text-[#52525B]" />
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-[#0F0F12] border-white/[0.08] rounded-xl">
                    {[
                      ['us', 'United States'],
                      ['uk', 'United Kingdom'],
                      ['eu', 'Europe'],
                      ['in', 'India'],
                      ['au', 'Australia'],
                    ].map(([val, label]) => (
                      <SelectItem key={val} value={val} className="text-[#FAFAFA] hover:bg-white/[0.04]">
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </SectionCard>

            {/* ── Intelligence Providers ── */}
            <SectionCard delay={0.08}>
              <div className="flex items-center justify-between mb-6">
                <SectionHeader
                  icon={<Cpu className="w-5 h-5" />}
                  iconBg="bg-emerald-500/15"
                  iconColor="text-emerald-400"
                  title="Intelligence Providers"
                  subtitle="Live status — refreshes every 10 s"
                />
                <button
                  onClick={loadProviders}
                  className="text-[#52525B] hover:text-[#A1A1AA] transition-colors p-1.5 rounded-lg hover:bg-white/[0.04]"
                  aria-label="Refresh provider status"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                </button>
              </div>

              {providersLoading ? (
                <div className="flex items-center gap-3 py-4">
                  <div className="w-4 h-4 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
                  <span className="text-sm text-[#52525B]">Loading provider status…</span>
                </div>
              ) : providers.length === 0 ? (
                <p className="text-sm text-[#52525B] py-2">
                  No providers available. Check your server configuration.
                </p>
              ) : (
                <div className="space-y-2">
                  {providers.map((provider) => (
                    <div
                      key={provider.id}
                      className="flex items-center justify-between px-4 py-3 rounded-xl bg-white/[0.02] border border-white/[0.05]"
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2.5">
                          <span className="text-sm font-medium text-[#FAFAFA]">{provider.name}</span>
                          {getStatusBadge(provider.status)}
                        </div>
                        <p className="text-xs text-[#52525B] mt-0.5">Model: {provider.model}</p>
                      </div>
                      <div className="text-right flex-shrink-0 ml-4">
                        {provider.requests_today !== undefined && (
                          <p className="text-xs text-[#71717A]">{provider.requests_today} req/day</p>
                        )}
                        {provider.last_error && (
                          <p className="text-rose-400/80 text-xs flex items-center gap-1 justify-end mt-1">
                            <AlertCircle className="w-3 h-3 flex-shrink-0" />
                            <span className="truncate max-w-[120px]">{provider.last_error}</span>
                          </p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <p className="mt-4 text-xs text-[#3F3F46] flex items-center gap-1.5">
                <ShieldCheck className="w-3 h-3 flex-shrink-0" />
                API keys are configured server-side in the <code className="text-[#52525B] font-mono">.env</code> file.
              </p>
            </SectionCard>

            {/* ── Data ── */}
            <SectionCard delay={0.16}>
              <SectionHeader
                icon={<Database className="w-5 h-5" />}
                iconBg="bg-amber-500/15"
                iconColor="text-amber-400"
                title="Your Data"
                subtitle="Export or permanently clear everything"
              />
              <div className="space-y-3">
                <div className="flex items-center justify-between px-4 py-3 rounded-xl bg-white/[0.02] border border-white/[0.05]">
                  <div>
                    <p className="text-sm font-medium text-[#FAFAFA]">Export all data</p>
                    <p className="text-xs text-[#52525B] mt-0.5">Download your history as JSON</p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleExportData}
                    className="text-[#71717A] hover:text-[#FAFAFA] hover:bg-white/[0.04] gap-1.5 text-xs rounded-lg"
                  >
                    <Download className="w-3.5 h-3.5" />
                    Export
                  </Button>
                </div>

                <div className="flex items-center justify-between px-4 py-3 rounded-xl border border-rose-500/20 bg-rose-500/[0.04]">
                  <div>
                    <p className="text-sm font-medium text-rose-400">Clear all data</p>
                    <p className="text-xs text-[#52525B] mt-0.5">Permanently deletes all searches and memory</p>
                  </div>
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        size="sm"
                        variant="destructive"
                        className="bg-rose-600/80 hover:bg-rose-600 text-white gap-1.5 text-xs rounded-lg"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                        Clear
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent className="bg-[#0F0F12] border-white/[0.08] rounded-2xl">
                      <AlertDialogHeader>
                        <AlertDialogTitle className="text-[#FAFAFA]">Clear all data?</AlertDialogTitle>
                        <AlertDialogDescription className="text-[#71717A]">
                          This permanently deletes all your searches, memory signals, and preferences.
                          This action cannot be undone.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel className="bg-white/[0.04] border-white/[0.08] text-[#FAFAFA] hover:bg-white/[0.07] rounded-xl">
                          Cancel
                        </AlertDialogCancel>
                        <AlertDialogAction
                          onClick={handleClearAllData}
                          className="bg-rose-600 hover:bg-rose-500 rounded-xl"
                        >
                          Clear everything
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </div>
            </SectionCard>

            {/* ── About ── */}
            <SectionCard delay={0.24}>
              <h2 className="text-base font-semibold text-[#FAFAFA] mb-5">About</h2>
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-[#71717A]">Version</span>
                  <span className="font-mono text-sm text-[#A1A1AA]">v2.0.0</span>
                </div>
                <Separator className="bg-white/[0.05]" />
                <div className="flex flex-wrap gap-3">
                  <a
                    href="https://github.com/Om-5640/shopsense"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-white/[0.02] border border-white/[0.06] text-sm text-[#71717A] hover:text-[#FAFAFA] hover:border-white/[0.12] hover:bg-white/[0.04] transition-all duration-200"
                  >
                    <Github className="w-4 h-4" />
                    Source code
                    <ExternalLink className="w-3 h-3 opacity-60" />
                  </a>
                  <Link
                    href="/memory"
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-white/[0.02] border border-white/[0.06] text-sm text-[#71717A] hover:text-[#FAFAFA] hover:border-white/[0.12] hover:bg-white/[0.04] transition-all duration-200"
                  >
                    <Brain className="w-4 h-4" />
                    View Memory
                  </Link>
                </div>
              </div>
            </SectionCard>

          </div>
        </div>
      </main>

      <Footer />
    </div>
  )
}
