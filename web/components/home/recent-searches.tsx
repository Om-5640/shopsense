'use client'

import { motion } from 'framer-motion'
import { ArrowRight, Clock } from 'lucide-react'
import Link from 'next/link'
import { useAppStore } from '@/lib/store'
import { formatDistanceToNow } from 'date-fns'

export function RecentSearches() {
  const { searchHistory } = useAppStore()
  
  // Show only first 6 searches
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
            <span className="text-xs font-medium tracking-widest uppercase text-[#71717A]">
              Recent Searches
            </span>
          </motion.div>
          
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-center py-12 rounded-2xl border border-dashed border-white/[0.1] bg-white/[0.01]"
          >
            <p className="text-[#71717A]">Your search history will appear here</p>
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
          className="text-center mb-12"
        >
          <span className="text-xs font-medium tracking-widest uppercase text-[#71717A]">
            Recent Searches
          </span>
        </motion.div>
        
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {recentSearches.map((search, index) => (
            <motion.div
              key={search.id}
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: index * 0.05 }}
              whileHover={{ y: -2 }}
            >
              <Link href={`/results/${search.id}`}>
                <div className="group relative h-full rounded-2xl bg-white/[0.02] border border-white/[0.06] p-5 hover:border-violet-500/30 hover:shadow-premium transition-all duration-300">
                  {/* Query */}
                  <h3 className="text-[#FAFAFA] font-medium line-clamp-2 mb-2">
                    {search.query}
                  </h3>
                  
                  {/* Metadata */}
                  <div className="flex items-center gap-2 text-xs text-[#71717A] mb-4">
                    <span className="px-2 py-0.5 rounded-full bg-white/[0.04]">
                      {search.category}
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {formatDistanceToNow(new Date(search.timestamp), { addSuffix: true })}
                    </span>
                  </div>
                  
                  {/* Divider */}
                  <div className="h-px bg-white/[0.06] mb-4" />
                  
                  {/* Top result */}
                  {search.topProduct && (
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs text-[#71717A] mb-1">Top result</p>
                        <p className="text-sm text-[#FAFAFA] truncate max-w-[180px]">
                          {search.topProduct.name}
                        </p>
                      </div>
                      <div className="text-right">
                        <span className="text-lg font-mono font-bold text-emerald-400">
                          {search.topProduct.score}%
                        </span>
                      </div>
                    </div>
                  )}
                  
                  {/* Hover arrow */}
                  <div className="absolute top-5 right-5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <ArrowRight className="w-4 h-4 text-violet-400" />
                  </div>
                </div>
              </Link>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
