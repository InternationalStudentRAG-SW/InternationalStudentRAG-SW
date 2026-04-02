import type { Source } from '../types'
import { getDocumentUrl } from '../services/api'

interface Props {
  sources: Source[]
}

export function SourceList({ sources }: Props) {
  if (sources.length === 0) return null

  return (
    <div className="source-list">
      <p className="source-list__title">출처 문서</p>
      <ul>
        {sources.map((src, i) => {
          // 파일명을 실제 열 수 있는 URL로 변환
          const url = getDocumentUrl(src.source)
          
          return (
            <li key={i} className="source-item">
              <a
                href={url}
                download={src.source} // download 기능
                className="source-item__name"
              >
              {src.source}
              </a>

              <span className="source-item__meta">
                청크 #{src.chunk_index} &nbsp;·&nbsp; 관련성{' '}
                {(src.similarity_score * 100).toFixed(1)}%
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
