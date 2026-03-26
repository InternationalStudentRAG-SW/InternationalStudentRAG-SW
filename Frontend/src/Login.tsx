import { useState } from "react";
import { styles } from "./styles";
import { useNavigate } from "react-router-dom";
import { GoogleOAuthProvider, GoogleLogin } from "@react-oauth/google";

// 귀욤둥이 숙힝님이 발급받으신 클라이언트 ID
const GOOGLE_CLIENT_ID = "732972275259-brh4j5m0siq77mifq88lr32mfvv8t3ie.apps.googleusercontent.com";

function Login() {
  const [id, setId] = useState<string>("");
  const [pw, setPw] = useState<string>("");
  const navigate = useNavigate();

  // 일반(자체) 로그인 버튼 클릭 시
  function handleLogin() {
    if (!id || !pw) {
      alert("아이디와 비밀번호를 입력해주세요.");
      return;
    }

    // 실제로는 여기서도 백엔드에 아이디/비번을 보내 검증해야 합니다.
    localStorage.setItem("isLogin", "true");
    localStorage.setItem("isLogin", "true");
    localStorage.setItem("userName", "동아대 유학생"); // 👈 일반 로그인 시 저장될 이름
    navigate("/");
  }

  // 구글 로그인 성공 시 백엔드와 통신하는 함수
  const handleGoogleSuccess = async (credentialResponse: any) => {
    const token = credentialResponse.credential;
    console.log("구글로부터 받은 토큰:", token);
    
    try {
      // 파이썬 FastAPI 백엔드(포트 8000 가정)로 토큰 전송
      const res = await fetch("http://localhost:8000/api/auth/google", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      
      const data = await res.json();
      
      if (res.ok) {
        console.log("백엔드 검증 성공:", data);
        localStorage.setItem("isLogin", "true");
        navigate("/"); 
      } else {
        alert("구글 로그인 검증 실패: " + data.detail);
      }
    } catch (error) {
      console.error("서버 통신 오류", error);
      // 만약 아직 백엔드를 켜지 않았다면 임시로 홈으로 이동하게 하려면 아래 두 줄의 주석을 푸세요.
      // localStorage.setItem("isLogin", "true");
      // navigate("/");
    }
  };

  return (
    <div style={styles.page}>
      <div style={styles.glowOne} />
      <div style={styles.glowTwo} />

      <div
        style={{
          maxWidth: "420px",
          margin: "0 auto",
          marginTop: "80px",
          background: "rgba(255,255,255,0.75)",
          backdropFilter: "blur(18px)",
          borderRadius: "28px",
          padding: "40px",
          boxShadow: "0 20px 60px rgba(89, 105, 255, 0.15)",
          border: "1px solid rgba(255,255,255,0.7)",
        }}
      >
        <h2
          style={{
            textAlign: "center",
            fontSize: "26px",
            fontWeight: 900,
            marginBottom: "30px",
          }}
        >
          로그인
        </h2>

        {/* 아이디 */}
        <input
          type="text"
          placeholder="아이디"
          value={id}
          onChange={(e) => setId(e.target.value)}
          style={{
            ...styles.input,
            background: "white",
            borderRadius: "14px",
            border: "1px solid rgba(226,232,240,0.9)",
            marginBottom: "14px",
          }}
        />

        {/* 비밀번호 */}
        <input
          type="password"
          placeholder="비밀번호"
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          style={{
            ...styles.input,
            background: "white",
            borderRadius: "14px",
            border: "1px solid rgba(226,232,240,0.9)",
            marginBottom: "20px",
          }}
        />

        {/* 일반 로그인 버튼 */}
        <button
          onClick={handleLogin}
          style={{
            width: "100%",
            ...styles.sendButton,
            borderRadius: "16px",
            marginBottom: "20px",
          }}
        >
          로그인
        </button>

        {/* 구분선 */}
        <div
          style={{
            textAlign: "center",
            margin: "20px 0",
            color: "#94a3b8",
            fontWeight: 600,
          }}
        >
          또는
        </div>

        {/* 구글 로그인 버튼 (GoogleOAuthProvider로 감쌈) */}
        <div style={{ display: "flex", justifyContent: "center", width: "100%" }}>
          <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
            <GoogleLogin
              onSuccess={handleGoogleSuccess}
              onError={() => {
                console.log("구글 로그인 실패 또는 창 닫힘");
              }}
              // 버튼 모양을 조금 더 넓게 설정하고 싶다면 아래 주석을 해제하세요.
              // shape="rectangular"
              // width="340"
            />
          </GoogleOAuthProvider>
        </div>
      </div>
    </div>
  );
}

export default Login;