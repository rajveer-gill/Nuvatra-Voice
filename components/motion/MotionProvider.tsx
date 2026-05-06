'use client'

import { LazyMotion, domAnimation } from 'framer-motion'

/**
 * Loads Framer’s DOM animation feature bundle once. Children may use `motion` from `framer-motion`.
 */
export function MotionProvider({ children }: { children: React.ReactNode }) {
  return <LazyMotion features={domAnimation}>{children}</LazyMotion>
}
