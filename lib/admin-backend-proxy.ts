import { NextRequest, NextResponse } from 'next/server'

/**
 * How long this function will wait on the backend before giving up.
 *
 * This runs as a Netlify Function, and Netlify bills function COMPUTE by duration.
 * The fetch below had no timeout, so when the backend was cold or saturated the
 * function sat there for the better part of a minute per call — the Render access
 * log recorded 58-second waits ending in 499. A burst of admin requests against a
 * sleeping backend therefore bought nothing and burned a month of credits in a day,
 * which paused production deploys.
 *
 * 15s is well past a warm backend (sub-second) and well short of a cold start, so
 * a sleeping backend now fails fast and cheap instead of slowly and expensively.
 */
const PROXY_TIMEOUT_MS = Number(process.env.ADMIN_PROXY_TIMEOUT_MS) > 0
  ? Number(process.env.ADMIN_PROXY_TIMEOUT_MS)
  : 15_000

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

  let res: Response
  try {
    res = await fetch(url, {
      method: request.method,
      headers,
      body: body && body.length > 0 ? body : undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
    })
  } catch (e) {
    const timedOut = (e as Error)?.name === 'TimeoutError'
    // 504, not 500: the request never got an answer, so the caller must not treat
    // this as "the backend said no". A write may still have landed.
    return NextResponse.json(
      {
        detail: timedOut
          ? `The API did not respond within ${Math.round(PROXY_TIMEOUT_MS / 1000)}s. It may be starting up — retry in a moment.`
          : 'Could not reach the API.',
      },
      { status: 504 }
    )
  }

  const text = await res.text()
  const resContentType = res.headers.get('Content-Type') || 'application/json'
  return new NextResponse(text, {
    status: res.status,
    headers: { 'Content-Type': resContentType },
  })
}
