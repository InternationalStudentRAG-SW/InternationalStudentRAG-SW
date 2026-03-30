import type { Language } from '../types'

interface Props {
  value: Language
  onChange: (lang: Language) => void
}

const LANGUAGES: { key: Language; label: string }[] = [
  { key: 'auto', label: 'Auto' },
  { key: 'ko', label: 'KR' },
  { key: 'en', label: 'EN' },
  { key: 'zh', label: 'ZH' },
  { key: 'es', label: 'ES' },
]

export function LanguageSelector({ value, onChange }: Props) {
  return (
    <div className="language-selector">
      {LANGUAGES.map(({ key, label }) => (
        <button
          key={key}
          className={`lang-btn ${value === key ? 'lang-btn--active' : ''}`}
          onClick={() => onChange(key)}
        >
          {label}
        </button>
      ))}
    </div>
  )
}
