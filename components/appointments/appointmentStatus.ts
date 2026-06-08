export const STATUS_LABELS: Record<string, string> = {
  pending: 'Needs response',
  pending_customer: 'Waiting for customer to confirm',
  pending_review: 'Needs response',
  confirmed: 'Accepted',
  accepted: 'Accepted',
  completed: 'Accepted',
  cancelled: 'Cancelled',
  rejected: 'Declined',
}

/** High-contrast pills for light backgrounds (WCAG-friendly on white cards). */
export const STATUS_CLASSES: Record<string, string> = {
  pending: 'bg-amber-200 text-amber-950',
  pending_customer: 'bg-sky-200 text-sky-950',
  pending_review: 'bg-amber-200 text-amber-950',
  confirmed: 'bg-emerald-200 text-emerald-950',
  accepted: 'bg-emerald-200 text-emerald-950',
  completed: 'bg-emerald-200 text-emerald-950',
  cancelled: 'bg-gray-200 text-gray-900',
  rejected: 'bg-red-200 text-red-950',
}

/** Only show Accept/Decline when customer has already confirmed via text (pending_review). */
export function canAcceptOrDecline(status: string): boolean {
  return status === 'pending_review'
}

/** Store can cancel confirmed bookings (frees the calendar slot). */
export function canCancelAccepted(status: string): boolean {
  return status === 'accepted' || status === 'confirmed' || status === 'completed'
}

export function needsResponse(status: string): boolean {
  return status === 'pending' || status === 'pending_review' || status === 'pending_customer'
}

/** Cancelled / declined rows are kept in a collapsed list section (not on calendar). */
export function isHiddenAppointmentStatus(status: string): boolean {
  return status === 'cancelled' || status === 'rejected'
}

export function appointmentDateTimeSortKey(date: string, time?: string | null): string {
  const d = (date || '').trim()
  const raw = (time || '00:00').trim()
  const hhmm = raw.length >= 5 ? raw.slice(0, 5) : raw.padStart(5, '0')
  return `${d}T${hhmm}`
}
