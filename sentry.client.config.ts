import * as Sentry from '@sentry/nextjs'
import { sentryTracesSampleRate } from './lib/sentry-traces-sample-rate'

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? 'production',
  tracesSampleRate: sentryTracesSampleRate(),
  debug: false,
})
