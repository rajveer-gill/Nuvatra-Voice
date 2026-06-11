import { ChevronDown } from 'lucide-react'
import type { ReactNode } from 'react'

/**
 * Collapsible card section for secondary/diagnostic content (ops checks, logs).
 * Native <details> — accessible, keyboard-toggleable, no JS state. The chevron
 * rotates when open. Collapsed by default; pass defaultOpen to start expanded.
 * Styled for the dark admin surfaces.
 */
export function CollapsibleSection({
  title,
  description,
  defaultOpen = false,
  className = '',
  children,
}: {
  title: string
  description?: string
  defaultOpen?: boolean
  className?: string
  children: ReactNode
}) {
  return (
    <details
      open={defaultOpen}
      className={`group rounded-2xl border border-white/10 bg-zinc-900/70 shadow-xl backdrop-blur-md ${className}`}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-6 [&::-webkit-details-marker]:hidden">
        <div>
          <h2 className="font-display text-lg font-semibold text-white">{title}</h2>
          {description && <p className="text-xs text-zinc-500">{description}</p>}
        </div>
        <ChevronDown
          className="h-5 w-5 shrink-0 text-zinc-400 transition-transform group-open:rotate-180"
          aria-hidden
        />
      </summary>
      <div className="px-6 pb-6">{children}</div>
    </details>
  )
}
