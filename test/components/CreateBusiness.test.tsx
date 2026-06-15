import { describe, it, expect, beforeEach, vi } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createApiMock, type ApiMock } from '../utils/apiMock'

const h = vi.hoisted(() => ({ api: null as unknown as ApiMock }))
vi.mock('@/lib/api', () => ({
  useApiClient: () => h.api,
  sameOriginApiConfig: () => ({ baseURL: '' }),
  API_URL: '',
}))
// The page redirects via the router after a subscription check; a no-op router
// lets it mount and show the form (subscription mock returns can_use_app: false).
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}))
// AppChrome pulls in nav/auth shell we don't need under test — pass children through.
vi.mock('@/components/layout/AppChrome', () => ({
  AppChrome: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

import CreateBusinessPage from '@/app/dashboard/create-business/page'

function mount() {
  h.api = createApiMock({
    // No live tenant yet → render the signup form rather than redirecting away.
    '/api/subscription': { can_use_app: false },
  })
  return render(<CreateBusinessPage />)
}

const submitBtn = () =>
  screen.getByRole('button', { name: /Continue to payment/ }) as HTMLButtonElement

describe('Create business — phone number choice', () => {
  beforeEach(() => vi.clearAllMocks())

  it('defaults to a new number and hides the existing-number input', async () => {
    mount()
    // Both choices are offered.
    expect(await screen.findByRole('button', { name: /Get a new number/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Use my existing number/ })).toBeInTheDocument()
    // In "new" mode the existing-number field is not shown.
    expect(screen.queryByPlaceholderText('e.g. (415) 555-0199')).not.toBeInTheDocument()
  })

  it('reveals the existing-number input and gates submit until it is valid', async () => {
    const user = userEvent.setup()
    mount()

    const nameInput = await screen.findByPlaceholderText('e.g. Acme Salon')
    await user.type(nameInput, 'Acme Salon')

    // Choosing "existing" reveals the number field.
    await user.click(screen.getByRole('button', { name: /Use my existing number/ }))
    const existing = (await screen.findByPlaceholderText('e.g. (415) 555-0199')) as HTMLInputElement

    // Empty → submit disabled.
    expect(submitBtn()).toBeDisabled()

    // Too-short number → still disabled, with a validation hint.
    await user.type(existing, '415555')
    expect(submitBtn()).toBeDisabled()
    expect(screen.getByText(/10-digit US phone number/i)).toBeInTheDocument()

    // Full 10 digits → enabled.
    await user.type(existing, '0199')
    await waitFor(() => expect(submitBtn()).toBeEnabled())
  })

  it('sends number_mode + existing_number in the create-business payload', async () => {
    const user = userEvent.setup()
    mount()

    await user.type(await screen.findByPlaceholderText('e.g. Acme Salon'), 'Acme Salon')
    await user.click(screen.getByRole('button', { name: /Use my existing number/ }))
    await user.type(screen.getByPlaceholderText('e.g. (415) 555-0199'), '(415) 555-0199')

    await user.click(submitBtn())

    await waitFor(() =>
      expect(h.api.post).toHaveBeenCalledWith(
        '/api/onboarding/create-business',
        expect.objectContaining({
          name: 'Acme Salon',
          number_mode: 'existing',
          existing_number: '(415) 555-0199',
        }),
      ),
    )
  })

  it('does not require an existing number when keeping the default new number', async () => {
    const user = userEvent.setup()
    mount()

    await user.type(await screen.findByPlaceholderText('e.g. Acme Salon'), 'Acme Salon')
    // Untouched number choice = "new"; submit is enabled with just a name.
    await waitFor(() => expect(submitBtn()).toBeEnabled())

    await user.click(submitBtn())
    await waitFor(() =>
      expect(h.api.post).toHaveBeenCalledWith(
        '/api/onboarding/create-business',
        expect.objectContaining({ number_mode: 'new', existing_number: undefined }),
      ),
    )
  })
})
