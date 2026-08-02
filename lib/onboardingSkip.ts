'use client'

/** "Skip to dashboard" on the setup wizard.
 *
 * The dashboard sends anyone with unfinished setup to the wizard, which is right —
 * the AI can't take calls until it's done. But it made the wizard's own skip link a
 * redirect loop: skip → /dashboard → straight back to the wizard.
 *
 * Skipping records the choice for the rest of the browsing session, so the dashboard
 * lets them through. sessionStorage, not localStorage, on purpose: skipping is "not
 * right now", not "never ask again" — a fresh session should nudge them again, since
 * their receptionist genuinely isn't answering calls yet.
 */

const KEY = 'nuvatra.skippedOnboarding'

export function markOnboardingSkipped(): void {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(KEY, '1')
  } catch {
    // Private mode / storage disabled — they'll just be redirected again.
  }
}

export function hasSkippedOnboarding(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.sessionStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}
