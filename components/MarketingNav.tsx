'use client'

import Link from 'next/link'
import Image from 'next/image'
import { SignedIn, SignedOut, UserButton } from '@clerk/nextjs'

export default function MarketingNav() {
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
        <ul className="flex items-center gap-5 md:gap-8">
          <li className="hidden sm:block">
            <Link
              href="/#outcomes"
              className="text-sm font-medium text-zinc-400 transition-colors hover:text-white"
            >
              Outcomes
            </Link>
          </li>
          <li className="hidden md:block">
            <Link
              href="/#how"
              className="text-sm font-medium text-zinc-400 transition-colors hover:text-white"
            >
              How it works
            </Link>
          </li>
          <li className="hidden md:block">
            <Link
              href="/#features"
              className="text-sm font-medium text-zinc-400 transition-colors hover:text-white"
            >
              Features
            </Link>
          </li>
          <li className="hidden sm:block">
            <Link
              href="/#contact"
              className="text-sm font-medium text-zinc-400 transition-colors hover:text-white"
            >
              Contact
            </Link>
          </li>
          <li>
            <SignedOut>
              <div className="flex items-center gap-2 md:gap-3">
                <Link
                  href="/dashboard"
                  className="rounded-full border border-white/20 bg-white/5 px-4 py-2 text-sm font-semibold text-white transition hover:bg-white/10"
                >
                  Sign in
                </Link>
                <Link
                  href="/dashboard"
                  className="rounded-full bg-gradient-to-r from-cyan-500 to-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-cyan-500/20 transition hover:brightness-110"
                >
                  Get started
                </Link>
              </div>
            </SignedOut>
            <SignedIn>
              <div className="flex items-center gap-2 md:gap-3">
                <Link
                  href="/admin"
                  className="hidden text-sm font-medium text-zinc-400 transition hover:text-white sm:inline"
                >
                  Admin
                </Link>
                <Link
                  href="/dashboard"
                  className="rounded-full bg-gradient-to-r from-cyan-500 to-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-cyan-500/20 transition hover:brightness-110"
                >
                  Dashboard
                </Link>
                <UserButton afterSignOutUrl="/" />
              </div>
            </SignedIn>
          </li>
        </ul>
      </div>
    </nav>
  )
}
