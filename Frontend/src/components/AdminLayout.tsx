import { useNavigate, Link } from 'react-router-dom'
import { supabase } from '../lib/supabaseClient'

type ActivePage = 'documents' | 'chat-logs' | 'members' | 'faq'

interface Props {
  activePage: ActivePage
  children: React.ReactNode
}

export default function AdminLayout({ activePage, children }: Props) {
  const navigate = useNavigate()
  const userEmail = localStorage.getItem('userEmail') || ''

  const handleLogout = async () => {
    await supabase.auth.signOut()
    localStorage.removeItem('token')
    localStorage.removeItem('role')
    localStorage.removeItem('userEmail')
    navigate('/')
  }

  return (
    <div className="admin-page">
      <div className="glow-one" />
      <div className="glow-two" />

      <aside className="admin-sidebar">
        <div className="admin-sidebar-top">
          <div className="admin-logo-row">
            <Link to="/" title="메인으로 돌아가기" className="admin-logo-img-link">
              <img src="/dongA_symbol.jpg" alt="동아대" className="admin-logo-img" />
            </Link>
            <div>
              <div className="admin-logo-badge">AI Campus Assistant</div>
              <div className="admin-logo-title">관리자 패널</div>
            </div>
          </div>

          <nav className="admin-nav">
            <Link
              to="/admin"
              className={`admin-nav-item ${activePage === 'documents' ? 'active' : ''}`}
            >
              <span>📄</span>
              <span>문서 관리</span>
            </Link>
            <Link
              to="/admin/chat-logs"
              className={`admin-nav-item ${activePage === 'chat-logs' ? 'active' : ''}`}
            >
              <span>💬</span>
              <span>질문 로그</span>
            </Link>
            <Link
              to="/admin/members"
              className={`admin-nav-item ${activePage === 'members' ? 'active' : ''}`}
            >
              <span>👥</span>
              <span>회원 관리</span>
            </Link>
            <Link
              to="/admin/faq"
              className={`admin-nav-item ${activePage === 'faq' ? 'active' : ''}`}
            >
              <span>❓</span>
              <span>FAQ 관리</span>
            </Link>
          </nav>
        </div>

        <div className="admin-sidebar-footer">
          <div className="admin-sidebar-divider" />
          {userEmail && <div className="admin-user-email">{userEmail}</div>}
          <button className="admin-logout-btn" onClick={handleLogout}>
            로그아웃
          </button>
        </div>
      </aside>

      <main className="admin-content">
        {children}
      </main>
    </div>
  )
}
