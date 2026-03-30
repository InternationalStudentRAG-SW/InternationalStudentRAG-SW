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
}

export type Language = 'auto' | 'ko' | 'en' | 'zh' | 'es'

export const LANGUAGE_LABELS: Record<Language, string> = {
  auto: '자동 감지',
  ko: '한국어',
  en: 'English',
  zh: '中文',
  es: 'Español',
}
