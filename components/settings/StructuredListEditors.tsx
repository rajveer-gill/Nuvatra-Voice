'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  CheckCircle2,
  ChevronDown,
  Clock,
  DollarSign,
  Plus,
  Pencil,
  Tag,
  Trash2,
  X,
} from 'lucide-react'

export type ServiceRow = {
  id: string
  name: string
  price: number
  duration_minutes: number
  /** An extra that attaches to a real service (conditioner, hot tools, master-stylist
   *  charge) and can never be the whole appointment. Enforced in the booking path. */
  is_addon?: boolean
  /** Which services this add-on may be offered with. Empty = any service. */
  applies_to_service_ids?: string[]
}
export type SpecialRow = { id: string; title: string; description: string; valid_until: string }
export type RuleRow = { id: string; rule_text: string }

function normalizeServices(raw: unknown): ServiceRow[] {
  if (!Array.isArray(raw)) return []
  if (raw.length && typeof raw[0] === 'object' && raw[0] !== null && 'name' in (raw[0] as object)) {
    return (raw as ServiceRow[]).map((s) => ({
      id: (s.id || crypto.randomUUID()).toString(),
      name: String(s.name ?? ''),
      price: typeof s.price === 'number' ? s.price : parseFloat(String(s.price ?? 0)) || 0,
      duration_minutes:
        typeof s.duration_minutes === 'number' ? s.duration_minutes : parseInt(String(s.duration_minutes ?? 30), 10) || 30,
      // Carried through, or every Settings save would silently un-flag add-ons.
      is_addon: Boolean(s.is_addon),
      applies_to_service_ids: Array.isArray(s.applies_to_service_ids)
        ? s.applies_to_service_ids.map(String)
        : [],
    }))
  }
  return (raw as string[])
    .filter((x) => String(x).trim())
    .map((line) => ({
      id: crypto.randomUUID(),
      name: String(line).trim(),
      price: 0,
      duration_minutes: 30,
    }))
}

function normalizeSpecials(raw: unknown): SpecialRow[] {
  if (!Array.isArray(raw)) return []
  if (raw.length && typeof raw[0] === 'object' && raw[0] !== null && 'title' in (raw[0] as object)) {
    return (raw as SpecialRow[]).map((s) => ({
      id: (s.id || crypto.randomUUID()).toString(),
      title: String(s.title ?? ''),
      description: String(s.description ?? ''),
      valid_until: String(s.valid_until ?? ''),
    }))
  }
  return (raw as string[])
    .filter((x) => String(x).trim())
    .map((line) => ({
      id: crypto.randomUUID(),
      title: String(line).trim(),
      description: '',
      valid_until: '',
    }))
}

function normalizeRules(raw: unknown): RuleRow[] {
  if (!Array.isArray(raw)) return []
  if (raw.length && typeof raw[0] === 'object' && raw[0] !== null && 'rule_text' in (raw[0] as object)) {
    return (raw as RuleRow[]).map((s) => ({
      id: (s.id || crypto.randomUUID()).toString(),
      rule_text: String(s.rule_text ?? ''),
    }))
  }
  return (raw as string[])
    .filter((x) => String(x).trim())
    .map((line) => ({
      id: crypto.randomUUID(),
      rule_text: String(line).trim(),
    }))
}

export { normalizeServices, normalizeSpecials, normalizeRules }

type ModalProps = { open: boolean; onClose: () => void; children: React.ReactNode; title: string }

function Modal({ open, onClose, title, children }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open) {
      if (!el.open) el.showModal()
    } else {
      el.close()
    }
  }, [open])

  return (
    <dialog
      ref={ref}
      className="rounded-2xl border border-gray-200 bg-white p-0 shadow-2xl backdrop:bg-black/40 max-w-lg w-[calc(100%-2rem)]"
      onClose={onClose}
    >
      <div className="flex items-center justify-between border-b border-gray-100 px-5 py-3">
        <h3 className="font-semibold text-gray-900">{title}</h3>
        <button type="button" className="rounded-lg p-2 hover:bg-gray-100" onClick={onClose} aria-label="Close">
          <X className="h-5 w-5 text-gray-600" />
        </button>
      </div>
      <div className="px-5 py-4">{children}</div>
    </dialog>
  )
}

/** How many services each group shows before "Show all". */
const PREVIEW_COUNT = 3

