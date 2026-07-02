import { NextResponse } from 'next/server'

type Body = { name?: string; email?: string; message?: string }

/** Escape user-supplied text before embedding in the email HTML. */
function esc(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export async function POST(request: Request) {
  let json: Body
  try {
    json = await request.json()
  } catch {
    return NextResponse.json({ ok: false, error: 'invalid_json' }, { status: 400 })
  }

  const name = typeof json.name === 'string' ? json.name.trim() : ''
  const email = typeof json.email === 'string' ? json.email.trim() : ''
  const message = typeof json.message === 'string' ? json.message.trim() : ''

  if (!name || !email || !message) {
    const missing: string[] = []
    if (!name) missing.push('name')
    if (!email) missing.push('email')
    if (!message) missing.push('message')
    return NextResponse.json({ ok: false, error: 'missing_fields', missing }, { status: 400 })
  }
  if (message.length > 20_000) {
    return NextResponse.json({ ok: false, error: 'message_too_long' }, { status: 400 })
  }

  // Resend transactional email. One provider powers the marketing contact form, the
  // in-app feedback widget, and appointment/operator emails (backend email_notify.py).
  const apiKey = process.env.RESEND_API_KEY
  // Verified sender on your domain (e.g. contact@nuvatrahq.com). Falls back to the
  // shared appointment sender so a single verified address can cover everything.
  const from = process.env.CONTACT_FROM_EMAIL || process.env.APPOINTMENT_EMAIL_FROM
  // Where contact submissions land. Defaults to the address shown on the form.
  const to = process.env.CONTACT_TO_EMAIL || 'info@nuvatrahq.com'
  if (!apiKey || !from) {
    return NextResponse.json({ ok: false, error: 'email_not_configured' }, { status: 503 })
  }

  const time = new Date().toLocaleString('en-US', { dateStyle: 'full', timeStyle: 'long' })
  const html = `
    <p><strong>New contact form submission</strong></p>
    <p><strong>Name:</strong> ${esc(name)}<br>
    <strong>Email:</strong> ${esc(email)}<br>
    <strong>Time:</strong> ${esc(time)}</p>
    <p style="white-space:pre-wrap">${esc(message)}</p>
  `.trim()
  const text = `New contact form submission\n\nName: ${name}\nEmail: ${email}\nTime: ${time}\n\n${message}`

  let res: Response
  try {
    res = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        from,
        to: [to],
        subject: `Contact form: ${name}`,
        html,
        text,
        reply_to: email,
      }),
    })
  } catch (err) {
    console.error('Resend contact send error', err)
    return NextResponse.json({ ok: false, error: 'send_failed' }, { status: 502 })
  }

  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    console.error('Resend contact send failed', res.status, detail)
    return NextResponse.json({ ok: false, error: 'send_failed' }, { status: 502 })
  }

  return NextResponse.json({ ok: true })
}
