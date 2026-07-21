'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import type { AxiosInstance } from 'axios'
import { AlertTriangle, ArrowRight, CreditCard, Mail, PhoneMissed, Plus, X } from 'lucide-react'
import { AppChrome } from '@/components/layout/AppChrome'
import { useApiClient, setSelectedStoreId } from '@/lib/api'

type Store = {
  client_id: string
  tenant_id: string
  name: string
  org_id: string | null
  org_name: string | null
  role: string
  plan: string
  can_use_app: boolean
  subscription_status: string | null
  demo_mode?: boolean
  calls: number
  missed: number
  bookings: number
  upcoming: number
  unread_messages: number
}

type Totals = {
  stores: number
  calls: number
  missed: number
  bookings: number
  upcoming: number
  unread_messages: number
}

type OrgInfo = {
  org_id: string
  name: string
  role: string
  subscription_status?: string | null
  billing_active?: boolean
  store_count?: number
}

const RANGES = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
] as const

const detailOf = (e: unknown): string | null => {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof d === 'string' ? d : null
}

/** Share of calls nobody answered — the number a multi-store owner actually cares about. */
function missedRate(calls: number, missed: number): number | null {
  if (!calls) return null
  return Math.round((missed / calls) * 100)
}

export default function StoresPage() {
  const api = useApiClient()
  const router = useRouter()
  const [stores, setStores] = useState<Store[] | null>(null)
  const [totals, setTotals] = useState<Totals | null>(null)
  const [orgs, setOrgs] = useState<OrgInfo[]>([])
  const [days, setDays] = useState<number>(7)
  const [error, setError] = useState<string | null>(null)
  const [addOpen, setAddOpen] = useState(false)
  const [inviteFor, setInviteFor] = useState<Store | null>(null)

  // Orgs this account manages (not just views) — only a manager can add stores or
  // set up billing. A viewer sees the rollup and nothing else.
  const managedOrgs = useMemo(() => orgs.filter((o) => o.role === 'manager'), [orgs])
  // A group that has stores but isn't paying yet: its stores can't take calls until
  // the manager sets up billing. Surface it, because it blocks everything else.
  const unbilledOrg = useMemo(
    () => managedOrgs.find((o) => (o.store_count ?? 0) > 0 && !o.billing_active),
    [managedOrgs]
  )

  const loadStores = useCallback(() => {
    setStores(null)
    return api
      .get<{ stores: Store[]; totals: Totals }>(`/api/org/stores?days=${days}`)
      .then((r) => {
        setStores(r.data.stores || [])
        setTotals(r.data.totals || null)
        setError(null)
      })
      .catch(() => {
        setStores([])
        setError('Could not load your stores. Please refresh.')
      })
  }, [api, days])

  const loadOrgs = useCallback(() => {
    return api
      .get<{ orgs: OrgInfo[] }>('/api/org/me')
      .then((r) => setOrgs(r.data.orgs || []))
      .catch(() => setOrgs([]))
  }, [api])

  useEffect(() => {
    let cancelled = false
    void loadStores()
    if (!cancelled) void loadOrgs()
    return () => {
      cancelled = true
    }
  }, [loadStores, loadOrgs])

  // Drilling in reuses every existing dashboard screen — the store is carried on the
  // X-Store-Id header from here on, and re-validated on each request server-side.
  const openStore = useCallback(
    (store: Store) => {
      setSelectedStoreId(store.client_id)
      router.push('/dashboard')
    },
    [router]
  )

  // Worst offenders first: a manager opens this to find the shop that needs them.
  const sorted = useMemo(() => {
    if (!stores) return null
    return [...stores].sort((a, b) => {
      const ra = missedRate(a.calls, a.missed) ?? -1
      const rb = missedRate(b.calls, b.missed) ?? -1
      if (rb !== ra) return rb - ra
      return a.name.localeCompare(b.name)
    })
  }, [stores])

  const afterAdd = useCallback(() => {
    setAddOpen(false)
    void loadStores()
    void loadOrgs()
  }, [loadStores, loadOrgs])

  return (
    <AppChrome>
      <main className="min-h-screen px-4 py-10 md:px-6">
        <div className="mx-auto max-w-6xl">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <h1 className="font-display text-2xl font-semibold text-white sm:text-3xl">
                Your stores
              </h1>
              <p className="mt-1 text-sm text-zinc-400">
                {totals
                  ? `${totals.stores} ${totals.stores === 1 ? 'store' : 'stores'} · last ${days} days`
                  : 'Loading…'}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex gap-1 rounded-full border border-white/10 bg-zinc-950/40 p-1">
                {RANGES.map((r) => (
                  <button
                    key={r.days}
                    type="button"
                    onClick={() => setDays(r.days)}
                    className={`rounded-full px-3 py-1.5 text-xs font-medium motion-safe-transition ${
                      days === r.days
                        ? 'bg-cyan-500/15 text-cyan-200'
                        : 'text-zinc-400 hover:text-white'
                    }`}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
              {managedOrgs.length > 0 && (
                <button
                  type="button"
                  onClick={() => setAddOpen(true)}
                  className="inline-flex items-center gap-1.5 rounded-full bg-gradient-to-r from-cyan-600 to-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-cyan-500/20 motion-safe-transition hover:brightness-110"
                >
                  <Plus className="h-4 w-4" aria-hidden />
                  Add store
                </button>
              )}
            </div>
          </div>

          {error && (
            <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
              {error}
            </div>
          )}

          {unbilledOrg && (
            <div className="mt-6 rounded-2xl border border-amber-400/40 bg-gradient-to-br from-amber-500/15 to-orange-600/10 p-5">
              <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div className="flex gap-3">
                  <CreditCard className="mt-0.5 h-6 w-6 shrink-0 text-amber-300" aria-hidden />
                  <div>
                    <h2 className="font-display text-lg font-semibold text-amber-50">
                      Set up billing for {unbilledOrg.name}
                    </h2>
                    <p className="mt-1 max-w-2xl text-sm text-amber-100/80">
                      Your stores can&rsquo;t take calls until the group has an active plan. One
                      subscription covers all {unbilledOrg.store_count} of them — you&rsquo;re billed
                      per store, and adding or removing a store adjusts it automatically.
                    </p>
                  </div>
                </div>
                <OrgBillingButton api={api} orgId={unbilledOrg.org_id} />
              </div>
            </div>
          )}

          {totals && totals.stores > 0 && (
            <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                { label: 'Calls', value: totals.calls },
                { label: 'Missed', value: totals.missed },
                { label: 'Booked', value: totals.bookings },
                { label: 'Upcoming', value: totals.upcoming },
              ].map((s) => (
                <div
                  key={s.label}
                  className="rounded-2xl border border-white/10 bg-zinc-900/60 px-4 py-3"
                >
                  <div className="text-xs text-zinc-500">{s.label}</div>
                  <div className="mt-0.5 text-2xl font-semibold text-white">{s.value}</div>
                </div>
              ))}
            </div>
          )}

          {sorted === null && (
            <div className="mt-10 flex justify-center">
              <div className="h-10 w-10 animate-spin rounded-full border-2 border-cyan-400/30 border-t-cyan-400" />
            </div>
          )}

          {sorted?.length === 0 && !error && (
            <div className="mt-10 rounded-2xl border border-white/10 bg-zinc-900/60 p-8 text-center">
              <h2 className="font-display text-lg font-semibold text-white">
                {managedOrgs.length > 0 ? 'No stores yet' : 'No stores assigned'}
              </h2>
              <p className="mx-auto mt-2 max-w-md text-sm text-zinc-400">
                {managedOrgs.length > 0
                  ? 'Add your first store to get started. Each one gets its own AI receptionist under your group.'
                  : 'Your account doesn’t oversee any stores yet. Ask your Nuvatra contact to add them to your group.'}
              </p>
              {managedOrgs.length > 0 && (
                <button
                  type="button"
                  onClick={() => setAddOpen(true)}
                  className="mt-5 inline-flex items-center gap-1.5 rounded-full bg-gradient-to-r from-cyan-600 to-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-cyan-500/20 motion-safe-transition hover:brightness-110"
                >
                  <Plus className="h-4 w-4" aria-hidden />
                  Add store
                </button>
              )}
            </div>
          )}

          {sorted && sorted.length > 0 && (
            <div className="mt-4 overflow-x-auto">
              <div className="min-w-[760px] space-y-2">
                <div className="grid grid-cols-12 gap-3 px-4 pb-1 text-xs font-medium text-zinc-500">
                  <div className="col-span-4">Store</div>
                  <div className="col-span-2 text-right">Calls</div>
                  <div className="col-span-2 text-right">Missed</div>
                  <div className="col-span-1 text-right">Booked</div>
                  <div className="col-span-2 text-right">Upcoming</div>
                  <div className="col-span-1" />
                </div>
                {sorted.map((s) => {
                  const rate = missedRate(s.calls, s.missed)
                  const concerning = rate !== null && rate >= 20
                  const canManage = s.role === 'manager'
                  return (
                    <div
                      key={s.client_id}
                      className="grid grid-cols-12 items-center gap-3 rounded-2xl border border-white/10 bg-zinc-900/60 px-4 py-3 motion-safe-transition hover:border-white/25"
                    >
                      <button
                        type="button"
                        onClick={() => openStore(s)}
                        className="col-span-4 min-w-0 text-left"
                      >
                        <div className="flex items-center gap-2">
                          <span className="truncate font-medium text-white">{s.name}</span>
                          {!s.can_use_app && (
                            <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-200">
                              <AlertTriangle className="h-3 w-3" aria-hidden />
                              Inactive
                            </span>
                          )}
                          {s.demo_mode && (
                            <span className="shrink-0 rounded-full border border-cyan-400/40 bg-cyan-500/10 px-2 py-0.5 text-[10px] font-semibold text-cyan-200">
                              Demo
                            </span>
                          )}
                        </div>
                        <div className="truncate text-xs text-zinc-500">
                          {s.org_name ? `${s.org_name} · ` : ''}
                          {s.unread_messages > 0
                            ? `${s.unread_messages} unread message${s.unread_messages === 1 ? '' : 's'}`
                            : s.plan}
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() => openStore(s)}
                        className="col-span-2 text-right text-sm text-zinc-200"
                      >
                        {s.calls}
                      </button>
                      <button
                        type="button"
                        onClick={() => openStore(s)}
                        className="col-span-2 text-right"
                      >
                        <span
                          className={`inline-flex items-center gap-1.5 text-sm ${
                            concerning ? 'font-semibold text-amber-300' : 'text-zinc-200'
                          }`}
                        >
                          {concerning && <PhoneMissed className="h-3.5 w-3.5" aria-hidden />}
                          {s.missed}
                          {rate !== null && (
                            <span className="text-xs text-zinc-500">({rate}%)</span>
                          )}
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => openStore(s)}
                        className="col-span-1 text-right text-sm text-zinc-200"
                      >
                        {s.bookings}
                      </button>
                      <button
                        type="button"
                        onClick={() => openStore(s)}
                        className="col-span-2 text-right text-sm text-zinc-200"
                      >
                        {s.upcoming}
                      </button>
                      <div className="col-span-1 flex items-center justify-end gap-1">
                        {canManage && (
                          <button
                            type="button"
                            onClick={() => setInviteFor(s)}
                            title="Invite this store's manager"
                            aria-label={`Invite manager for ${s.name}`}
                            className="rounded-full p-1.5 text-zinc-500 motion-safe-transition hover:bg-white/5 hover:text-cyan-300"
                          >
                            <Mail className="h-4 w-4" aria-hidden />
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => openStore(s)}
                          aria-label={`Open ${s.name}`}
                          className="rounded-full p-1.5 text-zinc-600 motion-safe-transition hover:text-white"
                        >
                          <ArrowRight className="h-4 w-4" aria-hidden />
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        {addOpen && (
          <AddStoreModal
            api={api}
            orgs={managedOrgs}
            onClose={() => setAddOpen(false)}
            onCreated={afterAdd}
          />
        )}
        {inviteFor && (
          <InviteManagerModal
            api={api}
            store={inviteFor}
            onClose={() => setInviteFor(null)}
          />
        )}
      </main>
    </AppChrome>
  )
}

/** Kicks off (or resumes) the group's single subscription. */
function OrgBillingButton({ api, orgId }: { api: AxiosInstance; orgId: string }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const start = async () => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await api.post<{ url: string }>('/api/org/create-checkout-session', {
        plan: 'pro',
        org_id: orgId,
      })
      if (data?.url) {
        window.location.href = data.url
        return
      }
      throw new Error('no url')
    } catch (e) {
      setError(detailOf(e) || 'Could not start checkout.')
      setLoading(false)
    }
  }
  return (
    <div className="shrink-0 text-right">
      <button
        type="button"
        onClick={start}
        disabled={loading}
        className="inline-flex items-center gap-1.5 rounded-full bg-amber-400 px-5 py-2.5 text-sm font-semibold text-amber-950 motion-safe-transition hover:brightness-105 disabled:opacity-60"
      >
        {loading ? 'Starting…' : 'Set up billing'}
      </button>
      {error && <p className="mt-1 text-xs text-red-300">{error}</p>}
    </div>
  )
}

function ModalShell({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-zinc-900 p-6 shadow-2xl">
        <div className="mb-4 flex items-start justify-between">
          <h2 className="font-display text-lg font-semibold text-white">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-full p-1 text-zinc-500 hover:text-white"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

function AddStoreModal({
  api,
  orgs,
  onClose,
  onCreated,
}: {
  api: AxiosInstance
  orgs: OrgInfo[]
  onClose: () => void
  onCreated: () => void
}) {
  const [name, setName] = useState('')
  const [orgId, setOrgId] = useState(orgs[0]?.org_id ?? '')
  const [numberMode, setNumberMode] = useState<'new' | 'existing'>('new')
  const [existingNumber, setExistingNumber] = useState('')
  const [managerEmail, setManagerEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const existingDigits = existingNumber.replace(/\D/g, '').replace(/^1/, '')
  const existingValid = numberMode === 'new' || existingDigits.length === 10
  const canSubmit = name.trim().length > 0 && existingValid && Boolean(orgId)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    try {
      await api.post('/api/org/stores', {
        name: name.trim(),
        org_id: orgId,
        number_mode: numberMode,
        existing_number: numberMode === 'existing' ? existingNumber.trim() : undefined,
        manager_email: managerEmail.trim() || undefined,
      })
      onCreated()
    } catch (err) {
      setError(detailOf(err) || 'Could not add the store. Please try again.')
      setSubmitting(false)
    }
  }

  return (
    <ModalShell title="Add a store" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        {orgs.length > 1 && (
          <div>
            <label className="mb-1 block text-sm font-medium text-zinc-300">Group</label>
            <select
              value={orgId}
              onChange={(e) => setOrgId(e.target.value)}
              className="w-full rounded-lg border border-white/10 bg-zinc-950/60 px-3 py-2 text-sm text-white focus:border-cyan-500 focus:outline-none"
            >
              {orgs.map((o) => (
                <option key={o.org_id} value={o.org_id}>
                  {o.name}
                </option>
              ))}
            </select>
          </div>
        )}

        <div>
          <label className="mb-1 block text-sm font-medium text-zinc-300">Store name</label>
          <input
            type="text"
            required
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Supercuts Downtown"
            className="w-full rounded-lg border border-white/10 bg-zinc-950/60 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:border-cyan-500 focus:outline-none"
          />
          <p className="mt-1 text-xs text-zinc-500">Callers hear this in the greeting.</p>
        </div>

        <div>
          <label className="mb-2 block text-sm font-medium text-zinc-300">Phone number</label>
          <div className="grid grid-cols-2 gap-2">
            {([
              { id: 'new' as const, title: 'New number' },
              { id: 'existing' as const, title: 'Use existing' },
            ]).map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => setNumberMode(opt.id)}
                className={`rounded-xl border px-3 py-2 text-sm font-medium motion-safe-transition ${
                  numberMode === opt.id
                    ? 'border-cyan-500 bg-cyan-500/10 text-cyan-100'
                    : 'border-white/10 bg-zinc-950/40 text-zinc-300 hover:border-white/25'
                }`}
              >
                {opt.title}
              </button>
            ))}
          </div>
          {numberMode === 'existing' && (
            <div className="mt-2">
              <input
                type="tel"
                inputMode="tel"
                value={existingNumber}
                onChange={(e) => setExistingNumber(e.target.value.replace(/[^\d\s()+-]/g, '').slice(0, 20))}
                placeholder="(415) 555-0199"
                className="w-full rounded-lg border border-white/10 bg-zinc-950/60 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:border-cyan-500 focus:outline-none"
              />
              {existingNumber.trim() && !existingValid && (
                <p className="mt-1 text-xs text-amber-400">Enter a 10-digit US phone number.</p>
              )}
              <p className="mt-1 text-xs text-zinc-500">
                This store keeps its number and forwards calls to its AI line.
              </p>
            </div>
          )}
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-zinc-300">
            Store manager&rsquo;s email <span className="text-zinc-500">(optional)</span>
          </label>
          <input
            type="email"
            value={managerEmail}
            onChange={(e) => setManagerEmail(e.target.value)}
            placeholder="manager@store.com"
            className="w-full rounded-lg border border-white/10 bg-zinc-950/60 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:border-cyan-500 focus:outline-none"
          />
          <p className="mt-1 text-xs text-zinc-500">
            We&rsquo;ll email them an invite to run this store. You can also do this later.
          </p>
        </div>

        {error && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting || !canSubmit}
          className="w-full rounded-full bg-gradient-to-r from-cyan-600 to-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-cyan-500/20 motion-safe-transition hover:brightness-110 disabled:opacity-50"
        >
          {submitting ? 'Adding store…' : 'Add store'}
        </button>
      </form>
    </ModalShell>
  )
}

function InviteManagerModal({
  api,
  store,
  onClose,
}: {
  api: AxiosInstance
  store: Store
  onClose: () => void
}) {
  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await api.post(`/api/org/stores/${encodeURIComponent(store.client_id)}/invite`, {
        email: email.trim(),
      })
      setSent(true)
    } catch (err) {
      setError(detailOf(err) || 'Could not send the invite. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ModalShell title={`Invite manager · ${store.name}`} onClose={onClose}>
      {sent ? (
        <div className="space-y-4">
          <p className="text-sm text-zinc-300">
            Invite sent to <span className="font-medium text-white">{email}</span>. When they sign up
            with that address they&rsquo;ll land in this store.
          </p>
          <button
            type="button"
            onClick={onClose}
            className="w-full rounded-full bg-gradient-to-r from-cyan-600 to-indigo-600 px-5 py-2.5 text-sm font-semibold text-white motion-safe-transition hover:brightness-110"
          >
            Done
          </button>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <p className="text-sm text-zinc-400">
            They&rsquo;ll get an email invite and see only this store — never the group rollup or
            your other stores.
          </p>
          <div>
            <label className="mb-1 block text-sm font-medium text-zinc-300">Email</label>
            <input
              type="email"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="manager@store.com"
              className="w-full rounded-lg border border-white/10 bg-zinc-950/60 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:border-cyan-500 focus:outline-none"
            />
          </div>
          {error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
              {error}
            </div>
          )}
          <button
            type="submit"
            disabled={submitting || !email.trim()}
            className="w-full rounded-full bg-gradient-to-r from-cyan-600 to-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-cyan-500/20 motion-safe-transition hover:brightness-110 disabled:opacity-50"
          >
            {submitting ? 'Sending…' : 'Send invite'}
          </button>
        </form>
      )}
    </ModalShell>
  )
}
