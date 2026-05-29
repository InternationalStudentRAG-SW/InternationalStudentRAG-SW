import { Routes, Route, Link, Navigate, useNavigate, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { supabase } from './lib/supabaseClient'
import { ChatInterface } from './components/ChatInterface'
import { QuickQuestions } from './components/QuickQuestions'
import { useChat } from './hooks/useChat'
import { getLabels } from './i18n'
import LoginPage from './pages/LoginPage'
import SignupPage from './pages/SignupPage'
import AdminSignupPage from './pages/AdminSignupPage'
import AdditionalInfoPage from './pages/AdditionalInfoPage'
import AdminDocumentPage from './pages/AdminDocumentPage'
import AdminChatLogPage from './pages/AdminChatLogPage'
import AdminMemberPage from './pages/AdminMemberPage'
import AdminFaqPage from './pages/AdminFaqPage'
import './App.css'

function BackgroundGlow() {
  return (
    <>
      <div className="glow-one" />
      <div className="glow-two" />
    </>
  )
}

function TopNav() {
  const navigate = useNavigate();
  const location = useLocation();

  const [isLoggedIn, setIsLoggedIn] = useState(!!localStorage.getItem('token'));
  const [role, setRole] = useState(localStorage.getItem('role') ?? '');

  useEffect(() => {
    setIsLoggedIn(!!localStorage.getItem('token'));
    setRole(localStorage.getItem('role') ?? '');
  }, [location]);

  const handleLogout = async () => {
    await supabase.auth.signOut()
    localStorage.removeItem('token');
    localStorage.removeItem('userEmail');
    localStorage.removeItem('role');
    setIsLoggedIn(false);
    setRole('');
    navigate('/login');
  };

  return (
    <nav className="top-nav">
      {isLoggedIn && role === 'admin' && (
        <Link to="/admin" className="top-nav-btn top-nav-btn--filled">관리자 페이지</Link>
      )}
      {isLoggedIn ? (
        <button onClick={handleLogout} className="top-nav-btn top-nav-btn--outline">로그아웃</button>
      ) : (
        <>
          <Link to="/login" className="top-nav-btn top-nav-btn--outline">로그인</Link>
          <Link to="/signup" className="top-nav-btn top-nav-btn--filled">회원가입</Link>
        </>
      )}
    </nav>
  )
}

function AdminRoute() {
  const token = localStorage.getItem('token');
  const role = localStorage.getItem('role');
  if (!token || role !== 'admin') return <Navigate to="/" replace />;
  return <AdminDocumentPage />;
}

function AdminChatLogRoute() {
  const token = localStorage.getItem('token');
  const role = localStorage.getItem('role');
  if (!token || role !== 'admin') return <Navigate to="/" replace />;
  return <AdminChatLogPage />;
}

function AdminMemberRoute() {
  const token = localStorage.getItem('token');
  const role = localStorage.getItem('role');
  if (!token || role !== 'admin') return <Navigate to="/" replace />;
  return <AdminMemberPage />;
}

function AdminFaqRoute() {
  const token = localStorage.getItem('token');
  const role = localStorage.getItem('role');
  if (!token || role !== 'admin') return <Navigate to="/" replace />;
  return <AdminFaqPage />;
}

function ChatApp() {
  const { messages, isLoading, error, language, setLanguage, send, sendFaq, clearHistory } = useChat()
  const navigate = useNavigate();
  const labels = getLabels(language);

  // 보호된 라우팅: 토큰이 없으면 로그인 페이지로 강제 이동
  useEffect(() => {
    // 인증 구현 완료 후 아래 주석을 해제하세요
    // if (!localStorage.getItem('token')) navigate('/login')
  }, [navigate]);

  return (
    <div className="app">
      <BackgroundGlow />
      <TopNav />

      <div className="app-shell">
        <aside className="app-sidebar">
          <div className="logo-card">
            <div className="logo-row">
              <img src="/dongA_symbol.jpg" className="logo-icon" alt="logo" />
              <div>
                <div className="logo-badge">AI CAMPUS ASSISTANT</div>
                <h1 className="logo-title">{labels.sidebarTitle.split('\n').map((line, i) => (
                  <span key={i}>{line}{i === 0 && <br />}</span>
                ))}</h1>
              </div>
            </div>
            <p className="logo-desc">{labels.sidebarDesc}</p>
            <div className="status-badge">
              <div className="status-dot" />
              <span>{labels.sidebarStatus}</span>
            </div>
          </div>
          <QuickQuestions language={language} onFaqClick={sendFaq} />
        </aside>

        <main className="app-main">
          <ChatInterface
            messages={messages}
            isLoading={isLoading}
            error={error}
            language={language}
            onSend={send}
            onClear={clearHistory}
            onLanguageChange={setLanguage}
          />
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ChatApp />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/admin-signup" element={<AdminSignupPage />} />
      <Route path="/admin" element={<AdminRoute />} />
      <Route path="/admin/chat-logs" element={<AdminChatLogRoute />} />
      <Route path="/admin/members" element={<AdminMemberRoute />} />
      <Route path="/admin/faq" element={<AdminFaqRoute />} />
      <Route path="/additional-info" element={<AdditionalInfoPage />} />
    </Routes>
  )
}