'use client'

import dynamic from 'next/dynamic'
import { useState } from 'react'

const VoiceReceptionist = dynamic(() => import('@/components/VoiceReceptionist'), { ssr: false })
const Dashboard = dynamic(() => import('@/components/Dashboard'), { ssr: false })
const Appointments = dynamic(() => import('@/components/Appointments'), { ssr: false })

export default function Home() {
  const [activeTab, setActiveTab] = useState<'call' | 'dashboard' | 'appointments'>('call')

  return (
    <main className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50">
      <div className="container mx-auto px-4 py-8">
        <header className="text-center mb-8">
          <h1 className="text-4xl font-bold text-gray-900 mb-2">
            Nuvatra Voice
          </h1>
          <p className="text-gray-600 text-lg">
            AI-Powered Voice Receptionist
          </p>
        </header>

        <div className="max-w-6xl mx-auto">
          {/* Tab Navigation */}
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

          {/* Content */}
          {activeTab === 'call' && <VoiceReceptionist />}
          {activeTab === 'appointments' && <Appointments />}
          {activeTab === 'dashboard' && <Dashboard />}
        </div>
      </div>
    </main>
  )
}












