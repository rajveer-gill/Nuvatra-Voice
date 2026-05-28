'use client'

import { useCallback, useEffect, useState } from 'react'
import type { AxiosInstance } from 'axios'
import { motion, useReducedMotion } from 'framer-motion'
import { CalendarDays, Filter, Loader2 } from 'lucide-react'
import FullCalendar from '@fullcalendar/react'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import interactionPlugin from '@fullcalendar/interaction'
import type { EventContentArg } from '@fullcalendar/core'
import './appointments/calendar-theme.css'

const LEGEND = [
  { label: 'Needs approval', color: '#d97706' },
  { label: 'Awaiting text confirm', color: '#0ea5e9' },
  { label: 'Confirmed', color: '#16a34a' },
] as const

function eventColor(status: string): string {
  if (status === 'accepted' || status === 'confirmed' || status === 'completed') return '#16a34a'
  if (status === 'pending_review') return '#d97706'
  if (status === 'pending_customer') return '#0ea5e9'
  return '#6366f1'
}

function EventContent({ arg }: { arg: EventContentArg }) {
  const time = arg.timeText
  const title = arg.event.title
  return (
    <div className="flex h-full flex-col justify-center overflow-hidden px-0.5 py-0.5 leading-tight">
      {time ? <span className="text-[10px] font-bold opacity-90">{time}</span> : null}
      <span className="truncate text-[11px] font-semibold">{title}</span>
    </div>
  )
}

function addMinutesToIsoLocal(isoStart: string, minutes: number): string {
  const d = new Date(isoStart)
  if (Number.isNaN(d.getTime())) return isoStart
  d.setMinutes(d.getMinutes() + minutes)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export default function AppointmentCalendar({ api }: { api: AxiosInstance }) {
  const reduceMotion = useReducedMotion()
  const [events, setEvents] = useState<
    { id: string; title: string; start: string; end: string; backgroundColor?: string; borderColor?: string }[]
  >([])
  const [staffList, setStaffList] = useState<{ id: string; name: string }[]>([])
  const [staffFilter, setStaffFilter] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/api/business-info').then((r) => {
      const st = (r.data?.staff || []) as { id?: string; name?: string }[]
      setStaffList(
        st
          .filter((s) => s.id && s.name)
          .map((s) => ({ id: s.id as string, name: s.name as string }))
      )
    })
  }, [api])

  const load = useCallback(
    (from: string, to: string) => {
      setLoading(true)
      const params: Record<string, string> = { date_from: from, date_to: to }
      if (staffFilter) params.staff_id = staffFilter
      api
        .get('/api/appointments/calendar', { params })
        .then((r) => {
          const list = (r.data?.events || []) as {
            id: number
            name: string
            reason?: string
            date: string
            time?: string
            status: string
            duration_minutes?: number
          }[]
          setEvents(
            list.map((a) => {
              const raw = (a.time || '09:00').trim()
              const t = raw.length >= 5 ? raw.slice(0, 5) : '09:00'
              const color = eventColor(a.status)
              const reason = (a.reason || '').trim()
              const subtitle = reason && reason !== '—' ? reason : 'Booking'
              const duration = Math.max(5, Math.min(Number(a.duration_minutes) || 30, 480))
              const start = `${a.date}T${t}`
              return {
                id: String(a.id),
                title: `${a.name} — ${subtitle}`,
                start,
                end: addMinutesToIsoLocal(start, duration),
                backgroundColor: color,
                borderColor: color,
              }
            })
          )
        })
        .catch(() => setEvents([]))
        .finally(() => setLoading(false))
    },
    [api, staffFilter]
  )

  return (
    <motion.div
      initial={reduceMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      className="appointment-calendar space-y-4"
    >
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex items-center gap-2 text-zinc-300">
          <CalendarDays className="h-5 w-5 text-cyan-400" />
          <span className="text-sm font-semibold text-white">Schedule view</span>
          {loading && <Loader2 className="h-4 w-4 animate-spin text-cyan-400" aria-label="Loading" />}
        </div>
        {staffList.length > 1 ? (
          <div className="flex flex-wrap items-center gap-2">
            <Filter className="h-4 w-4 text-zinc-500" aria-hidden />
            <label htmlFor="cal-staff-filter" className="text-sm text-zinc-400">
              Stylist
            </label>
            <select
              id="cal-staff-filter"
              value={staffFilter}
              onChange={(e) => setStaffFilter(e.target.value)}
              className="min-w-[12rem] rounded-lg border border-white/10 bg-zinc-900 px-3 py-2 text-sm text-zinc-200 focus:border-cyan-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/30"
            >
              <option value="">All stylists</option>
              {staffList.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
        ) : null}
      </div>

      <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-zinc-950/80 p-3 shadow-inner shadow-black/20 sm:p-4">
        <div
          className="pointer-events-none absolute inset-0 bg-gradient-to-br from-cyan-500/5 via-transparent to-indigo-600/5"
          aria-hidden
        />
        <div className="relative [&_.fc]:min-h-[32rem]">
          <FullCalendar
            plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
            initialView="timeGridWeek"
            headerToolbar={{
              left: 'prev,next today',
              center: 'title',
              right: 'dayGridMonth,timeGridWeek,timeGridDay',
            }}
            buttonText={{
              today: 'Today',
              month: 'Month',
              week: 'Week',
              day: 'Day',
            }}
            slotMinTime="00:00:00"
            slotMaxTime="24:00:00"
            scrollTime="07:00:00"
            slotDuration="00:30:00"
            allDaySlot={false}
            nowIndicator
            height="auto"
            expandRows
            stickyHeaderDates
            dayMaxEvents={4}
            events={events}
            eventContent={(arg) => <EventContent arg={arg} />}
            eventClassNames={() => ['appointment-cal-event']}
            slotLabelFormat={{
              hour: 'numeric',
              minute: '2-digit',
              meridiem: 'short',
            }}
            eventTimeFormat={{
              hour: 'numeric',
              minute: '2-digit',
              meridiem: 'short',
            }}
            datesSet={(arg) => {
              const from = arg.startStr.slice(0, 10)
              const endDay = new Date(arg.end)
              endDay.setMilliseconds(endDay.getMilliseconds() - 1)
              const to = endDay.toISOString().slice(0, 10)
              load(from, to)
            }}
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        {LEGEND.map((item) => (
          <span
            key={item.label}
            className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-zinc-900/80 px-3 py-1 text-xs text-zinc-300"
          >
            <span
              className="h-2.5 w-2.5 rounded-full shadow-sm"
              style={{ backgroundColor: item.color, boxShadow: `0 0 8px ${item.color}66` }}
            />
            {item.label}
          </span>
        ))}
      </div>
    </motion.div>
  )
}
