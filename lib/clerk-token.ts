/** Options for @clerk/nextjs `getToken()` when calling the backend API. */
export function clerkGetTokenOptions(opts?: { skipCache?: boolean }) {
  const template = process.env.NEXT_PUBLIC_CLERK_JWT_TEMPLATE?.trim()
  if (template) {
    return { template, ...(opts?.skipCache ? { skipCache: true } : {}) }
  }
  if (opts?.skipCache) {
    return { skipCache: true }
  }
  return undefined
}
