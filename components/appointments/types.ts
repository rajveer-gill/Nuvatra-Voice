export interface Appointment {
  id: number
  name: string
  email: string
  phone: string
  date: string
  time: string
  reason: string
  status: string
  created_at: string
  source?: string
  staff_id?: string | null
  owner_decline_reason?: string | null
  /** True when a dashboard accept/decline/cancel could not deliver its confirmation text. */
  confirmation_sms_failed?: boolean
  /** Set when this appointment falls on a shop closure or the stylist's time-off / off day. */
  schedule_conflict?: { type: 'shop_closed' | 'stylist_off'; label: string } | null
}
