import { useState, useMemo } from 'react' // [수정] useMemo 추가
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import Select from 'react-select' // [추가] 라이브러리 임포트
import countryList from 'react-select-country-list' // [추가] 국가 리스트 라이브러리
import './auth.css'

function BackgroundGlow() {
  return (
    <>
      <div className="glow-one" />
      <div className="glow-two" />
    </>
  )
}

export default function AdditionalInfoPage() {
  const navigate = useNavigate();
  const [isLoading, setIsLoading] = useState(false);
  
  // [추가] 국가 리스트 데이터 생성 (가나다순/알파벳순 자동 정렬됨)
  const options = useMemo(() => countryList().getData(), []);

  const [formData, setFormData] = useState({
    nationality: null as any, // react-select는 객체 형태를 사용함
    major: '',
    is_profile_public: false
  });

  // [수정] 일반 입력과 셀렉트 박스 입력을 동시에 처리하기 위한 핸들러
  const handleSelectChange = (value: any) => {
    setFormData(prev => ({ ...prev, nationality: value }));
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { id, value, type, checked } = e.target;
    setFormData(prev => ({ 
      ...prev, 
      [id]: type === 'checkbox' ? checked : value 
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    const userEmail = localStorage.getItem('userEmail');
    if (!userEmail || !formData.nationality) {
      alert("모든 필수 정보를 입력해 주세요.");
      return;
    }

    setIsLoading(true);
    try {
      await axios.post('http://127.0.0.1:8000/api/update-additional-info', {
        email: userEmail,
        nationality: formData.nationality.label, // 국가 이름(예: South Korea)만 추출해서 전송
        major: formData.major,
        is_profile_public: formData.is_profile_public
      });

      alert("프로필 설정이 완료되었습니다!");
      navigate('/'); 
    } catch (error: any) {
      alert("정보 저장 중 오류가 발생했습니다.");
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
            <div className="auth-logo-badge">Profile Setup</div>
            <div className="auth-logo-title">추가 정보 입력</div>
          </div>
        </div>

        <h1 className="auth-heading">정보 완성하기</h1>
        <p className="auth-subheading">전 세계 국가 리스트에서 본인의 국적을 선택하세요.</p>

        <form className="auth-form" onSubmit={handleSubmit}>
          {/* 국적 선택: 라이브러리 적용 */}
          <div className="auth-field">
            <label className="auth-label">국적 (Nationality) *</label>
            <Select 
              options={options} 
              value={formData.nationality} 
              onChange={handleSelectChange}
              placeholder="국가를 검색하거나 선택하세요..."
              className="country-select"
              // auth.css와 어울리도록 인라인 스타일 살짝 추가
              styles={{
                control: (base) => ({
                  ...base,
                  borderRadius: '8px',
                  padding: '2px',
                  borderColor: '#e2e8f0'
                })
              }}
            />
          </div>

          <div className="auth-field">
            <label className="auth-label" htmlFor="major">전공 (Major)</label>
            <input
              id="major"
              type="text"
              className="auth-input"
              placeholder="예: 컴퓨터공학부"
              value={formData.major}
              onChange={handleInputChange}
              required
            />
          </div>

          <div className="auth-field-checkbox" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 0' }}>
            <input
              id="is_profile_public"
              type="checkbox"
              checked={formData.is_profile_public}
              onChange={handleInputChange}
            />
            <label className="auth-label" htmlFor="is_profile_public" style={{ marginBottom: 0 }}>
              다른 유학생들에게 프로필 공개
            </label>
          </div>

          <button type="submit" className="auth-btn-primary" disabled={isLoading}>
            {isLoading ? "저장 중..." : "시작하기"}
          </button>
        </form>
      </div>
    </div>
  )
}