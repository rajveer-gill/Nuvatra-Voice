import type { ReactNode } from 'react'
import { auth } from '@clerk/nextjs/server'
import { cookies } from 'next/headers'
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
    // An admin owns no store, so /dashboard is a dead end for them — unless they
    // picked one in the admin console, which is exactly what "Open dashboard" does.
    // This runs on the server, before any client guard, so the selection has to
    // arrive as a cookie; localStorage is invisible from here. See setSelectedStoreId.
    const selectedStore = (await cookies()).get('cs_selected_store')?.value
    if (!selectedStore) {
      redirect('/admin')
    }
  }
  return (
    <>
      {children}
      <FeedbackWidget />
    </>
  )
}
