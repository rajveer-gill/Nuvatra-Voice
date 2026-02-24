'use client'

import { useState, useEffect, useRef } from 'react'
import { Mic, MicOff, Phone, PhoneOff, Volume2 } from 'lucide-react'
import { useApiClient } from '@/lib/api'

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

export default function VoiceReceptionist() {
  const api = useApiClient()
  const [isListening, setIsListening] = useState(false)
  const [isCallActive, setIsCallActive] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [isProcessing, setIsProcessing] = useState(false)
  const [sessionId] = useState(() => `session-${Date.now()}`)
  
  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const isSpeakingRef = useRef<boolean>(false)
  const shouldRestartListeningRef = useRef<boolean>(false)
  const isRecognitionActiveRef = useRef<boolean>(false)
  const [selectedVoice, setSelectedVoice] = useState<string>('fable') // OpenAI voice: alloy, echo, fable, onyx, nova, shimmer


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
          isRecognitionActiveRef.current = false
        }

        // Use addEventListener for onstart (more compatible)
        recognitionRef.current.addEventListener('start', () => {
          isRecognitionActiveRef.current = true
        })

        recognitionRef.current.onend = () => {
          isRecognitionActiveRef.current = false
          // Don't auto-restart here - let the audio onended handler manage it
          // This prevents double-starting issues
        }
      }

      // Initialize audio element for TTS playback
      audioRef.current = new Audio()
      audioRef.current.onended = () => {
        isSpeakingRef.current = false
        // Clean up the object URL to prevent memory leaks
        if (audioRef.current?.src) {
          URL.revokeObjectURL(audioRef.current.src)
        }
        // Wait a moment after speech completes, then restart listening
        setTimeout(() => {
          if (shouldRestartListeningRef.current && isCallActive && !isRecognitionActiveRef.current) {
            shouldRestartListeningRef.current = false
            setIsListening(true)
            try {
              if (recognitionRef.current && !isRecognitionActiveRef.current) {
                recognitionRef.current.start()
              }
            } catch (error: any) {
              // Recognition might already be starting, ignore the error
              if (error.name !== 'InvalidStateError') {
                console.log('Recognition start error:', error.message)
              }
            }
          }
        }, 500)
      }
      
      audioRef.current.onerror = (e) => {
        console.error('Audio playback error:', e)
        isSpeakingRef.current = false
        // Clean up on error
        if (audioRef.current?.src) {
          URL.revokeObjectURL(audioRef.current.src)
        }
      }
    }

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop()
      }
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current.src = ''
      }
    }
  }, [isCallActive])

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
    if (recognitionRef.current && isRecognitionActiveRef.current) {
      recognitionRef.current.stop()
      isRecognitionActiveRef.current = false
    }
    shouldRestartListeningRef.current = true

    try {
      const conversationHistory = messages.map(m => ({
        role: m.role,
        content: m.content
      }))

      const response = await api.post('/api/conversation', {
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
      
      // Speak the response and wait for it to complete before restarting listening
      await speakText(response.data.response)

      // Handle actions
      if (response.data.action === 'schedule_appointment') {
        // Could trigger appointment form
        console.log('Appointment scheduling requested')
      }
    } catch (error) {
      console.error('Error:', error)
      const errorMessage: Message = {
        role: 'assistant',
        content: "Oh no, I'm so sorry about that! I had a little technical hiccup. No worries though - let's try that again! I'm here to help!",
        timestamp: new Date()
      }
      setMessages(prev => [...prev, errorMessage])
      await speakText(errorMessage.content)
    } finally {
      setIsProcessing(false)
    }
  }

  const speakText = async (text: string): Promise<void> => {
    try {
      if (!audioRef.current) {
        console.error('Audio element not initialized')
        return
      }

      // Stop any ongoing speech and clean up
      if (isSpeakingRef.current && audioRef.current.src) {
        audioRef.current.pause()
        URL.revokeObjectURL(audioRef.current.src)
        audioRef.current.src = ''
      }

      isSpeakingRef.current = true

      console.log('Calling TTS endpoint with voice:', selectedVoice)
      
      // Call backend TTS endpoint
      const response = await api.post(
        '/api/text-to-speech',
        {
          text: text,
          voice: selectedVoice
        },
        {
          responseType: 'blob',
          timeout: 30000 // 30 second timeout
        }
      )

      if (!response.data || response.data.size === 0) {
        throw new Error('Empty audio response from server')
      }

      // Create audio URL from blob
      const audioBlob = new Blob([response.data], { type: 'audio/mpeg' })
      const audioUrl = URL.createObjectURL(audioBlob)

      // Set up audio before playing
      audioRef.current.src = audioUrl
      audioRef.current.load() // Ensure audio is loaded
      
      // Play audio and wait for it to start
      await audioRef.current.play()
      console.log('Premium AI voice playing successfully')

      // Note: Audio onended handler will handle restarting listening
    } catch (error: any) {
      console.error('TTS error:', error)
      isSpeakingRef.current = false
      
      // Clean up on error
      if (audioRef.current?.src) {
        URL.revokeObjectURL(audioRef.current.src)
        audioRef.current.src = ''
      }
      
      // Show user-friendly error message
      const errorMsg: Message = {
        role: 'assistant',
        content: "I'm having trouble with my voice right now. Could you try again in a moment?",
        timestamp: new Date()
      }
      setMessages(prev => [...prev, errorMsg])
      
      // Restart listening even if TTS fails
      setTimeout(() => {
        if (shouldRestartListeningRef.current && isCallActive && !isRecognitionActiveRef.current) {
          shouldRestartListeningRef.current = false
          setIsListening(true)
          try {
            if (recognitionRef.current && !isRecognitionActiveRef.current) {
              recognitionRef.current.start()
            }
          } catch (e: any) {
            if (e.name !== 'InvalidStateError') {
              console.log('Recognition start error:', e.message)
            }
          }
        }
      }, 500)
    }
  }

  const startCall = async () => {
    setIsCallActive(true)
    setMessages([])
    shouldRestartListeningRef.current = true
    
    // Initial greeting - upbeat, warm, and enthusiastic
    const greeting: Message = {
      role: 'assistant',
      content: "Hi there! Thanks so much for calling! I'm really excited to help you today! What can I do for you?",
      timestamp: new Date()
    }
    setMessages([greeting])
    
    // Speak greeting and wait for it to complete before starting to listen
    await speakText(greeting.content)
  }

  const endCall = () => {
    setIsCallActive(false)
    setIsListening(false)
    shouldRestartListeningRef.current = false
    
    if (recognitionRef.current && isRecognitionActiveRef.current) {
      recognitionRef.current.stop()
      isRecognitionActiveRef.current = false
    }
    
    // Stop any ongoing speech
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.src = ''
    }
    isSpeakingRef.current = false
    
    const closing: Message = {
      role: 'assistant',
      content: "Thanks so much for calling! It was wonderful talking with you! Have an absolutely amazing day!",
      timestamp: new Date()
    }
    setMessages(prev => [...prev, closing])
  }

  const toggleListening = () => {
    if (isListening) {
      if (recognitionRef.current && isRecognitionActiveRef.current) {
        recognitionRef.current.stop()
        isRecognitionActiveRef.current = false
      }
      setIsListening(false)
    } else {
      if (recognitionRef.current && !isRecognitionActiveRef.current) {
        try {
          recognitionRef.current.start()
          setIsListening(true)
        } catch (error) {
          console.log('Recognition start skipped (already active)')
        }
      }
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

        {/* Voice Selection */}
        {!isCallActive && (
          <div className="bg-purple-50 border border-purple-200 rounded-lg p-4 mb-4">
            <h3 className="font-semibold text-purple-900 mb-3">Voice Settings:</h3>
            <div className="flex flex-wrap gap-2">
              {['nova', 'alloy', 'echo', 'fable', 'onyx', 'shimmer'].map((voice) => (
                <button
                  key={voice}
                  onClick={() => setSelectedVoice(voice)}
                  className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                    selectedVoice === voice
                      ? 'bg-purple-600 text-white shadow-md'
                      : 'bg-white text-purple-700 hover:bg-purple-100 border border-purple-300'
                  }`}
                >
                  {voice.charAt(0).toUpperCase() + voice.slice(1)}
                  {voice === 'fable' && ' ⭐'}
                </button>
              ))}
            </div>
            <p className="text-xs text-purple-700 mt-2">
              ⭐ Fable is recommended for natural, warm conversations
            </p>
          </div>
        )}

        {/* Instructions */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <h3 className="font-semibold text-blue-900 mb-2">How it works:</h3>
          <ul className="text-sm text-blue-800 space-y-1 list-disc list-inside">
            <li>Click "Start Call" to begin a conversation</li>
            <li>Speak naturally - the AI will understand and respond</li>
            <li>The receptionist can schedule appointments, take messages, and answer questions</li>
            <li>Use "Mute" to temporarily stop listening</li>
            <li>Powered by OpenAI for ultra-realistic voice quality</li>
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



