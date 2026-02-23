'use client'

import { useState, useEffect } from 'react'
import { Calendar, Plus, RefreshCw, Clock, Mail, Phone, Check, X, Copy } from 'lucide-react'
import axios from 'axios'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface Appointment {
  id: number
  name: string
  email: string
  phone: string
  date: string
  time: string
  reason: string
  status: string
  created_at: string
  source?: string
}

const STATUS_OPTIONS = ['pending', 'pending_review', 'confirmed', 'accepted', 'completed', 'cancelled', 'rejected']
const STATUS_LABELS: Record<string, string> = {
  pending: 'Pending',
  pending_review: 'To review',
  confirmed: 'Confirmed',
  accepted: 'Accepted',
  completed: 'Completed',
  cancelled: 'Cancelled',
  rejected: 'Rejected',
}
const STATUS_CLASSES: Record<string, string> = {
  pending: 'bg-amber-100 text-amber-800',
  pending_review: 'bg-amber-100 text-amber-800',
  confirmed: 'bg-blue-100 text-blue-800',
  accepted: 'bg-green-100 text-green-800',
  completed: 'bg-green-100 text-green-800',
  cancelled: 'bg-gray-100 text-gray-600',
  rejected: 'bg-red-100 text-red-800',
}

function copyBlock(apt: Appointment): string {
  return [
    `Name: ${apt.name}`,
    `Phone: ${apt.phone || '—'}`,
    `Email: ${apt.email || '—'}`,
    `Date: ${apt.date}`,
    `Time: ${apt.time || '—'}`,
    `Service/Reason: ${apt.reason || '—'}`,
  ].join('\n')
}

