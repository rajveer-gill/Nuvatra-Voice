'use client'

import axios, { AxiosInstance } from 'axios'
import { useAuth } from '@clerk/nextjs'
import { useMemo, useRef } from 'react'
import { clerkGetTokenOptions } from '@/lib/clerk-token'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

/** Axios timeout (ms). Default 120s so cold-started hosts (e.g. Render free) can wake before abort. Override with NEXT_PUBLIC_API_TIMEOUT_MS. */
const API_TIMEOUT_MS =
  Number(process.env.NEXT_PUBLIC_API_TIMEOUT_MS) > 0
    ? Number(process.env.NEXT_PUBLIC_API_TIMEOUT_MS)
    : 120_000

/** Base URL for constructing absolute links (same as axios baseURL). */
export { API_URL }

/**
 * Multi-store oversight: which store the dashboard is currently showing.
 *
 * Only meaningful for an org overseer (a franchise/regional account). It rides along
 * as the X-Store-Id header and the backend validates it against org membership on
 * every request — the value here is a request for a store, never a grant of one.
 * A normal store owner never sets it, and the backend ignores it if they somehow do.
 */
const STORE_KEY = 'nuvatra.selectedStoreId'

export function getSelectedStoreId(): string | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage.getItem(STORE_KEY)
  } catch {
    return null // private mode / storage disabled
  }
}

export function setSelectedStoreId(storeId: string | null): void {
  if (typeof window === 'undefined') return
  try {
    if (storeId) window.localStorage.setItem(STORE_KEY, storeId)
    else window.localStorage.removeItem(STORE_KEY)
  } catch {
    // Non-fatal: without persistence they just re-pick the store.
  }
}

/**
 * Axios config for Next.js API routes that proxy to the backend (same origin as the app).
 * Use with paths like `/api/admin/session` so requests hit this deployment, not the wrong host.
 */
export function sameOriginApiConfig(): { baseURL: string } {
  if (typeof window !== 'undefined') {
    return { baseURL: window.location.origin }
  }
  return { baseURL: API_URL.replace(/\/$/, '') }
}

/**
 * Returns an axios instance that automatically adds the Clerk auth token to requests.
 * Use this for all API calls that require tenant-scoped data.
 */
export function useApiClient(): AxiosInstance {
  const { getToken } = useAuth()
  // Keep the axios instance STABLE across renders. Clerk's getToken changes identity
  // when the auth/session state churns (e.g. right after a session is revoked), so
  // memoizing on [getToken] would hand back a new client every render — that recreates
  // any useCallback/useEffect depending on the client and can spin an infinite
  // request loop. The interceptors call getToken lazily at request time, so they only
  // need the *latest* getToken via a ref, not as a memo dependency.
  const getTokenRef = useRef(getToken)
  getTokenRef.current = getToken
  const client = useMemo(() => {
    const instance = axios.create({ baseURL: API_URL, timeout: API_TIMEOUT_MS })
    instance.interceptors.request.use(async (config) => {
      try {
        const token = await getTokenRef.current(clerkGetTokenOptions())
        if (token) {
          config.headers.Authorization = `Bearer ${token}`
        }
      } catch (_) {
        // Ignore if getToken fails (e.g. signed out)
      }
      // Read at request time, not instance-creation time, so switching stores takes
      // effect immediately without rebuilding the (deliberately stable) client.
      const storeId = getSelectedStoreId()
      if (storeId) {
        config.headers['X-Store-Id'] = storeId
      }
      return config
    })
    instance.interceptors.response.use(
      (response) => response,
      async (error: {
        config?: {
          headers?: Record<string, string>
          url?: string
          _retry?: boolean
          _storeRetry?: boolean
        }
        response?: { status?: number; data?: { detail?: unknown } }
      }) => {
        const cfg = error.config
        const status = error.response?.status
        // A selected store that no longer exists (deleted, detached, or access
        // revoked) would otherwise 403 every single request and lock the user out
        // with no way back — clearing browser storage was the only escape. Drop the
        // stale selection and retry once, unscoped.
        if (status === 403 && cfg && !cfg._storeRetry) {
          const detail = error.response?.data?.detail as { code?: string } | undefined
          if (detail && typeof detail === 'object' && detail.code === 'STORE_NOT_ACCESSIBLE') {
            cfg._storeRetry = true
            setSelectedStoreId(null)
            if (cfg.headers) delete cfg.headers['X-Store-Id']
            return instance.request(cfg)
          }
        }
        if (status !== 401 || !cfg || cfg._retry) {
          return Promise.reject(error)
        }
        cfg._retry = true
        try {
          const token = await getTokenRef.current(clerkGetTokenOptions({ skipCache: true }))
          if (token) {
            cfg.headers = cfg.headers ?? {}
            cfg.headers.Authorization = `Bearer ${token}`
            return instance.request(cfg)
          }
        } catch {
          // ignore
        }
        return Promise.reject(error)
      }
    )
    return instance
  }, [])
  return client
}
