import Link from 'next/link'
import Image from 'next/image'
import { Rocket, Lightbulb, Shield, TrendingUp } from 'lucide-react'
import MarketingNav from '@/components/MarketingNav'
import ContactForm from '@/components/ContactForm'

export default function HomePage() {
  return (
    <>
      <MarketingNav />
      <main>
        {/* Hero */}
        <section id="home" className="pt-24 pb-20 px-4 bg-gradient-to-br from-[#1a1a2e] via-[#16213e] to-[#0f3460] text-white text-center">
          <div className="max-w-3xl mx-auto">
            <h1 className="text-4xl md:text-5xl font-bold mb-4 bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent">
              Innovative AI Solutions
            </h1>
            <p className="text-xl text-white/90 mb-8 font-light">
              Transforming businesses with cutting-edge artificial intelligence technology
            </p>
            <Link href="#products" className="inline-block px-10 py-4 rounded-full bg-gradient-to-r from-blue-600 to-blue-500 text-white font-semibold shadow-lg hover:shadow-xl hover:-translate-y-0.5 transition">
              Explore Our Products
            </Link>
          </div>
        </section>

        {/* Products */}
        <section id="products" className="py-20 px-4 bg-gray-50">
          <div className="max-w-6xl mx-auto">
            <h2 className="text-3xl font-bold text-center text-gray-900 mb-12">Our Products</h2>
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
              {/* Grubify */}
              <div className="bg-white rounded-2xl p-8 shadow-lg text-center hover:shadow-xl hover:-translate-y-2 transition">
                <div className="h-28 flex items-center justify-center mb-6">
                  <div className="w-24 h-24 rounded-xl bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center text-white text-4xl font-bold">G</div>
                </div>
                <h3 className="text-xl font-semibold mb-3">Grubify</h3>
                <p className="text-gray-600 mb-4">
                  Intelligent food ordering and restaurant management platform powered by AI.
                </p>
                <a href="https://grubify.ai" target="_blank" rel="noopener noreferrer" className="text-blue-600 font-semibold hover:underline">
                  Visit Grubify.ai →
                </a>
              </div>

              {/* RepsRight */}
              <div className="bg-gradient-to-br from-indigo-600 to-purple-600 rounded-2xl p-8 shadow-lg text-center hover:shadow-xl hover:-translate-y-2 transition text-white">
                <div className="h-28 flex items-center justify-center mb-6">
                  <Image src="/assets/repsright-logo.svg" alt="RepsRight" width={120} height={90} />
                </div>
                <h3 className="text-xl font-semibold mb-3">RepsRight</h3>
                <p className="text-white/90 mb-4">
                  Your AI-powered fitness companion with personalized workout plans and real-time form analysis.
                </p>
                <a href="https://apps.apple.com/us/app/repsright/id6754855530" target="_blank" rel="noopener noreferrer" className="text-white font-semibold hover:underline">
                  Download on App Store →
                </a>
              </div>

              {/* Nuvatra Voice */}
              <div className="bg-white rounded-2xl p-8 shadow-lg text-center hover:shadow-xl hover:-translate-y-2 transition">
                <div className="h-28 flex items-center justify-center mb-6">
                  <Image src="/assets/nuvatra-voice-logo.svg" alt="Nuvatra Voice" width={100} height={100} />
                </div>
                <h3 className="text-xl font-semibold mb-3">Nuvatra Voice</h3>
                <p className="text-gray-600 mb-4">
                  AI-powered receptionist that handles your calls 24/7. Never miss a call again.
                </p>
                <Link href="/dashboard" className="text-blue-600 font-semibold hover:underline">
                  Log in to Nuvatra Voice →
                </Link>
              </div>
            </div>
          </div>
        </section>

        {/* Features */}
        <section className="py-20 px-4 bg-white">
          <div className="max-w-6xl mx-auto">
            <h2 className="text-3xl font-bold text-center text-gray-900 mb-12">Why Choose Nuvatra</h2>
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-8 text-center">
              <div>
                <div className="inline-flex p-3 rounded-xl bg-blue-100 text-blue-600 mb-4"><Rocket size={32} /></div>
                <h3 className="text-lg font-semibold mb-2">Innovation First</h3>
                <p className="text-gray-600">Cutting-edge AI technology that pushes boundaries</p>
              </div>
              <div>
                <div className="inline-flex p-3 rounded-xl bg-amber-100 text-amber-600 mb-4"><Lightbulb size={32} /></div>
                <h3 className="text-lg font-semibold mb-2">Smart Solutions</h3>
                <p className="text-gray-600">Intelligent automation that simplifies complex tasks</p>
              </div>
              <div>
                <div className="inline-flex p-3 rounded-xl bg-green-100 text-green-600 mb-4"><Shield size={32} /></div>
                <h3 className="text-lg font-semibold mb-2">Reliable & Secure</h3>
                <p className="text-gray-600">Enterprise-grade security and reliability you can trust</p>
              </div>
              <div>
                <div className="inline-flex p-3 rounded-xl bg-purple-100 text-purple-600 mb-4"><TrendingUp size={32} /></div>
                <h3 className="text-lg font-semibold mb-2">Scalable Growth</h3>
                <p className="text-gray-600">Solutions that grow with your business needs</p>
              </div>
            </div>
          </div>
        </section>

        {/* Contact */}
        <section id="contact" className="py-20 px-4 bg-gray-50">
          <div className="max-w-4xl mx-auto">
            <h2 className="text-3xl font-bold text-center text-gray-900 mb-4">Get In Touch</h2>
            <p className="text-center text-gray-600 mb-12">Have questions? We&apos;d love to hear from you.</p>
            <div className="grid md:grid-cols-2 gap-12 items-start">
              <div>
                <div className="mb-6">
                  <h3 className="font-semibold text-gray-900 mb-2">Email</h3>
                  <a href="mailto:info@nuvatrahq.com" className="text-blue-600 hover:underline">info@nuvatrahq.com</a>
                </div>
                <div>
                  <h3 className="font-semibold text-gray-900 mb-2">Website</h3>
                  <a href="https://nuvatrahq.com" className="text-blue-600 hover:underline">nuvatrahq.com</a>
                </div>
              </div>
              <div className="bg-white p-8 rounded-xl shadow-lg">
                <ContactForm />
              </div>
            </div>
          </div>
        </section>

        {/* Footer */}
        <footer className="bg-black text-white py-12 px-4">
          <div className="max-w-6xl mx-auto flex flex-col md:flex-row justify-between items-center gap-6">
            <div className="flex items-center gap-2">
              <Image src="/assets/nuvatra-logo.svg" alt="Nuvatra" width={35} height={35} className="invert" />
              <span className="font-semibold tracking-wider">NUVATRA</span>
            </div>
            <div className="flex gap-8">
              <Link href="/#home" className="text-white/80 hover:text-white">Home</Link>
              <Link href="/#products" className="text-white/80 hover:text-white">Products</Link>
              <Link href="/#contact" className="text-white/80 hover:text-white">Contact</Link>
            </div>
            <p className="text-white/70 text-sm">&copy; {new Date().getFullYear()} Nuvatra. All rights reserved.</p>
          </div>
        </footer>
      </main>
    </>
  )
}
