'use client'

export default function SentryExamplePage() {
  return (
    <main className="min-h-screen bg-gray-50 py-12 px-4">
      <div className="max-w-2xl mx-auto bg-white rounded-2xl shadow-lg p-8 md:p-12">
        <h1 className="text-3xl font-bold text-gray-900 mb-4">Sentry Test Page</h1>
        <p className="text-gray-700 mb-6">
          Click the button below to throw a test client-side error and verify Sentry reporting.
        </p>
        <button
          type="button"
          onClick={() => {
            throw new Error('Sentry Example Frontend Error')
          }}
          className="inline-flex items-center rounded-lg bg-black text-white px-4 py-2 hover:bg-gray-800"
        >
          Throw test error
        </button>
      </div>
    </main>
  )
}
