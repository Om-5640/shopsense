'use client'

import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Send, SkipForward, User } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface Message {
  id: string
  role: 'assistant' | 'user'
  content: string
  isTyping?: boolean
}

interface InterviewChatProps {
  currentQuestion: number
  totalQuestions: number
  messages: Message[]
  onSendMessage: (message: string) => void
  onSkip: () => void
  isWaitingForResponse: boolean
}

export function InterviewChat({
  currentQuestion,
  totalQuestions,
  messages,
  onSendMessage,
  onSkip,
  isWaitingForResponse,
}: InterviewChatProps) {
  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  
  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])
  
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (input.trim() && !isWaitingForResponse) {
      onSendMessage(input.trim())
      setInput('')
    }
  }
  
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      handleSubmit(e)
    }
  }
  
  const progress = (currentQuestion / totalQuestions) * 100
  
  return (
    <div className="h-full flex flex-col rounded-2xl bg-white/[0.02] border border-white/[0.06] overflow-hidden">
      {/* Progress Header */}
      <div className="p-4 border-b border-white/[0.06]">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-[#A1A1AA]">
            Question {currentQuestion} of {totalQuestions}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={onSkip}
            className="text-[#71717A] hover:text-[#FAFAFA]"
          >
            <SkipForward className="w-4 h-4 mr-1" />
            Skip
          </Button>
        </div>
        <div className="h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-gradient-to-r from-violet-600 to-violet-400 rounded-full"
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.3 }}
          />
        </div>
      </div>
      
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <AnimatePresence mode="popLayout">
          {messages.map((message) => (
            <motion.div
              key={message.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              className={cn(
                'flex gap-3',
                message.role === 'user' ? 'justify-end' : 'justify-start'
              )}
            >
              {message.role === 'assistant' && (
                <div className="w-8 h-8 rounded-full bg-violet-500/20 flex items-center justify-center shrink-0">
                  <div className="w-3 h-3 rounded-full bg-violet-400" />
                </div>
              )}
              
              <div
                className={cn(
                  'max-w-[80%] px-4 py-3 rounded-2xl',
                  message.role === 'user'
                    ? 'bg-white/[0.08] rounded-br-sm'
                    : 'bg-violet-500/10 border border-violet-500/20 rounded-bl-sm'
                )}
              >
                {message.isTyping ? (
                  <TypewriterText text={message.content} />
                ) : (
                  <p className="text-[#FAFAFA] text-sm leading-relaxed">
                    {message.content}
                  </p>
                )}
              </div>
              
              {message.role === 'user' && (
                <div className="w-8 h-8 rounded-full bg-white/[0.08] flex items-center justify-center shrink-0">
                  <User className="w-4 h-4 text-[#A1A1AA]" />
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>
        
        {/* Typing indicator */}
        {isWaitingForResponse && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex gap-3"
          >
            <div className="w-8 h-8 rounded-full bg-violet-500/20 flex items-center justify-center shrink-0">
              <div className="w-3 h-3 rounded-full bg-violet-400" />
            </div>
            <div className="bg-violet-500/10 border border-violet-500/20 rounded-2xl rounded-bl-sm px-4 py-3">
              <div className="flex gap-1">
                <motion.div
                  className="w-2 h-2 rounded-full bg-violet-400"
                  animate={{ opacity: [0.4, 1, 0.4] }}
                  transition={{ duration: 1, repeat: Infinity, delay: 0 }}
                />
                <motion.div
                  className="w-2 h-2 rounded-full bg-violet-400"
                  animate={{ opacity: [0.4, 1, 0.4] }}
                  transition={{ duration: 1, repeat: Infinity, delay: 0.2 }}
                />
                <motion.div
                  className="w-2 h-2 rounded-full bg-violet-400"
                  animate={{ opacity: [0.4, 1, 0.4] }}
                  transition={{ duration: 1, repeat: Infinity, delay: 0.4 }}
                />
              </div>
            </div>
          </motion.div>
        )}
        
        <div ref={messagesEndRef} />
      </div>
      
      {/* Input */}
      <form onSubmit={handleSubmit} className="p-4 border-t border-white/[0.06]">
        <div className="flex gap-3">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type your answer..."
            rows={1}
            className="flex-1 resize-none bg-white/[0.04] border border-white/[0.08] rounded-xl px-4 py-3 text-[#FAFAFA] text-sm placeholder:text-[#71717A] outline-none focus:border-violet-500/50 transition-colors"
          />
          <Button
            type="submit"
            disabled={!input.trim() || isWaitingForResponse}
            className="h-auto px-4 bg-violet-600 hover:bg-violet-500 disabled:opacity-50"
          >
            <Send className="w-4 h-4" />
          </Button>
        </div>
        <p className="text-xs text-[#71717A] mt-2 text-center">
          Press <kbd className="px-1.5 py-0.5 rounded bg-white/[0.04] text-[#A1A1AA]">Cmd</kbd> + <kbd className="px-1.5 py-0.5 rounded bg-white/[0.04] text-[#A1A1AA]">Enter</kbd> to send
        </p>
      </form>
    </div>
  )
}

// Typewriter effect component
function TypewriterText({ text }: { text: string }) {
  const [displayText, setDisplayText] = useState('')
  
  useEffect(() => {
    let index = 0
    const interval = setInterval(() => {
      if (index < text.length) {
        setDisplayText(text.slice(0, index + 1))
        index++
      } else {
        clearInterval(interval)
      }
    }, 20)
    
    return () => clearInterval(interval)
  }, [text])
  
  return (
    <p className="text-[#FAFAFA] text-sm leading-relaxed">
      {displayText}
      <motion.span
        animate={{ opacity: [0, 1, 0] }}
        transition={{ duration: 0.8, repeat: Infinity }}
        className="inline-block w-0.5 h-4 ml-0.5 bg-violet-400 align-middle"
      />
    </p>
  )
}
