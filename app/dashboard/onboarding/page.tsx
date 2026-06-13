'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { AppChrome } from '@/components/layout/AppChrome'
import { SetupWizard, type SetupWizardStatus } from '@/components/onboarding/SetupWizard'
import { useApiClient } from '@/lib/api'

export default function OnboardingPage() {
  const api = useApiClient()
  const router = useRouter()
  const [status, setStatus] = useState<SetupWizardStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [completing, setCompleting] = useState(false)

  const load = useCallback(
    (opts?: { silent?: boolean }) => {
      if (!opts?.silent) setLoading(true)
      return api
        .get<SetupWizardStatus>('/api/setup-status')
        .then((r) => setStatus(r.data))
        .catch(() => setStatus(null))
        .finally(() => {
          if (!opts?.silent) setLoading(false)
        })
    },
    [api],
  )

  useEffect(() => {
    load()
  }, [load])

  // While the line is still being provisioned, poll quietly so the "AI phone line"
  // step flips to Live on its own without the user refreshing. Stops once live.
  const lineLive = Boolean(status?.twilio_number_set && status?.webhooks_configured)
  useEffect(() => {
    if (lineLive) return
    const id = setInterval(() => void load({ silent: true }), 15000)
    return () => clearInterval(id)
  }, [lineLive, load])

  const handleComplete = async () => {
    setCompleting(true)
    try {
      const r = await api.post<SetupWizardStatus>('/api/onboarding/complete')
      setStatus(r.data)
      router.push('/dashboard')
    } catch {
      setCompleting(false)
    }
  }

  return (
    <AppChrome>
      <main className="min-h-screen px-4 py-10 md:px-6">
        <div className="mx-auto max-w-lg">
          <div className="mb-6 flex items-center justify-between">
            <h1 className="font-display text-2xl font-semibold text-white">Setup wizard</h1>
            <Link href="/dashboard" className="text-sm text-zinc-400 hover:text-white">
              Skip to dashboard
            </Link>
          </div>
          {loading ? (
            <div className="flex justify-center py-16">
              <div className="h-10 w-10 animate-spin rounded-full border-2 border-cyan-400/30 border-t-cyan-400" />
            </div>
          ) : (
            <SetupWizard status={status} onComplete={() => void handleComplete()} completing={completing} />
          )}
        </div>
      </main>
    </AppChrome>
  )
}
