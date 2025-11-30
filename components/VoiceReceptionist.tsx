'use client'

import { useState, useEffect, useRef } from 'react'
import { Mic, MicOff, Phone, PhoneOff, Volume2 } from 'lucide-react'
import axios from 'axios'

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function VoiceReceptionist() {
  const [isListening, setIsListening] = useState(false)
  const [isCallActive, setIsCallActive] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [isProcessing, setIsProcessing] = useState(false)
  const [sessionId] = useState(() => `session-${Date.now()}`)
  
  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const synthesisRef = useRef<SpeechSynthesis | null>(null)

  useEffect(() => {
    // Initialize Web Speech API
    if (typeof window !== 'undefined') {
      const SpeechRecognition = window.SpeechRecognition || (window as any).webkitSpeechRecognition
      if (SpeechRecognition) {
        recognitionRef.current = new SpeechRecognition()
        recognitionRef.current.continuous = true
        recognitionRef.current.interimResults = false
        recognitionRef.current.lang = 'en-US'

        recognitionRef.current.onresult = async (event: SpeechRecognitionEvent) => {
          const transcript = event.results[event.results.length - 1][0].transcript
          handleUserMessage(transcript)
        }

        recognitionRef.current.onerror = (event: any) => {
          console.error('Speech recognition error:', event.error)
          setIsListening(false)
        }

        recognitionRef.current.onend = () => {
          if (isCallActive && isListening) {
            recognitionRef.current?.start()
          }
        }
      }

      synthesisRef.current = window.speechSynthesis
    }

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop()
      }
      if (synthesisRef.current) {
        synthesisRef.current.cancel()
      }
    }
  }, [isCallActive, isListening])

  const handleUserMessage = async (text: string) => {
    if (!text.trim()) return

    const userMessage: Message = {
      role: 'user',
      content: text,
      timestamp: new Date()
    }

    setMessages(prev => [...prev, userMessage])
    setIsProcessing(true)
    setIsListening(false)

    try {
      const conversationHistory = messages.map(m => ({
        role: m.role,
        content: m.content
      }))

      const response = await axios.post(`${API_URL}/api/conversation`, {
        message: text,
        session_id: sessionId,
        conversation_history: conversationHistory
      })

      const aiMessage: Message = {
        role: 'assistant',
        content: response.data.response,
        timestamp: new Date()
      }

      setMessages(prev => [...prev, aiMessage])
      speakText(response.data.response)

      // Handle actions
      if (response.data.action === 'schedule_appointment') {
        // Could trigger appointment form
        console.log('Appointment scheduling requested')
      }
    } catch (error) {
      console.error('Error:', error)
      const errorMessage: Message = {
        role: 'assistant',
        content: "I'm sorry, I encountered an error. Please try again.",
        timestamp: new Date()
      }
      setMessages(prev => [...prev, errorMessage])
      speakText(errorMessage.content)
    } finally {
      setIsProcessing(false)
      if (isCallActive) {
        setTimeout(() => setIsListening(true), 500)
      }
    }
  }

  const speakText = (text: string) => {
    if (synthesisRef.current) {
      synthesisRef.current.cancel()
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.rate = 0.9
      utterance.pitch = 1.0
      utterance.volume = 1.0
      synthesisRef.current.speak(utterance)
    }
  }

  const startCall = () => {
    setIsCallActive(true)
    setMessages([])
    
    // Initial greeting
    const greeting: Message = {
      role: 'assistant',
      content: "Hello! Thank you for calling. This is your AI receptionist. How may I assist you today?",
      timestamp: new Date()
    }
    setMessages([greeting])
    speakText(greeting.content)

    // Start listening after greeting
    setTimeout(() => {
      setIsListening(true)
      recognitionRef.current?.start()
    }, 2000)
  }

  const endCall = () => {
    setIsCallActive(false)
    setIsListening(false)
    recognitionRef.current?.stop()
    synthesisRef.current?.cancel()
    
    const closing: Message = {
      role: 'assistant',
      content: "Thank you for calling. Have a great day!",
      timestamp: new Date()
    }
    setMessages(prev => [...prev, closing])
  }

  const toggleListening = () => {
    if (isListening) {
      recognitionRef.current?.stop()
      setIsListening(false)
    } else {
      recognitionRef.current?.start()
      setIsListening(true)
    }
  }

  return (
    <div className="max-w-4xl mx-auto">
      <div className="bg-white rounded-2xl shadow-xl p-8">
        {/* Call Controls */}
        <div className="flex justify-center items-center mb-8 space-x-4">
          {!isCallActive ? (
            <button
              onClick={startCall}
              className="flex items-center space-x-2 bg-green-500 hover:bg-green-600 text-white px-6 py-3 rounded-full font-semibold transition-all shadow-lg hover:shadow-xl"
            >
              <Phone className="w-5 h-5" />
              <span>Start Call</span>
            </button>
          ) : (
            <>
              <button
                onClick={toggleListening}
                disabled={isProcessing}
                className={`flex items-center space-x-2 px-6 py-3 rounded-full font-semibold transition-all shadow-lg ${
                  isListening
                    ? 'bg-red-500 hover:bg-red-600 text-white'
                    : 'bg-gray-300 hover:bg-gray-400 text-gray-700'
                } ${isProcessing ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                {isListening ? (
                  <>
                    <MicOff className="w-5 h-5" />
                    <span>Mute</span>
                  </>
                ) : (
                  <>
                    <Mic className="w-5 h-5" />
                    <span>Unmute</span>
                  </>
                )}
              </button>
              <button
                onClick={endCall}
                className="flex items-center space-x-2 bg-red-500 hover:bg-red-600 text-white px-6 py-3 rounded-full font-semibold transition-all shadow-lg hover:shadow-xl"
              >
                <PhoneOff className="w-5 h-5" />
                <span>End Call</span>
              </button>
            </>
          )}
        </div>

        {/* Status Indicator */}
        {isCallActive && (
          <div className="text-center mb-6">
            <div className="inline-flex items-center space-x-2 px-4 py-2 bg-primary-100 rounded-full">
              {isListening && (
                <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
              )}
              <span className="text-sm font-medium text-primary-700">
                {isProcessing
                  ? 'Processing...'
                  : isListening
                  ? 'Listening...'
                  : 'Call Active'}
              </span>
            </div>
          </div>
        )}

        {/* Conversation */}
        <div className="bg-gray-50 rounded-lg p-6 h-96 overflow-y-auto mb-6">
          {messages.length === 0 ? (
            <div className="text-center text-gray-500 mt-20">
              <Volume2 className="w-16 h-16 mx-auto mb-4 opacity-50" />
              <p>Click "Start Call" to begin a conversation</p>
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((message, index) => (
                <div
                  key={index}
                  className={`flex ${
                    message.role === 'user' ? 'justify-end' : 'justify-start'
                  }`}
                >
                  <div
                    className={`max-w-[80%] rounded-lg px-4 py-2 ${
                      message.role === 'user'
                        ? 'bg-primary-600 text-white'
                        : 'bg-white text-gray-800 border border-gray-200'
                    }`}
                  >
                    <p className="text-sm">{message.content}</p>
                    <p className="text-xs mt-1 opacity-70">
                      {message.timestamp.toLocaleTimeString()}
                    </p>
                  </div>
                </div>
              ))}
              {isProcessing && (
                <div className="flex justify-start">
                  <div className="bg-white rounded-lg px-4 py-2 border border-gray-200">
                    <div className="flex space-x-1">
                      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }}></div>
                      <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Instructions */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <h3 className="font-semibold text-blue-900 mb-2">How it works:</h3>
          <ul className="text-sm text-blue-800 space-y-1 list-disc list-inside">
            <li>Click "Start Call" to begin a conversation</li>
            <li>Speak naturally - the AI will understand and respond</li>
            <li>The receptionist can schedule appointments, take messages, and answer questions</li>
            <li>Use "Mute" to temporarily stop listening</li>
          </ul>
        </div>
      </div>
    </div>
  )
}

// Extend Window interface for TypeScript
declare global {
  interface Window {
    SpeechRecognition: typeof SpeechRecognition
    webkitSpeechRecognition: typeof SpeechRecognition
  }
}



