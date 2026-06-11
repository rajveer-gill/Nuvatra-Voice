import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

/**
 * Empty-state placeholder for lists/tables with no data yet. An optional icon in a
 * soft brand-tinted tile, a short title, a one-line description, and optional
 * action. Tuned for light/white cards (the dashboard surfaces); pass `className`
 * to adjust spacing. Keep copy reassuring and forward-looking ("…will show up
 * here") rather than a flat "No data".
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className = '',
}: {
  icon?: LucideIcon
  title: string
  description?: string
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={`flex flex-col items-center justify-center gap-3 px-6 py-10 text-center ${className}`}>
      {Icon && (
        <div
          className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-cyan-500/10 to-indigo-600/10 text-cyan-600"
          aria-hidden
        >
          <Icon className="h-6 w-6" />
        </div>
      )}
      <div className="space-y-1">
        <p className="text-sm font-semibold text-gray-900">{title}</p>
        {description && <p className="mx-auto max-w-sm text-sm text-gray-500">{description}</p>}
      </div>
      {action}
    </div>
  )
}
