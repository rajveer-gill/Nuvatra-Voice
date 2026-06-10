/**
 * Minimal framer-motion stub for jsdom component tests.
 *
 * `motion.<tag>` renders the plain DOM tag with animation-only props stripped,
 * so `motion.button` is a real <button> that fires onClick. AnimatePresence
 * just renders its children (no enter/exit timing to wait on), which keeps
 * modal open/close assertions synchronous.
 */
import * as React from 'react'

// framer-specific props that must not reach the DOM element.
const MOTION_PROPS = new Set([
  'initial', 'animate', 'exit', 'transition', 'variants', 'whileHover',
  'whileTap', 'whileFocus', 'whileDrag', 'whileInView', 'layout', 'layoutId',
  'drag', 'dragConstraints', 'dragElastic', 'onAnimationComplete', 'custom',
  'viewport', 'transformTemplate', 'style',
])

function strip(props: Record<string, unknown>) {
  const out: Record<string, unknown> = {}
  for (const key of Object.keys(props)) {
    if (!MOTION_PROPS.has(key)) out[key] = props[key]
  }
  return out
}

// Cache the component per tag so `motion.div` returns a STABLE reference across
// renders. A fresh component each access makes React remount the subtree every
// render, which resets controlled inputs (textarea kept only the first char).
const cache = new Map<string, React.ComponentType<Record<string, unknown>>>()

export const motion: any = new Proxy(
  {},
  {
    get(_t, tag: string) {
      let Comp = cache.get(tag)
      if (!Comp) {
        Comp = React.forwardRef(function MotionStub(
          props: Record<string, unknown>,
          ref: React.Ref<unknown>,
        ) {
          const { children, ...rest } = props
          return React.createElement(tag, { ref, ...strip(rest) }, children as React.ReactNode)
        }) as unknown as React.ComponentType<Record<string, unknown>>
        Comp.displayName = `motion.${tag}`
        cache.set(tag, Comp)
      }
      return Comp
    },
  },
)

export function AnimatePresence({ children }: { children?: React.ReactNode }) {
  return React.createElement(React.Fragment, null, children)
}

export const useReducedMotion = () => true
export const useAnimation = () => ({ start: () => Promise.resolve(), stop: () => {} })
export const useMotionValue = (v: unknown) => ({ get: () => v, set: () => {} })
