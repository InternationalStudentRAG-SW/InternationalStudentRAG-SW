import { useState } from 'react'
import { uploadPDF, uploadText, getHealth, clearDatabase } from '../services/api'
import type { HealthResponse } from '../types'

export function AdminPanel() {
  const [isOpen, setIsOpen] = useState(false)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [status, setStatus] = useState<string>('')
  const [isLoading, setIsLoading] = useState(false)

  // PDF upload state
  const [pdfFile, setPdfFile] = useState<File | null>(null)

  // Text upload state
  const [textFilename, setTextFilename] = useState('')
  const [textContent, setTextContent] = useState('')

  async function handleCheckHealth() {
    setIsLoading(true)
    try {
      const result = await getHealth()
      setHealth(result)
      setStatus('')
    } catch {
      setStatus('상태 확인 실패')
    } finally {
      setIsLoading(false)
    }
  }

  async function handlePdfUpload() {
    if (!pdfFile) return
    setIsLoading(true)
    try {
      const result = await uploadPDF(pdfFile)
      setStatus(result.message)
      setPdfFile(null)
    } catch {
      setStatus('PDF 업로드 실패')
    } finally {
      setIsLoading(false)
    }
  }

  async function handleTextUpload() {
    if (!textFilename.trim() || !textContent.trim()) return
    setIsLoading(true)
    try {
      const result = await uploadText(textFilename, textContent)
      setStatus(result.message)
      setTextFilename('')
      setTextContent('')
    } catch {
      setStatus('텍스트 업로드 실패')
    } finally {
      setIsLoading(false)
    }
  }

  async function handleClearDatabase() {
    if (!confirm('정말로 데이터베이스를 초기화하시겠습니까?')) return
    setIsLoading(true)
    try {
      const result = await clearDatabase()
      setStatus(result.message)
      setHealth(null)
    } catch {
      setStatus('DB 초기화 실패')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="admin-panel">
      <button className="admin-panel__toggle" onClick={() => setIsOpen((v) => !v)}>
        관리자 패널 {isOpen ? '▲' : '▼'}
      </button>

      {isOpen && (
        <div className="admin-panel__body">
          {/* Health */}
          <section>
            <h3>DB 상태</h3>
            <button onClick={handleCheckHealth} disabled={isLoading}>
              상태 확인
            </button>
            {health && (
              <ul className="health-info">
                <li>상태: {health.status}</li>
                <li>DB: {health.database_status}</li>
                <li>청크 수: {health.total_chunks}</li>
              </ul>
            )}
          </section>

          {/* PDF Upload */}
          <section>
            <h3>PDF 업로드</h3>
            <input
              type="file"
              accept=".pdf"
              onChange={(e) => setPdfFile(e.target.files?.[0] ?? null)}
            />
            <button onClick={handlePdfUpload} disabled={isLoading || !pdfFile}>
              업로드
            </button>
          </section>

          {/* Text Upload */}
          <section>
            <h3>텍스트 업로드</h3>
            <input
              type="text"
              placeholder="파일명 (예: notice.txt)"
              value={textFilename}
              onChange={(e) => setTextFilename(e.target.value)}
            />
            <textarea
              placeholder="문서 내용"
              rows={4}
              value={textContent}
              onChange={(e) => setTextContent(e.target.value)}
            />
            <button
              onClick={handleTextUpload}
              disabled={isLoading || !textFilename.trim() || !textContent.trim()}
            >
              업로드
            </button>
          </section>

          {/* Clear DB */}
          <section>
            <h3>DB 초기화</h3>
            <button
              className="danger-btn"
              onClick={handleClearDatabase}
              disabled={isLoading}
            >
              전체 삭제
            </button>
          </section>

          {status && <p className="admin-panel__status">{status}</p>}
        </div>
      )}
    </div>
  )
}
