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
  /** Vertical-specific structured intake captured on the call (e.g. auto body:
   * { vehicle, insurance, damage, drivable }). Keys vary by industry. */
  intake?: Record<string, string> | null
  /** ISO timestamp set when the shop texted the customer their job is ready (auto
   * body). Drives the "✓ Customer notified" state; absence means not yet sent. */
  ready_notified_at?: string | null
}
