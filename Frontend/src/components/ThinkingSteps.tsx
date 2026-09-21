import { useState, useEffect } from 'react'
import type { Language } from '../types'

const HINTS: Record<string, string[]> = {
  ko: ["자료를 꼼꼼히 살펴보는 중이에요", "관련 내용을 분석하고 있어요", "핵심 정보를 찾는 중이에요", "조금만 더 기다려 주세요"],
  en: ["Carefully reviewing documents...", "Analyzing related content...", "Finding key information...", "Just a moment more..."],
  zh: ["正在仔细查阅资料...", "正在分析相关内容...", "正在寻找关键信息...", "请稍候..."],
  es: ["Revisando documentos...", "Analizando contenido...", "Buscando información clave...", "Un momento más..."],
  vi: ["Đang xem xét tài liệu...", "Đang phân tích nội dung...", "Đang tìm thông tin quan trọng...", "Vui lòng chờ thêm..."],
}

const FALLBACK: Record<string, string> = {
  ko: "질문을 분석하는 중...",
  en: "Analyzing your question...",
  zh: "正在分析您的问题...",
  es: "Analizando tu pregunta...",
  vi: "Đang phân tích câu hỏi của bạn...",
}

interface Props {
  statusSteps: string[]
  language?: Language
}

export function ThinkingSteps({ statusSteps, language }: Props) {
  const [hintIndex, setHintIndex] = useState(0)
  const [visibleCount, setVisibleCount] = useState(1)

  const lang = (!language || language === 'auto') ? 'en' : language
  const hints = HINTS[lang] ?? HINTS.ko
  const fallback = FALLBACK[lang] ?? FALLBACK.ko

  useEffect(() => {
    if (statusSteps.length <= visibleCount) return
    const timer = setTimeout(() => {
      setVisibleCount((prev) => prev + 1)
    }, 450)
    return () => clearTimeout(timer)
  }, [statusSteps.length, visibleCount])

  const isSearching = visibleCount <= 2
  useEffect(() => {
    if (!isSearching) return
    const id = setInterval(() => {
      setHintIndex((i) => (i + 1) % hints.length)
    }, 2500)
    return () => clearInterval(id)
  }, [isSearching, hints])

  const steps = statusSteps.length > 0
    ? statusSteps.slice(0, visibleCount)
    : [fallback]

  return (
    <div className="thinking-steps">
      <div className="thinking-step-list">
        {steps.map((step, i) => {
          const isCurrent = i === steps.length - 1
          return (
            <div
              key={i}
              className={`thinking-step ${isCurrent ? 'thinking-step--current' : 'thinking-step--done'}`}
            >
              <span className={`thinking-step__icon ${isCurrent ? 'thinking-step__icon--spin' : ''}`}>
                {isCurrent ? '✦' : '✓'}
              </span>
              <div className="thinking-step__body">
                <span className="thinking-step__text">{step}</span>
                {isCurrent && isSearching && (
                  <span className="thinking-step__hint">{hints[hintIndex]}</span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
