import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import Select from 'react-select'
import countryList from 'react-select-country-list'
import { updateAdditionalInfo } from '../services/api'
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
  const options = useMemo(() => countryList().getData(), []);

  const [formData, setFormData] = useState({
    nationality: null as any,
    major: '',
  });

  const handleSelectChange = (value: any) => {
    setFormData(prev => ({ ...prev, nationality: value }));
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { id, value } = e.target;
    setFormData(prev => ({ ...prev, [id]: value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!formData.nationality) {
      alert("모든 필수 정보를 입력해 주세요.");
      return;
    }

    setIsLoading(true);
    try {
      await updateAdditionalInfo(formData.nationality.label, formData.major);
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
          <div className="auth-field">
            <label className="auth-label">국적 (Nationality) *</label>
            <Select
              options={options}
              value={formData.nationality}
              onChange={handleSelectChange}
              placeholder="국가를 검색하거나 선택하세요..."
              className="country-select"
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

          <button type="submit" className="auth-btn-primary" disabled={isLoading}>
            {isLoading ? "저장 중..." : "시작하기"}
          </button>
        </form>
      </div>
    </div>
  )
}
