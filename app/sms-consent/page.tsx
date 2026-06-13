import Link from 'next/link'
import MarketingNav from '@/components/MarketingNav'

export default function SmsConsentPage() {
  return (
    <>
      <MarketingNav />
      <main className="min-h-screen bg-gray-50 py-12 px-4">
        <div className="max-w-3xl mx-auto bg-white rounded-2xl shadow-lg p-8 md:p-12">
          <h1 className="text-3xl font-bold text-gray-900 mb-6">SMS Consent & Opt-In</h1>

          <div className="prose prose-gray max-w-none space-y-6 text-gray-700">
            <section>
              <p>
                Callers consent to SMS when they call a Call Surge–powered business line and provide
                their number, or when a business they contacted enters it on their behalf to send
                appointment confirmations, reminders, and follow-ups. By providing your mobile number
                you agree to receive these messages from Call Surge. Msg &amp; data rates may apply;
                message frequency varies based on your interactions. Reply <strong>STOP</strong> to opt
                out at any time, or <strong>HELP</strong> for help.
              </p>
            </section>

            <section>
              <p>
                Privacy Policy:{' '}
                <Link href="/privacy" className="text-blue-600 hover:underline">
                  /privacy
                </Link>
              </p>
              <p className="mt-2">
                Terms of Service:{' '}
                <Link href="/terms" className="text-blue-600 hover:underline">
                  /terms
                </Link>
              </p>
            </section>

            <section>
              <p>
                Mobile phone numbers and SMS consent are never shared with third parties or affiliates for marketing
                purposes.
              </p>
            </section>
          </div>

          <div className="mt-8">
            <Link href="/" className="text-blue-600 hover:underline">← Back to home</Link>
          </div>
        </div>
      </main>
    </>
  )
}
