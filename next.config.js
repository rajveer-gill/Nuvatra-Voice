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
}

// Sentry wraps the config for source maps and performance monitoring. DSN is optional (no-op if unset).
module.exports = withSentryConfig(nextConfig, {
  org: 'nuvatra-llc',
  project: 'call-surge-frontend',
  silent: true,
  hideSourceMaps: true,
  disableLogger: true,
})
