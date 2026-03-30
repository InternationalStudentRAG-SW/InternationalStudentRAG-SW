import { useEffect, useRef, useState } from 'react'
import { MessageBubble } from './MessageBubble'
import { LanguageSelector } from './LanguageSelector'
import type { Message, Language } from '../types'

interface Props {
  messages: Message[]
  isLoading: boolean
  error: string | null
  language: Language
  onSend: (question: string) => void
  onClear: () => void
  onLanguageChange: (lang: Language) => void
}

export function ChatInterface({
  messages,
  isLoading,
  error,
  language,
  onSend,
  onClear,
  onLanguageChange,
}: Props) {
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!input.trim()) return
    onSend(input.trim())
    setInput('')
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      if (!input.trim()) return
      onSend(input.trim())
      setInput('')
    }
  }

  return (
    <div className="chat-interface">
      {/* Header */}
      <div className="chat-header">
        <div>
          <div className="chat-header-title">Campus Chat</div>
          <div className="chat-header-sub">문서 기반 안내 · 빠른 응답</div>
        </div>
        <LanguageSelector value={language} onChange={onLanguageChange} />
      </div>

      {/* Messages */}
      <div className="chat-interface__messages">
        {messages.length === 0 && (
          <div className="chat-interface__empty">
            <p>질문을 입력하여 대화를 시작하세요.</p>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {isLoading && (
          <div className="message-row message-row--assistant">
            <img src="/dongA_character.png" className="bot-avatar" alt="bot" />
            <div className="message-wrap message-wrap--assistant">
              <div className="message__bubble message__bubble--loading">
                <div className="loading-dots">
                  <span className="loading-dot" />
                  <span className="loading-dot" />
                  <span className="loading-dot" />
                </div>
                <span>답변 작성 중...</span>
              </div>
            </div>
          </div>
        )}
        {error && <p className="chat-error">{error}</p>}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="chat-interface__input-area">
        <form onSubmit={handleSubmit}>
          <div className="input-box">
            <textarea
              className="chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="예: 기숙사 신청 기간은 언제인가요?"
              rows={1}
              disabled={isLoading}
            />
            <div className="input-actions">
              <button
                type="button"
                className="clear-btn"
                onClick={onClear}
                disabled={isLoading || messages.length === 0}
              >
                초기화
              </button>
              <button
                type="submit"
                className="send-btn"
                disabled={isLoading || !input.trim()}
              >
                전송
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}
