'use client'

/** Admin referral program: create shareable codes, see who signed up, and track
 * payouts owed to referrers. "Mark paid" is record-keeping only — it never sends money. */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useApiClient, sameOriginApiConfig } from '@/lib/api'
import { Skeleton } from '@/components/ui/Skeleton'
import { CollapsibleSection } from '@/components/ui/CollapsibleSection'
import { Copy, Check } from 'lucide-react'

interface ReferralCode {
  id: number
  code: string
  referrer_name: string
  referrer_contact?: string | null
  active: boolean
  signups: number
  converted: number
  flagged: number
}

interface Commission {
  id: number
  kind: 'signup_bounty' | 'mrr'
  amount_cents: number
  plan_snapshot?: string | null
  code_snapshot: string
  referrer_name: string
  paid: boolean
  paid_at?: string | null
  created_at?: string | null
  business_name?: string | null
}

function money(cents: number): string {
  return `$${(cents / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function commissionLabel(c: Commission): string {
  if (c.kind === 'signup_bounty') return 'Signup bonus'
  const plan = c.plan_snapshot ? ` (${c.plan_snapshot})` : ''
  return `Monthly commission${plan}`
}

function whenLabel(iso?: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
}

export function ReferralsPanel() {
  const api = useApiClient()
  const adminApi = useMemo(() => sameOriginApiConfig(), [])

  const [codes, setCodes] = useState<ReferralCode[] | null>(null)
  const [commissions, setCommissions] = useState<Commission[] | null>(null)
  const [unpaidTotal, setUnpaidTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Create-code form
  const [form, setForm] = useState({ code: '', referrer_name: '', referrer_contact: '' })
  const [creating, setCreating] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)
  const [savingId, setSavingId] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [codesRes, commRes] = await Promise.all([
        api.get<{ codes: ReferralCode[] }>('/api/admin/referral-codes', adminApi),
        api.get<{ commissions: Commission[]; unpaid_total_cents: number }>(
          '/api/admin/referral-commissions',
          adminApi,
        ),
      ])
      setCodes(codesRes.data.codes || [])
      setCommissions(commRes.data.commissions || [])
      setUnpaidTotal(commRes.data.unpaid_total_cents || 0)
    } catch {
      setError('Failed to load referrals.')
    } finally {
      setLoading(false)
    }
  }, [api, adminApi])

  useEffect(() => {
    void load()
  }, [load])

  const createCode = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.code.trim() || !form.referrer_name.trim()) return
    setCreating(true)
    setError(null)
    setSuccess(null)
    try {
      await api.post(
        '/api/admin/referral-codes',
        {
          code: form.code.trim(),
          referrer_name: form.referrer_name.trim(),
          referrer_contact: form.referrer_contact.trim() || undefined,
        },
        adminApi,
      )
      setSuccess(`Code ${form.code.trim().toUpperCase()} is live — share it!`)
      setForm({ code: '', referrer_name: '', referrer_contact: '' })
      await load()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Could not create the code.')
    } finally {
      setCreating(false)
    }
  }

  const toggleActive = async (c: ReferralCode) => {
    setSavingId(c.id)
    setError(null)
    try {
      await api.patch(`/api/admin/referral-codes/${c.id}`, { active: !c.active }, adminApi)
      await load()
    } catch {
      setError('Could not update the code.')
    } finally {
      setSavingId(null)
    }
  }

  const markPaid = async (c: Commission) => {
    if (
      !confirm(
        `Mark ${money(c.amount_cents)} to ${c.referrer_name} as paid?\n\nThis only records that you paid them — it does not send any money.`,
      )
    )
      return
    setSavingId(c.id)
    setError(null)
    try {
      await api.patch(`/api/admin/referral-commissions/${c.id}`, { paid: true }, adminApi)
      await load()
    } catch {
      setError('Could not mark as paid.')
    } finally {
      setSavingId(null)
    }
  }

  const copyCode = (code: string) => {
    void navigator.clipboard?.writeText(code).then(() => {
      setCopied(code)
      setTimeout(() => setCopied(null), 1500)
    })
  }

  const generateCode = () => {
    // Readable random code: drop ambiguous chars (0/O, 1/I/L) so it's easy to share by
    // voice/text. Seed with a slug of the referrer's name when present, for memorability.
    const alphabet = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
    const rand = (n: number) =>
      Array.from({ length: n }, () => alphabet[Math.floor(Math.random() * alphabet.length)]).join('')
    const slug = form.referrer_name.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 5)
    const code = slug ? `${slug}${rand(3)}` : rand(6)
    setForm({ ...form, code: code.slice(0, 40) })
  }

  const owed = (commissions || []).filter((c) => !c.paid)

  return (
    <CollapsibleSection
      title="Referrals"
      description="Hand out codes, see who signed up, and track what you owe referrers."
      className="mb-8"
    >
      {error && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}
      {success && (
        <div className="mb-4 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
          {success}
        </div>
      )}

      {/* Create a code */}
      <form onSubmit={createCode} className="mb-8 rounded-xl border border-white/10 bg-zinc-950/40 p-4">
        <h3 className="mb-1 text-sm font-semibold text-white">Create a code</h3>
        <p className="mb-3 text-xs text-zinc-500">
          The referrer shares this code; anyone who signs up with it gets their first month free, and
          you owe the referrer $200 once that business&rsquo;s first payment clears, plus 25% of their
          plan each month for up to a year.
        </p>
        <div className="grid gap-3 sm:grid-cols-3">
          <input
            value={form.referrer_name}
            onChange={(e) => setForm({ ...form, referrer_name: e.target.value })}
            placeholder="Referrer name"
            className="rounded-lg border border-white/10 bg-zinc-950/60 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:border-cyan-500 focus:outline-none"
          />
          <input
            value={form.referrer_contact}
            onChange={(e) => setForm({ ...form, referrer_contact: e.target.value })}
            placeholder="Contact (how you'll pay them)"
            className="rounded-lg border border-white/10 bg-zinc-950/60 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:border-cyan-500 focus:outline-none"
          />
          <div className="flex gap-2">
            <input
              value={form.code}
              onChange={(e) =>
                setForm({ ...form, code: e.target.value.toUpperCase().replace(/[^A-Z0-9-]/g, '').slice(0, 40) })
              }
              placeholder="Code (or generate →)"
              className="min-w-0 flex-1 rounded-lg border border-white/10 bg-zinc-950/60 px-3 py-2 text-sm font-mono text-white placeholder-zinc-600 focus:border-cyan-500 focus:outline-none"
            />
            <button
              type="button"
              onClick={generateCode}
              title="Generate a random code"
              className="shrink-0 rounded-lg border border-white/15 px-3 py-2 text-xs font-medium text-zinc-300 hover:bg-white/5"
            >
              Generate
            </button>
          </div>
        </div>
        <button
          type="submit"
          disabled={creating || !form.code.trim() || !form.referrer_name.trim()}
          className="mt-3 rounded-full bg-gradient-to-r from-cyan-600 to-indigo-600 px-5 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          {creating ? 'Creating…' : 'Create code'}
        </button>
      </form>

      {/* Payouts owed — the part you'll use most */}
      <div className="mb-8">
        <div className="mb-3 flex items-baseline justify-between">
          <h3 className="text-sm font-semibold text-white">Payouts owed</h3>
          <span className="text-lg font-bold text-emerald-300">
            You owe {money(unpaidTotal)}
          </span>
        </div>
        {loading && !commissions ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-10 w-full bg-white/10" />
            ))}
          </div>
        ) : owed.length === 0 ? (
          <p className="rounded-xl border border-white/10 bg-zinc-950/40 py-6 text-center text-sm text-zinc-500">
            All caught up — nothing owed right now.
          </p>
        ) : (
          <div className="space-y-2">
            {owed.map((c) => (
              <div
                key={c.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-zinc-950/40 px-4 py-3"
              >
                <div className="min-w-0">
                  <div className="text-sm text-zinc-100">
                    <span className="font-semibold text-white">{money(c.amount_cents)}</span>
                    {' — '}
                    {commissionLabel(c)}
                    {c.business_name ? ` — ${c.business_name}` : ''}
                  </div>
                  <div className="text-xs text-zinc-500">
                    To {c.referrer_name} · code {c.code_snapshot}
                    {whenLabel(c.created_at) ? ` · ${whenLabel(c.created_at)}` : ''}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void markPaid(c)}
                  disabled={savingId === c.id}
                  className="rounded-lg border border-emerald-500/40 px-3 py-1.5 text-sm text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-50"
                >
                  {savingId === c.id ? 'Saving…' : 'Mark paid'}
                </button>
              </div>
            ))}
            <p className="pt-1 text-xs text-zinc-600">
              &ldquo;Mark paid&rdquo; only records that you paid them — it doesn&rsquo;t send any money.
            </p>
          </div>
        )}
      </div>

      {/* Active codes */}
      <div>
        <h3 className="mb-3 text-sm font-semibold text-white">Codes</h3>
        {loading && !codes ? (
          <div className="space-y-2">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-10 w-full bg-white/10" />
            ))}
          </div>
        ) : codes && codes.length > 0 ? (
          <div className="space-y-2">
            {codes.map((c) => (
              <div
                key={c.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-zinc-950/40 px-4 py-3"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-semibold text-white">{c.code}</span>
                    <button
                      type="button"
                      onClick={() => copyCode(c.code)}
                      className="text-zinc-500 hover:text-zinc-300"
                      title="Copy code"
                    >
                      {copied === c.code ? (
                        <Check className="h-3.5 w-3.5 text-emerald-400" />
                      ) : (
                        <Copy className="h-3.5 w-3.5" />
                      )}
                    </button>
                    {!c.active && (
                      <span className="rounded-full bg-zinc-700/40 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-zinc-400">
                        Paused
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-zinc-500">
                    {c.referrer_name}
                    {c.referrer_contact ? ` · ${c.referrer_contact}` : ''} · {c.signups} signups ·{' '}
                    {c.converted} became paying
                    {c.flagged ? ` · ${c.flagged} flagged` : ''}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void toggleActive(c)}
                  disabled={savingId === c.id}
                  className="rounded-lg border border-white/15 px-3 py-1.5 text-sm text-zinc-300 hover:bg-white/5 disabled:opacity-50"
                >
                  {savingId === c.id ? 'Saving…' : c.active ? 'Pause' : 'Activate'}
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="rounded-xl border border-white/10 bg-zinc-950/40 py-6 text-center text-sm text-zinc-500">
            No codes yet — create one above.
          </p>
        )}
      </div>
    </CollapsibleSection>
  )
}
