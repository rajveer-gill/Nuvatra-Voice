'use client'

import Link from 'next/link'
import Image from 'next/image'
import { SignedIn, SignedOut, SignInButton, UserButton } from '@clerk/nextjs'

export default function MarketingNav() {
  return (
    <nav className="fixed top-0 left-0 right-0 z-50 bg-black py-4 px-4 shadow-lg">
      <div className="max-w-6xl mx-auto flex justify-between items-center">
        <Link href="/" className="flex items-center gap-2">
          <Image src="/assets/nuvatra-logo.svg" alt="Nuvatra" width={40} height={40} className="invert" />
          <span className="text-white text-xl font-semibold tracking-wider">NUVATRA</span>
        </Link>
        <ul className="flex items-center gap-8">
          <li><Link href="/#home" className="text-white/90 hover:text-white font-medium transition">Home</Link></li>
          <li><Link href="/#products" className="text-white/90 hover:text-white font-medium transition">Products</Link></li>
          <li><Link href="/#contact" className="text-white/90 hover:text-white font-medium transition">Contact</Link></li>
          <li>
            <SignedOut>
              <div className="flex items-center gap-3">
                <Link href="/#contact" className="text-white/90 hover:text-white font-medium">
                  Contact us
                </Link>
                <SignInButton mode="modal">
                  <button className="px-4 py-2 rounded-full bg-blue-600 text-white font-semibold hover:bg-blue-700 transition">
                    Log in
                  </button>
                </SignInButton>
                <span className="text-white/60 text-sm">(by invite)</span>
              </div>
            </SignedOut>
            <SignedIn>
              <div className="flex items-center gap-3">
                <Link href="/admin" className="text-white/90 hover:text-white font-medium text-sm">
                  Admin
                </Link>
                <Link href="/dashboard" className="px-4 py-2 rounded-full bg-blue-600 text-white font-semibold hover:bg-blue-700 transition">
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
