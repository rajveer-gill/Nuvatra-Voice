'use client'

import { useState, useEffect, Fragment } from 'react'
import { Users, Send, Loader2 } from 'lucide-react'
import { motion, useReducedMotion } from 'framer-motion'
import { useApiClient } from '@/lib/api'
import { Skeleton } from '@/components/ui/Skeleton'
import { EmptyState } from '@/components/ui/EmptyState'
import { LockedFeature } from '@/components/ui/LockedFeature'
import { Reveal } from '@/components/motion'

interface Lead {
  id: number
  name: string
  phone: string
  reason: string
  source: string
  created_at: string
}

export default function Leads({ locked = false }: { locked?: boolean }) {
  const api = useApiClient()
  const reduce = useReducedMotion()
  const [leads, setLeads] = useState<Lead[]>([])
  const [loading, setLoading] = useState(true)
  const [textingId, setTextingId] = useState<number | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [text, setText] = useState('')
  const [note, setNote] = useState<{ id: number; text: string; ok: boolean } | null>(null)

  useEffect(() => {
    if (locked) {
      setLoading(false)
      return
    }
    api
      .get('/api/leads')
      .then((res) => setLeads(res.data?.leads || []))
      .catch(() => setLeads([]))
      .finally(() => setLoading(false))
  }, [api, locked])

  if (locked) {
    return (
      <LockedFeature
        title="Capture every lead"
        tagline="When a caller is interested but doesn't book, Call Surge saves them here so you can follow up with one tap—and never lose a potential customer to a missed call again."
        bullets={[
          'Automatically captures callers who didn’t book',
          'One-tap follow-up text to win them back',
          'See who called, when, and why',
        ]}
      />
    )
  }

  const sendText = async (id: number) => {
    const body = text.trim()
    if (!body) return
    setBusyId(id)
    setNote(null)
    try {
      const res = await api.post(`/api/leads/${id}/text`, { text: body })
      const ok = res?.data?.text_sms_sent !== false
      setNote({ id, ok, text: ok ? 'Text sent.' : "Couldn't send the text — try calling the lead instead." })
      setTextingId(null)
      setText('')
      setTimeout(() => setNote(null), ok ? 4000 : 8000)
    } catch (error) {
      console.error('Failed to text lead', error)
      setNote({ id, ok: false, text: 'Failed to send text.' })
      setTimeout(() => setNote(null), 6000)
    } finally {
      setBusyId(null)
    }
  }

  if (loading) {
    return (
      <div className="rounded-lg bg-white p-6 shadow-md">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="mt-3 h-4 w-72" />
        <div className="mt-5 space-y-2">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <Reveal className="rounded-lg bg-white p-6 text-gray-900 shadow-md">
      <h2 className="text-xl font-bold text-gray-900 mb-4 flex items-center">
        <Users className="w-5 h-5 mr-2 text-primary-600" />
        Leads
      </h2>
      <p className="text-gray-600 text-sm mb-4">People who reached out but did not book an appointment.</p>
      {leads.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No leads yet"
          description="People who reach out but don't book will be captured here so you can follow up with a text."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left py-3 px-4 font-semibold text-gray-800">Name</th>
                <th className="text-left py-3 px-4 font-semibold text-gray-800">Phone</th>
                <th className="text-left py-3 px-4 font-semibold text-gray-800">Reason / Message</th>
                <th className="text-left py-3 px-4 font-semibold text-gray-800">Source</th>
                <th className="text-left py-3 px-4 font-semibold text-gray-800">Date</th>
                <th className="text-right py-3 px-4 font-semibold text-gray-800">Actions</th>
              </tr>
            </thead>
            <motion.tbody
              initial={reduce ? false : 'hidden'}
              animate="visible"
              variants={{ visible: { transition: { staggerChildren: 0.04, delayChildren: 0.05 } } }}
            >
              {leads.map((lead) => {
                const busy = busyId === lead.id
                return (
                  <Fragment key={lead.id}>
                    <motion.tr
                      variants={{ hidden: { opacity: 0 }, visible: { opacity: 1 } }}
                      transition={{ duration: 0.3, ease: 'easeOut' }}
                      className="border-b border-gray-200 hover:bg-gray-50"
                    >
                      <td className="py-3 px-4 font-medium">{lead.name || '—'}</td>
                      <td className="py-3 px-4">{lead.phone}</td>
                      <td className="max-w-xs truncate py-3 px-4">{lead.reason || '—'}</td>
                      <td className="py-3 px-4">
                        <span className="rounded bg-gray-200 px-2 py-0.5 text-xs font-semibold text-gray-900">
                          {lead.source}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-sm text-gray-800">
                        {lead.created_at ? new Date(lead.created_at).toLocaleDateString() : '—'}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <button
                          type="button"
                          disabled={busy || !lead.phone}
                          title={lead.phone ? 'Send a follow-up text' : 'No phone number to text'}
                          onClick={() => {
                            setTextingId(textingId === lead.id ? null : lead.id)
                            setText('')
                            setNote(null)
                          }}
                          className="inline-flex items-center gap-1 rounded-lg bg-gradient-to-r from-cyan-500 to-indigo-600 px-2.5 py-1.5 text-xs font-semibold text-white shadow disabled:opacity-50"
                        >
                          <Send className="h-3.5 w-3.5" />
                          Text
                        </button>
                      </td>
                    </motion.tr>
                    {(textingId === lead.id || note?.id === lead.id) && (
                      <tr className="border-b border-gray-200 bg-gray-50">
                        <td colSpan={6} className="px-4 py-3">
                          {textingId === lead.id && (
                            <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                              <label className="flex-1">
                                <span className="mb-1 block text-xs font-medium text-gray-600">
                                  Follow-up text to {lead.phone}
                                </span>
                                <textarea
                                  value={text}
                                  onChange={(e) => setText(e.target.value)}
                                  rows={2}
                                  maxLength={1000}
                                  placeholder="e.g. Hi! Thanks for reaching out — want to book a time?"
                                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                                />
                              </label>
                              <button
                                type="button"
                                disabled={busy || !text.trim()}
                                onClick={() => sendText(lead.id)}
                                className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-gradient-to-r from-cyan-500 to-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow disabled:opacity-50"
                              >
                                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                                Send text
                              </button>
                            </div>
                          )}
                          {note?.id === lead.id && (
                            <p className={`mt-1 text-xs font-medium ${note.ok ? 'text-emerald-600' : 'text-red-600'}`}>
                              {note.text}
                            </p>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </motion.tbody>
          </table>
        </div>
      )}
    </Reveal>
  )
}
