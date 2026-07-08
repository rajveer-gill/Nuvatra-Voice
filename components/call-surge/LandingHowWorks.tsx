'use client'

import { motion, useReducedMotion } from 'framer-motion'

const STEPS = [
  { step: '01', title: 'Connect', desc: 'Link your business context, hours, and services.' },
  { step: '02', title: 'Configure', desc: 'Tune voice, SMS, routing, and escalation rules.' },
  { step: '03', title: 'Launch', desc: 'Forward your existing number—no porting, no new line. Calls and texts flow in.' },
  { step: '04', title: 'Optimize', desc: 'Review transcripts, outcomes, and funnel metrics.' },
] as const

export function LandingHowWorks() {
  const reduce = useReducedMotion()

  const container = {
    hidden: {},
    visible: {
      transition: {
        staggerChildren: reduce ? 0 : 0.08,
        delayChildren: reduce ? 0 : 0.06,
      },
    },
  }

  const item = {
    hidden: { opacity: 0, y: 18 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: reduce ? 0 : 0.42 },
    },
  }

  return (
    <section id="how" className="scroll-mt-24 border-t border-white/10 bg-zinc-900/30 px-4 py-24 md:py-32">
      <div className="mx-auto max-w-6xl">
        <motion.div
          className="text-center"
          initial={reduce ? false : { opacity: 0, y: 12 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-60px' }}
          transition={{ duration: reduce ? 0 : 0.45 }}
        >
          <h2 className="font-display text-3xl font-semibold tracking-tight text-white md:text-4xl">How it works</h2>
          <p className="mx-auto mt-4 max-w-xl text-lg text-zinc-400">
            Live in days—not quarters. We layer intelligence on your existing number and workflows.
          </p>
        </motion.div>
        <motion.ol
          className="mt-16 grid gap-8 md:grid-cols-2 lg:grid-cols-4"
          variants={container}
          initial={reduce ? false : 'hidden'}
          whileInView="visible"
          viewport={{ once: true, margin: '-40px' }}
        >
          {STEPS.map((itemData, i) => (
            <motion.li
              key={itemData.step}
              variants={item}
              className="relative rounded-2xl border border-white/10 bg-zinc-950/80 p-6 pt-10"
            >
              <span className="font-display absolute left-6 top-4 text-sm font-bold text-cyan-400/80">
                {itemData.step}
              </span>
              <h3 className="font-display text-lg font-semibold text-white">{itemData.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-zinc-400">{itemData.desc}</p>
              {i < 3 && (
                <div
                  className="absolute -right-4 top-1/2 hidden h-px w-8 -translate-y-1/2 bg-gradient-to-r from-cyan-500/50 to-transparent lg:block"
                  aria-hidden
                />
              )}
            </motion.li>
          ))}
        </motion.ol>
      </div>
    </section>
  )
}
