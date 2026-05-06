'use client'

import { motion, useReducedMotion } from 'framer-motion'

/** Subtle entrance for Clerk auth pages — respects reduced motion. */
export function AuthMainFade({ children }: { children: React.ReactNode }) {
  const reduce = useReducedMotion()

  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reduce ? 0 : 0.45, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  )
}
