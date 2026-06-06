'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Brain,
  Heart,
  ThumbsDown,
  ShoppingBag,
  Trash2,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Sparkles,
  User,
  Tag,
} from 'lucide-react'
import { AnimatedBackground } from '@/components/layout/animated-background'
import { Header } from '@/components/layout/header'
import { CommandPalette } from '@/components/layout/command-palette'
import { Footer } from '@/components/layout/footer'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
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
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { formatDistanceToNow } from 'date-fns'
import { toast } from 'sonner'
import { listMemorySignals, deleteMemorySignal, listProductMemories, wipeAllMemory } from '@/lib/api'
import type { UserSignal, ProductMemory } from '@/lib/types'
import { useSession, signIn } from 'next-auth/react'

// ── helpers ──────────────────────────────────────────────────────────────────

function categoryLabel(cat: string) {
  if (!cat || cat === 'any') return 'All searches'
  return cat.charAt(0).toUpperCase() + cat.slice(1).replace('/', ' › ')
}

function strengthColor(s: string) {
  if (s === 'strong') return 'text-violet-300 bg-violet-500/15 border-violet-500/30'
  if (s === 'moderate') return 'text-blue-300 bg-blue-500/15 border-blue-500/30'
  return 'text-slate-300 bg-slate-500/15 border-slate-500/30'
}

function strengthLabel(s: string) {
  if (s === 'strong') return 'Confirmed'
  if (s === 'moderate') return 'Likely'
  return 'Possible'
}

function groupByCategory<T extends { category?: string }>(items: T[]): Map<string, T[]> {
  const map = new Map<string, T[]>()
  for (const item of items) {
    const key = item.category || 'any'
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(item)
  }
  // Sort: "any" first, then alphabetical
  return new Map(
    [...map.entries()].sort(([a], [b]) => {
      if (a === 'any') return -1
      if (b === 'any') return 1
      return a.localeCompare(b)
    }),
  )
}

// ── page ──────────────────────────────────────────────────────────────────────

