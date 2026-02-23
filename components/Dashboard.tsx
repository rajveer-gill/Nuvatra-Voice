'use client'

import { useState, useEffect } from 'react'
import { Calendar, MessageSquare, Phone, TrendingUp, BarChart3 } from 'lucide-react'
import axios from 'axios'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

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
}

const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export default function Dashboard() {
  const [stats, setStats] = useState<Stats>({
    total_appointments: 0,
    total_messages: 0,
    pending_appointments: 0
  })
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [analyticsSummary, setAnalyticsSummary] = useState<AnalyticsSummary | null>(null)
  const [recentCalls, setRecentCalls] = useState<CallLogEntry[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 30000) // Refresh every 30 seconds
    return () => clearInterval(interval)
  }, [])

  const fetchData = async () => {
    try {
      const [statsRes, appointmentsRes, messagesRes, summaryRes, callsRes] = await Promise.all([
        axios.get(`${API_URL}/api/stats`),
        axios.get(`${API_URL}/api/appointments`),
        axios.get(`${API_URL}/api/messages`),
        axios.get(`${API_URL}/api/analytics/summary`).catch(() => ({ data: null })),
        axios.get(`${API_URL}/api/analytics/calls?limit=20`).catch(() => ({ data: { calls: [] } }))
      ])

      setStats(statsRes.data)
      setAppointments(appointmentsRes.data.appointments || [])
      setMessages(messagesRes.data.messages || [])
      setAnalyticsSummary(summaryRes.data?.client_id != null ? summaryRes.data : null)
      setRecentCalls(callsRes.data?.calls || [])
    } catch (error) {
      console.error('Error fetching data:', error)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white rounded-lg shadow-md p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-gray-600 text-sm font-medium">Total Appointments</p>
              <p className="text-3xl font-bold text-gray-900 mt-2">{stats.total_appointments}</p>
            </div>
            <div className="bg-blue-100 p-3 rounded-full">
              <Calendar className="w-6 h-6 text-blue-600" />
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg shadow-md p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-gray-600 text-sm font-medium">Total Messages</p>
              <p className="text-3xl font-bold text-gray-900 mt-2">{stats.total_messages}</p>
            </div>
            <div className="bg-green-100 p-3 rounded-full">
              <MessageSquare className="w-6 h-6 text-green-600" />
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg shadow-md p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-gray-600 text-sm font-medium">Pending Appointments</p>
              <p className="text-3xl font-bold text-gray-900 mt-2">{stats.pending_appointments}</p>
            </div>
            <div className="bg-yellow-100 p-3 rounded-full">
              <TrendingUp className="w-6 h-6 text-yellow-600" />
            </div>
          </div>
        </div>
      </div>

      {/* Pro: Call Analytics */}
      {analyticsSummary != null && (
        <div className="bg-white rounded-lg shadow-md p-6">
          <h2 className="text-xl font-bold text-gray-900 mb-4 flex items-center">
            <BarChart3 className="w-5 h-5 mr-2" />
            Call Analytics (Pro)
          </h2>
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
                    className={`px-2 py-1 rounded-full text-xs font-medium ${
                      outcome === 'answered_by_ai' ? 'bg-green-100 text-green-800' :
                      outcome === 'forwarded' ? 'bg-blue-100 text-blue-800' :
                      outcome === 'missed' ? 'bg-red-100 text-red-800' : 'bg-gray-100 text-gray-800'
                    }`}
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
                    <span className="text-[10px] text-gray-500 mt-1">{h}</span>
                  </div>
                )
              })}
            </div>
          </div>
          <div>
            <p className="text-gray-600 text-sm font-medium mb-2">By day of week</p>
            <div className="flex flex-wrap gap-2">
              {[0, 1, 2, 3, 4, 5, 6].map((d) => (
                <span key={d} className="px-2 py-1 bg-gray-100 rounded text-xs">
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
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th className="text-left py-2 px-2 font-semibold text-gray-700">From</th>
                      <th className="text-left py-2 px-2 font-semibold text-gray-700">Start</th>
                      <th className="text-left py-2 px-2 font-semibold text-gray-700">Duration</th>
                      <th className="text-left py-2 px-2 font-semibold text-gray-700">Outcome</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentCalls.slice(0, 10).map((call) => (
                      <tr key={call.call_sid} className="border-b border-gray-100 hover:bg-gray-50">
                        <td className="py-2 px-2">{call.from_number}</td>
                        <td className="py-2 px-2">
                          {call.start_iso ? new Date(call.start_iso).toLocaleString() : '—'}
                        </td>
                        <td className="py-2 px-2">
                          {call.duration_sec != null ? `${call.duration_sec}s` : '—'}
                        </td>
                        <td className="py-2 px-2">
                          <span
                            className={`px-2 py-0.5 rounded text-xs font-medium ${
                              call.outcome === 'answered_by_ai' ? 'bg-green-100 text-green-800' :
                              call.outcome === 'forwarded' ? 'bg-blue-100 text-blue-800' :
                              'bg-gray-100 text-gray-800'
                            }`}
                          >
                            {call.outcome || '—'}
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
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-3 px-4 font-semibold text-gray-700">Name</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-700">Date</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-700">Time</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-700">Reason</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-700">Status</th>
                </tr>
              </thead>
              <tbody>
                {appointments.slice(0, 10).map((appointment) => (
                  <tr key={appointment.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="py-3 px-4">{appointment.name}</td>
                    <td className="py-3 px-4">{appointment.date}</td>
                    <td className="py-3 px-4">{appointment.time}</td>
                    <td className="py-3 px-4">{appointment.reason}</td>
                    <td className="py-3 px-4">
                      <span
                        className={`px-2 py-1 rounded-full text-xs font-medium ${
                          appointment.status === 'pending'
                            ? 'bg-yellow-100 text-yellow-800'
                            : 'bg-green-100 text-green-800'
                        }`}
                      >
                        {appointment.status}
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
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-3 px-4 font-semibold text-gray-700">Caller</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-700">Phone</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-700">Message</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-700">Urgency</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-700">Status</th>
                </tr>
              </thead>
              <tbody>
                {messages.slice(0, 10).map((message) => (
                  <tr key={message.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="py-3 px-4">{message.caller_name}</td>
                    <td className="py-3 px-4">{message.caller_phone}</td>
                    <td className="py-3 px-4 max-w-md truncate">{message.message}</td>
                    <td className="py-3 px-4">
                      <span
                        className={`px-2 py-1 rounded-full text-xs font-medium ${
                          message.urgency === 'urgent'
                            ? 'bg-red-100 text-red-800'
                            : message.urgency === 'high'
                            ? 'bg-orange-100 text-orange-800'
                            : 'bg-blue-100 text-blue-800'
                        }`}
                      >
                        {message.urgency}
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      <span
                        className={`px-2 py-1 rounded-full text-xs font-medium ${
                          message.status === 'unread'
                            ? 'bg-yellow-100 text-yellow-800'
                            : 'bg-green-100 text-green-800'
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












