import { Routes, Route, Link } from 'react-router-dom'
import { ChatInterface } from './components/ChatInterface'
import { QuickQuestions } from './components/QuickQuestions'
import { useChat } from './hooks/useChat'
import LoginPage from './pages/LoginPage'
import SignupPage from './pages/SignupPage'
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
  return (
    <nav className="top-nav">
      <Link to="/login" className="top-nav-btn top-nav-btn--outline">로그인</Link>
      <Link to="/signup" className="top-nav-btn top-nav-btn--filled">회원가입</Link>
    </nav>
  )
}

function ChatApp() {
  const { messages, isLoading, error, language, setLanguage, send, clearHistory } = useChat()

  return (
    <div className="app">
      <BackgroundGlow />
      <TopNav />

      <div className="app-shell">
        <aside className="app-sidebar">
          {/* Logo Card */}
          <div className="logo-card">
            <div className="logo-row">
              <img src="/dongA_symbol.jpg" className="logo-icon" alt="logo" />
              <div>
                <div className="logo-badge">AI CAMPUS ASSISTANT</div>
                <h1 className="logo-title">유학생 생활·행정<br />안내 챗봇</h1>
              </div>
            </div>
            <p className="logo-desc">학교 문서를 바탕으로 필요한 정보를 빠르게 찾을 수 있는 스마트 챗봇</p>
            <div className="status-badge">
              <div className="status-dot" />
              <span>상담 가능</span>
            </div>
          </div>

          <QuickQuestions onSend={send} />
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
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/" element={<ChatApp />} />
    </Routes>
  )
}
