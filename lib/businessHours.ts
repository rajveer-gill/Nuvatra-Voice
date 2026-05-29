/**
 * Weekly business hours for Settings UI. Serialized to a readable string for the API / AI prompts.
 */

export const DAYS_FULL = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] as const
export const DAYS_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const

export type DayIndex = 0 | 1 | 2 | 3 | 4 | 5 | 6

export interface DaySlot {
  closed: boolean
  /** 24h "HH:MM" */
  open: string
  /** 24h "HH:MM" */
  close: string
}

export type WeeklySchedule = DaySlot[]

export const DEFAULT_OPEN = '09:00'
export const DEFAULT_CLOSE = '17:00'

export function defaultWeeklySchedule(): WeeklySchedule {
  return Array.from({ length: 7 }, (_, i) => ({
    closed: i >= 5,
    open: DEFAULT_OPEN,
    close: DEFAULT_CLOSE,
  }))
}

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

/** Parse "9", "9:30", "09:00", "17:30" to HH:MM */
export function normalizeTime24(raw: string): string | null {
  const s = raw.trim().toLowerCase().replace(/\./g, '')
  const ampm = /\s*(a|p)m?$/.exec(s)
  let base = s.replace(/\s*(a|p)\.?m\.?$/i, '').trim()
  const parts = base.split(':')
  let h = parseInt(parts[0] || '', 10)
  let m = parseInt(parts[1] || '0', 10)
  if (Number.isNaN(h)) return null
  if (Number.isNaN(m)) m = 0
  if (ampm) {
    const mer = ampm[1]?.toLowerCase()
    if (mer === 'p' && h < 12) h += 12
    if (mer === 'a' && h === 12) h = 0
  }
  if (h < 0 || h > 23 || m < 0 || m > 59) return null
  return `${pad2(h)}:${pad2(m)}`
}

/** Add 12h labels for display next to native time inputs */
export function formatTimeLabel(hhmm: string): string {
  const n = normalizeTime24(hhmm)
  if (!n) return ''
  const [hs, ms] = n.split(':').map((x) => parseInt(x, 10))
  const h12 = hs % 12 === 0 ? 12 : hs % 12
  const suf = hs >= 12 ? 'PM' : 'AM'
  return `${h12}:${pad2(ms)} ${suf}`
}

function expandDayRangeLabel(left: string): number[] | null {
  const a = left.trim().toLowerCase()
  const map: Record<string, number> = {
    monday: 0,
    mon: 0,
    tuesday: 1,
    tue: 1,
    tues: 1,
    wednesday: 2,
    wed: 2,
    thursday: 3,
    thu: 3,
    thur: 3,
    friday: 4,
    fri: 4,
    saturday: 5,
    sat: 5,
    sunday: 6,
    sun: 6,
  }
  const rangeParts = a.split(/\s*[–-]\s*/)
  if (rangeParts.length === 2) {
    const s = map[rangeParts[0]]
    const e = map[rangeParts[1]]
    if (s !== undefined && e !== undefined) {
      const out: number[] = []
      let i = s
      while (true) {
        out.push(i)
        if (i === e) break
        i = i === 6 ? 0 : i + 1
        if (out.length > 8) break
      }
      if (out.length && out[0] === s && out[out.length - 1] === e) return out
    }
  }
  const single = map[a.replace(/\.$/, '')]
  if (single !== undefined) return [single]
  return null
}

function splitPieces(text: string): string[] {
  const out: string[] = []
  for (const line of text.split(/\r?\n/)) {
    for (const segment of line.split(';')) {
      const t = segment.trim()
      if (t) out.push(t)
    }
  }
  return out
}

/** Pull first two times from a fragment like "9 AM – 5 PM" or "9:00-17:00" */
function extractTwoTimes(fragment: string): { open: string; close: string } | null {
  const f = fragment.replace(/\u2013/g, '-').replace(/–/g, '-').trim()
  const pieces = f.split(/\s*-\s*/)
  if (pieces.length >= 2) {
    const o = normalizeTime24(pieces[0])
    const c = normalizeTime24(pieces[pieces.length - 1])
    if (o && c) return { open: o, close: c }
  }
  const alt = f.match(/(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?|\d{1,2}:\d{2})/gi)
  if (alt && alt.length >= 2) {
    const o = normalizeTime24(alt[0])
    const c = normalizeTime24(alt[1])
    if (o && c) return { open: o, close: c }
  }
  return null
}

