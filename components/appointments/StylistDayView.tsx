'use client'

/** One day, one column per stylist.
 *
 * A salon day is concurrent by nature — four stylists working at once — and a single
 * time column stacks those into slivers: fifteen appointments turned customer names
 * into "Jar", "ado", "Eri". This is the layout the staff already read in Zenoti, and
 * it answers the question a receptionist actually asks, which is not "what is on at
 * 3pm" but "who is free at 3pm".
 *
 * Columns are a fixed width and scroll sideways rather than sharing the space, because
 * a column that shrinks with every extra stylist is the problem this replaces.
 */

import { useMemo } from 'react'
import type { Appointment } from '@/components/appointments/types'

export type StylistDayItem = {
  appointment: Appointment
  /** Minutes from midnight. */
  startMinutes: number
  endMinutes: number
  color: string
}

const UNASSIGNED = '__unassigned__'
const PX_PER_MIN = 1.1
const COL_WIDTH = 'minmax(11rem, 1fr)'

function label(min: number): string {
  const h = Math.floor(min / 60)
  const m = min % 60
  const period = h >= 12 ? 'pm' : 'am'
  const h12 = h % 12 === 0 ? 12 : h % 12
  return m === 0 ? `${h12}${period}` : `${h12}:${String(m).padStart(2, '0')}${period}`
}

/** Side-by-side lanes for anything that overlaps inside one stylist's column. A stylist
 *  can't be in two places, so an overlap is a data problem worth seeing, not hiding. */
function assignLanes(items: StylistDayItem[]) {
  const sorted = [...items].sort((a, b) => a.startMinutes - b.startMinutes)
  const laneEnds: number[] = []
  const placed = sorted.map((it) => {
    let lane = laneEnds.findIndex((end) => end <= it.startMinutes)
    if (lane === -1) {
      lane = laneEnds.length
      laneEnds.push(it.endMinutes)
    } else {
      laneEnds[lane] = it.endMinutes
    }
    return { it, lane }
  })
  return { placed, laneCount: Math.max(1, laneEnds.length) }
}

export function StylistDayView({
  items,
  staff,
  dayStartMinutes,
  dayEndMinutes,
  onSelect,
}: {
  items: StylistDayItem[]
  staff: { id: string; name: string }[]
  dayStartMinutes: number
  dayEndMinutes: number
  onSelect: (apt: Appointment) => void
}) {
  const columns = useMemo(() => {
    const byStaff = new Map<string, StylistDayItem[]>()
    for (const it of items) {
      const key = (it.appointment.staff_id || '').trim() || UNASSIGNED
      const list = byStaff.get(key)
      if (list) list.push(it)
      else byStaff.set(key, [it])
    }
    // Every rostered stylist gets a column even when empty — an empty column is the
    // answer to "who can take a walk-in", which a filtered list can't show.
    const cols = staff.map((s) => ({ key: s.id, name: s.name, items: byStaff.get(s.id) || [] }))
    const loose = byStaff.get(UNASSIGNED) || []
    if (loose.length) {
      cols.push({ key: UNASSIGNED, name: 'Unassigned', items: loose })
    }
    return cols
  }, [items, staff])

  const start = Math.min(dayStartMinutes, dayEndMinutes - 60)
  const totalMin = Math.max(60, dayEndMinutes - start)
  const bodyHeight = totalMin * PX_PER_MIN
  const firstHour = Math.floor(start / 60)
  const lastHour = Math.ceil(dayEndMinutes / 60)
  const hours = Array.from({ length: lastHour - firstHour }, (_, i) => (firstHour + i) * 60)

  if (!columns.length) {
    return (
      <p className="rounded-xl border border-dashed border-white/10 px-4 py-8 text-center text-sm text-zinc-500">
        Add team members in Settings to see the day by stylist.
      </p>
    )
  }

  const gridCols = `4.5rem repeat(${columns.length}, ${COL_WIDTH})`

  return (
    <div className="overflow-x-auto">
      <div className="min-w-max">
        {/* Header */}
        <div className="sticky top-0 z-20 grid bg-zinc-950/95 backdrop-blur" style={{ gridTemplateColumns: gridCols }}>
          <div className="border-b border-white/10" />
          {columns.map((c) => (
            <div
              key={c.key}
              className="truncate border-b border-l border-white/10 px-3 py-2 text-sm font-semibold text-zinc-200"
              title={c.name}
            >
              {c.name}
              <span className="ml-1.5 text-xs font-normal text-zinc-500">
                {c.items.length || '—'}
              </span>
            </div>
          ))}
        </div>

        {/* Body */}
        <div className="grid" style={{ gridTemplateColumns: gridCols }}>
          {/* Time gutter */}
          <div className="relative" style={{ height: bodyHeight }}>
            {hours.map((h) => (
              <div
                key={h}
                className="absolute right-2 -translate-y-1/2 text-[11px] tabular-nums text-zinc-500"
                style={{ top: (h - start) * PX_PER_MIN }}
              >
                {label(h)}
              </div>
            ))}
          </div>

          {columns.map((c) => {
            const { placed, laneCount } = assignLanes(c.items)
            return (
              <div
                key={c.key}
                className="relative border-l border-white/10"
                style={{ height: bodyHeight }}
              >
                {hours.map((h) => (
                  <div
                    key={h}
                    className="absolute inset-x-0 border-t border-white/[0.06]"
                    style={{ top: (h - start) * PX_PER_MIN }}
                  />
                ))}
                {placed.map(({ it, lane }) => {
                  const top = (it.startMinutes - start) * PX_PER_MIN
                  const height = Math.max(22, (it.endMinutes - it.startMinutes) * PX_PER_MIN)
                  const widthPct = 100 / laneCount
                  const svc = (it.appointment.reason || '').split(' — ')[0] || 'Booking'
                  return (
                    <button
                      key={it.appointment.id}
                      type="button"
                      onClick={() => onSelect(it.appointment)}
                      title={`${label(it.startMinutes)}–${label(it.endMinutes)} · ${it.appointment.name} · ${svc}`}
                      className="absolute overflow-hidden rounded-md px-2 py-1 text-left text-white shadow-sm ring-1 ring-black/20 transition hover:brightness-110 focus:outline-none focus:ring-2 focus:ring-cyan-400"
                      style={{
                        top,
                        height,
                        left: `calc(${lane * widthPct}% + 2px)`,
                        width: `calc(${widthPct}% - 4px)`,
                        backgroundColor: it.color,
                      }}
                    >
                      <span className="block truncate text-[11px] font-bold leading-tight opacity-95">
                        {label(it.startMinutes)}
                      </span>
                      <span className="block truncate text-xs font-semibold leading-tight">
                        {it.appointment.name}
                      </span>
                      {height > 44 && (
                        <span className="block truncate text-[11px] leading-tight opacity-90">
                          {svc}
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
