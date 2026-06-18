'use client'

import { motion } from 'framer-motion'
import {
  AlertTriangle,
  BellRing,
  Calendar,
  Check,
  Clock,
  Loader2,
  Mail,
  Phone,
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
  canNotifyReady = false,
  notifyingId = null,
  onNotifyReady,
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
  canNotifyReady?: boolean
  notifyingId?: number | null
  onNotifyReady?: (id: number) => void
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
      className="group relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-zinc-800/90 via-zinc-900/95 to-zinc-950 p-5 shadow-lg shadow-black/20"
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
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-zinc-500">
            <span className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5">
              {apt.source === 'receptionist' ? 'AI Receptionist' : 'Manual'}
            </span>
            {staffLabel && (
              <span className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5">
                {staffLabel}
              </span>
            )}
          </div>
          {apt.intake && Object.keys(apt.intake).length > 0 && (
            <div className="flex flex-wrap gap-2 pt-0.5">
              {Object.entries(apt.intake).map(([k, v]) =>
                v ? (
                  <span
                    key={k}
                    className="inline-flex items-center gap-1 rounded-md border border-cyan-500/20 bg-cyan-500/5 px-2 py-0.5 text-xs text-cyan-100/90"
                  >
                    <span className="font-semibold text-cyan-300/90">{humanizeIntakeKey(k)}:</span>
                    <span className="text-zinc-200">{v}</span>
                  </span>
                ) : null,
              )}
            </div>
          )}
          {canNotifyReady && onNotifyReady && ACTIVE_FOR_PICKUP.has(apt.status) && (
            apt.ready_notified_at ? (
              <div className="inline-flex w-fit items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-xs font-medium text-emerald-200">
                <Check className="h-3.5 w-3.5 shrink-0" />
                Customer notified their car&rsquo;s ready · {formatNotifiedTime(apt.ready_notified_at)}
              </div>
            ) : (
              <motion.button
                type="button"
                disabled={notifyingId === apt.id || !apt.phone}
                title={!apt.phone ? 'No phone number on file for this customer' : undefined}
                whileTap={reduceMotion ? undefined : { scale: 0.96 }}
                whileHover={reduceMotion ? undefined : { scale: 1.02 }}
                onClick={() => onNotifyReady(apt.id)}
                className="inline-flex w-fit items-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 px-3.5 py-2 text-xs font-semibold text-white shadow-md shadow-cyan-500/20 transition disabled:cursor-not-allowed disabled:opacity-50"
              >
                {notifyingId === apt.id ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <BellRing className="h-3.5 w-3.5" />
                )}
                Text customer: car&rsquo;s ready
              </motion.button>
            )
          )}
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

/** Turn an intake key like "drivable" or "damage_type" into a readable label. */
function humanizeIntakeKey(key: string): string {
  const s = key.replace(/_/g, ' ').trim()
  return s.charAt(0).toUpperCase() + s.slice(1)
}

/** Statuses where a job is in the shop / done — i.e. it can become ready for pickup. */
const ACTIVE_FOR_PICKUP = new Set(['accepted', 'confirmed', 'completed'])

/** Friendly local time for the "Customer notified · 2:14 PM" state. */
function formatNotifiedTime(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

export { apiDetail }
