'use client'

import { motion } from 'framer-motion'
import { MessagesSquare, Sparkles, SlidersHorizontal, ArrowRight } from 'lucide-react'

const features = [
  {
    icon: MessagesSquare,
    title: 'Community sourced',
    description: '15+ Reddit threads + expert reviews scraped, ranked, and analyzed for every query.',
    color: 'violet',
    bgClass: 'bg-violet-500/20',
    iconClass: 'text-violet-400',
  },
  {
    icon: Sparkles,
    title: 'Fully personalized',
    description: 'An 8-question interview builds a weighted rubric of what matters to YOU specifically.',
    color: 'emerald',
    bgClass: 'bg-emerald-500/20',
    iconClass: 'text-emerald-400',
  },
  {
    icon: SlidersHorizontal,
    title: 'Live re-ranking',
    description: 'Drag weight sliders on the results page and watch products instantly reorder.',
    color: 'amber',
    bgClass: 'bg-amber-500/20',
    iconClass: 'text-amber-400',
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
          className="text-center mb-12"
        >
          <span className="text-xs font-medium tracking-widest uppercase text-[#71717A]">
            How it works
          </span>
        </motion.div>
        
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {features.map((feature, index) => (
            <motion.div
              key={feature.title}
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: index * 0.1, duration: 0.5 }}
              whileHover={{ 
                y: -4,
                transition: { duration: 0.2 }
              }}
              className="group relative rounded-2xl bg-white/[0.02] border border-white/[0.06] p-8 hover:border-violet-500/30 hover:shadow-premium transition-all duration-300"
            >
              {/* Icon */}
              <div className={`w-12 h-12 rounded-xl ${feature.bgClass} flex items-center justify-center mb-6`}>
                <feature.icon className={`w-6 h-6 ${feature.iconClass}`} />
              </div>
              
              {/* Content */}
              <h3 className="text-xl font-semibold text-[#FAFAFA] mb-3">
                {feature.title}
              </h3>
              <p className="text-[#A1A1AA] leading-relaxed mb-6">
                {feature.description}
              </p>
              
              {/* Learn more link */}
              <a
                href="#"
                className="inline-flex items-center gap-1.5 text-sm text-violet-400 hover:text-violet-300 transition-colors"
              >
                Learn more
                <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
              </a>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
