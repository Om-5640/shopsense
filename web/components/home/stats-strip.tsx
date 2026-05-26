'use client'

import { useEffect, useState, useRef } from 'react'
import { motion, useInView } from 'framer-motion'

const stats = [
  { value: 15, suffix: '+', label: 'sources per search' },
  { value: 10, suffix: '', label: 'specialized AI agents' },
  { value: 60, prefix: '<', suffix: 's', label: 'average research time' },
]

function AnimatedNumber({ 
  value, 
  prefix = '', 
  suffix = '',
  inView 
}: { 
  value: number
  prefix?: string
  suffix?: string
  inView: boolean
}) {
  const [displayValue, setDisplayValue] = useState(0)
  
  useEffect(() => {
    if (!inView) return
    
    const duration = 1500
    const steps = 60
    const stepTime = duration / steps
    const increment = value / steps
    let current = 0
    
    const timer = setInterval(() => {
      current += increment
      if (current >= value) {
        setDisplayValue(value)
        clearInterval(timer)
      } else {
        setDisplayValue(Math.floor(current))
      }
    }, stepTime)
    
    return () => clearInterval(timer)
  }, [value, inView])
  
  return (
    <span className="font-mono text-5xl md:text-6xl font-bold text-[#FAFAFA]">
      {prefix}{displayValue}{suffix}
    </span>
  )
}

export function StatsStrip() {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { once: true, margin: '-100px' })
  
  return (
    <section ref={ref} className="py-16 border-y border-white/[0.06]">
      <div className="max-w-5xl mx-auto px-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 md:gap-4">
          {stats.map((stat, index) => (
            <motion.div
              key={stat.label}
              initial={{ opacity: 0, y: 20 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ delay: index * 0.1, duration: 0.5 }}
              className={`
                text-center py-4
                ${index < stats.length - 1 ? 'md:border-r md:border-white/[0.06]' : ''}
              `}
            >
              <AnimatedNumber
                value={stat.value}
                prefix={stat.prefix}
                suffix={stat.suffix}
                inView={inView}
              />
              <p className="mt-2 text-sm text-[#71717A]">{stat.label}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
