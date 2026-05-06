'use client'

import { useState } from 'react'

type FieldKey = 'name' | 'email' | 'message'

export default function ContactForm() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState('')
  const [status, setStatus] = useState<'idle' | 'sending' | 'success' | 'error'>('idle')
  const [errorDetail, setErrorDetail] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<FieldKey, string>>>({})

  const clearFieldError = (key: FieldKey) => {
    setFieldErrors((prev) => {
      if (!prev[key]) return prev
      const next = { ...prev }
      delete next[key]
      return next
    })
  }

  const validateTrimmed = (): boolean => {
    const next: Partial<Record<FieldKey, string>> = {}
    const nt = name.trim()
    const et = email.trim()
    const mt = message.trim()
    if (!nt) next.name = 'Name is required.'
    if (!et) next.email = 'Email is required.'
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(et)) next.email = 'Enter a valid email address.'
    if (!mt) next.message = 'Message is required.'
    setFieldErrors(next)
    return Object.keys(next).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErrorDetail(null)
    if (!validateTrimmed()) {
      setStatus('idle')
      return
    }
    setStatus('sending')
    try {
      const res = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          email: email.trim(),
          message: message.trim(),
        }),
      })
      const data = (await res.json().catch(() => ({}))) as {
        ok?: boolean
        error?: string
        missing?: string[]
      }

      if (res.ok && data.ok) {
        setStatus('success')
        setName('')
        setEmail('')
        setMessage('')
        setFieldErrors({})
        return
      }

      if (res.status === 400 && data.error === 'missing_fields' && Array.isArray(data.missing)) {
        const map: Partial<Record<FieldKey, string>> = {}
        if (data.missing.includes('name')) map.name = 'Name is required.'
        if (data.missing.includes('email')) map.email = 'Email is required.'
        if (data.missing.includes('message')) map.message = 'Message is required.'
        setFieldErrors(map)
        setStatus('error')
        setErrorDetail('Please complete all required fields.')
        return
      }

      if (res.status === 503 && data.error === 'email_not_configured') {
        setStatus('error')
        setErrorDetail(
          'Contact delivery is not configured on this server yet. Please email info@nuvatrahq.com directly.'
        )
        return
      }

      setStatus('error')
      setErrorDetail('Could not send your message. Try email at info@nuvatrahq.com.')
    } catch {
      setStatus('error')
      setErrorDetail('Network error. Email us at info@nuvatrahq.com.')
    }
  }

  const inputRing =
    'rounded-lg border-2 border-zinc-200 px-4 py-3 text-zinc-900 placeholder:text-zinc-400 focus:border-cyan-500'

  return (
    <form onSubmit={handleSubmit} method="post" className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <label htmlFor="contact-name" className="sr-only">
          Your name
        </label>
        <input
          id="contact-name"
          type="text"
          name="name"
          autoComplete="name"
          placeholder="Your Name"
          value={name}
          onChange={(e) => {
            setName(e.target.value)
            clearFieldError('name')
          }}
          aria-invalid={Boolean(fieldErrors.name)}
          aria-describedby={fieldErrors.name ? 'contact-name-error' : undefined}
          className={`${inputRing} ${fieldErrors.name ? 'border-red-500' : ''}`}
        />
        {fieldErrors.name && (
          <p id="contact-name-error" className="text-sm text-red-600">
            {fieldErrors.name}
          </p>
        )}
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="contact-email" className="sr-only">
          Your email
        </label>
        <input
          id="contact-email"
          type="email"
          name="email"
          autoComplete="email"
          placeholder="Your Email"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value)
            clearFieldError('email')
          }}
          aria-invalid={Boolean(fieldErrors.email)}
          aria-describedby={fieldErrors.email ? 'contact-email-error' : undefined}
          className={`${inputRing} ${fieldErrors.email ? 'border-red-500' : ''}`}
        />
        {fieldErrors.email && (
          <p id="contact-email-error" className="text-sm text-red-600">
            {fieldErrors.email}
          </p>
        )}
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="contact-message" className="sr-only">
          Your message
        </label>
        <textarea
          id="contact-message"
          name="message"
          placeholder="Your Message"
          rows={5}
          value={message}
          onChange={(e) => {
            setMessage(e.target.value)
            clearFieldError('message')
          }}
          aria-invalid={Boolean(fieldErrors.message)}
          aria-describedby={fieldErrors.message ? 'contact-message-error' : undefined}
          className={`resize-none ${inputRing} ${fieldErrors.message ? 'border-red-500' : ''}`}
        />
        {fieldErrors.message && (
          <p id="contact-message-error" className="text-sm text-red-600">
            {fieldErrors.message}
          </p>
        )}
      </div>
      <button
        type="submit"
        disabled={status === 'sending'}
        className="rounded-full bg-gradient-to-r from-cyan-600 to-indigo-600 px-8 py-3 font-semibold text-white transition hover:brightness-110 disabled:opacity-70"
      >
        {status === 'sending' ? 'Sending...' : 'Send Message'}
      </button>
      {status === 'success' && (
        <p className="text-sm text-emerald-700">Message sent! We&apos;ll get back to you soon.</p>
      )}
      {status === 'error' && errorDetail && <p className="text-sm text-red-600">{errorDetail}</p>}
      {status === 'error' && !errorDetail && (
        <p className="text-sm text-red-600">Something went wrong. Email us at info@nuvatrahq.com</p>
      )}
      <p className="text-xs text-zinc-500">
        Prefer email?{' '}
        <a
          href="mailto:info@nuvatrahq.com"
          className="text-cyan-700 underline-offset-2 hover:underline"
        >
          info@nuvatrahq.com
        </a>
      </p>
    </form>
  )
}
