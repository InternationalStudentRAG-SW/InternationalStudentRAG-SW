import type { Source } from '../types'

interface Props {
  sources: Source[]
}

export function SourceList({ sources }: Props) {
  if (sources.length === 0) return null

  return (
    <div className="source-list">
      <p className="source-list__title">출처 문서</p>
      <ul>
        {sources.map((src, i) => (
          <li key={i} className="source-item">
            <span className="source-item__name">{src.source}</span>
            <span className="source-item__meta">
              청크 #{src.chunk_index} &nbsp;·&nbsp; 관련성{' '}
              {(src.similarity_score * 100).toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
