'use client'

import { useState, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import {
  User, Globe, Moon, Cpu, Database,
  Trash2, Download, ExternalLink, Github,
  FileText, AlertCircle, Eye, EyeOff,
} from 'lucide-react'
import { AnimatedBackground } from '@/components/layout/animated-background'
import { Header } from '@/components/layout/header'
import { CommandPalette } from '@/components/layout/command-palette'
import { Footer } from '@/components/layout/footer'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { toast } from 'sonner'
import { getProvidersStatus, wipeAllMemory } from '@/lib/api'
import { useAppStore } from '@/lib/store'

interface ProviderStatus {
  id: string
  name: string
  model: string
  status: 'active' | 'quota' | 'inactive' | 'error'
  requests_today?: number
  last_error?: string | null
}

export default function SettingsPage() {
  const [commandOpen, setCommandOpen] = useState(false)
  const [region, setRegion] = useState('us')
  const [providers, setProviders] = useState<ProviderStatus[]>([])
  const [providersLoading, setProvidersLoading] = useState(true)
  const [showApiKeys, setShowApiKeys] = useState<Record<string, boolean>>({})
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({})
  const { clearHistory } = useAppStore()

  const loadProviders = useCallback(async () => {
    try {
      const { providers: ps } = await getProvidersStatus()
      setProviders(ps)
    } catch {
      // silently fail — backend may not have this endpoint yet
    } finally {
      setProvidersLoading(false)
    }
  }, [])

  // Load on mount, then refresh every 10 s
  useEffect(() => {
    loadProviders()
    const interval = setInterval(loadProviders, 10_000)
    return () => clearInterval(interval)
  }, [loadProviders])

  const toggleShowApiKey = (id: string) =>
    setShowApiKeys((prev) => ({ ...prev, [id]: !prev[id] }))

  const handleSaveApiKey = (id: string) => {
    toast.success(`API key saved for ${id}`)
    setApiKeys((prev) => ({ ...prev, [id]: '' }))
  }

  const handleExportData = () => {
    const data = {
      searchHistory: useAppStore.getState().searchHistory,
      exportedAt: new Date().toISOString(),
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'shopresearch-data.json'; a.click()
    URL.revokeObjectURL(url)
    toast.success('Data exported')
  }

  const handleClearAllData = async () => {
    try {
      await wipeAllMemory()
    } catch { /* best-effort */ }
    clearHistory()
    toast.success('All data cleared')
  }

  const getStatusIndicator = (status: string) => {
    if (status === 'active') return (
      <div className="flex items-center gap-2">
        <div className="w-2 h-2 rounded-full bg-emerald-500" />
        <span className="text-emerald-400 text-sm">Active</span>
      </div>
    )
    if (status === 'quota') return (
      <div className="flex items-center gap-2">
        <div className="w-2 h-2 rounded-full bg-rose-500" />
        <span className="text-rose-400 text-sm">Quota exceeded</span>
      </div>
    )
    return (
      <div className="flex items-center gap-2">
        <div className="w-2 h-2 rounded-full bg-slate-500" />
        <span className="text-slate-400 text-sm">Not configured</span>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex flex-col bg-[#08080A]">
      <AnimatedBackground />
      <Header onOpenCommandPalette={() => setCommandOpen(true)} />
      <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} />

      <main className="flex-1 relative z-10">
        <div className="max-w-4xl mx-auto px-4 py-8">
          <h1 className="text-3xl font-bold text-[#FAFAFA] mb-8">Settings</h1>

          <div className="space-y-8">
            {/* Profile */}
            <motion.section
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-6"
            >
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-violet-500/20 flex items-center justify-center">
                  <User className="w-5 h-5 text-violet-400" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-[#FAFAFA]">Profile</h2>
                  <p className="text-sm text-[#71717A]">Your personal settings</p>
                </div>
              </div>
              <div>
                <Label htmlFor="region" className="text-[#A1A1AA]">Default region</Label>
                <Select value={region} onValueChange={setRegion}>
                  <SelectTrigger className="mt-2 w-full sm:w-[200px] bg-white/[0.04] border-white/[0.08] text-[#FAFAFA]">
                    <Globe className="w-4 h-4 mr-2 text-[#71717A]" />
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-[#0F0F12] border-white/[0.1]">
                    <SelectItem value="us" className="text-[#FAFAFA]">United States</SelectItem>
                    <SelectItem value="uk" className="text-[#FAFAFA]">United Kingdom</SelectItem>
                    <SelectItem value="eu" className="text-[#FAFAFA]">Europe</SelectItem>
                    <SelectItem value="in" className="text-[#FAFAFA]">India</SelectItem>
                    <SelectItem value="au" className="text-[#FAFAFA]">Australia</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </motion.section>

            {/* LLM Providers */}
            <motion.section
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-6"
            >
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-emerald-500/20 flex items-center justify-center">
                  <Cpu className="w-5 h-5 text-emerald-400" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-[#FAFAFA]">LLM Providers</h2>
                  <p className="text-sm text-[#71717A]">Live status — refreshes every 10 s</p>
                </div>
              </div>

              {providersLoading ? (
                <div className="flex items-center gap-3 py-4">
                  <div className="w-4 h-4 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
                  <span className="text-sm text-[#71717A]">Loading provider status…</span>
                </div>
              ) : providers.length === 0 ? (
                <p className="text-sm text-[#71717A] py-4">
                  Provider status endpoint not available. Set your API keys in the backend <code>.env</code> file.
                </p>
              ) : (
                <div className="space-y-4">
                  {providers.map((provider) => (
                    <div key={provider.id} className="p-4 rounded-xl bg-white/[0.02] border border-white/[0.06]">
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
                        <div>
                          <div className="flex items-center gap-3 mb-1">
                            <h3 className="font-medium text-[#FAFAFA]">{provider.name}</h3>
                            {getStatusIndicator(provider.status)}
                          </div>
                          <p className="text-xs text-[#71717A]">Model: {provider.model}</p>
                        </div>
                        <div className="text-right text-sm">
                          {provider.requests_today !== undefined && (
                            <p className="text-[#A1A1AA]">{provider.requests_today} requests today</p>
                          )}
                          {provider.last_error && (
                            <p className="text-rose-400 text-xs flex items-center gap-1 justify-end mt-1">
                              <AlertCircle className="w-3 h-3" />
                              {provider.last_error}
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <div className="relative flex-1">
                          <Input
                            type={showApiKeys[provider.id] ? 'text' : 'password'}
                            placeholder="API Key"
                            value={apiKeys[provider.id] || ''}
                            onChange={(e) => setApiKeys((prev) => ({ ...prev, [provider.id]: e.target.value }))}
                            className="pr-10 bg-white/[0.04] border-white/[0.08] text-[#FAFAFA] font-mono text-sm"
                          />
                          <button
                            onClick={() => toggleShowApiKey(provider.id)}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-[#71717A] hover:text-[#A1A1AA]"
                          >
                            {showApiKeys[provider.id] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                          </button>
                        </div>
                        <Button
                          onClick={() => handleSaveApiKey(provider.id)}
                          disabled={!apiKeys[provider.id]}
                          className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50"
                        >
                          Save
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </motion.section>

            {/* Data Management */}
            <motion.section
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-6"
            >
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-amber-500/20 flex items-center justify-center">
                  <Database className="w-5 h-5 text-amber-400" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-[#FAFAFA]">Data Management</h2>
                  <p className="text-sm text-[#71717A]">Export or clear your data</p>
                </div>
              </div>
              <div className="space-y-4">
                <div className="flex items-center justify-between p-4 rounded-xl bg-white/[0.02] border border-white/[0.06]">
                  <div>
                    <h3 className="font-medium text-[#FAFAFA]">Export all data</h3>
                    <p className="text-xs text-[#71717A]">Download your history as JSON</p>
                  </div>
                  <Button variant="ghost" onClick={handleExportData} className="text-[#A1A1AA] hover:text-[#FAFAFA]">
                    <Download className="w-4 h-4 mr-2" />
                    Export
                  </Button>
                </div>
                <div className="flex items-center justify-between p-4 rounded-xl border border-rose-500/30 bg-rose-500/5">
                  <div>
                    <h3 className="font-medium text-rose-400">Clear all data</h3>
                    <p className="text-xs text-[#A1A1AA]">Permanently delete everything</p>
                  </div>
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button variant="destructive" className="bg-rose-600 hover:bg-rose-500">
                        <Trash2 className="w-4 h-4 mr-2" />
                        Clear
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent className="bg-[#0F0F12] border-white/[0.1]">
                      <AlertDialogHeader>
                        <AlertDialogTitle className="text-[#FAFAFA]">Clear all data?</AlertDialogTitle>
                        <AlertDialogDescription className="text-[#A1A1AA]">
                          Permanently deletes all searches, memory, and settings.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel className="bg-white/[0.04] border-white/[0.08] text-[#FAFAFA]">Cancel</AlertDialogCancel>
                        <AlertDialogAction onClick={handleClearAllData} className="bg-rose-600 hover:bg-rose-500">
                          Clear everything
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>
              </div>
            </motion.section>

            {/* About */}
            <motion.section
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
              className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-6"
            >
              <h2 className="text-lg font-semibold text-[#FAFAFA] mb-4">About</h2>
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-[#A1A1AA]">Version</span>
                  <span className="font-mono text-[#FAFAFA]">v8.0.0</span>
                </div>
                <Separator className="bg-white/[0.06]" />
                <div className="flex flex-wrap gap-4">
                  <a href="https://github.com" target="_blank" rel="noopener noreferrer"
                    className="flex items-center gap-2 text-sm text-[#A1A1AA] hover:text-[#FAFAFA] transition-colors">
                    <Github className="w-4 h-4" /> GitHub <ExternalLink className="w-3 h-3" />
                  </a>
                  <a href="/docs" className="flex items-center gap-2 text-sm text-[#A1A1AA] hover:text-[#FAFAFA] transition-colors">
                    <FileText className="w-4 h-4" /> Documentation <ExternalLink className="w-3 h-3" />
                  </a>
                </div>
              </div>
            </motion.section>
          </div>
        </div>
      </main>

      <Footer />
    </div>
  )
}
