'use client'

import { useEffect, useRef, useState } from 'react'
import { ImageOff, Loader2 } from 'lucide-react'
import { useApiClient } from '@/lib/api'

/**
 * Renders a customer-texted photo (MMS). The media proxy is auth-gated, so a plain
 * <img src> can't load it (no way to attach the bearer token). Instead we fetch the
 * image as an authenticated blob and render it via an object URL — revoked on unmount.
 */
export function SmsMediaImage({
  phone,
  sid,
  onOpen,
}: {
  phone: string
  sid: string
  onOpen?: (url: string) => void
}) {
  const api = useApiClient()
  const [url, setUrl] = useState<string | null>(null)
  const [err, setErr] = useState(false)
  const objectUrlRef = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setUrl(null)
    setErr(false)
    api
      .get(`/api/sms/media?phone=${encodeURIComponent(phone)}&sid=${encodeURIComponent(sid)}`, {
        responseType: 'blob',
      })
      .then((res) => {
        if (cancelled) return
        const obj = URL.createObjectURL(res.data as Blob)
        objectUrlRef.current = obj
        setUrl(obj)
      })
      .catch(() => {
        if (!cancelled) setErr(true)
      })
    return () => {
      cancelled = true
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current)
        objectUrlRef.current = null
      }
    }
  }, [api, phone, sid])

  if (err) {
    return (
      <div className="flex h-24 w-24 items-center justify-center rounded-lg bg-gray-100 text-gray-400">
        <ImageOff className="h-5 w-5" />
      </div>
    )
  }
  if (!url) {
    return (
      <div className="flex h-24 w-24 items-center justify-center rounded-lg bg-gray-100">
        <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
      </div>
    )
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={url}
      alt="Customer photo"
      onClick={() => onOpen?.(url)}
      className="h-24 w-24 cursor-zoom-in rounded-lg object-cover ring-1 ring-gray-200 transition hover:opacity-90"
    />
  )
}
