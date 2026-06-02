import { useState, useEffect, useRef } from 'react'
import {
  getAdminFaqs,
  createFaq,
  updateFaq,
  deleteFaq,
  analyzeLogs,
  bulkCreateFaqs,
  reorderFaqs,
} from '../services/api'
import AdminLayout from '../components/AdminLayout'
import type { FaqItem } from '../types'
import './admin.css'

type Candidate = { question_ko: string; answer_ko: string }

export default function AdminFaqPage() {
  const [faqs, setFaqs] = useState<FaqItem[]>([])
  const [loading, setLoading] = useState(true)

  // 로그 분석
  const [analyzing, setAnalyzing] = useState(false)
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [selectedCandidates, setSelectedCandidates] = useState<Set<number>>(new Set())
  const [saving, setSaving] = useState(false)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  // 수동 추가
  const [showAddForm, setShowAddForm] = useState(false)
  const [addQuestion, setAddQuestion] = useState('')
  const [addAnswer, setAddAnswer] = useState('')
  const [addLoading, setAddLoading] = useState(false)

  // 수정 모달
  const [editTarget, setEditTarget] = useState<FaqItem | null>(null)
  const [editAnswer, setEditAnswer] = useState('')
  const [editLoading, setEditLoading] = useState(false)

  // 삭제 모달
  const [deleteTarget, setDeleteTarget] = useState<FaqItem | null>(null)
  const [deleting, setDeleting] = useState(false)

  // Toast
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const showToast = (type: 'success' | 'error', message: string) => {
    if (toastTimer.current) clearTimeout(toastTimer.current)
    setToast({ type, message })
    toastTimer.current = setTimeout(() => setToast(null), 3000)
  }

  const loadFaqs = async () => {
    try {
      const data = await getAdminFaqs()
      setFaqs(data)
    } catch {
      showToast('error', 'FAQ 불러오기 실패')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadFaqs()
    return () => { if (toastTimer.current) clearTimeout(toastTimer.current) }
  }, [])

  // 로그 분석
  const handleAnalyze = async () => {
    setAnalyzing(true)
    setCandidates([])
    setSelectedCandidates(new Set())
    try {
      const res = await analyzeLogs({
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      })
      setCandidates(res.candidates)
      if (res.candidates.length === 0) showToast('error', '분석할 로그가 없습니다')
      else setSelectedCandidates(new Set(res.candidates.map((_, i) => i)))
    } catch {
      showToast('error', '로그 분석 실패')
    } finally {
      setAnalyzing(false)
    }
  }

  const toggleCandidate = (i: number) => {
    setSelectedCandidates(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }

  const handleSaveCandidates = async () => {
    const selected = candidates.filter((_, i) => selectedCandidates.has(i))
    if (selected.length === 0) return
    setSaving(true)
    try {
      await bulkCreateFaqs(selected)
      showToast('success', `${selected.length}개 FAQ 저장 완료 (번역 중, 잠시 후 새로고침됩니다)`)
      setCandidates([])
      setSelectedCandidates(new Set())
      setTimeout(loadFaqs, 3000)
    } catch {
      showToast('error', 'FAQ 저장 실패')
    } finally {
      setSaving(false)
    }
  }

  // 수동 추가
  const handleAdd = async () => {
    if (!addQuestion.trim() || !addAnswer.trim()) return
    setAddLoading(true)
    try {
      await createFaq(addQuestion.trim(), addAnswer.trim())
      showToast('success', 'FAQ 추가 완료 (번역 중, 잠시 후 새로고침됩니다)')
      setAddQuestion('')
      setAddAnswer('')
      setShowAddForm(false)
      setTimeout(loadFaqs, 3000)
    } catch {
      showToast('error', 'FAQ 추가 실패')
    } finally {
      setAddLoading(false)
    }
  }

  // 활성/비활성 토글
  const handleToggleActive = async (faq: FaqItem) => {
    try {
      await updateFaq(faq.id, { is_active: !faq.is_active })
      await loadFaqs()
    } catch {
      showToast('error', '상태 변경 실패')
    }
  }

  // 수정
  const openEdit = (faq: FaqItem) => {
    setEditTarget(faq)
    setEditAnswer(faq.answer_ko)
  }

  const handleEditSave = async () => {
    if (!editTarget || !editAnswer.trim()) return
    setEditLoading(true)
    try {
      await updateFaq(editTarget.id, { answer_ko: editAnswer.trim() })
      showToast('success', '답변 수정 완료 (재번역 중, 잠시 후 새로고침됩니다)')
      setEditTarget(null)
      setTimeout(loadFaqs, 3000)
    } catch {
      showToast('error', '수정 실패')
    } finally {
      setEditLoading(false)
    }
  }

  // 삭제
  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteFaq(deleteTarget.id)
      showToast('success', 'FAQ 삭제 완료')
      setDeleteTarget(null)
      await loadFaqs()
    } catch {
      showToast('error', '삭제 실패')
    } finally {
      setDeleting(false)
    }
  }

  // 드래그앤드롭
  const dragId = useRef<string | null>(null)
  const [dragOverId, setDragOverId] = useState<string | null>(null)

  const handleDragStart = (id: string) => {
    dragId.current = id
  }

  const handleDragOver = (e: React.DragEvent, id: string) => {
    e.preventDefault()
    if (dragId.current !== id) setDragOverId(id)
  }

  const handleDrop = async (targetId: string) => {
    setDragOverId(null)
    if (!dragId.current || dragId.current === targetId) return
    const s = [...faqs].sort((a, b) => a.display_order - b.display_order)
    const fromIdx = s.findIndex(f => f.id === dragId.current)
    const toIdx = s.findIndex(f => f.id === targetId)
    if (fromIdx === -1 || toIdx === -1) return
    const reordered = [...s]
    const [moved] = reordered.splice(fromIdx, 1)
    reordered.splice(toIdx, 0, moved)
    const updated = reordered.map((f, i) => ({ ...f, display_order: i }))
    setFaqs(updated)
    dragId.current = null
    try {
      await reorderFaqs(updated.map(f => ({ id: f.id, display_order: f.display_order })))
    } catch {
      showToast('error', '순서 저장 실패')
      await loadFaqs()
    }
  }

  const activeCount = faqs.filter(f => f.is_active).length
  const sorted = [...faqs].sort((a, b) => a.display_order - b.display_order)

  return (
    <AdminLayout activePage="faq">
      {/* Header */}
      <div className="admin-page-header">
        <div>
          <h1 className="admin-page-title">❓ FAQ 관리</h1>
          <p className="admin-page-subtitle">자주 묻는 질문을 관리합니다. 총 {faqs.length}개 · 활성 {activeCount}개</p>
        </div>
        <button className="admin-btn-primary" onClick={() => setShowAddForm(v => !v)}>
          + 직접 추가
        </button>
      </div>

      {/* 수동 추가 폼 */}
      {showAddForm && (
        <div className="admin-card">
          <div className="admin-card-header">
            <span className="admin-section-title">FAQ 직접 추가</span>
          </div>
          <div className="admin-upload-content">
            <div className="admin-field">
              <label className="admin-label">질문 (한국어)</label>
              <input
                className="admin-input"
                type="text"
                placeholder="예: 비자 연장 방법은 무엇인가요?"
                value={addQuestion}
                onChange={e => setAddQuestion(e.target.value)}
              />
            </div>
            <div className="admin-field">
              <label className="admin-label">답변 (한국어) — 저장 시 4개 언어로 자동 번역</label>
              <textarea
                className="admin-input admin-textarea"
                placeholder="답변 내용을 입력하세요..."
                value={addAnswer}
                onChange={e => setAddAnswer(e.target.value)}
              />
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                className="admin-btn-primary"
                onClick={handleAdd}
                disabled={!addQuestion.trim() || !addAnswer.trim() || addLoading}
              >
                {addLoading ? <><span className="admin-spinner" />번역 중...</> : '저장'}
              </button>
              <button className="admin-btn-outline" onClick={() => setShowAddForm(false)}>취소</button>
            </div>
          </div>
        </div>
      )}

      {/* 로그 분석 카드 */}
      <div className="admin-card">
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
          <span className="admin-section-title" style={{ whiteSpace: 'nowrap', fontSize: '16px' }}>채팅 로그 분석</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <label className="admin-label" style={{ margin: 0, whiteSpace: 'nowrap', fontSize: '14px' }}>시작일</label>
            <input
              type="date"
              className="admin-input"
              style={{ width: '150px', height: '40px', padding: '0 12px', fontSize: '14px' }}
              value={dateFrom}
              onChange={e => setDateFrom(e.target.value)}
            />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <label className="admin-label" style={{ margin: 0, whiteSpace: 'nowrap', fontSize: '14px' }}>종료일</label>
            <input
              type="date"
              className="admin-input"
              style={{ width: '150px', height: '40px', padding: '0 12px', fontSize: '14px' }}
              value={dateTo}
              onChange={e => setDateTo(e.target.value)}
            />
          </div>
          {(dateFrom || dateTo) && (
            <button
              className="admin-btn-outline"
              onClick={() => { setDateFrom(''); setDateTo('') }}
              style={{ height: '40px', whiteSpace: 'nowrap', fontSize: '13px' }}
            >
              초기화
            </button>
          )}
          <div style={{ flex: 1 }} />
          <button
            className="admin-btn-primary"
            onClick={handleAnalyze}
            disabled={analyzing}
            style={{ height: '40px', whiteSpace: 'nowrap', fontSize: '15px', padding: '0 24px' }}
          >
            {analyzing ? <><span className="admin-spinner" />분석 중...</> : '로그 분석'}
          </button>
        </div>

        {candidates.length > 0 && (
          <div style={{ padding: '0 0 16px' }}>
            <p style={{ fontSize: '13px', color: 'var(--color-text-muted)', marginBottom: '12px' }}>
              추출한 FAQ 후보입니다. 저장할 항목을 선택하세요.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '16px' }}>
              {candidates.map((c, i) => (
                <div
                  key={i}
                  className={`admin-card ${selectedCandidates.has(i) ? '' : 'admin-card--dimmed'}`}
                  style={{ padding: '12px 16px', cursor: 'pointer', border: selectedCandidates.has(i) ? '1.5px solid var(--color-primary)' : undefined }}
                  onClick={() => toggleCandidate(i)}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
                    <input
                      type="checkbox"
                      checked={selectedCandidates.has(i)}
                      onChange={() => toggleCandidate(i)}
                      onClick={e => e.stopPropagation()}
                      style={{ marginTop: '3px', accentColor: 'var(--color-primary)' }}
                    />
                    <div>
                      <div style={{ fontWeight: 600, fontSize: '14px', marginBottom: '4px' }}>Q. {c.question_ko}</div>
                      <div style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>A. {c.answer_ko}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <button
              className="admin-btn-primary"
              onClick={handleSaveCandidates}
              disabled={selectedCandidates.size === 0 || saving}
            >
              {saving ? <><span className="admin-spinner" />저장 중...</> : `선택 항목 저장 (${selectedCandidates.size}개)`}
            </button>
          </div>
        )}
      </div>

      {/* FAQ 목록 */}
      <div className="admin-card">
        <div className="admin-card-header">
          <span className="admin-section-title">등록된 FAQ</span>
          <span className="admin-doc-count">{faqs.length}개</span>
        </div>

        {loading ? (
          <div className="admin-loading">불러오는 중...</div>
        ) : faqs.length === 0 ? (
          <div className="admin-empty">
            <div className="admin-empty-icon">❓</div>
            <div className="admin-empty-title">등록된 FAQ가 없습니다.</div>
            <div className="admin-empty-desc">로그 분석 또는 직접 추가로 FAQ를 등록해 보세요.</div>
          </div>
        ) : (
          <table className="admin-faq-table">
            <colgroup>
              <col className="faq-col-num" />
              <col className="faq-col-q" />
              <col className="faq-col-a" />
              <col className="faq-col-status" />
              <col className="faq-col-drag" />
              <col className="faq-col-edit" />
              <col className="faq-col-del" />
            </colgroup>
            <thead>
              <tr>
                <th>#</th>
                <th>질문 (KO)</th>
                <th>답변 미리보기</th>
                <th style={{ textAlign: 'center' }}>상태</th>
                <th style={{ textAlign: 'center' }}>순서</th>
                <th style={{ textAlign: 'center' }}>수정</th>
                <th style={{ textAlign: 'center' }}>삭제</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((faq, idx) => (
                <tr
                  key={faq.id}
                  draggable
                  onDragStart={() => handleDragStart(faq.id)}
                  onDragOver={e => handleDragOver(e, faq.id)}
                  onDrop={() => handleDrop(faq.id)}
                  onDragEnd={() => setDragOverId(null)}
                  className={[
                    dragId.current === faq.id ? 'admin-faq-row--dragging' : '',
                    dragOverId === faq.id ? 'admin-faq-row--over' : '',
                  ].filter(Boolean).join(' ')}
                >
                  <td style={{ textAlign: 'center', color: 'var(--color-text-muted)', fontSize: '13px' }}>{idx + 1}</td>
                  <td title={faq.question_ko} style={{ fontWeight: 500 }}>{faq.question_ko}</td>
                  <td title={faq.answer_ko} style={{ color: 'var(--color-text-muted)', fontSize: '13px' }}>{faq.answer_ko}</td>
                  <td style={{ textAlign: 'center' }}>
                    <button
                      className={`admin-status-badge admin-status-badge--${faq.is_active ? 'ACTIVE' : 'INACTIVE'}`}
                      onClick={() => handleToggleActive(faq)}
                      title="클릭하여 상태 변경"
                    >
                      {faq.is_active ? '활성' : '비활성'}
                    </button>
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <div className="faq-drag-handle" title="드래그하여 순서 변경">⠿</div>
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <button className="admin-delete-btn" style={{ background: 'var(--color-primary)', color: '#fff' }} onClick={() => openEdit(faq)}>
                      수정
                    </button>
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <button className="admin-delete-btn" onClick={() => setDeleteTarget(faq)}>삭제</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 수정 모달 */}
      {editTarget && (
        <div className="admin-modal-overlay" onClick={() => !editLoading && setEditTarget(null)} role="dialog" aria-modal="true">
          <div className="admin-modal-card" onClick={e => e.stopPropagation()} style={{ maxWidth: '560px', width: '90%' }}>
            <h2 className="admin-modal-title">FAQ 답변 수정</h2>
            <p style={{ fontSize: '13px', color: 'var(--color-text-muted)', marginBottom: '16px' }}>
              한국어 답변 수정 시 나머지 언어도 자동 재번역됩니다.
            </p>

            <div style={{ display: 'grid', gap: '12px', marginBottom: '16px' }}>
              {(['ko', 'en', 'zh', 'es'] as const).map(lang => (
                <div key={lang}>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-text-muted)', marginBottom: '4px', textTransform: 'uppercase' }}>
                    {lang === 'ko' ? '한국어' : lang === 'en' ? 'English' : lang === 'zh' ? '中文' : 'Español'}
                  </div>
                  <div style={{ fontSize: '13px', color: 'var(--color-text-muted)', marginBottom: '4px' }}>
                    Q: {editTarget[`question_${lang}`]}
                  </div>
                  {lang === 'ko' ? (
                    <textarea
                      className="admin-input admin-textarea"
                      value={editAnswer}
                      onChange={e => setEditAnswer(e.target.value)}
                      style={{ minHeight: '80px' }}
                    />
                  ) : (
                    <div style={{ fontSize: '13px', padding: '8px 12px', background: 'var(--color-surface)', borderRadius: '6px', border: '1px solid var(--color-border)', color: 'var(--color-text-muted)' }}>
                      {editTarget[`answer_${lang}`] || '(번역 없음)'}
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="admin-modal-actions">
              <button className="admin-btn-outline" onClick={() => setEditTarget(null)} disabled={editLoading}>취소</button>
              <button className="admin-btn-primary" onClick={handleEditSave} disabled={!editAnswer.trim() || editLoading}>
                {editLoading ? <><span className="admin-spinner" />저장 중...</> : '저장 및 재번역'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 삭제 확인 모달 */}
      {deleteTarget && (
        <div className="admin-modal-overlay" onClick={() => !deleting && setDeleteTarget(null)} role="dialog" aria-modal="true">
          <div className="admin-modal-card" onClick={e => e.stopPropagation()}>
            <div className="admin-modal-icon">⚠️</div>
            <h2 className="admin-modal-title">FAQ를 삭제하시겠습니까?</h2>
            <p className="admin-modal-desc">
              <strong>"{deleteTarget.question_ko}"</strong> 항목이 삭제됩니다.<br />
              이 작업은 되돌릴 수 없습니다.
            </p>
            <div className="admin-modal-actions">
              <button className="admin-btn-outline" onClick={() => setDeleteTarget(null)} disabled={deleting}>취소</button>
              <button className="admin-btn-danger" onClick={handleDeleteConfirm} disabled={deleting}>
                {deleting ? '삭제 중...' : '삭제'}
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
