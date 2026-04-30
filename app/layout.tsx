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

export const metadata: Metadata = {
  title: 'Call Surge — AI voice receptionist for modern businesses',
  description:
    'Call Surge answers and texts for your business 24/7: bookings, lead capture, and a dashboard your team will actually use.',
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












