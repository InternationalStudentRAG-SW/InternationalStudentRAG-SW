import { useState, useMemo } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Select from 'react-select'
import countryList from 'react-select-country-list'
import { signup } from '../services/api'
import './auth.css'

function BackgroundGlow() {
  return (
    <>
      <div className="glow-one" />
      <div className="glow-two" />
    </>
  )
}


export default function SignupPage() {
  const navigate = useNavigate();
  
  // [추가] 국가 리스트 데이터 생성
  const options = useMemo(() => countryList().getData(), []);

  const [formData, setFormData] = useState({
    email: '',
    nationality: null as any,
    major: '',
    password: '',
    passwordConfirm: '',
  });

  const [isLoading, setIsLoading] = useState(false);

  // [추가] 국적 선택 전용 핸들러
  const handleSelectChange = (value: any) => {
    setFormData(prev => ({ ...prev, nationality: value }));
  };

  // 일반 입력 핸들러
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { id, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [id]: value
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (formData.password !== formData.passwordConfirm) {
      alert("비밀번호가 서로 일치하지 않습니다.");
      return;
    }

    if (!formData.nationality) {
      alert("국적을 선택해 주세요.");
      return;
    }

    setIsLoading(true);

    try {
      await signup(
        formData.email,
        formData.password,
        formData.nationality.label,
        formData.major,
      );
      alert("회원가입이 완료되었습니다! 로그인해 주세요.");
      navigate('/login');
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || "오류가 발생했습니다.";
      alert("회원가입 실패: " + errorMsg);
    } finally {
      setIsLoading(false);
    }
  };

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

        <h1 className="auth-heading">회원가입</h1>
        <p className="auth-subheading">계정을 만들고 서비스를 시작하세요.</p>

        <form className="auth-form" onSubmit={handleSubmit}>
          {/* 이메일 */}
          <div className="auth-field">
            <label className="auth-label" htmlFor="email">이메일</label>
            <input
              id="email"
              type="email"
              className="auth-input"
              placeholder="example@email.com"
              value={formData.email}
              onChange={handleChange}
              required
            />
          </div>

          {/* [수정] 국적 선택 (react-select 적용) */}
          <div className="auth-field">
            <label className="auth-label">국적 (Nationality) *</label>
            <Select 
              options={options} 
              value={formData.nationality} 
              onChange={handleSelectChange}
              placeholder="국적을 검색하거나 선택하세요"
              className="country-select-container"
              styles={{
                control: (base) => ({
                  ...base,
                  borderRadius: '8px',
                  padding: '2px',
                  borderColor: '#e2e8f0',
                  boxShadow: 'none',
                  '&:hover': { borderColor: '#cbd5e1' }
                })
              }}
            />
          </div>

          {/* 전공 */}
          <div className="auth-field">
            <label className="auth-label" htmlFor="major">전공 (Major)</label>
            <input
              id="major"
              type="text"
              className="auth-input"
              placeholder="학과를 입력하세요 (예: 컴퓨터공학과)"
              value={formData.major}
              onChange={handleChange}
              required
            />
          </div>

          {/* 비밀번호 */}
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

          {/* 비밀번호 확인 */}
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

          <button type="submit" className="auth-btn-primary" disabled={isLoading}>
            {isLoading ? "처리 중..." : "회원가입"}
          </button>
        </form>

        <p className="auth-footer">
          이미 계정이 있으신가요?
          <Link to="/login" className="auth-link">로그인</Link>
        </p>
      </div>
    </div>
  )
}