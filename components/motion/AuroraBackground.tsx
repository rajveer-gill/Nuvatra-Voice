'use client'

/**
 * Ambient aurora — slowly drifting, breathing blurred gradient orbs for a
 * "this site is alive" backdrop. Decorative (pointer-events-none, aria-hidden),
 * GPU-only (transform/opacity), and fully static under prefers-reduced-motion.
 * Drop it inside any `relative overflow-hidden` container.
 */

import { motion, useReducedMotion } from 'framer-motion'

interface Orb {
  className: string
  anim: Record<string, number[]>
  dur: number
}

const ORBS: Orb[] = [
  {
    className: 'left-[8%] -top-24 h-[420px] w-[420px] bg-gradient-to-br from-cyan-500/30 to-transparent',
    anim: { x: [0, 50, -10, 0], y: [0, 30, -10, 0], scale: [1, 1.12, 0.98, 1] },
    dur: 22,
  },
  {
    className: 'right-[4%] top-8 h-[460px] w-[460px] bg-gradient-to-bl from-indigo-600/25 to-transparent',
    anim: { x: [0, -60, 0], y: [0, 40, 0], scale: [1, 1.08, 1] },
    dur: 27,
  },
  {
    className: 'left-[34%] top-[38%] h-[360px] w-[360px] bg-gradient-to-tr from-violet-600/20 to-transparent',
    anim: { x: [0, 40, -30, 0], y: [0, -30, 10, 0], scale: [1, 0.92, 1.06, 1] },
    dur: 24,
  },
]

export function AuroraBackground({ className = '' }: { className?: string }) {
  const reduce = useReducedMotion()
  return (
    <div className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`} aria-hidden>
      {ORBS.map((o, i) => (
        <motion.div
          key={i}
          className={`absolute rounded-full blur-3xl ${o.className}`}
          animate={reduce ? undefined : o.anim}
          transition={
            reduce
              ? undefined
              : {
                  duration: o.dur,
                  repeat: Infinity,
                  repeatType: 'mirror',
                  ease: 'easeInOut',
                  delay: i * 2,
                }
          }
        />
      ))}
    </div>
  )
}
