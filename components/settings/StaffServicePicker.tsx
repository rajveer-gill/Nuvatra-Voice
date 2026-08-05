'use client'

/** Pick which services a team member provides.
 *
 * A real salon menu is ~40 bookable services, and a flat checkbox list means forty
 * ticks per stylist across every store — which in practice means nobody fills it in.
 * Three things make that tractable:
 *
 *  - Services are grouped by the category they came in with ("Color Services"), and a
 *    category can be ticked whole. A colourist is two clicks, not twenty-nine.
 *  - Add-ons are excluded. Nobody "provides" a length surcharge or a master-stylist
 *    charge; those attach to a service someone else is already performing.
 *  - A new stylist can be copied from an existing one, because a salon runs two or
 *    three skill profiles, not ten.
 *
 * Empty still means "everything", and the copy says so — for most stylists that's the
 * correct answer and the cheapest one.
 */

import { useMemo, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import type { ServiceRow } from '@/components/settings/StructuredListEditors'

const UNCATEGORISED = 'Other services'

export type CopySource = { id: string; name: string; service_ids: string[] }

export function StaffServicePicker({
  services,
  selected,
  onChange,
  copyFrom = [],
}: {
  /** The full menu; add-ons are filtered out here rather than by the caller. */
  services: ServiceRow[]
  selected: string[]
  onChange: (next: string[]) => void
  /** Other team members, offered as a starting point. */
  copyFrom?: CopySource[]
}) {
  const [openCats, setOpenCats] = useState<Record<string, boolean>>({})

  const bookable = useMemo(() => services.filter((s) => !s.is_addon), [services])

  const groups = useMemo(() => {
    const by = new Map<string, ServiceRow[]>()
    for (const s of bookable) {
      const key = (s.category || '').trim() || UNCATEGORISED
      const list = by.get(key)
      if (list) list.push(s)
      else by.set(key, [s])
    }
    // Anything the file didn't categorise sorts last; the rest keep menu order.
    return Array.from(by.entries())
      .map(([title, rows]) => ({ title, rows }))
      .sort((a, b) =>
        a.title === UNCATEGORISED ? 1 : b.title === UNCATEGORISED ? -1 : 0
      )
  }, [bookable])

  const chosen = useMemo(() => new Set(selected), [selected])
  /** Selections can outlive the service that owned them — count only live ones. */
  const liveCount = bookable.filter((s) => chosen.has(s.id)).length

  const setMany = (ids: string[], on: boolean) => {
    const next = new Set(selected)
    for (const id of ids) {
      if (on) next.add(id)
      else next.delete(id)
    }
    onChange(Array.from(next))
  }

  if (!bookable.length) {
    return (
      <p className="rounded-lg border border-dashed border-gray-200 px-3 py-2 text-xs text-gray-500">
        Add services in the <strong>Services</strong> section above to link them to team
        members here.
      </p>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-gray-500">
          {liveCount === 0
            ? 'Not set — they can be booked for anything on the menu. That’s right for most people.'
            : `${liveCount} of ${bookable.length} services.`}
        </p>
        <div className="flex items-center gap-2">
          {copyFrom.length > 0 && (
            <select
              value=""
              aria-label="Copy services from another team member"
              onChange={(e) => {
                const src = copyFrom.find((c) => c.id === e.target.value)
                if (!src) return
                // Only ids that still exist and are still bookable.
                const live = new Set(bookable.map((s) => s.id))
                onChange(src.service_ids.filter((id) => live.has(id)))
              }}
              className="rounded-lg border border-gray-300 bg-white px-2 py-1 text-xs text-gray-700"
            >
              <option value="">Copy from…</option>
              {copyFrom.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          )}
          {liveCount > 0 && (
            <button
              type="button"
              onClick={() => onChange([])}
              className="rounded-lg px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      <div className="max-h-64 overflow-y-auto rounded-xl border border-teal-100 bg-teal-50/40 p-2">
        {groups.map((g) => {
          const ids = g.rows.map((s) => s.id)
          const on = ids.filter((id) => chosen.has(id)).length
          const all = on === ids.length
          const isOpen = Boolean(openCats[g.title])
          return (
            <div key={g.title} className="mb-1 last:mb-0">
              <div className="flex items-center gap-2 rounded-lg px-1 py-1 hover:bg-white/70">
                <input
                  type="checkbox"
                  aria-label={`All ${g.title}`}
                  checked={all}
                  // Partly-selected is a real third state; without it a category with
                  // 3 of 15 ticked looks identical to one with none.
                  ref={(el) => {
                    if (el) el.indeterminate = on > 0 && !all
                  }}
                  onChange={() => setMany(ids, !all)}
                  className="h-4 w-4 shrink-0 rounded border-gray-300 text-teal-600 focus:ring-teal-500"
                />
                {/* Collapsed by default: eight category rows beat forty checkboxes, and
                    most people never need to open one. */}
                <button
                  type="button"
                  onClick={() => setOpenCats((p) => ({ ...p, [g.title]: !isOpen }))}
                  className="flex min-w-0 flex-1 items-center gap-1 text-left"
                  aria-expanded={isOpen}
                >
                  <ChevronRight
                    className={`h-3.5 w-3.5 shrink-0 text-gray-400 transition-transform ${
                      isOpen ? 'rotate-90' : ''
                    }`}
                  />
                  <span className="truncate text-sm font-medium text-gray-800">
                    {g.title}
                  </span>
                  <span className="shrink-0 text-xs text-gray-500">
                    {on ? `${on}/${ids.length}` : ids.length}
                  </span>
                </button>
              </div>

              {isOpen && (
                <div className="ml-6 space-y-1 border-l border-teal-100 pl-3 pt-1">
                  {g.rows.map((svc) => (
                    <label
                      key={svc.id}
                      className="flex cursor-pointer items-start gap-2 text-sm text-gray-800"
                    >
                      <input
                        type="checkbox"
                        checked={chosen.has(svc.id)}
                        onChange={() => setMany([svc.id], !chosen.has(svc.id))}
                        className="mt-0.5 h-4 w-4 shrink-0 rounded border-gray-300 text-teal-600 focus:ring-teal-500"
                      />
                      <span className="min-w-0">
                        <span className="block truncate">{svc.name}</span>
                        {(svc.duration_minutes > 0 || svc.price > 0) && (
                          <span className="block text-xs text-gray-500">
                            {svc.duration_minutes > 0 ? `${svc.duration_minutes} min` : ''}
                            {svc.duration_minutes > 0 && svc.price > 0 ? ' · ' : ''}
                            {svc.price > 0 ? `$${svc.price}` : ''}
                          </span>
                        )}
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
