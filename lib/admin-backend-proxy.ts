import { NextRequest, NextResponse } from 'next/server'

export function adminBackendBaseUrl(): string | null {
  const raw = process.env.NEXT_PUBLIC_API_URL?.trim() ?? ''
  const u = raw.replace(/\/$/, '')
  if (!u || !/^https?:\/\//i.test(u)) return null
  return u
}

/** Proxy /api/admin/* to FastAPI (same pattern as /api/admin/session). */
export async function proxyAdminToBackend(
  request: NextRequest,
  pathSegments: string[]
): Promise<NextResponse> {
  const backend = adminBackendBaseUrl()
  if (!backend) {
    return NextResponse.json(
      { detail: 'NEXT_PUBLIC_API_URL is not set to the API origin' },
      { status: 503 }
    )
  }

  const subpath = pathSegments.filter(Boolean).join('/')
  const search = request.nextUrl.search
  const url = `${backend}/api/admin/${subpath}${search}`

  const authorization = request.headers.get('authorization')
  const contentType = request.headers.get('content-type')
  const headers: HeadersInit = {
    Accept: 'application/json',
    ...(authorization ? { Authorization: authorization } : {}),
    ...(contentType ? { 'Content-Type': contentType } : {}),
  }

  let body: string | undefined
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    body = await request.text()
  }

  const res = await fetch(url, {
    method: request.method,
    headers,
    body: body && body.length > 0 ? body : undefined,
    cache: 'no-store',
  })

  const text = await res.text()
  const resContentType = res.headers.get('Content-Type') || 'application/json'
  return new NextResponse(text, {
    status: res.status,
    headers: { 'Content-Type': resContentType },
  })
}
