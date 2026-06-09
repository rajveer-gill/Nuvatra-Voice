'use client'

/**
 * Per-navigation page transition. template.tsx (unlike layout.tsx) re-mounts on
 * every route change, so this cross-fades page content as you navigate — the
 * "feels like a native app" polish.
 *
 * Deliberately opacity-only: a transform on a wrapper around fixed elements
 * (the marketing nav / dashboard chrome) would break their positioning mid-
 * animation. Opacity creates a stacking context but NOT a containing block for
 * `position: fixed`, so this is safe. Static under prefers-reduced-motion.
 */

import { motion, useReducedMotion } from 'framer-motion'

export default function Template({ children }: { children: React.ReactNode }) {
  const reduce = useReducedMotion()
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: reduce ? 0 : 0.3, ease: 'easeOut' }}
    >
      {children}
    </motion.div>
  )
}
