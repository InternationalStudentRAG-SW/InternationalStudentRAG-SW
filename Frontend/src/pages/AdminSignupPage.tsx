import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { adminSignup } from '../services/api'
import './auth.css'

function BackgroundGlow() {
  return (
    <>
      <div className="glow-one" />
      <div className="glow-two" />
    </>
  )
}

export default function AdminSignupPage() {
  const navigate = useNavigate()
  const [formData, setFormData] = useState({
    email: '',
    password: '',
    passwordConfirm: '',
    adminSecret: '',
  })
  const [isLoading, setIsLoading] = useState(false)

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { id, value } = e.target
    setFormData(prev => ({ ...prev, [id]: value }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (formData.password !== formData.passwordConfirm) {
      alert('비밀번호가 일치하지 않습니다.')
      return
    }
    setIsLoading(true)
    try {
      await adminSignup(formData.email, formData.password, formData.adminSecret)
      alert('관리자 계정이 생성되었습니다. 로그인하세요.')
      navigate('/login')
    } catch (error: any) {
      const msg = error.response?.data?.detail || '오류가 발생했습니다.'
      alert('실패: ' + msg)
    } finally {
      setIsLoading(false)
    }
  }

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

        <h1 className="auth-heading">관리자 계정 생성</h1>
        <p className="auth-subheading">관리자 코드가 있는 경우에만 접근 가능합니다.</p>

        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="auth-field">
            <label className="auth-label" htmlFor="email">이메일</label>
            <input
              id="email"
              type="email"
              className="auth-input"
              placeholder="admin@example.com"
              value={formData.email}
              onChange={handleChange}
              required
            />
          </div>

          <div className="auth-field">
            <label className="auth-label" htmlFor="password">비밀번호</label>
            <input
              id="password"
              type="password"
              className="auth-input"
              placeholder="비밀번호를 입력하세요"
              value={formData.password}
              onChange={handleChange}
              required
            />
          </div>

          <div className="auth-field">
            <label className="auth-label" htmlFor="passwordConfirm">비밀번호 확인</label>
            <input
              id="passwordConfirm"
              type="password"
              className="auth-input"
              placeholder="비밀번호를 다시 입력하세요"
              value={formData.passwordConfirm}
              onChange={handleChange}
              required
            />
          </div>

          <div className="auth-field">
            <label className="auth-label" htmlFor="adminSecret">관리자 코드</label>
            <input
              id="adminSecret"
              type="password"
              className="auth-input"
              placeholder="관리자 코드를 입력하세요"
              value={formData.adminSecret}
              onChange={handleChange}
              required
            />
          </div>

          <button type="submit" className="auth-btn-primary" disabled={isLoading}>
            {isLoading ? '처리 중...' : '관리자 계정 생성'}
          </button>
        </form>

        <p className="auth-footer">
          <Link to="/login" className="auth-link">로그인으로 돌아가기</Link>
        </p>
      </div>
    </div>
  )
}
