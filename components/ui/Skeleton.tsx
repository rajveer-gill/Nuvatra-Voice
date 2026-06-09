/**
 * Shimmer skeleton placeholder. Pure CSS (uses the `shimmer` keyframe from
 * tailwind.config) — a moving highlight sweeps across a neutral block. Decorative
 * (aria-hidden); the sweep is hidden under prefers-reduced-motion, leaving a
 * static placeholder. Defaults suit light/white cards; pass `className` to recolor
 * (e.g. `bg-white/10` on dark surfaces).
 */
export function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`relative overflow-hidden rounded bg-gray-200 ${className}`}
    >
      <span className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-white/70 to-transparent motion-reduce:hidden" />
    </div>
  )
}
