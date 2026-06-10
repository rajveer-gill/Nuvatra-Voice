/** No-op Sentry stub for tests — error reporting is not exercised here. */
export const captureException = () => undefined
export const captureMessage = () => undefined
export const addBreadcrumb = () => undefined
export const setTag = () => undefined
export const setContext = () => undefined
export const withScope = (fn: (scope: unknown) => void) => fn({})
