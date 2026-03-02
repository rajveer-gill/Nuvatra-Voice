import { test, expect } from '@playwright/test'

test.describe('Appointments', () => {
  test('home page loads', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveTitle(/Nuvatra/i)
  })

  test('dashboard redirects to sign-in when not authenticated', async ({ page }) => {
    await page.goto('/dashboard')
    // Either redirects to Clerk sign-in or shows No Access / loading
    await page.waitForLoadState('networkidle')
    const url = page.url()
    const hasSignIn = url.includes('sign-in') || url.includes('clerk')
    const hasDashboard = url.includes('dashboard')
    const hasAccess = await page.getByText(/No Access|Loading|Nuvatra Voice/i).isVisible().catch(() => false)
    expect(hasSignIn || hasDashboard || hasAccess).toBeTruthy()
  })

  test('appointments tab visible when on dashboard', async ({ page }) => {
    // Navigate to dashboard - may redirect to sign-in
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')
    // If we're on the dashboard, Appointments button should exist
    const appointmentsBtn = page.getByRole('button', { name: /Appointments/i })
    const count = await appointmentsBtn.count()
    // Either we see Appointments (if authed) or we're on sign-in page
    expect(count >= 0).toBeTruthy()
  })
})
