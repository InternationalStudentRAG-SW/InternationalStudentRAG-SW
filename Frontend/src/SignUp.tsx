import React, { useState } from "react"; // 👈 React를 임포트 해줍니다.
import { styles } from "./styles"; 
import { useNavigate } from "react-router-dom";

function SignUp() {
  const [name, setName] = useState<string>("");
  const [id, setId] = useState<string>("");
  const [pw, setPw] = useState<string>("");
  const [nationality, setNationality] = useState<string>("");
  const [department, setDepartment] = useState<string>("");
  const [studentId, setStudentId] = useState<string>("");

  const navigate = useNavigate();

  const handleSignUp = async () => {
    if (!name || !id || !pw || !nationality || !department || !studentId) {
      alert("모든 항목을 입력해주세요.");
      return;
    }

    try {
      const res = await fetch("http://localhost:8000/api/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          user_id: id, 
          password: pw, 
          name: name,
          nationality: nationality,
          department: department,
          student_id: studentId
        }),
      });

      const data = await res.json();

      if (res.ok) {
        alert("회원가입이 완료되었습니다! 로그인해주세요.");
        navigate("/login"); 
      } else {
        alert("회원가입 실패: " + data.detail);
      }
    } catch (error) {
      console.error("서버 오류", error);
      alert("서버와 통신할 수 없습니다.");
    }
  };

  // 🔥 React.CSSProperties 타입을 붙여서 오류를 없앱니다!
  
  const fieldWrapperStyle: React.CSSProperties = {
    display: "flex",
    flexDirection: "column",
    width: "100%",
    marginBottom: "20px" 
  };

  const labelStyle: React.CSSProperties = {
    fontSize: "15px", 
    fontWeight: 700,   
    color: "#333",     
    marginBottom: "8px", 
    textAlign: "left"
  };

  const inputStyle: React.CSSProperties = {
    ...(styles.input as React.CSSProperties), // 👈 혹시 모를 충돌 방지용 타입 단언
    width: "100%", 
    boxSizing: "border-box", 
    margin: 0, 
    height: "50px", 
    background: "white",
    borderRadius: "14px",
    border: "1px solid rgba(226,232,240,0.9)",
    fontSize: "15px", 
  };

  const formContainerStyle: React.CSSProperties = {
    display: "flex",
    flexDirection: "column",
    width: "100%",
  };

  return (
    <div style={styles.page}>
      <div style={styles.glowOne} />
      <div style={styles.glowTwo} />

      <div
        style={{
          maxWidth: "420px",
          margin: "0 auto",
          marginTop: "40px",
          background: "rgba(255,255,255,0.75)",
          backdropFilter: "blur(18px)",
          borderRadius: "28px",
          padding: "40px 30px", 
          boxShadow: "0 20px 60px rgba(89, 105, 255, 0.15)",
          border: "1px solid rgba(255,255,255,0.7)",
        }}
      >
        {/* 기존 styles.title에도 깐깐한 타입스크립트를 위해 as React.CSSProperties를 붙여줍니다 */}
        <h2 style={{ ...(styles.title as React.CSSProperties), fontSize: "28px", marginBottom: "35px" }}>
          회원가입
        </h2>

        <div style={formContainerStyle}>
          
          <div style={fieldWrapperStyle}>
            <label style={labelStyle}>이름</label>
            <input type="text" placeholder="예: 홍길동" value={name} onChange={(e)=>setName(e.target.value)} style={inputStyle} />
          </div>

          <div style={fieldWrapperStyle}>
            <label style={labelStyle}>국적</label>
            <input type="text" placeholder="예: 베트남, 중국 등" value={nationality} onChange={(e)=>setNationality(e.target.value)} style={inputStyle} />
          </div>

          <div style={fieldWrapperStyle}>
            <label style={labelStyle}>학과</label>
            <input type="text" placeholder="예: 컴퓨터공학과" value={department} onChange={(e)=>setDepartment(e.target.value)} style={inputStyle} />
          </div>

          <div style={fieldWrapperStyle}>
            <label style={labelStyle}>학번</label>
            <input type="text" placeholder="예: 20240001" value={studentId} onChange={(e)=>setStudentId(e.target.value)} style={inputStyle} />
          </div>

          <div style={fieldWrapperStyle}>
            <label style={labelStyle}>아이디</label>
            <input type="text" placeholder="이메일 또는 아이디" value={id} onChange={(e)=>setId(e.target.value)} style={inputStyle} />
          </div>

          <div style={fieldWrapperStyle}>
            <label style={labelStyle}>비밀번호</label>
            <input type="password" placeholder="비밀번호" value={pw} onChange={(e)=>setPw(e.target.value)} style={inputStyle} />
          </div>

        </div>

        <div style={{ marginTop: "35px", display: "flex", flexDirection: "column", gap: "12px" }}>
          <button onClick={handleSignUp} style={{ width: "100%", ...styles.sendButton, borderRadius: "16px", height: "50px" }}>
            가입하기
          </button>
          <button onClick={()=> navigate(-1)} style={{ width: "100%", padding: "14px", borderRadius: "16px", border: "none", background: "#e2e8f0", color: "#475569", fontWeight: 800, cursor: "pointer", height: "50px" }}>
            뒤로가기
          </button>
        </div>
      </div>
    </div>
  );
}

export default SignUp;