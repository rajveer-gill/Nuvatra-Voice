'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import type { AxiosInstance } from 'axios'
import { Calendar, ChevronRight, Mail, Pencil, Phone, Plus, Trash2, User, X } from 'lucide-react'
import { fadeUpChild, staggerContainer } from '@/components/motion'

export type StaffRow = {
  id: string
  name: string
  phone: string
  email: string
  notes: string
}

export function normalizeStaffFromApi(raw: unknown): StaffRow[] {
  if (!Array.isArray(raw)) return []
  return raw.map((item) => {
    const o = item as Record<string, unknown>
    const id = typeof o.id === 'string' && o.id.trim() ? o.id.trim() : crypto.randomUUID()
    return {
      id,
      name: String(o.name ?? '').trim(),
      phone: String(o.phone ?? '').trim(),
      email: String(o.email ?? '').trim(),
      notes: String(o.notes ?? ''),
    }
  })
}

function maskPhone(phone: string): string {
  const d = phone.replace(/\D/g, '')
  if (d.length < 4) return phone ? '••••' : ''
  return `••••${d.slice(-4)}`
}

type Notify = (msg: { type: 'success' | 'error'; text: string } | null) => void

export function StaffMembersSection({
  staff,
  onStaffChange,
  api,
  onNotify,
  onAfterSave,
}: {
  staff: StaffRow[]
  onStaffChange: (next: StaffRow[]) => void
  api: AxiosInstance
  onNotify: Notify
  onAfterSave?: () => void
}) {
  const reduceMotion = useReducedMotion()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const firstFieldRef = useRef<HTMLInputElement>(null)

  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<'add' | 'edit'>('add')
  const [editId, setEditId] = useState<string | null>(null)
  const [draft, setDraft] = useState({ name: '', phone: '', email: '', notes: '' })
  const [draftError, setDraftError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const motionProps = reduceMotion
    ? { initial: false, animate: { opacity: 1 }, exit: { opacity: 1 } }
    : {
        initial: { opacity: 0, y: 14, scale: 0.97 },
        animate: { opacity: 1, y: 0, scale: 1 },
        exit: { opacity: 0, y: 12, scale: 0.98 },
        transition: { type: 'spring' as const, stiffness: 380, damping: 30 },
      }

  const openModal = useCallback((opts: { mode: 'add' | 'edit'; row?: StaffRow }) => {
    setDraftError(null)
    setMode(opts.mode)
    if (opts.mode === 'add') {
      setEditId(null)
      setDraft({ name: '', phone: '', email: '', notes: '' })
    } else if (opts.row) {
      setEditId(opts.row.id)
      setDraft({
        name: opts.row.name,
        phone: opts.row.phone,
        email: opts.row.email,
        notes: opts.row.notes,
      })
    }
    setOpen(true)
  }, [])

  const closeModal = useCallback(() => {
    setOpen(false)
    setEditId(null)
    setDraftError(null)
  }, [])

  useEffect(() => {
    const el = dialogRef.current
    if (!el) return
    if (open) {
      if (!el.open) el.showModal()
      const t = window.setTimeout(() => firstFieldRef.current?.focus(), reduceMotion ? 0 : 80)
      return () => window.clearTimeout(t)
    }
    if (el.open) el.close()
    return undefined
  }, [open, reduceMotion])

  const parseApiError = (e: unknown): string => {
    const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    if (typeof d === 'string') return d
    if (Array.isArray(d)) {
      const first = d[0] as { msg?: string }
      return first?.msg || 'Could not save team member'
    }
    if (d && typeof d === 'object') {
      const msg = (d as { message?: string }).message
      if (typeof msg === 'string') return msg
    }
    return 'Could not save team member'
  }

  const saveDraft = async () => {
    const name = draft.name.trim()
    if (!name) {
      setDraftError('Name is required.')
      return
    }
    setDraftError(null)
    setSaving(true)
    try {
      const nextStaff: StaffRow[] =
        mode === 'add'
          ? [
              ...staff,
              {
                id: crypto.randomUUID(),
                name,
                phone: draft.phone.trim(),
                email: draft.email.trim(),
                notes: draft.notes,
              },
            ]
          : staff.map((s) =>
              s.id === editId
                ? {
                    ...s,
                    name,
                    phone: draft.phone.trim(),
                    email: draft.email.trim(),
                    notes: draft.notes,
                  }
                : s,
            )

      const { data } = await api.patch<Record<string, unknown>>('/api/business-info', {
        staff: nextStaff.map((s) => ({
          id: s.id,
          name: s.name,
          phone: s.phone || undefined,
          email: s.email || undefined,
          notes: s.notes || undefined,
        })),
      })
      const next = normalizeStaffFromApi(data.staff)
      onStaffChange(next)
      onNotify({ type: 'success', text: 'Team member saved.' })
      onAfterSave?.()
      closeModal()
    } catch (e) {
      onNotify({ type: 'error', text: parseApiError(e) })
    } finally {
      setSaving(false)
    }
  }

  const confirmDelete = async (row: StaffRow) => {
    if (!window.confirm(`Remove ${row.name.trim() || 'this team member'} from your roster?`)) return
    setDeleting(true)
    try {
      const nextStaff = staff.filter((s) => s.id !== row.id)
      const { data } = await api.patch<Record<string, unknown>>('/api/business-info', {
        staff: nextStaff.map((s) => ({
          id: s.id,
          name: s.name,
          phone: s.phone || undefined,
          email: s.email || undefined,
          notes: s.notes || undefined,
        })),
      })
      const next = normalizeStaffFromApi(data.staff)
      onStaffChange(next)
      onNotify({ type: 'success', text: 'Team member removed.' })
      onAfterSave?.()
      if (open && editId === row.id) closeModal()
    } catch (e) {
      onNotify({ type: 'error', text: parseApiError(e) })
    } finally {
      setDeleting(false)
    }
  }

  return (
    <motion.div
      className="md:col-span-2 rounded-2xl border border-teal-200/70 bg-gradient-to-br from-teal-50/80 via-white to-emerald-50/40 p-4 sm:p-5 shadow-sm"
      initial={reduceMotion ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
    >
      <motion.div className="flex items-start gap-3 mb-4" layout>
        <motion.span
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-teal-600 to-emerald-600 text-white shadow-md"
          whileHover={reduceMotion ? {} : { rotate: 4, scale: 1.05 }}
        >
          <Calendar className="h-5 w-5" />
        </motion.span>
        <motion.div className="min-w-0 flex-1">
          <h3 className="text-base font-bold text-gray-900">Team roster (booking)</h3>
          <p className="text-sm text-gray-600 mt-1">
            Add everyone callers can book with — artists, stylists, providers. No plan limit on roster size. Phone is optional here; use{' '}
            <span className="font-medium text-violet-800">Live call transfers</span> below to route spoken transfer requests.
          </p>
          <motion.p
            className="text-xs text-teal-800 mt-2 font-medium"
            animate={reduceMotion ? {} : { opacity: [0.7, 1, 0.7] }}
            transition={{ duration: 3, repeat: Infinity }}
          >
            {staff.length} on roster
          </motion.p>
        </motion.div>
      </motion.div>

      <motion.ul
        className="space-y-2 mb-3 max-h-[min(420px,50vh)] overflow-y-auto pr-1"
        variants={reduceMotion ? undefined : staggerContainer}
        initial="hidden"
        animate="visible"
      >
        <AnimatePresence mode="popLayout">
          {staff.length === 0 ? (
            <motion.li
              key="empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="rounded-xl border border-dashed border-teal-200 bg-white/70 px-4 py-8 text-center text-sm text-gray-500"
            >
              No team members yet. Add stylists or staff so callers can book with a specific person.
            </motion.li>
          ) : (
            staff.map((s, i) => (
              <motion.li
                key={s.id}
                layout
                variants={fadeUpChild}
                custom={i}
                exit={{ opacity: 0, scale: 0.96 }}
                className="list-none"
              >
                <motion.div
                  className="group flex rounded-xl border border-teal-100 bg-white/95 shadow-sm hover:shadow-md hover:border-teal-300 transition-shadow"
                  whileHover={reduceMotion ? {} : { x: 2 }}
                >
                  <button
                    type="button"
                    onClick={() => openModal({ mode: 'edit', row: s })}
                    className="flex flex-1 min-w-0 items-center gap-3 px-3 py-3 text-left rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
                  >
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-teal-100 text-teal-800">
                      <User className="h-5 w-5" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="font-semibold text-gray-900 block truncate">{s.name || 'Unnamed'}</span>
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-gray-600 mt-0.5">
                        {s.phone ? (
                          <span className="inline-flex items-center gap-1">
                            <Phone className="w-3.5 h-3.5 shrink-0" />
                            <span>{maskPhone(s.phone)}</span>
                          </span>
                        ) : (
                          <span className="text-gray-400">No phone on file</span>
                        )}
                        {s.email ? (
                          <span className="inline-flex items-center gap-1 text-gray-500 truncate max-w-[180px]">
                            <Mail className="w-3 h-3" />
                            {s.email}
                          </span>
                        ) : null}
                      </span>
                    </span>
                    <ChevronRight className="w-5 h-5 text-gray-400 group-hover:text-teal-600 shrink-0" />
                  </button>
                  <motion.div className="flex items-center pr-1" layout>
                    <button
                      type="button"
                      onClick={() => openModal({ mode: 'edit', row: s })}
                      className="p-2 rounded-lg text-gray-600 hover:bg-teal-50"
                      title="Edit"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => confirmDelete(s)}
                      disabled={deleting}
                      className="p-2 rounded-lg text-red-600 hover:bg-red-50 disabled:opacity-40"
                      title="Remove"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </motion.div>
                </motion.div>
              </motion.li>
            ))
          )}
        </AnimatePresence>
      </motion.ul>

      <motion.button
        type="button"
        onClick={() => openModal({ mode: 'add' })}
        className="inline-flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium rounded-xl bg-gradient-to-r from-teal-600 to-emerald-600 text-white shadow-md hover:from-teal-700 hover:to-emerald-700"
        whileHover={reduceMotion ? {} : { scale: 1.02 }}
        whileTap={reduceMotion ? {} : { scale: 0.98 }}
      >
        <Plus className="w-4 h-4" /> Add team member
      </motion.button>

      <dialog
        ref={dialogRef}
        className="w-[min(100%,28rem)] max-h-[90vh] rounded-2xl border border-gray-200 bg-white p-0 text-gray-900 shadow-2xl backdrop:bg-black/55"
        onCancel={(ev) => {
          ev.preventDefault()
          closeModal()
        }}
      >
        <AnimatePresence>
          {open && (
            <motion.div {...motionProps} className="flex max-h-[90vh] flex-col overflow-hidden rounded-2xl">
              <motion.div
                className="flex items-center justify-between border-b border-teal-100 px-5 py-4 bg-gradient-to-r from-teal-50 to-emerald-50"
                layout
              >
                <h3 className="text-lg font-bold text-gray-900">
                  {mode === 'add' ? 'Add team member' : 'Edit team member'}
                </h3>
                <button type="button" onClick={closeModal} className="rounded-lg p-2 hover:bg-white/80" aria-label="Close">
                  <X className="w-5 h-5" />
                </button>
              </motion.div>
              <div className="space-y-4 overflow-y-auto px-5 py-4">
                {draftError && (
                  <p className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">{draftError}</p>
                )}
                <motion.div layout>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                  <input
                    ref={firstFieldRef}
                    type="text"
                    value={draft.name}
                    onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                    className="cs-field w-full"
                    placeholder="e.g. Alex Rivera"
                    maxLength={120}
                    autoComplete="name"
                  />
                </motion.div>
                <motion.div layout>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Phone (optional)</label>
                  <input
                    type="tel"
                    value={draft.phone}
                    onChange={(e) => setDraft((d) => ({ ...d, phone: e.target.value }))}
                    className="cs-field w-full tabular-nums"
                    placeholder="+1… for SMS approvals or linking transfers"
                    maxLength={32}
                    autoComplete="tel"
                  />
                </motion.div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Email (optional)</label>
                  <input
                    type="email"
                    value={draft.email}
                    onChange={(e) => setDraft((d) => ({ ...d, email: e.target.value }))}
                    className="cs-field w-full"
                    placeholder="you@business.com"
                    maxLength={254}
                  />
                </motion.div>
                <motion.div layout>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Notes for the AI</label>
                  <textarea
                    value={draft.notes}
                    onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))}
                    className="cs-field w-full min-h-[100px]"
                    placeholder="Services, chair, specialties — helps booking and Q&A…"
                    maxLength={4000}
                  />
                </motion.div>
              </motion.div>
              <motion.div
                className="flex flex-wrap items-center justify-end gap-2 border-t border-gray-100 px-5 py-4 bg-gray-50/80"
                layout
              >
                {mode === 'edit' && editId && (
                  <button
                    type="button"
                    disabled={deleting || saving}
                    onClick={() => {
                      const row = staff.find((x) => x.id === editId)
                      if (row) confirmDelete(row)
                    }}
                    className="mr-auto text-sm font-medium text-red-600 hover:text-red-800 disabled:opacity-40"
                  >
                    Remove
                  </button>
                )}
                <button type="button" onClick={closeModal} className="px-4 py-2 rounded-xl text-sm font-medium bg-gray-100">
                  Cancel
                </button>
                <motion.button
                  type="button"
                  disabled={saving}
                  onClick={() => saveDraft()}
                  className="px-5 py-2 rounded-xl text-sm font-semibold bg-teal-600 text-white disabled:opacity-50"
                  whileTap={reduceMotion ? {} : { scale: 0.96 }}
                >
                  {saving ? 'Saving…' : 'Save'}
                </motion.button>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      </dialog>
    </motion.div>
  )
}
