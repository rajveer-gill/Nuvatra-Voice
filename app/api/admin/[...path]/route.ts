import { NextRequest } from 'next/server'
import { proxyAdminToBackend } from '@/lib/admin-backend-proxy'

export const dynamic = 'force-dynamic'

type RouteContext = { params: Promise<{ path: string[] }> }

async function handle(request: NextRequest, context: RouteContext) {
  const { path } = await context.params
  return proxyAdminToBackend(request, path ?? [])
}

export const GET = handle
export const POST = handle
export const PATCH = handle
export const PUT = handle
export const DELETE = handle