export interface ParseResult {
  schedule: WeeklySchedule
  /** If previous text could not be fully interpreted */
  warning?: string
}

/**
 * Best-effort parse from legacy free-text hours. Falls back to Mon–Fri 9–5 when empty or unusable.
 */
export function parseHoursToWeekly(text: string): ParseResult {
  const raw = text.trim()
  if (!raw) {
    return { schedule: defaultWeeklySchedule() }
  }

  const lower = raw.toLowerCase()
  if (
    /\b24\s*\/\s*7\b/.test(lower) ||
    /\b24-7\b/.test(lower) ||
    (lower.includes('24 hour') && lower.includes('day'))
  ) {
    const s = defaultWeeklySchedule().map((d) => ({
      ...d,
      closed: false,
      open: '00:00',
      close: '23:59',
    }))
    return { schedule: s }
  }

  const sched = defaultWeeklySchedule().map((d) => ({ ...d, closed: true }))
  let matchedAny = false

  for (const piece of splitPieces(raw)) {
    const colon = piece.indexOf(':')
    if (colon < 0) continue
    const left = piece.slice(0, colon).trim()
    const right = piece.slice(colon + 1).trim()
    if (!left || !right) continue

    const days = expandDayRangeLabel(left)
    if (!days?.length) continue

    if (/^closed\b/i.test(right)) {
      days.forEach((d) => {
        sched[d] = { closed: true, open: DEFAULT_OPEN, close: DEFAULT_CLOSE }
      })
      matchedAny = true
      continue
    }

    const times = extractTwoTimes(right)
    if (!times) continue
    days.forEach((d) => {
      sched[d] = { closed: false, open: times.open, close: times.close }
      matchedAny = true
    })
  }

  if (!matchedAny) {
    const looseTimes = extractTwoTimes(raw)
    if (looseTimes) {
      for (let d = 0; d < 5; d++) {
        sched[d] = { closed: false, open: looseTimes.open, close: looseTimes.close }
      }
      return {
        schedule: sched,
        warning: 'We could not detect which days those hours apply to. Applied Monday–Friday; adjust in the editor.',
      }
    }
    return {
      schedule: defaultWeeklySchedule(),
      warning: 'We could not read your previous hours text. Showing a common Mon–Fri schedule — please confirm.',
    }
  }

  return { schedule: sched }
}

function groupRanges(schedule: WeeklySchedule): { start: number; end: number; slot: DaySlot }[] {
  const groups: { start: number; end: number; slot: DaySlot }[] = []
  let i = 0
  while (i < 7) {
    const sig = schedule[i].closed
      ? `c`
      : `${schedule[i].open}|${schedule[i].close}`
    const start = i
    i++
    while (i < 7) {
      const s2 = schedule[i].closed
        ? `c`
        : `${schedule[i].open}|${schedule[i].close}`
      if (s2 !== sig) break
      i++
    }
    groups.push({ start, end: i - 1, slot: schedule[start] })
  }
  return groups
}

function formatDayRangeShort(start: number, end: number): string {
  if (start === end) return DAYS_FULL[start]
  if (start === 0 && end === 4) return 'Monday–Friday'
  if (start === 5 && end === 6) return 'Saturday–Sunday'
  if (start === 1 && end === 5) return 'Tuesday–Saturday'
  return `${DAYS_SHORT[start]}–${DAYS_SHORT[end]}`
}

/** Serialize to human-readable lines for the AI / API */
export function weeklyScheduleToString(schedule: WeeklySchedule): string {
  const allOpenSame =
    schedule.every((d) => !d.closed) &&
    schedule.every(
      (d) => d.open === schedule[0].open && d.close === schedule[0].close && !schedule[0].closed
    )
  if (allOpenSame && schedule[0].open === '00:00' && schedule[0].close === '23:59') {
    return 'Open 24 hours, 7 days a week.'
  }

  const lines: string[] = []
  for (const g of groupRanges(schedule)) {
    if (g.slot.closed) {
      lines.push(`${formatDayRangeShort(g.start, g.end)}: Closed`)
    } else {
      lines.push(
        `${formatDayRangeShort(g.start, g.end)}: ${formatTimeLabel(g.slot.open)} – ${formatTimeLabel(g.slot.close)}`
      )
    }
  }

  if (lines.length === 0) return 'Hours not set — contact us for availability.'

  return lines.join('\n')
}