export default function Appointments() {
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [updatingId, setUpdatingId] = useState<number | null>(null)
  const [acceptRejectMsg, setAcceptRejectMsg] = useState<{ id: number; msg: string } | null>(null)
  const [form, setForm] = useState({
    name: '',
    email: '',
    phone: '',
    date: '',
    time: '',
    reason: '',
  })

  const fetchAppointments = async () => {
    try {
      const res = await axios.get(`${API_URL}/api/appointments`)
      setAppointments(res.data.appointments || [])
    } catch (e) {
      console.error('Failed to fetch appointments', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAppointments()
    const interval = setInterval(fetchAppointments, 30000)
    return () => clearInterval(interval)
  }, [])

  const filtered = appointments.filter((a) => {
    if (statusFilter !== 'all' && a.status !== statusFilter) return false
    if (dateFrom && a.date < dateFrom) return false
    if (dateTo && a.date > dateTo) return false
    return true
  }).sort((a, b) => {
    const d = (x: Appointment) => `${x.date}T${x.time || '00:00'}`
    return d(a).localeCompare(d(b))
  })

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.name.trim() || !form.date.trim() || !form.time.trim()) return
    setSubmitting(true)
    try {
      await axios.post(`${API_URL}/api/appointments`, {
        name: form.name.trim(),
        email: form.email.trim() || '',
        phone: form.phone.trim() || '',
        date: form.date,
        time: form.time,
        reason: form.reason.trim() || '—',
      })
      setForm({ name: '', email: '', phone: '', date: '', time: '', reason: '' })
      setShowForm(false)
      await fetchAppointments()
    } catch (e) {
      console.error('Failed to create appointment', e)
    } finally {
      setSubmitting(false)
    }
  }

  const handleStatusChange = async (id: number, newStatus: string) => {
    setUpdatingId(id)
    try {
      await axios.patch(`${API_URL}/api/appointments/${id}`, { status: newStatus })
      await fetchAppointments()
    } catch (e) {
      console.error('Failed to update appointment', e)
    } finally {
      setUpdatingId(null)
    }
  }

  const fromReceptionist = appointments.filter(
    (a) => (a.source === 'receptionist') && (a.status === 'pending_review' || a.status === 'pending')
  )

  const handleCopy = async (apt: Appointment) => {
    try {
      await navigator.clipboard.writeText(copyBlock(apt))
      setAcceptRejectMsg({ id: apt.id, msg: 'Copied to clipboard' })
      setTimeout(() => setAcceptRejectMsg(null), 2000)
    } catch {
      setAcceptRejectMsg({ id: apt.id, msg: 'Copy failed' })
      setTimeout(() => setAcceptRejectMsg(null), 2000)
    }
  }

  const handleAccept = async (id: number) => {
    setUpdatingId(id)
    setAcceptRejectMsg(null)
    try {
      await axios.post(`${API_URL}/api/appointments/${id}/accept`)
      await fetchAppointments()
      setAcceptRejectMsg({ id, msg: 'Accepted; confirmation text sent.' })
      setTimeout(() => setAcceptRejectMsg(null), 3000)
    } catch (e) {
      console.error('Failed to accept', e)
      setAcceptRejectMsg({ id, msg: 'Accept failed' })
      setTimeout(() => setAcceptRejectMsg(null), 3000)
    } finally {
      setUpdatingId(null)
    }
  }

  const handleReject = async (id: number) => {
    setUpdatingId(id)
    setAcceptRejectMsg(null)
    try {
      await axios.post(`${API_URL}/api/appointments/${id}/reject`)
      await fetchAppointments()
      setAcceptRejectMsg({ id, msg: "Rejected; we've asked them for other times." })
      setTimeout(() => setAcceptRejectMsg(null), 3000)
    } catch (e) {
      console.error('Failed to reject', e)
      setAcceptRejectMsg({ id, msg: 'Reject failed' })
      setTimeout(() => setAcceptRejectMsg(null), 3000)
    } finally {
      setUpdatingId(null)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600" />
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="bg-white rounded-2xl shadow-xl p-6">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
          <h2 className="text-xl font-bold text-gray-900 flex items-center">
            <Calendar className="w-6 h-6 mr-2 text-primary-600" />
            Appointments
          </h2>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setShowForm((v) => !v)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg font-medium bg-primary-600 text-white hover:bg-primary-700 shadow"
            >
              <Plus className="w-4 h-4" />
              New appointment
            </button>
            <button
              type="button"
              onClick={() => { setLoading(true); fetchAppointments(); }}
              className="p-2 rounded-lg border border-gray-300 hover:bg-gray-50"
              title="Refresh"
            >
              <RefreshCw className="w-4 h-4 text-gray-600" />
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap gap-4 mb-6 p-4 bg-gray-50 rounded-lg">
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-gray-700">Status</label>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded border border-gray-300 px-3 py-1.5 text-sm"
            >
              <option value="all">All</option>
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>{STATUS_LABELS[s] || s}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-gray-700">From date</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="rounded border border-gray-300 px-3 py-1.5 text-sm"
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-gray-700">To date</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="rounded border border-gray-300 px-3 py-1.5 text-sm"
            />
          </div>
        </div>

        {/* Create form */}
        {showForm && (
          <form onSubmit={handleCreate} className="mb-6 p-4 border border-primary-200 rounded-lg bg-primary-50/50 space-y-4">
            <h3 className="font-semibold text-gray-900">Add appointment</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  className="w-full rounded border border-gray-300 px-3 py-2"
                  placeholder="Client name"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Phone</label>
                <input
                  type="tel"
                  value={form.phone}
                  onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
                  className="w-full rounded border border-gray-300 px-3 py-2"
                  placeholder="(555) 123-4567"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                <input
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                  className="w-full rounded border border-gray-300 px-3 py-2"
                  placeholder="client@example.com"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Date *</label>
                <input
                  type="date"
                  value={form.date}
                  onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))}
                  className="w-full rounded border border-gray-300 px-3 py-2"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Time *</label>
                <input
                  type="time"
                  value={form.time}
                  onChange={(e) => setForm((f) => ({ ...f, time: e.target.value }))}
                  className="w-full rounded border border-gray-300 px-3 py-2"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Reason / Service</label>
                <input
                  type="text"
                  value={form.reason}
                  onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
                  className="w-full rounded border border-gray-300 px-3 py-2"
                  placeholder="e.g. Haircut, Color"
                />
              </div>
            </div>
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={submitting}
                className="px-4 py-2 rounded-lg font-medium bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50"
              >
                {submitting ? 'Saving…' : 'Save appointment'}
              </button>
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="px-4 py-2 rounded-lg font-medium border border-gray-300 hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* From receptionist: copy-paste for Zenoti + Accept / Reject */}
        {fromReceptionist.length > 0 && (
          <div className="mb-6 p-4 border border-amber-200 rounded-lg bg-amber-50/50">
            <h3 className="text-lg font-semibold text-gray-900 mb-3">From receptionist (review for Zenoti)</h3>
            <p className="text-sm text-gray-600 mb-4">Compare with Zenoti; copy details to paste into Zenoti, then Accept or Reject.</p>
            <div className="space-y-4">
              {fromReceptionist.map((apt) => (
                <div key={apt.id} className="bg-white rounded-lg border border-gray-200 p-4 flex flex-wrap items-start gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-gray-900">{apt.name}</div>
                    <div className="text-sm text-gray-600">{apt.date} at {apt.time || '—'} · {apt.reason || '—'}</div>
                    <pre className="mt-2 p-2 bg-gray-50 rounded text-xs text-gray-700 whitespace-pre-wrap font-sans">
                      {copyBlock(apt)}
                    </pre>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => handleCopy(apt)}
                      className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-gray-300 bg-white text-gray-700 text-sm font-medium hover:bg-gray-50"
                    >
                      <Copy className="w-4 h-4" /> Copy
                    </button>
                    <button
                      type="button"
                      onClick={() => handleAccept(apt.id)}
                      disabled={updatingId === apt.id}
                      className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-green-600 text-white text-sm font-medium hover:bg-green-700 disabled:opacity-50"
                    >
                      <Check className="w-4 h-4" /> Accept
                    </button>
                    <button
                      type="button"
                      onClick={() => handleReject(apt.id)}
                      disabled={updatingId === apt.id}
                      className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700 disabled:opacity-50"
                    >
                      <X className="w-4 h-4" /> Reject
                    </button>
                    {acceptRejectMsg?.id === apt.id && (
                      <span className="text-sm text-gray-600">{acceptRejectMsg.msg}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* List */}
        {filtered.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            <Calendar className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p>No appointments match your filters.</p>
            {appointments.length === 0 && (
              <p className="mt-1 text-sm">Create one with the button above or via the AI receptionist.</p>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-3 px-3 font-semibold text-gray-700">Client</th>
                  <th className="text-left py-3 px-3 font-semibold text-gray-700">Date & time</th>
                  <th className="text-left py-3 px-3 font-semibold text-gray-700">Reason</th>
                  <th className="text-left py-3 px-3 font-semibold text-gray-700">Source</th>
                  <th className="text-left py-3 px-3 font-semibold text-gray-700">Status</th>
                  <th className="text-left py-3 px-3 font-semibold text-gray-700">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((apt) => (
                  <tr key={apt.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="py-3 px-3">
                      <div className="font-medium text-gray-900">{apt.name}</div>
                      {apt.phone && (
                        <div className="flex items-center gap-1 text-sm text-gray-500">
                          <Phone className="w-3 h-3" /> {apt.phone}
                        </div>
                      )}
                      {apt.email && (
                        <div className="flex items-center gap-1 text-sm text-gray-500">
                          <Mail className="w-3 h-3" /> {apt.email}
                        </div>
                      )}
                    </td>
                    <td className="py-3 px-3">
                      <div className="flex items-center gap-1">
                        <Calendar className="w-4 h-4 text-gray-400" />
                        {apt.date}
                      </div>
                      <div className="flex items-center gap-1 text-sm text-gray-600">
                        <Clock className="w-3 h-3" />
                        {apt.time || '—'}
                      </div>
                    </td>
                    <td className="py-3 px-3 text-gray-700 max-w-xs truncate" title={apt.reason}>
                      {apt.reason || '—'}
                    </td>
                    <td className="py-3 px-3 text-sm text-gray-600">
                      {(apt as Appointment & { source?: string }).source === 'receptionist' ? 'Receptionist' : 'Manual'}
                    </td>
                    <td className="py-3 px-3">
                      <span
                        className={`inline-block px-2 py-1 rounded-full text-xs font-medium ${
                          STATUS_CLASSES[apt.status] || 'bg-gray-100 text-gray-700'
                        }`}
                      >
                        {STATUS_LABELS[apt.status] || apt.status}
                      </span>
                    </td>
                    <td className="py-3 px-3">
                      {(apt as Appointment & { source?: string }).source === 'receptionist' && (apt.status === 'pending_review' || apt.status === 'pending') ? (
                        <div className="flex flex-wrap items-center gap-2">
                          <button type="button" onClick={() => handleCopy(apt)} className="text-sm px-2 py-1 rounded border border-gray-300 hover:bg-gray-50">Copy</button>
                          <button type="button" onClick={() => handleAccept(apt.id)} disabled={updatingId === apt.id} className="text-sm px-2 py-1 rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50">Accept</button>
                          <button type="button" onClick={() => handleReject(apt.id)} disabled={updatingId === apt.id} className="text-sm px-2 py-1 rounded bg-red-600 text-white hover:bg-red-700 disabled:opacity-50">Reject</button>
                        </div>
                      ) : (
                      <select
                        value={apt.status}
                        onChange={(e) => handleStatusChange(apt.id, e.target.value)}
                        disabled={updatingId === apt.id}
                        className="text-sm rounded border border-gray-300 py-1 px-2 disabled:opacity-50"
                      >
                        {STATUS_OPTIONS.map((s) => (
                          <option key={s} value={s}>{STATUS_LABELS[s]}</option>
                        ))}
                      </select>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
