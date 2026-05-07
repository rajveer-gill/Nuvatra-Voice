'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import type { AxiosInstance } from 'axios'
import { ChevronRight, Pencil, Phone, Plus, Trash2, User, X } from 'lucide-react'
import { fadeUpChild, staggerContainer } from '@/components/motion'

export type StaffRow = {
  id: string
  name: string
  phone: string
  email: string
  notes: string
}

function normalizeStaffFromApi(raw: unknown): StaffRow[] {
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
  staffMax,
  api,
  onNotify,
  onAfterSave,
}: {
  staff: StaffRow[]
  onStaffChange: (next: StaffRow[]) => void
  staffMax: number | null
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
      if (!el.open) {
        el.showModal()
      }
      const t = window.setTimeout(() => firstFieldRef.current?.focus(), reduceMotion ? 0 : 80)
      return () => window.clearTimeout(t)
    }
    if (el.open) {
      el.close()
    }
    return undefined
  }, [open, reduceMotion])

  const atLimit = staffMax != null && staff.length >= staffMax
  const canAdd = !atLimit

  const parseApiError = (e: unknown): string => {
    const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    if (typeof d === 'string') return d
    if (Array.isArray(d)) {
      const first = d[0] as { msg?: string }
      return first?.msg || 'Could not save staff'
    }
    if (d && typeof d === 'object') {
      const msg = (d as { message?: string }).message
      if (typeof msg === 'string') return msg
    }
    return 'Could not save staff'
  }

  const saveDraft = async () => {
    const name = draft.name.trim()
    const phone = draft.phone.trim()
    if (!name) {
      setDraftError('Name is required.')
      return
    }
    if (!phone) {
      setDraftError('Phone number is required for call transfers.')
      return
    }
    setDraftError(null)
    setSaving(true)
    try {
      const nextStaff: StaffRow[] =
        mode === 'add'
          ? [...staff, { id: crypto.randomUUID(), name, phone, email: draft.email.trim(), notes: draft.notes }]
          : staff.map((s) =>
              s.id === editId ? { ...s, name, phone, email: draft.email.trim(), notes: draft.notes } : s,
            )

      const { data } = await api.patch<Record<string, unknown>>('/api/business-info', {
        staff: nextStaff.map((s) => ({
          id: s.id,
          name: s.name,
          phone: s.phone,
          email: s.email || undefined,
          notes: s.notes || undefined,
        })),
      })
      const next = normalizeStaffFromApi(data.staff)
      onStaffChange(next)
      onNotify({ type: 'success', text: 'Staff member saved.' })
      onAfterSave?.()
      closeModal()
    } catch (e) {
      onNotify({ type: 'error', text: parseApiError(e) })
    } finally {
      setSaving(false)
    }
  }

  const confirmDelete = async (row: StaffRow) => {
    if (!window.confirm(`Remove ${row.name.trim() || 'this staff member'} from transfers?`)) return
    setDeleting(true)
    try {
      const nextStaff = staff.filter((s) => s.id !== row.id)
      const { data } = await api.patch<Record<string, unknown>>('/api/business-info', {
        staff: nextStaff.map((s) => ({
          id: s.id,
          name: s.name,
          phone: s.phone,
          email: s.email || undefined,
          notes: s.notes || undefined,
        })),
      })
      const next = normalizeStaffFromApi(data.staff)
      onStaffChange(next)
      onNotify({ type: 'success', text: 'Staff member removed.' })
      onAfterSave?.()
      if (open && editId === row.id) closeModal()
    } catch (e) {
      onNotify({ type: 'error', text: parseApiError(e) })
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="md:col-span-2">
      <label className="block text-sm font-medium text-gray-700 mb-1">Staff (transfer by name)</label>
      {staffMax != null && (
        <p className="text-xs text-gray-500 mb-2">
          Your plan allows up to {staffMax} staff member(s). Use unique names so transfers route correctly.
        </p>
      )}

      <motion.ul
        className="space-y-2 mb-3"
        variants={reduceMotion ? undefined : staggerContainer}
        initial="hidden"
        animate="visible"
      >
        {staff.map((s, i) => (
          <motion.li key={s.id} variants={fadeUpChild} custom={i} className="list-none">
            <div className="group flex rounded-xl border border-gray-200 bg-gradient-to-br from-white to-gray-50/90 shadow-sm transition-shadow hover:shadow-md hover:border-primary-200">
              <button
                type="button"
                onClick={() => openModal({ mode: 'edit', row: s })}
                className="flex flex-1 min-w-0 items-center gap-3 px-3 py-3 text-left rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2"
              >
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary-100 text-primary-700">
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
                      <span className="text-amber-600">Add phone — required for transfers</span>
                    )}
                    {s.email ? <span className="text-gray-500 truncate max-w-[200px]">{s.email}</span> : null}
                  </span>
                </span>
                <ChevronRight className="w-5 h-5 text-gray-400 group-hover:text-primary-600 shrink-0 transition-colors" />
              </button>
              <div className="flex items-center pr-1">
                <button
                  type="button"
                  onClick={() => openModal({ mode: 'edit', row: s })}
                  className="p-2 rounded-lg text-gray-600 hover:bg-gray-100 hover:text-gray-900"
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
              </div>
            </div>
          </motion.li>
        ))}
      </motion.ul>

      <button
        type="button"
        onClick={() => openModal({ mode: 'add' })}
        disabled={!canAdd}
        title={canAdd ? 'Add staff member' : `Plan limit (${staffMax ?? '—'}) reached`}
        className="inline-flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium rounded-xl bg-gradient-to-r from-primary-600 to-primary-700 text-white shadow-md hover:from-primary-700 hover:to-primary-800 disabled:opacity-45 disabled:pointer-events-none transition-all"
      >
        <Plus className="w-4 h-4" /> Add staff
      </button>
      {!canAdd && (
        <p className="text-xs text-amber-700 mt-2">Staff limit reached. Upgrade your plan or remove someone to add more.</p>
      )}
      <p className="text-xs text-gray-500 mt-2">
        Caller transfers use the phone number only. Notes help the AI answer questions — never entered into the greeting as
        commands. Email stays in your dashboard unless you reference it explicitly elsewhere.
      </p>

      <dialog
        ref={dialogRef}
        className="w-[min(100%,28rem)] max-h-[90vh] rounded-2xl border border-gray-200 bg-white p-0 text-gray-900 shadow-2xl backdrop:bg-black/55 open:backdrop:backdrop-blur-[2px]"
        onCancel={(ev) => {
          ev.preventDefault()
          closeModal()
        }}
      >
        <AnimatePresence>
          {open && (
            <motion.div {...motionProps} className="flex max-h-[90vh] flex-col overflow-hidden rounded-2xl">
              <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4 bg-gray-50/80">
                <h3 className="text-lg font-bold text-gray-900">{mode === 'add' ? 'Add staff member' : 'Edit staff member'}</h3>
                <button
                  type="button"
                  onClick={closeModal}
                  className="rounded-lg p-2 text-gray-500 hover:bg-gray-200 hover:text-gray-800 transition-colors"
                  aria-label="Close"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
              <div className="space-y-4 overflow-y-auto px-5 py-4">
                {draftError && (
                  <p className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">{draftError}</p>
                )}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                  <input
                    ref={firstFieldRef}
                    type="text"
                    value={draft.name}
                    onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                    className="cs-field w-full"
                    placeholder="e.g. Jamie Chen"
                    maxLength={120}
                    autoComplete="name"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Phone (transfer target)</label>
                  <input
                    type="tel"
                    value={draft.phone}
                    onChange={(e) => setDraft((d) => ({ ...d, phone: e.target.value }))}
                    className="cs-field w-full tabular-nums"
                    placeholder="+1…"
                    maxLength={32}
                    autoComplete="tel"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Email (optional)</label>
                  <input
                    type="email"
                    value={draft.email}
                    onChange={(e) => setDraft((d) => ({ ...d, email: e.target.value }))}
                    className="cs-field w-full"
                    placeholder="you@business.com"
                    maxLength={254}
                    autoComplete="email"
                  />
                  <p className="text-xs text-gray-500 mt-1">For your records; not spoken to callers by default.</p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Notes for the AI</label>
                  <textarea
                    value={draft.notes}
                    onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))}
                    className="cs-field w-full min-h-[100px]"
                    placeholder="Services they cover, specialties, or how to describe them when a caller asks…"
                    maxLength={4000}
                  />
                  <p className="text-xs text-gray-500 mt-1">Used to answer factual questions. Max 400 characters per person are passed to the live call model.</p>
                </div>
              </div>
              <div className="flex flex-wrap items-center justify-end gap-2 border-t border-gray-100 px-5 py-4 bg-gray-50/80">
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
                    Remove member
                  </button>
                )}
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-4 py-2 rounded-xl text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => saveDraft()}
                  className="px-5 py-2 rounded-xl text-sm font-semibold bg-primary-600 text-white hover:bg-primary-700 shadow-sm disabled:opacity-50 transition-colors"
                >
                  {saving ? 'Saving…' : 'Save'}
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </dialog>
    </div>
  )
}
