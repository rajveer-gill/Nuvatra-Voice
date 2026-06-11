'use client'

/** Admin audit-log viewer — the security trail (who did what, when, from where).
 * Reads GET /api/admin/audit (admin-authed via the shared client). */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useApiClient, sameOriginApiConfig } from '@/lib/api'
import { Skeleton } from '@/components/ui/Skeleton'
import { RevealStagger, RevealItem } from '@/components/motion'
import { CollapsibleSection } from '@/components/ui/CollapsibleSection'

interface AuditEvent {
  id: number
  occurred_at: string | null
  actor_type: string
  actor_id?: string | null
  action: string
  resource_type?: string | null
  resource_id?: string | null
  client_id?: string | null
  ip?: string | null
}

function relTime(iso: string | null): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  if (s < 604800) return `${Math.floor(s / 86400)}d ago`
  return new Date(iso).toLocaleDateString()
}

function actionTone(action: string): string {
  const a = (action || '').toLowerCase()
  if (/(fail|denied|reject|error)/.test(a)) return 'border-red-500/30 bg-red-500/10 text-red-200'
  if (/(delete|clear|remove|revoke|purge)/.test(a)) return 'border-amber-500/30 bg-amber-500/10 text-amber-200'
  if (/(create|add|sent|insert|grant|link)/.test(a)) return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
  return 'border-white/15 bg-white/5 text-zinc-300'
}

export function AuditLog() {
  const api = useApiClient()
  const adminApi = useMemo(() => sameOriginApiConfig(), [])
  const [events, setEvents] = useState<AuditEvent[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await api.get<{ events: AuditEvent[] }>(
        '/api/admin/audit?limit=100',
        adminApi,
      )
      setEvents(data.events || [])
    } catch {
      setError('Failed to load audit log.')
    } finally {
      setLoading(false)
    }
  }, [api, adminApi])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <CollapsibleSection
      title="Audit log"
      description="Recent security & admin events (newest first)."
      className="mb-8"
    >
      <div className="mb-4 flex justify-end">
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="rounded-lg border border-white/15 px-3 py-1.5 text-xs font-medium text-zinc-300 hover:bg-white/5 disabled:opacity-50"
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {loading && !events ? (
        <div className="space-y-2">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-9 w-full bg-white/10" />
          ))}
        </div>
      ) : events && events.length > 0 ? (
        <div className="overflow-x-auto">
          <RevealStagger className="min-w-full" stagger={0.03}>
            <div className="grid grid-cols-[auto_1fr_auto_auto] gap-x-4 border-b border-white/10 pb-2 text-[11px] font-medium uppercase tracking-wider text-zinc-500">
              <span>When</span>
              <span>Action</span>
              <span>Actor</span>
              <span>Tenant</span>
            </div>
            {events.map((e) => (
              <RevealItem
                key={e.id}
                className="grid grid-cols-[auto_1fr_auto_auto] items-center gap-x-4 border-b border-white/5 py-2 text-sm"
              >
                <span className="whitespace-nowrap text-zinc-400" title={e.occurred_at || ''}>
                  {relTime(e.occurred_at)}
                </span>
                <span className="min-w-0">
                  <span
                    className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${actionTone(e.action)}`}
                  >
                    {e.action}
                  </span>
                  {e.resource_type && (
                    <span className="ml-2 text-xs text-zinc-500">
                      {e.resource_type}
                      {e.resource_id ? `:${String(e.resource_id).slice(0, 12)}` : ''}
                    </span>
                  )}
                </span>
                <span className="whitespace-nowrap text-xs text-zinc-400">
                  {e.actor_type}
                  {e.actor_id ? ` · ${String(e.actor_id).slice(0, 10)}…` : ''}
                </span>
                <span className="whitespace-nowrap font-mono text-xs text-zinc-500">
                  {e.client_id || '—'}
                </span>
              </RevealItem>
            ))}
          </RevealStagger>
        </div>
      ) : (
        <p className="py-6 text-center text-sm text-zinc-500">No audit events recorded yet.</p>
      )}
    </CollapsibleSection>
  )
}
