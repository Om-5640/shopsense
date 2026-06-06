'use client'

import { useEffect, useRef, useState } from 'react'
import { motion, useInView } from 'framer-motion'

const stats = [
  { value: 15, suffix: '+', label: 'sources per search',     desc: 'Reddit + reviews + YouTube' },
  { value: 10, suffix: '',  label: 'specialized AI agents',  desc: 'Scoring, ranking, enrichment' },
  { value: 60, prefix: '<', suffix: 's', label: 'research time', desc: 'End-to-end pipeline' },
]

function AnimatedNumber({
  value, prefix = '', suffix = '', inView,
}: { value: number; prefix?: string; suffix?: string; inView: boolean }) {
  const [display, setDisplay] = useState(0)

  useEffect(() => {
    if (!inView) return
    const dur  = 1600
    let start: number | null = null
    const tick = (ts: number) => {
      if (start === null) start = ts
      const p = Math.min((ts - start) / dur, 1)
      setDisplay(Math.floor((1 - Math.pow(1 - p, 3)) * value))
      if (p < 1) requestAnimationFrame(tick)
      else setDisplay(value)
    }
    requestAnimationFrame(tick)
  }, [inView, value])

  return (
    <span className="font-mono text-5xl md:text-6xl font-bold gradient-number tabular-nums">
      {prefix}{display}{suffix}
    </span>
  )
}

export function StatsStrip() {
  const ref    = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { once: true, margin: '-80px' })

  return (
    <section ref={ref} className="relative py-16">
      {/* Gradient borders */}
      <div className="absolute top-0 left-4 right-4 h-px bg-gradient-to-r from-transparent via-white/[0.08] to-transparent" />
      <div className="absolute bottom-0 left-4 right-4 h-px bg-gradient-to-r from-transparent via-white/[0.08] to-transparent" />

      <div className="max-w-5xl mx-auto px-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-0">
          {stats.map((stat, i) => (
            <motion.div
              key={stat.label}
              initial={{ opacity: 0, y: 24 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ delay: i * 0.12, duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
              className={`relative text-center py-8 px-6 ${
                i < stats.length - 1 ? 'md:border-r md:border-white/[0.06]' : ''
              }`}
            >
              {/* The number */}
              <AnimatedNumber value={stat.value} prefix={stat.prefix} suffix={stat.suffix} inView={inView} />

              {/* Label */}
              <p className="mt-2.5 text-sm font-medium text-[#A1A1AA]">{stat.label}</p>

              {/* Sub-description */}
              <p className="mt-1 text-xs text-[#52525B]">{stat.desc}</p>

              {/* Thin animated underline bar */}
              <div className="mt-4 mx-auto w-16 h-0.5 rounded-full bg-white/[0.05] overflow-hidden">
                <motion.div
                  className="h-full rounded-full"
                  style={{
                    background: i === 0
                      ? 'linear-gradient(90deg, #8B5CF6, #A78BFA)'
                      : i === 1
                        ? 'linear-gradient(90deg, #A78BFA, #C4B5FD)'
                        : 'linear-gradient(90deg, #C4B5FD, #FAFAFA)',
                  }}
                  initial={{ width: 0 }}
                  animate={inView ? { width: '100%' } : {}}
                  transition={{ delay: 0.4 + i * 0.12, duration: 0.7, ease: 'easeOut' }}
                />
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
