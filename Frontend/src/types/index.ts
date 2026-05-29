export interface ChatRequest {
  question: string
  language?: string
  top_k?: number
}

export interface Source {
  source: string
  chunk_index: number
  similarity_score: number
}

export interface ChatResponse {
  answer: string
  sources: Source[]
  language?: string
  question: string
  suggestions : string[]
}

export interface HealthResponse {
  status: string
  database_status: string
  total_chunks: number
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
  language?: string
  timestamp: Date
  suggestions?: string[];
}

export interface UserProfile {
  id: string
  role: string
  nationality: string | null
}

export type Language = 'auto' | 'ko' | 'en' | 'zh' | 'es'

export interface FaqItem {
  id: string
  question_ko: string
  question_en: string
  question_zh: string
  question_es: string
  answer_ko: string
  answer_en: string
  answer_zh: string
  answer_es: string
  is_active: boolean
  display_order: number
  created_at?: string
}

export const LANGUAGE_LABELS: Record<Language, string> = {
  auto: '자동 감지',
  ko: '한국어',
  en: 'English',
  zh: '中文',
  es: 'Español',
}
