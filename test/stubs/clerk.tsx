/**
 * Clerk stub. Components under test only read auth via these hooks/components;
 * the api client itself is mocked separately per test, so a static signed-in
 * session is enough.
 */
import * as React from 'react'

export const useAuth = () => ({
  isLoaded: true,
  isSignedIn: true,
  userId: 'user_test',
  getToken: async () => 'test-token',
})

export const useUser = () => ({
  isLoaded: true,
  isSignedIn: true,
  user: { id: 'user_test', fullName: 'Test User' },
})

export const UserButton = () => React.createElement('div', { 'data-testid': 'user-button' })
export const ClerkProvider = ({ children }: { children?: React.ReactNode }) =>
  React.createElement(React.Fragment, null, children)
export const SignedIn = ({ children }: { children?: React.ReactNode }) =>
  React.createElement(React.Fragment, null, children)
export const SignedOut = () => null
export const RedirectToSignIn = () => null
