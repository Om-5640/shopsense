'use client'

import { useEffect } from 'react'
import { motion, useMotionValue, useSpring, useTransform, type MotionValue } from 'framer-motion'
import { useTheme } from 'next-themes'

/* ── Deterministic pseudo-random data ──────────────────────────── */

// Reduced from 44 → 18 stars (saves ~26 JS animation instances)
const STARS = Array.from({ length: 18 }, (_, i) => ({
  id: i,
  x:    ((i * 37.1 + 11) * 2.618) % 100,
  y:    ((i * 23.7 +  7) * 1.414) % 100,
  size: i % 7 === 0 ? 2 : 1,
  delay: (i * 0.55) % 9,
  dur:   4.5 + ((i * 0.8) % 5.5),
  minOp: 0.06 + ((i * 0.04) % 0.10),
  maxOp: 0.20 + ((i * 0.06) % 0.22),
}))

// Reduced from 22 → 5 particles (saves 17 JS animation instances)
const PARTICLES = Array.from({ length: 5 }, (_, i) => ({
  id: i,
  x:     ((i * 47.3 + 5) * 3.14) % 100,
  size:  1 + ((i * 7) % 3) * 0.5,
  delay: (i * 3.6) % 18,
  dur:   24 + ((i * 4.2) % 20),
  op:    0.08 + ((i * 0.07) % 0.12),
}))

const RIPPLE_DELAYS: readonly number[] = [0, 2.6, 5.2]

/* ── Blob definitions ──────────────────────────────────────────── */

type BlobDef = {
  id: string; color: string; w: number; h: number
  top?: string; left?: string; right?: string; bottom?: string
  dur: number; dx: number[]; dy: number[]
  blur: number; op: number; px: number; py: number
}

const DARK_BLOBS: BlobDef[] = [
  { id: 'b1', color: '#6D28D9', w: 700, h: 700, top: '0%',  left:  '8%',
    dur: 46, dx: [0, 130, 65, -80, 0], dy: [0, 70, 130, 65, 0],   blur: 170, op: 0.22, px: 0.05, py: 0.03 },
  { id: 'b2', color: '#3730A3', w: 580, h: 580, top: '40%', right: '2%',
    dur: 54, dx: [0,-115,-55,  75, 0], dy: [0,-80,  95,-55, 0],   blur: 160, op: 0.16, px:-0.06, py:-0.04 },
  { id: 'b3', color: '#0E7490', w: 500, h: 500, bottom: '6%', left: '28%',
    dur: 60, dx: [0,  90,-65, 110, 0], dy: [0,-100,-35,  80, 0],  blur: 155, op: 0.09, px: 0.04, py:-0.04 },
  { id: 'b4', color: '#7C3AED', w: 620, h: 620, top: '16%', right: '16%',
    dur: 41, dx: [0, -90, 45, -50, 0], dy: [0,  60,-70,  90, 0],  blur: 155, op: 0.15, px:-0.05, py: 0.05 },
]

// Light mode blobs — ultra-soft, airy violet/indigo tints
const LIGHT_BLOBS: BlobDef[] = [
  { id: 'l1', color: '#7C3AED', w: 750, h: 750, top: '-5%', left:  '5%',
    dur: 52, dx: [0,  80, 45,-50, 0], dy: [0,  55, 90, 40, 0], blur: 210, op: 0.038, px: 0.04, py: 0.03 },
  { id: 'l2', color: '#4F46E5', w: 640, h: 640, top: '30%', right: '0%',
    dur: 60, dx: [0, -80,-45, 60, 0], dy: [0, -65, 75,-40, 0], blur: 195, op: 0.032, px:-0.05, py:-0.03 },
  { id: 'l3', color: '#6D28D9', w: 520, h: 520, bottom: '0%', left: '35%',
    dur: 66, dx: [0,  65,-50, 80, 0], dy: [0, -70,-25, 60, 0], blur: 185, op: 0.028, px: 0.03, py:-0.03 },
]

