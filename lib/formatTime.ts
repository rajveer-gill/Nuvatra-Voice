/** Format HH:MM as 12-hour AM/PM (e.g. "13:00" -> "1:00 PM"). */
export function formatTimeHhmmToAmPm(hhmm: string | undefined): string {
  if (!hhmm || !hhmm.trim()) return hhmm || '—'
  const [hStr, mStr] = hhmm.trim().split(':')
  const h = parseInt(hStr || '0', 10)
  const m = parseInt(mStr || '0', 10)
  if (h === 0) return `12:${String(m).padStart(2, '0')} AM`
  if (h < 12) return `${h}:${String(m).padStart(2, '0')} AM`
  if (h === 12) return `12:${String(m).padStart(2, '0')} PM`
  return `${h - 12}:${String(m).padStart(2, '0')} PM`
}
