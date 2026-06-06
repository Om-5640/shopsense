'use client'

import { motion } from 'framer-motion'
import { ArrowRight, Clock, Search } from 'lucide-react'
import Link from 'next/link'
import { useAppStore } from '@/lib/store'
import { formatDistanceToNow } from 'date-fns'

const ACCENT_COLORS = [
  'from-violet-500/60 to-purple-500/40',
  'from-emerald-500/60 to-teal-500/40',
  'from-amber-500/60 to-orange-500/40',
  'from-blue-500/60 to-indigo-500/40',
  'from-rose-500/60 to-pink-500/40',
  'from-cyan-500/60 to-sky-500/40',
]

function scoreColor(score: number) {
  if (score >= 70) return 'text-emerald-400'
  if (score >= 45) return 'text-amber-400'
  return 'text-rose-400'
}

export function RecentSearches() {
  const { searchHistory } = useAppStore()
  const recentSearches = searchHistory.slice(0, 6)

  if (recentSearches.length === 0) {
    return (
      <section className="py-20">
        <div className="max-w-6xl mx-auto px-4">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-center mb-12"
          >
            <span className="text-xs font-medium tracking-widest uppercase text-[#52525B]">
              Recent Searches
            </span>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-center py-16 rounded-2xl border border-dashed border-white/[0.08] bg-white/[0.01]"
          >
            <Search className="w-8 h-8 text-[#3F3F46] mx-auto mb-3" />
            <p className="text-[#71717A] text-sm">Your search history will appear here</p>
            <p className="text-[#3F3F46] text-xs mt-1">Start a search above to see it here</p>
          </motion.div>
        </div>
      </section>
    )
  }

  return (
    <section className="py-20">
      <div className="max-w-6xl mx-auto px-4">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="flex items-center justify-between mb-10"
        >
          <div>
            <span className="text-xs font-medium tracking-widest uppercase text-[#52525B] block mb-1">
              Recent Searches
            </span>
            <h2 className="text-lg font-semibold text-[#FAFAFA]">Continue your research</h2>
          </div>
          <span className="text-xs text-[#3F3F46] px-2.5 py-1 rounded-full bg-white/[0.03] border border-white/[0.06]">
            {recentSearches.length} sessions
          </span>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {recentSearches.map((search, index) => (
            <motion.div
              key={search.id}
              initial={{ opacity: 0, y: 28 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: index * 0.06, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
              whileHover={{ y: -4, transition: { duration: 0.2 } }}
            >
              <Link href={`/results/${search.id}`}>
                <div className="group relative h-full rounded-2xl bg-white/[0.02] border border-white/[0.07] p-5 overflow-hidden
                  hover:border-white/[0.12] hover:shadow-[0_8px_30px_rgba(0,0,0,0.35)] transition-all duration-300 cursor-pointer">

                  {/* Left accent bar */}
                  <div className={`absolute left-0 top-4 bottom-4 w-0.5 rounded-full bg-gradient-to-b ${ACCENT_COLORS[index % ACCENT_COLORS.length]} opacity-60`} />

                  {/* Shimmer on hover */}
                  <div className="absolute inset-0 opacity-0 group-hover:opacity-100 animate-shimmer pointer-events-none" />

                  {/* Hover arrow top-right */}
                  <div className="absolute top-4 right-4 opacity-0 group-hover:opacity-100 transition-all duration-200 translate-x-1 group-hover:translate-x-0">
                    <div className="w-6 h-6 rounded-lg bg-violet-500/15 flex items-center justify-center">
                      <ArrowRight className="w-3.5 h-3.5 text-violet-400" />
                    </div>
                  </div>

                  {/* Query */}
                  <h3 className="text-[#FAFAFA] font-medium line-clamp-2 mb-2.5 pr-8 leading-snug">
                    {search.query}
                  </h3>

                  {/* Meta */}
                  <div className="flex items-center gap-2 text-xs text-[#71717A] mb-4">
                    <span className="px-2 py-0.5 rounded-full bg-white/[0.05] border border-white/[0.06] text-[#A1A1AA]">
                      {search.category}
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {formatDistanceToNow(new Date(search.timestamp), { addSuffix: true })}
                    </span>
                  </div>

                  {/* Divider */}
                  <div className="h-px bg-gradient-to-r from-white/[0.08] via-white/[0.04] to-transparent mb-4" />

                  {/* Top result */}
                  {search.topProduct && (
                    <div className="flex items-end justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <p className="text-[10px] text-[#52525B] mb-0.5 uppercase tracking-wide">Top result</p>
                        <p className="text-sm text-[#FAFAFA] truncate font-medium">
                          {search.topProduct.name}
                        </p>
                      </div>
                      <div className="shrink-0 text-right">
                        <span className={`text-xl font-mono font-bold tabular-nums ${scoreColor(search.topProduct.score)}`}>
                          {search.topProduct.score}%
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              </Link>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
