'use client'

import axios, { AxiosInstance } from 'axios'
import { useAuth } from '@clerk/nextjs'
import { useMemo } from 'react'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

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
  const client = useMemo(() => {
    const instance = axios.create({ baseURL: API_URL })
    instance.interceptors.request.use(async (config) => {
      try {
        const token = await getToken()
        if (token) {
          config.headers.Authorization = `Bearer ${token}`
        }
      } catch (_) {
        // Ignore if getToken fails (e.g. signed out)
      }
      return config
    })
    return instance
  }, [getToken])
  return client
}
