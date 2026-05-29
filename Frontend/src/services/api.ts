import axios from 'axios'
import type { ChatRequest, ChatResponse, HealthResponse, UserProfile, FaqItem } from '../types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const client = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
})

// JWT 자동 첨부
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
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

export async function adminSignup(
  email: string,
  password: string,
  adminSecret: string,
): Promise<{ message: string; user_id: string }> {
  const { data } = await client.post('/api/admin-signup', {
    email,
    password,
    admin_secret: adminSecret,
  })
  return data
}

export async function getMe(): Promise<UserProfile> {
  const { data } = await client.get<UserProfile>('/api/me')
  return data
}

export async function login(
  email: string,
  password: string,
): Promise<{ access_token: string; token_type: string; user_id: string; role: string }> {
  const { data } = await client.post('/api/login', { email, password })
  return data
}

export async function signup(
  email: string,
  password: string,
  nationality: string,
  major?: string,
): Promise<{ message: string; user_id: string }> {
  const { data } = await client.post('/api/signup', {
    email,
    password,
    nationality,
    major,
    role: 'STUDENT',
    status: 'ACTIVE',
  })
  return data
}

export async function updateAdditionalInfo(
  nationality: string,
  major?: string,
): Promise<{ message: string }> {
  const { data } = await client.post('/api/update-additional-info', { nationality, major })
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

export function getDocumentUrl(filename: string): string {
  return `${BASE_URL}/documents/${encodeURIComponent(filename)}`
}

export async function getDocuments(): Promise<{ documents: string[]; total: number }> {
  const { data } = await client.get<{ documents: string[]; total: number }>('/admin/documents')
  return data
}

export async function deleteDocument(filename: string): Promise<{ status: string; filename: string }> {
  const { data } = await client.delete<{ status: string; filename: string }>(
    `/admin/documents/${encodeURIComponent(filename)}`
  )
  return data
}

export interface ChatLog {
  id: string
  created_at: string
  query: string
  answer: string
  sources: Array<{ source: string; chunk_index: number; similarity_score: number }>
  language: string
}

export interface ChatStats {
  total: number
  today: number
  by_language: Record<string, number>
}

export async function getChatLogs(params: {
  page?: number
  limit?: number
  language?: string
  search?: string
  date_from?: string
  date_to?: string
}): Promise<{ logs: ChatLog[]; total: number; page: number; limit: number }> {
  const { data } = await client.get('/admin/chat-logs', { params })
  return data
}

export async function getChatStats(): Promise<ChatStats> {
  const { data } = await client.get('/admin/chat-stats')
  return data
}

export async function getChatDaily(): Promise<{ daily: Array<{ date: string; count: number }> }> {
  const { data } = await client.get('/admin/chat-daily')
  return data
}

export interface Member {
  id: string
  email: string
  role: string
  nationality: string
  major: string | null
  status: string
  created_at: string
}

export interface MemberStats {
  total: number
  today: number
  by_nationality: Record<string, number>
  daily: Array<{ date: string; count: number }>
}

export async function getUsers(params: {
  page?: number
  limit?: number
  role?: string
  status?: string
  search?: string
}): Promise<{ users: Member[]; total: number; page: number; limit: number }> {
  const { data } = await client.get('/admin/users', { params })
  return data
}

export async function getUserStats(): Promise<MemberStats> {
  const { data } = await client.get('/admin/user-stats')
  return data
}

export async function updateUserRole(userId: string, role: string): Promise<{ message: string }> {
  const { data } = await client.patch(`/admin/users/${userId}/role`, { role })
  return data
}

export async function updateUserStatus(userId: string, status: string): Promise<{ message: string }> {
  const { data } = await client.patch(`/admin/users/${userId}/status`, { status })
  return data
}

export async function deleteUser(userId: string): Promise<{ message: string }> {
  const { data } = await client.delete(`/admin/users/${userId}`)
  return data
}

// --- FAQ API ---
export async function getFaqs(): Promise<FaqItem[]> {
  const { data } = await client.get<FaqItem[]>('/faq')
  return data
}

export async function getAdminFaqs(): Promise<FaqItem[]> {
  const { data } = await client.get<FaqItem[]>('/faq/all')
  return data
}

export async function createFaq(question_ko: string, answer_ko: string): Promise<FaqItem> {
  const { data } = await client.post<FaqItem>('/faq', { question_ko, answer_ko })
  return data
}

export async function updateFaq(
  id: string,
  updates: { answer_ko?: string; is_active?: boolean; display_order?: number },
): Promise<FaqItem> {
  const { data } = await client.patch<FaqItem>(`/faq/${id}`, updates)
  return data
}

export async function deleteFaq(id: string): Promise<void> {
  await client.delete(`/faq/${id}`)
}

export async function analyzeLogs(params?: {
  date_from?: string
  date_to?: string
}): Promise<{ candidates: Array<{ question_ko: string; answer_ko: string }> }> {
  const { data } = await client.post('/faq/analyze', params ?? {})
  return data
}

export async function reorderFaqs(
  items: Array<{ id: string; display_order: number }>,
): Promise<void> {
  await client.post('/faq/reorder', { items })
}

export async function bulkCreateFaqs(
  items: Array<{ question_ko: string; answer_ko: string }>,
): Promise<{ message: string }> {
  const { data } = await client.post<{ message: string }>('/faq/bulk-create', { items })
  return data
}
