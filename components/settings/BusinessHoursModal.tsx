'use client'

import { useEffect, useId, useState } from 'react'
import { createPortal } from 'react-dom'
import { m, AnimatePresence, useReducedMotion } from 'framer-motion'
import { Clock, Copy, Sparkles, Sun, X } from 'lucide-react'
import {
  DAYS_FULL,
  DAYS_SHORT,
  type DayIndex,
  type WeeklySchedule,
  defaultWeeklySchedule,
  formatTimeLabel,
  parseHoursToWeekly,
  summarizeSchedule,
  weeklyScheduleToString,
} from '@/lib/businessHours'

function timeToMinutes(t: string): number {
  const [h, m] = t.split(':').map((x) => parseInt(x, 10))
  if (Number.isNaN(h) || Number.isNaN(m)) return -1
  return h * 60 + m
}

function cloneSchedule(s: WeeklySchedule): WeeklySchedule {
  return s.map((d) => ({ ...d }))
}

export interface BusinessHoursModalProps {
  isOpen: boolean
  onClose: () => void
  /** Current `hours` field from settings */
  hoursText: string
  /** Called with serialized hours string when user saves */
  onApply: (nextHours: string) => void
}

export function BusinessHoursModal({ isOpen, onClose, hoursText, onApply }: BusinessHoursModalProps) {
  const reduceMotion = useReducedMotion()
  const titleId = useId()
  const [mounted, setMounted] = useState(false)
  const [schedule, setSchedule] = useState<WeeklySchedule>(() => defaultWeeklySchedule())
  const [parseWarning, setParseWarning] = useState<string | null>(null)
  const [timeError, setTimeError] = useState<string | null>(null)

  useEffect(() => setMounted(true), [])

  useEffect(() => {
    if (!isOpen) return
    const r = parseHoursToWeekly(hoursText)
    setSchedule(cloneSchedule(r.schedule))
    setParseWarning(r.warning ?? null)
    setTimeError(null)
  }, [isOpen, hoursText])

  useEffect(() => {
    if (!isOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  const updateDay = (idx: DayIndex, patch: Partial<WeeklySchedule[number]>) => {
    setSchedule((prev) => {
      const next = cloneSchedule(prev)
      next[idx] = { ...next[idx], ...patch }
      return next
    })
    setTimeError(null)
  }

  const presetClassicOffice = () => {
    setSchedule(defaultWeeklySchedule())
    setParseWarning(null)
    setTimeError(null)
  }

  const presetIncludeSaturday = () => {
    const base = defaultWeeklySchedule()
    base[5] = { closed: false, open: '10:00', close: '14:00' }
    setSchedule(base)
    setParseWarning(null)
    setTimeError(null)
  }

  const preset247 = () => {
    setSchedule(
      Array.from({ length: 7 }, () => ({
        closed: false,
        open: '00:00',
        close: '23:59',
      }))
    )
    setParseWarning(null)
    setTimeError(null)
  }

  const copyMondayToWeekdays = () => {
    setSchedule((prev) => {
      const next = cloneSchedule(prev)
      const src = next[0]
      for (let i = 1; i <= 4; i++) {
        next[i] = { closed: src.closed, open: src.open, close: src.close }
      }
      return next
    })
    setTimeError(null)
  }

  const validateTimes = (): boolean => {
    for (let i = 0; i < 7; i++) {
      const d = schedule[i]
      if (d.closed) continue
      const a = timeToMinutes(d.open)
      const b = timeToMinutes(d.close)
      if (a < 0 || b < 0) {
        setTimeError(`Invalid time on ${DAYS_FULL[i]}.`)
        return false
      }
      if (b <= a) {
        setTimeError(`${DAYS_FULL[i]}: closing time must be after opening time (same day).`)
        return false
      }
    }
    setTimeError(null)
    return true
  }

  const handleSave = () => {
    if (!validateTimes()) return
    onApply(weeklyScheduleToString(schedule))
    onClose()
  }

  const dur = reduceMotion ? 0 : 0.22
  const spring = reduceMotion ? { duration: 0 } : { type: 'spring', stiffness: 380, damping: 28 }

  if (!mounted) return null

  const modal = (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-[100] flex items-end justify-center sm:items-center p-0 sm:p-4">
          <m.button
            type="button"
            aria-label="Close"
            className="absolute inset-0 bg-gray-950/60 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: dur }}
            onClick={onClose}
          />
          <m.div
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            className="relative z-[101] flex max-h-[min(92vh,880px)] w-full max-w-lg flex-col overflow-hidden rounded-t-3xl border border-gray-200/80 bg-white shadow-2xl shadow-primary-900/10 sm:rounded-3xl"
            initial={{ opacity: 0, y: reduceMotion ? 0 : 28, scale: reduceMotion ? 1 : 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: reduceMotion ? 0 : 16, scale: reduceMotion ? 1 : 0.98 }}
            transition={spring}
          >
            <div className="relative overflow-hidden bg-gradient-to-br from-primary-600 via-primary-600 to-cyan-600 px-6 pb-10 pt-6 text-white">
              <div className="pointer-events-none absolute -right-16 -top-24 h-48 w-48 rounded-full bg-white/15 blur-3xl" />
              <div className="pointer-events-none absolute -bottom-20 -left-10 h-40 w-40 rounded-full bg-cyan-300/20 blur-3xl" />
              <div className="relative flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white/20 backdrop-blur-sm">
                    <Clock className="h-6 w-6 text-white" aria-hidden />
                  </div>
                  <div>
                    <h2 id={titleId} className="font-display text-xl font-semibold tracking-tight">
                      Business hours
                    </h2>
                    <p className="mt-0.5 text-sm text-white/85">
                      Toggle days, set open and close — your receptionist reads this on calls and texts.
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  className="rounded-xl p-2 text-white/90 transition hover:bg-white/15 hover:text-white"
                  aria-label="Close dialog"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
            </div>

            <div className="-mt-6 flex flex-1 flex-col overflow-hidden rounded-t-3xl bg-white px-4 pb-4 pt-2 sm:px-6">
              {parseWarning && (
                <m.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"
                >
                  {parseWarning}
                </m.div>
              )}

              <div className="mb-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={presetClassicOffice}
                  className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-800 transition hover:border-primary-300 hover:bg-primary-50"
                >
                  <Sparkles className="h-3.5 w-3.5 text-primary-600" />
                  Mon–Fri 9–5
                </button>
                <button
                  type="button"
                  onClick={presetIncludeSaturday}
                  className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-800 transition hover:border-primary-300 hover:bg-primary-50"
                >
                  + Sat hours
                </button>
                <button
                  type="button"
                  onClick={preset247}
                  className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-800 transition hover:border-primary-300 hover:bg-primary-50"
                >
                  <Sun className="h-3.5 w-3.5 text-amber-500" />
                  24/7
                </button>
                <button
                  type="button"
                  onClick={copyMondayToWeekdays}
                  className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-800 transition hover:border-primary-300 hover:bg-primary-50"
                >
                  <Copy className="h-3.5 w-3.5 text-gray-600" />
                  Copy Mon → weekdays
                </button>
              </div>

              <div className="min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-contain pb-2 pr-1 pt-1 [-webkit-overflow-scrolling:touch]">
                {DAYS_FULL.map((label, idx) => {
                  const i = idx as DayIndex
                  const row = schedule[i]
                  return (
                    <m.div
                      key={label}
                      initial={reduceMotion ? false : { opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: reduceMotion ? 0 : idx * 0.035, duration: dur }}
                      className="rounded-2xl border border-gray-100 bg-gradient-to-b from-gray-50/90 to-white p-3 shadow-sm"
                    >
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                        <div className="flex items-center justify-between gap-3 sm:justify-start">
                          <span className="min-w-[100px] text-sm font-semibold text-gray-900">{label}</span>
                          <div
                            className="inline-flex shrink-0 rounded-full border border-gray-200 bg-white p-0.5 shadow-inner"
                            role="group"
                            aria-label={`${DAYS_SHORT[i]} open or closed`}
                          >
                            <button
                              type="button"
                              onClick={() => updateDay(i, { closed: false })}
                              className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${
                                !row.closed
                                  ? 'bg-primary-600 text-white shadow-sm'
                                  : 'text-gray-600 hover:text-gray-900'
                              }`}
                            >
                              Open
                            </button>
                            <button
                              type="button"
                              onClick={() => updateDay(i, { closed: true })}
                              className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${
                                row.closed
                                  ? 'bg-gray-800 text-white shadow-sm'
                                  : 'text-gray-600 hover:text-gray-900'
                              }`}
                            >
                              Closed
                            </button>
                          </div>
                        </div>
                        {!row.closed && (
                          <div className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-center sm:justify-end">
                            <label className="flex flex-1 flex-col gap-1 sm:max-w-[140px]">
                              <span className="text-[10px] font-medium uppercase tracking-wide text-gray-500">
                                Opens
                              </span>
                              <input
                                type="time"
                                value={row.open}
                                step={300}
                                onChange={(e) => updateDay(i, { open: e.target.value })}
                                className="cs-field w-full font-mono text-sm"
                              />
                              <span className="text-[10px] text-gray-500">{formatTimeLabel(row.open)}</span>
                            </label>
                            <label className="flex flex-1 flex-col gap-1 sm:max-w-[140px]">
                              <span className="text-[10px] font-medium uppercase tracking-wide text-gray-500">
                                Closes
                              </span>
                              <input
                                type="time"
                                value={row.close}
                                step={300}
                                onChange={(e) => updateDay(i, { close: e.target.value })}
                                className="cs-field w-full font-mono text-sm"
                              />
                              <span className="text-[10px] text-gray-500">{formatTimeLabel(row.close)}</span>
                            </label>
                          </div>
                        )}
                      </div>
                    </m.div>
                  )
                })}
              </div>

              {timeError && (
                <p className="mt-2 text-center text-xs font-medium text-red-600" role="alert">
                  {timeError}
                </p>
              )}

              <div className="mt-3 rounded-xl border border-gray-100 bg-gray-50 px-3 py-2 text-xs text-gray-600">
                <span className="font-medium text-gray-700">Preview </span>
                {summarizeSchedule(schedule, 220)}
              </div>

              <div className="mt-4 flex flex-col-reverse gap-2 border-t border-gray-100 pt-4 sm:flex-row sm:justify-end">
                <button
                  type="button"
                  onClick={onClose}
                  className="rounded-xl px-4 py-2.5 text-sm font-medium text-gray-700 transition hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSave}
                  className="rounded-xl bg-primary-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-primary-600/25 transition hover:bg-primary-700"
                >
                  Apply hours
                </button>
              </div>
            </div>
          </m.div>
        </div>
      )}
    </AnimatePresence>
  )

  return createPortal(modal, document.body)
}
