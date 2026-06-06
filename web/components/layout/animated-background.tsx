'use client'

import { useEffect } from 'react'
import { motion, useMotionValue, useSpring, useTransform, type MotionValue } from 'framer-motion'

/* ── Deterministic pseudo-random data (stable across renders) ── */

const STARS = Array.from({ length: 44 }, (_, i) => ({
  id: i,
  x: ((i * 37.1 + 11) * 2.618) % 100,
  y: ((i * 23.7 + 7)  * 1.414) % 100,
  size: i % 7 === 0 ? 2 : 1,
  delay: (i * 0.38) % 9,
  dur:   3.2 + ((i * 0.7) % 5.4),
  minOp: 0.05 + ((i * 0.04) % 0.11),
  maxOp: 0.20 + ((i * 0.06) % 0.24),
}))

const PARTICLES = Array.from({ length: 22 }, (_, i) => ({
  id: i,
  x:    ((i * 47.3 + 5) * 3.14) % 100,
  size: 1 + ((i * 7) % 3) * 0.5,
  delay: (i * 0.75) % 18,
  dur:  18 + ((i * 3.3) % 24),
  op:   0.07 + ((i * 0.07) % 0.14),
}))

type BlobDef = {
  id: string
  color: string
  w: number
  h: number
  top?: string
  left?: string
  right?: string
  bottom?: string
  dur: number
  dx: number[]
  dy: number[]
  blur: number
  op: number
  px: number
  py: number
}

const BLOBS: BlobDef[] = [
  {
    id: 'b1', color: '#6D28D9', w: 760, h: 760,
    top: '0%', left: '8%',
    dur: 46, dx: [0, 130, 65, -80, 0], dy: [0, 70, 130, 65, 0],
    blur: 170, op: 0.24, px: 0.05, py: 0.03,
  },
  {
    id: 'b2', color: '#3730A3', w: 620, h: 620,
    top: '40%', right: '2%',
    dur: 54, dx: [0, -115, -55, 75, 0], dy: [0, -80, 95, -55, 0],
    blur: 160, op: 0.17, px: -0.06, py: -0.04,
  },
  {
    id: 'b3', color: '#0E7490', w: 540, h: 540,
    bottom: '6%', left: '28%',
    dur: 60, dx: [0, 90, -65, 110, 0], dy: [0, -100, -35, 80, 0],
    blur: 155, op: 0.10, px: 0.04, py: -0.04,
  },
  {
    id: 'b4', color: '#7C3AED', w: 660, h: 660,
    top: '16%', right: '16%',
    dur: 41, dx: [0, -90, 45, -50, 0], dy: [0, 60, -70, 90, 0],
    blur: 155, op: 0.16, px: -0.05, py: 0.05,
  },
  {
    id: 'b5', color: '#9333EA', w: 440, h: 440,
    top: '52%', left: '3%',
    dur: 36, dx: [0, 55, -35, 80, 0], dy: [0, 70, -45, 90, 0],
    blur: 135, op: 0.11, px: 0.06, py: 0.03,
  },
]

const RIPPLE_DELAYS: readonly number[] = [0, 2.6, 5.2]

