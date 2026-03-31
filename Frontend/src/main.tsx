import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { GoogleOAuthProvider } from '@react-oauth/google' // [추가] 구글 인증 프로바이더 임포트
import App from './App'

const rootEl = document.getElementById('root')!

// [참고] 구글 클라이언트 ID는 보통 .env 파일에 관리하는 것이 좋지만, 
// 테스트를 위해 직접 입력하는 방식으로 구성했습니다.
const GOOGLE_CLIENT_ID = "183948671269-vivrbtf6jiol1qfmrkukjd2kk5j2n25f.apps.googleusercontent.com"

createRoot(rootEl).render(
  <StrictMode>
    {/* [수정] 앱 전체를 GoogleOAuthProvider로 감싸서 어디서든 구글 로그인을 쓸 수 있게 함 */}
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </GoogleOAuthProvider>
  </StrictMode>,
)