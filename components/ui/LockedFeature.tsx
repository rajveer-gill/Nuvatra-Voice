'use client'

/** Upsell card shown in place of a plan-gated feature (e.g. Leads on Starter after the
 * trial ends). Cool, on-brand locked state with a one-click "upgrade" that opens the
 * Stripe billing portal (where plan switching is enabled). Reusable for any Pro feature. */

import { useState } from 'react'
import { Lock, Sparkles, ArrowRight, Check } from 'lucide-react'
import { useApiClient } from '@/lib/api'

export function LockedFeature({
  title,
  tagline,
  bullets = [],
}: {
  title: string
  tagline: string
  bullets?: string[]
}) {
  const api = useApiClient()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const upgrade = async () => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await api.post<{ url: string }>('/api/create-portal-session')
      if (data?.url) {
        window.location.href = data.url
        return
      }
      setError('Could not open billing. Please try again.')
    } catch {
      setError('Could not open billing. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-b from-zinc-900/80 to-zinc-950/90 p-8 text-center shadow-xl">
      <div className="pointer-events-none absolute -top-24 left-1/2 h-48 w-48 -translate-x-1/2 rounded-full bg-cyan-500/20 blur-3xl" />
      <div className="relative">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full border border-cyan-400/30 bg-cyan-500/10">
          <Lock className="h-6 w-6 text-cyan-300" aria-hidden />
        </div>
        <span className="inline-flex items-center gap-1 rounded-full border border-cyan-400/30 bg-cyan-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-cyan-300">
          <Sparkles className="h-3.5 w-3.5" /> Pro feature
        </span>
        <h2 className="mt-4 font-display text-2xl font-semibold text-white">{title}</h2>
        <p className="mx-auto mt-2 max-w-md text-sm text-zinc-400">{tagline}</p>
        {bullets.length > 0 && (
          <ul className="mx-auto mt-5 max-w-sm space-y-2 text-left">
            {bullets.map((b) => (
              <li key={b} className="flex items-start gap-2 text-sm text-zinc-300">
                <Check className="mt-0.5 h-4 w-4 shrink-0 text-cyan-400" aria-hidden />
                <span>{b}</span>
              </li>
            ))}
          </ul>
        )}
        <button
          type="button"
          onClick={() => void upgrade()}
          disabled={loading}
          className="mt-7 inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-cyan-600 to-indigo-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-cyan-500/20 hover:brightness-110 disabled:opacity-50"
        >
          {loading ? 'Opening…' : 'Upgrade your plan'}
          {!loading && <ArrowRight className="h-4 w-4" />}
        </button>
        {error && <p className="mt-3 text-sm text-red-300">{error}</p>}
        <p className="mt-3 text-xs text-zinc-500">
          Included on Growth and Pro · manage your plan anytime.
        </p>
      </div>
    </div>
  )
}
