'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Check } from 'lucide-react'
import { AppChrome } from '@/components/layout/AppChrome'
import { useApiClient } from '@/lib/api'

// Prices are display-only — the real charge comes from the Stripe price IDs on the
// backend. Keep these in sync with your Stripe products. Features mirror backend/plans.py.
const PLANS = [
  {
    id: 'starter',
    name: 'Starter',
    price: '$150',
    tagline: 'Get your AI receptionist answering & booking.',
    features: [
      '500 call minutes / month',
      'Answers calls & books appointments, 24/7',
      'Texts appointment confirmations',
      '100 two-way text conversations / month',
      '30-day call history',
    ],
  },
  {
    id: 'growth',
    name: 'Growth',
    price: '$250',
    popular: true,
    tagline: 'Fill more of the calendar and chase every lead.',
    features: [
      'Everything in Starter, plus:',
      '1,500 call minutes / month',
      'Appointment reminders (cut no-shows)',
      'Lead capture & follow-up texts',
      'SMS automations + CSV export',
      '90-day call history',
    ],
  },
  {
    id: 'pro',
    name: 'Pro',
    price: '$399',
    tagline: 'Full power for high-volume, multi-chair shops.',
    features: [
      'Everything in Growth, plus:',
      '3,500 call minutes / month',
      'Call recording & AI summaries',
      'Unlimited SMS automations & transfers',
      '1,000 text conversations / month',
      'Unlimited call history',
    ],
  },
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
              <label className="mb-2 block text-sm font-medium text-zinc-300">Choose a plan</label>
              <div className="grid gap-3">
                {PLANS.map((p) => {
                  const selected = plan === p.id
                  return (
                    <button
                      type="button"
                      key={p.id}
                      onClick={() => setPlan(p.id)}
                      className={`relative rounded-2xl border p-4 text-left transition ${
                        selected
                          ? 'border-cyan-500 bg-cyan-500/10 ring-1 ring-cyan-500/40'
                          : 'border-white/10 bg-zinc-950/40 hover:border-white/25'
                      }`}
                    >
                      {'popular' in p && (
                        <span className="absolute -top-2 right-4 rounded-full bg-gradient-to-r from-cyan-500 to-indigo-600 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white">
                          Most popular
                        </span>
                      )}
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-2">
                          <span
                            className={`h-4 w-4 shrink-0 rounded-full border ${
                              selected ? 'border-cyan-400 bg-cyan-400' : 'border-zinc-600'
                            }`}
                          />
                          <div>
                            <span className="text-base font-semibold text-white">{p.name}</span>
                            <p className="text-xs text-zinc-400">{p.tagline}</p>
                          </div>
                        </div>
                        <div className="shrink-0 text-right">
                          <span className="text-lg font-bold text-white">{p.price}</span>
                          <span className="block text-[11px] text-zinc-500">/month</span>
                        </div>
                      </div>
                      <ul className="mt-3 space-y-1.5 pl-6">
                        {p.features.map((f) => (
                          <li key={f} className="flex items-start gap-2 text-xs text-zinc-300">
                            <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-400" />
                            <span>{f}</span>
                          </li>
                        ))}
                      </ul>
                    </button>
                  )
                })}
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
