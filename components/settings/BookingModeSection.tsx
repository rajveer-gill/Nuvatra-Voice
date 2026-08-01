'use client'

/** Where this store's appointments actually live.
 *
 * Most businesses use Nuvatra as their calendar ("internal") — that's the default and
 * nothing here needs touching. Salons on a closed system like Zenoti are the exception:
 * we can't write to their calendar, so the AI takes *requests* their staff approve and
 * enter on their side, and it never claims a slot it can't hold.
 *
 * The consult-only list and booking policies are enforced per store — an empty list
 * means no rules, which is every store until someone configures one. */

import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Loader2, Plus, X } from 'lucide-react'
import { useApiClient } from '@/lib/api'

type BookingMode = 'internal' | 'external'

const apiDetail = (e: unknown): string | null => {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof d === 'string' ? d : null
}

/** A small add/remove list of free-text entries. */
function StringList({
  label,
  hint,
  placeholder,
  values,
  onChange,
}: {
  label: string
  hint: string
  placeholder: string
  values: string[]
  onChange: (next: string[]) => void
}) {
  const [draft, setDraft] = useState('')
  const add = () => {
    const v = draft.trim()
    if (!v) return
    if (!values.some((x) => x.toLowerCase() === v.toLowerCase())) onChange([...values, v])
    setDraft('')
  }
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-zinc-300">{label}</label>
      <p className="mb-2 text-xs text-zinc-500">{hint}</p>
      <div className="mb-2 space-y-1.5">
        {values.length === 0 && <p className="text-xs text-zinc-600">None yet.</p>}
        {values.map((v, i) => (
          <div
            key={`${v}-${i}`}
            className="flex items-start justify-between gap-2 rounded-lg border border-white/10 bg-zinc-950/40 px-3 py-1.5"
          >
            <span className="text-sm text-zinc-200">{v}</span>
            <button
              type="button"
              onClick={() => onChange(values.filter((_, idx) => idx !== i))}
              aria-label={`Remove ${v}`}
              className="shrink-0 rounded p-0.5 text-zinc-500 hover:text-red-300"
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
          placeholder={placeholder}
          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-zinc-950/60 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:border-cyan-500 focus:outline-none"
        />
        <button
          type="button"
          onClick={add}
          disabled={!draft.trim()}
          className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-white/15 px-3 py-2 text-xs font-medium text-zinc-200 hover:bg-white/5 disabled:opacity-50"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden />
          Add
        </button>
      </div>
    </div>
  )
}

export function BookingModeSection() {
  const api = useApiClient()
  const [mode, setMode] = useState<BookingMode>('internal')
  const [provider, setProvider] = useState('')
  const [consultOnly, setConsultOnly] = useState<string[]>([])
  const [rules, setRules] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api
      .get('/api/business-info')
      .then((r) => {
        const d = r.data || {}
        setMode(d.booking_mode === 'external' ? 'external' : 'internal')
        setProvider((d.booking_provider_name as string) || '')
        setConsultOnly(Array.isArray(d.consult_only_services) ? d.consult_only_services : [])
        setRules(Array.isArray(d.booking_rules) ? d.booking_rules : [])
      })
      .catch(() => setError('Could not load booking settings.'))
      .finally(() => setLoading(false))
  }, [api])

  const save = useCallback(async () => {
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      await api.patch('/api/business-info', {
        booking_mode: mode,
        booking_provider_name: provider,
        consult_only_services: consultOnly,
        booking_rules: rules,
      })
      setSaved(true)
      window.setTimeout(() => setSaved(false), 3000)
    } catch (e) {
      setError(apiDetail(e) || 'Could not save booking settings.')
    } finally {
      setSaving(false)
    }
  }, [api, mode, provider, consultOnly, rules])

  if (loading) {
    return (
      <div className="rounded-2xl border border-white/10 bg-zinc-900/60 p-6">
        <div className="h-5 w-40 animate-pulse rounded bg-white/10" />
      </div>
    )
  }

  return (
    <section className="rounded-2xl border border-white/10 bg-zinc-900/60 p-6">
      <h2 className="font-display text-lg font-semibold text-white">Booking &amp; calendar</h2>
      <p className="mt-1 text-sm text-zinc-400">
        Where your appointments live, and any rules the receptionist must follow.
      </p>

      {error && (
        <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        {([
          {
            id: 'internal' as const,
            title: 'Nuvatra is my calendar',
            blurb:
              'The receptionist checks availability and books appointments directly. Most businesses use this.',
          },
          {
            id: 'external' as const,
            title: 'I book in another system',
            blurb:
              'Your calendar lives elsewhere (Zenoti, Mindbody, Boulevard…). The receptionist takes requests for your team to approve and enter.',
          },
        ]).map((opt) => {
          const selected = mode === opt.id
          return (
            <button
              type="button"
              key={opt.id}
              onClick={() => setMode(opt.id)}
              className={`rounded-2xl border p-4 text-left motion-safe-transition ${
                selected
                  ? 'border-cyan-500 bg-cyan-500/10 ring-1 ring-cyan-500/40'
                  : 'border-white/10 bg-zinc-950/40 hover:border-white/25'
              }`}
            >
              <div className="flex items-center gap-2">
                <span
                  className={`h-4 w-4 shrink-0 rounded-full border ${
                    selected ? 'border-cyan-400 bg-cyan-400' : 'border-zinc-600'
                  }`}
                />
                <span className="text-sm font-semibold text-white">{opt.title}</span>
              </div>
              <p className="mt-1 pl-6 text-xs text-zinc-400">{opt.blurb}</p>
            </button>
          )
        })}
      </div>

      {mode === 'external' && (
        <div className="mt-5 space-y-5 rounded-xl border border-white/10 bg-zinc-950/40 p-4">
          <div className="flex items-start gap-2 text-xs text-amber-200/90">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>
              In this mode the receptionist never promises a time — it tells callers their
              request has been sent, and your team confirms it. Appointments arrive on the
              Appointments tab for approval.
            </span>
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-zinc-300">
              What system do you book in?
            </label>
            <input
              type="text"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              placeholder="e.g. Zenoti"
              className="w-56 rounded-lg border border-white/10 bg-zinc-950/60 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:border-cyan-500 focus:outline-none"
            />
            <p className="mt-1 text-xs text-zinc-500">
              Used in wording your staff sees, like “Paste from Zenoti”.
            </p>
          </div>

          <StringList
            label="Never book these over the phone"
            hint="The receptionist takes their details and says the salon will call back — it won't offer a time. Use for anything needing a consultation first, e.g. corrective color."
            placeholder="e.g. Corrective Color"
            values={consultOnly}
            onChange={setConsultOnly}
          />

          <StringList
            label="Booking policies"
            hint="Plain-English rules the receptionist follows on every call."
            placeholder="e.g. Fashion colors must be booked as Vivid color."
            values={rules}
            onChange={setRules}
          />
        </div>
      )}

      <div className="mt-5 flex items-center gap-3">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="inline-flex items-center gap-1.5 rounded-full bg-gradient-to-r from-cyan-600 to-indigo-600 px-5 py-2 text-sm font-semibold text-white shadow-lg shadow-cyan-500/20 motion-safe-transition hover:brightness-110 disabled:opacity-50"
        >
          {saving && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
          {saving ? 'Saving…' : 'Save booking settings'}
        </button>
        {saved && <span className="text-sm text-emerald-400">Saved</span>}
      </div>
    </section>
  )
}
