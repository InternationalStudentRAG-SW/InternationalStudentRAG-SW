import { useState, useEffect, useRef, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell,
} from 'recharts'
import { getChatLogs, getChatStats, getChatDaily } from '../services/api'
import type { ChatLog, ChatStats } from '../services/api'
import AdminLayout from '../components/AdminLayout'
import './admin.css'

const LIMIT = 20

const LANG_LABELS: Record<string, string> = {
  ko: 'KO', en: 'EN', zh: 'ZH', es: 'ES', auto: 'AUTO',
}

const LANG_COLORS: Record<string, string> = {
  ko: '#3b82f6', en: '#22c55e', zh: '#ef4444', es: '#f59e0b', auto: '#94a3b8',
}

function formatDate(iso: string) {
  const d = new Date(iso)
  return d.toLocaleDateString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' })
    + ' ' + d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
}

export default function AdminChatLogPage() {
  const [logs, setLogs] = useState<ChatLog[]>([])
  const [stats, setStats] = useState<ChatStats | null>(null)
  const [daily, setDaily] = useState<Array<{ date: string; count: number }>>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)

  // Filters
  const [language, setLanguage] = useState('')
  const [search, setSearch] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  // Modal
  const [selected, setSelected] = useState<ChatLog | null>(null)

  // Toast
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Debounce search
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [debouncedSearch, setDebouncedSearch] = useState('')

  const showToast = (type: 'success' | 'error', message: string) => {
    if (toastTimer.current) clearTimeout(toastTimer.current)
    setToast({ type, message })
    toastTimer.current = setTimeout(() => setToast(null), 3000)
  }

  const loadLogs = useCallback(async (p: number) => {
    setLoading(true)
    try {
      const res = await getChatLogs({
        page: p, limit: LIMIT,
        language: language || undefined,
        search: debouncedSearch || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      })
      setLogs(res.logs)
      setTotal(res.total)
    } catch {
      showToast('error', '로그를 불러오는 데 실패했습니다.')
    } finally {
      setLoading(false)
    }
  }, [language, debouncedSearch, dateFrom, dateTo])

  const loadStats = async () => {
    try {
      const [s, d] = await Promise.all([getChatStats(), getChatDaily()])
      setStats(s)
      setDaily(d.daily)
    } catch {
      // 통계 실패는 조용히 무시
    }
  }

  useEffect(() => {
    loadStats()
    return () => {
      if (toastTimer.current) clearTimeout(toastTimer.current)
    }
  }, [])

  useEffect(() => {
    setPage(1)
    loadLogs(1)
  }, [loadLogs])

  const handleSearchChange = (value: string) => {
    setSearch(value)
    if (searchTimer.current) clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => setDebouncedSearch(value), 300)
  }

  const totalPages = Math.ceil(total / LIMIT)

  const langData = stats
    ? Object.entries(stats.by_language).map(([name, value]) => ({ name, value }))
    : []
  const langTotal = langData.reduce((sum, d) => sum + d.value, 0)

  return (
    <AdminLayout activePage="chat-logs">
      {/* Page Header */}
      <div className="admin-page-header">
        <div>
          <h1 className="admin-page-title">💬 질문 로그</h1>
          <p className="admin-page-subtitle">사용자 질의응답 기록을 확인합니다.</p>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="admin-stats-row">
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'var(--color-gradient)' }}>💬</div>
          <div>
            <div className="admin-stat-value">{stats?.total ?? '—'}</div>
            <div className="admin-stat-label">총 질문 수</div>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'linear-gradient(135deg, #22c55e, #16a34a)' }}>📅</div>
          <div>
            <div className="admin-stat-value" style={{ color: '#16a34a' }}>{stats?.today ?? '—'}</div>
            <div className="admin-stat-label">오늘 질문 수</div>
          </div>
        </div>
      </div>

      {/* Charts Row */}
      <div className="admin-charts-row">
        {/* 7일 추이 바 차트 */}
        <div className="admin-card admin-chart-card admin-chart-bar">
          <div className="admin-chart-title">최근 7일 질문 추이</div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={daily} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#94a3b8' }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#94a3b8' }} />
              <Tooltip
                contentStyle={{ background: '#1e1b4b', border: '1px solid rgba(124,58,237,0.3)', borderRadius: 10, fontSize: 12 }}
                cursor={{ fill: 'rgba(124,58,237,0.08)' }}
              />
              <Bar dataKey="count" name="질문 수" fill="#7c3aed" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* 언어별 분포 도넛 차트 */}
        <div className="admin-card admin-chart-card admin-chart-donut">
          <div className="admin-chart-title">언어별 분포</div>
          {langData.length > 0 ? (
            <div className="admin-donut-row">
              <ResponsiveContainer width={160} height={160}>
                <PieChart>
                  <Pie data={langData} innerRadius={48} outerRadius={72} dataKey="value" paddingAngle={2}>
                    {langData.map((entry, i) => (
                      <Cell key={i} fill={LANG_COLORS[entry.name] ?? '#94a3b8'} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ background: '#1e1b4b', border: '1px solid rgba(124,58,237,0.3)', borderRadius: 10, fontSize: 12 }}
                    formatter={(v, n) => [`${v}회`, String(n).toUpperCase()]}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="admin-donut-legend">
                {langData.sort((a, b) => b.value - a.value).map((d) => (
                  <div key={d.name} className="admin-donut-legend-item">
                    <span className="admin-donut-dot" style={{ background: LANG_COLORS[d.name] ?? '#94a3b8' }} />
                    <span>{d.name.toUpperCase()}</span>
                    <span className="admin-donut-pct">
                      {Math.round((d.value / langTotal) * 100)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="admin-log-empty" style={{ padding: '40px 0' }}>데이터 없음</div>
          )}
        </div>
      </div>

      {/* Log Table Card */}
      <div className="admin-card">
        {/* Filters */}
        <div className="admin-log-filters">
          <select
            className="admin-log-filter-select"
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
          >
            <option value="">전체 언어</option>
            <option value="ko">KO</option>
            <option value="en">EN</option>
            <option value="zh">ZH</option>
            <option value="es">ES</option>
            <option value="auto">AUTO</option>
          </select>
          <input
            className="admin-log-filter-date"
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            title="시작일"
          />
          <span className="admin-log-date-sep">~</span>
          <input
            className="admin-log-filter-date"
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            title="종료일"
          />
          <input
            className="admin-log-filter-search"
            type="text"
            placeholder="질문 키워드 검색..."
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
          />
        </div>

        {/* Table */}
        {loading ? (
          <div className="admin-log-empty">불러오는 중...</div>
        ) : logs.length === 0 ? (
          <div className="admin-log-empty">조건에 맞는 로그가 없습니다.</div>
        ) : (
          <table className="admin-log-table">
            <thead>
              <tr>
                <th>시간</th>
                <th>언어</th>
                <th>질문</th>
                <th>소스 수</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => {
                const sourceCount = Array.isArray(log.sources) ? log.sources.length : 0
                return (
                  <tr
                    key={log.id}
                    className={sourceCount === 0 ? 'admin-log-row--no-source' : ''}
                  >
                    <td className="admin-log-time">{formatDate(log.created_at)}</td>
                    <td>
                      <span className={`admin-lang-badge admin-lang-badge--${log.language || 'auto'}`}>
                        {LANG_LABELS[log.language] ?? log.language}
                      </span>
                    </td>
                    <td className="admin-log-query">
                      {log.query.length > 60 ? log.query.slice(0, 60) + '…' : log.query}
                    </td>
                    <td className="admin-log-source-count">{sourceCount}</td>
                    <td>
                      <button
                        className="admin-log-detail-btn"
                        onClick={() => setSelected(log)}
                      >
                        상세
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="admin-pagination">
            <button
              className="admin-pagination-btn"
              onClick={() => { setPage(p => p - 1); loadLogs(page - 1) }}
              disabled={page <= 1}
            >
              이전
            </button>
            <span className="admin-pagination-info">{page} / {totalPages}</span>
            <button
              className="admin-pagination-btn"
              onClick={() => { setPage(p => p + 1); loadLogs(page + 1) }}
              disabled={page >= totalPages}
            >
              다음
            </button>
          </div>
        )}
      </div>

      {/* Detail Modal */}
      {selected && (
        <div
          className="admin-modal-overlay"
          onClick={() => setSelected(null)}
          role="dialog"
          aria-modal="true"
          aria-label="질문 로그 상세"
        >
          <div className="admin-log-detail-modal" onClick={(e) => e.stopPropagation()}>
            <div className="admin-log-detail-header">
              <div className="admin-log-detail-meta">
                <span className={`admin-lang-badge admin-lang-badge--${selected.language || 'auto'}`}>
                  {LANG_LABELS[selected.language] ?? selected.language}
                </span>
                <span className="admin-log-detail-time">{formatDate(selected.created_at)}</span>
              </div>
              <button className="admin-log-detail-close" onClick={() => setSelected(null)}>×</button>
            </div>

            <div className="admin-log-detail-section">
              <div className="admin-log-detail-label">질문</div>
              <div className="admin-log-detail-query">{selected.query}</div>
            </div>

            <div className="admin-log-detail-section">
              <div className="admin-log-detail-label">답변</div>
              <div className="admin-log-detail-answer">
                <ReactMarkdown>{selected.answer}</ReactMarkdown>
              </div>
            </div>

            {Array.isArray(selected.sources) && selected.sources.length > 0 && (
              <div className="admin-log-detail-section">
                <div className="admin-log-detail-label">출처 ({selected.sources.length}개)</div>
                <div className="admin-log-detail-sources">
                  {selected.sources.map((src, i) => (
                    <div key={i} className="admin-log-source-item">
                      <span className="admin-log-source-name">{src.source}</span>
                      <span className="admin-log-source-meta">
                        유사도 {(src.similarity_score * 100).toFixed(1)}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {(!Array.isArray(selected.sources) || selected.sources.length === 0) && (
              <div className="admin-log-detail-section">
                <div className="admin-log-no-source">관련 문서를 찾지 못한 질문입니다. 문서 보완을 검토하세요.</div>
              </div>
            )}
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
