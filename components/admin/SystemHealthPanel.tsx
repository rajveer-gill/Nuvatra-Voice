'use client'

/** System health: live ops self-check (cron/dependency status) + the incident log of
 * recorded failures, each resolvable once handled. This is your "is anything broken?" view. */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useApiClient, sameOriginApiConfig } from '@/lib/api'
import { Skeleton } from '@/components/ui/Skeleton'
import { CollapsibleSection } from '@/components/ui/CollapsibleSection'

interface FailedEvent {
  id: number
  source: string
  event_type?: string | null
  ref?: string | null
  error?: string | null
  resolved: boolean
  created_at?: string | null
}

interface OpsCheck {
  cron_jobs_healthy?: boolean
  stale_cron_jobs?: string[]
  database_enabled?: boolean
  public_base_url_set?: boolean
  twilio_signature_validation_enabled?: boolean
}

function relTime(iso?: string | null): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export function SystemHealthPanel() {
  const api = useApiClient()
  const adminApi = useMemo(() => sameOriginApiConfig(), [])
  const [events, setEvents] = useState<FailedEvent[] | null>(null)
  const [ops, setOps] = useState<OpsCheck | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [savingId, setSavingId] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [evRes, opsRes] = await Promise.all([
        api.get<{ events: FailedEvent[] }>('/api/admin/failed-events', adminApi),
        api.get<OpsCheck>('/api/admin/ops/self-check', adminApi).catch(() => ({ data: {} as OpsCheck })),
      ])
      setEvents(evRes.data.events || [])
      setOps(opsRes.data || {})
    } catch {
      setError('Failed to load system health.')
    } finally {
      setLoading(false)
    }
  }, [api, adminApi])

  useEffect(() => {
    void load()
  }, [load])

  const resolve = async (id: number) => {
    setSavingId(id)
    try {
      await api.patch(`/api/admin/failed-events/${id}`, { resolved: true }, adminApi)
      await load()
    } catch {
      setError('Could not resolve.')
    } finally {
      setSavingId(null)
    }
  }

  const open = events || []
  const cronOk = ops?.cron_jobs_healthy !== false
  const dbOk = ops?.database_enabled !== false

  const Status = ({ ok, label }: { ok: boolean; label: string }) => (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${
        ok ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-red-500/30 bg-red-500/10 text-red-200'
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? 'bg-emerald-400' : 'bg-red-400'}`} />
      {label}
    </span>
  )

  return (
    <CollapsibleSection
      title="System health"
      description="Is anything broken? Live status + the incident log."
      className="mb-8"
    >
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Status ok={dbOk} label={dbOk ? 'Database OK' : 'Database issue'} />
        <Status ok={cronOk} label={cronOk ? 'Cron jobs healthy' : `Stale: ${(ops?.stale_cron_jobs || []).join(', ') || 'yes'}`} />
        <Status ok={open.length === 0} label={open.length === 0 ? 'No open incidents' : `${open.length} open incident(s)`} />
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="ml-auto rounded-lg border border-white/15 px-3 py-1.5 text-xs font-medium text-zinc-300 hover:bg-white/5 disabled:opacity-50"
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {loading && !events ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10 w-full bg-white/10" />
          ))}
        </div>
      ) : open.length === 0 ? (
        <p className="rounded-xl border border-white/10 bg-zinc-950/40 py-6 text-center text-sm text-zinc-500">
          No open incidents — everything looks healthy. 🎉
        </p>
      ) : (
        <div className="space-y-2">
          {open.map((e) => (
            <div
              key={e.id}
              className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3"
            >
              <div className="min-w-0">
                <div className="text-sm text-zinc-100">
                  <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-200">
                    {e.source}
                  </span>
                  {e.event_type && <span className="ml-2 text-xs text-zinc-400">{e.event_type}</span>}
                  <span className="ml-2 text-xs text-zinc-500">{relTime(e.created_at)}</span>
                </div>
                {e.error && <div className="mt-1 break-words text-xs text-zinc-400">{e.error}</div>}
                {e.ref && <div className="text-[11px] text-zinc-600">ref: {e.ref}</div>}
              </div>
              <button
                type="button"
                onClick={() => void resolve(e.id)}
                disabled={savingId === e.id}
                className="shrink-0 rounded-lg border border-white/15 px-3 py-1.5 text-sm text-zinc-300 hover:bg-white/5 disabled:opacity-50"
              >
                {savingId === e.id ? 'Saving…' : 'Mark resolved'}
              </button>
            </div>
          ))}
        </div>
      )}
    </CollapsibleSection>
  )
}
