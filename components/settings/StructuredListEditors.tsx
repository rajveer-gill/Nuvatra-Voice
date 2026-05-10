'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Clock, DollarSign, Plus, Pencil, Tag, Trash2, X } from 'lucide-react'

export type ServiceRow = { id: string; name: string; price: number; duration_minutes: number }
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

export function ServicesEditor({
  items,
  onChange,
}: {
  items: ServiceRow[]
  onChange: (next: ServiceRow[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [edit, setEdit] = useState<ServiceRow | null>(null)

  const remove = (id: string) => {
    onChange(items.filter((x) => x.id !== id))
  }

  return (
    <div className="md:col-span-2 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label className="block text-sm font-medium text-gray-700">Services</label>
        <button
          type="button"
          onClick={() => {
            setEdit({ id: crypto.randomUUID(), name: '', price: 0, duration_minutes: 30 })
            setOpen(true)
          }}
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-1.5 text-sm font-medium text-white shadow hover:bg-primary-700"
        >
          <Plus className="h-4 w-4" />
          Add service
        </button>
      </div>
      <ul className="space-y-2">
        <AnimatePresence initial={false}>
          {items.map((s) => (
            <motion.li
              key={s.id}
              layout
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-gray-200 bg-gray-50/80 px-4 py-3"
            >
              <div>
                <p className="font-medium text-gray-900">{s.name || 'Untitled'}</p>
                <p className="text-xs text-gray-600">
                  ${Number(s.price).toFixed(2)} · {s.duration_minutes} min
                </p>
              </div>
              <div className="flex gap-1">
                <button
                  type="button"
                  className="rounded-lg p-2 text-gray-600 hover:bg-gray-200"
                  onClick={() => {
                    setEdit(s)
                    setOpen(true)
                  }}
                  aria-label="Edit"
                >
                  <Pencil className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  className="rounded-lg p-2 text-red-600 hover:bg-red-50"
                  onClick={() => remove(s.id)}
                  aria-label="Remove"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={edit && items.some((x) => x.id === edit.id) ? 'Edit service' : 'New service'}
      >
        {edit && (
          <ServiceForm
            key={edit.id}
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

function ServiceForm({
  initial,
  onSave,
  onCancel,
}: {
  initial: ServiceRow
  onSave: (row: ServiceRow) => void
  onCancel: () => void
}) {
  const [name, setName] = useState(initial.name)
  const [price, setPrice] = useState(initial.price)
  const [dur, setDur] = useState(initial.duration_minutes)
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
      <div className="flex justify-end gap-2 pt-2">
        <button type="button" className="rounded-lg px-4 py-2 text-sm text-gray-700 hover:bg-gray-100" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
          onClick={() => onSave({ ...initial, name, price, duration_minutes: dur })}
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
