import Link from 'next/link'
import MarketingNav from '@/components/MarketingNav'

export default function PrivacyPage() {
  return (
    <>
      <MarketingNav />
      <main className="min-h-screen bg-gray-50 py-12 px-4">
        <div className="max-w-3xl mx-auto bg-white rounded-2xl shadow-lg p-8 md:p-12">
          <h1 className="text-3xl font-bold text-gray-900 mb-6">Privacy Policy</h1>
          <p className="text-sm text-gray-500 mb-8">Last updated: {new Date().toLocaleDateString('en-US')}</p>

          <div className="prose prose-gray max-w-none space-y-6 text-gray-700">
            <section>
              <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-2">1. Information We Collect</h2>
              <p>We collect and process information necessary to provide the Service, including: account and profile information (via our identity provider); business and configuration data you enter (business name, hours, services, forwarding numbers); call and SMS content and metadata (phone numbers, transcripts, and call outcomes); and payment information processed by our payment provider (Stripe). We do not store full payment card numbers on our servers.</p>
            </section>
            <section>
              <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-2">2. How We Use Information</h2>
              <p>We use this information to operate the AI receptionist (e.g., answering calls and texts, booking appointments), to provide and secure your dashboard, to process payments, and to improve the Service. Call and message data may be retained for analytics and support purposes as described in our data retention practices.</p>
            </section>
            <section>
              <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-2">3. Data Retention</h2>
              <p>We retain call logs, appointment data, and SMS conversation history for as long as your account is active and as needed to provide the Service and comply with legal obligations. You may request deletion of your data by contacting us.</p>
            </section>
            <section>
              <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-2">4. Third-Party Services</h2>
              <p>We use third-party services for authentication (Clerk), communications (Twilio), payments (Stripe), and AI (OpenAI). Their respective privacy policies apply to data they process. We do not sell your personal information to third parties.</p>
            </section>
            <section>
              <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-2">5. SMS and Your Choices</h2>
              <p>
                If you text or receive texts from a business using Nuvatra Voice, we process your phone number,
                message content, and related metadata to deliver the service (e.g. appointment updates and replies).
                Message and data rates may apply according to your carrier.
              </p>
              <p className="mt-2">
                Mobile phone numbers and SMS consent are never shared with third parties or affiliates for marketing
                purposes. Message frequency varies based on your interactions with our service.
              </p>
              <p className="mt-2">
                You may opt out of further SMS from that business&apos;s number by replying <strong>STOP</strong>.
                We record that preference so our systems do not send further messages to your number for that business
                until you reply <strong>START</strong> to resubscribe. For help with SMS, reply <strong>HELP</strong> or
                contact us at{' '}
                <a href="mailto:info@nuvatrahq.com" className="text-blue-600 hover:underline">info@nuvatrahq.com</a>.
                Additional terms for SMS are in our{' '}
                <Link href="/terms" className="text-blue-600 hover:underline">Terms of Service</Link>.
              </p>
            </section>
            <section>
              <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-2">6. Contact</h2>
              <p>For privacy-related questions or requests, contact us at <a href="mailto:info@nuvatrahq.com" className="text-blue-600 hover:underline">info@nuvatrahq.com</a>.</p>
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
