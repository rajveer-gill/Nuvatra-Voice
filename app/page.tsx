import Link from 'next/link'
import Image from 'next/image'
import {
  ArrowRight,
  BarChart3,
  CalendarClock,
  Headphones,
  MessageSquare,
  PhoneIncoming,
  ShieldCheck,
  Sparkles,
  Zap,
} from 'lucide-react'
import MarketingNav from '@/components/MarketingNav'
import ContactForm from '@/components/ContactForm'
import { FeaturesDashboardCTA, HeroPrimaryCTA } from '@/components/call-surge/LandingCTAs'

export default function HomePage() {
  return (
    <>
      <MarketingNav />
      <main className="bg-zinc-950 text-zinc-100">
        {/* Hero */}
        <section id="hero" className="relative overflow-hidden pt-24 pb-16 px-4 md:pt-28 md:pb-24">
          <div className="pointer-events-none absolute inset-0 bg-call-surge-mesh" aria-hidden />
          <div
            className="pointer-events-none absolute -top-40 left-1/2 h-[520px] w-[min(140%,900px)] -translate-x-1/2 rounded-full bg-gradient-to-b from-cyan-500/25 via-indigo-600/15 to-transparent blur-3xl"
            aria-hidden
          />
          <div className="relative mx-auto max-w-5xl text-center">
            <p className="mb-6 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-1.5 text-xs font-medium uppercase tracking-[0.2em] text-cyan-300/90 md:text-sm">
              <Sparkles className="h-3.5 w-3.5 md:h-4 md:w-4" aria-hidden />
              AI voice receptionist
            </p>
            <h1 className="font-display text-4xl font-semibold leading-[1.08] tracking-tight text-white md:text-6xl lg:text-7xl">
              Turn every ring into{' '}
              <span className="bg-gradient-to-r from-cyan-300 via-white to-violet-300 bg-clip-text text-transparent">
                revenue
              </span>
              .
            </h1>
            <p className="mx-auto mt-6 max-w-2xl text-lg text-zinc-400 md:text-xl md:leading-relaxed">
              Call Surge answers calls and texts like your best front desk—24/7—so leads book, buyers get answers,
              and nothing slips through.
            </p>
            <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
              <HeroPrimaryCTA />
              <Link
                href="/#contact"
                className="inline-flex items-center justify-center rounded-full border border-white/15 bg-white/5 px-8 py-4 text-base font-semibold text-white transition hover:bg-white/10"
              >
                Talk to us
              </Link>
            </div>
            <p className="mt-6 text-sm text-zinc-500">Invite-only access. Sign in with your organization.</p>
          </div>
        </section>

        {/* Metrics strip */}
        <section className="border-y border-white/10 bg-zinc-900/40 py-10 px-4 backdrop-blur-sm">
          <div className="mx-auto grid max-w-5xl grid-cols-2 gap-8 md:grid-cols-4 md:gap-4">
            {[
              { label: 'Missed calls recovered', value: 'Always-on' },
              { label: 'SMS + voice', value: 'Unified' },
              { label: 'Bookings', value: 'Calendar-ready' },
              { label: 'Your brand', value: 'On every call' },
            ].map((item) => (
              <div key={item.label} className="text-center md:text-left">
                <p className="font-display text-2xl font-semibold text-white md:text-3xl">{item.value}</p>
                <p className="mt-1 text-sm text-zinc-500">{item.label}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Outcomes */}
        <section id="outcomes" className="scroll-mt-24 px-4 py-24 md:py-32">
          <div className="mx-auto max-w-6xl">
            <div className="mx-auto max-w-2xl text-center">
              <h2 className="font-display text-3xl font-semibold tracking-tight text-white md:text-4xl">
                From missed rings to booked meetings
              </h2>
              <p className="mt-4 text-lg text-zinc-400">
                Your phones stop being a bottleneck. Call Surge qualifies intent, captures details, and routes what
                matters—automatically.
              </p>
            </div>
            <div className="mt-16 grid gap-6 md:grid-cols-3">
              {[
                {
                  icon: PhoneIncoming,
                  title: 'Never ghost a lead',
                  body: 'Instant pickup with natural, on-brand dialog—so first impressions feel human, not robotic.',
                },
                {
                  icon: CalendarClock,
                  title: 'Fill the calendar',
                  body: 'Appointment flows that sync with how you work, reducing back-and-forth and no-shows.',
                },
                {
                  icon: MessageSquare,
                  title: 'SMS that stays compliant',
                  body: 'Continue conversations over text with consent-aware messaging and clear opt-out paths.',
                },
              ].map(({ icon: Icon, title, body }) => (
                <div
                  key={title}
                  className="group rounded-2xl border border-white/10 bg-gradient-to-b from-white/[0.07] to-transparent p-8 transition hover:border-cyan-500/30 hover:shadow-lg hover:shadow-cyan-500/5"
                >
                  <div className="mb-5 inline-flex rounded-xl border border-cyan-500/20 bg-cyan-500/10 p-3 text-cyan-300">
                    <Icon className="h-6 w-6" aria-hidden />
                  </div>
                  <h3 className="font-display text-xl font-semibold text-white">{title}</h3>
                  <p className="mt-3 leading-relaxed text-zinc-400">{body}</p>
                  {title === 'SMS that stays compliant' && (
                    <p className="mt-4 text-sm">
                      <Link
                        href="/sms-consent"
                        className="font-medium text-cyan-400 underline-offset-4 hover:text-cyan-300 hover:underline"
                      >
                        SMS consent &amp; opt-out policy
                      </Link>
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* How it works */}
        <section id="how" className="scroll-mt-24 border-t border-white/10 bg-zinc-900/30 px-4 py-24 md:py-32">
          <div className="mx-auto max-w-6xl">
            <h2 className="font-display text-center text-3xl font-semibold tracking-tight text-white md:text-4xl">
              How it works
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-center text-lg text-zinc-400">
              Live in days—not quarters. We layer intelligence on your existing number and workflows.
            </p>
            <ol className="mt-16 grid gap-8 md:grid-cols-2 lg:grid-cols-4">
              {[
                { step: '01', title: 'Connect', desc: 'Link your business context, hours, and services.' },
                { step: '02', title: 'Configure', desc: 'Tune voice, SMS, routing, and escalation rules.' },
                { step: '03', title: 'Launch', desc: 'Point traffic at Call Surge—calls and texts flow in.' },
                { step: '04', title: 'Optimize', desc: 'Review transcripts, outcomes, and funnel metrics.' },
              ].map((item, i) => (
                <li
                  key={item.step}
                  className="relative rounded-2xl border border-white/10 bg-zinc-950/80 p-6 pt-10"
                >
                  <span className="font-display absolute left-6 top-4 text-sm font-bold text-cyan-400/80">
                    {item.step}
                  </span>
                  <h3 className="font-display text-lg font-semibold text-white">{item.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-zinc-400">{item.desc}</p>
                  {i < 3 && (
                    <div
                      className="absolute -right-4 top-1/2 hidden h-px w-8 -translate-y-1/2 bg-gradient-to-r from-cyan-500/50 to-transparent lg:block"
                      aria-hidden
                    />
                  )}
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Features */}
        <section id="features" className="scroll-mt-24 px-4 py-24 md:py-32">
          <div className="mx-auto max-w-6xl">
            <div className="flex flex-col items-start justify-between gap-6 md:flex-row md:items-end">
              <div>
                <h2 className="font-display text-3xl font-semibold tracking-tight text-white md:text-4xl">
                  Built for operators who care about quality
                </h2>
                <p className="mt-4 max-w-xl text-lg text-zinc-400">
                  Enterprise-grade reliability with a consumer-grade experience—because your callers deserve both.
                </p>
              </div>
              <FeaturesDashboardCTA />
            </div>
            <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {[
                {
                  icon: Headphones,
                  title: '24/7 coverage',
                  desc: 'Always-on answering with consistent scripts and smart handoff.',
                },
                {
                  icon: Zap,
                  title: 'Low latency',
                  desc: 'Responsive dialog that keeps callers engaged—not on hold.',
                },
                {
                  icon: BarChart3,
                  title: 'Visibility',
                  desc: 'Logs and signals so you know what drove outcomes.',
                },
                {
                  icon: ShieldCheck,
                  title: 'Security-minded',
                  desc: 'Auth via Clerk, tenant-scoped data, and disciplined API access.',
                },
                {
                  icon: CalendarClock,
                  title: 'Scheduling',
                  desc: 'Appointments that reflect your real availability and rules.',
                },
                {
                  icon: MessageSquare,
                  title: 'Omnichannel',
                  desc: 'Voice and SMS in one coherent thread for your team.',
                },
              ].map(({ icon: Icon, title, desc }) => (
                <div
                  key={title}
                  className="flex gap-4 rounded-2xl border border-white/10 bg-white/[0.03] p-6 transition hover:bg-white/[0.06]"
                >
                  <Icon className="h-6 w-6 shrink-0 text-cyan-400" aria-hidden />
                  <div>
                    <h3 className="font-display font-semibold text-white">{title}</h3>
                    <p className="mt-1 text-sm text-zinc-400">{desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Trust strip */}
        <section className="border-y border-white/10 px-4 py-16">
          <div className="mx-auto max-w-4xl text-center">
            <p className="text-sm font-medium uppercase tracking-[0.25em] text-zinc-500">Trusted operations</p>
            <p className="mt-4 font-display text-2xl font-semibold text-white md:text-3xl">
              Designed for teams who cannot afford a dropped call.
            </p>
            <p className="mx-auto mt-4 max-w-2xl text-zinc-400">
              Whether you run one location or many, Call Surge scales with your front-office ambition—without scaling
              chaos.
            </p>
          </div>
        </section>

        {/* Compliance / trust (conversion moment) */}
        <section className="border-t border-white/10 bg-zinc-950/80 px-4 py-10">
          <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-center gap-x-6 gap-y-3 text-center text-sm text-zinc-400">
            <span>Clerk authentication</span>
            <span className="hidden text-zinc-600 sm:inline" aria-hidden>
              ·
            </span>
            <span>Tenant-scoped data</span>
            <span className="hidden text-zinc-600 sm:inline" aria-hidden>
              ·
            </span>
            <Link href="/sms-consent" className="text-cyan-400 transition hover:text-cyan-300">
              TCPA-aware SMS
            </Link>
            <span className="hidden text-zinc-600 sm:inline" aria-hidden>
              ·
            </span>
            <span>Twilio-backed voice &amp; SMS</span>
            <span className="hidden text-zinc-600 sm:inline" aria-hidden>
              ·
            </span>
            <Link href="/privacy" className="text-cyan-400 transition hover:text-cyan-300">
              Privacy
            </Link>
          </div>
        </section>

        {/* Contact */}
        <section id="contact" className="scroll-mt-24 px-4 pb-12 pt-8 md:pb-20">
          <div className="mx-auto grid max-w-6xl gap-12 lg:grid-cols-2 lg:gap-16">
            <div>
              <h2 className="font-display text-3xl font-semibold tracking-tight text-white md:text-4xl">
                Let&apos;s talk
              </h2>
              <p className="mt-4 text-lg text-zinc-400">
                Tell us about your call volume, locations, and goals—we&apos;ll follow up fast.
              </p>
              <div className="mt-10 space-y-6 text-zinc-300">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Email</p>
                  <a href="mailto:info@nuvatrahq.com" className="mt-1 inline-block text-cyan-400 hover:text-cyan-300">
                    info@nuvatrahq.com
                  </a>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Company</p>
                  <a
                    href="https://nuvatrahq.com"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-1 inline-flex items-center gap-1 text-cyan-400 hover:text-cyan-300"
                  >
                    Nuvatra HQ
                    <ArrowRight className="h-4 w-4" />
                  </a>
                </div>
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white p-8 shadow-2xl shadow-black/40">
              <ContactForm />
            </div>
          </div>
        </section>

        {/* Footer */}
        <footer className="border-t border-white/10 bg-black/40 px-4 py-12">
          <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-8 md:flex-row">
            <div className="flex items-center gap-3">
              <Image src="/assets/call-surge-mark.svg" alt="Call Surge" width={36} height={36} />
              <span className="font-display text-lg font-semibold text-white">Call Surge</span>
            </div>
            <nav className="flex flex-wrap justify-center gap-x-8 gap-y-3 text-sm text-zinc-400">
              <Link href="/#hero" className="transition hover:text-white">
                Home
              </Link>
              <Link href="/#features" className="transition hover:text-white">
                Features
              </Link>
              <Link href="/#contact" className="transition hover:text-white">
                Contact
              </Link>
              <Link href="/terms" className="transition hover:text-white">
                Terms
              </Link>
              <Link href="/privacy" className="transition hover:text-white">
                Privacy
              </Link>
              <Link href="/sms-consent" className="transition hover:text-white">
                SMS consent
              </Link>
            </nav>
            <div className="text-center text-sm text-zinc-500 md:text-right">
              <p>
                A product of{' '}
                <a
                  href="https://nuvatrahq.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-zinc-400 underline-offset-4 hover:text-white hover:underline"
                >
                  Nuvatra
                </a>
              </p>
              <p className="mt-1">&copy; {new Date().getFullYear()} Call Surge. All rights reserved.</p>
            </div>
          </div>
        </footer>
      </main>
    </>
  )
}
