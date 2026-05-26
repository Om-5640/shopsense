'use client'

import { motion } from 'framer-motion'
import { Check, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface RedditThread {
  id: string
  subreddit: string
  title: string
  score: number
  status: 'pending' | 'fetching' | 'complete'
  commentCount?: number
}

interface RedditFetchGridProps {
  threads: RedditThread[]
}

export function RedditFetchGrid({ threads }: RedditFetchGridProps) {
  return (
    <div className="rounded-2xl bg-white/[0.02] border border-white/[0.06] p-6">
      <h3 className="text-lg font-semibold text-[#FAFAFA] mb-4">
        Fetching Reddit Threads
      </h3>
      <p className="text-sm text-[#71717A] mb-6">
        Discovering and analyzing relevant discussions...
      </p>
      
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {threads.map((thread, index) => (
          <motion.div
            key={thread.id}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: index * 0.05 }}
            className={cn(
              'relative p-3 rounded-xl border transition-all duration-300',
              thread.status === 'pending' && 'bg-white/[0.02] border-white/[0.06]',
              thread.status === 'fetching' && 'bg-blue-500/5 border-blue-500/30 animate-pulse',
              thread.status === 'complete' && 'bg-emerald-500/5 border-emerald-500/30'
            )}
          >
            {/* Subreddit */}
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-violet-400">
                r/{thread.subreddit}
              </span>
              <div className="w-5 h-5 flex items-center justify-center">
                {thread.status === 'fetching' && (
                  <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />
                )}
                {thread.status === 'complete' && (
                  <Check className="w-4 h-4 text-emerald-400" />
                )}
              </div>
            </div>
            
            {/* Title */}
            <p className="text-sm text-[#FAFAFA] line-clamp-2 mb-2">
              {thread.title}
            </p>
            
            {/* Metadata */}
            <div className="flex items-center gap-2 text-xs text-[#71717A]">
              <span>{thread.score} pts</span>
              {thread.commentCount !== undefined && (
                <>
                  <span>•</span>
                  <span>{thread.commentCount} comments</span>
                </>
              )}
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
