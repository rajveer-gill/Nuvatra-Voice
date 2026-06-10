import { describe, it, expect } from 'vitest'
import {
  canAcceptOrDecline,
  canCancelAccepted,
  needsResponse,
  isHiddenAppointmentStatus,
  appointmentDateTimeSortKey,
} from '@/components/appointments/appointmentStatus'

// Pure status logic that decides which actions each appointment offers. These
// gate the Accept/Decline/Cancel buttons, so a regression here silently changes
// what the owner can do.
describe('appointmentStatus', () => {
  it('offers accept/decline only for pending_review', () => {
    expect(canAcceptOrDecline('pending_review')).toBe(true)
    for (const s of ['pending', 'accepted', 'confirmed', 'rejected', 'cancelled', 'completed']) {
      expect(canAcceptOrDecline(s)).toBe(false)
    }
  })

  it('offers cancel only for live/booked appointments', () => {
    for (const s of ['accepted', 'confirmed', 'completed']) expect(canCancelAccepted(s)).toBe(true)
    for (const s of ['pending', 'pending_review', 'rejected', 'cancelled']) {
      expect(canCancelAccepted(s)).toBe(false)
    }
  })

  it('treats the pending family as needing a response', () => {
    for (const s of ['pending', 'pending_review', 'pending_customer']) {
      expect(needsResponse(s)).toBe(true)
    }
    for (const s of ['accepted', 'confirmed', 'rejected', 'cancelled']) {
      expect(needsResponse(s)).toBe(false)
    }
  })

  it('hides cancelled and rejected from the active list', () => {
    expect(isHiddenAppointmentStatus('cancelled')).toBe(true)
    expect(isHiddenAppointmentStatus('rejected')).toBe(true)
    expect(isHiddenAppointmentStatus('accepted')).toBe(false)
    expect(isHiddenAppointmentStatus('pending_review')).toBe(false)
  })

  it('sorts by date then time', () => {
    expect(
      appointmentDateTimeSortKey('2026-06-20', '09:00') <
        appointmentDateTimeSortKey('2026-06-20', '10:30'),
    ).toBe(true)
    expect(
      appointmentDateTimeSortKey('2026-06-19', '23:00') <
        appointmentDateTimeSortKey('2026-06-20', '01:00'),
    ).toBe(true)
  })
})
