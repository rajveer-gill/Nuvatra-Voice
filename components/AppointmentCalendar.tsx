'use client'

import { useCallback, useEffect, useState } from 'react'
import type { AxiosInstance } from 'axios'
import FullCalendar from '@fullcalendar/react'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import interactionPlugin from '@fullcalendar/interaction'

function eventColor(status: string): string {
  if (status === 'accepted' || status === 'confirmed' || status === 'completed') return '#16a34a'
  if (status === 'pending_review') return '#d97706'
  if (status === 'pending_customer') return '#0ea5e9'
  if (status === 'rejected' || status === 'cancelled') return '#dc2626'
  return '#6b7280'
}

export default function AppointmentCalendar({ api }: { api: AxiosInstance }) {
  const [events, setEvents] = useState<
    { id: string; title: string; start: string; backgroundColor?: string }[]
  >([])
  const [staffList, setStaffList] = useState<{ id: string; name: string }[]>([])
  const [staffFilter, setStaffFilter] = useState('')

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
      const params: Record<string, string> = { date_from: from, date_to: to }
      if (staffFilter) params.staff_id = staffFilter
      api.get('/api/appointments/calendar', { params }).then((r) => {
        const list = (r.data?.events || []) as {
          id: number
          name: string
          reason?: string
          date: string
          time?: string
          status: string
        }[]
        setEvents(
          list.map((a) => {
            const raw = (a.time || '09:00').trim()
            const t = raw.length >= 5 ? raw.slice(0, 5) : '09:00'
            return {
              id: String(a.id),
              title: `${a.name} — ${a.reason || 'Booking'}`,
              start: `${a.date}T${t}`,
              backgroundColor: eventColor(a.status),
            }
          })
        )
      })
    },
    [api, staffFilter]
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm font-medium text-gray-700">Staff filter</label>
        <select
          value={staffFilter}
          onChange={(e) => setStaffFilter(e.target.value)}
          className="cs-field-compact min-w-[12rem]"
        >
          <option value="">All staff</option>
          {staffList.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>
      <div className="fc-root rounded-xl border border-gray-200 bg-white p-2 shadow-inner [&_.fc]:font-sans">
        <FullCalendar
          plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
          initialView="timeGridWeek"
          headerToolbar={{
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay',
          }}
          slotMinTime="07:00:00"
          slotMaxTime="21:00:00"
          height="auto"
          events={events}
          datesSet={(arg) => {
            const from = arg.startStr.slice(0, 10)
            const endDay = new Date(arg.end)
            endDay.setMilliseconds(endDay.getMilliseconds() - 1)
            const to = endDay.toISOString().slice(0, 10)
            load(from, to)
          }}
        />
      </div>
      <p className="text-xs text-gray-500">
        Amber = needs your approval · Sky = customer confirming by text · Green = confirmed · Red = declined/cancelled
      </p>
    </div>
  )
}
