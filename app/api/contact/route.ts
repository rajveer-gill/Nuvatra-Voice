import { NextResponse } from 'next/server'

type Body = { name?: string; email?: string; message?: string }

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
    return NextResponse.json({ ok: false, error: 'missing_fields' }, { status: 400 })
  }
  if (message.length > 20_000) {
    return NextResponse.json({ ok: false, error: 'message_too_long' }, { status: 400 })
  }

  const serviceId = process.env.EMAILJS_SERVICE_ID
  const templateId = process.env.EMAILJS_TEMPLATE_ID
  const userId = process.env.EMAILJS_PUBLIC_KEY
  if (!serviceId || !templateId || !userId) {
    return NextResponse.json({ ok: false, error: 'email_not_configured' }, { status: 503 })
  }

  const time = new Date().toLocaleString('en-US', { dateStyle: 'full', timeStyle: 'long' })
  const privateKey = process.env.EMAILJS_PRIVATE_KEY

  const payload: Record<string, unknown> = {
    service_id: serviceId,
    template_id: templateId,
    user_id: userId,
    template_params: {
      name,
      email,
      message,
      time,
      reply_to: email,
    },
  }
  if (privateKey) {
    payload.accessToken = privateKey
  }

  const res = await fetch('https://api.emailjs.com/api/v1.0/email/send', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!res.ok) {
    const text = await res.text().catch(() => '')
    console.error('EmailJS send failed', res.status, text)
    return NextResponse.json({ ok: false, error: 'send_failed' }, { status: 502 })
  }

  return NextResponse.json({ ok: true })
}