export default function MemoryPage() {
  const { status: authStatus } = useSession()
  const [commandOpen, setCommandOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const fetchedRef = useRef(false)
  const [preferences, setPreferences] = useState<UserSignal[]>([])
  const [avoided, setAvoided] = useState<UserSignal[]>([])
  const [products, setProducts] = useState<ProductMemory[]>([])
  const [dangerExpanded, setDangerExpanded] = useState(false)
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set(['any']))

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [{ signals }, { products: prods }] = await Promise.all([
        listMemorySignals(200),
        listProductMemories(100),
      ])
      setPreferences(signals.filter((s) => s.signalType === 'preference' || s.signalType === 'purchase'))
      setAvoided(signals.filter((s) => s.signalType === 'rejection' || s.signalType === 'complaint'))
      setProducts(prods.filter((product) => product.status !== 'considered'))
    } catch {
      toast.error('Could not load memory')
    } finally {
      setLoading(false)
    }
  }, [])

  // Wait until auth resolves, then fetch exactly once.
  // useRef guard prevents double-fire from React StrictMode + authStatus cycling.
  useEffect(() => {
    if (authStatus === 'loading') return
    if (authStatus === 'unauthenticated') return
    if (fetchedRef.current) return
    fetchedRef.current = true
    reload()
  }, [authStatus, reload])

  async function handleRemoveSignal(id: string) {
    try {
      await deleteMemorySignal(id)
      setPreferences((p) => p.filter((s) => s.id !== id))
      setAvoided((a) => a.filter((s) => s.id !== id))
      toast.success('Insight removed')
    } catch {
      toast.error('Could not remove insight')
    }
  }

  async function handleClearAll() {
    try {
      await wipeAllMemory()
      setPreferences([])
      setAvoided([])
      setProducts([])
      toast.success('All memory cleared')
    } catch {
      toast.error('Could not clear memory')
    }
  }

  const toggleCategory = (key: string) =>
    setExpandedCategories((prev) => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })

  const prefGroups = groupByCategory(preferences)
  const avoidGroups = groupByCategory(avoided)
  const stats = { preferences: preferences.length, avoided: avoided.length, products: products.length }

  // Build a smart cross-category profile line from strong "any" signals
  const profileLines = preferences
    .filter((s) => (s.category === 'any' || !s.category) && s.strength === 'strong')
    .slice(0, 4)
    .map((s) => s.text)

  // While NextAuth is resolving the session, show a neutral spinner.
  if (authStatus === 'loading') {
    return (
      <div className="min-h-screen flex flex-col bg-[#08080A]">
        <AnimatedBackground />
        <Header onOpenCommandPalette={() => setCommandOpen(true)} />
        <main className="flex-1 relative z-10 flex items-center justify-center">
          <div className="w-6 h-6 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
        </main>
      </div>
    )
  }

  // Show in-page sign-in card for guests (no redirect, graceful fallback).
  if (authStatus === 'unauthenticated') {
    return (
      <div className="min-h-screen flex flex-col bg-[#08080A]">
        <AnimatedBackground />
        <Header onOpenCommandPalette={() => setCommandOpen(true)} />
        <main className="flex-1 relative z-10 flex items-center justify-center px-4">
          <div className="bg-[#0F0F12] border border-white/[0.08] rounded-2xl p-8 max-w-sm w-full text-center shadow-2xl">
            <Brain className="w-10 h-10 text-violet-400 mx-auto mb-4" />
            <h2 className="text-lg font-semibold text-[#FAFAFA] mb-2">Sign in to view your memory</h2>
            <p className="text-sm text-[#71717A] mb-6">
              Memory is saved per account so you can access it on any device.
            </p>
            <Button
              onClick={() => signIn('google', { callbackUrl: '/memory' })}
              className="w-full bg-white hover:bg-white/90 text-[#0F0F12] font-medium h-10 rounded-lg"
            >
              Sign in with Google
            </Button>
          </div>
        </main>
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
          <div className="mb-8">
            <h1 className="text-3xl font-bold text-[#FAFAFA] mb-2">Your Memory</h1>
            <p className="text-[#71717A]">What ShopResearch remembers about you across all searches</p>
          </div>

          {/* Profile summary card — only when we have strong cross-category signals */}
          {!loading && profileLines.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              className="mb-6 p-5 rounded-2xl bg-violet-500/[0.06] border border-violet-500/20"
            >
              <div className="flex items-center gap-2 mb-3">
                <Sparkles className="w-4 h-4 text-violet-400" />
                <span className="text-sm font-medium text-violet-300">What we know about you</span>
                <span className="text-xs text-[#71717A]">· shapes all your searches</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {profileLines.map((line, i) => (
                  <span key={i} className="px-3 py-1 rounded-full text-sm bg-white/[0.06] text-[#FAFAFA] border border-white/[0.08]">
                    {line}
                  </span>
                ))}
              </div>
            </motion.div>
          )}

          {/* Stats */}
          <div className="grid grid-cols-3 gap-3 mb-8">
            {[
              { icon: Heart,       label: 'Preferences',     count: stats.preferences, color: 'violet' },
              { icon: ThumbsDown,  label: 'Avoided',         count: stats.avoided,    color: 'rose' },
              { icon: ShoppingBag, label: 'Products tracked', count: stats.products,  color: 'emerald' },
            ].map(({ icon: Icon, label, count, color }, i) => (
              <motion.div
                key={label}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.08 }}
                className="p-4 rounded-2xl bg-white/[0.02] border border-white/[0.06] text-center"
              >
                <Icon className={`w-4 h-4 mx-auto mb-2 text-${color}-400`} />
                <div className="text-2xl font-bold text-[#FAFAFA]">{loading ? '—' : count}</div>
                <div className="text-xs text-[#71717A] mt-0.5">{label}</div>
              </motion.div>
            ))}
          </div>

          {loading ? (
            <div className="flex justify-center py-12">
              <div className="w-6 h-6 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : (
            <Tabs defaultValue="preferences" className="mb-8">
              <TabsList className="w-full grid grid-cols-3 bg-white/[0.04] rounded-xl p-1 mb-6">
                <TabsTrigger value="preferences" className="data-[state=active]:bg-white/[0.08] data-[state=active]:text-[#FAFAFA] rounded-lg">
                  Preferences {preferences.length > 0 && <span className="ml-1.5 text-xs text-violet-400">{preferences.length}</span>}
                </TabsTrigger>
                <TabsTrigger value="avoided" className="data-[state=active]:bg-white/[0.08] data-[state=active]:text-[#FAFAFA] rounded-lg">
                  Avoided {avoided.length > 0 && <span className="ml-1.5 text-xs text-rose-400">{avoided.length}</span>}
                </TabsTrigger>
                <TabsTrigger value="products" className="data-[state=active]:bg-white/[0.08] data-[state=active]:text-[#FAFAFA] rounded-lg">
                  Products {products.length > 0 && <span className="ml-1.5 text-xs text-emerald-400">{products.length}</span>}
                </TabsTrigger>
              </TabsList>

              <TabsContent value="preferences">
                {preferences.length === 0 ? (
                  <EmptyState icon={Heart} title="No preferences yet" description="Complete interviews in your searches to build your permanent preference profile" />
                ) : (
                  <CategoryGroupList
                    groups={prefGroups}
                    expandedCategories={expandedCategories}
                    onToggle={toggleCategory}
                    onRemove={handleRemoveSignal}
                    accentColor="violet"
                  />
                )}
              </TabsContent>

              <TabsContent value="avoided">
                {avoided.length === 0 ? (
                  <EmptyState icon={ThumbsDown} title="Nothing to avoid" description="Products or features you dislike will appear here after your searches" />
                ) : (
                  <CategoryGroupList
                    groups={avoidGroups}
                    expandedCategories={expandedCategories}
                    onToggle={toggleCategory}
                    onRemove={handleRemoveSignal}
                    accentColor="rose"
                  />
                )}
              </TabsContent>

              <TabsContent value="products">
                {products.length === 0 ? (
                  <EmptyState icon={ShoppingBag} title="No products tracked" description="Purchased, rejected, or returned products will be saved here" />
                ) : (
                  <div className="space-y-3">
                    <AnimatePresence mode="popLayout">
                      {products.map((product) => (
                        <ProductMemoryCard key={product.id} product={product} />
                      ))}
                    </AnimatePresence>
                  </div>
                )}
              </TabsContent>
            </Tabs>
          )}

          {/* Danger zone */}
          <Collapsible open={dangerExpanded} onOpenChange={setDangerExpanded}>
            <CollapsibleTrigger asChild>
              <button className="flex items-center gap-2 text-sm text-[#71717A] hover:text-[#A1A1AA] transition-colors">
                <AlertTriangle className="w-4 h-4" />
                Danger zone
                <ChevronDown className={`w-4 h-4 transition-transform ${dangerExpanded ? 'rotate-180' : ''}`} />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="mt-4 p-4 rounded-xl border border-rose-500/30 bg-rose-500/5">
                <h4 className="font-medium text-rose-400 mb-1">Clear all memory</h4>
                <p className="text-sm text-[#A1A1AA] mb-4">
                  Permanently deletes all preferences, avoidances, and product history. Future searches start from scratch.
                </p>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button variant="destructive" size="sm" className="bg-rose-600 hover:bg-rose-500">
                      Clear all memory
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent className="bg-[#0F0F12] border-white/[0.1]">
                    <AlertDialogHeader>
                      <AlertDialogTitle className="text-[#FAFAFA]">Are you sure?</AlertDialogTitle>
                      <AlertDialogDescription className="text-[#A1A1AA]">
                        This permanently deletes all your preferences and product history. It cannot be undone.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel className="bg-white/[0.04] border-white/[0.08] text-[#FAFAFA]">Cancel</AlertDialogCancel>
                      <AlertDialogAction onClick={handleClearAll} className="bg-rose-600 hover:bg-rose-500">
                        Clear everything
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            </CollapsibleContent>
          </Collapsible>
        </div>
      </main>

      <Footer />
    </div>
  )
}

