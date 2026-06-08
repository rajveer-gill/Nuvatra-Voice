'use client'

/**
 * Scroll-reveal primitives — the reusable building blocks for the site-wide
 * motion pass. Server components can wrap any section in <Reveal> to get a
 * polished on-scroll entrance without becoming client components themselves.
 *
 * Performance & a11y: animates transform/opacity only (GPU-friendly, no layout
 * thrash), fires once, and collapses to no motion when prefers-reduced-motion
 * is set. Uses the shared easing so every surface feels consistent.
 */

import { motion, useReducedMotion } from 'framer-motion'
import type { ReactNode } from 'react'

const EASE = [0.22, 1, 0.36, 1] as const
const VIEWPORT = { once: true, margin: '0px 0px -12% 0px' } as const

type Dir = 'up' | 'down' | 'left' | 'right' | 'none'

function offset(dir: Dir, distance: number) {
  switch (dir) {
    case 'up':
      return { y: distance }
    case 'down':
      return { y: -distance }
    case 'left':
      return { x: distance }
    case 'right':
      return { x: -distance }
    default:
      return {}
  }
}

interface RevealProps {
  children: ReactNode
  className?: string
  /** Entrance direction (default 'up'). */
  direction?: Dir
  /** Travel distance in px (default 24). */
  distance?: number
  /** Seconds to delay (default 0). */
  delay?: number
  /** Seconds for the motion (default 0.6). */
  duration?: number
}

/** Fade + slide a block into view on scroll. */
export function Reveal({
  children,
  className,
  direction = 'up',
  distance = 24,
  delay = 0,
  duration = 0.6,
}: RevealProps) {
  const reduce = useReducedMotion()
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, ...offset(direction, distance) }}
      whileInView={{ opacity: 1, x: 0, y: 0 }}
      viewport={VIEWPORT}
      transition={{ duration: reduce ? 0 : duration, ease: EASE, delay: reduce ? 0 : delay }}
    >
      {children}
    </motion.div>
  )
}

interface StaggerProps {
  children: ReactNode
  className?: string
  /** Seconds between each child (default 0.08). */
  stagger?: number
}

/** Container that staggers its <RevealItem> children into view. */
export function RevealStagger({ children, className, stagger = 0.08 }: StaggerProps) {
  return (
    <motion.div
      className={className}
      initial="hidden"
      whileInView="visible"
      viewport={VIEWPORT}
      variants={{
        hidden: {},
        visible: { transition: { staggerChildren: stagger, delayChildren: 0.05 } },
      }}
    >
      {children}
    </motion.div>
  )
}

interface ItemProps {
  children: ReactNode
  className?: string
  distance?: number
}

/** A single child of <RevealStagger>. */
export function RevealItem({ children, className, distance = 16 }: ItemProps) {
  const reduce = useReducedMotion()
  return (
    <motion.div
      className={className}
      variants={{
        hidden: reduce ? { opacity: 0 } : { opacity: 0, y: distance },
        visible: {
          opacity: 1,
          y: 0,
          transition: { duration: reduce ? 0 : 0.5, ease: EASE },
        },
      }}
    >
      {children}
    </motion.div>
  )
}
