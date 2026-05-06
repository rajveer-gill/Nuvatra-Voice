import Link from 'next/link'
import Image from 'next/image'

export default function AuthShell({
  children,
  headingId,
}: {
  children: React.ReactNode
  /** Visually hidden heading for the auth landmark (page title still comes from Clerk UI). */
  headingId?: string
}) {
  return (
    <div className="relative min-h-dvh bg-zinc-950">
      <div className="pointer-events-none absolute inset-0 bg-call-surge-mesh" aria-hidden />
      <div className="relative mx-auto flex min-h-dvh max-w-lg flex-col px-4 pb-16 pt-24 md:pt-28">
        <Link
          href="/"
          className="mb-8 inline-flex items-center gap-2.5 self-start text-zinc-400 transition hover:text-white"
        >
          <Image src="/assets/call-surge-mark.svg" alt="" width={36} height={36} className="h-9 w-9" />
          <span className="font-display text-base font-semibold text-white">Call Surge</span>
        </Link>
        <main aria-labelledby={headingId}>{children}</main>
      </div>
    </div>
  )
}
