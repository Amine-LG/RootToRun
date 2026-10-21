import { useState } from 'react'
import type { Explain } from '../lib/data'
import { t } from '../lib/i18n'
import { Md } from "../lib/md"
import { recordExplain, setConfidence, useProgress } from '../lib/progress'
import { Icon } from './ui'

/** Explain it in your own words to a given audience, then self-assess against a rubric (recorded as self-assessment). */
export function ExplainCard({ e, k }: { e: Explain; k: string }) {
  const prog = useProgress()
  const prior = prog.explains[k]
  const [text, setText] = useState('')
  const [phase, setPhase] = useState<'write' | 'score' | 'done'>('write')
  const [marks, setMarks] = useState<boolean[]>(e.rubric.map(() => false))
  const score = marks.filter(Boolean).length
  return (
    <div className="explain" data-testid="explain">
      <div className="explain-h">
        <Icon name="bulb" size={16} /> {t('learn.explainTo', { audience: e.audience })}
        {prior && <span className="pill muted">{t('learn.lastScore', { score: prior.score, of: prior.of })}</span>}
      </div>
      <Md text={e.prompt} />
      {phase === 'write' && (
        <>
          <textarea value={text} onChange={(ev) => setText(ev.target.value)} rows={5} placeholder={t('learn.explainPlaceholder')} aria-label={t('learn.yourExplanation')} />
          <div className="row">
            <button className="btn" disabled={text.trim().length < 40} onClick={() => setPhase('score')}>
              {t('learn.scoreIt')}
            </button>
            <span className="muted small">{t('learn.minChars', { n: Math.max(0, 40 - text.trim().length) })}</span>
          </div>
        </>
      )}
      {phase !== 'write' && (
        <>
          <blockquote className="mine">{text}</blockquote>
          <div className="rubric">
            <div className="small muted">{t('learn.tickHonestly')}</div>
            {e.rubric.map((r, i) => (
              <label key={i} className="check">
                <input type="checkbox" checked={marks[i]} disabled={phase === 'done'} onChange={(ev) => setMarks(marks.map((m, j) => (j === i ? ev.target.checked : m)))} /> <span>{r}</span>
              </label>
            ))}
          </div>
          {phase === 'score' ? (
            <button
              className="btn primary"
              onClick={() => {
                recordExplain(k, score, e.rubric.length)
                setPhase('done')
              }}
            >
              {t('learn.saveScore', { score, of: e.rubric.length })}
            </button>
          ) : (
            <div className="predict-res ok" role="status">
              <strong className="feedback-heading"><Icon name="check" size={18} />{t('learn.scored', { score, of: e.rubric.length })}</strong> {score === e.rubric.length ? t('learn.fullMarks') : t('learn.compareModel')}
              <details open>
                <summary>{t('learn.model')}</summary>
                <Md text={e.model} />
              </details>
            </div>
          )}
        </>
      )}
    </div>
  )
}

const CONF = ['', 'conf.1', 'conf.2', 'conf.3', 'conf.4', 'conf.5'] as const
export function Confidence({ concept, title }: { concept: string; title: string }) {
  const prog = useProgress()
  const v = prog.confidence[concept] || 0
  return (
    <div className="confidence">
      <span className="conf-title">{title}</span>
      <span className="conf-dots" role="radiogroup" aria-label={t('learn.confidenceFor', { c: title })}>
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} role="radio" aria-checked={v === n} className={`dot ${n <= v ? 'on' : ''}`} title={t(CONF[n] as 'conf.1')} onClick={() => setConfidence(concept, n)} />
        ))}
      </span>
      <span className="conf-label muted small">{v ? t(CONF[v] as 'conf.1') : t('learn.rateYourself')}</span>
    </div>
  )
}
