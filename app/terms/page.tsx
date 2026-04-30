import Link from 'next/link'
import MarketingNav from '@/components/MarketingNav'

export default function TermsPage() {
  return (
    <>
      <MarketingNav />
      <main className="min-h-screen bg-gray-50 py-12 px-4">
        <div className="max-w-3xl mx-auto bg-white rounded-2xl shadow-lg p-8 md:p-12">
          <h1 className="text-3xl font-bold text-gray-900 mb-6">Terms of Service</h1>
          <p className="text-sm text-gray-500 mb-8">Last updated: {new Date().toLocaleDateString('en-US')}</p>

          <div className="prose prose-gray max-w-none space-y-6 text-gray-700">
            <section>
              <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-2">1. Acceptance of Terms</h2>
              <p>By accessing or using Call Surge and related services (&quot;Service&quot;), you agree to be bound by these Terms of Service. If you do not agree, do not use the Service.</p>
            </section>
            <section>
              <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-2">2. Description of Service</h2>
              <p>Call Surge provides an AI-powered voice and SMS receptionist for businesses. The Service includes call handling, appointment booking, SMS conversations, and a client dashboard. Features and availability may vary by plan.</p>
            </section>
            <section>
              <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-2">3. Use of the Service</h2>
              <p>You agree to use the Service only for lawful purposes and in accordance with these Terms. You are responsible for the content of calls and messages handled by the Service and for ensuring that your use complies with applicable laws, including telephony and data protection regulations.</p>
            </section>
            <section>
              <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-2">4. Payment and Subscriptions</h2>
              <p>Paid plans are billed monthly via our payment processor (Stripe). By subscribing, you authorize recurring charges. Refunds and cancellations are governed by our cancellation policy and applicable law. You may change or cancel your plan through the dashboard or the billing portal.</p>
            </section>
            <section>
              <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-2">5. SMS Messaging</h2>
              <p>
                Call Surge sends SMS messages on behalf of businesses using the Service. Message types include
                appointment confirmations, booking reminders, and conversational replies to customers who initiated
                contact by calling or texting the business. Message frequency varies based on customer interactions.
                Message and data rates may apply.
              </p>
              <p className="mt-2">
                Mobile phone numbers and SMS consent are never shared with third parties or affiliates for marketing
                purposes.
              </p>
              <p className="mt-2">
                To opt out of SMS messages, reply <strong>STOP</strong> at any time. You will receive a confirmation
                and no further messages will be sent. To opt back in, reply <strong>START</strong>.
                For help, reply <strong>HELP</strong> or contact us at{' '}
                <a href="mailto:info@nuvatrahq.com" className="text-blue-600 hover:underline">info@nuvatrahq.com</a>.
              </p>
            </section>
            <section>
              <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-2">6. Contact</h2>
              <p>For questions about these Terms, contact us at <a href="mailto:info@nuvatrahq.com" className="text-blue-600 hover:underline">info@nuvatrahq.com</a>.</p>
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
