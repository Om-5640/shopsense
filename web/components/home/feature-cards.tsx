'use client'

import { motion } from 'framer-motion'
import { MessagesSquare, Sparkles, SlidersHorizontal, ArrowRight } from 'lucide-react'

const features = [
  {
    icon: MessagesSquare,
    title: 'Community sourced',
    description: '15+ Reddit threads + expert reviews scraped, ranked, and analyzed for every query.',
    bgClass: 'bg-violet-500/15',
    iconClass: 'text-violet-400',
    glowClass: 'shadow-[0_0_24px_rgba(139,92,246,0.25)]',
    borderHover: 'hover:border-violet-500/30',
    accentGrad: 'from-violet-500/20 to-purple-500/10',
    anchor: '#learn-more-community',
  },
  {
    icon: Sparkles,
    title: 'Fully personalized',
    description: 'An 8-question interview builds a weighted rubric of what matters to YOU specifically.',
    bgClass: 'bg-emerald-500/15',
    iconClass: 'text-emerald-400',
    glowClass: 'shadow-[0_0_24px_rgba(52,211,153,0.2)]',
    borderHover: 'hover:border-emerald-500/30',
    accentGrad: 'from-emerald-500/15 to-teal-500/10',
    anchor: '#learn-more-interview',
  },
  {
    icon: SlidersHorizontal,
    title: 'Live re-ranking',
    description: 'Drag weight sliders on the results page and watch products instantly reorder.',
    bgClass: 'bg-amber-500/15',
    iconClass: 'text-amber-400',
    glowClass: 'shadow-[0_0_24px_rgba(251,191,36,0.2)]',
    borderHover: 'hover:border-amber-500/30',
    accentGrad: 'from-amber-500/15 to-orange-500/10',
    anchor: '#learn-more-reranking',
  },
]

export function FeatureCards() {
  return (
    <section className="py-24">
      <div className="max-w-6xl mx-auto px-4">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="text-center mb-14"
        >
          <span className="text-xs font-medium tracking-widest uppercase text-[#52525B]">
            How it works
          </span>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {features.map((feature, index) => (
            <motion.div
              key={feature.title}
              initial={{ opacity: 0, y: 32 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: index * 0.1, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
              whileHover={{ y: -6, transition: { duration: 0.22 } }}
              className={`group relative rounded-2xl bg-white/[0.02] border border-white/[0.07] p-8 overflow-hidden
                transition-all duration-300 cursor-pointer
                ${feature.borderHover} hover:shadow-premium`}
            >
              {/* Top-edge gradient accent — fades in on hover */}
              <div className={`absolute top-0 left-0 right-0 h-px bg-gradient-to-r ${feature.accentGrad} opacity-0 group-hover:opacity-100 transition-opacity duration-300`} />

              {/* Ambient corner glow on hover */}
              <div className={`absolute -top-8 -right-8 w-32 h-32 rounded-full blur-3xl opacity-0 group-hover:opacity-100 transition-opacity duration-400 bg-gradient-to-br ${feature.accentGrad}`} />

              {/* Icon with hover glow */}
              <motion.div
                className={`relative w-12 h-12 rounded-xl ${feature.bgClass} flex items-center justify-center mb-6 transition-all duration-300`}
                whileHover={{ scale: 1.1 }}
                transition={{ type: 'spring', stiffness: 350, damping: 18 }}
              >
                <feature.icon className={`w-6 h-6 ${feature.iconClass}`} />
                <div className={`absolute inset-0 rounded-xl opacity-0 group-hover:opacity-100 transition-opacity duration-300 ${feature.glowClass}`} />
              </motion.div>

              {/* Content */}
              <h3 className="text-xl font-semibold text-[#FAFAFA] mb-3 group-hover:text-white transition-colors duration-200">
                {feature.title}
              </h3>
              <p className="text-[#A1A1AA] leading-relaxed mb-7 text-sm">
                {feature.description}
              </p>

              {/* Learn more link */}
              <a
                href={feature.anchor}
                onClick={(e) => {
                  e.preventDefault()
                  document.querySelector(feature.anchor)?.scrollIntoView({ behavior: 'smooth' })
                }}
                className={`inline-flex items-center gap-1.5 text-sm font-medium ${feature.iconClass} opacity-70 group-hover:opacity-100 transition-all duration-200`}
              >
                Learn more
                <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-1 transition-transform duration-200" />
              </a>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
