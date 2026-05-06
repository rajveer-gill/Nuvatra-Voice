import { dark } from '@clerk/themes'

/** Shared Clerk `<SignIn />` / `<SignUp />` styling — matches Call Surge dark UI. */
export const clerkAppearance = {
  baseTheme: dark,
  variables: {
    colorPrimary: '#06b6d4',
    colorTextOnPrimaryBackground: '#030712',
    borderRadius: '0.75rem',
  },
  elements: {
    card: 'border border-white/10 shadow-2xl',
    footerActionLink: 'text-cyan-400 hover:text-cyan-300',
    socialButtonsBlockButton: 'border-white/15 bg-white/5 hover:bg-white/10',
  },
}
