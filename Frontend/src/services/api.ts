import axios from 'axios'
import type { ChatRequest, ChatResponse, HealthResponse } from '../types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const client = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
})

export async function sendMessage(
  question: string,
  language?: string,
  top_k?: number,
): Promise<ChatResponse> {
  const body: ChatRequest = { question }
  if (language && language !== 'auto') body.language = language
  if (top_k !== undefined) body.top_k = top_k
  const { data } = await client.post<ChatResponse>('/chat/', body)
  return data
}

export async function uploadPDF(file: File): Promise<{ message: string }> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await client.post<{ message: string }>('/admin/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function uploadText(
  filename: string,
  content: string,
): Promise<{ message: string }> {
  const { data } = await client.post<{ message: string }>('/admin/upload-text', {
    filename,
    content,
  })
  return data
}

export async function getHealth(): Promise<HealthResponse> {
  const { data } = await client.get<HealthResponse>('/admin/health')
  return data
}

export async function clearDatabase(): Promise<{ message: string }> {
  const { data } = await client.post<{ message: string }>('/admin/clear-database')
  return data
}
// 출처 문서(PDF)를 열기 위한 URL을 만들어주는 함수
export function getDocumentUrl(filename: string): string {
  // 특수문자까지 전부
  return `${BASE_URL}/documents/${encodeURIComponent(filename)}`
}