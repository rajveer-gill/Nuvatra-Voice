/** Shared dark branded shell for dashboard / admin (matches marketing bg-call-surge-mesh). */
export function AppChrome({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative min-h-screen overflow-hidden bg-zinc-950 text-zinc-100">
      <div className="pointer-events-none absolute inset-0 bg-call-surge-mesh" aria-hidden />
      <div className="relative z-10">{children}</div>
    </div>
  )
}
