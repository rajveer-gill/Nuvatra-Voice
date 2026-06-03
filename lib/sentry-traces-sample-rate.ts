/** Shared Sentry trace sampling: env override, else 100% in dev and 10% in production. */
export function sentryTracesSampleRate(): number {
  const raw = process.env.NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE?.trim()
  if (raw) {
    const n = Number(raw)
    if (!Number.isNaN(n)) {
      return Math.max(0, Math.min(1, n))
    }
  }
  const env = (process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? process.env.NODE_ENV ?? 'production').toLowerCase()
  if (env === 'development' || env === 'dev' || env === 'test') {
    return 1.0
  }
  return 0.1
}
