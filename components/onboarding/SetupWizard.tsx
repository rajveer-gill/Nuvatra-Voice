'use client'

import Link from 'next/link'
import { CheckCircle2, Circle, ArrowRight } from 'lucide-react'

export type SetupWizardStatus = {
  complete?: boolean
  missing?: string[]
  warnings?: string[]
  roster_ready?: boolean
  forwarding_phone_ready?: boolean
  voice_ready?: boolean
  twilio_number_set?: boolean
  webhooks_configured?: boolean
  onboarding_completed_at?: string | null
}

type Step = {
  id: string
  title: string
  description: string
  done: boolean
  settingsAnchor?: string
}

function buildSteps(status: SetupWizardStatus | null): Step[] {
  const missing = status?.missing ?? []
  const businessDone = !missing.includes('Business name') && !missing.includes('Hours of operation') && !missing.includes('Address')
  const servicesDone = !(status?.warnings ?? []).some((w) => w.startsWith('Add services'))
  return [
    {
      id: 'business',
      title: 'Business profile',
      description: 'Name, hours, and address so callers get accurate info.',
      done: businessDone,
      settingsAnchor: undefined,
    },
    {
      id: 'services',
      title: 'Services',
      description: 'What you offer — helps the AI guide booking conversations.',
      done: servicesDone,
    },
    {
      id: 'team',
      title: 'Team roster',
      description: 'At least one named team member for appointments.',
      done: status?.roster_ready === true,
      settingsAnchor: 'team-roster-settings',
    },
    {
      id: 'store-phone',
      title: 'Store phone',
      description: 'Number to transfer callers when they need a real person.',
      done: status?.forwarding_phone_ready === true,
      settingsAnchor: 'store-phone-settings',
    },
    {
      id: 'go-live',
      title: 'AI phone & webhooks',
      description: 'Your admin assigns a Twilio number and configures webhooks.',
      done: Boolean(status?.twilio_number_set && status?.webhooks_configured),
    },
    {
      id: 'test',
      title: 'Test your greeting',
      description: 'Preview what callers hear in Settings, then place a test call.',
      done: Boolean(status?.onboarding_completed_at),
    },
  ]
}

type Props = {
  status: SetupWizardStatus | null
  onComplete: () => void
  completing?: boolean
  compact?: boolean
}

export function SetupWizard({ status, onComplete, completing, compact }: Props) {
  const steps = buildSteps(status)
  const doneCount = steps.filter((s) => s.done).length
  const progress = Math.round((doneCount / steps.length) * 100)

  return (
    <div className={compact ? '' : 'rounded-2xl border border-white/10 bg-zinc-900/80 p-6 shadow-xl backdrop-blur-md'}>
      {!compact && (
        <div className="mb-6">
          <h2 className="font-display text-xl font-semibold text-white">Get your AI receptionist live</h2>
          <p className="mt-1 text-sm text-zinc-400">
            Complete these steps so Call Surge can answer and book for your business.
          </p>
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-zinc-800">
            <div
              className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-indigo-600 transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
          <p className="mt-2 text-xs text-zinc-500">{doneCount} of {steps.length} complete</p>
        </div>
      )}

      <ol className="space-y-3">
        {steps.map((step, i) => (
          <li
            key={step.id}
            className="flex gap-3 rounded-xl border border-white/10 bg-zinc-950/50 px-4 py-3"
          >
            {step.done ? (
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-400" aria-hidden />
            ) : (
              <Circle className="mt-0.5 h-5 w-5 shrink-0 text-zinc-600" aria-hidden />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-zinc-100">
                {i + 1}. {step.title}
              </p>
              <p className="mt-0.5 text-xs text-zinc-500">{step.description}</p>
              {!step.done && step.settingsAnchor && (
                <Link
                  href={`/dashboard?tab=settings#${step.settingsAnchor}`}
                  className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-cyan-400 hover:text-cyan-300"
                >
                  Open in Settings
                  <ArrowRight className="h-3 w-3" />
                </Link>
              )}
            </div>
          </li>
        ))}
      </ol>

      <div className="mt-6 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={onComplete}
          disabled={completing}
          className="rounded-full bg-gradient-to-r from-cyan-600 to-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-cyan-500/20 hover:brightness-110 disabled:opacity-50"
        >
          {completing ? 'Saving…' : "I've completed setup / tested my line"}
        </button>
        <Link
          href="/dashboard?tab=settings"
          className="inline-flex items-center rounded-full border border-white/15 px-5 py-2.5 text-sm font-medium text-zinc-300 hover:bg-white/5"
        >
          Open Settings
        </Link>
      </div>
    </div>
  )
}
