'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { AppChrome } from '@/components/layout/AppChrome'
import { useApiClient } from '@/lib/api'

const PLANS = [
  { id: 'starter', name: 'Starter', tagline: 'Get your AI line answering calls' },
  { id: 'growth', name: 'Growth', tagline: 'Reminders, leads & more staff' },
  { id: 'pro', name: 'Pro', tagline: 'Call recording & unlimited team' },
] as const

type PlanId = (typeof PLANS)[number]['id']

export default function CreateBusinessPage() {
  const api = useApiClient()
  const router = useRouter()
  const [name, setName] = useState('')
  const [plan, setPlan] = useState<PlanId>('starter')
  const [areaCode, setAreaCode] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState(true)

  // If they already have a live business, skip this and go to the dashboard.
  useEffect(() => {
    api
      .get('/api/subscription')
      .then((r) => {
        if (r?.data?.can_use_app) router.replace('/dashboard')
        else setChecking(false) // no tenant yet, or pending payment — show the form
      })
      .catch(() => setChecking(false))
  }, [api, router])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await api.post('/api/onboarding/create-business', { name: name.trim(), plan })
      const res = await api.post('/api/create-checkout-session', {
        plan,
        area_code: areaCode.trim() || undefined,
      })
      const url = res?.data?.url
      if (url) {
        window.location.href = url
        return
      }
      setError('Could not start checkout. Please try again.')
      setSubmitting(false)
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Something went wrong. Please try again.')
      setSubmitting(false)
    }
  }

  if (checking) {
    return (
      <AppChrome>
        <main className="flex min-h-screen items-center justify-center">
          <div className="h-10 w-10 animate-spin rounded-full border-2 border-cyan-400/30 border-t-cyan-400" />
        </main>
      </AppChrome>
    )
  }

  return (
    <AppChrome>
      <main className="min-h-screen px-4 py-10 md:px-6">
        <div className="mx-auto max-w-lg">
          <h1 className="font-display text-2xl font-semibold text-white">Set up your business</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Tell us about your business and pick a plan. You&rsquo;ll add a card to start a 7-day free
            trial — then we set up your AI phone line automatically.
          </p>

          {error && (
            <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
              {error}
            </div>
          )}

          <form
            onSubmit={submit}
            className="mt-6 space-y-5 rounded-2xl border border-white/10 bg-zinc-900/70 p-6 shadow-xl backdrop-blur-md"
          >
            <div>
              <label className="mb-1 block text-sm font-medium text-zinc-300">Business name</label>
              <input
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Acme Salon"
                className="w-full rounded-lg border border-white/10 bg-zinc-950/60 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:border-cyan-500 focus:outline-none"
              />
              <p className="mt-1 text-xs text-zinc-500">Callers hear this in your greeting.</p>
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-zinc-300">Plan</label>
              <div className="grid gap-2">
                {PLANS.map((p) => (
                  <button
                    type="button"
                    key={p.id}
                    onClick={() => setPlan(p.id)}
                    className={`flex items-center justify-between rounded-xl border px-4 py-3 text-left transition ${
                      plan === p.id
                        ? 'border-cyan-500 bg-cyan-500/10'
                        : 'border-white/10 bg-zinc-950/40 hover:border-white/20'
                    }`}
                  >
                    <span>
                      <span className="block text-sm font-semibold text-white">{p.name}</span>
                      <span className="block text-xs text-zinc-500">{p.tagline}</span>
                    </span>
                    <span
                      className={`h-4 w-4 shrink-0 rounded-full border ${
                        plan === p.id ? 'border-cyan-400 bg-cyan-400' : 'border-zinc-600'
                      }`}
                    />
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-zinc-300">
                Preferred area code <span className="text-zinc-500">(optional)</span>
              </label>
              <input
                type="text"
                inputMode="numeric"
                maxLength={3}
                value={areaCode}
                onChange={(e) => setAreaCode(e.target.value.replace(/\D/g, '').slice(0, 3))}
                placeholder="e.g. 415"
                className="w-32 rounded-lg border border-white/10 bg-zinc-950/60 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:border-cyan-500 focus:outline-none"
              />
              <p className="mt-1 text-xs text-zinc-500">We&rsquo;ll try to get you a number in this area code.</p>
            </div>

            <button
              type="submit"
              disabled={submitting || !name.trim()}
              className="w-full rounded-full bg-gradient-to-r from-cyan-600 to-indigo-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-cyan-500/20 hover:brightness-110 disabled:opacity-50"
            >
              {submitting ? 'Starting checkout…' : 'Continue to payment'}
            </button>
            <p className="text-center text-xs text-zinc-500">Free for 7 days · cancel anytime</p>
          </form>
        </div>
      </main>
    </AppChrome>
  )
}
