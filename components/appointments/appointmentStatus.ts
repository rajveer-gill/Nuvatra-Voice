export const STATUS_LABELS: Record<string, string> = {
  pending: 'Needs response',
  pending_customer: 'Waiting for customer to confirm',
  pending_review: 'Needs response',
  confirmed: 'Accepted',
  accepted: 'Accepted',
  completed: 'Accepted',
  cancelled: 'Declined',
  rejected: 'Declined',
}

export const STATUS_CLASSES: Record<string, string> = {
  pending: 'bg-amber-100 text-amber-800',
  pending_customer: 'bg-blue-100 text-blue-800',
  pending_review: 'bg-amber-100 text-amber-800',
  confirmed: 'bg-green-100 text-green-800',
  accepted: 'bg-green-100 text-green-800',
  completed: 'bg-green-100 text-green-800',
  cancelled: 'bg-gray-100 text-gray-600',
  rejected: 'bg-red-100 text-red-800',
}

/** Only show Accept/Decline when customer has already confirmed via text (pending_review). */
export function canAcceptOrDecline(status: string): boolean {
  return status === 'pending_review'
}

export function needsResponse(status: string): boolean {
  return status === 'pending' || status === 'pending_review' || status === 'pending_customer'
}
