'use client'

import { useState } from 'react'

export default function ContactForm() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState('')
  const [status, setStatus] = useState<'idle' | 'sending' | 'success' | 'error'>('idle')
  const [errorDetail, setErrorDetail] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setStatus('sending')
    setErrorDetail(null)
    try {
      const res = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, message }),
      })
      const data = (await res.json().catch(() => ({}))) as { ok?: boolean; error?: string }

      if (res.ok && data.ok) {
        setStatus('success')
        setName('')
        setEmail('')
        setMessage('')
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

  return (
    <form
      onSubmit={handleSubmit}
      method="post"
      className="flex flex-col gap-4"
      noValidate
    >
      <input
        type="text"
        name="name"
        autoComplete="name"
        placeholder="Your Name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        required
        className="rounded-lg border-2 border-zinc-200 px-4 py-3 text-zinc-900 placeholder:text-zinc-400 focus:border-cyan-500 focus:outline-none"
      />
      <input
        type="email"
        name="email"
        autoComplete="email"
        placeholder="Your Email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
        className="rounded-lg border-2 border-zinc-200 px-4 py-3 text-zinc-900 placeholder:text-zinc-400 focus:border-cyan-500 focus:outline-none"
      />
      <textarea
        name="message"
        placeholder="Your Message"
        rows={5}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        required
        className="resize-none rounded-lg border-2 border-zinc-200 px-4 py-3 text-zinc-900 placeholder:text-zinc-400 focus:border-cyan-500 focus:outline-none"
      />
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
        <a href="mailto:info@nuvatrahq.com" className="text-cyan-700 underline-offset-2 hover:underline">
          info@nuvatrahq.com
        </a>
      </p>
    </form>
  )
}
