'use client'

import { motion, useReducedMotion } from 'framer-motion'

const METRICS = [
  { label: 'Missed calls recovered', value: 'Always-on' },
  { label: 'SMS + voice', value: 'Unified' },
  { label: 'Bookings', value: 'Calendar-ready' },
  { label: 'Your brand', value: 'On every call' },
] as const

export function LandingMetricsStrip() {
  const reduce = useReducedMotion()

  const container = {
    hidden: {},
    visible: {
      transition: {
        staggerChildren: reduce ? 0 : 0.06,
        delayChildren: reduce ? 0 : 0.05,
      },
    },
  }

  const cell = {
    hidden: { opacity: 0, y: 10 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: reduce ? 0 : 0.38, ease: [0.22, 1, 0.36, 1] },
    },
  }

  return (
    <section className="border-y border-white/10 bg-zinc-900/40 py-10 px-4 backdrop-blur-sm">
      <motion.div
        className="mx-auto grid max-w-5xl grid-cols-2 gap-8 md:grid-cols-4 md:gap-4"
        variants={container}
        initial={reduce ? false : 'hidden'}
        whileInView="visible"
        viewport={{ once: true, margin: '-40px' }}
      >
        {METRICS.map((item) => (
          <motion.div key={item.label} className="text-center md:text-left" variants={cell}>
            <p className="font-display text-2xl font-semibold text-white md:text-3xl">{item.value}</p>
            <p className="mt-1 text-sm text-zinc-500">{item.label}</p>
          </motion.div>
        ))}
      </motion.div>
    </section>
  )
}
