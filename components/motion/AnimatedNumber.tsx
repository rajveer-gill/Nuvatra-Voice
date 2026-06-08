'use client'

/**
 * Count-up number — springs from 0 to `value` on mount and re-springs when the
 * value changes (e.g. live dashboard polling). Reduced-motion shows the final
 * value immediately. Locale-formatted (thousands separators).
 */

import { useEffect } from 'react'
import {
  motion,
  useMotionValue,
  useReducedMotion,
  useSpring,
  useTransform,
} from 'framer-motion'

interface AnimatedNumberProps {
  value: number
  className?: string
}

export function AnimatedNumber({ value, className }: AnimatedNumberProps) {
  const reduce = useReducedMotion()
  const mv = useMotionValue(0)
  const spring = useSpring(mv, { stiffness: 90, damping: 20, restDelta: 0.5 })
  const text = useTransform(spring, (v) => Math.round(v).toLocaleString())

  useEffect(() => {
    mv.set(value)
  }, [value, mv])

  if (reduce) return <span className={className}>{value.toLocaleString()}</span>
  return <motion.span className={className}>{text}</motion.span>
}
