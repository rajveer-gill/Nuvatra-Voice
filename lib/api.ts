'use client'

import axios, { AxiosInstance } from 'axios'
import { useAuth } from '@clerk/nextjs'
import { useMemo } from 'react'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

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

export { API_URL }
