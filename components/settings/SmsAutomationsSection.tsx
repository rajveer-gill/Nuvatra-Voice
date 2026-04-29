'use client'

import { useState } from 'react'
import { MessageSquare, Plus, Trash2 } from 'lucide-react'
import { useApiClient } from '@/lib/api'

export function SmsAutomationsSection({
  automations,
  smsAutomationsMax,
  onRefresh,
  onAdd,
  api,
}: {
  automations: { id: number; trigger: string; template: string; enabled: boolean }[]
  smsAutomationsMax: number
  onRefresh: () => void
  onAdd: (a: { id: number; trigger: string; template: string; enabled: boolean }) => void
  api: ReturnType<typeof useApiClient>
}) {
  const [newTrigger, setNewTrigger] = useState<'after_inquiry' | 'post_call'>('after_inquiry')
  const [newTemplate, setNewTemplate] = useState('')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const handleAdd = async () => {
    if (!newTemplate.trim()) return
    setSaving(true)
    setMsg(null)
    try {
      const { data } = await api.post('/api/sms-automations', { trigger: newTrigger, template: newTemplate.trim() })
      setNewTemplate('')
      if (data?.id) {
        onAdd({ id: data.id, trigger: data.trigger || newTrigger, template: data.template || '', enabled: true })
      }
      onRefresh()
      setMsg({ type: 'success', text: 'Automation added' })
    } catch {
      setMsg({ type: 'error', text: 'Failed to add automation (plan limit or error)' })
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: number) => {
    try {
      await api.delete(`/api/sms-automations/${id}`)
      onRefresh()
    } catch {
      setMsg({ type: 'error', text: 'Failed to delete' })
    }
  }

  return (
    <div className="bg-white rounded-2xl shadow-xl p-8">
      <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2 mb-6">
        <MessageSquare className="w-6 h-6 text-primary-600" />
        SMS Automations
      </h2>
      <p className="text-gray-600 text-sm mb-2">
        Auto-send a follow-up text when someone inquires but doesn&apos;t book, or after a call. Use {'{business_name}'} in the template.
      </p>
      <p className="text-xs text-gray-500 mb-4">Your plan allows {smsAutomationsMax} automation(s). Growth: 2, Pro: unlimited.</p>

      <h3 className="text-sm font-semibold text-gray-700 mb-2">
        Your automations {automations.length > 0 ? `(${automations.length})` : ''}
      </h3>
      {automations.length === 0 ? (
        <p className="text-sm text-gray-500 mb-4 py-2">No automations yet. Add one below to get started.</p>
      ) : (
        <ul className="space-y-3 mb-6">
          {automations.map((a) => (
            <li key={a.id} className="flex items-start gap-3 p-4 bg-gray-50 rounded-lg border border-gray-100">
              <div className="flex-1 min-w-0">
                <span className="text-xs font-medium text-primary-600 uppercase tracking-wide">
                  {a.trigger.replace(/_/g, ' ')}
                </span>
                <p className="text-sm text-gray-800 mt-1 break-words">{a.template}</p>
              </div>
              <button
                type="button"
                onClick={() => handleDelete(a.id)}
                className="p-2 text-red-600 hover:bg-red-50 rounded-lg shrink-0"
                title="Remove automation"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {automations.length < smsAutomationsMax && (
        <div className="mt-4 space-y-2">
          <select
            value={newTrigger}
            onChange={(e) => setNewTrigger(e.target.value as 'after_inquiry' | 'post_call')}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
          >
            <option value="after_inquiry">After inquiry (no booking)</option>
            <option value="post_call">Post call</option>
          </select>
          <input
            type="text"
            value={newTemplate}
            onChange={(e) => setNewTemplate(e.target.value)}
            placeholder="e.g. Thanks for reaching out! Here's our menu: {business_name}"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
          />
          <button
            type="button"
            onClick={handleAdd}
            disabled={saving || !newTemplate.trim()}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
          >
            <Plus className="w-4 h-4" /> Add automation
          </button>
        </div>
      )}
      {msg && <p className={`mt-2 text-sm ${msg.type === 'success' ? 'text-green-600' : 'text-red-600'}`}>{msg.text}</p>}
    </div>
  )
}
