import { Link } from 'react-router-dom'
import './auth.css'

function BackgroundGlow() {
  return (
    <>
      <div className="glow-one" />
      <div className="glow-two" />
    </>
  )
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M17.64 9.205c0-.639-.057-1.252-.164-1.841H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615Z" fill="#4285F4"/>
      <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18Z" fill="#34A853"/>
      <path d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332Z" fill="#FBBC05"/>
      <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58Z" fill="#EA4335"/>
    </svg>
  )
}

export default function LoginPage() {
  return (
    <div className="auth-page">
      <BackgroundGlow />

      <div className="auth-card">
        <div className="auth-logo">
          <img src="/dongA_symbol.jpg" className="auth-logo-icon" alt="logo" />
          <div>
            <div className="auth-logo-badge">AI Campus Assistant</div>
            <div className="auth-logo-title">유학생 생활·행정 안내 챗봇</div>
          </div>
        </div>

        <h1 className="auth-heading">로그인</h1>
        <p className="auth-subheading">서비스를 이용하려면 로그인하세요.</p>

        <form className="auth-form" onSubmit={(e) => e.preventDefault()}>
          <div className="auth-field">
            <label className="auth-label" htmlFor="email">이메일</label>
            <input
              id="email"
              type="email"
              className="auth-input"
              placeholder="example@email.com"
              autoComplete="email"
            />
          </div>

          <div className="auth-field">
            <label className="auth-label" htmlFor="password">비밀번호</label>
            <input
              id="password"
              type="password"
              className="auth-input"
              placeholder="비밀번호를 입력하세요"
              autoComplete="current-password"
            />
          </div>

          <button type="submit" className="auth-btn-primary">로그인</button>
        </form>

        <div className="auth-divider">또는</div>

        <button type="button" className="auth-btn-google">
          <GoogleIcon />
          Google로 계속하기
        </button>

        <p className="auth-footer">
          계정이 없으신가요?
          <Link to="/signup" className="auth-link">회원가입</Link>
        </p>
      </div>
    </div>
  )
}
