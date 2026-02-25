'use client'

import dynamic from 'next/dynamic'
import { UserButton } from '@clerk/nextjs'
import { useState, useEffect } from 'react'
import Link from 'next/link'
import { useApiClient } from '@/lib/api'

const VoiceReceptionist = dynamic(() => import('@/components/VoiceReceptionist'), { ssr: false })
const Dashboard = dynamic(() => import('@/components/Dashboard'), { ssr: false })
const Appointments = dynamic(() => import('@/components/Appointments'), { ssr: false })

export default function DashboardPage() {
  const api = useApiClient()
  const [activeTab, setActiveTab] = useState<'call' | 'dashboard' | 'appointments'>('call')
  const [access, setAccess] = useState<'loading' | 'granted' | 'denied'>('loading')

  useEffect(() => {
    let cancelled = false
    api.get('/api/business-info')
      .then(() => { if (!cancelled) setAccess('granted') })
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

        <div className="max-w-6xl mx-auto">
          <div className="flex justify-center mb-6 flex-wrap gap-2">
            <button
              onClick={() => setActiveTab('call')}
              className={`px-6 py-2 rounded-lg font-medium transition-all ${
                activeTab === 'call'
                  ? 'bg-primary-600 text-white shadow-lg'
                  : 'bg-white text-gray-700 hover:bg-gray-100'
              }`}
            >
              Voice Call
            </button>
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
          </div>

          {activeTab === 'call' && <VoiceReceptionist />}
          {activeTab === 'appointments' && <Appointments />}
          {activeTab === 'dashboard' && <Dashboard />}
        </div>
      </div>
    </main>
  )
}
