'use client'

import dynamic from 'next/dynamic'
import { UserButton } from '@clerk/nextjs'
import { useState, useEffect } from 'react'
import Link from 'next/link'
import { useApiClient } from '@/lib/api'
import { PlanPicker } from '@/components/PlanPicker'

const Dashboard = dynamic(() => import('@/components/Dashboard'), { ssr: false })
const Appointments = dynamic(() => import('@/components/Appointments'), { ssr: false })
const Settings = dynamic(() => import('@/components/Settings'), { ssr: false })
const Leads = dynamic(() => import('@/components/Leads'), { ssr: false })

export type SubscriptionState = {
  can_use_app: boolean
  trial_ends_at: string | null
  subscription_status: string | null
  plan: string
  billing_exempt_until: string | null
  limits?: { has_lead_capture?: boolean; staff_max?: number; minutes_cap?: number; sms_automations_max?: number; has_export?: boolean }
}

export default function DashboardPage() {
  const api = useApiClient()
  const [activeTab, setActiveTab] = useState<'dashboard' | 'appointments' | 'leads' | 'settings'>('appointments')
  const [access, setAccess] = useState<'loading' | 'granted' | 'denied' | 'subscription_required'>('loading')
  const [subscription, setSubscription] = useState<SubscriptionState | null>(null)

  const fetchSubscription = () => {
    api.get<SubscriptionState>('/api/subscription')
      .then((res) => {
        if (res.data.can_use_app) {
          setAccess('granted')
        } else {
          setAccess('subscription_required')
        }
        setSubscription(res.data)
      })
      .catch((err: { response?: { status?: number } }) => {
        setAccess(err.response?.status === 401 || err.response?.status === 403 ? 'denied' : 'granted')
      })
  }

  useEffect(() => {
    let cancelled = false
    const POLL_DELAY_MS = 1500
    const MAX_POLL_ATTEMPTS = 5

    api.get<SubscriptionState>('/api/subscription')
      .then((res) => {
        if (cancelled) return
        if (res.data.can_use_app) {
          setAccess('granted')
          setSubscription(res.data)
          return
        }
        setSubscription(res.data)
        const hasSessionId = typeof window !== 'undefined' && window.location.search.includes('session_id')
        if (hasSessionId) {
          let attempts = 0
          const poll = () => {
            if (cancelled || attempts >= MAX_POLL_ATTEMPTS) {
              if (!cancelled) setAccess('subscription_required')
              return
            }
            attempts += 1
            api.get<SubscriptionState>('/api/subscription')
              .then((r) => {
                if (cancelled) return
                if (r.data.can_use_app) {
                  setAccess('granted')
                  setSubscription(r.data)
                  return
                }
                if (attempts < MAX_POLL_ATTEMPTS) setTimeout(poll, POLL_DELAY_MS)
                else setAccess('subscription_required')
              })
              .catch(() => {
                if (cancelled) return
                if (attempts < MAX_POLL_ATTEMPTS) setTimeout(poll, POLL_DELAY_MS)
                else setAccess('subscription_required')
              })
          }
          setTimeout(poll, POLL_DELAY_MS)
        } else {
          setAccess('subscription_required')
        }
      })
      .catch((err: { response?: { status?: number } }) => {
        if (!cancelled) {
          setAccess(err.response?.status === 401 || err.response?.status === 403 ? 'denied' : 'granted')
        }
      })
    return () => { cancelled = true }
  }, [api])

  if (access === 'loading') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 flex items-center justify-center">
        <div className="text-center">
          <div className="inline-block w-8 h-8 border-2 border-blue-600 border-t-transparent rounded-full animate-spin mb-4" />
          <p className="text-gray-600">Loading...</p>
        </div>
      </div>
    )
  }

  if (access === 'denied') {
    return (
      <main className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 flex items-center justify-center">
        <div className="text-center max-w-md px-6">
          <div className="bg-white rounded-2xl shadow-lg p-8">
            <div className="w-12 h-12 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-6 h-6 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">No Access</h2>
            <p className="text-gray-600 mb-6">
              Your account is not linked to an active business. If you were invited, please use the link from your invite email. If your access was removed, contact your administrator.
            </p>
            <div className="flex items-center justify-center gap-4">
              <Link href="/" className="text-blue-600 hover:underline text-sm">← Back to home</Link>
              <UserButton afterSignOutUrl="/" />
            </div>
          </div>
        </div>
      </main>
    )
  }

  if (access === 'subscription_required') {
    return (
      <main className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 flex items-center justify-center">
        <div className="container mx-auto px-4 py-8">
          <header className="flex justify-between items-center mb-8">
            <Link href="/" className="text-gray-600 hover:text-gray-900 text-sm">← nuvatrahq.com</Link>
            <UserButton afterSignOutUrl="/" />
          </header>
          <PlanPicker subscription={subscription} onSubscribed={fetchSubscription} api={api} />
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50">
      <div className="container mx-auto px-4 py-8">
        <header className="flex flex-col sm:flex-row items-center justify-between gap-4 mb-8">
          <div className="flex items-center gap-4">
            <Link href="/" className="text-gray-600 hover:text-gray-900 text-sm">← nuvatrahq.com</Link>
            <h1 className="text-2xl sm:text-4xl font-bold text-gray-900">
              Nuvatra Voice
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <UserButton afterSignOutUrl="/" />
          </div>
        </header>
        <p className="text-gray-600 text-lg mb-6">AI-Powered Voice Receptionist</p>

        {subscription?.subscription_status === 'trialing' && subscription?.trial_ends_at && (
          <div className="max-w-6xl mx-auto mb-4 px-4 py-3 bg-amber-50 border border-amber-200 rounded-lg text-center text-amber-800 text-sm">
            Your free trial ends on {new Date(subscription.trial_ends_at).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })}.
            {Math.ceil((new Date(subscription.trial_ends_at).getTime() - Date.now()) / (1000 * 60 * 60 * 24)) > 0 && (
              <> {Math.ceil((new Date(subscription.trial_ends_at).getTime() - Date.now()) / (1000 * 60 * 60 * 24))} days left.</>
            )}
          </div>
        )}

        <div className="max-w-6xl mx-auto">
          <div className="flex justify-center mb-6 flex-wrap gap-2">
            <button
              onClick={() => setActiveTab('appointments')}
              className={`px-6 py-2 rounded-lg font-medium transition-all ${
                activeTab === 'appointments'
                  ? 'bg-primary-600 text-white shadow-lg'
                  : 'bg-white text-gray-700 hover:bg-gray-100'
              }`}
            >
              Appointments
            </button>
            <button
              onClick={() => setActiveTab('dashboard')}
              className={`px-6 py-2 rounded-lg font-medium transition-all ${
                activeTab === 'dashboard'
                  ? 'bg-primary-600 text-white shadow-lg'
                  : 'bg-white text-gray-700 hover:bg-gray-100'
              }`}
            >
              Dashboard
            </button>
            {subscription?.limits?.has_lead_capture && (
              <button
                onClick={() => setActiveTab('leads')}
                className={`px-6 py-2 rounded-lg font-medium transition-all ${
                  activeTab === 'leads'
                    ? 'bg-primary-600 text-white shadow-lg'
                    : 'bg-white text-gray-700 hover:bg-gray-100'
                }`}
              >
                Leads
              </button>
            )}
            <button
              onClick={() => setActiveTab('settings')}
              className={`px-6 py-2 rounded-lg font-medium transition-all ${
                activeTab === 'settings'
                  ? 'bg-primary-600 text-white shadow-lg'
                  : 'bg-white text-gray-700 hover:bg-gray-100'
              }`}
            >
              Settings
            </button>
          </div>

          {activeTab === 'appointments' && <Appointments />}
          {activeTab === 'leads' && <Leads />}
          {activeTab === 'dashboard' && <Dashboard />}
          {activeTab === 'settings' && <Settings />}
        </div>
        <footer className="max-w-6xl mx-auto mt-12 pt-6 border-t border-gray-200 text-center text-sm text-gray-500">
          <Link href="/terms" className="hover:text-gray-700">Terms of Service</Link>
          <span className="mx-2">·</span>
          <Link href="/privacy" className="hover:text-gray-700">Privacy Policy</Link>
        </footer>
      </div>
    </main>
  )
}
