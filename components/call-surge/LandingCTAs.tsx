'use client'

import { SignInButton } from '@clerk/nextjs'
import { ArrowRight } from 'lucide-react'

export function HeroPrimaryCTA() {
  return (
    <SignInButton mode="modal">
      <button
        type="button"
        className="group inline-flex items-center justify-center gap-2 rounded-full bg-gradient-to-r from-cyan-500 to-indigo-600 px-8 py-4 text-base font-semibold text-white shadow-xl shadow-cyan-500/25 transition hover:brightness-110 hover:gap-3"
      >
        Get started
        <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-0.5" />
      </button>
    </SignInButton>
  )
}

export function FeaturesDashboardCTA() {
  return (
    <SignInButton mode="modal">
      <button
        type="button"
        className="inline-flex items-center gap-2 rounded-full border border-white/20 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-white/10"
      >
        Open dashboard
        <ArrowRight className="h-4 w-4" />
      </button>
    </SignInButton>
  )
}
