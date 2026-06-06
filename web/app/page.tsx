'use client'

import { useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { AnimatedBackground } from '@/components/layout/animated-background'
import { Header } from '@/components/layout/header'
import { Footer } from '@/components/layout/footer'
import { CommandPalette } from '@/components/layout/command-palette'
import { HeroSearch } from '@/components/home/hero-search'
import { ChipRow } from '@/components/home/chip-row'
import { FeatureCards } from '@/components/home/feature-cards'
import { LearnMoreSection } from '@/components/home/learn-more-section'
import { StatsStrip } from '@/components/home/stats-strip'
import { RecentSearches } from '@/components/home/recent-searches'

export default function HomePage() {
  const router = useRouter()
  const [commandOpen, setCommandOpen] = useState(false)
  
  const handleSearch = useCallback((query: string, region: string = 'global') => {
    const params = new URLSearchParams({ q: query })
    if (region && region !== 'global') params.set('region', region)
    router.push(`/research?${params.toString()}`)
  }, [router])

  const handleChipClick = useCallback((query: string) => {
    setTimeout(() => {
      router.push(`/research?q=${encodeURIComponent(query)}`)
    }, 200)
  }, [router])
  
  return (
    <div className="min-h-screen flex flex-col bg-[#08080A]">
      <AnimatedBackground />
      <Header onOpenCommandPalette={() => setCommandOpen(true)} />
      <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} />
      
      <main className="flex-1 relative z-10">
        {/* Hero Section */}
        <section className="min-h-[70vh] flex flex-col items-center justify-center px-4 py-20">
          {/* Badge */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="mb-8"
          >
            <span className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-violet-500/10 border border-violet-500/20 text-sm text-violet-300">
              <span className="text-violet-400">&#10022;</span>
              Now with live Reddit research
            </span>
          </motion.div>
          
          {/* Headline */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1, duration: 0.5 }}
            className="text-center mb-6"
          >
            <h1 className="text-5xl sm:text-6xl md:text-7xl lg:text-[80px] font-medium tracking-tighter text-[#FAFAFA] leading-[1.1]">
              Find what you should
            </h1>
            <h1 className="text-5xl sm:text-6xl md:text-7xl lg:text-[80px] tracking-tighter leading-[1.1]">
              <span className="font-serif italic gradient-text">actually buy.</span>
            </h1>
          </motion.div>
          
          {/* Subtitle */}
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2, duration: 0.5 }}
            className="text-lg text-[#A1A1AA] text-center max-w-xl mb-10"
          >
            15 Reddit threads. Expert reviews. Ranked to{' '}
            <span className="text-[#FAFAFA] font-medium">your</span>{' '}
            priorities, not theirs.
          </motion.p>
          
          {/* Search Input */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3, duration: 0.5 }}
            className="w-full max-w-2xl mb-8"
          >
            <HeroSearch onSearch={handleSearch} />
          </motion.div>
          
          {/* Chip Row */}
          <ChipRow onChipClick={handleChipClick} />
        </section>
        
        {/* Feature Cards */}
        <FeatureCards />

        {/* Learn More deep-dive */}
        <LearnMoreSection />

        {/* Stats Strip */}
        <StatsStrip />
        
        {/* Recent Searches */}
        <RecentSearches />
      </main>
      
      <Footer />
    </div>
  )
}
