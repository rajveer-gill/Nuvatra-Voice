import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server'
import { NextResponse } from 'next/server'

const isProtectedRoute = createRouteMatcher(['/dashboard(.*)', '/admin(.*)'])

/** Sentry test page: never public on production unless explicitly enabled (preview/dev escape hatch). */
function allowSentryExamplePage(): boolean {
  if (process.env.NEXT_PUBLIC_ENABLE_SENTRY_TEST_PAGE === 'true') return true
  if (process.env.NODE_ENV === 'development') return true
  if (process.env.VERCEL_ENV === 'preview') return true
  return false
}

export default clerkMiddleware(async (auth, request) => {
  if (request.nextUrl.pathname === '/sentry-example-page' && !allowSentryExamplePage()) {
    return new NextResponse(null, { status: 404 })
  }
  if (isProtectedRoute(request)) {
    await auth.protect()
  }
})

export const config = {
  matcher: [
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    '/(api|trpc)(.*)',
  ],
}
