'use client'

import { useState, useEffect, useRef, useMemo, type ReactNode } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import * as Sentry from '@sentry/nextjs'
import { useAuth } from '@clerk/nextjs'
import {
  Volume2,
  Store,
  Save,
  Shuffle,
  User,
  Play,
  Square,
  CreditCard,
  CheckCircle2,
  Circle,
  AlertTriangle,
  Clock,
  Users,
  PhoneForwarded,
} from 'lucide-react'
import { useApiClient } from '@/lib/api'
import {
  RANDOM_NAMES,
  SPEECH_SPEED_MAX,
  SPEECH_SPEED_MIN,
  SPEECH_SPEED_STEP,
  VOICES,
  VOICE_SAMPLE_BASE,
  VOICE_SAMPLE_TEXT,
} from '@/components/settings/constants'
import { SmsAutomationsSection } from '@/components/settings/SmsAutomationsSection'
import { StaffMembersSection, normalizeStaffFromApi, type StaffRow } from '@/components/settings/StaffMembersSection'
import {
  TransferTargetsSection,
  normalizeTransferFromApi,
  type TransferRow,
} from '@/components/settings/TransferTargetsSection'
import {
  normalizeServices,
  normalizeSpecials,
  normalizeRules,
  ServicesEditor,
  SpecialsEditor,
  RulesEditor,
  type ServiceRow,
  type SpecialRow,
  type RuleRow,
} from '@/components/settings/StructuredListEditors'
import { BusinessHoursModal } from '@/components/settings/BusinessHoursModal'
import { parseHoursToWeekly, summarizeSchedule } from '@/lib/businessHours'
import { fadeUpChild, staggerContainer } from '@/components/motion'

/** Set NEXT_PUBLIC_DEBUG_SETTINGS=1 in .env.local (or Vercel) to log per-endpoint load outcomes — no tokens. */
const DEBUG_SETTINGS = process.env.NEXT_PUBLIC_DEBUG_SETTINGS === '1'

function SettingsSection({
  children,
  className = '',
  delay = 0,
  ...rest
}: {
  children: ReactNode
  className?: string
  delay?: number
} & React.ComponentPropsWithoutRef<'section'>) {
  const reduceMotion = useReducedMotion()
  return (
    <motion.section
      variants={fadeUpChild}
      custom={delay}
      whileHover={reduceMotion ? undefined : { y: -3, transition: { type: 'spring', stiffness: 420, damping: 26 } }}
      className={`relative overflow-hidden rounded-2xl border border-slate-200/90 bg-white p-8 shadow-xl shadow-slate-900/10 ring-1 ring-slate-900/[0.04] ${className}`}
      {...rest}
    >
      <motion.div
        aria-hidden
        className="pointer-events-none absolute -right-16 -top-16 h-36 w-36 rounded-full bg-gradient-to-br from-primary-400/25 via-cyan-300/10 to-transparent blur-2xl"
        animate={reduceMotion ? undefined : { scale: [1, 1.12, 1], opacity: [0.35, 0.65, 0.35] }}
        transition={{ duration: 5.5, repeat: Infinity, ease: 'easeInOut' }}
      />
      <motion.div
        aria-hidden
        className="pointer-events-none absolute -bottom-12 -left-12 h-28 w-28 rounded-full bg-gradient-to-tr from-violet-400/15 to-transparent blur-2xl"
        animate={reduceMotion ? undefined : { x: [0, 8, 0], y: [0, -6, 0] }}
        transition={{ duration: 7, repeat: Infinity, ease: 'easeInOut' }}
      />
      <motion.div className="relative z-10" layout>
        {children}
      </motion.div>
    </motion.section>
  )
}

