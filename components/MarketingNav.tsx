'use client'

import Link from 'next/link'
import Image from 'next/image'
import { Menu, X } from 'lucide-react'
import { SignedIn, SignedOut, UserButton } from '@clerk/nextjs'
import { useEffect, useId, useState } from 'react'
import { useApiClient, sameOriginApiConfig } from '@/lib/api'

const navLinks = [
  { href: '/#outcomes', label: 'Outcomes' },
  { href: '/#how', label: 'How it works' },
  { href: '/#features', label: 'Features' },
  { href: '/#contact', label: 'Contact' },
] as const

function AdminNavLink({
  className,
  onNavigate,
}: {
  className: string
  onNavigate?: () => void
}) {
  const api = useApiClient()
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    let cancelled = false
    api
      .get<{ is_admin: boolean }>('/api/admin/session', sameOriginApiConfig())
      .then((res) => {
        if (!cancelled && res.data?.is_admin) setVisible(true)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [api])
  if (!visible) return null
  return (
    <Link href="/admin" className={className} onClick={onNavigate}>
      Admin
    </Link>
  )
}

export default function MarketingNav() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const menuId = useId()

  useEffect(() => {
    if (!mobileOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [mobileOpen])

  useEffect(() => {
    const mq = window.matchMedia('(min-width: 640px)')
    const onChange = () => {
      if (mq.matches) setMobileOpen(false)
    }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 border-b border-white/10 bg-zinc-950/80 backdrop-blur-xl supports-[backdrop-filter]:bg-zinc-950/60">
      <div className="max-w-6xl mx-auto flex h-16 items-center justify-between px-4 md:px-6">
        <Link href="/" className="flex items-center gap-2.5 group">
          <Image
            src="/assets/call-surge-mark.svg"
            alt=""
            width={40}
            height={40}
            className="h-10 w-10 transition-transform duration-300 group-hover:scale-[1.02]"
            aria-hidden
          />
          <span className="font-display text-lg font-semibold tracking-tight text-white md:text-xl">
            Call Surge
          </span>
        </Link>

        <div className="flex flex-1 items-center justify-end gap-2 md:gap-4">
          <ul className="hidden sm:flex items-center gap-5 lg:gap-8">
            {navLinks.map(({ href, label }) => (
              <li key={href}>
                <Link
                  href={href}
                  className="text-sm font-medium text-zinc-400 transition-colors hover:text-white"
                >
                  {label}
                </Link>
              </li>
            ))}
          </ul>

          <div className="flex items-center gap-1.5 sm:gap-2 md:gap-3">
            <SignedOut>
              <div className="flex items-center gap-1.5 sm:gap-2 md:gap-3">
                <Link
                  href="/sign-in"
                  className="rounded-full border border-white/20 bg-white/5 px-3 py-2 text-xs font-semibold text-white transition hover:bg-white/10 sm:px-4 sm:text-sm"
                >
                  Sign in
                </Link>
                <Link
                  href="/sign-up"
                  className="rounded-full bg-gradient-to-r from-cyan-500 to-indigo-600 px-3 py-2 text-xs font-semibold text-white shadow-lg shadow-cyan-500/20 transition hover:brightness-110 sm:px-4 sm:text-sm"
                >
                  Get started
                </Link>
              </div>
            </SignedOut>
            <SignedIn>
              <div className="flex items-center gap-1.5 sm:gap-2 md:gap-3">
                <AdminNavLink className="hidden text-sm font-medium text-zinc-400 transition hover:text-white sm:inline" />
                <Link
                  href="/dashboard"
                  className="rounded-full bg-gradient-to-r from-cyan-500 to-indigo-600 px-3 py-2 text-xs font-semibold text-white shadow-lg shadow-cyan-500/20 transition hover:brightness-110 sm:px-4 sm:text-sm"
                >
                  Dashboard
                </Link>
                <UserButton afterSignOutUrl="/" />
              </div>
            </SignedIn>

            <button
              type="button"
              id={`${menuId}-trigger`}
              className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-zinc-400 transition hover:bg-white/10 hover:text-white sm:hidden"
              aria-expanded={mobileOpen}
              aria-controls={menuId}
              onClick={() => setMobileOpen((o) => !o)}
            >
              {mobileOpen ? (
                <>
                  <X className="h-6 w-6" aria-hidden />
                  <span className="sr-only">Close menu</span>
                </>
              ) : (
                <>
                  <Menu className="h-6 w-6" aria-hidden />
                  <span className="sr-only">Open menu</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {mobileOpen && (
        <div
          id={menuId}
          className="fixed inset-x-0 bottom-0 top-16 z-[60] sm:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Site navigation"
        >
          <button
            type="button"
            className="absolute inset-0 z-0 bg-black/70"
            aria-label="Close menu"
            onClick={() => setMobileOpen(false)}
          />
          <div className="relative z-10 max-h-[calc(100dvh-4rem)] overflow-y-auto border-b border-white/10 bg-zinc-950 px-4 py-6 shadow-xl">
            <ul className="flex flex-col gap-1">
              {navLinks.map(({ href, label }) => (
                <li key={href}>
                  <Link
                    href={href}
                    className="block rounded-lg px-3 py-3 text-base font-medium text-zinc-200 transition hover:bg-white/5 hover:text-white"
                    onClick={() => setMobileOpen(false)}
                  >
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
            <SignedIn>
              <div className="mt-4 border-t border-white/10 pt-4 sm:hidden">
                <AdminNavLink
                  className="block rounded-lg px-3 py-3 text-base font-medium text-zinc-200 transition hover:bg-white/5 hover:text-white"
                  onNavigate={() => setMobileOpen(false)}
                />
              </div>
            </SignedIn>
          </div>
        </div>
      )}
    </nav>
  )
}
