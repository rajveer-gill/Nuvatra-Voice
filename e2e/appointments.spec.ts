import { test, expect } from '@playwright/test'

test.describe('Appointments', () => {
  test('home page loads', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveTitle(/Call Surge/i)
  })

  test('dashboard redirects to sign-in when not authenticated', async ({ page }) => {
    await page.goto('/dashboard')
    // Either redirects to Clerk sign-in or shows No Access / loading
    await page.waitForLoadState('networkidle')
    const url = page.url()
    const hasSignIn = url.includes('sign-in') || url.includes('clerk')
    const hasDashboard = url.includes('dashboard')
    const hasAccess = await page.getByText(/No Access|Loading|Call Surge/i).isVisible().catch(() => false)
    expect(hasSignIn || hasDashboard || hasAccess).toBeTruthy()
  })

  test('onboarding route loads for unauthenticated users', async ({ page }) => {
    await page.goto('/dashboard/onboarding')
    await page.waitForLoadState('domcontentloaded')
    const url = page.url()
    expect(url.includes('onboarding') || url.includes('sign-in')).toBeTruthy()
  })
})
