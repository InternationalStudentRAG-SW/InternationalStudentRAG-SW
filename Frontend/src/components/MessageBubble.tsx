import ReactMarkdown from 'react-markdown'
import { SourceList } from './SourceList'
import type { Message } from '../types'

interface Props {
  message: Message
}

function getTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function MessageBubble({ message }: Props) {
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
      </div>
    </div>
  )
}
