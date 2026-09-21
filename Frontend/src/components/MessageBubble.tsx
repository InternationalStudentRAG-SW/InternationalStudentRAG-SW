import ReactMarkdown from 'react-markdown'
import { SourceList } from './SourceList'
import { ThinkingSteps } from './ThinkingSteps'
import type { Message, Language } from '../types'
import { getLabels } from '../i18n'

interface Props {
  message: Message
  onSend: (question: string) => void
  language: Language
}

function getTime(date: Date, locale: string): string {
  return date.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })
}

export function MessageBubble({ message, onSend, language }: Props) {
  const isUser = message.role === 'user'
  const labels = getLabels(language)

  return (
    <div className={`message-row ${isUser ? 'message-row--user' : 'message-row--assistant'}`}>
      {!isUser && (
        <img src="/dongA_character.png" className="bot-avatar" alt="bot" />
      )}

      <div className={`message-wrap ${isUser ? 'message-wrap--user' : 'message-wrap--assistant'}`}>
        {/* 답변 생성 전: 상태 표시 (content 없으면 즉시 표시) */}
        {!isUser && !message.content && (
          <ThinkingSteps statusSteps={message.statusSteps ?? []} language={(message.language ?? language) as Language} />
        )}

        {/* 마지막 토큰 후 ~ done 이벤트 전 (meta 이벤트 수신 시점부터) */}
        {!isUser && message.metaStatus && !message.sources && (
          <div className="thinking-more">
            <div className="thinking-more__dots">
              <span className="thinking-more__dot" />
              <span className="thinking-more__dot" />
              <span className="thinking-more__dot" />
            </div>
            <span>{message.metaStatus}</span>
          </div>
        )}

        <div className={`message__bubble ${isUser ? 'message__bubble--user' : 'message__bubble--assistant'}`}
          style={!isUser && !message.content ? { display: 'none' } : undefined}>
          {isUser ? (
            <p style={{ margin: 0 }}>{message.content}</p>
          ) : (
            <ReactMarkdown>{message.content}</ReactMarkdown>
          )}
        </div>
        <div className="message-time">{getTime(message.timestamp, labels.timeLocale)}</div>

        {!isUser && message.sources && message.sources.length > 0 && (
          <SourceList sources={message.sources} language={language} />
        )}

        {!isUser && message.suggestions && message.suggestions.length > 0 && (
          <div className="follow-up-container" style={{ marginTop : '12px'}}>
            <p style={{ fontSize: '0.85rem', color: '#666', marginBottom: '8px', fontWeight: 600 }}>
              {labels.suggestions}
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