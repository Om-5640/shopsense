'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { Link, AlertCircle } from 'lucide-react'
import { AnimatedBackground } from '@/components/layout/animated-background'
import { resolveShareToken } from '@/lib/api'

/**
 * Share link resolver page — /s/[token]
 *
 * Resolves a share token to its search_id and immediately redirects
 * to /results/[search_id].  Shows a brief loading state while resolving,
 * and a clear error if the token is not found or has expired.
 */
export default function SharePage() {
  const { token } = useParams<{ token: string }>()
  const router = useRouter()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    resolveShareToken(token)
      .then((searchId) => {
        router.replace(`/results/${searchId}`)
      })
      .catch(() => {
        setError('This share link is invalid or has expired.')
      })
  }, [token, router])

  if (error) {
    return (
      <div className="min-h-screen flex flex-col bg-[#08080A]">
        <AnimatedBackground />
        <div className="flex-1 flex items-center justify-center relative z-10">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-center space-y-4 px-6"
          >
            <div className="w-14 h-14 rounded-2xl bg-rose-500/15 border border-rose-500/25 flex items-center justify-center mx-auto">
              <AlertCircle className="w-7 h-7 text-rose-400" />
            </div>
            <h1 className="text-xl font-semibold text-[#FAFAFA]">Link not found</h1>
            <p className="text-[#71717A] text-sm max-w-xs">{error}</p>
            <button
              onClick={() => router.push('/')}
              className="mt-4 px-5 py-2 rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium transition-colors"
            >
              Start a new search
            </button>
          </motion.div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex flex-col bg-[#08080A]">
      <AnimatedBackground />
      <div className="flex-1 flex items-center justify-center relative z-10">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="text-center space-y-4"
        >
          <div className="w-14 h-14 rounded-2xl bg-violet-500/15 border border-violet-500/25 flex items-center justify-center mx-auto">
            <Link className="w-7 h-7 text-violet-400" />
          </div>
          <p className="text-[#A1A1AA] text-sm">Loading shared results…</p>
          <div className="w-6 h-6 border-2 border-violet-500 border-t-transparent rounded-full animate-spin mx-auto" />
        </motion.div>
      </div>
    </div>
  )
}
