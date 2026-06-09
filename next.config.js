const { withSentryConfig } = require('@sentry/nextjs')

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  typescript: {
    // Staged tightening: set to false once the TS backlog is fixed; CI can run `tsc --noEmit` separately.
    ignoreBuildErrors: true,
  },
  eslint: {
    // Staged tightening: set to false after clearing ESLint debt.
    ignoreDuringBuilds: true,
  },
  swcMinify: true,
  async headers() {
    const securityHeaders = [
      { key: 'X-Content-Type-Options', value: 'nosniff' },
      { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
      { key: 'X-Frame-Options', value: 'DENY' },
      {
        key: 'Permissions-Policy',
        value: 'camera=(), microphone=(), geolocation=()',
      },
    ]
    if (process.env.NODE_ENV === 'production') {
      securityHeaders.unshift({
        key: 'Strict-Transport-Security',
        value: 'max-age=63072000; includeSubDomains; preload',
      })
      // Report-Only first: this never blocks anything — it surfaces violations
      // (browser console) so the allowlist can be verified before flipping to an
      // enforcing `Content-Security-Policy`. Allows our third parties: Clerk,
      // Stripe, Sentry, and the backend API. Next.js needs 'unsafe-inline'/'eval'
      // for its inline framework scripts (nonce-based CSP is a later step).
      const csp = [
        "default-src 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://*.clerk.com https://*.clerk.accounts.dev https://js.stripe.com",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: https://*.clerk.com https://img.clerk.com",
        "font-src 'self' data:",
        "connect-src 'self' https://*.clerk.com https://*.clerk.accounts.dev https://api.stripe.com https://*.ingest.sentry.io https://*.sentry.io https://nuvatra-voice.onrender.com",
        "frame-src 'self' https://js.stripe.com https://hooks.stripe.com https://checkout.stripe.com https://*.clerk.com https://*.clerk.accounts.dev",
        "worker-src 'self' blob:",
      ].join('; ')
      securityHeaders.push({ key: 'Content-Security-Policy-Report-Only', value: csp })
    }
    return [
      {
        source: '/:path*',
        headers: securityHeaders,
      },
    ]
  },
}

// Sentry wraps the config for source maps and performance monitoring. DSN is optional (no-op if unset).
module.exports = withSentryConfig(nextConfig, {
  org: 'nuvatra-llc',
  project: 'call-surge-frontend',
  silent: true,
  hideSourceMaps: true,
  disableLogger: true,
})
