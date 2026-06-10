import { vi } from 'vitest'

/**
 * A fake of the axios instance returned by useApiClient(). GET responses are
 * routed by URL from `getRoutes` (defaulting to {}); post/patch/put/delete
 * resolve to `{ data: {} }` and can be overridden per-test with
 * `.mockResolvedValueOnce` / `.mockRejectedValueOnce`. All methods are vi.fn
 * spies, so tests assert on the exact URL + body the component sent.
 */
export interface ApiMock {
  get: ReturnType<typeof vi.fn>
  post: ReturnType<typeof vi.fn>
  patch: ReturnType<typeof vi.fn>
  put: ReturnType<typeof vi.fn>
  delete: ReturnType<typeof vi.fn>
}

export function createApiMock(getRoutes: Record<string, unknown> = {}): ApiMock {
  const lookup = (url: string) => (url in getRoutes ? getRoutes[url] : {})
  return {
    get: vi.fn(async (url: string) => ({ data: lookup(url) })),
    post: vi.fn(async () => ({ data: {} })),
    patch: vi.fn(async () => ({ data: {} })),
    put: vi.fn(async () => ({ data: {} })),
    delete: vi.fn(async () => ({ data: {} })),
  }
}
