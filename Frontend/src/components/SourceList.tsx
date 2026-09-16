import type { Source, Language } from '../types'
import { getDocumentUrl } from '../services/api'
import { getLabels } from '../i18n'

interface Props {
  sources: Source[]
  language: Language
}

export function SourceList({ sources, language }: Props) {
  if (sources.length === 0) return null
  const labels = getLabels(language)

  return (
    <div className="source-list">
      <p className="source-list__title">{labels.sourceTitle}</p>
      <ul>
        {sources.map((src, i) => {
          const url = getDocumentUrl(src.source)
          return (
            <li key={i} className="source-item">
              <a
                href={url}
                download={src.source}
                className="source-item__name"
              >
                {src.source}
              </a>
              <span className="source-item__meta">
                {labels.relevance} {(src.similarity_score * 100).toFixed(1)}%
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
