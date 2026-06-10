import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// Component tests run in jsdom. Heavy, presentational, or auth-only modules are
// aliased to lightweight stubs in test/stubs so tests stay deterministic and
// don't need a browser, a real Clerk session, or FullCalendar. Behavior under
// test (the api calls and resulting UI) is exercised through the real
// components; only these leaf concerns are stubbed.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      'framer-motion': path.resolve(__dirname, 'test/stubs/framer-motion.tsx'),
      '@sentry/nextjs': path.resolve(__dirname, 'test/stubs/sentry.ts'),
      '@clerk/nextjs': path.resolve(__dirname, 'test/stubs/clerk.tsx'),
      '@/components/AppointmentCalendar': path.resolve(__dirname, 'test/stubs/AppointmentCalendar.tsx'),
      // Keep the '@/*' path mapping last so the specific stubs above win.
      '@': path.resolve(__dirname, '.'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./test/setup.ts'],
    include: ['test/**/*.test.{ts,tsx}'],
  },
})