export function ServicesEditor({
  items,
  onChange,
  required = false,
  importSlot,
}: {
  items: ServiceRow[]
  onChange: (next: ServiceRow[]) => void
  required?: boolean
  /** Optional "Import from file" control, injected so this editor stays free of
   *  API/auth concerns. */
  importSlot?: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  const [edit, setEdit] = useState<ServiceRow | null>(null)
  /** Which groups are fully expanded. Collapsed by default — see the button below. */
  const [showAll, setShowAll] = useState<Record<string, boolean>>({})
  const ready = items.length > 0

  const remove = (id: string) => {
    onChange(items.filter((x) => x.id !== id))
  }

  const nameById = useMemo(() => new Map(items.map((s) => [s.id, s.name])), [items])
  const groups = useMemo(() => {
    const addons = items.filter((s) => s.is_addon)
    return [
      {
        key: 'services',
        title: 'Services',
        hint: 'Booked on their own',
        rows: items.filter((s) => !s.is_addon),
      },
      {
        key: 'addons',
        title: 'Add-ons',
        hint: 'Added to a service — never booked alone',
        rows: addons,
      },
    ].filter((g) => g.rows.length > 0 || g.key === 'services')
  }, [items])
  /** A shop with no add-ons doesn't need to be taught the distinction. */
  const showGroupHeadings = groups.length > 1

  return (
    <div className="md:col-span-2 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <span className="flex items-center gap-1.5 text-sm font-medium text-gray-700">
            Services
            {required && (
              <>
                <span className="text-rose-500" aria-label="required">*</span>
                <span
                  className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                    ready ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'
                  }`}
                >
                  {ready ? (
                    <>
                      <CheckCircle2 className="h-3 w-3" aria-hidden /> Ready
                    </>
                  ) : (
                    <>
                      <span className="relative flex h-1.5 w-1.5" aria-hidden>
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
                        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-amber-500" />
                      </span>
                      Action needed
                    </>
                  )}
                </span>
              </>
            )}
          </span>
          {required && !ready && (
            <p className="mt-0.5 text-xs text-gray-500">
              Required — your AI receptionist won&apos;t take calls until you add at least one service.
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {importSlot}
          <button
            type="button"
            onClick={() => {
              setEdit({
                id: crypto.randomUUID(),
                name: '',
                price: 0,
                duration_minutes: 30,
                is_addon: false,
              })
              setOpen(true)
            }}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-1.5 text-sm font-medium text-white shadow hover:bg-primary-700"
          >
            <Plus className="h-4 w-4" />
            Add service
          </button>
        </div>
      </div>
      {/* Two lists, because these are two different things: one is an appointment,
          the other is a charge that rides along with one. After importing fifty rows
          from a spreadsheet, telling them apart at a glance is the whole point. */}
      {groups.map((g) => {
        const expandedGroup = Boolean(showAll[g.key])
        const visible = expandedGroup ? g.rows : g.rows.slice(0, PREVIEW_COUNT)
        return (
        <div key={g.key}>
          {showGroupHeadings && (
            <div className="mb-2 mt-4 flex items-baseline gap-2 first:mt-0">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                {g.title} ({g.rows.length})
              </h4>
              <span className="text-xs text-gray-500">{g.hint}</span>
            </div>
          )}
          <ul className="space-y-2">
            <AnimatePresence initial={false}>
              {visible.map((s) => {
                const linked = (s.applies_to_service_ids || [])
                  .map((id) => nameById.get(id))
                  .filter(Boolean) as string[]
                return (
                  <motion.li
                    key={s.id}
                    layout
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    className={`flex flex-wrap items-center justify-between gap-2 rounded-xl border px-4 py-3 ${
                      s.is_addon
                        ? 'border-indigo-200 bg-indigo-50/50'
                        : 'border-gray-200 bg-gray-50/80'
                    }`}
                  >
                    {/* The whole row opens the editor — the pencil alone was easy to
                        miss on a list this long. */}
                    <button
                      type="button"
                      onClick={() => {
                        setEdit(s)
                        setOpen(true)
                      }}
                      className="min-w-0 flex-1 rounded-lg text-left focus:outline-none focus:ring-2 focus:ring-primary-500"
                    >
                      <p className="flex flex-wrap items-center gap-2 font-medium text-gray-900">
                        {s.name || 'Untitled'}
                        {s.is_addon && (
                          <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-indigo-700">
                            Add-on
                          </span>
                        )}
                      </p>
                      <p className="text-xs text-gray-600">
                        ${Number(s.price).toFixed(2)} · {s.duration_minutes} min
                      </p>
                      {s.is_addon && (
                        <p className="mt-0.5 text-xs text-indigo-700">
                          {linked.length
                            ? `Goes with: ${linked.slice(0, 3).join(', ')}${
                                linked.length > 3 ? ` +${linked.length - 3} more` : ''
                              }`
                            : 'Goes with any service'}
                        </p>
                      )}
                    </button>
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-gray-600 hover:bg-gray-200"
                        onClick={() => {
                          setEdit(s)
                          setOpen(true)
                        }}
                      >
                        <Pencil className="h-4 w-4" />
                        Edit
                      </button>
                      <button
                        type="button"
                        className="rounded-lg p-2 text-red-600 hover:bg-red-50"
                        onClick={() => remove(s.id)}
                        aria-label={`Remove ${s.name || 'service'}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </motion.li>
                )
              })}
            </AnimatePresence>
          </ul>
          {/* A 39-service menu buries everything below it on the Settings page, and
              nobody scrolls a list they aren't looking through. */}
          {g.rows.length > PREVIEW_COUNT && (
            <button
              type="button"
              onClick={() => setShowAll((p) => ({ ...p, [g.key]: !expandedGroup }))}
              className="mt-2 inline-flex w-full items-center justify-center gap-1.5 rounded-xl border border-dashed border-gray-300 px-4 py-2 text-sm font-medium text-gray-600 hover:border-gray-400 hover:bg-gray-50"
            >
              <ChevronDown
                className={`h-4 w-4 transition-transform ${expandedGroup ? 'rotate-180' : ''}`}
              />
              {expandedGroup
                ? 'Show fewer'
                : `Show all ${g.rows.length} ${g.title.toLowerCase()}`}
            </button>
          )}
        </div>
        )
      })}
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={edit && items.some((x) => x.id === edit.id) ? 'Edit service' : 'New service'}
      >
        {edit && (
          <ServiceForm
            key={edit.id}
            initial={edit}
            allServices={items}
            onSave={(row) => {
              const next = [...items]
              const ix = next.findIndex((x) => x.id === row.id)
              if (ix >= 0) next[ix] = row
              else next.push(row)
              onChange(next)
              // Saving a service and not seeing it reads as the save having failed.
              // If it lands outside the collapsed window, open its group.
              const posInGroup = next
                .filter((x) => Boolean(x.is_addon) === Boolean(row.is_addon))
                .findIndex((x) => x.id === row.id)
              if (posInGroup >= PREVIEW_COUNT) {
                setShowAll((p) => ({ ...p, [row.is_addon ? 'addons' : 'services']: true }))
              }
              setOpen(false)
              setEdit(null)
            }}
            onCancel={() => setOpen(false)}
          />
        )}
      </Modal>
    </div>
  )
}

