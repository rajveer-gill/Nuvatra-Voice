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
}

export default function AdminPage() {
  const { isLoaded, isSignedIn } = useAuth()
  const api = useApiClient()
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState<string | null>(null)
  const [form, setForm] = useState({
    client_id: '',
    name: '',
    twilio_phone_number: '',
    email: '',
    plan: 'starter',
  })

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
      await api.post('/api/admin/tenants', form)
      setSuccess(`Tenant "${form.name}" created. Invite sent to ${form.email}.`)
      setForm({ client_id: '', name: '', twilio_phone_number: '', email: '', plan: 'starter' })
      fetchTenants()
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } }
      setError(err.response?.data?.detail || 'Failed to create tenant')
    } finally {
      setSubmitting(false)
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
              <p className="text-xs text-gray-500 mt-1">Buy the number in Twilio Console, then add it here. Point the webhook to your backend /api/phone/incoming</p>
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
              <p className="text-xs text-gray-500 mt-1">Clerk will send an invite. Only invited users can sign up.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Plan</label>
              <select
                value={form.plan}
                onChange={(e) => setForm({ ...form, plan: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              >
                <option value="starter">Starter</option>
                <option value="growth">Growth</option>
                <option value="pro">Pro</option>
              </select>
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
            <ul className="space-y-3">
              {tenants.map((t) => (
                <li key={t.id} className="flex justify-between items-center py-2 border-b border-gray-100 last:border-0">
                  <div>
                    <span className="font-medium">{t.name}</span>
                    <span className="text-gray-500 text-sm ml-2">({t.client_id})</span>
                  </div>
                  <span className="text-sm text-gray-600">{t.twilio_phone_number}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  )
}
