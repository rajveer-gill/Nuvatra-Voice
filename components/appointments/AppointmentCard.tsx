'use client'

import { motion } from 'framer-motion'
import {
  AlertTriangle,
  Calendar,
  Check,
  Clock,
  Loader2,
  Mail,
  Phone,
  Scissors,
  Trash2,
  X,
} from 'lucide-react'
import { formatTimeHhmmToAmPm } from '@/lib/formatTime'
import {
  STATUS_CLASSES,
  STATUS_LABELS,
  canAcceptOrDecline,
  canCancelAccepted,
} from '@/components/appointments/appointmentStatus'
import type { Appointment } from '@/components/appointments/types'

function apiDetail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof d === 'string') return d
  return 'Something went wrong'
}

export function AppointmentCard({
  apt,
  staffLabel,
  index,
  reduceMotion,
  updatingId,
  acceptRejectMsg,
  onAccept,
  onDecline,
  onCancel,
  onDelete,
}: {
  apt: Appointment
  staffLabel: string
  index: number
  reduceMotion: boolean
  updatingId: number | null
  acceptRejectMsg: { id: number; msg: string; ok?: boolean } | null
  onAccept: (id: number) => Promise<void>
  onDecline: (id: number) => void
  onCancel: (id: number) => void
  onDelete?: (id: number) => void
}) {
  const isUpdating = updatingId === apt.id
  const showMsg = acceptRejectMsg?.id === apt.id

  return (
    <motion.article
      layout={!reduceMotion}
      initial={reduceMotion ? false : { opacity: 0, y: 24, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={reduceMotion ? undefined : { opacity: 0, scale: 0.95, transition: { duration: 0.2 } }}
      transition={{
        type: 'spring',
        stiffness: 340,
        damping: 28,
        delay: reduceMotion ? 0 : index * 0.06,
      }}
      whileHover={reduceMotion ? undefined : { y: -4, transition: { duration: 0.2 } }}
      className={`group relative overflow-hidden rounded-2xl border bg-gradient-to-br from-zinc-800/90 via-zinc-900/95 to-zinc-950 p-5 shadow-lg shadow-black/20 ${
        apt.schedule_conflict ? 'border-amber-400/60 ring-1 ring-amber-400/30' : 'border-white/10'
      }`}
    >
      <div
        className="pointer-events-none absolute -right-8 -top-8 h-32 w-32 rounded-full bg-cyan-500/10 blur-2xl transition-opacity group-hover:opacity-100 opacity-60"
        aria-hidden
      />
      <div className="relative flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold text-white">{apt.name}</h3>
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                STATUS_CLASSES[apt.status] || 'bg-zinc-700 text-zinc-200'
              }`}
            >
              {needsResponsePulse(apt.status) && (
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500" />
                </span>
              )}
              {STATUS_LABELS[apt.status] || apt.status}
            </span>
            {apt.schedule_conflict && (
              <span
                className="inline-flex items-center gap-1 rounded-full bg-amber-400/20 px-2.5 py-0.5 text-xs font-semibold text-amber-300"
                title="This appointment is on a day the stylist or shop is off. Reach out to the customer to reschedule."
              >
                <AlertTriangle className="h-3 w-3" />
                {apt.schedule_conflict.label}
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-zinc-400">
            <span className="inline-flex items-center gap-1.5">
              <Phone className="h-3.5 w-3.5 text-cyan-500/80" />
              {apt.phone || 'No phone'}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Mail className="h-3.5 w-3.5 text-cyan-500/80" />
              {apt.email || 'No email'}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="inline-flex items-center gap-1.5 font-medium text-zinc-200">
              <Calendar className="h-4 w-4 text-indigo-400" />
              {apt.date}
            </span>
            <span className="inline-flex items-center gap-1.5 text-zinc-300">
              <Clock className="h-4 w-4 text-indigo-400" />
              {formatTimeHhmmToAmPm(apt.time)}
            </span>
            {apt.reason && apt.reason !== '—' && (
              <span className="rounded-lg bg-white/5 px-2 py-0.5 text-zinc-400">{apt.reason}</span>
            )}
            {staffLabel && (
              <span className="inline-flex items-center gap-1.5 rounded-lg bg-teal-500/15 px-2.5 py-0.5 font-semibold text-teal-200 ring-1 ring-teal-500/30">
                <Scissors className="h-3.5 w-3.5" />
                {staffLabel}
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-zinc-500">
            <span className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5">
              {apt.source === 'receptionist' ? 'AI Receptionist' : 'Manual'}
            </span>
          </div>
          {apt.confirmation_sms_failed && (
            <div className="flex items-start gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1.5 text-xs font-medium text-amber-200">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>Confirmation text didn&rsquo;t send — call the customer to confirm.</span>
            </div>
          )}
        </div>

        <div className="flex shrink-0 flex-col items-stretch gap-2 sm:items-end">
          {apt.status === 'pending_customer' ? (
            <p className="max-w-[14rem] text-center text-xs text-sky-300/90 sm:text-right">
              Waiting for customer to text YES
            </p>
          ) : canAcceptOrDecline(apt.status) ? (
            <div className="flex flex-wrap gap-2 sm:justify-end">
              <motion.button
                type="button"
                disabled={isUpdating}
                whileTap={reduceMotion ? undefined : { scale: 0.94 }}
                whileHover={reduceMotion ? undefined : { scale: 1.03 }}
                onClick={() => void onAccept(apt.id)}
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-emerald-500/25 disabled:opacity-50"
              >
                {isUpdating ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Check className="h-4 w-4" />
                )}
                Accept
              </motion.button>
              <motion.button
                type="button"
                disabled={isUpdating}
                whileTap={reduceMotion ? undefined : { scale: 0.94 }}
                whileHover={reduceMotion ? undefined : { scale: 1.03 }}
                onClick={() => onDecline(apt.id)}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-2.5 text-sm font-semibold text-red-200 hover:bg-red-500/20 disabled:opacity-50"
              >
                <X className="h-4 w-4" />
                Decline
              </motion.button>
            </div>
          ) : canCancelAccepted(apt.status) ? (
            <motion.button
              type="button"
              disabled={isUpdating}
              whileTap={reduceMotion ? undefined : { scale: 0.94 }}
              whileHover={reduceMotion ? undefined : { scale: 1.03 }}
              onClick={() => onCancel(apt.id)}
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-2.5 text-sm font-semibold text-red-200 hover:bg-red-500/20 disabled:opacity-50"
            >
              {isUpdating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <X className="h-4 w-4" />
              )}
              Cancel appointment
            </motion.button>
          ) : (
            <span className="text-xs text-zinc-500">No actions</span>
          )}
          {onDelete && (
            <button
              type="button"
              disabled={isUpdating}
              onClick={() => onDelete(apt.id)}
              className="inline-flex items-center justify-center gap-1.5 self-end rounded-lg px-2 py-1 text-xs font-medium text-zinc-500 transition-colors hover:bg-red-500/10 hover:text-red-300 disabled:opacity-50"
              title="Remove this appointment from your dashboard"
              aria-label="Delete appointment"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Delete
            </button>
          )}
          {showMsg && (
            <motion.p
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className={`text-xs font-medium ${acceptRejectMsg?.ok ? 'text-emerald-400' : 'text-red-400'}`}
            >
              {acceptRejectMsg?.msg}
            </motion.p>
          )}
        </div>
      </div>
    </motion.article>
  )
}

function needsResponsePulse(status: string): boolean {
  return status === 'pending_review' || status === 'pending' || status === 'pending_customer'
}

export { apiDetail }
