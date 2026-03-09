'use client'

import { useState, useEffect, useRef } from 'react'
import { Volume2, Store, Save, Shuffle, User, Play, Square, CreditCard, Plus, Trash2, MessageSquare } from 'lucide-react'
import { useApiClient } from '@/lib/api'

const VOICES = ['nova', 'alloy', 'echo', 'fable', 'onyx', 'shimmer'] as const
const VOICE_SAMPLE_TEXT = "Hi there! Thanks for calling. How can I help you today?"

const SPEECH_SPEED_MIN = 0.25
const SPEECH_SPEED_MAX = 4
const SPEECH_SPEED_STEP = 0.05

function SmsAutomationsSection({
  automations,
  smsAutomationsMax,
  onRefresh,
  api,
}: {
  automations: { id: number; trigger: string; template: string; enabled: boolean }[]
  smsAutomationsMax: number
  onRefresh: () => void
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
      await api.post('/api/sms-automations', { trigger: newTrigger, template: newTemplate.trim() })
      setNewTemplate('')
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
        Auto-send a follow-up text when someone inquires but doesn&apos;t book. Use {'{business_name}'} in the template.
      </p>
      <p className="text-xs text-gray-500 mb-4">Your plan allows {smsAutomationsMax} automation(s). Growth: 2, Pro: unlimited.</p>
      {automations.map((a) => (
        <div key={a.id} className="flex items-start gap-2 mb-3 p-3 bg-gray-50 rounded-lg">
          <div className="flex-1">
            <span className="text-xs font-medium text-gray-500">{a.trigger.replace(/_/g, ' ')}</span>
            <p className="text-sm text-gray-800 mt-0.5">{a.template}</p>
          </div>
          <button type="button" onClick={() => handleDelete(a.id)} className="p-1.5 text-red-600 hover:bg-red-50 rounded">
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      ))}
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

const RANDOM_NAMES = [
  'Ava', 'Liam', 'Sophia', 'Noah', 'Olivia', 'Ethan', 'Mia', 'Lucas',
  'Emma', 'Mason', 'Aria', 'Logan', 'Chloe', 'James', 'Lily', 'Aiden',
  'Zoe', 'Carter', 'Nora', 'Owen', 'Ella', 'Riley', 'Luna', 'Kai',
  'Ivy', 'Leo', 'Ruby', 'Max', 'Jade', 'Finn', 'Sage', 'Quinn',
  'Sky', 'River', 'Hazel', 'Atlas', 'Willow', 'Juno', 'Nova', 'Iris',
]

export default function Settings() {
  const api = useApiClient()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [voice, setVoice] = useState<string>('fable')
  const [speechSpeed, setSpeechSpeed] = useState<number>(1.0)
  const [previewing, setPreviewing] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [receptionistName, setReceptionistName] = useState('')
  const [aiPhone, setAiPhone] = useState('')
  const [portalLoading, setPortalLoading] = useState(false)
  const [form, setForm] = useState({
    name: '',
    hours: '',
    forwarding_phone: '',
    email: '',
    address: '',
    menu_link: '',
    greeting: '',
    services: '' as string,
    specials: '' as string,
    reservation_rules: '' as string,
  })
  const [staff, setStaff] = useState<{ name: string; phone: string }[]>([])
  const [staffMax, setStaffMax] = useState<number | null>(null)
  const [automations, setAutomations] = useState<{ id: number; trigger: string; template: string; enabled: boolean }[]>([])
  const [smsAutomationsMax, setSmsAutomationsMax] = useState<number | null>(null)

  useEffect(() => {
    Promise.all([
      api.get('/api/business-info'),
      api.get('/api/subscription').catch(() => ({ data: null })),
      api.get('/api/sms-automations').catch(() => ({ data: { automations: [] } })),
    ]).then(([infoRes, subRes, automationsRes]) => {
        const d = infoRes.data
        setVoice(d.voice || 'fable')
        const limits = (subRes?.data as { limits?: { staff_max?: number; sms_automations_max?: number } } | null)?.limits
        if (limits?.staff_max != null) setStaffMax(limits.staff_max)
        if (limits?.sms_automations_max != null) setSmsAutomationsMax(limits.sms_automations_max)
        const staffArr = (d.staff || []) as { name?: string; phone?: string }[]
        setStaff(staffArr.length ? staffArr.map((x) => ({ name: x.name || '', phone: x.phone || '' })) : [])
        const spd = typeof d.speed === 'number' ? d.speed : 1.0
        setSpeechSpeed(Math.max(SPEECH_SPEED_MIN, Math.min(SPEECH_SPEED_MAX, spd)))
        setReceptionistName(d.receptionist_name || '')
        setAiPhone(d.phone || '')
        setForm({
          name: d.name || '',
          hours: d.hours || '',
          forwarding_phone: d.forwarding_phone || '',
          email: d.email || '',
          address: d.address || '',
          menu_link: d.menu_link || '',
          greeting: d.greeting || '',
          services: Array.isArray(d.services) ? d.services.join('\n') : '',
          specials: Array.isArray(d.specials) ? d.specials.join('\n') : '',
          reservation_rules: Array.isArray(d.reservation_rules) ? d.reservation_rules.join('\n') : '',
        })
      setAutomations((automationsRes?.data as { automations?: unknown[] })?.automations || [])
      })
    .catch(() => setMessage({ type: 'error', text: 'Failed to load settings' }))
    .finally(() => setLoading(false))
  }, [api])

  const randomizeName = () => {
    const current = receptionistName.trim().toLowerCase()
    let pick: string
    do {
      pick = RANDOM_NAMES[Math.floor(Math.random() * RANDOM_NAMES.length)]
    } while (pick.toLowerCase() === current && RANDOM_NAMES.length > 1)
    setReceptionistName(pick)
  }

  const previewVoice = async (v: string) => {
    if (previewing === v) {
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current = null
      }
      setPreviewing(null)
      return
    }
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    setPreviewing(v)
    try {
      const res = await api.post('/api/text-to-speech', { text: VOICE_SAMPLE_TEXT, voice: v, speed: speechSpeed }, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const audio = new Audio(url)
      audioRef.current = audio
      audio.onended = () => {
        setPreviewing(null)
        URL.revokeObjectURL(url)
        audioRef.current = null
      }
      audio.onerror = () => {
        setPreviewing(null)
        URL.revokeObjectURL(url)
        audioRef.current = null
      }
      await audio.play()
    } catch {
      setPreviewing(null)
    }
  }

  const addStaff = () => setStaff((prev) => [...prev, { name: '', phone: '' }])
  const removeStaff = (i: number) => setStaff((prev) => prev.filter((_, idx) => idx !== i))
  const updateStaff = (i: number, field: 'name' | 'phone', value: string) =>
    setStaff((prev) => prev.map((s, idx) => idx === i ? { ...s, [field]: value } : s))

  const handleSave = async () => {
    setSaving(true)
    setMessage(null)
    try {
      await api.patch('/api/business-info', {
        name: form.name || undefined,
        hours: form.hours || undefined,
        forwarding_phone: form.forwarding_phone || undefined,
        email: form.email || undefined,
        address: form.address || undefined,
        menu_link: form.menu_link || undefined,
        greeting: form.greeting || undefined,
        voice: voice || undefined,
        receptionist_name: receptionistName || undefined,
        staff: staff.filter((s) => s.name.trim() || s.phone.trim()).map((s) => ({ name: s.name, phone: s.phone })),
        services: form.services
          ? form.services.split('\n').map((s) => s.trim()).filter(Boolean)
          : undefined,
        specials: form.specials
          ? form.specials.split('\n').map((s) => s.trim()).filter(Boolean)
          : undefined,
        reservation_rules: form.reservation_rules
          ? form.reservation_rules.split('\n').map((s) => s.trim()).filter(Boolean)
          : undefined,
      })
      setMessage({ type: 'success', text: 'Settings saved. Your AI receptionist will use this info.' })
    } catch (e) {
      setMessage({ type: 'error', text: 'Failed to save settings' })
    } finally {
      setSaving(false)
    }
  }

  const openBillingPortal = async () => {
    setPortalLoading(true)
    try {
      const { data } = await api.post<{ url: string }>('/api/create-portal-session')
      if (data?.url) {
        window.location.href = data.url
        return
      }
      setMessage({ type: 'error', text: 'Could not open billing portal' })
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMessage({ type: 'error', text: detail || 'Could not open billing portal' })
    } finally {
      setPortalLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600" />
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* AI Receptionist Identity */}
      <div className="bg-white rounded-2xl shadow-xl p-8">
        <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2 mb-6">
          <User className="w-6 h-6 text-primary-600" />
          AI Receptionist
        </h2>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Receptionist name</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={receptionistName}
                onChange={(e) => setReceptionistName(e.target.value)}
                className="flex-1 rounded-lg border border-gray-300 px-3 py-2"
                placeholder="Give your AI receptionist a name"
              />
              <button
                type="button"
                onClick={randomizeName}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
                title="Random name"
              >
                <Shuffle className="w-4 h-4" />
                Random
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-1">This name is used when your AI introduces itself to callers.</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">AI receptionist phone number</label>
            <input
              type="text"
              value={aiPhone}
              readOnly
              className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-gray-500 cursor-not-allowed"
            />
            <p className="text-xs text-gray-500 mt-1">This is your AI receptionist&apos;s phone number. Contact your administrator to change it.</p>
            <p className="text-xs text-gray-500 mt-1">Calls and texts work when your number&apos;s Voice and Messaging webhooks are set in Twilio. If calls or texts aren&apos;t working, contact your administrator.</p>
          </div>
        </div>
      </div>

      {/* Voice Settings */}
      <div className="bg-white rounded-2xl shadow-xl p-8">
        <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2 mb-6">
          <Volume2 className="w-6 h-6 text-primary-600" />
          Voice settings
        </h2>
        <p className="text-gray-600 text-sm mb-4">
          Choose the voice and speaking speed for your AI receptionist (phone and SMS).
        </p>
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-1">Speaking speed</label>
          <div className="flex items-center gap-4 flex-wrap">
            <input
              type="range"
              min={SPEECH_SPEED_MIN}
              max={SPEECH_SPEED_MAX}
              step={SPEECH_SPEED_STEP}
              value={speechSpeed}
              onChange={(e) => setSpeechSpeed(Number(e.target.value))}
              className="flex-1 min-w-[120px] h-2 rounded-lg appearance-none cursor-pointer bg-gray-200 accent-primary-600"
            />
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={SPEECH_SPEED_MIN}
                max={SPEECH_SPEED_MAX}
                step={0.01}
                value={speechSpeed}
                onChange={(e) => {
                  const v = parseFloat(e.target.value)
                  if (!Number.isNaN(v)) {
                    setSpeechSpeed(Math.max(SPEECH_SPEED_MIN, Math.min(SPEECH_SPEED_MAX, v)))
                  }
                }}
                className="w-20 rounded-lg border border-gray-300 px-2 py-1.5 text-sm text-right tabular-nums"
              />
            </div>
          </div>
          <p className="text-xs text-gray-500 mt-1">Drag the slider or type a value (0.25 = slowest, 4 = fastest).</p>
        </div>
        <div className="flex flex-wrap gap-3">
          {VOICES.map((v) => (
            <div key={v} className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setVoice(v)}
                className={`px-4 py-2 rounded-l-lg text-sm font-medium transition-all ${
                  voice === v
                    ? 'bg-primary-600 text-white shadow-md'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                {v.charAt(0).toUpperCase() + v.slice(1)}
                {v === 'fable' && ' (recommended)'}
              </button>
              <button
                type="button"
                onClick={() => previewVoice(v)}
                disabled={previewing !== null && previewing !== v}
                className={`px-2 py-2 rounded-r-lg text-sm transition-all ${
                  previewing === v
                    ? 'bg-red-500 text-white'
                    : voice === v
                      ? 'bg-primary-700 text-white hover:bg-primary-800'
                      : 'bg-gray-200 text-gray-600 hover:bg-gray-300'
                } disabled:opacity-40 disabled:cursor-not-allowed`}
                title={previewing === v ? 'Stop' : `Preview ${v}`}
              >
                {previewing === v ? <Square className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
              </button>
            </div>
          ))}
        </div>
        {previewing && (
          <p className="text-xs text-gray-500 mt-2 animate-pulse">Playing {previewing} voice sample...</p>
        )}
      </div>

      {/* SMS Automations (Growth/Pro) */}
      {smsAutomationsMax != null && smsAutomationsMax > 0 && (
        <SmsAutomationsSection
          automations={automations}
          smsAutomationsMax={smsAutomationsMax}
          onRefresh={() => api.get('/api/sms-automations').then((r) => setAutomations(r.data?.automations || []))}
          api={api}
        />
      )}

      {/* Billing */}
      <div className="bg-white rounded-2xl shadow-xl p-8">
        <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2 mb-6">
          <CreditCard className="w-6 h-6 text-primary-600" />
          Billing
        </h2>
        <p className="text-gray-600 text-sm mb-4">
          Change plan, update payment method, or manage your subscription.
        </p>
        <button
          type="button"
          onClick={openBillingPortal}
          disabled={portalLoading}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg font-medium bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50"
        >
          <CreditCard className="w-4 h-4" />
          {portalLoading ? 'Opening…' : 'Manage subscription'}
        </button>
        <p className="mt-4 text-xs text-gray-500">
          To cancel your subscription, use &quot;Manage subscription&quot; above; cancellation is available in the billing portal.
        </p>
        <button
          type="button"
          onClick={openBillingPortal}
          disabled={portalLoading}
          className="mt-3 text-xs text-gray-500 hover:text-gray-700 underline"
        >
          Cancel service
        </button>
      </div>

      {/* Store Info */}
      <div className="bg-white rounded-2xl shadow-xl p-8">
        <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2 mb-6">
          <Store className="w-6 h-6 text-primary-600" />
          Store info &amp; AI customizations
        </h2>
        <p className="text-gray-600 text-sm mb-6">
          This information is used by your AI receptionist when answering calls and texts (hours, services, booking rules, etc.).
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Business name</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              className="w-full rounded-lg border border-gray-300 px-3 py-2"
              placeholder="Your Business Name"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Hours</label>
            <input
              type="text"
              value={form.hours}
              onChange={(e) => setForm((f) => ({ ...f, hours: e.target.value }))}
              className="w-full rounded-lg border border-gray-300 px-3 py-2"
              placeholder="e.g. Mon–Fri 9 AM–5 PM"
            />
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Forwarding phone number</label>
            <input
              type="text"
              value={form.forwarding_phone}
              onChange={(e) => setForm((f) => ({ ...f, forwarding_phone: e.target.value }))}
              className="w-full rounded-lg border border-gray-300 px-3 py-2"
              placeholder="Number to forward calls to when a caller asks for a real person"
            />
            <p className="text-xs text-gray-500 mt-1">When a caller asks to speak to someone, the AI will transfer the call to this number.</p>
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Staff (transfer by name)</label>
            {staffMax != null && <p className="text-xs text-gray-500 mb-2">Your plan allows up to {staffMax} staff member(s).</p>}
            {staff.map((s, i) => (
              <div key={i} className="flex gap-2 mb-2">
                <input
                  type="text"
                  value={s.name}
                  onChange={(e) => updateStaff(i, 'name', e.target.value)}
                  className="flex-1 rounded-lg border border-gray-300 px-3 py-2"
                  placeholder="Name"
                />
                <input
                  type="text"
                  value={s.phone}
                  onChange={(e) => updateStaff(i, 'phone', e.target.value)}
                  className="flex-1 rounded-lg border border-gray-300 px-3 py-2"
                  placeholder="Phone (E.164)"
                />
                <button type="button" onClick={() => removeStaff(i)} className="p-2 text-red-600 hover:bg-red-50 rounded-lg" title="Remove">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={addStaff}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 rounded-lg"
            >
              <Plus className="w-4 h-4" /> Add staff
            </button>
            <p className="text-xs text-gray-500 mt-1">Callers can ask to speak to these people by name; the AI will transfer the call.</p>
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
            <input
              type="email"
              value={form.email}
              onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              className="w-full rounded-lg border border-gray-300 px-3 py-2"
              placeholder="info@yourbusiness.com"
            />
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Address</label>
            <input
              type="text"
              value={form.address}
              onChange={(e) => setForm((f) => ({ ...f, address: e.target.value }))}
              className="w-full rounded-lg border border-gray-300 px-3 py-2"
              placeholder="123 Main St, City, State"
            />
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Menu or website link</label>
            <input
              type="text"
              value={form.menu_link}
              onChange={(e) => setForm((f) => ({ ...f, menu_link: e.target.value }))}
              className="w-full rounded-lg border border-gray-300 px-3 py-2"
              placeholder="https://..."
            />
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Custom greeting (optional)</label>
            <input
              type="text"
              value={form.greeting}
              onChange={(e) => setForm((f) => ({ ...f, greeting: e.target.value }))}
              className="w-full rounded-lg border border-gray-300 px-3 py-2"
              placeholder="Thank you for calling {business_name}. How can I help?"
            />
            <p className="text-xs text-gray-500 mt-1">Use {'{business_name}'} for your business name.</p>
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Services (one per line)</label>
            <textarea
              value={form.services}
              onChange={(e) => setForm((f) => ({ ...f, services: e.target.value }))}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 min-h-[80px]"
              placeholder="Haircut&#10;Color&#10;Styling"
            />
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Specials / promotions (one per line)</label>
            <textarea
              value={form.specials}
              onChange={(e) => setForm((f) => ({ ...f, specials: e.target.value }))}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 min-h-[80px]"
              placeholder="Happy hour 4–6 PM&#10;Tuesday 2-for-1"
            />
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Reservation / booking rules (one per line)</label>
            <textarea
              value={form.reservation_rules}
              onChange={(e) => setForm((f) => ({ ...f, reservation_rules: e.target.value }))}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 min-h-[80px]"
              placeholder="Reservations recommended for 6+&#10;Same-day booking by phone"
            />
          </div>
        </div>

        {message && (
          <p className={`mt-4 text-sm ${message.type === 'success' ? 'text-green-600' : 'text-red-600'}`}>
            {message.text}
          </p>
        )}

        <div className="mt-6 flex items-center gap-3">
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg font-medium bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50"
          >
            <Save className="w-4 h-4" />
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </div>
    </div>
  )
}
