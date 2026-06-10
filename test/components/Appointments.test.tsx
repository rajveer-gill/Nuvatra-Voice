import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createApiMock, type ApiMock } from '../utils/apiMock'
import type { Appointment } from '@/components/appointments/types'

// useApiClient is mocked so the component talks to a controllable fake instead
// of a real Clerk-authenticated axios instance. vi.hoisted gives the mock
// factory a holder it can close over (the factory is hoisted above imports).
const h = vi.hoisted(() => ({ api: null as unknown as ApiMock }))
vi.mock('@/lib/api', () => ({
  useApiClient: () => h.api,
  sameOriginApiConfig: () => ({ baseURL: '' }),
  API_URL: '',
}))

import Appointments from '@/components/Appointments'

const pendingReview: Appointment = {
  id: 42,
  name: 'Jane Doe',
  email: '',
  phone: '+15551234567',
  date: '2026-06-20',
  time: '14:00',
  reason: 'Haircut',
  status: 'pending_review',
  created_at: '2026-06-10T00:00:00Z',
}

function mountWith(appointments: Appointment[]) {
  h.api = createApiMock({
    '/api/appointments': { appointments },
    '/api/business-info': { staff: [] },
  })
  return render(<Appointments />)
}

describe('Appointments accept/reject flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('accepting posts to /accept, refetches, and confirms', async () => {
    const user = userEvent.setup()
    mountWith([pendingReview])

    await user.click(await screen.findByRole('button', { name: /accept/i }))

    await waitFor(() =>
      expect(h.api.post).toHaveBeenCalledWith('/api/appointments/42/accept'),
    )
    // Initial load + post-accept refetch.
    const apptGets = h.api.get.mock.calls.filter(([url]) => url === '/api/appointments')
    expect(apptGets.length).toBeGreaterThanOrEqual(2)
    expect(await screen.findByText(/confirmation text sent/i)).toBeInTheDocument()
  })

  it('declining opens the modal and posts the typed reason to /reject', async () => {
    const user = userEvent.setup()
    mountWith([pendingReview])

    await user.click(await screen.findByRole('button', { name: /^decline$/i }))
    const reason = await screen.findByRole('textbox')
    await user.type(reason, 'Fully booked that day')
    expect((reason as HTMLTextAreaElement).value).toBe('Fully booked that day')
    const send = await screen.findByRole('button', { name: /send decline/i })
    expect(send).toBeEnabled()
    await user.click(send)

    await waitFor(() =>
      expect(h.api.post).toHaveBeenCalledWith('/api/appointments/42/reject', {
        reason: 'Fully booked that day',
      }),
    )
  })

  it('surfaces the API error detail when accept fails', async () => {
    const user = userEvent.setup()
    mountWith([pendingReview])
    h.api.post.mockRejectedValueOnce({
      response: { data: { detail: 'Slot already taken' } },
    })

    await user.click(await screen.findByRole('button', { name: /accept/i }))

    expect(await screen.findByText(/slot already taken/i)).toBeInTheDocument()
  })
})
