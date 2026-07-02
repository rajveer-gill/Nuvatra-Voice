'use client'

import { useEffect, useRef, useState } from 'react'
import { useUser } from '@clerk/nextjs'
import { Bug, Check, Lightbulb, MessageSquarePlus, MessageCircle, X } from 'lucide-react'
import { useApiClient } from '@/lib/api'

type Category = 'bug' | 'idea' | 'other'

const CATEGORIES: { value: Category; label: string; icon: typeof Bug }[] = [
  { value: 'bug', label: 'Bug', icon: Bug },
  { value: 'idea', label: 'Suggestion', icon: Lightbulb },
  { value: 'other', label: 'Other', icon: MessageCircle },
]

/**
 * Floating "Feedback" button + modal for reporting bugs or suggesting improvements.
 * Mounted in the dashboard layout so it's reachable from every page. Submissions post to
 * POST /api/feedback (stored + emailed to the operator).
 */
export function FeedbackWidget() {
  const api = useApiClient()
  const { user } = useUser()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [open, setOpen] = useState(false)
  const [category, setCategory] = useState<Category>('bug')
  const [message, setMessage] = useState('')
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')
  const [errorText, setErrorText] = useState('')

  // Prefill the contact email from the signed-in user once it loads.
  useEffect(() => {
    const e = user?.primaryEmailAddress?.emailAddress || ''
    if (e) setEmail((prev) => prev || e)
  }, [user])

  useEffect(() => {
    const el = dialogRef.current
    if (!el) return
    if (open && !el.open) el.showModal()
    if (!open && el.open) el.close()
  }, [open])

  const openModal = () => {
    setStatus('idle')
    setErrorText('')
    setOpen(true)
  }

  const closeModal = () => {
    setOpen(false)
    // Reset the transient message a moment after closing so a reopen starts fresh,
    // but keep the prefilled email.
    setTimeout(() => {
      setMessage('')
      setCategory('bug')
      setStatus('idle')
      setErrorText('')
    }, 200)
  }

  const submit = async () => {
    const trimmed = message.trim()
    if (!trimmed) {
      setErrorText('Please add a short description.')
      setStatus('error')
      return
    }
    setStatus('sending')
    setErrorText('')
    try {
      await api.post('/api/feedback', {
        category,
        message: trimmed,
        email: email.trim() || undefined,
        page_url: typeof window !== 'undefined' ? window.location.pathname : undefined,
      })
      setStatus('sent')
      setTimeout(closeModal, 1400)
    } catch (err) {
      setStatus('error')
      setErrorText('Could not send that right now. Please try again in a moment.')
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={openModal}
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full bg-teal-500 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-teal-900/30 transition-colors hover:bg-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-300 focus:ring-offset-2 focus:ring-offset-zinc-950"
        aria-label="Send feedback or report a bug"
      >
        <MessageSquarePlus className="h-5 w-5" />
        <span className="hidden sm:inline">Feedback</span>
      </button>

      <dialog
        ref={dialogRef}
        className="w-[min(100%,30rem)] max-h-[90vh] rounded-2xl border border-gray-200 bg-white p-0 text-gray-900 shadow-2xl backdrop:bg-black/55"
        onCancel={(ev) => {
          ev.preventDefault()
          closeModal()
        }}
        onClick={(ev) => {
          // Close when the backdrop (the dialog element itself) is clicked.
          if (ev.target === dialogRef.current) closeModal()
        }}
      >
        <div className="flex max-h-[90vh] flex-col overflow-hidden rounded-2xl">
          <div className="flex items-center justify-between border-b border-teal-100 bg-gradient-to-r from-teal-50 to-emerald-50 px-5 py-4">
            <h3 className="text-lg font-bold text-gray-900">Send us feedback</h3>
            <button
              type="button"
              onClick={closeModal}
              className="rounded-lg p-2 hover:bg-white/80"
              aria-label="Close"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {status === 'sent' ? (
            <div className="flex flex-col items-center gap-3 px-6 py-10 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-teal-100">
                <Check className="h-6 w-6 text-teal-600" />
              </div>
              <p className="text-base font-semibold text-gray-900">Thanks — we got it!</p>
              <p className="text-sm text-gray-500">
                Every note helps us make the product better.
              </p>
            </div>
          ) : (
            <div className="space-y-4 overflow-y-auto px-5 py-4">
              <p className="text-sm text-gray-500">
                Found a bug or have an idea? Tell us what happened or what would help — it goes
                straight to the team.
              </p>

              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Type</label>
                <div className="flex flex-wrap gap-1.5">
                  {CATEGORIES.map(({ value, label, icon: Icon }) => {
                    const active = category === value
                    return (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setCategory(value)}
                        aria-pressed={active}
                        className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors ${
                          active
                            ? 'border-teal-500 bg-teal-50 text-teal-700'
                            : 'border-gray-200 text-gray-600 hover:border-gray-300'
                        }`}
                      >
                        <Icon className="h-4 w-4" />
                        {label}
                      </button>
                    )
                  })}
                </div>
              </div>

              <div>
                <label htmlFor="feedback-message" className="mb-1 block text-sm font-medium text-gray-700">
                  Details
                </label>
                <textarea
                  id="feedback-message"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  rows={5}
                  maxLength={4000}
                  autoFocus
                  placeholder={
                    category === 'bug'
                      ? 'What happened? What did you expect instead?'
                      : category === 'idea'
                        ? 'What would make this better for you?'
                        : 'Tell us anything…'
                  }
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
                />
              </div>

              <div>
                <label htmlFor="feedback-email" className="mb-1 block text-sm font-medium text-gray-700">
                  Email <span className="font-normal text-gray-400">(so we can follow up)</span>
                </label>
                <input
                  id="feedback-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  maxLength={254}
                  placeholder="you@example.com"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
                />
              </div>

              {status === 'error' && errorText && (
                <p className="rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-600">
                  {errorText}
                </p>
              )}

              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={closeModal}
                  className="rounded-lg px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={submit}
                  disabled={status === 'sending'}
                  className="rounded-lg bg-teal-500 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-teal-400 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {status === 'sending' ? 'Sending…' : 'Send feedback'}
                </button>
              </div>
            </div>
          )}
        </div>
      </dialog>
    </>
  )
}
