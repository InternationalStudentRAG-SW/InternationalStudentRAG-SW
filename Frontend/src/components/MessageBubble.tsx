import ReactMarkdown from 'react-markdown'
import { SourceList } from './SourceList'
import type { Message } from '../types'

interface Props {
  message: Message
  onSend: (question: string) => void; // 1. onSend 대소문자 수정
}

function getTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// 2. onSend 매개변수 추가
export function MessageBubble({ message, onSend }: Props) {
  const isUser = message.role === 'user'

  return (
    <div className={`message-row ${isUser ? 'message-row--user' : 'message-row--assistant'}`}>
      {!isUser && (
        <img src="/dongA_character.png" className="bot-avatar" alt="bot" />
      )}

      <div className={`message-wrap ${isUser ? 'message-wrap--user' : 'message-wrap--assistant'}`}>
        <div className={`message__bubble ${isUser ? 'message__bubble--user' : 'message__bubble--assistant'}`}>
          {isUser ? (
            <p style={{ margin: 0 }}>{message.content}</p>
          ) : (
            <ReactMarkdown>{message.content}</ReactMarkdown>
          )}
        </div>
        <div className="message-time">{getTime(message.timestamp)}</div>
        
        {!isUser && message.sources && message.sources.length > 0 && (
          <SourceList sources={message.sources} />
        )}

        {!isUser && message.suggestions && message.suggestions.length > 0 && (
          <div className="follow-up-container" style={{ marginTop : '12px'}}>
            <p style={{ fontSize: '0.85rem', color: '#666', marginBottom: '8px', fontWeight: 600 }}>
              💡 이런 질문은 어때요?
            </p>

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
              {message.suggestions.map((question, index) => (
                <button
                  key={index}
                  onClick={() => onSend(question)}
                  style={{
                    padding: '6px 12px',
                    fontSize: '0.85rem',
                    backgroundColor: '#f0f4ff',
                    color: '#2b6cb0',
                    border: '1px solid #bee3f8',
                    borderRadius: '16px',
                    cursor: 'pointer',
                    transition: 'all 0.2s ease'
                  }}
                  onMouseOver={(e) => e.currentTarget.style.backgroundColor = '#e2e8f0'}
                  onMouseOut={(e) => e.currentTarget.style.backgroundColor = '#f0f4ff'}
                >
                  {question}
                </button>
              ))}
            </div>
          </div>
        )}
      </div> {/* 4. message-wrap div 닫는 태그 추가 */}
    </div>
  )
}