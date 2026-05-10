'use client'

import { useState, useEffect } from 'react'
import { Calendar, Plus, RefreshCw, Clock, Mail, Phone, LayoutGrid, List } from 'lucide-react'
import { useApiClient } from '@/lib/api'
import { formatTimeHhmmToAmPm } from '@/lib/formatTime'
import AppointmentCalendar from '@/components/AppointmentCalendar'
import {
  STATUS_CLASSES,
  STATUS_LABELS,
  canAcceptOrDecline,
  needsResponse,
} from '@/components/appointments/appointmentStatus'

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
  staff_id?: string | null
  owner_decline_reason?: string | null
}

export default function Appointments() {
  const api = useApiClient()
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [updatingId, setUpdatingId] = useState<number | null>(null)
  const [acceptRejectMsg, setAcceptRejectMsg] = useState<{ id: number; msg: string } | null>(null)
  const [view, setView] = useState<'list' | 'calendar'>('list')
  const [rejectModalId, setRejectModalId] = useState<number | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [declinePreview, setDeclinePreview] = useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [staffOptions, setStaffOptions] = useState<{ id: string; name: string }[]>([])
  const [form, setForm] = useState({
    name: '',
    email: '',
    phone: '',
    date: '',
    time: '',
    reason: '',
    staff_id: '',
  })

  const fetchAppointments = async () => {
    try {
      const res = await api.get('/api/appointments')
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
  }, [api])

  useEffect(() => {
    api
      .get('/api/business-info')
      .then((r) => {
        const st = (r.data?.staff || []) as { id?: string; name?: string }[]
        setStaffOptions(
          st.filter((s) => s.id && s.name).map((s) => ({ id: s.id as string, name: s.name as string }))
        )
      })
      .catch(() => setStaffOptions([]))
  }, [api])

  const staffNameById = Object.fromEntries(staffOptions.map((s) => [s.id, s.name]))

  const filtered = appointments.filter((a) => {
    if (statusFilter === 'needs_response' && !needsResponse(a.status)) return false
    if (statusFilter === 'accepted' && !['accepted', 'confirmed', 'completed'].includes(a.status)) return false
    if (statusFilter === 'declined' && !['rejected', 'cancelled'].includes(a.status)) return false
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
      await api.post('/api/appointments', {
        name: form.name.trim(),
        email: form.email.trim() || '',
        phone: form.phone.trim() || '',
        date: form.date,
        time: form.time,
        reason: form.reason.trim() || '—',
        ...(form.staff_id.trim() ? { staff_id: form.staff_id.trim() } : {}),
      })
      setForm({ name: '', email: '', phone: '', date: '', time: '', reason: '', staff_id: '' })
      setShowForm(false)
      await fetchAppointments()
    } catch (e) {
      console.error('Failed to create appointment', e)
    } finally {
      setSubmitting(false)
    }
  }

  const handleAccept = async (id: number) => {
    setUpdatingId(id)
    setAcceptRejectMsg(null)
    try {
      await api.post(`/api/appointments/${id}/accept`)
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

  const confirmReject = async () => {
    if (rejectModalId == null || !rejectReason.trim()) return
    const id = rejectModalId
    setUpdatingId(id)
    setAcceptRejectMsg(null)
    try {
      await api.post(`/api/appointments/${id}/reject`, { reason: rejectReason.trim() })
      await fetchAppointments()
      setAcceptRejectMsg({ id, msg: 'Declined; customer was notified.' })
      setTimeout(() => setAcceptRejectMsg(null), 3000)
      setRejectModalId(null)
      setRejectReason('')
    } catch (e) {
      console.error('Failed to reject', e)
      setAcceptRejectMsg({ id, msg: 'Decline failed' })
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
    <div className="mx-auto max-w-5xl space-y-6 text-gray-900">
      <div className="bg-white rounded-2xl shadow-xl p-6">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
          <h2 className="text-xl font-bold text-gray-900 flex items-center">
            <Calendar className="w-6 h-6 mr-2 text-primary-600" />
            Appointments
          </h2>
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex rounded-lg border border-gray-200 p-0.5 bg-gray-50">
              <button
                type="button"
                onClick={() => setView('list')}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium ${
                  view === 'list' ? 'bg-white shadow text-primary-700' : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                <List className="w-4 h-4" />
                List
              </button>
              <button
                type="button"
                onClick={() => setView('calendar')}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium ${
                  view === 'calendar' ? 'bg-white shadow text-primary-700' : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                <LayoutGrid className="w-4 h-4" />
                Calendar
              </button>
            </div>
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

        {view === 'calendar' ? (
          <AppointmentCalendar api={api} />
        ) : null}

        {/* Filters */}
        {view === 'list' ? (
        <div className="flex flex-wrap gap-4 mb-6 p-4 bg-gray-50 rounded-lg">
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-gray-700">Status</label>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="cs-field-compact min-w-[11rem]"
            >
              <option value="all">All</option>
              <option value="needs_response">Needs response</option>
              <option value="accepted">Accepted</option>
              <option value="declined">Declined</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-gray-700">From date</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="cs-field-compact min-w-[11rem]"
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-gray-700">To date</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="cs-field-compact min-w-[11rem]"
            />
          </div>
        </div>
        ) : null}

        {/* Create form */}
        {view === 'list' && showForm && (
          <form onSubmit={handleCreate} className="mb-6 p-4 border border-primary-200 rounded-lg bg-primary-50/50 space-y-4">
            <h3 className="font-semibold text-gray-900">Add appointment</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  className="cs-field w-full"
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
                  className="cs-field w-full"
                  placeholder="(555) 123-4567"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                <input
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                  className="cs-field w-full"
                  placeholder="client@example.com"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Date *</label>
                <input
                  type="date"
                  value={form.date}
                  onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))}
                  className="cs-field w-full"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Time *</label>
                <input
                  type="time"
                  value={form.time}
                  onChange={(e) => setForm((f) => ({ ...f, time: e.target.value }))}
                  className="cs-field w-full"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Reason / Service</label>
                <input
                  type="text"
                  value={form.reason}
                  onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
                  className="cs-field w-full"
                  placeholder="e.g. Haircut, Color"
                />
              </div>
              {staffOptions.length > 0 && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Provider (optional)</label>
                  <select
                    value={form.staff_id}
                    onChange={(e) => setForm((f) => ({ ...f, staff_id: e.target.value }))}
                    className="cs-field w-full"
                  >
                    <option value="">Any / not specified</option>
                    {staffOptions.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
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

        {/* List */}
        {view === 'list' && filtered.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            <Calendar className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p>No appointments match your filters.</p>
            {appointments.length === 0 && (
              <p className="mt-1 text-sm">Create one with the button above or via the AI receptionist.</p>
            )}
          </div>
        ) : view === 'list' ? (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-3 px-3 font-semibold text-gray-700">Client</th>
                  <th className="text-left py-3 px-3 font-semibold text-gray-700">Date & time</th>
                  <th className="text-left py-3 px-3 font-semibold text-gray-700">Reason</th>
                  {staffOptions.length > 0 && (
                    <th className="text-left py-3 px-3 font-semibold text-gray-700">Provider</th>
                  )}
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
                      <div className="flex items-center gap-1 text-sm text-gray-500">
                        <Phone className="w-3 h-3" /> {apt.phone || 'Not provided'}
                      </div>
                      <div className="flex items-center gap-1 text-sm text-gray-500">
                        <Mail className="w-3 h-3" /> {apt.email || 'Not provided'}
                      </div>
                    </td>
                    <td className="py-3 px-3">
                      <div className="flex items-center gap-1">
                        <Calendar className="w-4 h-4 text-gray-400" />
                        {apt.date}
                      </div>
                      <div className="flex items-center gap-1 text-sm text-gray-600">
                        <Clock className="w-3 h-3" />
                        {formatTimeHhmmToAmPm(apt.time)}
                      </div>
                    </td>
                    <td className="py-3 px-3 text-gray-700 max-w-xs truncate" title={apt.reason}>
                      {apt.reason || '—'}
                    </td>
                    {staffOptions.length > 0 && (
                      <td className="py-3 px-3 text-sm text-gray-600">
                        {(apt.staff_id && staffNameById[apt.staff_id]) || '—'}
                      </td>
                    )}
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
                      {apt.status === 'pending_customer' ? (
                        <span className="text-sm text-gray-500">Customer must confirm by text first</span>
                      ) : canAcceptOrDecline(apt.status) ? (
                        <div className="flex flex-wrap items-center gap-2">
                          <button type="button" onClick={() => handleAccept(apt.id)} disabled={updatingId === apt.id} className="text-sm px-3 py-1.5 rounded font-medium bg-green-600 text-white hover:bg-green-700 disabled:opacity-50">Accept</button>
                          <button
                            type="button"
                            onClick={() => {
                              setRejectModalId(apt.id)
                              setRejectReason('')
                              setDeclinePreview(null)
                            }}
                            disabled={updatingId === apt.id}
                            className="text-sm px-3 py-1.5 rounded font-medium bg-red-600 text-white hover:bg-red-700 disabled:opacity-50"
                          >
                            Decline
                          </button>
                          {acceptRejectMsg?.id === apt.id && <span className="text-xs text-gray-500">{acceptRejectMsg.msg}</span>}
                        </div>
                      ) : (
                        <span className="text-sm text-gray-500">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {rejectModalId != null && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
              <h3 className="text-lg font-semibold text-gray-900">Decline appointment</h3>
              <p className="mt-1 text-sm text-gray-600">
                Brief reason for the customer (we&apos;ll polish the text before texting them).
              </p>
              <textarea
                className="cs-field mt-4 w-full min-h-[100px]"
                placeholder="e.g. Stylist booked — can we do 3 PM instead?"
                value={rejectReason}
                onChange={(e) => {
                  setRejectReason(e.target.value)
                  setDeclinePreview(null)
                }}
              />
              {declinePreview != null && (
                <div className="mt-3 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-800">
                  <span className="font-medium text-gray-600">Customer will receive:</span>
                  <p className="mt-1 whitespace-pre-wrap">{declinePreview}</p>
                </div>
              )}
              <div className="mt-4 flex flex-wrap justify-end gap-2">
                <button
                  type="button"
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                  onClick={() => {
                    setRejectModalId(null)
                    setRejectReason('')
                    setDeclinePreview(null)
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={!rejectReason.trim() || previewLoading}
                  className="rounded-lg border border-primary-600 px-4 py-2 text-sm font-medium text-primary-700 hover:bg-primary-50 disabled:opacity-50"
                  onClick={async () => {
                    if (!rejectReason.trim() || rejectModalId == null) return
                    setPreviewLoading(true)
                    setDeclinePreview(null)
                    try {
                      const res = await api.post('/api/appointments/preview-decline-sms', {
                        reason: rejectReason.trim(),
                        appointment_id: rejectModalId,
                      })
                      setDeclinePreview(String(res.data?.polished_message || '').trim() || null)
                    } catch {
                      setDeclinePreview('Could not generate preview.')
                    } finally {
                      setPreviewLoading(false)
                    }
                  }}
                >
                  {previewLoading ? 'Preview…' : 'Preview SMS'}
                </button>
                <button
                  type="button"
                  disabled={!rejectReason.trim() || updatingId === rejectModalId}
                  className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                  onClick={() => void confirmReject()}
                >
                  Send decline
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