/* ── Reusable blob component (isolates useTransform calls) ──────── */
function PBlob({ blob, smoothX, smoothY }: {
  blob: BlobDef
  smoothX: MotionValue<number>
  smoothY: MotionValue<number>
}) {
  const tx = useTransform(smoothX, [0, 1], [-blob.px * 180,  blob.px * 180])
  const ty = useTransform(smoothY, [0, 1], [-blob.py * 140,  blob.py * 140])

  return (
    <motion.div
      className="absolute"
      style={{ top: blob.top, left: blob.left, right: blob.right, bottom: blob.bottom, x: tx, y: ty }}
    >
      <motion.div
        className="rounded-full"
        style={{
          width:      blob.w,
          height:     blob.h,
          background: `radial-gradient(circle, ${blob.color} 0%, transparent 70%)`,
          filter:     `blur(${blob.blur}px)`,
          opacity:    blob.op,
        }}
        animate={{ x: blob.dx, y: blob.dy }}
        transition={{ duration: blob.dur, repeat: Infinity, ease: 'linear' }}
      />
    </motion.div>
  )
}

/* ── Main component ─────────────────────────────────────────────── */
export function AnimatedBackground() {
  const { resolvedTheme } = useTheme()
  const isDark = resolvedTheme !== 'light'

  const rawX    = useMotionValue(0.5)
  const rawY    = useMotionValue(0.5)
  const smoothX = useSpring(rawX, { stiffness: 22, damping: 32, mass: 2.8 })
  const smoothY = useSpring(rawY, { stiffness: 22, damping: 32, mass: 2.8 })

  useEffect(() => {
    const handle = (e: MouseEvent) => {
      rawX.set(e.clientX / window.innerWidth)
      rawY.set(e.clientY / window.innerHeight)
    }
    window.addEventListener('mousemove', handle, { passive: true })
    return () => window.removeEventListener('mousemove', handle)
  }, [rawX, rawY])

  /* ── LIGHT MODE ───────────────────────────────────────────────── */
  if (!isDark) {
    return (
      <div className="fixed inset-0 overflow-hidden pointer-events-none" aria-hidden="true">

        {/* 1 ── Soft top radial lift */}
        <div className="absolute inset-0" style={{
          background: 'radial-gradient(ellipse 90% 60% at 50% 0%, rgba(109,40,217,0.07) 0%, transparent 65%)',
        }} />

        {/* 2 ── Ultra-soft orbital blobs */}
        {LIGHT_BLOBS.map((blob) => (
          <PBlob key={blob.id} blob={blob} smoothX={smoothX} smoothY={smoothY} />
        ))}

        {/* 3 ── Sweeping aurora band — very faint */}
        <motion.div
          className="absolute inset-x-0 top-0 h-[55%]"
          animate={{ backgroundPosition: ['0% 50%', '100% 50%', '0% 50%'] }}
          transition={{ duration: 32, repeat: Infinity, ease: 'linear' }}
          style={{
            background: 'linear-gradient(90deg, transparent 0%, rgba(124,58,237,0.055) 22%, rgba(79,70,229,0.045) 44%, rgba(167,139,250,0.065) 70%, transparent 100%)',
            backgroundSize: '300% 100%',
            filter: 'blur(45px)',
          }}
        />

        {/* 4 ── Perspective floor grid */}
        <div className="absolute inset-x-0 bottom-0 h-[50%] overflow-hidden">
          <div
            className="absolute inset-0 animate-grid-scroll"
            style={{
              backgroundImage: [
                'linear-gradient(rgba(139,92,246,0.05) 1px, transparent 1px)',
                'linear-gradient(90deg, rgba(139,92,246,0.05) 1px, transparent 1px)',
              ].join(', '),
              backgroundSize: '64px 64px',
              transform: 'perspective(720px) rotateX(63deg)',
              transformOrigin: 'bottom center',
              maskImage: 'linear-gradient(to top, rgba(0,0,0,0.25) 0%, transparent 100%)',
              WebkitMaskImage: 'linear-gradient(to top, rgba(0,0,0,0.25) 0%, transparent 100%)',
            }}
          />
        </div>

        {/* 5 ── Breathing center orb */}
        <motion.div
          className="absolute rounded-full"
          style={{
            width: 440, height: 440,
            top: '15%', left: '50%', marginLeft: -220, marginTop: -220,
            background: 'radial-gradient(circle, rgba(139,92,246,0.10) 0%, transparent 70%)',
            filter: 'blur(64px)',
          }}
          animate={{ scale: [1, 1.16, 1], opacity: [0.55, 1, 0.55] }}
          transition={{ duration: 9, repeat: Infinity, ease: 'easeInOut' }}
        />

        {/* 6 ── Edge vignettes — white fade for airy feel */}
        <div className="absolute inset-0" style={{
          background: [
            'radial-gradient(ellipse 160% 35% at 50% 100%, rgba(245,244,254,0.90) 0%, transparent 55%),',
            'radial-gradient(ellipse 18% 100% at   0% 50%, rgba(245,244,254,0.65) 0%, transparent 52%),',
            'radial-gradient(ellipse 18% 100% at 100% 50%, rgba(245,244,254,0.65) 0%, transparent 52%)',
          ].join('\n'),
        }} />

        {/* 7 ── Subtle top conic bloom */}
        <div
          className="absolute top-0 left-1/2 -translate-x-1/2 w-[1100px] h-[380px]"
          style={{
            background: 'conic-gradient(from 198deg at 50% 0%, rgba(109,40,217,0.12), rgba(79,70,229,0.08), rgba(167,139,250,0.12), transparent)',
            filter: 'blur(80px)',
            opacity: 0.8,
          }}
        />
      </div>
    )
  }

  /* ── DARK MODE (original design, optimised counts) ─────────────── */
  return (
    <div className="fixed inset-0 overflow-hidden pointer-events-none" aria-hidden="true">

      {/* 1 ── Base radial lift */}
      <div className="absolute inset-0" style={{
        background: 'radial-gradient(ellipse 80% 55% at 50% 20%, rgba(79,70,229,0.11) 0%, transparent 72%)',
      }} />

      {/* 2 ── Perspective floor grid */}
      <div className="absolute inset-x-0 bottom-0 h-[56%] overflow-hidden">
        <div
          className="absolute inset-0 animate-grid-scroll"
          style={{
            backgroundImage: [
              'linear-gradient(rgba(139,92,246,0.07) 1px, transparent 1px)',
              'linear-gradient(90deg, rgba(139,92,246,0.07) 1px, transparent 1px)',
            ].join(', '),
            backgroundSize: '64px 64px',
            transform: 'perspective(720px) rotateX(63deg)',
            transformOrigin: 'bottom center',
            maskImage: 'linear-gradient(to top, rgba(0,0,0,0.55) 0%, transparent 100%)',
            WebkitMaskImage: 'linear-gradient(to top, rgba(0,0,0,0.55) 0%, transparent 100%)',
          }}
        />
      </div>

      {/* 3 ── Stars (18, down from 44) */}
      {STARS.map((s) => (
        <motion.div
          key={s.id}
          className="absolute rounded-full bg-white"
          style={{ left: `${s.x}%`, top: `${s.y}%`, width: s.size, height: s.size }}
          animate={{ opacity: [s.minOp, s.maxOp, s.minOp] }}
          transition={{ duration: s.dur, delay: s.delay, repeat: Infinity, ease: 'easeInOut' }}
        />
      ))}

      {/* 4a ── Primary aurora band */}
      <motion.div
        className="absolute inset-x-0 top-0 h-[68%] opacity-[0.17]"
        animate={{ backgroundPosition: ['0% 50%', '100% 50%', '0% 50%'] }}
        transition={{ duration: 24, repeat: Infinity, ease: 'linear' }}
        style={{
          background: 'linear-gradient(90deg, transparent 0%, rgba(124,58,237,0.60) 16%, rgba(79,70,229,0.50) 34%, rgba(6,182,212,0.32) 52%, rgba(167,139,250,0.60) 70%, rgba(109,40,217,0.48) 88%, transparent 100%)',
          backgroundSize: '360% 100%',
          filter: 'blur(50px)',
        }}
      />

      {/* 4b ── Secondary aurora band */}
      <motion.div
        className="absolute inset-x-0 top-[16%] h-[50%] opacity-[0.09]"
        animate={{ backgroundPosition: ['100% 50%', '0% 50%', '100% 50%'] }}
        transition={{ duration: 34, repeat: Infinity, ease: 'linear' }}
        style={{
          background: 'linear-gradient(90deg, transparent 0%, rgba(167,139,250,0.70) 20%, rgba(139,92,246,0.58) 42%, rgba(79,70,229,0.62) 64%, rgba(6,182,212,0.42) 86%, transparent 100%)',
          backgroundSize: '290% 100%',
          filter: 'blur(58px)',
        }}
      />

      {/* 5 ── Four blobs (down from 5) */}
      {DARK_BLOBS.map((blob) => (
        <PBlob key={blob.id} blob={blob} smoothX={smoothX} smoothY={smoothY} />
      ))}

      {/* 6 ── Central breathing orb */}
      <motion.div
        className="absolute rounded-full"
        style={{
          width: 300, height: 300,
          top: '24%', left: '50%', marginLeft: -150, marginTop: -150,
          background: 'radial-gradient(circle, rgba(139,92,246,0.7) 0%, transparent 70%)',
          filter: 'blur(52px)',
        }}
        animate={{ scale: [1, 1.22, 1], opacity: [0.07, 0.17, 0.07] }}
        transition={{ duration: 7, repeat: Infinity, ease: 'easeInOut' }}
      />

      {/* 7 ── Micro-particles (5, down from 22) */}
      {PARTICLES.map((p) => (
        <motion.div
          key={p.id}
          className="absolute rounded-full bg-white"
          style={{ left: `${p.x}%`, bottom: '-2px', width: p.size, height: p.size, opacity: 0 }}
          animate={{ y: [0, -1900], opacity: [0, p.op, p.op, 0] }}
          transition={{ duration: p.dur, delay: p.delay, repeat: Infinity, ease: 'linear' }}
        />
      ))}

      {/* 8 ── Ripple rings */}
      {RIPPLE_DELAYS.map((delay, i) => (
        <motion.div
          key={i}
          className="absolute rounded-full"
          style={{
            width: 380, height: 380,
            top: '25%', left: '50%', marginLeft: -190, marginTop: -190,
            border: '1px solid rgba(139,92,246,0.20)',
          }}
          animate={{ scale: [0.5, 3.1], opacity: [0.5, 0] }}
          transition={{ duration: 8, delay, repeat: Infinity, ease: 'easeOut' }}
        />
      ))}

      {/* 9 ── Top conic aurora bloom */}
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2 w-[1200px] h-[460px]"
        style={{
          background: 'conic-gradient(from 198deg at 50% 0%, rgba(109,40,217,0.80), rgba(79,70,229,0.65), rgba(6,182,212,0.42), rgba(167,139,250,0.78), transparent)',
          filter: 'blur(92px)',
          opacity: 0.13,
        }}
      />

      {/* 10 ── Noise grain */}
      <div className="absolute inset-0 noise-overlay" />

      {/* 11 ── Edge vignettes */}
      <div
        className="absolute inset-0"
        style={{
          background: [
            'radial-gradient(ellipse 150% 44% at 50% 100%, rgba(8,8,10,0.94) 0%, transparent 52%),',
            'radial-gradient(ellipse 20% 100% at   0%  50%, rgba(8,8,10,0.58) 0%, transparent 58%),',
            'radial-gradient(ellipse 20% 100% at 100%  50%, rgba(8,8,10,0.58) 0%, transparent 58%),',
            'radial-gradient(ellipse 100%  16% at  50%   0%, rgba(8,8,10,0.48) 0%, transparent 100%)',
          ].join('\n'),
        }}
      />
    </div>
  )
}