/* PBlob — isolates useTransform hook calls away from the parent's .map() */
function PBlob({
  blob,
  smoothX,
  smoothY,
}: {
  blob: BlobDef
  smoothX: MotionValue<number>
  smoothY: MotionValue<number>
}) {
  const tx = useTransform(smoothX, [0, 1], [-blob.px * 180, blob.px * 180])
  const ty = useTransform(smoothY, [0, 1], [-blob.py * 140, blob.py * 140])

  return (
    /* outer wrapper: mouse parallax offset */
    <motion.div
      className="absolute"
      style={{
        top:    blob.top,
        left:   blob.left,
        right:  blob.right,
        bottom: blob.bottom,
        x: tx,
        y: ty,
      }}
    >
      {/* inner div: slow orbital drift */}
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

export function AnimatedBackground() {
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

  return (
    <div className="fixed inset-0 overflow-hidden pointer-events-none" aria-hidden="true">

      {/* 1 ── Base radial lift */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse 80% 55% at 50% 20%, rgba(79,70,229,0.11) 0%, transparent 72%)',
        }}
      />

      {/* 2 ── Perspective floor grid — CSS keyframe scrolls it toward the viewer */}
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
            WebkitMaskImage:
              'linear-gradient(to top, rgba(0,0,0,0.55) 0%, transparent 100%)',
          }}
        />
      </div>

      {/* 3 ── Star field */}
      {STARS.map((s) => (
        <motion.div
          key={s.id}
          className="absolute rounded-full bg-white"
          style={{ left: `${s.x}%`, top: `${s.y}%`, width: s.size, height: s.size }}
          animate={{ opacity: [s.minOp, s.maxOp, s.minOp] }}
          transition={{ duration: s.dur, delay: s.delay, repeat: Infinity, ease: 'easeInOut' }}
        />
      ))}

      {/* 4a ── Primary aurora band — sweeps left→right */}
      <motion.div
        className="absolute inset-x-0 top-0 h-[68%] opacity-[0.17]"
        animate={{ backgroundPosition: ['0% 50%', '100% 50%', '0% 50%'] }}
        transition={{ duration: 24, repeat: Infinity, ease: 'linear' }}
        style={{
          background: [
            'linear-gradient(90deg,',
            'transparent 0%,',
            'rgba(124,58,237,0.60) 16%,',
            'rgba(79,70,229,0.50) 34%,',
            'rgba(6,182,212,0.32) 52%,',
            'rgba(167,139,250,0.60) 70%,',
            'rgba(109,40,217,0.48) 88%,',
            'transparent 100%)',
          ].join(' '),
          backgroundSize: '360% 100%',
          filter: 'blur(50px)',
        }}
      />

      {/* 4b ── Secondary aurora band — sweeps right→left */}
      <motion.div
        className="absolute inset-x-0 top-[16%] h-[50%] opacity-[0.09]"
        animate={{ backgroundPosition: ['100% 50%', '0% 50%', '100% 50%'] }}
        transition={{ duration: 34, repeat: Infinity, ease: 'linear' }}
        style={{
          background: [
            'linear-gradient(90deg,',
            'transparent 0%,',
            'rgba(167,139,250,0.70) 20%,',
            'rgba(139,92,246,0.58) 42%,',
            'rgba(79,70,229,0.62) 64%,',
            'rgba(6,182,212,0.42) 86%,',
            'transparent 100%)',
          ].join(' '),
          backgroundSize: '290% 100%',
          filter: 'blur(58px)',
        }}
      />

      {/* 5 ── Five blobs — slow orbital drift + mouse parallax */}
      {BLOBS.map((blob) => (
        <PBlob key={blob.id} blob={blob} smoothX={smoothX} smoothY={smoothY} />
      ))}

      {/* 6 ── Central breathing orb */}
      <motion.div
        className="absolute rounded-full"
        style={{
          width:      300,
          height:     300,
          top:        '24%',
          left:       '50%',
          marginLeft: -150,
          marginTop:  -150,
          background: 'radial-gradient(circle, rgba(139,92,246,0.7) 0%, transparent 70%)',
          filter:     'blur(52px)',
        }}
        animate={{ scale: [1, 1.22, 1], opacity: [0.07, 0.17, 0.07] }}
        transition={{ duration: 7, repeat: Infinity, ease: 'easeInOut' }}
      />

      {/* 7 ── Floating micro-particles */}
      {PARTICLES.map((p) => (
        <motion.div
          key={p.id}
          className="absolute rounded-full bg-white"
          style={{
            left:   `${p.x}%`,
            bottom: '-2px',
            width:  p.size,
            height: p.size,
            opacity: 0,
          }}
          animate={{ y: [0, -1900], opacity: [0, p.op, p.op, 0] }}
          transition={{ duration: p.dur, delay: p.delay, repeat: Infinity, ease: 'linear' }}
        />
      ))}

      {/* 8 ── Ripple rings expanding from centre */}
      {RIPPLE_DELAYS.map((delay, i) => (
        <motion.div
          key={i}
          className="absolute rounded-full"
          style={{
            width:      380,
            height:     380,
            top:        '25%',
            left:       '50%',
            marginLeft: -190,
            marginTop:  -190,
            border:     '1px solid rgba(139,92,246,0.20)',
          }}
          animate={{ scale: [0.5, 3.1], opacity: [0.5, 0] }}
          transition={{ duration: 8, delay, repeat: Infinity, ease: 'easeOut' }}
        />
      ))}

      {/* 9 ── Top conic aurora bloom */}
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2 w-[1200px] h-[460px]"
        style={{
          background: [
            'conic-gradient(from 198deg at 50% 0%,',
            'rgba(109,40,217,0.80),',
            'rgba(79,70,229,0.65),',
            'rgba(6,182,212,0.42),',
            'rgba(167,139,250,0.78),',
            'transparent)',
          ].join(' '),
          filter:  'blur(92px)',
          opacity: 0.13,
        }}
      />

      {/* 10 ── Noise grain texture */}
      <div className="absolute inset-0 noise-overlay" />

      {/* 11 ── Edge vignettes — deepen all four sides */}
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
