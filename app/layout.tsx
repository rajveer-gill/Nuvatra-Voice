import type { Metadata } from 'next'
import { ClerkProvider } from '@clerk/nextjs'
import { DM_Sans, Syne } from 'next/font/google'
import './globals.css'

const dmSans = DM_Sans({
  subsets: ['latin'],
  variable: '--font-dm-sans',
  display: 'swap',
})

const syne = Syne({
  subsets: ['latin'],
  variable: '--font-syne',
  display: 'swap',
})

const siteUrl = 'https://call-surge.com'

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: 'Call Surge — AI voice receptionist for modern businesses',
  description:
    'Call Surge answers and texts for your business 24/7: bookings, lead capture, and a dashboard your team will actually use.',
  alternates: {
    canonical: '/',
  },
  openGraph: {
    type: 'website',
    locale: 'en_US',
    url: siteUrl,
    siteName: 'Call Surge',
    title: 'Call Surge — AI voice receptionist for modern businesses',
    description:
      'Call Surge answers calls and texts like your best front desk—24/7—so leads book, buyers get answers, and nothing slips through.',
    images: [{ url: '/assets/call-surge-mark.svg', width: 512, height: 512, alt: 'Call Surge' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Call Surge — AI voice receptionist',
    description:
      'AI voice + SMS receptionist for teams who cannot afford a dropped call. Invite-only access.',
    images: ['/assets/call-surge-mark.svg'],
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <ClerkProvider>
      <html lang="en" className={`${dmSans.variable} ${syne.variable}`}>
        <body className="min-h-dvh font-sans antialiased">{children}</body>
      </html>
    </ClerkProvider>
  )
}












