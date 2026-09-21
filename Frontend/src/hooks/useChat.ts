import { useState, useCallback, useRef } from 'react'
import { sendMessageStream } from '../services/api'
import type { Message, Language, MessageHistory } from '../types'

const CHARS_PER_FRAME = 3  // RAF당 렌더링할 최대 글자 수 (~60fps → 180chars/s)

function detectLang(text: string): string {
  if (/[가-힣]/.test(text)) return 'ko'
  if (/[一-鿿]/.test(text)) return 'zh'
  if (/[àáâãèéêìíîòóôùúûýăđơư]/i.test(text)) return 'vi'
  if (/[ñ¿¡]/i.test(text)) return 'es'
  return 'en'
}

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [language, setLanguage] = useState<Language>('auto')
  const messagesRef = useRef<Message[]>(messages)

  // 타이프라이터 큐
  const tokenQueueRef = useRef<string[]>([])
  const activeIdRef = useRef<string>('')
  const rafRef = useRef<number | null>(null)

  const drainQueue = useCallback(() => {
    rafRef.current = null
    const batch = tokenQueueRef.current.splice(0, CHARS_PER_FRAME)
    if (batch.length === 0) return
    const text = batch.join('')
    setMessages((prev) =>
      prev.map((m) =>
        m.id === activeIdRef.current ? { ...m, content: m.content + text } : m
      )
    )
    if (tokenQueueRef.current.length > 0) {
      rafRef.current = requestAnimationFrame(drainQueue)
    }
  }, [])

  function scheduleQueueDrain() {
    if (rafRef.current !== null) return
    rafRef.current = requestAnimationFrame(drainQueue)
  }

  function cancelQueueDrain() {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    tokenQueueRef.current = []
  }

  const send = useCallback(
    async (question: string) => {
      if (!question.trim() || isLoading) return

      const history: MessageHistory[] = messagesRef.current.map((m) => ({
        role: m.role,
        content: m.content,
      }))

      const userMessage: Message = {
        id: crypto.randomUUID(),
        role: 'user',
        content: question,
        timestamp: new Date(),
      }

      messagesRef.current = [...messagesRef.current, userMessage]
      setMessages((prev) => [...prev, userMessage])
      setIsLoading(true)
      setError(null)

      const streamingId = crypto.randomUUID()
      activeIdRef.current = streamingId
      tokenQueueRef.current = []

      const effectiveLang = language === 'auto' ? detectLang(question) : language
      const streamingMessage: Message = {
        id: streamingId,
        role: 'assistant',
        content: '',
        language: effectiveLang,
        timestamp: new Date(),
      }
      messagesRef.current = [...messagesRef.current, streamingMessage]
      setMessages((prev) => [...prev, streamingMessage])

      let streamedContent = ''
      let clarifyReceived = false

      try {
        await sendMessageStream(
          question,
          language,
          history,
          // onToken: 글자 단위로 큐에 쌓고 RAF로 드레인
          (token) => {
            streamedContent += token
            for (const char of token) {
              tokenQueueRef.current.push(char)
            }
            scheduleQueueDrain()
          },
          // onDone: clarify가 먼저 처리된 경우 스킵
          (sources, suggestions) => {
            if (clarifyReceived) return
            cancelQueueDrain()
            const finalMessage: Message = {
              id: streamingId,
              role: 'assistant',
              content: streamedContent,
              sources,
              suggestions,
              language,
              timestamp: new Date(),
            }
            messagesRef.current = messagesRef.current.map((m) =>
              m.id === streamingId ? finalMessage : m
            )
            setMessages((prev) =>
              prev.map((m) => (m.id === streamingId ? finalMessage : m))
            )
          },
          // onClarify
          (clarifyQuestion) => {
            clarifyReceived = true
            cancelQueueDrain()
            const clarifyMessage: Message = {
              id: streamingId,
              role: 'assistant',
              content: clarifyQuestion,
              timestamp: new Date(),
            }
            messagesRef.current = messagesRef.current.map((m) =>
              m.id === streamingId ? clarifyMessage : m
            )
            setMessages((prev) =>
              prev.map((m) => (m.id === streamingId ? clarifyMessage : m))
            )
          },
          // onError
          (errMsg) => {
            cancelQueueDrain()
            setError(errMsg)
            setMessages((prev) => prev.filter((m) => m.id !== streamingId))
            messagesRef.current = messagesRef.current.filter((m) => m.id !== streamingId)
          },
          // onStatus
          (step) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === streamingId
                  ? { ...m, statusSteps: [...(m.statusSteps ?? []), step] }
                  : m
              )
            )
          },
          // onMeta: 마지막 토큰 후, done 전 — 출처/추천질문 대기 표시
          (content) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === streamingId ? { ...m, metaStatus: content } : m
              )
            )
          },
        )
      } finally {
        setIsLoading(false)
      }
    },
    [isLoading, language, drainQueue],
  )

  const sendFaq = useCallback((question: string, answer: string) => {
    const faqMessages: Message[] = [
      { id: crypto.randomUUID(), role: 'user', content: question, timestamp: new Date() },
      { id: crypto.randomUUID(), role: 'assistant', content: answer, timestamp: new Date() },
    ]
    messagesRef.current = [...messagesRef.current, ...faqMessages]
    setMessages((prev) => [...prev, ...faqMessages])
    setError(null)
  }, [])

  const clearHistory = useCallback(() => {
    cancelQueueDrain()
    messagesRef.current = []
    setMessages([])
    setError(null)
  }, [])

  return { messages, isLoading, error, language, setLanguage, send, sendFaq, clearHistory }
}
