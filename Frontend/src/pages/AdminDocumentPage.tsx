import { useState, useEffect, useRef } from 'react'
import {
  getDocuments,
  deleteDocument,
  uploadPDF,
  uploadText,
  clearDatabase,
  getDocumentUrl,
} from '../services/api'
import AdminLayout from '../components/AdminLayout'
import './admin.css'

export default function AdminDocumentPage() {
  // Data state
  const [documents, setDocuments] = useState<string[]>([])
  const [totalDocs, setTotalDocs] = useState(0)
  const [loading, setLoading] = useState(true)

  // Upload state
  const [uploadTab, setUploadTab] = useState<'pdf' | 'text'>('pdf')
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [isDragOver, setIsDragOver] = useState(false)
  const [textFilename, setTextFilename] = useState('')
  const [textContent, setTextContent] = useState('')
  const [uploading, setUploading] = useState(false)

  // Modal state
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [showClearModal, setShowClearModal] = useState(false)
  const [clearConfirmInput, setClearConfirmInput] = useState('')
  const [deleting, setDeleting] = useState(false)

  // Toast state
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)

  const showToast = (type: 'success' | 'error', message: string) => {
    if (toastTimer.current) clearTimeout(toastTimer.current)
    setToast({ type, message })
    toastTimer.current = setTimeout(() => setToast(null), 3000)
  }

  const loadData = async () => {
    try {
      const docs = await getDocuments()
      setDocuments(docs.documents)
      setTotalDocs(docs.total)
    } catch {
      showToast('error', '데이터를 불러오는 데 실패했습니다.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
    return () => {
      if (toastTimer.current) clearTimeout(toastTimer.current)
    }
  }, [])

  const handleFileSelect = (files: FileList | File[]) => {
    const arr = Array.from(files)
    const invalid = arr.filter(f => !f.name.toLowerCase().endsWith('.pdf'))
    if (invalid.length > 0) {
      showToast('error', 'PDF 파일만 업로드할 수 있습니다.')
    }
    const valid = arr.filter(f => f.name.toLowerCase().endsWith('.pdf'))
    if (valid.length === 0) return
    setSelectedFiles(prev => {
      const existing = new Set(prev.map(f => f.name))
      return [...prev, ...valid.filter(f => !existing.has(f.name))]
    })
  }

  const handleRemoveFile = (name: string) => {
    setSelectedFiles(prev => prev.filter(f => f.name !== name))
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    if (e.dataTransfer.files.length > 0) handleFileSelect(e.dataTransfer.files)
  }

  const handlePdfUpload = async () => {
    if (selectedFiles.length === 0) return
    setUploading(true)
    let successCount = 0
    let lastError = ''
    for (const file of selectedFiles) {
      try {
        await uploadPDF(file)
        successCount++
      } catch (err: unknown) {
        lastError = (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail || `'${file.name}' 업로드 실패`
      }
    }
    setSelectedFiles([])
    if (fileInputRef.current) fileInputRef.current.value = ''
    await loadData()
    if (successCount > 0 && !lastError) {
      showToast('success', `${successCount}개 파일 업로드 완료`)
    } else if (successCount > 0 && lastError) {
      showToast('success', `${successCount}개 완료 (일부 실패)`)
    } else {
      showToast('error', 'PDF 업로드 실패')
    }
    setUploading(false)
  }

  const handleTextUpload = async () => {
    if (!textFilename.trim() || !textContent.trim()) return
    setUploading(true)
    try {
      await uploadText(textFilename, textContent)
      showToast('success', '텍스트 업로드 완료')
      setTextFilename('')
      setTextContent('')
      await loadData()
    } catch {
      showToast('error', '텍스트 업로드 실패')
    } finally {
      setUploading(false)
    }
  }

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteDocument(deleteTarget)
      showToast('success', '문서 삭제 완료')
      setDeleteTarget(null)
      await loadData()
    } catch {
      showToast('error', '문서 삭제 실패')
    } finally {
      setDeleting(false)
    }
  }

  const handleClearConfirm = async () => {
    if (clearConfirmInput !== '전체삭제') return
    setDeleting(true)
    try {
      await clearDatabase()
      showToast('success', '전체 문서 초기화 완료')
      setShowClearModal(false)
      setClearConfirmInput('')
      await loadData()
    } catch {
      showToast('error', '전체 문서 초기화 실패')
    } finally {
      setDeleting(false)
    }
  }

  const closeClearModal = () => {
    if (deleting) return
    setShowClearModal(false)
    setClearConfirmInput('')
  }

  return (
    <AdminLayout activePage="documents">
        {/* Page Header */}
        <div className="admin-page-header">
          <div>
            <h1 className="admin-page-title">📄 문서 관리</h1>
            <p className="admin-page-subtitle">지식베이스에 저장된 PDF 문서를 관리합니다.</p>
          </div>
        </div>

        {/* Upload Card */}
        <div className="admin-card">
          <div className="admin-card-header">
            <div className="admin-upload-tabs">
              <button
                className={`admin-upload-tab ${uploadTab === 'pdf' ? 'active' : 'inactive'}`}
                onClick={() => setUploadTab('pdf')}
              >
                📎 PDF 파일 업로드
              </button>
              <button
                className={`admin-upload-tab ${uploadTab === 'text' ? 'active' : 'inactive'}`}
                onClick={() => setUploadTab('text')}
              >
                ✏️ 텍스트 직접 입력
              </button>
            </div>
          </div>

          {uploadTab === 'pdf' ? (
            <div className="admin-upload-content">
              <div
                className={`admin-upload-zone ${isDragOver ? 'drag-over' : ''} ${selectedFiles.length > 0 ? 'has-files' : ''}`}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
                onDragLeave={() => setIsDragOver(false)}
                onDrop={handleDrop}
                role="button"
                aria-label="PDF 파일 선택"
              >
                {selectedFiles.length === 0 ? (
                  <>
                    <div className="admin-upload-icon">📄</div>
                    <div className="admin-upload-text">PDF 파일을 드래그하거나 클릭하여 선택</div>
                    <div className="admin-upload-hint">여러 파일 동시 선택 가능 · PDF 형식만 지원</div>
                  </>
                ) : (
                  <>
                    <div className="admin-file-chips" onClick={(e) => e.stopPropagation()}>
                      {selectedFiles.map(f => (
                        <div key={f.name} className="admin-file-chip">
                          <span className="admin-file-chip-icon">📄</span>
                          <span className="admin-file-chip-name" title={f.name}>{f.name}</span>
                          <button
                            className="admin-file-chip-remove"
                            onClick={() => handleRemoveFile(f.name)}
                            aria-label={`${f.name} 제거`}
                          >×</button>
                        </div>
                      ))}
                    </div>
                    <div
                      className="admin-file-chips-add"
                      onClick={(e) => { e.stopPropagation(); fileInputRef.current?.click(); }}
                    >
                      + 추가
                    </div>
                  </>
                )}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf"
                  multiple
                  style={{ display: 'none' }}
                  onChange={(e) => e.target.files && handleFileSelect(e.target.files)}
                />
              </div>
              <button
                className="admin-btn-primary"
                onClick={handlePdfUpload}
                disabled={selectedFiles.length === 0 || uploading}
                aria-label="PDF 업로드"
              >
                {uploading ? (
                  <><span className="admin-spinner" />처리 중...</>
                ) : selectedFiles.length > 1 ? (
                  `${selectedFiles.length}개 업로드`
                ) : (
                  '업로드'
                )}
              </button>
            </div>
          ) : (
            <div className="admin-upload-content">
              <div className="admin-field">
                <label className="admin-label">파일명</label>
                <input
                  className="admin-input"
                  type="text"
                  placeholder="예: 2026_비자_안내.txt"
                  value={textFilename}
                  onChange={(e) => setTextFilename(e.target.value)}
                />
              </div>
              <div className="admin-field">
                <label className="admin-label">내용</label>
                <textarea
                  className="admin-input admin-textarea"
                  placeholder="문서 내용을 직접 입력하세요..."
                  value={textContent}
                  onChange={(e) => setTextContent(e.target.value)}
                />
              </div>
              <button
                className="admin-btn-primary"
                onClick={handleTextUpload}
                disabled={!textFilename.trim() || !textContent.trim() || uploading}
                aria-label="텍스트 문서 등록"
              >
                {uploading ? (
                  <><span className="admin-spinner" />처리 중...</>
                ) : (
                  '등록'
                )}
              </button>
            </div>
          )}
        </div>

        {/* Document List Card */}
        <div className="admin-card">
          <div className="admin-card-header">
            <div className="admin-card-header-left">
              <span className="admin-section-title">등록된 문서</span>
              <span className="admin-doc-count">{totalDocs}개</span>
            </div>
            <button
              className="admin-btn-danger-outline"
              onClick={() => setShowClearModal(true)}
              disabled={totalDocs === 0}
            >
              전체 삭제
            </button>
          </div>

          {loading ? (
            <div className="admin-loading">불러오는 중...</div>
          ) : documents.length === 0 ? (
            <div className="admin-empty">
              <div className="admin-empty-icon">📭</div>
              <div className="admin-empty-title">등록된 문서가 없습니다.</div>
              <div className="admin-empty-desc">
                PDF 파일을 업로드하여 지식베이스를 구성해 보세요.
              </div>
            </div>
          ) : (
            <table className="admin-doc-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>파일명</th>
                  <th>삭제</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc, idx) => (
                  <tr key={doc}>
                    <td className="admin-table-num">{idx + 1}</td>
                    <td>
                      <div className="admin-table-filename">
                        <span className="admin-file-icon">📄</span>
                        <a
                          href={getDocumentUrl(doc)}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="admin-filename-link"
                        >
                          {doc}
                        </a>
                      </div>
                    </td>
                    <td>
                      <button
                        className="admin-delete-btn"
                        onClick={() => setDeleteTarget(doc)}
                        aria-label={`${doc} 삭제`}
                      >
                        삭제
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

      {/* Individual Delete Confirm Modal */}
      {deleteTarget && (
        <div
          className="admin-modal-overlay"
          onClick={() => !deleting && setDeleteTarget(null)}
          role="dialog"
          aria-modal="true"
          aria-label="문서 삭제 확인"
        >
          <div className="admin-modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="admin-modal-icon">⚠️</div>
            <h2 className="admin-modal-title">문서를 삭제하시겠습니까?</h2>
            <p className="admin-modal-desc">
              <strong>"{deleteTarget}"</strong>이(가) 지식베이스에서 완전히 삭제됩니다.<br />
              이 작업은 되돌릴 수 없습니다.
            </p>
            <div className="admin-modal-actions">
              <button
                className="admin-btn-outline"
                onClick={() => setDeleteTarget(null)}
                disabled={deleting}
              >
                취소
              </button>
              <button
                className="admin-btn-danger"
                onClick={handleDeleteConfirm}
                disabled={deleting}
              >
                {deleting ? '삭제 중...' : '삭제'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Clear All Confirm Modal */}
      {showClearModal && (
        <div
          className="admin-modal-overlay"
          onClick={closeClearModal}
          role="dialog"
          aria-modal="true"
          aria-label="전체 문서 삭제 확인"
        >
          <div className="admin-modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="admin-modal-icon">🚨</div>
            <h2 className="admin-modal-title admin-modal-title--danger">
              전체 문서를 삭제하시겠습니까?
            </h2>
            <div className="admin-clear-warning">
              현재 등록된 <strong>{totalDocs}개</strong> 문서 전체가 삭제됩니다.<br />
              이 작업은 취소할 수 없으며 지식베이스가 완전히 초기화됩니다.
            </div>
            <div className="admin-field" style={{ marginTop: '16px' }}>
              <label className="admin-label">
                아래에 <strong>'전체삭제'</strong>를 입력하여 확인하세요
              </label>
              <input
                className="admin-input"
                type="text"
                placeholder="전체삭제"
                value={clearConfirmInput}
                onChange={(e) => setClearConfirmInput(e.target.value)}
                autoComplete="off"
              />
            </div>
            <div className="admin-modal-actions">
              <button
                className="admin-btn-outline"
                onClick={closeClearModal}
                disabled={deleting}
              >
                취소
              </button>
              <button
                className="admin-btn-danger"
                onClick={handleClearConfirm}
                disabled={deleting || clearConfirmInput !== '전체삭제'}
              >
                {deleting ? '삭제 중...' : '전체 삭제'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className={`admin-toast admin-toast--${toast.type}`} role="alert">
          {toast.type === 'success' ? '✓' : '✗'} {toast.message}
        </div>
      )}
    </AdminLayout>
  )
}
