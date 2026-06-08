'use client'

import { useState, useEffect } from 'react'
import { Calendar, MessageSquare, Phone, TrendingUp, BarChart3 } from 'lucide-react'
import { useApiClient } from '@/lib/api'
import { RevealStagger, RevealItem, AnimatedNumber } from '@/components/motion'
import { formatTimeHhmmToAmPm } from '@/lib/formatTime'
import { STATUS_CLASSES, STATUS_LABELS } from '@/components/appointments/appointmentStatus'

/** Call log outcome pills — dark text on tinted fills for white cards. */
function callOutcomeClass(outcome: string): string {
  if (outcome === 'answered_by_ai') return 'bg-emerald-200 text-emerald-950'
  if (outcome === 'forwarded') return 'bg-blue-200 text-blue-950'
  if (outcome === 'missed' || outcome === 'no_answer') return 'bg-red-200 text-red-950'
  return 'bg-gray-200 text-gray-900'
}

interface Appointment {
  id: number
  name: string
  email: string
  phone: string
  date: string
  time: string
  reason: string
  status: string
  created_at: string
}

interface Message {
  id: number
  caller_name: string
  caller_phone: string
  message: string
  urgency: string
  status: string
  created_at: string
}

interface Stats {
  total_appointments: number
  total_messages: number
  pending_appointments: number
}

interface AnalyticsSummary {
  total_calls: number
  by_outcome: Record<string, number>
  by_hour: Record<string, number>
  by_day_of_week: Record<string, number>
  client_id: string | null
  /** ISO date (Monday) — counts below are for this week only (UTC). */
  by_day_of_week_period_start?: string
  by_day_of_week_period_end?: string
  by_day_of_week_timezone?: string
}

interface AnalyticsHealth {
  period_days: number
  calls_total: number
  forward_rate: number
  error_rate: number
  missed_rate: number
  booking_completion_rate: number
  avg_duration_sec: number
  by_outcome: Record<string, number>
}

interface CallLogEntry {
  call_sid: string
  from_number: string
  to_number: string
  start_iso: string
  end_iso?: string
  outcome: string
  duration_sec?: number
  category?: string
  recording_sid?: string | null
  recording_url?: string | null
  recording_duration_sec?: number | null
  recording_status?: string | null
  call_summary?: string | null
  created_at?: string | null
}

