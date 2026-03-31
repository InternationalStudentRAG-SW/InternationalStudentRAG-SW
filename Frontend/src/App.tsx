import { Routes, Route, Link, useNavigate, useLocation } from 'react-router-dom' // [수정] 현재 경로 확인을 위해 useLocation 추가
import { useEffect, useState } from 'react'
import { ChatInterface } from './components/ChatInterface'
import { QuickQuestions } from './components/QuickQuestions'
import { useChat } from './hooks/useChat'
import LoginPage from './pages/LoginPage'
import SignupPage from './pages/SignupPage'
import AdditionalInfoPage from './pages/AdditionalInfoPage' // [추가] 새 페이지 임포트
import './App.css'

function BackgroundGlow() {
  return (
    <>
      <div className="glow-one" />
      <div className="glow-two" />
    </>
  )
}

// TopNav: 로그인 상태에 따라 버튼을 다르게 보여줌
function TopNav() {
  const navigate = useNavigate();
  const location = useLocation(); // [추가] 경로 변경 감지용
  
  // [수정] 단순 변수가 아닌 상태(State)로 관리해야 로그아웃 시 즉시 UI가 바뀜
  const [isLoggedIn, setIsLoggedIn] = useState(!!localStorage.getItem('token'));

  useEffect(() => {
    setIsLoggedIn(!!localStorage.getItem('token'));
  }, [location]); // 페이지가 바뀔 때마다 로그인 상태 다시 확인

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('userEmail'); // [추가] 이메일 정보도 함께 삭제
    alert("로그아웃 되었습니다.");
    setIsLoggedIn(false);
    navigate('/login');
  };

  return (
    <nav className="top-nav">
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

function ChatApp() {
  const { messages, isLoading, error, language, setLanguage, send, clearHistory } = useChat()
  const navigate = useNavigate();

  // 보호된 라우팅: 토큰이 없으면 로그인 페이지로 강제 이동
  useEffect(() => {
    const token = localStorage.getItem('token');
    // if (!token) {
    //   navigate('/login'); 
    // }
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
      {/* [수정] 각 페이지 경로 설정 */}
      <Route path="/" element={<ChatApp />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      {/* [추가] 구글 로그인 후 추가 정보 입력을 위한 경로 추가 */}
      <Route path="/additional-info" element={<AdditionalInfoPage />} />
    </Routes>
  )
}