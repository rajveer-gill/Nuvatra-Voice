export default function Loading() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 flex items-center justify-center">
      <div className="text-center">
        <div className="inline-block w-8 h-8 border-2 border-primary-600 border-t-transparent rounded-full animate-spin mb-4" />
        <p className="text-gray-600">Loading...</p>
      </div>
    </div>
  )
}
