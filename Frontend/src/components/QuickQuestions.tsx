interface Props {
  onSend: (question: string) => void
}

const QUICK_QUESTIONS = [
  '기숙사 신청 기간은 언제인가요?',
  '비자 연장에 필요한 서류는 무엇인가요?',
  '유학생 보험은 어떻게 가입하나요?',
  '수강신청 변경 기간을 알려주세요.',
]

export function QuickQuestions({ onSend }: Props) {
  return (
    <div className="quick-card">
      <div className="quick-title">자주 묻는 질문</div>
      <div className="quick-list">
        {QUICK_QUESTIONS.map((q) => (
          <button key={q} className="quick-button" onClick={() => onSend(q)}>
            <span className="quick-icon">↗</span>
            <span>{q}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
