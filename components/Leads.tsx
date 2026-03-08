'use client'

import { useState, useEffect } from 'react'
import { Users } from 'lucide-react'
import { useApiClient } from '@/lib/api'

interface Lead {
  id: number
  name: string
  phone: string
  reason: string
  source: string
  created_at: string
}

export default function Leads() {
  const api = useApiClient()
  const [leads, setLeads] = useState<Lead[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/api/leads')
      .then((res) => setLeads(res.data?.leads || []))
      .catch(() => setLeads([]))
      .finally(() => setLoading(false))
  }, [api])

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600" />
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg shadow-md p-6">
      <h2 className="text-xl font-bold text-gray-900 mb-4 flex items-center">
        <Users className="w-5 h-5 mr-2 text-primary-600" />
        Leads
      </h2>
      <p className="text-gray-600 text-sm mb-4">People who reached out but did not book an appointment.</p>
      {leads.length === 0 ? (
        <p className="text-gray-500 text-center py-8">No leads yet</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left py-3 px-4 font-semibold text-gray-700">Name</th>
                <th className="text-left py-3 px-4 font-semibold text-gray-700">Phone</th>
                <th className="text-left py-3 px-4 font-semibold text-gray-700">Reason / Message</th>
                <th className="text-left py-3 px-4 font-semibold text-gray-700">Source</th>
                <th className="text-left py-3 px-4 font-semibold text-gray-700">Date</th>
              </tr>
            </thead>
            <tbody>
              {leads.map((lead) => (
                <tr key={lead.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-3 px-4">{lead.name || '—'}</td>
                  <td className="py-3 px-4">{lead.phone}</td>
                  <td className="py-3 px-4 max-w-xs truncate">{lead.reason || '—'}</td>
                  <td className="py-3 px-4">
                    <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800">
                      {lead.source}
                    </span>
                  </td>
                  <td className="py-3 px-4 text-sm text-gray-600">
                    {lead.created_at ? new Date(lead.created_at).toLocaleDateString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
