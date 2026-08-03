'use client'

/** Import a service menu from a spreadsheet.
 *
 * Salons coming from another booking system can export their services to Excel, and
 * retyping fifty of them is the difference between onboarding in minutes and giving
 * up. The file is parsed server-side and shown for review — nothing is saved until
 * the normal Save on the Settings page, so there's one write path for services.
 *
 * Add-ons are guessed (a charge with no duration, or a name that says so) and
 * pre-ticked. It's a heuristic, so every row is editable before import. */

import { useRef, useState } from 'react'
import type { AxiosInstance } from 'axios'
import { AlertTriangle, Loader2, Upload, X } from 'lucide-react'
import type { ServiceRow } from '@/components/settings/StructuredListEditors'

type ParsedService = {
  name: string
  price: number
  duration_minutes: number
  category?: string
  code?: string
  is_addon: boolean
  /** Services this add-on was suggested to belong with, read from notes elsewhere in
   *  the workbook. Names here, mapped to ids at import once rows have ids. */
  applies_to_names?: string[]
}

export function ImportServicesButton({
  api,
  existing,
  onImport,
}: {
  api: AxiosInstance
  existing: ServiceRow[]
  onImport: (rows: ServiceRow[]) => void
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [rows, setRows] = useState<ParsedService[] | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [sheet, setSheet] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const upload = async (file: File) => {
    setBusy(true)
    setError(null)
    try {
      const body = new FormData()
      body.append('file', file)
      const { data } = await api.post('/api/business-info/services/import', body, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setRows(data.services || [])
      setWarnings(data.warnings || [])
      setSheet(data.sheet || '')
      if (!(data.services || []).length && !(data.warnings || []).length) {
        setError('No services were found in that file.')
      }
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      setError(typeof d === 'string' ? d : 'Could not read that file.')
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const close = () => {
    setRows(null)
    setWarnings([])
    setError(null)
  }

  /** Every field is correctable before anything is saved. Parsing a stranger's
   *  spreadsheet is guesswork, and this file in particular has no prices at all —
   *  typing them here beats opening 51 services one at a time afterwards. */
  const patch = (i: number, next: Partial<ParsedService>) =>
    setRows((prev) => (prev || []).map((r, ix) => (ix === i ? { ...r, ...next } : r)))

  const commit = () => {
    if (!rows) return
    // Skip anything already on the list — importing twice shouldn't duplicate a menu.
    const seen = new Set(existing.map((s) => s.name.trim().toLowerCase()))
    // Keep each new row paired with the parsed row it came from, so the suggested
    // links can be resolved without re-deriving the filter and hoping indexes line up.
    const pairs = rows
      .filter((r) => r.name.trim() && !seen.has(r.name.trim().toLowerCase()))
      .map((r) => ({
        source: r,
        row: {
          id: crypto.randomUUID(),
          name: r.name,
          price: r.price,
          // An add-on legitimately has no duration of its own; a bookable service
          // needs one, and the editor's own minimum is 5.
          duration_minutes: r.is_addon
            ? Math.max(0, r.duration_minutes)
            : Math.max(5, r.duration_minutes),
          is_addon: r.is_addon,
          applies_to_service_ids: [] as string[],
        } satisfies ServiceRow,
      }))
    // Suggestions arrive as names, because ids only exist now. Resolve against the
    // whole menu — an add-on can be linked to a service that was already there, not
    // just one imported in this batch.
    const idByName = new Map(
      [...existing, ...pairs.map((p) => p.row)].map((s) => [s.name.trim().toLowerCase(), s.id])
    )
    for (const { source, row } of pairs) {
      if (!row.is_addon || !source.applies_to_names?.length) continue
      row.applies_to_service_ids = source.applies_to_names
        .map((n) => idByName.get(n.trim().toLowerCase()))
        .filter((x): x is string => Boolean(x))
    }
    onImport([...existing, ...pairs.map((p) => p.row)])
    close()
  }

  const newCount = rows
    ? rows.filter(
        (r) =>
          r.name.trim() &&
          !existing.some((s) => s.name.trim().toLowerCase() === r.name.trim().toLowerCase())
      ).length
    : 0

  return (
    <>
      <input
        ref={fileRef}
        type="file"
        accept=".xlsx,.xls,.csv"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) void upload(f)
        }}
      />
      <button
        type="button"
        onClick={() => fileRef.current?.click()}
        disabled={busy}
        className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
        {busy ? 'Reading…' : 'Import from file'}
      </button>

      {error && !rows && (
        <p className="mt-1 text-xs text-red-600">{error}</p>
      )}

      {rows && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          role="dialog"
          aria-modal="true"
        >
          <div className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-2xl bg-white p-6 shadow-2xl">
            <div className="mb-3 flex items-start justify-between">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">
                  Import {newCount} service{newCount === 1 ? '' : 's'}
                </h3>
                <p className="text-xs text-gray-600">
                  {sheet && `From the “${sheet}” sheet. `}
                  Everything here is editable — fix any name, price or duration before
                  importing. Tick anything that&rsquo;s an add-on and the receptionist
                  won&rsquo;t book it on its own.
                </p>
              </div>
              <button
                type="button"
                onClick={close}
                aria-label="Close"
                className="rounded p-1 text-gray-400 hover:text-gray-700"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {warnings.map((w) => (
              <div
                key={w}
                className="mb-2 flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800"
              >
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>{w}</span>
              </div>
            ))}

            <div className="flex-1 overflow-y-auto rounded-lg border border-gray-200">
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-gray-50 text-xs text-gray-600">
                  <tr>
                    <th className="px-3 py-2 font-medium">Service</th>
                    <th className="w-20 px-3 py-2 text-right font-medium">Price</th>
                    <th className="w-20 px-3 py-2 text-right font-medium">Min</th>
                    <th className="w-24 px-3 py-2 text-center font-medium">Add-on</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const dupe = existing.some(
                      (s) => s.name.trim().toLowerCase() === r.name.trim().toLowerCase()
                    )
                    return (
                      <tr
                        key={`${r.name}-${i}`}
                        className={`border-t border-gray-100 ${dupe ? 'opacity-40' : ''}`}
                      >
                        <td className="px-3 py-1.5">
                          <input
                            type="text"
                            value={r.name}
                            disabled={dupe}
                            onChange={(e) => patch(i, { name: e.target.value })}
                            className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-gray-900 hover:border-gray-200 focus:border-primary-500 focus:bg-white focus:outline-none disabled:text-gray-400"
                          />
                          {dupe && (
                            <span className="ml-1 text-[10px] uppercase text-gray-500">
                              already added
                            </span>
                          )}
                          {r.is_addon && r.applies_to_names?.length ? (
                            <span className="mt-0.5 block pl-1 text-[11px] text-indigo-700">
                              with: {r.applies_to_names.slice(0, 3).join(', ')}
                              {r.applies_to_names.length > 3
                                ? ` +${r.applies_to_names.length - 3} more`
                                : ''}
                            </span>
                          ) : null}
                        </td>
                        <td className="px-3 py-1.5">
                          <input
                            type="number"
                            min={0}
                            step={0.01}
                            value={r.price || ''}
                            placeholder="—"
                            disabled={dupe}
                            onChange={(e) => patch(i, { price: parseFloat(e.target.value) || 0 })}
                            className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-right text-gray-700 hover:border-gray-200 focus:border-primary-500 focus:bg-white focus:outline-none disabled:text-gray-400"
                          />
                        </td>
                        <td className="px-3 py-1.5">
                          <input
                            type="number"
                            min={0}
                            max={480}
                            value={r.duration_minutes || ''}
                            placeholder="—"
                            disabled={dupe}
                            onChange={(e) =>
                              patch(i, { duration_minutes: parseInt(e.target.value, 10) || 0 })
                            }
                            className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-right text-gray-700 hover:border-gray-200 focus:border-primary-500 focus:bg-white focus:outline-none disabled:text-gray-400"
                          />
                        </td>
                        <td className="px-3 py-1.5 text-center">
                          <input
                            type="checkbox"
                            checked={r.is_addon}
                            disabled={dupe}
                            onChange={(e) => patch(i, { is_addon: e.target.checked })}
                            className="h-4 w-4 rounded border-gray-300 text-primary-600"
                          />
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={close}
                className="rounded-lg px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={commit}
                disabled={newCount === 0}
                className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
              >
                {newCount ? `Add ${newCount} service${newCount === 1 ? '' : 's'}` : 'Nothing new'}
              </button>
            </div>
            <p className="mt-2 text-right text-[11px] text-gray-500">
              They&rsquo;re added to the list below — press Save to keep them.
            </p>
          </div>
        </div>
      )}
    </>
  )
}
