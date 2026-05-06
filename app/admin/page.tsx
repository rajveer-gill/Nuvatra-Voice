'use client'

import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '@clerk/nextjs'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { motion, useReducedMotion } from 'framer-motion'
import { useApiClient, sameOriginApiConfig } from '@/lib/api'
import { AppChrome } from '@/components/layout/AppChrome'

interface Tenant {
  id: string
  client_id: string
  name: string
  twilio_phone_number: string
  plan: string
  created_at: string | null
  trial_ends_at?: string | null
  subscription_status?: string | null
  billing_exempt_until?: string | null
}

const inputClass =
  'w-full rounded-lg border border-white/15 bg-zinc-950 px-3 py-2 text-zinc-100 placeholder:text-zinc-600 focus:border-cyan-500/50 focus:outline-none focus:ring-2 focus:ring-cyan-500/25'
const selectClass =
  'rounded-lg border border-white/15 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100 focus:border-cyan-500/50 focus:outline-none focus:ring-2 focus:ring-cyan-500/25'

export default function AdminPage() {
  const router = useRouter()
  const { isLoaded, isSignedIn } = useAuth()
  const api = useApiClient()
  const reduceMotion = useReducedMotion()
  const [adminAllowed, setAdminAllowed] = useState<boolean | null>(null)
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [form, setForm] = useState({
    client_id: '',
    name: '',
    twilio_phone_number: '',
    email: '',
  })
  const [exempting, setExempting] = useState<string | null>(null)
  const [exemptAction, setExemptAction] = useState<Record<string, string>>({})
  const [exemptUntilDate, setExemptUntilDate] = useState<Record<string, string>>({})
  const [sessionError, setSessionError] = useState<string | null>(null)

  const listContainer = {
    hidden: {},
    visible: {
      transition: { staggerChildren: reduceMotion ? 0 : 0.06, delayChildren: reduceMotion ? 0 : 0.02 },
    },
  }

  const listItem = {
    hidden: { opacity: 0, y: 12 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: reduceMotion ? 0 : 0.35, ease: [0.22, 1, 0.36, 1] },
    },
  }

  const fetchTenants = useCallback(async () => {
    try {
      const res = await api.get('/api/admin/tenants')
      setTenants(res.data.tenants || [])
      setError(null)
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } }
      if (err.response?.status === 403) {
        setError('Admin access required. Add your Clerk user ID to ADMIN_CLERK_USER_IDS on the backend.')
      } else if (err.response?.status === 401) {
        setError('Please sign in.')
      } else {
        setError(err.response?.data?.detail || 'Failed to load tenants')
      }
    } finally {
      setLoading(false)
    }
  }, [api])

  const verifyAdminSession = useCallback(async () => {
    setSessionError(null)
    setAdminAllowed(null)
    try {
      const res = await api.get<{ is_admin: boolean }>('/api/admin/session', sameOriginApiConfig())
      if (res.data.is_admin) {
        setAdminAllowed(true)
      } else {
        setAdminAllowed(false)
        router.replace('/dashboard')
      }
    } catch {
      setSessionError('Could not verify admin access. Check your connection and try again.')
      setAdminAllowed(false)
    }
  }, [api, router])

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return
    void verifyAdminSession()
  }, [isLoaded, isSignedIn, verifyAdminSession])

  useEffect(() => {
    if (adminAllowed !== true) return
    fetchTenants()
  }, [adminAllowed, fetchTenants])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setSuccess(null)
    setError(null)
    try {
      await api.post('/api/admin/tenants', { ...form, plan: 'free' })
      setSuccess(`Tenant "${form.name}" created. Invite sent to ${form.email}.`)
      setForm({ client_id: '', name: '', twilio_phone_number: '', email: '' })
      fetchTenants()
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } }
      setError(err.response?.data?.detail || 'Failed to create tenant')
    } finally {
      setSubmitting(false)
    }
  }

  const handleBillingExempt = async (tenantId: string) => {
    const action = exemptAction[tenantId]
    if (!action) return
    setExempting(tenantId)
    setError(null)
    setSuccess(null)
    try {
      if (action === 'extend_trial_1') {
        await api.patch(`/api/admin/tenants/${tenantId}/billing-exempt`, { extend_trial_months: 1 })
        setSuccess('Trial extended by 1 month.')
      } else if (action === 'free_1') {
        await api.patch(`/api/admin/tenants/${tenantId}/billing-exempt`, { extend_months: 1 })
        setSuccess('1 month billing exemption set.')
      } else if (action === 'free_3') {
        await api.patch(`/api/admin/tenants/${tenantId}/billing-exempt`, { extend_months: 3 })
        setSuccess('3 months billing exemption set.')
      } else if (action === 'exempt_until') {
        const date = exemptUntilDate[tenantId]
        if (!date) {
          setError('Pick a date for exempt until.')
          setExempting(null)
          return
        }
        await api.patch(`/api/admin/tenants/${tenantId}/billing-exempt`, { exempt_until: date })
        setSuccess(`Exempt until ${date} set.`)
        setExemptUntilDate((d) => ({ ...d, [tenantId]: '' }))
      }
      setExemptAction((a) => ({ ...a, [tenantId]: '' }))
      fetchTenants()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail || 'Failed to update billing')
    } finally {
      setExempting(null)
    }
  }

  const handleDelete = async (tenant: Tenant) => {
    if (!confirm(`Remove "${tenant.name}" (${tenant.client_id})? This cannot be undone.`)) return
    setDeleting(tenant.id)
    setError(null)
    setSuccess(null)
    try {
      await api.delete(`/api/admin/tenants/${tenant.id}`)
      setSuccess(`Tenant "${tenant.name}" removed.`)
      fetchTenants()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail || 'Failed to remove tenant')
    } finally {
      setDeleting(null)
    }
  }

  if (!isLoaded) {
    return (
      <AppChrome>
        <div className="flex min-h-screen items-center justify-center">
          <div className="h-10 w-10 animate-spin rounded-full border-2 border-cyan-400/30 border-t-cyan-400" />
        </div>
      </AppChrome>
    )
  }

  if (!isSignedIn) {
    return (
      <AppChrome>
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
          <p className="max-w-md text-center text-zinc-400">You must be signed in to access the admin panel.</p>
          <Link href="/" className="text-cyan-400 motion-safe-transition hover:text-cyan-300">
            Back to home
          </Link>
        </div>
      </AppChrome>
    )
  }

  if (sessionError) {
    return (
      <AppChrome>
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
          <p className="max-w-md text-center text-zinc-300">{sessionError}</p>
          <button
            type="button"
            className="rounded-full bg-gradient-to-r from-cyan-600 to-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-cyan-500/20 motion-safe-transition hover:brightness-110"
            onClick={() => void verifyAdminSession()}
          >
            Retry
          </button>
          <Link href="/" className="text-sm text-cyan-400 hover:text-cyan-300">
            Back to home
          </Link>
        </div>
      </AppChrome>
    )
  }

  if (adminAllowed !== true) {
    return (
      <AppChrome>
        <div className="flex min-h-screen items-center justify-center">
          <div className="h-10 w-10 animate-spin rounded-full border-2 border-cyan-400/30 border-t-cyan-400" />
        </div>
      </AppChrome>
    )
  }

  return (
    <AppChrome>
      <main className="min-h-screen px-4 py-10 md:px-6">
        <div className="mx-auto max-w-4xl">
          <div className="mb-8 flex items-center justify-between gap-4">
            <h1 className="font-display text-2xl font-semibold tracking-tight text-white md:text-3xl">Admin – Add Client</h1>
            <Link href="/" className="text-sm text-zinc-400 motion-safe-transition hover:text-white">
              ← Home
            </Link>
          </div>

          {error && (
            <div className="mb-6 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{error}</div>
          )}
          {success && (
            <div className="mb-6 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">{success}</div>
          )}

          <motion.form
            onSubmit={handleSubmit}
            className="mb-8 rounded-2xl border border-white/10 bg-zinc-900/70 p-6 shadow-xl backdrop-blur-md md:p-8"
            initial={reduceMotion ? false : { opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: reduceMotion ? 0 : 0.35 }}
          >
            <h2 className="mb-4 font-display text-lg font-semibold text-white">Add new client</h2>
            <div className="grid gap-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-zinc-400">Client ID (slug)</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. acme-salon"
                  value={form.client_id}
                  onChange={(e) => setForm({ ...form, client_id: e.target.value.replace(/\s/g, '-').toLowerCase() })}
                  className={inputClass}
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-zinc-400">Business name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Acme Salon"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className={inputClass}
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-zinc-400">Twilio phone number (E.164)</label>
                <input
                  type="tel"
                  required
                  placeholder="e.g. +15551234567"
                  value={form.twilio_phone_number}
                  onChange={(e) => setForm({ ...form, twilio_phone_number: e.target.value })}
                  className={inputClass}
                />
                <p className="mt-1 text-xs text-zinc-500">
                  Buy the number in Twilio Console, then add it here. In Twilio, set Voice webhook to your-backend/api/phone/incoming and Messaging webhook to your-backend/api/sms/incoming.
                </p>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-zinc-400">Client email (for invite)</label>
                <input
                  type="email"
                  required
                  placeholder="client@example.com"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  className={inputClass}
                />
                <p className="mt-1 text-xs text-zinc-500">Clerk will send an invite. New tenants get a 7-day free trial.</p>
              </div>
              <button
                type="submit"
                disabled={submitting}
                className="rounded-full bg-gradient-to-r from-cyan-600 to-indigo-600 px-6 py-2.5 font-semibold text-white shadow-lg shadow-cyan-500/15 motion-safe-transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting ? 'Creating…' : 'Create tenant and send invite'}
              </button>
            </div>
          </motion.form>

          <section className="rounded-2xl border border-white/10 bg-zinc-900/70 p-6 shadow-xl backdrop-blur-md md:p-8">
            <h2 className="mb-4 font-display text-lg font-semibold text-white">Existing tenants</h2>
            {loading ? (
              <div className="flex justify-center py-12">
                <div className="h-8 w-8 animate-spin rounded-full border-2 border-cyan-400/30 border-t-cyan-400" />
              </div>
            ) : tenants.length === 0 ? (
              <p className="text-zinc-500">No tenants yet.</p>
            ) : (
              <motion.ul
                className="divide-y divide-white/10"
                variants={listContainer}
                initial={reduceMotion ? false : 'hidden'}
                animate="visible"
              >
                {tenants.map((t) => (
                  <motion.li key={t.id} variants={listItem} className="py-6 first:pt-0 last:pb-0">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div>
                        <span className="font-medium text-zinc-100">{t.name}</span>
                        <span className="ml-2 text-sm text-zinc-500">({t.client_id})</span>
                        <div className="mt-1 flex flex-wrap items-center gap-3">
                          <span className="text-sm text-zinc-400">{t.twilio_phone_number}</span>
                          <span className="rounded-full bg-cyan-500/15 px-2 py-0.5 text-xs font-medium text-cyan-300">{t.plan}</span>
                          {t.subscription_status && (
                            <span className="text-xs text-zinc-500">status: {t.subscription_status}</span>
                          )}
                        </div>
                        {(t.trial_ends_at || t.billing_exempt_until) && (
                          <div className="mt-1 text-xs text-zinc-500">
                            {t.trial_ends_at && <>Trial ends: {new Date(t.trial_ends_at).toLocaleDateString()}</>}
                            {t.trial_ends_at && t.billing_exempt_until && ' · '}
                            {t.billing_exempt_until && <>Exempt until: {new Date(t.billing_exempt_until).toLocaleDateString()}</>}
                          </div>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <select
                            value={exemptAction[t.id] || ''}
                            onChange={(e) => setExemptAction((a) => ({ ...a, [t.id]: e.target.value }))}
                            className={selectClass}
                          >
                            <option value="">Exempt from payment…</option>
                            <option value="extend_trial_1">Extend trial 1 month</option>
                            <option value="free_1">Give 1 month free</option>
                            <option value="free_3">Give 3 months free</option>
                            <option value="exempt_until">Exempt until date</option>
                          </select>
                          {exemptAction[t.id] === 'exempt_until' && (
                            <input
                              type="date"
                              value={exemptUntilDate[t.id] || ''}
                              onChange={(e) => setExemptUntilDate((d) => ({ ...d, [t.id]: e.target.value }))}
                              className={selectClass}
                            />
                          )}
                          <button
                            type="button"
                            onClick={() => handleBillingExempt(t.id)}
                            disabled={
                              exempting === t.id ||
                              !exemptAction[t.id] ||
                              (exemptAction[t.id] === 'exempt_until' && !exemptUntilDate[t.id])
                            }
                            className="rounded-lg bg-white/10 px-2 py-1 text-sm text-zinc-200 motion-safe-transition hover:bg-white/15 disabled:opacity-50"
                          >
                            {exempting === t.id ? 'Applying…' : 'Apply'}
                          </button>
                        </div>
                        <button
                          type="button"
                          onClick={() => handleDelete(t)}
                          disabled={deleting === t.id}
                          className="rounded-lg border border-red-500/40 px-3 py-1.5 text-sm text-red-300 motion-safe-transition hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {deleting === t.id ? 'Removing…' : 'Remove'}
                        </button>
                      </div>
                    </div>
                  </motion.li>
                ))}
              </motion.ul>
            )}
          </section>
        </div>
      </main>
    </AppChrome>
  )
}
