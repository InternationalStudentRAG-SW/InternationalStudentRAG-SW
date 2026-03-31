import { useState, useMemo } from 'react' // [수정] useMemo 추가
import { Link, useNavigate } from 'react-router-dom'
import axios from 'axios'
import Select from 'react-select' // [추가] react-select 임포트
import countryList from 'react-select-country-list' // [추가] 국가 리스트 임포트
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

export default function SignupPage() {
  const navigate = useNavigate();
  
  // [추가] 국가 리스트 데이터 생성
  const options = useMemo(() => countryList().getData(), []);

  const [formData, setFormData] = useState({
    name: '',
    email: '',
    nationality: null as any, // [수정] react-select를 위해 객체 타입으로 변경
    major: '',
    password: '',
    passwordConfirm: ''
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
      const response = await axios.post('http://127.0.0.1:8000/api/signup', {
        email: formData.email,
        password: formData.password,
        nationality: formData.nationality.label, // [수정] 객체에서 국가 이름(label)만 추출해서 전송
        major: formData.major,
        role: 'STUDENT',
        status: 'ACTIVE'
      });

      if (response.status === 200 || response.status === 201) {
        alert("회원가입이 완료되었습니다! 로그인해 주세요.");
        navigate('/login');
      }
    } catch (error: any) {
      console.error("Signup Error:", error);
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
          {/* 이름 */}
          <div className="auth-field">
            <label className="auth-label" htmlFor="name">이름</label>
            <input
              id="name"
              type="text"
              className="auth-input"
              placeholder="홍길동"
              value={formData.name}
              onChange={handleChange}
              required
            />
          </div>

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

        <div className="auth-divider">또는</div>

        <button type="button" className="auth-btn-google">
          <GoogleIcon />
          Google로 계속하기
        </button>

        <p className="auth-footer">
          이미 계정이 있으신가요?
          <Link to="/login" className="auth-link">로그인</Link>
        </p>
      </div>
    </div>
  )
}