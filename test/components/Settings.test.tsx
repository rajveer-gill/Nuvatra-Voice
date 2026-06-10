import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createApiMock, type ApiMock } from '../utils/apiMock'

const h = vi.hoisted(() => ({ api: null as unknown as ApiMock }))
vi.mock('@/lib/api', () => ({
  useApiClient: () => h.api,
  sameOriginApiConfig: () => ({ baseURL: '' }),
  API_URL: '',
}))

import Settings from '@/components/Settings'

function mount() {
  h.api = createApiMock({
    '/api/business-info': {
      name: 'Old Salon',
      business_type: 'hair salon',
      hours: 'Mon-Fri 9-5',
      voice: 'fable',
      staff: [],
    },
    '/api/subscription': {
      can_use_app: true,
      plan: 'pro',
      limits: { staff_max: 99, transfer_max: 99, sms_automations_max: 99, has_export: true },
    },
    '/api/sms-automations': { automations: [] },
    '/api/setup-status': { complete: true },
  })
  return render(<Settings />)
}

describe('Settings save flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('saves edited business info via PATCH and confirms success', async () => {
    const user = userEvent.setup()
    mount()

    // Wait for the loaded value to populate the controlled input.
    const nameInput = (await screen.findByPlaceholderText('Your Business Name')) as HTMLInputElement
    await waitFor(() => expect(nameInput.value).toBe('Old Salon'))

    await user.clear(nameInput)
    await user.type(nameInput, 'New Salon Name')

    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() =>
      expect(h.api.patch).toHaveBeenCalledWith(
        '/api/business-info',
        expect.objectContaining({ name: 'New Salon Name' }),
      ),
    )
    expect(await screen.findByText(/settings saved/i)).toBeInTheDocument()
  })

  it('shows an error message when the save fails', async () => {
    const user = userEvent.setup()
    mount()

    const nameInput = (await screen.findByPlaceholderText('Your Business Name')) as HTMLInputElement
    await waitFor(() => expect(nameInput.value).toBe('Old Salon'))
    h.api.patch.mockRejectedValueOnce({ response: { data: { detail: 'Name is required' } } })

    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByText(/name is required/i)).toBeInTheDocument()
  })
})
