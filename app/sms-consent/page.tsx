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
              <div className="flex items-start gap-3 not-prose">
                <input
                  id="sms-opt-in"
                  type="checkbox"
                  className="mt-1 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  aria-label="SMS opt-in consent checkbox"
                />
                <label htmlFor="sms-opt-in" className="text-gray-700 leading-relaxed">
                  I agree to receive SMS notifications and updates from Nuvatra Voice. Msg &amp; data rates may
                  apply. Message frequency varies based on your interactions with our service. Reply STOP to opt out
                  at any time.
                </label>
              </div>
            </section>

            <section>
              <p>
                Privacy Policy:{' '}
                <a
                  href="https://nuvatrahq.com/privacy"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:underline"
                >
                  nuvatrahq.com/privacy
                </a>
              </p>
              <p className="mt-2">
                Terms of Service:{' '}
                <a
                  href="https://nuvatrahq.com/terms"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:underline"
                >
                  nuvatrahq.com/terms
                </a>
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
