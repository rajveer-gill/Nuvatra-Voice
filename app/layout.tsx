import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Nuvatra Voice - AI Receptionist',
  description: 'AI-powered voice receptionist for businesses',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}






