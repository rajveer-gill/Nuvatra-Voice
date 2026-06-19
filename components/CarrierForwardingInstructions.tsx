'use client'

import { useState, type ReactNode } from 'react'

const digits = (s: string) => (s || '').replace(/\D/g, '')

type Carrier = { id: string; label: string; steps: (aiLine: string) => ReactNode }

const Code = ({ children }: { children: ReactNode }) => (
  <code className="rounded bg-gray-900/90 px-1.5 py-0.5 font-mono text-[0.78rem] text-cyan-300">{children}</code>
)

/** Forwarding steps per major US carrier. GSM carriers use **21* codes; CDMA/landline use *72. */
const CARRIERS: Carrier[] = [
  {
    id: 'att',
    label: 'AT&T',
    steps: (ai) => (
      <>
        Dial <Code>**21*{digits(ai)}#</Code> and press call. To turn it off later, dial <Code>##21#</Code>.
      </>
    ),
  },
  {
    id: 'tmobile',
    label: 'T-Mobile',
    steps: (ai) => (
      <>
        Dial <Code>**21*{digits(ai)}#</Code> and press call. To turn it off, dial <Code>##21#</Code>.
      </>
    ),
  },
  {
    id: 'verizon',
    label: 'Verizon',
    steps: (ai) => (
      <>
        Dial <Code>*72</Code> then <Code>{digits(ai)}</Code> and press call. To turn it off, dial <Code>*73</Code>.
      </>
    ),
  },
  {
    id: 'iphone',
    label: 'iPhone',
    steps: (ai) => (
      <>
        Open <strong>Settings → Phone → Call Forwarding</strong>, turn it on, and enter <strong>{ai}</strong>.
        (Available on GSM carriers like AT&amp;T and T-Mobile.)
      </>
    ),
  },
  {
    id: 'other',
    label: 'Landline / other',
    steps: (ai) => (
      <>
        Most landlines: dial <Code>*72</Code>, then <Code>{digits(ai)}</Code>, then call (<Code>*73</Code> to cancel).
        If that doesn&rsquo;t work, search &ldquo;[your carrier] call forwarding&rdquo; or ask them to forward all
        calls to {ai}.
      </>
    ),
  },
]

export function CarrierForwardingInstructions({ aiLine }: { aiLine: string }) {
  const [carrier, setCarrier] = useState<string>('att')
  const active = CARRIERS.find((c) => c.id === carrier) || CARRIERS[0]
  return (
    <div className="rounded-xl border border-cyan-500/25 bg-cyan-500/5 p-4">
      <p className="text-sm font-medium text-gray-800">
        Forward your number to your AI line <span className="font-mono text-gray-900">{aiLine}</span>
      </p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {CARRIERS.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => setCarrier(c.id)}
            aria-pressed={carrier === c.id}
            className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
              carrier === c.id
                ? 'border-cyan-500 bg-cyan-500/15 text-cyan-800'
                : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>
      <p className="mt-3 text-sm leading-relaxed text-gray-700">{active.steps(aiLine)}</p>
      <p className="mt-2 text-xs text-gray-500">
        After setting it up, call your own business number from another phone — when the AI answers, you&rsquo;re live.
      </p>
    </div>
  )
}
