'use client'

import Link from 'next/link'
import { motion, useReducedMotion } from 'framer-motion'
import { CalendarClock, MessageSquare, PhoneIncoming } from 'lucide-react'

const CARDS = [
  {
    icon: PhoneIncoming,
    title: 'Never ghost a lead',
    body: 'Instant pickup with natural, on-brand dialog—so first impressions feel human, not robotic.',
    complianceLink: false,
  },
  {
    icon: CalendarClock,
    title: 'Fill the calendar',
    body: 'Appointment flows that sync with how you work, reducing back-and-forth and no-shows.',
    complianceLink: false,
  },
  {
    icon: MessageSquare,
    title: 'SMS that stays compliant',
    body: 'Continue conversations over text with consent-aware messaging and clear opt-out paths.',
    complianceLink: true,
  },
] as const

export function LandingOutcomes() {
  const reduce = useReducedMotion()

  const container = {
    hidden: {},
    visible: {
      transition: {
        staggerChildren: reduce ? 0 : 0.1,
        delayChildren: reduce ? 0 : 0.08,
      },
    },
  }

  const card = {
    hidden: { opacity: 0, y: 24 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: reduce ? 0 : 0.45, ease: [0.22, 1, 0.36, 1] },
    },
  }

  return (
    <section id="outcomes" className="scroll-mt-24 px-4 py-24 md:py-32">
      <div className="mx-auto max-w-6xl">
        <motion.div
          className="mx-auto max-w-2xl text-center"
          initial={reduce ? false : { opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={{ duration: reduce ? 0 : 0.5 }}
        >
          <h2 className="font-display text-3xl font-semibold tracking-tight text-white md:text-4xl">
            From missed rings to booked meetings
          </h2>
          <p className="mt-4 text-lg text-zinc-400">
            Your phones stop being a bottleneck. Call Surge qualifies intent, captures details, and routes what
            matters—automatically.
          </p>
        </motion.div>
        <motion.div
          className="mt-16 grid gap-6 md:grid-cols-3"
          variants={container}
          initial={reduce ? false : 'hidden'}
          whileInView="visible"
          viewport={{ once: true, margin: '-60px' }}
        >
          {CARDS.map(({ icon: Icon, title, body, complianceLink }) => (
            <motion.div
              key={title}
              variants={card}
              className="group rounded-2xl border border-white/10 bg-gradient-to-b from-white/[0.07] to-transparent p-8 motion-safe-transition hover:border-cyan-500/30 hover:shadow-lg hover:shadow-cyan-500/5"
            >
              <div className="mb-5 inline-flex rounded-xl border border-cyan-500/20 bg-cyan-500/10 p-3 text-cyan-300">
                <Icon className="h-6 w-6" aria-hidden />
              </div>
              <h3 className="font-display text-xl font-semibold text-white">{title}</h3>
              <p className="mt-3 leading-relaxed text-zinc-400">{body}</p>
              {complianceLink && (
                <p className="mt-4 text-sm">
                  <Link
                    href="/sms-consent"
                    className="font-medium text-cyan-400 underline-offset-4 hover:text-cyan-300 hover:underline"
                  >
                    SMS consent &amp; opt-out policy
                  </Link>
                </p>
              )}
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  )
}
