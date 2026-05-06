'use client'

import { motion, useReducedMotion } from 'framer-motion'
import { BarChart3, CalendarClock, Headphones, MessageSquare, ShieldCheck, Zap } from 'lucide-react'
import { FeaturesDashboardCTA } from '@/components/call-surge/LandingCTAs'

const FEATURES = [
  { icon: Headphones, title: '24/7 coverage', desc: 'Always-on answering with consistent scripts and smart handoff.' },
  { icon: Zap, title: 'Low latency', desc: 'Responsive dialog that keeps callers engaged—not on hold.' },
  { icon: BarChart3, title: 'Visibility', desc: 'Logs and signals so you know what drove outcomes.' },
  { icon: ShieldCheck, title: 'Security-minded', desc: 'Auth via Clerk, tenant-scoped data, and disciplined API access.' },
  { icon: CalendarClock, title: 'Scheduling', desc: 'Appointments that reflect your real availability and rules.' },
  { icon: MessageSquare, title: 'Omnichannel', desc: 'Voice and SMS in one coherent thread for your team.' },
] as const

export function LandingFeatures() {
  const reduce = useReducedMotion()

  const grid = {
    hidden: {},
    visible: {
      transition: {
        staggerChildren: reduce ? 0 : 0.06,
        delayChildren: reduce ? 0 : 0.05,
      },
    },
  }

  const cell = {
    hidden: { opacity: 0, y: 14 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: reduce ? 0 : 0.38 },
    },
  }

  return (
    <section id="features" className="scroll-mt-24 px-4 py-24 md:py-32">
      <div className="mx-auto max-w-6xl">
        <motion.div
          className="flex flex-col items-start justify-between gap-6 md:flex-row md:items-end"
          initial={reduce ? false : { opacity: 0, y: 14 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-60px' }}
          transition={{ duration: reduce ? 0 : 0.45 }}
        >
          <div>
            <h2 className="font-display text-3xl font-semibold tracking-tight text-white md:text-4xl">
              Built for operators who care about quality
            </h2>
            <p className="mt-4 max-w-xl text-lg text-zinc-400">
              Enterprise-grade reliability with a consumer-grade experience—because your callers deserve both.
            </p>
          </div>
          <FeaturesDashboardCTA />
        </motion.div>
        <motion.div
          className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
          variants={grid}
          initial={reduce ? false : 'hidden'}
          whileInView="visible"
          viewport={{ once: true, margin: '-50px' }}
        >
          {FEATURES.map(({ icon: Icon, title, desc }) => (
            <motion.div
              key={title}
              variants={cell}
              className="flex gap-4 rounded-2xl border border-white/10 bg-white/[0.03] p-6 motion-safe-transition hover:bg-white/[0.06]"
            >
              <Icon className="h-6 w-6 shrink-0 text-cyan-400" aria-hidden />
              <div>
                <h3 className="font-display font-semibold text-white">{title}</h3>
                <p className="mt-1 text-sm text-zinc-400">{desc}</p>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  )
}
