'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Search,
  Plus,
  Clock,
  Trash2,
  RefreshCw,
  ArrowRight,
  Filter,
  MapPin,
  PackageSearch,
} from 'lucide-react'
import { AnimatedBackground } from '@/components/layout/animated-background'
import { Header } from '@/components/layout/header'
import { CommandPalette } from '@/components/layout/command-palette'
import { Footer } from '@/components/layout/footer'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
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
import { formatDistanceToNow } from 'date-fns'
import { toast } from 'sonner'
import { listSearches } from '@/lib/api'
import type { SearchResult } from '@/lib/types'

export default function HistoryPage() {
  const router = useRouter()
  const [commandOpen, setCommandOpen] = useState(false)
  const [searchFilter, setSearchFilter] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [history, setHistory] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    listSearches(100)
      .then(setHistory)
      .catch(() => toast.error('Could not load history'))
      .finally(() => setLoading(false))
  }, [])

  const categories = [...new Set(history.map((h) => h.category))]

  const filteredHistory = history.filter((item) => {
    const matchesSearch = item.query.toLowerCase().includes(searchFilter.toLowerCase())
    const matchesCategory = categoryFilter === 'all' || item.category === categoryFilter
    return matchesSearch && matchesCategory
  })

  const handleDelete = (id: string) => {
    setHistory((prev) => prev.filter((item) => item.id !== id))
    toast.success('Search removed from history')
  }

  const handleReresearch = (query: string) => {
    router.push(`/research?q=${encodeURIComponent(query)}`)
  }

  function topScore(item: SearchResult): number | undefined {
    return item.scoredProducts?.[0]?.percentage
  }

  function topProduct(item: SearchResult): string | undefined {
    return item.scoredProducts?.[0]?.name
  }

  return (
    <div className="min-h-screen flex flex-col bg-[#08080A]">
      <AnimatedBackground />
      <Header onOpenCommandPalette={() => setCommandOpen(true)} />
      <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} />

      <main className="flex-1 relative z-10">
        <div className="max-w-5xl mx-auto px-4 py-8">
          {/* Page header */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
            <div>
              <h1 className="text-3xl font-bold text-[#FAFAFA]">Search History</h1>
              <p className="text-[#71717A] mt-1">Your past research sessions</p>
            </div>
            <Button onClick={() => router.push('/')} className="bg-violet-600 hover:bg-violet-500">
              <Plus className="w-4 h-4 mr-2" />
              New Search
            </Button>
          </div>

          {/* Filters */}
          <div className="flex flex-col sm:flex-row gap-4 mb-8">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#71717A]" />
              <Input
                placeholder="Search history…"
                value={searchFilter}
                onChange={(e) => setSearchFilter(e.target.value)}
                className="pl-10 bg-white/[0.04] border-white/[0.08] text-[#FAFAFA] placeholder:text-[#71717A]"
              />
            </div>
            <Select value={categoryFilter} onValueChange={setCategoryFilter}>
              <SelectTrigger className="w-full sm:w-[200px] bg-white/[0.04] border-white/[0.08] text-[#FAFAFA]">
                <Filter className="w-4 h-4 mr-2 text-[#71717A]" />
                <SelectValue placeholder="Category" />
              </SelectTrigger>
              <SelectContent className="bg-[#0F0F12] border-white/[0.1]">
                <SelectItem value="all" className="text-[#FAFAFA]">All Categories</SelectItem>
                {categories.map((cat) => (
                  <SelectItem key={cat} value={cat} className="text-[#FAFAFA]">{cat}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Loading */}
          {loading && (
            <div className="flex justify-center py-16">
              <div className="w-6 h-6 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
            </div>
          )}

          {/* Empty */}
          {!loading && filteredHistory.length === 0 && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-center py-16"
            >
              <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-white/[0.04] flex items-center justify-center">
                <PackageSearch className="w-8 h-8 text-[#71717A]" />
              </div>
              <h3 className="text-lg font-medium text-[#FAFAFA] mb-2">No searches found</h3>
              <p className="text-[#71717A] mb-6">
                {searchFilter || categoryFilter !== 'all'
                  ? 'Try adjusting your filters'
                  : 'Start your first search to see it here'}
              </p>
              <Button onClick={() => router.push('/')} className="bg-violet-600 hover:bg-violet-500">
                Start your first search
                <ArrowRight className="w-4 h-4 ml-2" />
              </Button>
            </motion.div>
          )}

          {/* History grid */}
          {!loading && filteredHistory.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <AnimatePresence mode="popLayout">
                {filteredHistory.map((item, index) => (
                  <motion.div
                    key={item.id}
                    layout
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.9 }}
                    transition={{ delay: index * 0.04 }}
                    className="group relative rounded-2xl bg-white/[0.02] border border-white/[0.06] p-5 hover:border-violet-500/30 hover:shadow-premium transition-all duration-300"
                  >
                    <h3 className="text-[#FAFAFA] font-medium pr-8 mb-3 line-clamp-2">
                      {item.query}
                    </h3>

                    <div className="flex flex-wrap items-center gap-2 text-xs text-[#71717A] mb-4">
                      <Badge variant="outline" className="border-white/[0.1]">
                        {item.category}
                      </Badge>
                      <span className="flex items-center gap-1">
                        <MapPin className="w-3 h-3" />
                        {item.region}
                      </span>
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {formatDistanceToNow(new Date(item.createdAt), { addSuffix: true })}
                      </span>
                    </div>

                    <div className="h-px bg-white/[0.06] mb-4" />

                    <div className="flex items-center justify-between mb-4">
                      <div>
                        <p className="text-xs text-[#71717A] mb-1">Top result</p>
                        <p className="text-sm text-[#FAFAFA] truncate max-w-[200px]">
                          {topProduct(item) ?? '—'}
                        </p>
                      </div>
                      {topScore(item) !== undefined && (
                        <span className="text-xl font-mono font-bold text-emerald-400">
                          {Math.round(topScore(item)!)}%
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => router.push(`/results/${item.id}`)}
                        className="flex-1 text-[#A1A1AA] hover:text-[#FAFAFA]"
                      >
                        Open
                        <ArrowRight className="w-4 h-4 ml-1" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleReresearch(item.query)}
                        className="text-[#71717A] hover:text-[#FAFAFA]"
                        title="Re-research"
                      >
                        <RefreshCw className="w-4 h-4" />
                      </Button>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="ghost" size="sm" className="text-[#71717A] hover:text-rose-400">
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent className="bg-[#0F0F12] border-white/[0.1]">
                          <AlertDialogHeader>
                            <AlertDialogTitle className="text-[#FAFAFA]">Delete search?</AlertDialogTitle>
                            <AlertDialogDescription className="text-[#A1A1AA]">
                              This will remove this search from your history.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel className="bg-white/[0.04] border-white/[0.08] text-[#FAFAFA]">
                              Cancel
                            </AlertDialogCancel>
                            <AlertDialogAction
                              onClick={() => handleDelete(item.id)}
                              className="bg-rose-600 hover:bg-rose-500"
                            >
                              Delete
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </div>
      </main>

      <Footer />
    </div>
  )
}
