'use client'

/** At-a-glance fleet health for 60+ stores. Derived entirely from the tenant
 * records the admin page already loaded — no extra API/Twilio/Clerk calls. */

import { useMemo } from 'react'
import { Reveal, AnimatedNumber } from '@/components/motion'

interface TenantLite {
  twilio_phone_number?: string | null
  subscription_status?: string | null
  trial_ends_at?: string | null
  billing_exempt_until?: string | null
}

type Health = 'active' | 'trial' | 'attention' | 'no_number'

function classify(t: TenantLite): Health {
  if (!(t.twilio_phone_number || '').trim()) return 'no_number'
  const status = (t.subscription_status || '').toLowerCase()
  const exempt =
    !!t.billing_exempt_until && new Date(t.billing_exempt_until).getTime() > Date.now()
  if (status === 'active' || exempt) return 'active'
  if (status === 'trialing') {
    const trialOk = !!t.trial_ends_at && new Date(t.trial_ends_at).getTime() > Date.now()
    return trialOk ? 'trial' : 'attention'
  }
  return 'attention'
}

export function FleetHealthSummary({ tenants }: { tenants: TenantLite[] }) {
  const counts = useMemo(() => {
    const c = { total: tenants.length, active: 0, trial: 0, attention: 0, no_number: 0 }
    for (const t of tenants) c[classify(t)] += 1
    return c
  }, [tenants])

  if (!tenants.length) return null

  const tiles = [
    { label: 'Total stores', value: counts.total, tone: 'text-white', ring: 'border-white/10' },
    { label: 'Active', value: counts.active, tone: 'text-emerald-300', ring: 'border-emerald-500/30' },
    { label: 'On trial', value: counts.trial, tone: 'text-cyan-300', ring: 'border-cyan-500/30' },
    {
      label: 'Need attention',
      value: counts.attention + counts.no_number,
      tone: 'text-amber-300',
      ring: 'border-amber-500/30',
    },
  ]

  return (
    <Reveal className="mb-8">
      <section className="rounded-2xl border border-white/10 bg-zinc-900/70 p-6 shadow-xl backdrop-blur-md md:p-8">
        <h2 className="font-display text-lg font-semibold text-white">Fleet health</h2>
        <p className="mb-4 text-xs text-zinc-500">Derived from tenant records — no external calls.</p>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {tiles.map((t) => (
            <div key={t.label} className={`rounded-xl border ${t.ring} bg-black/20 p-4`}>
              <p className={`font-display text-3xl font-bold ${t.tone}`}>
                <AnimatedNumber value={t.value} />
              </p>
              <p className="mt-1 text-xs text-zinc-400">{t.label}</p>
            </div>
          ))}
        </div>
        {counts.no_number > 0 && (
          <p className="mt-4 text-xs text-amber-400/90">
            {counts.no_number} store{counts.no_number === 1 ? '' : 's'} without a phone number — they can&apos;t receive calls.
          </p>
        )}
      </section>
    </Reveal>
  )
}
