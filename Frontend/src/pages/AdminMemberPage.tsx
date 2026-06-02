import { useState, useEffect, useRef, useCallback } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell,
} from 'recharts'
import {
  getUsers, getUserStats, updateUserRole, updateUserStatus, deleteUser,
} from '../services/api'
import type { Member, MemberStats } from '../services/api'
import AdminLayout from '../components/AdminLayout'
import './admin.css'

const LIMIT = 20

const NAT_COLORS = [
  '#7c3aed', '#3b82f6', '#22c55e', '#ef4444', '#f59e0b',
  '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#94a3b8',
]

function formatDate(iso: string) {
  const d = new Date(iso)
  return d.toLocaleDateString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

export default function AdminMemberPage() {
  const [members, setMembers] = useState<Member[]>([])
  const [stats, setStats] = useState<MemberStats | null>(null)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)

  const [roleFilter, setRoleFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [deleteTarget, setDeleteTarget] = useState<Member | null>(null)
  const [deleting, setDeleting] = useState(false)

  const [roleConfirm, setRoleConfirm] = useState<{ member: Member; newRole: string } | null>(null)
  const [statusConfirm, setStatusConfirm] = useState<{ member: Member; newStatus: string } | null>(null)
  const [confirming, setConfirming] = useState(false)

  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const showToast = (type: 'success' | 'error', message: string) => {
    if (toastTimer.current) clearTimeout(toastTimer.current)
    setToast({ type, message })
    toastTimer.current = setTimeout(() => setToast(null), 3000)
  }

  const loadMembers = useCallback(async (p: number) => {
    setLoading(true)
    try {
      const res = await getUsers({
        page: p, limit: LIMIT,
        role: roleFilter || undefined,
        status: statusFilter || undefined,
        search: debouncedSearch || undefined,
      })
      setMembers(res.users)
      setTotal(res.total)
    } catch {
      showToast('error', '회원 목록을 불러오는 데 실패했습니다.')
    } finally {
      setLoading(false)
    }
  }, [roleFilter, statusFilter, debouncedSearch])

  const loadStats = async () => {
    try {
      const s = await getUserStats()
      setStats(s)
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
    loadMembers(1)
  }, [loadMembers])

  const handleSearchChange = (value: string) => {
    setSearch(value)
    if (searchTimer.current) clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => setDebouncedSearch(value), 300)
  }

  const handleRoleToggle = (member: Member) => {
    const newRole = member.role === 'admin' ? 'student' : 'admin'
    setRoleConfirm({ member, newRole })
  }

  const handleRoleConfirm = async () => {
    if (!roleConfirm) return
    setConfirming(true)
    try {
      await updateUserRole(roleConfirm.member.id, roleConfirm.newRole)
      setMembers(prev => prev.map(m => m.id === roleConfirm.member.id ? { ...m, role: roleConfirm.newRole } : m))
      showToast('success', `${roleConfirm.member.email} 역할을 ${roleConfirm.newRole === 'admin' ? '관리자' : '학생'}으로 변경했습니다.`)
      setRoleConfirm(null)
    } catch {
      showToast('error', '역할 변경에 실패했습니다.')
    } finally {
      setConfirming(false)
    }
  }

  const handleStatusToggle = (member: Member) => {
    const newStatus = member.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE'
    setStatusConfirm({ member, newStatus })
  }

  const handleStatusConfirm = async () => {
    if (!statusConfirm) return
    setConfirming(true)
    try {
      await updateUserStatus(statusConfirm.member.id, statusConfirm.newStatus)
      setMembers(prev => prev.map(m => m.id === statusConfirm.member.id ? { ...m, status: statusConfirm.newStatus } : m))
      showToast('success', `${statusConfirm.member.email} 상태를 ${statusConfirm.newStatus === 'ACTIVE' ? '활성' : '비활성'}으로 변경했습니다.`)
      setStatusConfirm(null)
    } catch {
      showToast('error', '상태 변경에 실패했습니다.')
    } finally {
      setConfirming(false)
    }
  }

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteUser(deleteTarget.id)
      showToast('success', '회원 삭제 완료')
      setDeleteTarget(null)
      await loadMembers(page)
      await loadStats()
    } catch {
      showToast('error', '회원 삭제 실패')
    } finally {
      setDeleting(false)
    }
  }

  const totalPages = Math.ceil(total / LIMIT)

  const natData = stats
    ? Object.entries(stats.by_nationality)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 8)
        .map(([name, value]) => ({ name, value }))
    : []
  const natTotal = natData.reduce((sum, d) => sum + d.value, 0)

  return (
    <AdminLayout activePage="members">
      <div className="admin-page-header">
        <div>
          <h1 className="admin-page-title">👥 회원 관리</h1>
          <p className="admin-page-subtitle">가입된 유학생 및 관리자 계정을 관리합니다.</p>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="admin-stats-row">
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'var(--color-gradient)' }}>👥</div>
          <div>
            <div className="admin-stat-value">{stats?.total ?? '—'}</div>
            <div className="admin-stat-label">총 회원 수</div>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon" style={{ background: 'linear-gradient(135deg, #22c55e, #16a34a)' }}>🆕</div>
          <div>
            <div className="admin-stat-value" style={{ color: '#16a34a' }}>{stats?.today ?? '—'}</div>
            <div className="admin-stat-label">오늘 신규 가입</div>
          </div>
        </div>
      </div>

      {/* Charts Row */}
      <div className="admin-charts-row">
        {/* 7일 가입 추이 */}
        <div className="admin-card admin-chart-card admin-chart-bar">
          <div className="admin-chart-title">최근 7일 가입 추이</div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={stats?.daily ?? []} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#94a3b8' }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#94a3b8' }} />
              <Tooltip
                contentStyle={{ background: '#1e1b4b', border: '1px solid rgba(124,58,237,0.3)', borderRadius: 10, fontSize: 12 }}
                cursor={{ fill: 'rgba(124,58,237,0.08)' }}
              />
              <Bar dataKey="count" name="가입 수" fill="#7c3aed" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* 국적별 분포 도넛 */}
        <div className="admin-card admin-chart-card admin-chart-donut">
          <div className="admin-chart-title">국적별 분포</div>
          {natData.length > 0 ? (
            <div className="admin-donut-row">
              <ResponsiveContainer width={160} height={160}>
                <PieChart>
                  <Pie data={natData} innerRadius={48} outerRadius={72} dataKey="value" paddingAngle={2}>
                    {natData.map((_, i) => (
                      <Cell key={i} fill={NAT_COLORS[i % NAT_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ background: '#1e1b4b', border: '1px solid rgba(124,58,237,0.3)', borderRadius: 10, fontSize: 12 }}
                    formatter={(v, n) => [`${v}명`, String(n)]}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="admin-donut-legend">
                {natData.map((d, i) => (
                  <div key={d.name} className="admin-donut-legend-item">
                    <span className="admin-donut-dot" style={{ background: NAT_COLORS[i % NAT_COLORS.length] }} />
                    <span>{d.name}</span>
                    <span className="admin-donut-pct">
                      {Math.round((d.value / natTotal) * 100)}%
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

      {/* Member Table */}
      <div className="admin-card">
        {/* Filters */}
        <div className="admin-log-filters">
          <select
            className="admin-log-filter-select"
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
          >
            <option value="">전체 역할</option>
            <option value="student">학생</option>
            <option value="admin">관리자</option>
          </select>
          <select
            className="admin-log-filter-select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">전체 상태</option>
            <option value="ACTIVE">활성</option>
            <option value="INACTIVE">비활성</option>
          </select>
          <input
            className="admin-log-filter-search"
            type="text"
            placeholder="이메일 검색..."
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
          />
        </div>

        {/* Table */}
        {loading ? (
          <div className="admin-log-empty">불러오는 중...</div>
        ) : members.length === 0 ? (
          <div className="admin-log-empty">조건에 맞는 회원이 없습니다.</div>
        ) : (
          <table className="admin-member-table">
            <thead>
              <tr>
                <th>이메일</th>
                <th>국적</th>
                <th>전공</th>
                <th>역할</th>
                <th>상태</th>
                <th>가입일</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.id}>
                  <td className="admin-member-email">{m.email}</td>
                  <td>{m.nationality || '—'}</td>
                  <td className="admin-member-major">{m.major || '—'}</td>
                  <td>
                    {m.role === 'admin' ? (
                      <span
                        className="admin-role-badge admin-role-badge--admin admin-badge--locked"
                        title="Supabase에서 직접 관리"
                      >
                        관리자
                      </span>
                    ) : (
                      <button
                        className="admin-role-badge admin-role-badge--student"
                        onClick={() => handleRoleToggle(m)}
                        title="클릭하여 역할 변경"
                      >
                        학생
                      </button>
                    )}
                  </td>
                  <td>
                    {(() => {
                      const s = m.status === 'ACTIVE' ? 'ACTIVE' : 'INACTIVE'
                      return m.role === 'admin' ? (
                        <span
                          className={`admin-status-badge admin-status-badge--${s} admin-badge--locked`}
                          title="Supabase에서 직접 관리"
                        >
                          {s === 'ACTIVE' ? '활성' : '비활성'}
                        </span>
                      ) : (
                        <button
                          className={`admin-status-badge admin-status-badge--${s}`}
                          onClick={() => handleStatusToggle(m)}
                          title="클릭하여 상태 변경"
                        >
                          {s === 'ACTIVE' ? '활성' : '비활성'}
                        </button>
                      )
                    })()}
                  </td>
                  <td className="admin-log-time">{formatDate(m.created_at)}</td>
                  <td>
                    <button
                      className="admin-delete-btn"
                      onClick={() => m.role !== 'admin' && setDeleteTarget(m)}
                      disabled={m.role === 'admin'}
                      aria-label={`${m.email} 삭제`}
                      title={m.role === 'admin' ? 'Supabase에서 직접 관리' : undefined}
                    >
                      삭제
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="admin-pagination">
            <button
              className="admin-pagination-btn"
              onClick={() => { setPage(p => p - 1); loadMembers(page - 1) }}
              disabled={page <= 1}
            >
              이전
            </button>
            <span className="admin-pagination-info">{page} / {totalPages}</span>
            <button
              className="admin-pagination-btn"
              onClick={() => { setPage(p => p + 1); loadMembers(page + 1) }}
              disabled={page >= totalPages}
            >
              다음
            </button>
          </div>
        )}
      </div>

      {/* Role Change Confirm Modal */}
      {roleConfirm && (
        <div
          className="admin-modal-overlay"
          onClick={() => !confirming && setRoleConfirm(null)}
          role="dialog"
          aria-modal="true"
          aria-label="역할 변경 확인"
        >
          <div className="admin-modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="admin-modal-icon">🔄</div>
            <h2 className="admin-modal-title">역할을 변경하시겠습니까?</h2>
            <p className="admin-modal-desc">
              <strong>"{roleConfirm.member.email}"</strong>의 역할을<br />
              <strong>{roleConfirm.newRole === 'admin' ? '관리자' : '학생'}</strong>으로 변경합니다.
            </p>
            <div className="admin-modal-actions">
              <button
                className="admin-btn-outline"
                onClick={() => setRoleConfirm(null)}
                disabled={confirming}
              >
                취소
              </button>
              <button
                className="admin-btn-primary"
                onClick={handleRoleConfirm}
                disabled={confirming}
              >
                {confirming ? '변경 중...' : '변경'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Status Change Confirm Modal */}
      {statusConfirm && (
        <div
          className="admin-modal-overlay"
          onClick={() => !confirming && setStatusConfirm(null)}
          role="dialog"
          aria-modal="true"
          aria-label="상태 변경 확인"
        >
          <div className="admin-modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="admin-modal-icon">🔄</div>
            <h2 className="admin-modal-title">상태를 변경하시겠습니까?</h2>
            <p className="admin-modal-desc">
              <strong>"{statusConfirm.member.email}"</strong>의 상태를<br />
              <strong>{statusConfirm.newStatus === 'ACTIVE' ? '활성' : '비활성'}</strong>으로 변경합니다.
            </p>
            <div className="admin-modal-actions">
              <button
                className="admin-btn-outline"
                onClick={() => setStatusConfirm(null)}
                disabled={confirming}
              >
                취소
              </button>
              <button
                className="admin-btn-primary"
                onClick={handleStatusConfirm}
                disabled={confirming}
              >
                {confirming ? '변경 중...' : '변경'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirm Modal */}
      {deleteTarget && (
        <div
          className="admin-modal-overlay"
          onClick={() => !deleting && setDeleteTarget(null)}
          role="dialog"
          aria-modal="true"
          aria-label="회원 삭제 확인"
        >
          <div className="admin-modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="admin-modal-icon">⚠️</div>
            <h2 className="admin-modal-title">회원을 삭제하시겠습니까?</h2>
            <p className="admin-modal-desc">
              <strong>"{deleteTarget.email}"</strong> 계정이 완전히 삭제됩니다.<br />
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

      {/* Toast */}
      {toast && (
        <div className={`admin-toast admin-toast--${toast.type}`} role="alert">
          {toast.type === 'success' ? '✓' : '✗'} {toast.message}
        </div>
      )}
    </AdminLayout>
  )
}