// ── CategoryGroupList ─────────────────────────────────────────────────────────

function CategoryGroupList({
  groups,
  expandedCategories,
  onToggle,
  onRemove,
  accentColor,
}: {
  groups: Map<string, UserSignal[]>
  expandedCategories: Set<string>
  onToggle: (key: string) => void
  onRemove: (id: string) => void
  accentColor: 'violet' | 'rose'
}) {
  return (
    <div className="space-y-3">
      {[...groups.entries()].map(([category, signals]) => {
        const isOpen = expandedCategories.has(category)
        const label = categoryLabel(category)
        const isCrossCategory = category === 'any'

        return (
          <div
            key={category}
            className="rounded-xl border border-white/[0.06] bg-white/[0.02] overflow-hidden"
          >
            <button
              onClick={() => onToggle(category)}
              className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-white/[0.02] transition-colors"
            >
              <div className="flex items-center gap-2">
                {isCrossCategory ? (
                  <User className="w-4 h-4 text-violet-400" />
                ) : (
                  <Tag className="w-4 h-4 text-[#71717A]" />
                )}
                <span className="text-sm font-medium text-[#FAFAFA]">{label}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${
                  accentColor === 'violet'
                    ? 'bg-violet-500/15 text-violet-300'
                    : 'bg-rose-500/15 text-rose-300'
                }`}>
                  {signals.length}
                </span>
                {isCrossCategory && (
                  <span className="text-xs text-[#71717A]">· used in every search</span>
                )}
              </div>
              <ChevronRight className={`w-4 h-4 text-[#71717A] transition-transform ${isOpen ? 'rotate-90' : ''}`} />
            </button>

            <AnimatePresence initial={false}>
              {isOpen && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.18 }}
                  className="overflow-hidden"
                >
                  <div className="px-4 pb-4 pt-1 space-y-2 border-t border-white/[0.04]">
                    {signals.map((signal) => (
                      <SignalRow
                        key={signal.id}
                        signal={signal}
                        onRemove={() => onRemove(signal.id)}
                        accentColor={accentColor}
                      />
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )
      })}
    </div>
  )
}

// ── SignalRow ─────────────────────────────────────────────────────────────────

function SignalRow({
  signal,
  onRemove,
  accentColor,
}: {
  signal: UserSignal
  onRemove: () => void
  accentColor: 'violet' | 'rose'
}) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, scale: 0.97 }}
      className="group flex items-start justify-between gap-3 p-3 rounded-lg hover:bg-white/[0.03] transition-colors"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <Badge className={`text-xs ${strengthColor(signal.strength)}`}>
            {strengthLabel(signal.strength)}
          </Badge>
          <span className="text-xs text-[#4B4B55]">
            {formatDistanceToNow(new Date(signal.createdAt), { addSuffix: true })}
          </span>
        </div>
        <p className={`text-sm ${accentColor === 'rose' ? 'text-[#E2E2E2]' : 'text-[#E2E2E2]'}`}>
          {signal.text}
        </p>
      </div>
      <Button
        variant="ghost"
        size="sm"
        onClick={onRemove}
        className="opacity-0 group-hover:opacity-100 shrink-0 h-7 w-7 p-0 text-[#71717A] hover:text-rose-400 hover:bg-rose-500/10 transition-all"
      >
        <Trash2 className="w-3.5 h-3.5" />
      </Button>
    </motion.div>
  )
}