export default function Settings() {
  const { isLoaded, isSignedIn } = useAuth()
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
  const [billingError, setBillingError] = useState<string | null>(null)
  const [form, setForm] = useState({
    name: '',
    business_type: '',
    hours: '',
    forwarding_phone: '',
    email: '',
    address: '',
    menu_link: '',
    greeting: '',
  })
  const [serviceItems, setServiceItems] = useState<ServiceRow[]>([])
  const [specialItems, setSpecialItems] = useState<SpecialRow[]>([])
  const [ruleItems, setRuleItems] = useState<RuleRow[]>([])
  const [industryLocked, setIndustryLocked] = useState(false)
  const [verticalLabel, setVerticalLabel] = useState('')
  const [staff, setStaff] = useState<StaffRow[]>([])
  const [transferTargets, setTransferTargets] = useState<TransferRow[]>([])
  const [transferMax, setTransferMax] = useState<number | null>(null)
  const [automations, setAutomations] = useState<{ id: number; trigger: string; template: string; enabled: boolean }[]>([])
  const [smsAutomationsMax, setSmsAutomationsMax] = useState<number | null>(null)
  const [setupStatus, setSetupStatus] = useState<{ complete: boolean; missing: string[]; warnings: string[] } | null>(null)
  const [hoursModalOpen, setHoursModalOpen] = useState(false)
  const saveBarRef = useRef<HTMLDivElement>(null)
  const reduceMotion = useReducedMotion()

  const hoursSummaryPreview = useMemo(() => {
    const { schedule } = parseHoursToWeekly(form.hours || '')
    const line = summarizeSchedule(schedule, 96)
    return (form.hours || '').trim() ? line : ''
  }, [form.hours])

  // Preload static voice samples so first play is instant
  useEffect(() => {
    VOICES.forEach((v) => {
      const a = new Audio()
      a.src = `${VOICE_SAMPLE_BASE}/${v}.mp3`
    })
  }, [])

  const refreshSetupStatus = () => {
    api.get('/api/setup-status').then((r) => setSetupStatus(r.data)).catch(() => setSetupStatus(null))
  }

  useEffect(() => {
    if (!isLoaded) {
      return
    }
    if (!isSignedIn) {
      setLoading(false)
      setMessage(null)
      return
    }

    let cancelled = false
    setLoading(true)

    const swallow =
      (label: string, fallback: unknown) => (err: unknown) => {
        if (DEBUG_SETTINGS) {
          const ax = err as { response?: { status?: number; data?: unknown }; message?: string }
          console.warn(
            `[Settings] ${label} request failed`,
            ax.response?.status ?? 'network',
            ax.message,
            ax.response?.data !== undefined ? '(body present)' : ''
          )
        }
        return { data: fallback }
      }

    Promise.all([
      api.get('/api/business-info').catch(swallow('business-info', null as unknown)),
      api.get('/api/subscription').catch(swallow('subscription', null)),
      api.get('/api/sms-automations').catch(swallow('sms-automations', { automations: [] })),
      api.get('/api/setup-status').catch(swallow('setup-status', null)),
    ])
      .then(([infoRes, subRes, automationsRes, setupRes]) => {
        if (cancelled) return
        setMessage(null)
        try {
          const limits = (subRes?.data as { limits?: { transfer_max?: number; sms_automations_max?: number } } | null)?.limits
          if (limits?.transfer_max != null) setTransferMax(limits.transfer_max)
          if (limits?.sms_automations_max != null) setSmsAutomationsMax(limits.sms_automations_max)
          setAutomations((automationsRes?.data as { automations?: unknown[] })?.automations || [])
          setSetupStatus((setupRes?.data as { complete?: boolean; missing?: string[]; warnings?: string[] }) || null)

          const d = infoRes?.data as Record<string, unknown> | null | undefined
          if (!d) {
            if (DEBUG_SETTINGS) {
              console.warn(
                '[Settings] business-info body is empty — open Network → /api/business-info (status, JSON, CORS)'
              )
            }
            return
          }
          setVoice((d.voice as string) || 'fable')
          setStaff(normalizeStaffFromApi(d.staff ?? []))
          setTransferTargets(normalizeTransferFromApi(d.transfer_targets ?? []))
          const spd = typeof d.speed === 'number' ? d.speed : 1.0
          setSpeechSpeed(Math.max(SPEECH_SPEED_MIN, Math.min(SPEECH_SPEED_MAX, spd)))
          setReceptionistName((d.receptionist_name as string) || '')
          setAiPhone((d.phone as string) || '')
          setForm({
            name: (d.name as string) || '',
            business_type: (d.business_type as string) || '',
            hours: (d.hours as string) || '',
            forwarding_phone: (d.forwarding_phone as string) || '',
            email: (d.email as string) || '',
            address: (d.address as string) || '',
            menu_link: (d.menu_link as string) || '',
            greeting: (d.greeting as string) || '',
          })
          setServiceItems(normalizeServices(d.services))
          setSpecialItems(normalizeSpecials(d.specials))
          setRuleItems(normalizeRules(d.reservation_rules))
          setIndustryLocked(!!d.business_type_admin_locked)
          setVerticalLabel(String(d.business_vertical_label || ''))
        } catch (e) {
          console.error('[Settings] failed to apply API response', e)
          Sentry.captureException(e instanceof Error ? e : new Error(String(e)), {
            tags: { area: 'settings_load' },
            extra: { phase: 'apply_response' },
          })
          setMessage({ type: 'error', text: 'Failed to load settings' })
        }
      })
      .catch((err) => {
        if (cancelled) return
        console.error('[Settings] settings fetch failed', err)
        Sentry.captureException(err instanceof Error ? err : new Error(String(err)), {
          tags: { area: 'settings_load' },
          extra: { phase: 'promise_all' },
        })
        setMessage({ type: 'error', text: 'Failed to load settings' })
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [api, isLoaded, isSignedIn])

  useEffect(() => {
    if (!message || !saveBarRef.current) return
    saveBarRef.current.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'nearest' })
  }, [message, reduceMotion])

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

    const cleanup = () => {
      setPreviewing(null)
      audioRef.current = null
    }

    const staticUrl = `${VOICE_SAMPLE_BASE}/${v}.mp3`
    const audio = new Audio(staticUrl)
    audio.playbackRate = speechSpeed
    audioRef.current = audio

    const fallbackToApi = async () => {
      audioRef.current = null
      try {
        const res = await api.post('/api/text-to-speech', { text: VOICE_SAMPLE_TEXT, voice: v, speed: speechSpeed }, { responseType: 'blob' })
        const url = URL.createObjectURL(res.data)
        const apiAudio = new Audio(url)
        audioRef.current = apiAudio
        apiAudio.onended = () => {
          setPreviewing(null)
          URL.revokeObjectURL(url)
          audioRef.current = null
        }
        apiAudio.onerror = () => {
          setPreviewing(null)
          URL.revokeObjectURL(url)
          audioRef.current = null
        }
        await apiAudio.play()
      } catch {
        setPreviewing(null)
      }
    }

    audio.onended = cleanup
    audio.onerror = () => fallbackToApi()
    try {
      await audio.play()
    } catch {
      fallbackToApi()
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setMessage(null)
    try {
      const { data } = await api.patch('/api/business-info', {
        name: form.name || undefined,
        ...(!industryLocked ? { business_type: form.business_type || undefined } : {}),
        hours: form.hours || undefined,
        forwarding_phone: form.forwarding_phone || undefined,
        email: form.email || undefined,
        address: form.address || undefined,
        menu_link: form.menu_link || undefined,
        greeting: form.greeting || undefined,
        voice: voice || undefined,
        receptionist_name: receptionistName || undefined,
        staff: staff
          .filter((s) => s.name.trim() || s.phone.trim())
          .map((s) => ({
            id: s.id,
            name: s.name.trim(),
            phone: s.phone.trim(),
            email: s.email.trim() || undefined,
            notes: s.notes || undefined,
            service_ids: s.service_ids.length ? s.service_ids : undefined,
          })),
        services: serviceItems.length ? serviceItems : undefined,
        specials: specialItems.length ? specialItems : undefined,
        reservation_rules: ruleItems.length ? ruleItems : undefined,
      })
      setStaff(normalizeStaffFromApi((data as { staff?: unknown }).staff ?? []))
      setMessage({ type: 'success', text: 'Settings saved. Your AI receptionist will use this info.' })
      refreshSetupStatus()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      const msg =
        typeof detail === 'string'
          ? detail
          : typeof detail === 'object' && detail !== null && 'message' in detail && typeof (detail as { message?: string }).message === 'string'
            ? (detail as { message: string }).message
            : 'Failed to save settings'
      setMessage({ type: 'error', text: msg })
    } finally {
      setSaving(false)
    }
  }

  const openBillingPortal = async () => {
    setPortalLoading(true)
    setBillingError(null)
    try {
      const { data } = await api.post<{ url: string }>('/api/create-portal-session')
      if (data?.url) {
        window.location.href = data.url
        return
      }
      setBillingError('Could not open billing portal')
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setBillingError(detail || 'Could not open billing portal')
    } finally {
      setPortalLoading(false)
    }
  }

  if (loading) {
    return (
      <motion.div
        className="flex h-64 flex-col items-center justify-center gap-4"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
      >
        <motion.div
          className="h-12 w-12 rounded-full border-2 border-primary-200 border-t-primary-600"
          animate={reduceMotion ? undefined : { rotate: 360 }}
          transition={{ duration: 0.9, repeat: Infinity, ease: 'linear' }}
        />
        <motion.p
          className="text-sm font-medium text-gray-500"
          animate={reduceMotion ? undefined : { opacity: [0.45, 1, 0.45] }}
          transition={{ duration: 1.6, repeat: Infinity }}
        >
          Loading settings…
        </motion.p>
      </motion.div>
    )
  }

  const setupComplete = setupStatus?.complete ?? true
  const missing = setupStatus?.missing ?? []
  const warnings = setupStatus?.warnings ?? []

  return (
    <motion.div
      className="mx-auto max-w-4xl space-y-8 pb-44 text-gray-900"
      variants={staggerContainer}
      initial="hidden"
      animate="visible"
    >
      {/* Setup checklist: ensure AI has correct business info before taking calls */}
      <SettingsSection delay={0}>
        <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2 mb-2">
          {setupComplete ? <CheckCircle2 className="w-6 h-6 text-green-600" /> : <AlertTriangle className="w-6 h-6 text-amber-500" />}
          Setup checklist
        </h2>
        <p className="text-gray-600 text-sm mb-4">
          Complete these so your AI receptionist can give callers accurate info and handle bookings. Works for any business—restaurants, salons, HVAC, real estate, and more.
        </p>
        <ul className="space-y-2">
          {(
            [
              { key: 'name', label: 'Business name' },
              { key: 'hours', label: 'Hours of operation' },
              { key: 'phone', label: 'Phone number' },
              { key: 'address', label: 'Address' },
            ] as const
          ).map(({ key, label }) => {
            const done = !missing.includes(label)
            return (
            <motion.li
              key={key}
              layout
              initial={reduceMotion ? false : { opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.05 * (['name', 'hours', 'phone', 'address'].indexOf(key) + 1) }}
              className="flex items-center gap-2 text-sm"
            >
              {done ? <CheckCircle2 className="w-4 h-4 text-green-600 shrink-0" /> : <Circle className="w-4 h-4 text-gray-300 shrink-0" />}
              <span className={done ? 'text-gray-700' : 'text-gray-500'}>{label}</span>
              {key === 'phone' && (
                <span className="text-gray-400 text-xs font-normal">(where callers go when they ask for a person)</span>
              )}
            </motion.li>
            )
          })}
        </ul>
        {warnings.length > 0 && (
          <p className="mt-3 text-amber-700 text-sm flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            {warnings[0]}
          </p>
        )}
        {!setupComplete && (
          <p className="mt-3 text-amber-700 text-sm font-medium">
            Fill in the required fields below and save. Your AI will work better with complete business info.
          </p>
        )}
      </SettingsSection>

      {/* AI Receptionist Identity */}
      <SettingsSection delay={1}>
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
                className="cs-field flex-1 min-w-0"
                placeholder="Give your AI receptionist a name"
              />
              <motion.button
                type="button"
                onClick={randomizeName}
                whileHover={reduceMotion ? undefined : { scale: 1.03 }}
                whileTap={reduceMotion ? undefined : { scale: 0.97 }}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
                title="Random name"
              >
                <Shuffle className="w-4 h-4" />
                Random
              </motion.button>
            </div>
            <p className="text-xs text-gray-500 mt-1">This name is used when your AI introduces itself to callers.</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">AI receptionist phone number</label>
            <input
              type="text"
              value={aiPhone}
              readOnly
              className="w-full cursor-not-allowed rounded-lg border border-gray-400 bg-gray-100 px-3 py-2 text-gray-800"
            />
            <p className="text-xs text-gray-500 mt-1">This is your AI receptionist&apos;s phone number. Contact your administrator to change it.</p>
            <p className="text-xs text-gray-500 mt-1">Calls and texts work when your number&apos;s Voice and Messaging webhooks are set in Twilio. If calls or texts aren&apos;t working, contact your administrator.</p>
          </div>
        </div>
      </SettingsSection>

      {/* Voice Settings */}
      <SettingsSection delay={2}>
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
                className="cs-field-compact w-20 text-right tabular-nums"
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
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="mt-2 text-xs font-medium text-primary-600"
          >
            Playing {previewing} voice sample…
          </motion.p>
        )}
      </SettingsSection>

      {/* SMS Automations (Growth/Pro) */}
      {smsAutomationsMax != null && smsAutomationsMax > 0 && (
        <SmsAutomationsSection
          automations={automations}
          smsAutomationsMax={smsAutomationsMax}
          onRefresh={() => api.get('/api/sms-automations').then((r) => setAutomations(r.data?.automations || [])).catch(() => {})}
          onAdd={(a) => setAutomations((prev) => [...prev, a])}
          api={api}
        />
      )}

      {/* Billing */}
      <SettingsSection delay={3}>
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
        {billingError && (
          <p className="mt-3 text-sm text-red-600">{billingError}</p>
        )}
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
      </SettingsSection>

      {/* Business info — any type: restaurant, salon, HVAC, real estate, etc. */}
      <SettingsSection delay={4}>
        <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2 mb-6">
          <Store className="w-6 h-6 text-primary-600" />
          Business info &amp; AI customizations
        </h2>
        <p className="text-gray-600 text-sm mb-6">
          Your AI receptionist uses this when answering calls and texts. Fill in hours, services, and booking rules so it can give accurate info and take bookings—for any business type (restaurant, nail salon, HVAC, real estate, etc.).
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Business name</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              className="cs-field w-full"
              placeholder="Your Business Name"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Industry</label>
            {industryLocked && verticalLabel ? (
              <>
                <div className="cs-field w-full bg-gray-50 text-gray-800">{verticalLabel}</div>
                <p className="text-xs text-gray-500 mt-1">Set by your administrator when the account was created.</p>
              </>
            ) : (
              <>
                <input
                  type="text"
                  value={form.business_type}
                  onChange={(e) => setForm((f) => ({ ...f, business_type: e.target.value }))}
                  className="cs-field w-full"
                  placeholder="e.g. nail salon, HVAC company, real estate brokerage, restaurant"
                />
                <p className="text-xs text-gray-500 mt-1">
                  This tells the AI what kind of business you run so it doesn&apos;t assume a generic or demo industry.
                </p>
              </>
            )}
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Hours of operation</label>
            <button
              type="button"
              onClick={() => setHoursModalOpen(true)}
              className="group flex w-full items-center justify-between gap-3 rounded-xl border border-gray-200 bg-gradient-to-br from-white via-white to-primary-50/40 px-4 py-3.5 text-left shadow-sm ring-1 ring-black/5 transition hover:border-primary-300 hover:shadow-md hover:ring-primary-200/40"
            >
              <div className="min-w-0 flex-1">
                <p className={`truncate text-sm ${hoursSummaryPreview ? 'font-medium text-gray-900' : 'text-gray-500'}`}>
                  {hoursSummaryPreview || 'Set which days you’re open and your hours — opens the visual editor'}
                </p>
                <p className="mt-1 text-xs text-gray-500">
                  Schedule presets, copy weekdays, and live preview — saved when you click Apply in the editor, then Save changes below.
                </p>
              </div>
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-primary-100 text-primary-700 transition group-hover:scale-105 group-hover:bg-primary-200">
                <Clock className="h-5 w-5" aria-hidden />
              </div>
            </button>
            <BusinessHoursModal
              isOpen={hoursModalOpen}
              onClose={() => setHoursModalOpen(false)}
              hoursText={form.hours}
              onApply={(next) => setForm((f) => ({ ...f, hours: next }))}
            />
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Forwarding phone number</label>
            <input
              type="text"
              value={form.forwarding_phone}
              onChange={(e) => setForm((f) => ({ ...f, forwarding_phone: e.target.value }))}
              className="cs-field w-full"
              placeholder="Number to forward calls to when a caller asks for a real person"
            />
            <p className="text-xs text-gray-500 mt-1">
              Default line when someone asks for a person without naming anyone on your transfer list (see Call transfers
              section below).
            </p>
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
            <input
              type="email"
              value={form.email}
              onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              className="cs-field w-full"
              placeholder="info@yourbusiness.com"
            />
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Address</label>
            <input
              type="text"
              value={form.address}
              onChange={(e) => setForm((f) => ({ ...f, address: e.target.value }))}
              className="cs-field w-full"
              placeholder="123 Main St, City, State"
            />
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Website or menu link (optional)</label>
            <input
              type="text"
              value={form.menu_link}
              onChange={(e) => setForm((f) => ({ ...f, menu_link: e.target.value }))}
              className="cs-field w-full"
              placeholder="https://... (menu, services, or main site)"
            />
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Custom greeting (optional)</label>
            <input
              type="text"
              value={form.greeting}
              onChange={(e) => setForm((f) => ({ ...f, greeting: e.target.value }))}
              className="cs-field w-full"
              placeholder="Thank you for calling {business_name}. How can I help?"
            />
            <p className="text-xs text-gray-500 mt-1">
              Use {'{business_name}'} for your business name and {'{receptionist_name}'} for the AI name above. If you
              leave the name out of this text, we prepend “Hi, I&apos;m [name].” on the phone greeting automatically.
            </p>
          </div>
          <ServicesEditor items={serviceItems} onChange={setServiceItems} />
          <SpecialsEditor items={specialItems} onChange={setSpecialItems} />
          <RulesEditor items={ruleItems} onChange={setRuleItems} />
        </div>

      </SettingsSection>

      <SettingsSection delay={5} aria-labelledby="team-roster-settings-heading">
        <h2
          id="team-roster-settings-heading"
          className="text-xl font-bold text-gray-900 flex items-center gap-2 mb-2"
        >
          <Users className="w-6 h-6 text-teal-600" />
          Team roster
        </h2>
        <p className="text-gray-600 text-sm mb-6 max-w-3xl">
          Everyone callers can book with—stylists, artists, providers, chairs. Add as many as you need; this list is only for
          scheduling and AI context, not who receives live call transfers.
        </p>
        <StaffMembersSection
          staff={staff}
          availableServices={serviceItems}
          onStaffChange={setStaff}
          api={api}
          onNotify={setMessage}
          onAfterSave={refreshSetupStatus}
        />
      </SettingsSection>

      <SettingsSection delay={6} aria-labelledby="call-transfers-settings-heading">
        <h2
          id="call-transfers-settings-heading"
          className="text-xl font-bold text-gray-900 flex items-center gap-2 mb-2"
        >
          <PhoneForwarded className="w-6 h-6 text-violet-600" />
          Call transfers
        </h2>
        <p className="text-gray-600 text-sm mb-6 max-w-3xl">
          When a caller asks to speak with someone by name, the AI can transfer only to numbers you list here. Your plan limits
          how many destinations you can add—not how many people are on your booking roster above.
        </p>
        <TransferTargetsSection
          transfers={transferTargets}
          staff={staff}
          transferMax={transferMax}
          onTransfersChange={setTransferTargets}
          api={api}
          onNotify={setMessage}
          onAfterSave={refreshSetupStatus}
        />
      </SettingsSection>

      <motion.div
        ref={saveBarRef}
        initial={reduceMotion ? false : { y: 28, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ type: 'spring', stiffness: 380, damping: 32, delay: 0.15 }}
        className="fixed bottom-0 left-0 right-0 z-50 border-t border-white/10 bg-gradient-to-t from-zinc-950 via-zinc-950/95 to-zinc-950/85 px-4 pt-3 pb-[max(1rem,env(safe-area-inset-bottom))] backdrop-blur-xl"
      >
        <motion.div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-400/70 to-transparent"
          animate={reduceMotion ? undefined : { opacity: [0.35, 1, 0.35] }}
          transition={{ duration: 2.8, repeat: Infinity, ease: 'easeInOut' }}
        />
        <motion.div className="mx-auto flex w-full max-w-4xl flex-col gap-3">
          <AnimatePresence mode="wait">
            {message && (
              <motion.div
                key={`${message.type}-${message.text}`}
                role="alert"
                initial={reduceMotion ? false : { opacity: 0, y: 12, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={reduceMotion ? undefined : { opacity: 0, y: 8, scale: 0.98 }}
                transition={{ type: 'spring', stiffness: 500, damping: 28 }}
                className={`flex items-start gap-2.5 rounded-xl border px-4 py-3 text-sm shadow-lg ${
                  message.type === 'success'
                    ? 'border-emerald-500/35 bg-emerald-500/15 text-emerald-50'
                    : 'border-red-500/35 bg-red-500/15 text-red-50'
                }`}
              >
                {message.type === 'success' ? (
                  <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-400" />
                ) : (
                  <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-400" />
                )}
                <span>{message.text}</span>
              </motion.div>
            )}
          </AnimatePresence>
          <motion.button
            type="button"
            onClick={handleSave}
            disabled={saving}
            whileHover={reduceMotion ? undefined : { scale: 1.01 }}
            whileTap={reduceMotion ? undefined : { scale: 0.98 }}
            className="relative flex w-full items-center justify-center gap-2 overflow-hidden rounded-xl bg-gradient-to-r from-cyan-600 via-primary-600 to-indigo-600 px-6 py-4 text-base font-semibold text-white shadow-lg shadow-cyan-900/35 disabled:opacity-55"
          >
            {!reduceMotion && !saving && (
              <motion.span
                aria-hidden
                className="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0"
                animate={{ x: ['-120%', '120%'] }}
                transition={{ duration: 2.6, repeat: Infinity, ease: 'easeInOut', repeatDelay: 0.8 }}
              />
            )}
            <Save className="relative h-5 w-5" />
            <span className="relative">{saving ? 'Saving…' : 'Save changes'}</span>
          </motion.button>
        </motion.div>
      </motion.div>
    </motion.div>
  )
}
