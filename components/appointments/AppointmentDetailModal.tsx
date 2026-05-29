'use client'

import { motion } from 'framer-motion'
import {
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

export function AppointmentDetailModal({
  apt,
  staffLabel,
  reduceMotion,
  updatingId,
  acceptRejectMsg,
  onClose,
  onAccept,
  onDecline,
  onCancel,
}: {
  apt: Appointment
  staffLabel: string
  reduceMotion: boolean
  updatingId: number | null
  acceptRejectMsg: { id: number; msg: string; ok?: boolean } | null
  onClose: () => void
  onAccept: (id: number) => Promise<void>
  onDecline: (id: number) => void
  onCancel: (id: number) => void
}) {
  const isUpdating = updatingId === apt.id
  const showMsg = acceptRejectMsg?.id === apt.id

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={onClose}
      role="presentation"
    >
      <motion.div
        initial={reduceMotion ? false : { opacity: 0, scale: 0.92, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={reduceMotion ? undefined : { opacity: 0, scale: 0.96 }}
        transition={{ type: 'spring', stiffness: 380, damping: 28 }}
        className="w-full max-w-lg rounded-2xl border border-white/10 bg-zinc-900 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="apt-detail-title"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h3 id="apt-detail-title" className="text-lg font-semibold text-white">
              {apt.name}
            </h3>
            <span
              className={`mt-2 inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                STATUS_CLASSES[apt.status] || 'bg-zinc-700 text-zinc-200'
              }`}
            >
              {STATUS_LABELS[apt.status] || apt.status}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-zinc-400 hover:bg-white/10 hover:text-white"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <dl className="space-y-3 text-sm">
          <div className="flex items-center gap-2 text-zinc-300">
            <Phone className="h-4 w-4 shrink-0 text-cyan-500/80" />
            <dt className="sr-only">Phone</dt>
            <dd>{apt.phone || 'No phone'}</dd>
          </div>
          <div className="flex items-center gap-2 text-zinc-300">
            <Mail className="h-4 w-4 shrink-0 text-cyan-500/80" />
            <dt className="sr-only">Email</dt>
            <dd>{apt.email || 'No email'}</dd>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-zinc-200">
            <span className="inline-flex items-center gap-1.5">
              <Calendar className="h-4 w-4 text-indigo-400" />
              {apt.date}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Clock className="h-4 w-4 text-indigo-400" />
              {formatTimeHhmmToAmPm(apt.time)}
            </span>
          </div>
          {apt.reason && apt.reason !== '—' ? (
            <div>
              <dt className="text-xs font-medium text-zinc-500">Service</dt>
              <dd className="mt-0.5 text-zinc-300">{apt.reason}</dd>
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2 text-xs text-zinc-500">
            <span className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5">
              {apt.source === 'receptionist' ? 'AI Receptionist' : 'Manual'}
            </span>
            {staffLabel ? (
              <span className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5">
                {staffLabel}
              </span>
            ) : null}
          </div>
        </dl>

        <div className="mt-6 flex flex-col gap-2 border-t border-white/10 pt-4">
          {apt.status === 'pending_customer' ? (
            <p className="text-sm text-sky-300/90">Waiting for customer to text YES</p>
          ) : canAcceptOrDecline(apt.status) ? (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={isUpdating}
                onClick={() => void onAccept(apt.id)}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
              >
                {isUpdating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                Accept
              </button>
              <button
                type="button"
                disabled={isUpdating}
                onClick={() => onDecline(apt.id)}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-2.5 text-sm font-semibold text-red-200 disabled:opacity-50"
              >
                <X className="h-4 w-4" />
                Decline
              </button>
            </div>
          ) : canCancelAccepted(apt.status) ? (
            <button
              type="button"
              disabled={isUpdating}
              onClick={() => onCancel(apt.id)}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-2.5 text-sm font-semibold text-red-200 disabled:opacity-50"
            >
              {isUpdating ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}
              Cancel appointment
            </button>
          ) : (
            <p className="text-xs text-zinc-500">No actions available for this status.</p>
          )}
          {showMsg && (
            <p className={`text-xs font-medium ${acceptRejectMsg?.ok ? 'text-emerald-400' : 'text-red-400'}`}>
              {acceptRejectMsg?.msg}
            </p>
          )}
        </div>
      </motion.div>
    </motion.div>
  )
}
