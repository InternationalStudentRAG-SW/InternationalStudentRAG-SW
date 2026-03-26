import { useMemo, useState, useEffect, useRef } from "react";
import { styles } from "./styles";
import { useNavigate } from "react-router-dom";

type Language = "ko" | "en";
type Role = "bot" | "user";

type Message = {
  role: Role;
  text: string;
  time: string;
};

type ContentItem = {
  badge: string;
  title: string;
  description: string;
  quickTitle: string;
  inputPlaceholder: string;
  send: string;
  typing: string;
  online: string;
  welcome: string;
  quickQuestions: string[];
};

type ContentMap = {
  ko: ContentItem;
  en: ContentItem;
};

function Home() {
  const navigate = useNavigate();
  const [isLogin, setIsLogin] = useState<boolean>(false);
  const [input, setInput] = useState<string>("");
  const [language, setLanguage] = useState<Language>("ko");
  const [userName, setUserName] = useState<string>(""); // 유저 이름 상태 추가 
  const [loading, setLoading] = useState<boolean>(false);
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "bot",
      text: "안녕하세요! 유학생 생활과 행정 안내를 도와드릴게요. 궁금한 내용을 편하게 물어보세요.",
      time: getTime(),
    },
  ]);

  const chatBodyRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const loginState = localStorage.getItem("isLogin");
    const storedName = localStorage.getItem("userName"); // 저장된 이름 가져오기
    setIsLogin(loginState === "true");
    if (storedName) {
      setUserName(storedName); // 상태에 이름 설정
    }
  }, []);

  useEffect(() => {
    if (chatBodyRef.current) {
      chatBodyRef.current.scrollTop = chatBodyRef.current.scrollHeight;
    }
  }, [messages, loading]);

  function handleLoginClick() {
    navigate("/login");
  }

  function handleLogout() {
    localStorage.removeItem("isLogin");
    localStorage.removeItem("userName"); // 로그아웃 시 이름도 제거
    setIsLogin(false);
    setUserName(""); // 이름 상태 초기화
  }

  const content = useMemo<ContentMap>(() => {
    return {
      ko: {
        badge: "AI CAMPUS ASSISTANT",
        title: "유학생 생활·행정 안내 챗봇",
        description:
          "학교 문서를 바탕으로 필요한 정보를 빠르게 찾을 수 있는 스마트 챗봇",
        quickTitle: "자주 묻는 질문",
        inputPlaceholder: "예: 기숙사 신청 기간은 언제인가요?",
        send: "전송",
        typing: "답변 작성 중...",
        online: "상담 가능",
        welcome:
          "안녕하세요! 유학생 생활과 행정 안내를 도와드릴게요. 궁금한 내용을 편하게 물어보세요.",
        quickQuestions: [
          "기숙사 신청 기간은 언제인가요?",
          "비자 연장에 필요한 서류는 무엇인가요?",
          "유학생 보험은 어떻게 가입하나요?",
          "수강신청 변경 기간을 알려주세요.",
        ],
      },
      en: {
        badge: "AI CAMPUS ASSISTANT",
        title: "International Student Support Chatbot",
        description:
          "A smart chatbot that helps students quickly find guidance from school documents",
        quickTitle: "Popular Questions",
        inputPlaceholder: "e.g. When is the dormitory application period?",
        send: "Send",
        typing: "Writing a reply...",
        online: "Online",
        welcome:
          "Hello! I can help you with international student life and administrative guidance. Ask me anything.",
        quickQuestions: [
          "When is the dormitory application period?",
          "What documents are needed for a visa extension?",
          "How do I sign up for student insurance?",
          "When can I change my course registration?",
        ],
      },
    };
  }, []);

  const t = content[language];

  function getBotReply(question: string): string {
    const q = question.toLowerCase();

    if (q.includes("기숙사") || q.includes("dorm")) {
      return language === "ko"
        ? "기숙사 신청은 보통 학기 시작 전 공지 기간에 진행돼요. 학교 홈페이지 공지사항이나 포털의 생활관 안내를 먼저 확인해보세요."
        : "Dormitory applications are usually announced before the semester starts. Please check the housing notice on the school website or portal first.";
    }

    if (q.includes("비자") || q.includes("visa")) {
      return language === "ko"
        ? "비자 연장 시에는 일반적으로 여권, 재학증명서, 등록금 납부 확인서 등이 필요해요. 학교 국제처 공지와 출입국 공식 안내를 함께 확인하는 것이 가장 정확합니다."
        : "For a visa extension, you usually need your passport, certificate of enrollment, and tuition payment proof. It is best to check both the international office notice and the official immigration guide.";
    }

    if (q.includes("보험") || q.includes("insurance")) {
      return language === "ko"
        ? "유학생 보험은 학교 공지 또는 학생지원 안내에서 가입 방법을 확인할 수 있어요. 대상 여부, 납부 기간, 보장 범위를 함께 확인해보세요."
        : "You can usually find student insurance information in school notices or student support guidance. Check eligibility, payment dates, and coverage details as well.";
    }

    if (q.includes("수강") || q.includes("course") || q.includes("registration")) {
      return language === "ko"
        ? "수강신청 변경 기간은 학사일정에 함께 안내되는 경우가 많아요. 학사 공지와 수강신청 시스템 일정을 먼저 확인해보세요."
        : "The add/drop period is often listed in the academic calendar. Please check the academic notice and course registration schedule first.";
    }

    return language === "ko"
      ? "현재는 데모 UI라서 대표 질문 중심으로 답변하고 있어요. 이후에는 실제 문서 검색 기능을 연결해서 더 정확한 안내를 제공할 수 있습니다."
      : "This is currently a demo UI, so it answers common questions first. Later, real document retrieval can be connected for more accurate guidance.";
  }

  function sendMessage(textFromButton?: string): void {
    const text = textFromButton || input;
    if (!text.trim()) return;

    const userMessage: Message = {
      role: "user",
      text,
      time: getTime(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);

    setTimeout(() => {
      const botReply: Message = {
        role: "bot",
        text: getBotReply(text),
        time: getTime(),
      };
      setMessages((prev) => [...prev, botReply]);
      setLoading(false);
    }, 900);
  }

  return (
    <div style={styles.page}>
      <BackgroundGlow />
      
      {/* 🔥 로그인 버튼 (상단 위치) */}
      <div style={{ 
        position: "absolute", 
        top: 20, right: 30,
        display: "flex", alignItems: "center", gap: "15px", zIndex: 10
        }}>
        {isLogin ? (
          <>
            <span style={{ fontSize: "15px", color: "#555", fontWeight: 800 }}>
              {userName ? `${userName}님 , 환영합니다` : "로그인 상태"}
            </span>
            <button onClick={handleLogout} style={{
              ...styles.sendButton,
              padding : "8px 14px",
              fontSize: "13px",
              borderRadius: "12px",
              }}>
              로그아웃
            </button>
          </> 
        ) : (
          <> 
            <button onClick={handleLoginClick} style={{
              ...styles.sendButton,
              padding: "8px 14px",
              fontSize: "13px",
              borderRadius: "12px"
            }}>
              로그인
            </button>
            <button onClick={() => navigate("/signup")} style={{
                ...styles.sendButton,
                padding: "8px 14px",
                fontSize: "13px",
                borderRadius: "12px",
                background: "white",     
                color: "#5969ff",        
                border: "1px solid #5969ff" 
              }}>
                회원가입
            </button>
          </>
        )}
      </div>
      
      <div style={styles.shell}>
        <aside style={styles.sidebar}>
          <div style={styles.logoCard}>
            <div style={styles.logoRow}>
              <img src="/dongA_symbol.jpg" style={styles.logoIcon} />
              <div>
                <div style={styles.badge}>{t.badge}</div>
                <h1 style={styles.title}>{t.title}</h1>
              </div>
            </div>

            <p style={styles.description}>{t.description}</p>

            <div style={styles.statusCard}>
              <div style={styles.statusDot} />
              <span>{t.online}</span>
            </div>
          </div>

          <div style={styles.quickCard}>
            <div style={styles.sectionTitle}>{t.quickTitle}</div>
            <div style={styles.quickList}>
              {t.quickQuestions.map((q) => (
                <button
                  key={q}
                  onClick={() => sendMessage(q)}
                  style={styles.quickButton}
                >
                  <span style={styles.quickIcon}>↗</span>
                  <span>{q}</span>
                </button>
              ))}
            </div>
          </div>
        </aside>

        <main style={styles.chatPanel}>
          <div style={styles.chatHeader}>
            <div>
              <div style={styles.chatHeaderTitle}>Campus Chat</div>
              <div style={styles.chatHeaderSub}>
                {language === "ko"
                  ? "문서 기반 안내 · 빠른 응답"
                  : "Document-based guidance · fast replies"}
              </div>
            </div>

            <div style={styles.langSwitch}>
              <button
                onClick={() => setLanguage("ko")}
                style={{
                  ...styles.langButton,
                  ...(language === "ko" ? styles.langButtonActive : {}),
                }}
              >
                KR
              </button>
              <button
                onClick={() => setLanguage("en")}
                style={{
                  ...styles.langButton,
                  ...(language === "en" ? styles.langButtonActive : {}),
                }}
              >
                EN
              </button>
            </div>
          </div>

          <div ref={chatBodyRef} style={styles.chatBody}>
            {messages.map((msg, index) => {
              const isUser = msg.role === "user";
              return (
                <div
                  key={`${msg.time}-${index}`}
                  style={{
                    ...styles.messageRow,
                    justifyContent: isUser ? "flex-end" : "flex-start",
                  }}
                >
                  {!isUser && (<img src="/dongA_character.png" style={styles.avatarBot} />)}

                  <div
                    style={{
                      ...styles.messageWrap,
                      alignItems: isUser ? "flex-end" : "flex-start",
                    }}
                  >
                    <div
                      style={{
                        ...styles.messageBubble,
                        ...(isUser ? styles.userBubble : styles.botBubble),
                      }}
                    >
                      {msg.text}
                    </div>
                    <div style={styles.messageTime}>{msg.time}</div>
                  </div>
                </div>
              );
            })}

            {loading && (
              <div style={styles.messageRow}>
                <img src="/dongA_character.png" style={styles.avatarBot} />
                <div style={styles.messageWrap}>
                  <div style={styles.loadingBubble}>
                    <TypingDots />
                    <span style={{ marginLeft: 10 }}>{t.typing}</span>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div style={styles.inputArea}>
            <div style={styles.inputBox}>
              <input
                type="text"
                value={input}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setInput(e.target.value)
                }
                placeholder={t.inputPlaceholder}
                style={styles.input}
                onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => {
                  // 🔥 핵심 수정 부분! isComposing이 false일 때만 (한글 조합이 끝났을 때만) 전송
                  if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                    sendMessage();
                  }
                }}
              />

              <button onClick={() => sendMessage()} style={styles.sendButton}>
                {t.send}
              </button>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

function BackgroundGlow() {
  return (
    <>
      <div style={styles.glowOne} />
      <div style={styles.glowTwo} />
    </>
  );
}

function TypingDots() {
  return (
    <div style={styles.dots}>
      <span style={styles.dot} />
      <span style={styles.dot} />
      <span style={styles.dot} />
    </div>
  );
}

function getTime(): string {
  const now = new Date();
  return now.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default Home;