function ServiceForm({
  initial,
  allServices,
  onSave,
  onCancel,
}: {
  initial: ServiceRow
  /** Everything on the menu, so an add-on can say which services it belongs with. */
  allServices: ServiceRow[]
  onSave: (row: ServiceRow) => void
  onCancel: () => void
}) {
  const [name, setName] = useState(initial.name)
  const [price, setPrice] = useState(initial.price)
  const [dur, setDur] = useState(initial.duration_minutes)
  const [isAddon, setIsAddon] = useState(Boolean(initial.is_addon))
  const [appliesTo, setAppliesTo] = useState<string[]>(initial.applies_to_service_ids || [])
  // Only real services can host an add-on — an add-on can't attach to another add-on.
  const hostServices = allServices.filter((s) => !s.is_addon && s.id !== initial.id && s.name.trim())
  const toggleHost = (id: string) =>
    setAppliesTo((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  return (
    <div className="space-y-4">
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-600">Service name</label>
        <input className="cs-field w-full" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Haircut" />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1 flex items-center gap-1 text-xs font-medium text-gray-600">
            <DollarSign className="h-3 w-3" /> Price (USD)
          </label>
          <input
            type="number"
            min={0}
            step={0.01}
            className="cs-field w-full"
            value={price}
            onChange={(e) => setPrice(parseFloat(e.target.value) || 0)}
          />
        </div>
        <div>
          <label className="mb-1 flex items-center gap-1 text-xs font-medium text-gray-600">
            <Clock className="h-3 w-3" /> Duration (min)
          </label>
          <input
            type="number"
            min={5}
            max={480}
            className="cs-field w-full"
            value={dur}
            onChange={(e) => setDur(parseInt(e.target.value, 10) || 30)}
          />
        </div>
      </div>
      <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-gray-200 bg-gray-50/80 p-3">
        <input
          type="checkbox"
          checked={isAddon}
          onChange={(e) => setIsAddon(e.target.checked)}
          className="mt-0.5 h-4 w-4 rounded border-gray-300 text-primary-600"
        />
        <span>
          <span className="block text-sm font-medium text-gray-800">
            This is an add-on
          </span>
          <span className="block text-xs text-gray-600">
            Something added to another service — a conditioner, hot tools, a
            master-stylist charge. The receptionist will never book it on its own; it
            asks which service it goes with.
          </span>
        </span>
      </label>
      {isAddon && hostServices.length > 0 && (
        <div className="rounded-lg border border-gray-200 p-3">
          <p className="text-sm font-medium text-gray-800">Which services can it go with?</p>
          <p className="mb-2 text-xs text-gray-600">
            Leave all unticked if it can go with anything. Tick some to restrict it — e.g.
            a master-stylist charge for chemical services only.
          </p>
          <div className="max-h-44 space-y-1 overflow-y-auto">
            {hostServices.map((s) => (
              <label key={s.id} className="flex cursor-pointer items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={appliesTo.includes(s.id)}
                  onChange={() => toggleHost(s.id)}
                  className="h-4 w-4 rounded border-gray-300 text-primary-600"
                />
                {s.name}
              </label>
            ))}
          </div>
          <p className="mt-2 text-xs text-gray-500">
            {appliesTo.length === 0
              ? 'Currently: goes with any service.'
              : `Currently: ${appliesTo.length} service${appliesTo.length === 1 ? '' : 's'} only.`}
          </p>
        </div>
      )}
      <div className="flex justify-end gap-2 pt-2">
        <button type="button" className="rounded-lg px-4 py-2 text-sm text-gray-700 hover:bg-gray-100" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
          onClick={() =>
            onSave({
              ...initial,
              name,
              price,
              duration_minutes: dur,
              is_addon: isAddon,
              // Restrictions only mean anything for an add-on; clear them otherwise so
              // a service that stops being an add-on doesn't keep stale references.
              applies_to_service_ids: isAddon ? appliesTo : [],
            })
          }
        >
          Save
        </button>
      </div>
    </div>
  )
}

export function SpecialsEditor({
  items,
  onChange,
}: {
  items: SpecialRow[]
  onChange: (next: SpecialRow[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [edit, setEdit] = useState<SpecialRow | null>(null)

  return (
    <div className="md:col-span-2 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label className="block text-sm font-medium text-gray-700">Specials / promotions</label>
        <button
          type="button"
          onClick={() => {
            setEdit({ id: crypto.randomUUID(), title: '', description: '', valid_until: '' })
            setOpen(true)
          }}
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-1.5 text-sm font-medium text-white shadow hover:bg-primary-700"
        >
          <Plus className="h-4 w-4" />
          Add special
        </button>
      </div>
      <ul className="space-y-2">
        {items.map((s) => (
          <li
            key={s.id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-gray-200 bg-gray-50/80 px-4 py-3"
          >
            <div>
              <p className="font-medium text-gray-900">{s.title || 'Untitled'}</p>
              {s.description ? <p className="text-xs text-gray-600 line-clamp-2">{s.description}</p> : null}
              {s.valid_until ? <p className="text-xs text-amber-700">Until {s.valid_until}</p> : null}
            </div>
            <div className="flex gap-1">
              <button
                type="button"
                className="rounded-lg p-2 text-gray-600 hover:bg-gray-200"
                onClick={() => {
                  setEdit(s)
                  setOpen(true)
                }}
              >
                <Pencil className="h-4 w-4" />
              </button>
              <button type="button" className="rounded-lg p-2 text-red-600 hover:bg-red-50" onClick={() => onChange(items.filter((x) => x.id !== s.id))}>
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </li>
        ))}
      </ul>
      <Modal open={open} onClose={() => setOpen(false)} title="Special / promotion">
        {edit && (
          <SpecialForm
            initial={edit}
            onSave={(row) => {
              const next = [...items]
              const ix = next.findIndex((x) => x.id === row.id)
              if (ix >= 0) next[ix] = row
              else next.push(row)
              onChange(next)
              setOpen(false)
              setEdit(null)
            }}
            onCancel={() => setOpen(false)}
          />
        )}
      </Modal>
    </div>
  )
}

function SpecialForm({
  initial,
  onSave,
  onCancel,
}: {
  initial: SpecialRow
  onSave: (row: SpecialRow) => void
  onCancel: () => void
}) {
  const [title, setTitle] = useState(initial.title)
  const [description, setDescription] = useState(initial.description)
  const [validUntil, setValidUntil] = useState(initial.valid_until)
  return (
    <div className="space-y-4">
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-600">Title</label>
        <input className="cs-field w-full" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Summer glow package" />
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-600">Description (optional)</label>
        <textarea className="cs-field w-full min-h-[72px]" value={description} onChange={(e) => setDescription(e.target.value)} />
      </div>
      <div>
        <label className="mb-1 flex items-center gap-1 text-xs font-medium text-gray-600">
          <Tag className="h-3 w-3" /> Valid until (optional)
        </label>
        <input type="date" className="cs-field w-full" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} />
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <button type="button" className="rounded-lg px-4 py-2 text-sm text-gray-700 hover:bg-gray-100" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          disabled={!title.trim()}
          className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          onClick={() => onSave({ ...initial, title: title.trim(), description: description.trim(), valid_until: validUntil })}
        >
          Save
        </button>
      </div>
    </div>
  )
}

export function RulesEditor({
  items,
  onChange,
}: {
  items: RuleRow[]
  onChange: (next: RuleRow[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [edit, setEdit] = useState<RuleRow | null>(null)

  return (
    <div className="md:col-span-2 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label className="block text-sm font-medium text-gray-700">Booking / appointment rules</label>
        <button
          type="button"
          onClick={() => {
            setEdit({ id: crypto.randomUUID(), rule_text: '' })
            setOpen(true)
          }}
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-1.5 text-sm font-medium text-white shadow hover:bg-primary-700"
        >
          <Plus className="h-4 w-4" />
          Add rule
        </button>
      </div>
      <ul className="space-y-2">
        {items.map((s) => (
          <li key={s.id} className="flex items-start justify-between gap-2 rounded-xl border border-gray-200 bg-gray-50/80 px-4 py-3">
            <p className="text-sm text-gray-800">{s.rule_text}</p>
            <div className="flex gap-1 shrink-0">
              <button type="button" className="rounded-lg p-2 text-gray-600 hover:bg-gray-200" onClick={() => { setEdit(s); setOpen(true) }}>
                <Pencil className="h-4 w-4" />
              </button>
              <button type="button" className="rounded-lg p-2 text-red-600 hover:bg-red-50" onClick={() => onChange(items.filter((x) => x.id !== s.id))}>
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </li>
        ))}
      </ul>
      <Modal open={open} onClose={() => setOpen(false)} title="Booking rule">
        {edit && (
          <RuleForm
            initial={edit}
            onSave={(row) => {
              const next = [...items]
              const ix = next.findIndex((x) => x.id === row.id)
              if (ix >= 0) next[ix] = row
              else next.push(row)
              onChange(next)
              setOpen(false)
              setEdit(null)
            }}
            onCancel={() => setOpen(false)}
          />
        )}
      </Modal>
    </div>
  )
}

function RuleForm({
  initial,
  onSave,
  onCancel,
}: {
  initial: RuleRow
  onSave: (row: RuleRow) => void
  onCancel: () => void
}) {
  const [text, setText] = useState(initial.rule_text)
  return (
    <div className="space-y-4">
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-600">Rule</label>
        <textarea className="cs-field w-full min-h-[100px]" value={text} onChange={(e) => setText(e.target.value)} placeholder="24h cancellation notice" />
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <button type="button" className="rounded-lg px-4 py-2 text-sm text-gray-700 hover:bg-gray-100" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          disabled={!text.trim()}
          className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          onClick={() => onSave({ ...initial, rule_text: text.trim() })}
        >
          Save
        </button>
      </div>
    </div>
  )
}
