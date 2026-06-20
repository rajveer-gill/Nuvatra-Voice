'use client'

import { useState, useEffect, useMemo, useCallback } from 'react'
import { Voicemail, Phone, Send, Loader2, Check, AlertTriangle, Clock, RefreshCw } from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useApiClient } from '@/lib/api'
import { Skeleton } from '@/components/ui/Skeleton'
import { EmptyState } from '@/components/ui/EmptyState'

interface CallerMessage {
  id: number
  caller_name: string
  caller_phone: string
  message: string
  urgency: string
  status: string
  created_at: string
}

type Filter = 'all' | 'unread' | 'urgent'

function relativeTime(iso: string): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const diff = Date.now() - then
  const min = Math.round(diff / 60000)
  if (min < 1) return 'just now'
  if (min < 60) return `${min}m ago`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.round(hr / 24)
  if (day < 7) return `${day}d ago`
  return new Date(iso).toLocaleDateString()
}

function initials(name: string, phone: string): string {
  const n = (name || '').trim()
  if (n) {
    const parts = n.split(/\s+/).filter(Boolean)
    return (parts[0]?.[0] || '').concat(parts[1]?.[0] || '').toUpperCase() || n[0].toUpperCase()
  }
  const d = (phone || '').replace(/\D/g, '')
  return d ? d.slice(-2) : '—'
}

function prettyPhone(phone: string): string {
  const d = (phone || '').replace(/\D/g, '')
  if (d.length === 11 && d.startsWith('1')) {
    return `(${d.slice(1, 4)}) ${d.slice(4, 7)}-${d.slice(7)}`
  }
  if (d.length === 10) return `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}`
  return phone || ''
}