const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export default function Dashboard() {
  const api = useApiClient()
  const [stats, setStats] = useState<Stats>({
    total_appointments: 0,
    total_messages: 0,
    pending_appointments: 0
  })
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [analyticsSummary, setAnalyticsSummary] = useState<AnalyticsSummary | null>(null)
  const [callHealth, setCallHealth] = useState<AnalyticsHealth | null>(null)
  const [recentCalls, setRecentCalls] = useState<CallLogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [noTenant, setNoTenant] = useState(false)
  const [hasExport, setHasExport] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [usage, setUsage] = useState<{ voice_minutes: number; sms_count: number; month: string } | null>(null)
  const [minutesCap, setMinutesCap] = useState<number | null>(null)

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 30000) // Refresh every 30 seconds
    return () => clearInterval(interval)
  }, [api])

  const fetchData = async () => {
    try {
      const [statsRes, appointmentsRes, messagesRes, summaryRes, callsRes, subRes, healthRes] = await Promise.all([
        api.get('/api/stats'),
        api.get('/api/appointments'),
        api.get('/api/messages'),
        api.get('/api/analytics/summary').catch(() => ({ data: null })),
        api.get('/api/analytics/calls?limit=20').catch(() => ({ data: { calls: [] } })),
        api.get('/api/subscription').catch(() => ({ data: null })),
        api.get('/api/analytics/health').catch(() => ({ data: null })),
      ])

      const sub = subRes?.data as { limits?: { has_export?: boolean; minutes_cap?: number }; usage?: { voice_minutes?: number; sms_count?: number; month?: string } } | null
      const limits = sub?.limits
      setHasExport(!!limits?.has_export)
      setMinutesCap(limits?.minutes_cap ?? null)
      setUsage(sub?.usage ?? null)
      setStats(statsRes.data)
      setAppointments(appointmentsRes.data.appointments || [])
      setMessages(messagesRes.data.messages || [])
      setAnalyticsSummary(summaryRes.data?.client_id != null ? summaryRes.data : null)
      setCallHealth(healthRes.data?.calls_total != null ? healthRes.data : null)
      setRecentCalls(callsRes.data?.calls || [])
    } catch (error: unknown) {
      const status = (error as { response?: { status?: number } })?.response?.status
      if (status === 401 || status === 403) {
        setNoTenant(true)
      }
      console.error('Error fetching data:', error)
    } finally {
      setLoading(false)
    }
  }

  if (noTenant) {
    return (
      <div className="flex flex-col items-center justify-center h-64 space-y-4">
        <p className="text-zinc-300 text-center max-w-md">
          Your account is not yet linked to a business. If you were invited, please use the link from your invite email. Otherwise, contact support.
        </p>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  return (
    <div className="space-y-6 text-gray-900">
      {/* Usage widget */}
      {usage != null && minutesCap != null && minutesCap > 0 && (
        <div className="bg-white rounded-lg shadow-md p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-2">Usage this month</h3>
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <div className="flex justify-between text-sm text-gray-600 mb-1">
                <span>Voice minutes: {usage.voice_minutes} / {minutesCap}</span>
                {usage.voice_minutes > minutesCap && (
                  <span className="text-amber-600">Overage: {usage.voice_minutes - minutesCap} extra min</span>
                )}
              </div>
              <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${usage.voice_minutes >= minutesCap ? 'bg-amber-500' : 'bg-primary-600'}`}
                  style={{ width: `${Math.min(100, (usage.voice_minutes / minutesCap) * 100)}%` }}
                />
              </div>
            </div>
            <div className="text-sm text-gray-600">SMS: {usage.sms_count}</div>
          </div>
        </div>
      )}

      {/* Stats Cards */}
      <RevealStagger className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <RevealItem className="bg-white rounded-lg shadow-md p-6 transition-transform duration-200 hover:-translate-y-1 hover:shadow-lg">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-gray-600 text-sm font-medium">Total Appointments</p>
              <p className="text-3xl font-bold text-gray-900 mt-2">
                <AnimatedNumber value={stats.total_appointments} />
              </p>
            </div>
            <div className="bg-blue-100 p-3 rounded-full">
              <Calendar className="w-6 h-6 text-blue-600" />
            </div>
          </div>
        </RevealItem>

        <RevealItem className="bg-white rounded-lg shadow-md p-6 transition-transform duration-200 hover:-translate-y-1 hover:shadow-lg">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-gray-600 text-sm font-medium">Total Messages</p>
              <p className="text-3xl font-bold text-gray-900 mt-2">
                <AnimatedNumber value={stats.total_messages} />
              </p>
            </div>
            <div className="bg-green-100 p-3 rounded-full">
              <MessageSquare className="w-6 h-6 text-green-600" />
            </div>
          </div>
        </RevealItem>

        <RevealItem className="bg-white rounded-lg shadow-md p-6 transition-transform duration-200 hover:-translate-y-1 hover:shadow-lg">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-gray-600 text-sm font-medium">Pending Appointments</p>
              <p className="text-3xl font-bold text-gray-900 mt-2">
                <AnimatedNumber value={stats.pending_appointments} />
              </p>
            </div>
            <div className="bg-yellow-100 p-3 rounded-full">
              <TrendingUp className="w-6 h-6 text-yellow-600" />
            </div>
          </div>
        </RevealItem>
      </RevealStagger>

      {callHealth != null && (
        <div className="bg-white rounded-lg shadow-md p-6">
          <h2 className="text-xl font-bold text-gray-900 flex items-center mb-4">
            <Phone className="w-5 h-5 mr-2" />
            Call health (last {callHealth.period_days} days)
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-gray-600 text-sm">Total calls</p>
              <p className="text-2xl font-bold text-gray-900">{callHealth.calls_total}</p>
            </div>
            <div>
              <p className="text-gray-600 text-sm">Forward rate</p>
              <p className="text-2xl font-bold text-gray-900">{Math.round(callHealth.forward_rate * 100)}%</p>
            </div>
            <div>
              <p className="text-gray-600 text-sm">Missed / no answer</p>
              <p className="text-2xl font-bold text-gray-900">{Math.round(callHealth.missed_rate * 100)}%</p>
            </div>
            <div>
              <p className="text-gray-600 text-sm">Avg duration</p>
              <p className="text-2xl font-bold text-gray-900">
                {callHealth.avg_duration_sec ? `${callHealth.avg_duration_sec}s` : '—'}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Call Analytics */}
      {analyticsSummary != null && (
        <div className="bg-white rounded-lg shadow-md p-6">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-xl font-bold text-gray-900 flex items-center">
              <BarChart3 className="w-5 h-5 mr-2" />
              Call Analytics
            </h2>
            {hasExport && (
              <button
                type="button"
                disabled={exporting}
                onClick={async () => {
                  setExporting(true)
                  try {
                    const res = await api.get('/api/analytics/export', { responseType: 'blob' })
                    const blob = new Blob([res.data], { type: 'text/csv' })
                    const url = URL.createObjectURL(blob)
                    const a = document.createElement('a')
                    a.href = url
                    a.download = 'call_log.csv'
                    a.click()
                    setTimeout(() => URL.revokeObjectURL(url), 100)
                  } catch {
                    // 403 or error - ignore
                  } finally {
                    setExporting(false)
                  }
                }}
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50"
              >
                {exporting ? 'Exporting…' : 'Export CSV'}
              </button>
            )}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
            <div>
              <p className="text-gray-600 text-sm font-medium">Total calls</p>
              <p className="text-3xl font-bold text-gray-900 mt-1">{analyticsSummary.total_calls}</p>
            </div>
            <div>
              <p className="text-gray-600 text-sm font-medium mb-2">By outcome</p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(analyticsSummary.by_outcome).map(([outcome, count]) => (
                  <span
                    key={outcome}
                    className={`px-2 py-1 rounded-full text-xs font-semibold ${callOutcomeClass(outcome)}`}
                  >
                    {outcome.replace(/_/g, ' ')}: {count}
                  </span>
                ))}
                {Object.keys(analyticsSummary.by_outcome).length === 0 && (
                  <span className="text-gray-500 text-sm">No data yet</span>
                )}
              </div>
            </div>
          </div>
          <div className="mb-4">
            <p className="text-gray-600 text-sm font-medium mb-2">Peak call times (by hour)</p>
            <div className="flex flex-wrap gap-1 items-end" style={{ minHeight: '24px' }}>
              {Array.from({ length: 24 }, (_, h) => {
                const count = analyticsSummary.by_hour[String(h)] ?? 0
                const max = Math.max(...Object.values(analyticsSummary.by_hour).map(Number), 1)
                const pct = max ? (count / max) * 100 : 0
                return (
                  <div key={h} className="flex flex-col items-center" title={`${h}:00 - ${count} calls`}>
                    <div
                      className="w-3 bg-primary-600 rounded-t min-h-[4px]"
                      style={{ height: `${Math.max(pct, 4)}px` }}
                    />
                    <span className="mt-1 text-[10px] font-medium text-gray-700">{h}</span>
                  </div>
                )
              })}
            </div>
          </div>
          <div>
            <p className="text-gray-600 text-sm font-medium mb-1">By day of week (this week)</p>
            {analyticsSummary.by_day_of_week_period_start && analyticsSummary.by_day_of_week_period_end && (
              <p className="text-gray-500 text-xs mb-2">
                {analyticsSummary.by_day_of_week_period_start} – {analyticsSummary.by_day_of_week_period_end}
                {analyticsSummary.by_day_of_week_timezone ? ` (${analyticsSummary.by_day_of_week_timezone})` : ''}. Full history stays in the database; use Export CSV for all calls in your plan window.
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              {[0, 1, 2, 3, 4, 5, 6].map((d) => (
                <span key={d} className="rounded bg-gray-200 px-2 py-1 text-xs font-medium text-gray-900">
                  {DAY_NAMES[d]}: {analyticsSummary.by_day_of_week[String(d)] ?? 0}
                </span>
              ))}
            </div>
          </div>
          <div className="mt-6">
            <p className="text-gray-700 font-semibold mb-2">Recent calls</p>
            {recentCalls.length === 0 ? (
              <p className="text-gray-500 text-sm">No calls logged yet</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-gray-900">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th className="text-left py-2 px-2 font-semibold text-gray-800">From</th>
                      <th className="text-left py-2 px-2 font-semibold text-gray-800">Start</th>
                      <th className="text-left py-2 px-2 font-semibold text-gray-800">Duration</th>
                      <th className="text-left py-2 px-2 font-semibold text-gray-800">Outcome</th>
                      <th className="text-left py-2 px-2 font-semibold text-gray-800">Summary</th>
                      <th className="text-left py-2 px-2 font-semibold text-gray-800">Recording</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentCalls.slice(0, 10).map((call) => (
                      <tr key={call.call_sid} className="border-b border-gray-200 hover:bg-gray-50">
                        <td className="py-2 px-2 font-medium text-gray-900">{call.from_number}</td>
                        <td className="py-2 px-2 text-gray-900">
                          {call.start_iso ? new Date(call.start_iso).toLocaleString() : '—'}
                        </td>
                        <td className="py-2 px-2 text-gray-900">
                          {call.duration_sec != null ? `${call.duration_sec}s` : '—'}
                        </td>
                        <td className="py-2 px-2">
                          <span
                            className={`rounded px-2 py-0.5 text-xs font-semibold ${callOutcomeClass(call.outcome || '')}`}
                          >
                            {call.outcome || '—'}
                          </span>
                        </td>
                        <td className="max-w-[200px] py-2 px-2">
                          {call.call_summary ? (
                            <span className="line-clamp-2 text-gray-900" title={call.call_summary}>
                              {call.call_summary.length > 120 ? `${call.call_summary.slice(0, 120)}…` : call.call_summary}
                            </span>
                          ) : (
                            <span className="text-gray-600">—</span>
                          )}
                        </td>
                        <td className="py-2 px-2">
                          {call.recording_sid || call.recording_url ? (
                            <button
                              type="button"
                              className="text-primary-600 hover:text-primary-800 text-sm font-medium underline"
                              onClick={async () => {
                                try {
                                  const res = await api.get(
                                    `/api/analytics/calls/${encodeURIComponent(call.call_sid)}/recording`,
                                    { responseType: 'blob' }
                                  )
                                  const blob = new Blob([res.data], { type: 'audio/mpeg' })
                                  const url = URL.createObjectURL(blob)
                                  window.open(url, '_blank', 'noopener,noreferrer')
                                  setTimeout(() => URL.revokeObjectURL(url), 120_000)
                                } catch {
                                  // 404 / auth — ignore
                                }
                              }}
                            >
                              Play
                            </button>
                          ) : (
                            <span className="text-gray-600">—</span>
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
      )}

      {/* Appointments Table */}
      <div className="bg-white rounded-lg shadow-md p-6">
        <h2 className="text-xl font-bold text-gray-900 mb-4 flex items-center">
          <Calendar className="w-5 h-5 mr-2" />
          Recent Appointments
        </h2>
        {appointments.length === 0 ? (
          <p className="text-gray-500 text-center py-8">No appointments yet</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-gray-900">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-3 px-4 font-semibold text-gray-800">Name</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-800">Date</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-800">Time</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-800">Reason</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-800">Status</th>
                </tr>
              </thead>
              <tbody>
                {appointments.slice(0, 10).map((appointment) => (
                  <tr key={appointment.id} className="border-b border-gray-200 hover:bg-gray-50">
                    <td className="py-3 px-4 font-medium text-gray-900">{appointment.name}</td>
                    <td className="py-3 px-4 text-gray-900">{appointment.date}</td>
                    <td className="py-3 px-4 text-gray-900">{formatTimeHhmmToAmPm(appointment.time)}</td>
                    <td className="py-3 px-4 text-gray-900">{appointment.reason}</td>
                    <td className="py-3 px-4">
                      <span
                        className={`inline-block rounded-full px-2 py-1 text-xs font-semibold ${
                          STATUS_CLASSES[appointment.status] || 'bg-gray-200 text-gray-900'
                        }`}
                      >
                        {STATUS_LABELS[appointment.status] || appointment.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Messages Table */}
      <div className="bg-white rounded-lg shadow-md p-6">
        <h2 className="text-xl font-bold text-gray-900 mb-4 flex items-center">
          <MessageSquare className="w-5 h-5 mr-2" />
          Recent Messages
        </h2>
        {messages.length === 0 ? (
          <p className="text-gray-500 text-center py-8">No messages yet</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-gray-900">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-3 px-4 font-semibold text-gray-800">Caller</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-800">Phone</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-800">Message</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-800">Urgency</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-800">Status</th>
                </tr>
              </thead>
              <tbody>
                {messages.slice(0, 10).map((message) => (
                  <tr key={message.id} className="border-b border-gray-200 hover:bg-gray-50">
                    <td className="py-3 px-4 font-medium text-gray-900">{message.caller_name}</td>
                    <td className="py-3 px-4 text-gray-900">{message.caller_phone}</td>
                    <td className="max-w-md truncate py-3 px-4 text-gray-900">{message.message}</td>
                    <td className="py-3 px-4">
                      <span
                        className={`inline-block rounded-full px-2 py-1 text-xs font-semibold ${
                          message.urgency === 'urgent'
                            ? 'bg-red-200 text-red-950'
                            : message.urgency === 'high'
                              ? 'bg-orange-200 text-orange-950'
                              : 'bg-sky-200 text-sky-950'
                        }`}
                      >
                        {message.urgency}
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      <span
                        className={`inline-block rounded-full px-2 py-1 text-xs font-semibold ${
                          message.status === 'unread'
                            ? 'bg-amber-200 text-amber-950'
                            : 'bg-emerald-200 text-emerald-950'
                        }`}
                      >
                        {message.status}
                      </span>
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












