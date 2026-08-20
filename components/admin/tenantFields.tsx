/** Shared field vocabulary for the admin tenant list.
 *
 * Split out when the tenant row became its own component: both the page and the row
 * need the phone input and the class strings, and duplicating them is how two
 * supposedly identical inputs drift apart.
 */

export const inputClass =
  'w-full rounded-lg border border-white/15 bg-zinc-950 px-3 py-2 text-zinc-100 placeholder:text-zinc-600 focus:border-cyan-500/50 focus:outline-none focus:ring-2 focus:ring-cyan-500/25'
export const selectClass =
  'rounded-lg border border-white/15 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100 focus:border-cyan-500/50 focus:outline-none focus:ring-2 focus:ring-cyan-500/25'

/** US A2P / Twilio numbers on this admin flow are NANP (+1). */
export const US_E164_PREFIX = '+1'

export function digitsOnly(s: string): string {
  return s.replace(/\D/g, '')
}

export function fullUsE164FromNationalInput(nationalRaw: string): string {
  return US_E164_PREFIX + digitsOnly(nationalRaw).slice(0, 10)
}

export function nationalDigitsForUsTwilioInput(full: string | null | undefined): string {
  const p = (full || '').trim()
  if (p.startsWith(US_E164_PREFIX)) return digitsOnly(p.slice(US_E164_PREFIX.length)).slice(0, 10)
  const d = digitsOnly(p)
  if (d.length === 11 && d.startsWith('1')) return d.slice(1, 11)
  return d.slice(0, 10)
}

export function isUsTenantTwilioDraft(raw: string | undefined | null): boolean {
  // Pending self-serve tenants have a null number until checkout completes — treat as US.
  return !raw || raw.startsWith(US_E164_PREFIX)
}

export function UsTwilioPhoneInput({
  value,
  onChange,
  placeholderNational = '5551234567',
  required,
  minNationalLength,
  autoComplete,
}: {
  value: string
  onChange: (fullE164: string) => void
  placeholderNational?: string
  required?: boolean
  minNationalLength?: number
  autoComplete?: string
}) {
  const national = nationalDigitsForUsTwilioInput(value)
  return (
    <div className="flex w-full overflow-hidden rounded-lg border border-white/15 bg-zinc-950 focus-within:border-cyan-500/50 focus-within:outline-none focus-within:ring-2 focus-within:ring-cyan-500/25">
      <span
        className="flex shrink-0 items-center border-r border-white/15 bg-zinc-900/80 px-3 py-2 text-sm text-zinc-400 tabular-nums"
        aria-hidden
      >
        {US_E164_PREFIX}
      </span>
      <input
        type="tel"
        required={required}
        minLength={minNationalLength}
        autoComplete={autoComplete}
        inputMode="numeric"
        placeholder={placeholderNational}
        className="min-w-0 flex-1 border-0 bg-transparent px-3 py-2 text-zinc-100 placeholder:text-zinc-600 focus:outline-none"
        value={national}
        onChange={(e) => onChange(fullUsE164FromNationalInput(e.target.value))}
      />
    </div>
  )
}
