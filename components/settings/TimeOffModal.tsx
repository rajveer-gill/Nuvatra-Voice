'use client'

import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import type { AxiosInstance } from 'axios'
import { ChevronLeft, ChevronRight, Lock, X } from 'lucide-react'
import type { StaffRow } from '@/components/settings/StaffMembersSection'

const SHOP = '__shop__'
const WEEKDAY_LETTERS = ['S', 'M', 'T', 'W', 'T', 'F', 'S']
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

const pad = (n: number) => String(n).padStart(2, '0')
const isoOf = (y: number, m: number, d: number) => `${y}-${pad(m + 1)}-${pad(d)}`
const todayIso = () => {
  const t = new Date()
  return isoOf(t.getFullYear(), t.getMonth(), t.getDate())
}
const prettyDay = (iso: string) => {
  const [y, m, d] = iso.split('-').map(Number)
  return `${MONTHS[m - 1].slice(0, 3)} ${d}, ${y}`
}

type Notify = (msg: { type: 'success' | 'error'; text: string } | null) => void

export function TimeOffModal({
  open,
  onClose,
  staff,
  closures,
  api,
  onSaved,
  onNotify,
}: {
  open: boolean
  onClose: () => void
  staff: StaffRow[]
  closures: string[]
  api: AxiosInstance
  onSaved: (nextStaff: StaffRow[], nextClosures: string[]) => void
  onNotify: Notify
}) {
  const reduceMotion = useReducedMotion()
  const named = useMemo(() => staff.filter((s) => s.name.trim()), [staff])

  const [targetId, setTargetId] = useState<string>(SHOP)
  const [offByStaff, setOffByStaff] = useState<Record<string, string[]>>({})
  const [shopOff, setShopOff] = useState<string[]>([])
  const [view, setView] = useState(() => {
    const t = new Date()
    return { y: t.getFullYear(), m: t.getMonth() }
  })
  const [saving, setSaving] = useState(false)

  // Re-seed working state from props each time the modal opens.
  useEffect(() => {
    if (!open) return
    setOffByStaff(Object.fromEntries(named.map((s) => [s.id, [...(s.time_off || [])]])))
    setShopOff([...closures])
    setTargetId(named[0]?.id ?? SHOP)
    const t = new Date()
    setView({ y: t.getFullYear(), m: t.getMonth() })
  }, [open, named, closures])

  if (!open) return null

  const current = targetId === SHOP ? shopOff : offByStaff[targetId] || []
  const targetName = targetId === SHOP ? 'the shop' : named.find((s) => s.id === targetId)?.name || 'this person'

  const toggle = (iso: string) => {
    const next = current.includes(iso) ? current.filter((x) => x !== iso) : [...current, iso].sort()
    if (targetId === SHOP) setShopOff(next)
    else setOffByStaff((prev) => ({ ...prev, [targetId]: next }))
  }

  const today = todayIso()
  const daysInMonth = new Date(view.y, view.m + 1, 0).getDate()
  const firstWeekday = new Date(view.y, view.m, 1).getDay()
  const cells: (number | null)[] = [...Array(firstWeekday).fill(null), ...Array.from({ length: daysInMonth }, (_, i) => i + 1)]

  const shiftMonth = (delta: number) => {
    setView((v) => {
      const d = new Date(v.y, v.m + delta, 1)
      return { y: d.getFullYear(), m: d.getMonth() }
    })
  }

  const save = async () => {
    setSaving(true)
    try {
      const nextStaff: StaffRow[] = staff.map((s) =>
        s.name.trim() ? { ...s, time_off: (offByStaff[s.id] || []).slice().sort() } : s,
      )
      const nextClosures = shopOff.slice().sort()
      const { data } = await api.patch<Record<string, unknown>>('/api/business-info', {
        staff: nextStaff
          .filter((s) => s.name.trim())
          .map((s) => ({
            id: s.id,
            name: s.name,
            phone: s.phone || undefined,
            email: s.email || undefined,
            notes: s.notes || undefined,
            service_ids: s.service_ids.length ? s.service_ids : undefined,
            working_days: s.working_days?.length ? s.working_days : undefined,
            working_hours: s.working_hours && Object.keys(s.working_hours).length ? s.working_hours : undefined,
            time_off: s.time_off?.length ? s.time_off : undefined,
          })),
        closures: nextClosures,
      })
      const savedClosures = Array.isArray(data.closures) ? (data.closures as string[]) : nextClosures
      onSaved(nextStaff, savedClosures)
      onNotify({ type: 'success', text: 'Time off saved.' })
      onClose()
    } catch {
      onNotify({ type: 'error', text: 'Could not save time off. Try again.' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Time off"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <AnimatePresence>
        <motion.div
          initial={reduceMotion ? false : { opacity: 0, y: 12, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          className="w-[min(100%,30rem)] rounded-2xl border border-gray-200 bg-white p-5 text-gray-900 shadow-2xl"
        >
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-lg font-bold text-gray-900">Time off</h3>
            <button type="button" onClick={onClose} className="rounded-lg p-1.5 hover:bg-gray-100" aria-label="Close">
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="mb-1 text-sm font-medium text-gray-700">Who&apos;s off?</div>
          <div className="mb-4 flex flex-wrap gap-1.5">
            {named.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => setTargetId(s.id)}
                aria-pressed={targetId === s.id}
                className={`rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors ${
                  targetId === s.id ? 'border-teal-500 bg-teal-50 text-teal-700' : 'border-gray-200 text-gray-600 hover:border-gray-300'
                }`}
              >
                {s.name}
              </button>
            ))}
            <button
              type="button"
              onClick={() => setTargetId(SHOP)}
              aria-pressed={targetId === SHOP}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors ${
                targetId === SHOP ? 'border-teal-500 bg-teal-50 text-teal-700' : 'border-gray-200 text-gray-600 hover:border-gray-300'
              }`}
            >
              <Lock className="h-3.5 w-3.5" />
              Whole shop
            </button>
          </div>

          <p className="mb-3 text-sm text-gray-600">
            Tap the days <span className="font-medium text-gray-900">{targetName}</span> {targetId === SHOP ? 'is closed' : 'is off'}. Tap a day again to un-select it.
          </p>

          <div className="rounded-xl border border-gray-200 p-3">
            <div className="mb-2 flex items-center justify-between">
              <button type="button" onClick={() => shiftMonth(-1)} className="rounded-lg p-1 hover:bg-gray-100" aria-label="Previous month">
                <ChevronLeft className="h-5 w-5 text-gray-600" />
              </button>
              <span className="text-sm font-semibold text-gray-900">
                {MONTHS[view.m]} {view.y}
              </span>
              <button type="button" onClick={() => shiftMonth(1)} className="rounded-lg p-1 hover:bg-gray-100" aria-label="Next month">
                <ChevronRight className="h-5 w-5 text-gray-600" />
              </button>
            </div>
            <div className="grid grid-cols-7 gap-1 text-center">
              {WEEKDAY_LETTERS.map((w, i) => (
                <span key={i} className="py-1 text-[11px] text-gray-400">
                  {w}
                </span>
              ))}
              {cells.map((day, i) => {
                if (day === null) return <span key={`b${i}`} />
                const iso = isoOf(view.y, view.m, day)
                const selected = current.includes(iso)
                const isPast = iso < today
                return (
                  <button
                    key={iso}
                    type="button"
                    disabled={isPast}
                    onClick={() => toggle(iso)}
                    aria-pressed={selected}
                    className={`rounded-lg py-2 text-sm transition-colors ${
                      isPast
                        ? 'cursor-not-allowed text-gray-300'
                        : selected
                          ? 'bg-teal-600 font-semibold text-white'
                          : 'text-gray-800 hover:bg-gray-100'
                    }`}
                  >
                    {day}
                  </button>
                )
              })}
            </div>
          </div>

          <p className="mt-2 min-h-[18px] text-xs text-gray-500">
            {current.length ? `Off: ${current.slice().sort().map(prettyDay).join(', ')}` : 'No days selected.'}
          </p>

          <div className="mt-4 flex justify-end gap-2">
            <button type="button" onClick={onClose} className="rounded-xl bg-gray-100 px-4 py-2 text-sm font-medium">
              Cancel
            </button>
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="rounded-xl bg-teal-600 px-5 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
