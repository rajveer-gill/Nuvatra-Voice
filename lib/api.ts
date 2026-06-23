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
      return config
    })
    instance.interceptors.response.use(
      (response) => response,
      async (error: {
        config?: { headers?: Record<string, string>; url?: string; _retry?: boolean }
        response?: { status?: number }
      }) => {
        const cfg = error.config
        const status = error.response?.status
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
