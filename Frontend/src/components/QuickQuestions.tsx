import { useState, useEffect } from 'react'
import { getFaqs } from '../services/api'
import { getLabels } from '../i18n'
import type { FaqItem, Language } from '../types'

interface Props {
  language: Language
  onFaqClick: (question: string, answer: string) => void
}

export function QuickQuestions({ language, onFaqClick }: Props) {
  const [faqs, setFaqs] = useState<FaqItem[]>([])
  const labels = getLabels(language)

  useEffect(() => {
    getFaqs().then(setFaqs).catch(() => setFaqs([]))
  }, [])

  const langKey = language === 'auto' ? 'ko' : language

  if (faqs.length === 0) return null

  return (
    <div className="quick-card">
      <div className="quick-title">{labels.faqTitle}</div>
      <div className="quick-list">
        {faqs.map((faq) => {
          const question = faq[`question_${langKey}` as keyof FaqItem] as string || faq.question_ko
          const answer = faq[`answer_${langKey}` as keyof FaqItem] as string || faq.answer_ko
          return (
            <button
              key={faq.id}
              className="quick-button"
              onClick={() => onFaqClick(question, answer)}
            >
              <span className="quick-icon">↗</span>
              <span>{question}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