/** One-line preview for the settings card */
export function summarizeSchedule(schedule: WeeklySchedule, maxLen = 96): string {
  const s = weeklyScheduleToString(schedule).replace(/\n/g, ' · ')
  if (s.length <= maxLen) return s
  return `${s.slice(0, maxLen - 1)}…`
}

function timeToMinutes(hhmm: string): number {
  const n = normalizeTime24(hhmm)
  if (!n) return -1
  const [h, m] = n.split(':').map((x) => parseInt(x, 10))
  return h * 60 + m
}

function minutesToSlotTime(totalMinutes: number): string {
  const h = Math.floor(totalMinutes / 60)
  const m = totalMinutes % 60
  return `${pad2(h)}:${pad2(m)}:00`
}

export interface CalendarSlotBounds {
  slotMinTime: string
  slotMaxTime: string
  scrollTime: string
}

export function isScheduleOpen247(schedule: WeeklySchedule): boolean {
  return (
    schedule.length === 7 &&
    schedule.every((d) => !d.closed && d.open === '00:00' && d.close === '23:59')
  )
}

/** Map JS Date.getDay() (0=Sun) to schedule index (0=Mon). */
export function jsDayToScheduleIndex(jsDay: number): DayIndex {
  return (jsDay === 0 ? 6 : jsDay - 1) as DayIndex
}

const FULL_DAY_BOUNDS: CalendarSlotBounds = {
  slotMinTime: '00:00:00',
  slotMaxTime: '24:00:00',
  scrollTime: '07:00:00',
}

function boundsFromOpenClose(open: string, close: string): CalendarSlotBounds | null {
  const o = timeToMinutes(open)
  const c = timeToMinutes(close)
  if (o < 0 || c <= o) return null
  return {
    slotMinTime: minutesToSlotTime(o),
    slotMaxTime: minutesToSlotTime(c),
    scrollTime: minutesToSlotTime(o),
  }
}

/** Union of open hours across all open days (week view). */
export function calendarSlotBoundsForWeek(schedule: WeeklySchedule): CalendarSlotBounds {
  if (isScheduleOpen247(schedule)) return FULL_DAY_BOUNDS

  let minOpen = 24 * 60
  let maxClose = 0
  let anyOpen = false

  for (const d of schedule) {
    if (d.closed) continue
    anyOpen = true
    const o = timeToMinutes(d.open)
    const c = timeToMinutes(d.close)
    if (o >= 0) minOpen = Math.min(minOpen, o)
    if (c >= 0) maxClose = Math.max(maxClose, c)
  }

  if (!anyOpen || minOpen >= maxClose) {
    return boundsFromOpenClose(DEFAULT_OPEN, DEFAULT_CLOSE) ?? FULL_DAY_BOUNDS
  }

  return {
    slotMinTime: minutesToSlotTime(minOpen),
    slotMaxTime: minutesToSlotTime(maxClose),
    scrollTime: minutesToSlotTime(minOpen),
  }
}

/** Hours for a single day (day view). Closed days fall back to the week union. */
export function calendarSlotBoundsForDay(
  schedule: WeeklySchedule,
  dayIndex: DayIndex
): CalendarSlotBounds {
  const d = schedule[dayIndex]
  if (!d || d.closed) return calendarSlotBoundsForWeek(schedule)
  if (d.open === '00:00' && d.close === '23:59') return FULL_DAY_BOUNDS
  return boundsFromOpenClose(d.open, d.close) ?? calendarSlotBoundsForWeek(schedule)
}

const SLOT_TIME_RE = /^(\d{1,2}):(\d{2})/

function slotTimeToMinutes(slotTime: string): number {
  const m = slotTime.match(SLOT_TIME_RE)
  if (!m) return 0
  return parseInt(m[1], 10) * 60 + parseInt(m[2], 10)
}

/** Pixel height for FullCalendar time-grid (30-min slots, toolbar + headers). */
export function calendarHeightFromSlotBounds(bounds: CalendarSlotBounds): number {
  const min = slotTimeToMinutes(bounds.slotMinTime)
  let max = slotTimeToMinutes(bounds.slotMaxTime)
  if (max <= min) max = min + 8 * 60
  const halfHourSlots = Math.max(2, Math.ceil((max - min) / 30))
  const slotPx = 56
  const chromePx = 148
  return Math.min(960, Math.max(440, halfHourSlots * slotPx + chromePx))
}
