import Link from 'next/link'
import Image from 'next/image'
import { ArrowRight } from 'lucide-react'
import MarketingNav from '@/components/MarketingNav'
import ContactForm from '@/components/ContactForm'
import { Reveal, RevealStagger, RevealItem } from '@/components/motion'
import { LandingHero } from '@/components/call-surge/LandingHero'
import { LandingMetricsStrip } from '@/components/call-surge/LandingMetricsStrip'
import { LandingOutcomes } from '@/components/call-surge/LandingOutcomes'
import { LandingHowWorks } from '@/components/call-surge/LandingHowWorks'
import { LandingFeatures } from '@/components/call-surge/LandingFeatures'

export default function HomePage() {
  return (
    <>
      <MarketingNav />
      <main className="bg-zinc-950 text-zinc-100">
        <LandingHero />
        <LandingMetricsStrip />
        <LandingOutcomes />
        <LandingHowWorks />
        <LandingFeatures />

        {/* Trust strip */}
        <section className="border-y border-white/10 px-4 py-16">
          <Reveal className="mx-auto max-w-4xl text-center">
            <p className="text-sm font-medium uppercase tracking-[0.25em] text-zinc-500">Trusted operations</p>
            <p className="mt-4 font-display text-2xl font-semibold text-white md:text-3xl">
              Designed for teams who cannot afford a dropped call.
            </p>
            <p className="mx-auto mt-4 max-w-2xl text-zinc-400">
              Whether you run one location or many, Call Surge scales with your front-office ambition—without scaling
              chaos.
            </p>
          </Reveal>
        </section>

        {/* Compliance / trust (conversion moment) */}
        <section className="border-t border-white/10 bg-zinc-950/80 px-4 py-10">
          <Reveal className="mx-auto flex max-w-4xl flex-wrap items-center justify-center gap-x-6 gap-y-3 text-center text-sm text-zinc-400">
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
          </Reveal>
        </section>

        {/* Contact */}
        <section id="contact" className="scroll-mt-24 px-4 pb-12 pt-8 md:pb-20">
          <div className="mx-auto grid max-w-6xl gap-12 lg:grid-cols-2 lg:gap-16">
            <Reveal>
              <h2 className="font-display text-3xl font-semibold tracking-tight text-white md:text-4xl">
                Let&apos;s talk
              </h2>
              <p className="mt-4 text-lg text-zinc-400">
                Tell us about your call volume, locations, and goals—we&apos;ll follow up fast.
              </p>
              <RevealStagger className="mt-10 space-y-6 text-zinc-300">
                <RevealItem>
                  <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Email</p>
                  <a href="mailto:info@nuvatrahq.com" className="mt-1 inline-block text-cyan-400 hover:text-cyan-300">
                    info@nuvatrahq.com
                  </a>
                </RevealItem>
                <RevealItem>
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
                </RevealItem>
              </RevealStagger>
            </Reveal>
            <Reveal direction="up" delay={0.1} className="rounded-2xl border border-white/10 bg-white p-8 shadow-2xl shadow-black/40">
              <ContactForm />
            </Reveal>
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
              <Link href="/#hero" className="motion-safe-transition hover:text-white">
                Home
              </Link>
              <Link href="/#features" className="motion-safe-transition hover:text-white">
                Features
              </Link>
              <Link href="/#contact" className="motion-safe-transition hover:text-white">
                Contact
              </Link>
              <Link href="/terms" className="motion-safe-transition hover:text-white">
                Terms
              </Link>
              <Link href="/privacy" className="motion-safe-transition hover:text-white">
                Privacy
              </Link>
              <Link href="/sms-consent" className="motion-safe-transition hover:text-white">
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
