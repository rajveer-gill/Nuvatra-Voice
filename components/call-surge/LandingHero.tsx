'use client'

import Link from 'next/link'
import { motion, useReducedMotion } from 'framer-motion'
import { Sparkles } from 'lucide-react'
import { HeroPrimaryCTA } from '@/components/call-surge/LandingCTAs'
import { AuroraBackground } from '@/components/motion'

export function LandingHero() {
  const reduce = useReducedMotion()

  const container = {
    hidden: {},
    visible: {
      transition: {
        staggerChildren: reduce ? 0 : 0.07,
        delayChildren: reduce ? 0 : 0.04,
      },
    },
  }

  const item = {
    hidden: { opacity: 0, y: 14 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: reduce ? 0 : 0.42, ease: [0.22, 1, 0.36, 1] },
    },
  }

  return (
    <section id="hero" className="relative overflow-hidden pt-24 pb-16 px-4 md:pt-28 md:pb-24">
      <div className="pointer-events-none absolute inset-0 bg-call-surge-mesh" aria-hidden />
      <AuroraBackground />
      <motion.div
        className="relative mx-auto max-w-5xl text-center"
        variants={container}
        initial={reduce ? false : 'hidden'}
        animate="visible"
      >
        <motion.p
          className="mb-6 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-1.5 text-xs font-medium uppercase tracking-[0.2em] text-cyan-300/90 md:text-sm"
          variants={item}
        >
          <Sparkles className="h-3.5 w-3.5 md:h-4 md:w-4" aria-hidden />
          AI voice receptionist
        </motion.p>
        <motion.h1
          className="font-display text-4xl font-semibold leading-[1.08] tracking-tight text-white md:text-6xl lg:text-7xl"
          variants={item}
        >
          Turn every ring into{' '}
          <span className="bg-gradient-to-r from-cyan-300 via-white to-violet-300 bg-clip-text text-transparent">
            revenue
          </span>
          .
        </motion.h1>
        <motion.p
          className="mx-auto mt-6 max-w-2xl text-lg text-zinc-400 md:text-xl md:leading-relaxed"
          variants={item}
        >
          Call Surge answers calls and texts like your best front desk—24/7—so leads book, buyers get answers, and
          nothing slips through.
        </motion.p>
        <motion.div
          className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row"
          variants={item}
        >
          <HeroPrimaryCTA />
          <Link
            href="/#contact"
            className="inline-flex items-center justify-center rounded-full border border-white/15 bg-white/5 px-8 py-4 text-base font-semibold text-white motion-safe-transition hover:bg-white/10"
          >
            Talk to us
          </Link>
        </motion.div>
        <motion.p className="mt-6 text-sm text-zinc-500" variants={item}>
          Sign in with email and password, Google, Facebook, or Microsoft — then open your dashboard.
        </motion.p>
      </motion.div>
    </section>
  )
}
