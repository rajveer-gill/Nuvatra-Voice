'use client'

import dynamic from 'next/dynamic'
import { UserButton } from '@clerk/nextjs'
import { useState } from 'react'
import Link from 'next/link'

const VoiceReceptionist = dynamic(() => import('@/components/VoiceReceptionist'), { ssr: false })
const Dashboard = dynamic(() => import('@/components/Dashboard'), { ssr: false })
const Appointments = dynamic(() => import('@/components/Appointments'), { ssr: false })

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<'call' | 'dashboard' | 'appointments'>('call')

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
