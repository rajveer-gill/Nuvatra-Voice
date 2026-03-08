'use client'

import { useState, useEffect } from 'react'
import { useAuth } from '@clerk/nextjs'
import Link from 'next/link'
import { useApiClient } from '@/lib/api'

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

export default function AdminPage() {
  const { isLoaded, isSignedIn } = useAuth()
  const api = useApiClient()
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

  const fetchTenants = async () => {
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
  }

  useEffect(() => {
    if (isLoaded) {
      fetchTenants()
    }
  }, [isLoaded, api])

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
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600" />
      </div>
    )
  }

  if (!isSignedIn) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-8">
        <p className="text-gray-600 mb-4">You must be signed in to access the admin panel.</p>
        <Link href="/dashboard" className="text-blue-600 hover:underline">Go to Dashboard</Link>
      </div>
    )
  }

  return (
    <main className="min-h-screen bg-gray-50 py-12 px-4">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Admin – Add Client</h1>
          <Link href="/dashboard" className="text-gray-600 hover:text-gray-900 text-sm">← Dashboard</Link>
        </div>

        {error && (
          <div className="mb-6 p-4 rounded-lg bg-red-50 text-red-700 border border-red-200">
            {error}
          </div>
        )}
        {success && (
          <div className="mb-6 p-4 rounded-lg bg-green-50 text-green-700 border border-green-200">
            {success}
          </div>
        )}

        <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow-md p-6 mb-8">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Add new client</h2>
          <div className="grid gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Client ID (slug)</label>
              <input
                type="text"
                required
                placeholder="e.g. acme-salon"
                value={form.client_id}
                onChange={(e) => setForm({ ...form, client_id: e.target.value.replace(/\s/g, '-').toLowerCase() })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Business name</label>
              <input
                type="text"
                required
                placeholder="e.g. Acme Salon"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Twilio phone number (E.164)</label>
              <input
                type="tel"
                required
                placeholder="e.g. +15551234567"
                value={form.twilio_phone_number}
                onChange={(e) => setForm({ ...form, twilio_phone_number: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
              <p className="text-xs text-gray-500 mt-1">Buy the number in Twilio Console, then add it here. In Twilio, set Voice webhook to your-backend/api/phone/incoming and Messaging webhook to your-backend/api/sms/incoming.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Client email (for invite)</label>
              <input
                type="email"
                required
                placeholder="client@example.com"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
              <p className="text-xs text-gray-500 mt-1">Clerk will send an invite. New tenants get a 7-day free trial.</p>
            </div>
            <button
              type="submit"
              disabled={submitting}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting ? 'Creating…' : 'Create tenant and send invite'}
            </button>
          </div>
        </form>

        <section className="bg-white rounded-xl shadow-md p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Existing tenants</h2>
          {loading ? (
            <div className="flex justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
            </div>
          ) : tenants.length === 0 ? (
            <p className="text-gray-500">No tenants yet.</p>
          ) : (
            <ul className="space-y-4">
              {tenants.map((t) => (
                <li key={t.id} className="py-4 border-b border-gray-100 last:border-0">
                  <div className="flex justify-between items-start gap-4 flex-wrap">
                    <div>
                      <span className="font-medium">{t.name}</span>
                      <span className="text-gray-500 text-sm ml-2">({t.client_id})</span>
                      <div className="flex items-center gap-3 mt-1 flex-wrap">
                        <span className="text-sm text-gray-600">{t.twilio_phone_number}</span>
                        <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium">{t.plan}</span>
                        {t.subscription_status && (
                          <span className="text-xs text-gray-500">status: {t.subscription_status}</span>
                        )}
                      </div>
                      {(t.trial_ends_at || t.billing_exempt_until) && (
                        <div className="text-xs text-gray-500 mt-1">
                          {t.trial_ends_at && <>Trial ends: {new Date(t.trial_ends_at).toLocaleDateString()}</>}
                          {t.trial_ends_at && t.billing_exempt_until && ' · '}
                          {t.billing_exempt_until && <>Exempt until: {new Date(t.billing_exempt_until).toLocaleDateString()}</>}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <div className="flex flex-wrap items-center gap-2">
                        <select
                          value={exemptAction[t.id] || ''}
                          onChange={(e) => setExemptAction((a) => ({ ...a, [t.id]: e.target.value }))}
                          className="text-sm border border-gray-300 rounded px-2 py-1"
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
                            className="text-sm border border-gray-300 rounded px-2 py-1"
                          />
                        )}
                        <button
                          type="button"
                          onClick={() => handleBillingExempt(t.id)}
                          disabled={exempting === t.id || !exemptAction[t.id] || (exemptAction[t.id] === 'exempt_until' && !exemptUntilDate[t.id])}
                          className="text-sm px-2 py-1 bg-gray-100 text-gray-700 rounded hover:bg-gray-200 disabled:opacity-50"
                        >
                          {exempting === t.id ? 'Applying…' : 'Apply'}
                        </button>
                      </div>
                      <button
                        onClick={() => handleDelete(t)}
                        disabled={deleting === t.id}
                        className="px-3 py-1.5 text-sm text-red-600 border border-red-200 rounded-lg hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {deleting === t.id ? 'Removing…' : 'Remove'}
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  )
}
