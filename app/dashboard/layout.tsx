import type { ReactNode } from 'react'
import { auth } from '@clerk/nextjs/server'
import { redirect } from 'next/navigation'
import { isPlatformAdminListConfigured, isPlatformAdminUserId } from '@/lib/platform-admin'
import { FeedbackWidget } from '@/components/FeedbackWidget'

export const dynamic = 'force-dynamic'

export default async function DashboardLayout({ children }: { children: ReactNode }) {
  const { userId } = await auth()
  if (!userId) {
    redirect('/sign-in')
  }
  if (isPlatformAdminListConfigured() && isPlatformAdminUserId(userId)) {
    redirect('/admin')
  }
  return (
    <>
      {children}
      <FeedbackWidget />
    </>
  )
}
