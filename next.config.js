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
      { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
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
