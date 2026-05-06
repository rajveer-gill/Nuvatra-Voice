import { NextRequest, NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'

function backendBaseUrl(): string | null {
  const raw = process.env.NEXT_PUBLIC_API_URL?.trim() ?? ''
  const u = raw.replace(/\/$/, '')
  if (!u || !/^https?:\/\//i.test(u)) return null
  return u
}

/**
 * Proxies GET /api/admin/session to the FastAPI backend so the browser calls same-origin
 * (avoids CORS and avoids mistaken NEXT_PUBLIC_API_URL pointing at the marketing site).
 */
export async function GET(request: NextRequest) {
  const backend = backendBaseUrl()
  if (!backend) {
    return NextResponse.json(
      { is_admin: false, detail: 'NEXT_PUBLIC_API_URL is not set to the API origin' },
      { status: 503 }
    )
  }

  const authorization = request.headers.get('authorization')
  const headers: HeadersInit = {
    Accept: 'application/json',
    ...(authorization ? { Authorization: authorization } : {}),
  }

  const res = await fetch(`${backend}/api/admin/session`, {
    method: 'GET',
    headers,
    cache: 'no-store',
  })

  const text = await res.text()
  const contentType = res.headers.get('Content-Type') || 'application/json'
  return new NextResponse(text, {
    status: res.status,
    headers: { 'Content-Type': contentType },
  })
}
