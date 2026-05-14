/**
 * Format subscription / billing timestamps for UI using the UTC calendar date.
 * Values stored as midnight UTC (common from PostgreSQL) otherwise appear as the
 * previous local calendar day for US timezones (e.g. 2026-05-14T00:00:00Z → May 13 in PT).
 */
export function formatTrialEndDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, {
    timeZone: 'UTC',
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}
