'use client'

import { motion } from 'framer-motion'

export function AnimatedBackground() {
  return (
    <div className="fixed inset-0 overflow-hidden pointer-events-none" aria-hidden="true">
      {/* Noise texture overlay */}
      <div className="absolute inset-0 noise-overlay" />
      
      {/* Animated gradient blobs */}
      <motion.div
        className="absolute w-[600px] h-[600px] rounded-full blur-[120px] opacity-30"
        style={{
          background: 'radial-gradient(circle, #8B5CF6 0%, transparent 70%)',
          top: '10%',
          left: '20%',
        }}
        animate={{
          x: [0, 100, 50, -50, 0],
          y: [0, 50, 100, 50, 0],
        }}
        transition={{
          duration: 40,
          repeat: Infinity,
          ease: 'linear',
        }}
      />
      
      <motion.div
        className="absolute w-[500px] h-[500px] rounded-full blur-[120px] opacity-25"
        style={{
          background: 'radial-gradient(circle, #4F46E5 0%, transparent 70%)',
          top: '50%',
          right: '10%',
        }}
        animate={{
          x: [0, -80, -40, 40, 0],
          y: [0, -60, 80, -40, 0],
        }}
        transition={{
          duration: 45,
          repeat: Infinity,
          ease: 'linear',
        }}
      />
      
      <motion.div
        className="absolute w-[550px] h-[550px] rounded-full blur-[120px] opacity-20"
        style={{
          background: 'radial-gradient(circle, #10B981 0%, transparent 70%)',
          bottom: '20%',
          left: '40%',
        }}
        animate={{
          x: [0, 60, -40, 80, 0],
          y: [0, -80, -20, 60, 0],
        }}
        transition={{
          duration: 50,
          repeat: Infinity,
          ease: 'linear',
        }}
      />
      
      <motion.div
        className="absolute w-[450px] h-[450px] rounded-full blur-[120px] opacity-20"
        style={{
          background: 'radial-gradient(circle, #7C3AED 0%, transparent 70%)',
          top: '30%',
          right: '30%',
        }}
        animate={{
          x: [0, -60, 30, -30, 0],
          y: [0, 40, -50, 70, 0],
        }}
        transition={{
          duration: 35,
          repeat: Infinity,
          ease: 'linear',
        }}
      />
    </div>
  )
}
