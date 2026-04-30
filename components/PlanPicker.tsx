'use client'

import { useState } from 'react'
import type { AxiosInstance } from 'axios'
import type { SubscriptionState } from '@/app/dashboard/page'

const PLANS = [
  {
    id: 'starter' as const,
    name: 'Starter',
    price: '$149',
    description: 'Essential AI receptionist',
    features: ['500 min/mo', '1 staff', '24/7 answering', 'Appointments', 'Basic call log (30 days)'],
  },
  {
    id: 'growth' as const,
    name: 'Growth',
    price: '$249',
    description: 'More capacity & features',
    features: ['1,500 min/mo', '5 staff', 'Appointment reminders', 'Lead capture', 'SMS automations (2)', 'Call log export', '90 days history'],
  },
  {
    id: 'pro' as const,
    name: 'Pro',
    price: '$399',
    description: 'Full capability & priority',
    features: ['10,000 min/mo', 'Unlimited staff', 'All Growth features', 'Full analytics', 'Dedicated support'],
  },
]

type PlanId = 'starter' | 'growth' | 'pro'

export function PlanPicker({
  subscription,
  onSubscribed,
  api,
}: {
  subscription: SubscriptionState | null
  onSubscribed: () => void
  api: AxiosInstance
}) {
  const [loading, setLoading] = useState<PlanId | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleSelectPlan = async (plan: PlanId) => {
    setError(null)
    setLoading(plan)
    try {
      const { data } = await api.post<{ url: string }>('/api/create-checkout-session', { plan })
      if (data?.url) {
        window.location.href = data.url
        return
      }
      throw new Error('No checkout URL returned')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string | { message?: string } } } }
      const msg = err.response?.data?.detail
      setError(
        typeof msg === 'string' ? msg : (msg && typeof msg === 'object' && msg.message) || 'Something went wrong'
      )
      setLoading(null)
    }
  }

  return (
    <div className="max-w-3xl mx-auto text-center">
      <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 mb-2">Choose a plan</h1>
      <p className="text-gray-600 mb-8">
        Your free trial has ended. Select a plan to continue using Call Surge.
      </p>
      {subscription?.trial_ends_at && (
        <p className="text-sm text-gray-500 mb-6">
          Trial ended. Subscribe to keep full access.
        </p>
      )}
      {error && (
        <div className="mb-6 p-4 bg-red-50 text-red-700 rounded-lg text-sm">
          {error}
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
        {PLANS.map((plan) => (
          <div
            key={plan.id}
            className="bg-white rounded-2xl shadow-lg border border-gray-200 p-6 flex flex-col"
          >
            <h3 className="text-lg font-semibold text-gray-900">{plan.name}</h3>
            <p className="text-2xl font-bold text-primary-600 mt-2">{plan.price}<span className="text-sm font-normal text-gray-500">/mo</span></p>
            <p className="text-gray-600 text-sm mt-1 mb-4">{plan.description}</p>
            <ul className="text-left text-sm text-gray-700 space-y-1.5 mb-6">
              {plan.features.map((f, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="text-green-500 mt-0.5">✓</span>
                  {f}
                </li>
              ))}
            </ul>
            <button
              onClick={() => handleSelectPlan(plan.id)}
              disabled={!!loading}
              className="mt-auto px-6 py-3 bg-primary-600 text-white rounded-lg font-medium hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading === plan.id ? 'Redirecting…' : 'Select'}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