// ── ProductMemoryCard ─────────────────────────────────────────────────────────

function ProductMemoryCard({ product }: { product: ProductMemory }) {
  const statusConfig: Record<string, { label: string; className: string }> = {
    purchased: { label: 'Purchased', className: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' },
    considered: { label: 'Considered', className: 'bg-amber-500/20 text-amber-300 border-amber-500/30' },
    rejected: { label: 'Rejected', className: 'bg-rose-500/20 text-rose-300 border-rose-500/30' },
    returned: { label: 'Returned', className: 'bg-slate-500/20 text-slate-300 border-slate-500/30' },
  }
  const cfg = statusConfig[product.status] ?? statusConfig.considered

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      className="p-4 rounded-xl bg-white/[0.02] border border-white/[0.06] hover:border-white/[0.1] transition-colors"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <Badge className={`text-xs ${cfg.className}`}>{cfg.label}</Badge>
            <Badge variant="outline" className="text-xs border-white/[0.1] text-[#71717A]">
              {categoryLabel(product.category)}
            </Badge>
          </div>
          <h4 className="font-medium text-[#FAFAFA] text-sm mb-1 truncate">{product.productName}</h4>
          <div className="flex items-center gap-3 text-xs text-[#71717A]">
            {typeof product.ourScore === 'number' && Number.isFinite(product.ourScore) && (
              <span className="text-emerald-400 font-mono">{Math.round(product.ourScore)}% match</span>
            )}
            <span>{formatDistanceToNow(new Date(product.createdAt), { addSuffix: true })}</span>
          </div>
          {product.userFeedback && (
            <p className="text-xs text-[#A1A1AA] mt-2 italic">&ldquo;{product.userFeedback}&rdquo;</p>
          )}
        </div>
      </div>
    </motion.div>
  )
}

// ── EmptyState ────────────────────────────────────────────────────────────────

function EmptyState({ icon: Icon, title, description }: { icon: React.ElementType; title: string; description: string }) {
  return (
    <div className="text-center py-12">
      <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-white/[0.04] flex items-center justify-center">
        <Icon className="w-6 h-6 text-[#71717A]" />
      </div>
      <h3 className="font-medium text-[#FAFAFA] mb-1">{title}</h3>
      <p className="text-sm text-[#71717A] max-w-xs mx-auto">{description}</p>
    </div>
  )
}
