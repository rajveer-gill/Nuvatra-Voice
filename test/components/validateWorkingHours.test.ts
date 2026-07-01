import { describe, expect, it } from 'vitest'
import { validateWorkingHours } from '@/components/settings/StaffMembersSection'

const SHOP = {
  mon: { start: '09:00', end: '17:00' },
  tue: { start: '09:00', end: '17:00' },
}

describe('validateWorkingHours', () => {
  it('is a no-op when shop hours are not configured', () => {
    expect(validateWorkingHours(['mon'], { mon: { start: '06:00', end: '23:00' } }, undefined)).toBeNull()
    expect(validateWorkingHours(['mon'], {}, {})).toBeNull()
  })

  it('allows blank hours (full shop hours)', () => {
    expect(validateWorkingHours(['mon'], {}, SHOP)).toBeNull()
    expect(validateWorkingHours(['mon'], { mon: { start: '', end: '' } }, SHOP)).toBeNull()
  })

  it('allows hours within the shop window', () => {
    expect(validateWorkingHours(['mon'], { mon: { start: '10:00', end: '16:00' } }, SHOP)).toBeNull()
    expect(validateWorkingHours(['mon'], { mon: { start: '09:00', end: '17:00' } }, SHOP)).toBeNull()
  })

  it('rejects a working day the shop is closed', () => {
    const err = validateWorkingHours(['mon', 'wed'], {}, SHOP)
    expect(err).toMatch(/Wed.*closed/i)
  })

  it('rejects start before shop opens', () => {
    const err = validateWorkingHours(['mon'], { mon: { start: '08:00', end: '16:00' } }, SHOP)
    expect(err).toMatch(/within shop hours/i)
  })

  it('rejects end after shop closes', () => {
    const err = validateWorkingHours(['mon'], { mon: { start: '10:00', end: '18:00' } }, SHOP)
    expect(err).toMatch(/within shop hours/i)
  })

  it('rejects end not after start', () => {
    const err = validateWorkingHours(['mon'], { mon: { start: '14:00', end: '14:00' } }, SHOP)
    expect(err).toMatch(/end time must be after/i)
  })

  it('rejects only one of start/end set', () => {
    const err = validateWorkingHours(['mon'], { mon: { start: '10:00', end: '' } }, SHOP)
    expect(err).toMatch(/both a start and end/i)
  })
})