export default function Messages() {
  const api = useApiClient()
  const reduce = useReducedMotion()
  const [messages, setMessages] = useState<CallerMessage[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [filter, setFilter] = useState<Filter>('all')
  const [replyingId, setReplyingId] = useState<number | null>(null)
  const [replyText, setReplyText] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)
  const [note, setNote] = useState<{ id: number; text: string; ok: boolean } | null>(null)

  const load = useCallback(
    (showSpinner: boolean) => {
      if (showSpinner) setRefreshing(true)
      api
        .get('/api/messages')
        .then((res) => setMessages(res.data?.messages || []))
        .catch(() => setMessages([]))
        .finally(() => {
          setLoading(false)
          setRefreshing(false)
        })
    },
    [api],
  )

  useEffect(() => {
    load(false)
  }, [load])

  const unreadCount = useMemo(() => messages.filter((m) => m.status !== 'read').length, [messages])
  const urgentCount = useMemo(
    () => messages.filter((m) => m.urgency === 'high' && m.status !== 'read').length,
    [messages],
  )

  const visible = useMemo(() => {
    if (filter === 'unread') return messages.filter((m) => m.status !== 'read')
    if (filter === 'urgent') return messages.filter((m) => m.urgency === 'high')
    return messages
  }, [messages, filter])

  const setStatus = async (id: number, read: boolean) => {
    setBusyId(id)
    // Optimistic update
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, status: read ? 'read' : 'unread' } : m)))
    try {
      await api.post(`/api/messages/${id}/read?read=${read}`)
    } catch {
      // Revert on failure
      setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, status: read ? 'unread' : 'read' } : m)))
      setNote({ id, ok: false, text: "Couldn't update — try again." })
      setTimeout(() => setNote(null), 5000)
    } finally {
      setBusyId(null)
    }
  }

  const sendReply = async (id: number) => {
    const body = replyText.trim()
    if (!body) return
    setBusyId(id)
    setNote(null)
    try {
      const res = await api.post(`/api/messages/${id}/reply`, { text: body })
      const ok = res?.data?.reply_sms_sent !== false
      setNote({ id, ok, text: ok ? 'Text sent — message resolved.' : "Couldn't send the text. Try calling instead." })
      if (ok) {
        setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, status: 'read' } : m)))
        setReplyingId(null)
        setReplyText('')
      }
      setTimeout(() => setNote(null), ok ? 4000 : 8000)
    } catch {
      setNote({ id, ok: false, text: 'Failed to send text.' })
      setTimeout(() => setNote(null), 6000)
    } finally {
      setBusyId(null)
    }
  }

  if (loading) {
    return (
      <div className="rounded-2xl bg-white p-6 shadow-md">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="mt-3 h-4 w-72" />
        <div className="mt-5 space-y-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-24 w-full rounded-xl" />
          ))}
        </div>
      </div>
    )
  }

  const filterTabs: { id: Filter; label: string; count?: number }[] = [
    { id: 'all', label: 'All', count: messages.length },
    { id: 'unread', label: 'Unread', count: unreadCount },
    { id: 'urgent', label: 'Urgent', count: urgentCount },
  ]

  return (
    <div className="rounded-2xl bg-white p-6 text-gray-900 shadow-md">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 text-white shadow-sm">
            <Voicemail className="h-5 w-5" />
          </span>
          <div>
            <h2 className="flex items-center gap-2 text-xl font-bold text-gray-900">
              Messages
              {unreadCount > 0 && (
                <span className="inline-flex items-center justify-center rounded-full bg-indigo-600 px-2 py-0.5 text-xs font-bold text-white">
                  {unreadCount} new
                </span>
              )}
            </h2>
            <p className="text-sm text-gray-500">Messages your AI receptionist took on calls — call or text them back.</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => load(true)}
          disabled={refreshing}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {messages.length > 0 && (
        <div className="mb-5 inline-flex flex-wrap gap-1 rounded-xl bg-gray-100 p-1">
          {filterTabs.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setFilter(t.id)}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                filter === t.id ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {t.label}
              {typeof t.count === 'number' && t.count > 0 && (
                <span
                  className={`rounded-full px-1.5 text-xs font-semibold ${
                    t.id === 'urgent' ? 'bg-rose-100 text-rose-700' : 'bg-indigo-100 text-indigo-700'
                  }`}
                >
                  {t.count}
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {messages.length === 0 ? (
        <EmptyState
          icon={Voicemail}
          title="No messages yet"
          description="When a caller asks for a person and your receptionist takes a message, it shows up here with their number so you can follow up."
        />
      ) : visible.length === 0 ? (
        <EmptyState icon={Check} title="All caught up" description="No messages match this filter." />
      ) : (
        <motion.ul
          className="space-y-3"
          initial={reduce ? false : 'hidden'}
          animate="visible"
          variants={{ visible: { transition: { staggerChildren: 0.04, delayChildren: 0.03 } } }}
        >
          <AnimatePresence initial={false}>
            {visible.map((m) => {
              const unread = m.status !== 'read'
              const urgent = m.urgency === 'high'
              const busy = busyId === m.id
              return (
                <motion.li
                  key={m.id}
                  layout
                  variants={{ hidden: { opacity: 0, y: 8 }, visible: { opacity: 1, y: 0 } }}
                  exit={{ opacity: 0, scale: 0.98 }}
                  className={`relative overflow-hidden rounded-xl border p-4 transition-colors ${
                    unread ? 'border-indigo-200 bg-indigo-50/40' : 'border-gray-200 bg-white'
                  }`}
                >
                  {unread && <span className="absolute left-0 top-0 h-full w-1 bg-indigo-500" aria-hidden />}
                  <div className="flex items-start gap-3">
                    <span
                      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-bold ${
                        urgent ? 'bg-rose-100 text-rose-700' : 'bg-indigo-100 text-indigo-700'
                      }`}
                    >
                      {initials(m.caller_name, m.caller_phone)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="font-semibold text-gray-900">{m.caller_name || 'Unknown caller'}</span>
                        {urgent && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2 py-0.5 text-[11px] font-semibold text-rose-700">
                            <AlertTriangle className="h-3 w-3" /> Urgent
                          </span>
                        )}
                        {unread && (
                          <span className="inline-flex items-center rounded-full bg-indigo-100 px-2 py-0.5 text-[11px] font-semibold text-indigo-700">
                            New
                          </span>
                        )}
                        <span className="inline-flex items-center gap-1 text-xs text-gray-400">
                          <Clock className="h-3 w-3" />
                          {relativeTime(m.created_at)}
                        </span>
                      </div>
                      <p className="mt-1.5 text-sm leading-relaxed text-gray-700">{m.message}</p>
                      {m.caller_phone && (
                        <a
                          href={`tel:${m.caller_phone}`}
                          className="mt-2 inline-flex items-center gap-1.5 text-sm font-medium text-indigo-600 hover:text-indigo-800"
                        >
                          <Phone className="h-3.5 w-3.5" />
                          {prettyPhone(m.caller_phone)}
                        </a>
                      )}

                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          disabled={busy || !m.caller_phone}
                          title={m.caller_phone ? 'Text the caller back' : 'No phone number to text'}
                          onClick={() => {
                            setReplyingId(replyingId === m.id ? null : m.id)
                            setReplyText('')
                            setNote(null)
                          }}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-violet-500 to-indigo-600 px-3 py-1.5 text-xs font-semibold text-white shadow disabled:opacity-50"
                        >
                          <Send className="h-3.5 w-3.5" />
                          Text back
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => setStatus(m.id, unread)}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50"
                        >
                          {busy ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Check className="h-3.5 w-3.5" />
                          )}
                          {unread ? 'Mark read' : 'Mark unread'}
                        </button>
                      </div>

                      {replyingId === m.id && (
                        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end">
                          <label className="flex-1">
                            <span className="mb-1 block text-xs font-medium text-gray-600">
                              Text {prettyPhone(m.caller_phone)}
                            </span>
                            <textarea
                              value={replyText}
                              onChange={(e) => setReplyText(e.target.value)}
                              rows={2}
                              maxLength={1000}
                              placeholder="e.g. Hi! Got your message — happy to help. When works for a callback?"
                              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                            />
                          </label>
                          <button
                            type="button"
                            disabled={busy || !replyText.trim()}
                            onClick={() => sendReply(m.id)}
                            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-gradient-to-r from-violet-500 to-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow disabled:opacity-50"
                          >
                            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                            Send
                          </button>
                        </div>
                      )}
                      {note?.id === m.id && (
                        <p className={`mt-2 text-xs font-medium ${note.ok ? 'text-emerald-600' : 'text-red-600'}`}>
                          {note.text}
                        </p>
                      )}
                    </div>
                  </div>
                </motion.li>
              )
            })}
          </AnimatePresence>
        </motion.ul>
      )}
    </div>
  )
}
