'use client'

import { useState } from 'react'
import emailjs from '@emailjs/browser'

const EMAILJS_PUBLIC_KEY = 'HLs4shQc-2XbmccpA'
const EMAILJS_SERVICE_ID = 'service_hnnkg0a'
const EMAILJS_TEMPLATE_ID = 'template_9dmddia'

export default function ContactForm() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState('')
  const [status, setStatus] = useState<'idle' | 'sending' | 'success' | 'error'>('idle')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setStatus('sending')
    const time = new Date().toLocaleString('en-US', { dateStyle: 'full', timeStyle: 'long' })
    try {
      emailjs.init(EMAILJS_PUBLIC_KEY)
      await emailjs.send(EMAILJS_SERVICE_ID, EMAILJS_TEMPLATE_ID, {
        name, email, message, time, reply_to: email
      })
      setStatus('success')
      setName('')
      setEmail('')
      setMessage('')
    } catch (err) {
      const subject = encodeURIComponent(`Contact from ${name} - Nuvatra Website`)
      const body = encodeURIComponent(`Name: ${name}\nEmail: ${email}\n\nMessage:\n${message}`)
      window.location.href = `mailto:info@nuvatrahq.com?subject=${subject}&body=${body}`
      setStatus('idle')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <input
        type="text"
        placeholder="Your Name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        required
        className="px-4 py-3 border-2 border-gray-200 rounded-lg focus:border-blue-500 focus:outline-none"
      />
      <input
        type="email"
        placeholder="Your Email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
        className="px-4 py-3 border-2 border-gray-200 rounded-lg focus:border-blue-500 focus:outline-none"
      />
      <textarea
        placeholder="Your Message"
        rows={5}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        required
        className="px-4 py-3 border-2 border-gray-200 rounded-lg focus:border-blue-500 focus:outline-none resize-none"
      />
      <button
        type="submit"
        disabled={status === 'sending'}
        className="px-8 py-3 rounded-full bg-gradient-to-r from-blue-600 to-blue-500 text-white font-semibold hover:shadow-lg hover:-translate-y-0.5 transition disabled:opacity-70"
      >
        {status === 'sending' ? 'Sending...' : 'Send Message'}
      </button>
      {status === 'success' && <p className="text-green-600 text-sm">Message sent! We&apos;ll get back to you soon.</p>}
      {status === 'error' && <p className="text-red-600 text-sm">Failed to send. Email us at info@nuvatrahq.com</p>}
    </form>
  )
}
