import { useEffect, useMemo, useState } from 'react'
import { api, type ReviewCard } from '../lib/data'
import { useApp } from '../lib/app'
import { t } from '../lib/i18n'
import { MdInline } from '../lib/md'
import { grade, unlocked, useProgress } from '../lib/progress'
import { Icon } from './ui'

/** "Before you go": up to three due review cards from OTHER lessons the learner has already studied, mixed in at the
 * end of a lesson. Interleaved, spaced retrieval of earlier material; skippable and never blocks anything. */
export function RecallBreak({ lessonId }: { lessonId: string }) {
  const { lang } = useApp()
  const prog = useProgress()
  const [cards, setCards] = useState<ReviewCard[] | null>(null)
  const [shown, setShown] = useState<Record<string, boolean>>({})
  const [done, setDone] = useState<Record<string, boolean>>({})
  useEffect(() => {
    api.cards(lang).then(setCards, () => setCards([]))
  }, [lang])
  // chosen once per visit, so grading a card does not reshuffle the set
  const pick = useMemo(() => {
    if (!cards) return []
    const now = Date.now()
    return cards
      .filter((c) => c.ref !== lessonId && unlocked(c, prog) && (prog.cards[c.id]?.due ?? 0) <= now)
      .sort((a, b) => (prog.cards[a.id]?.due ?? 0) - (prog.cards[b.id]?.due ?? 0) || a.id.localeCompare(b.id))
      .filter((c, i, all) => all.findIndex((x) => x.ref === c.ref) === i) // one per lesson: mix topics
      .slice(0, 3)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cards, lessonId])
  if (!pick.length) return null
  return (
    <section className="recall" aria-labelledby="recall-h" data-testid="recall-break">
      <h3 id="recall-h">
        <Icon name="cards" size={16} /> {t('recall.title')}
      </h3>
      <p className="muted small">{t('recall.text')}</p>
      <ol className="recall-list">
        {pick.map((c) => (
          <li key={c.id} className={done[c.id] ? 'done' : ''}>
            <p className="recall-q">
              <MdInline text={c.q} /> <span className="muted small">· {c.title}</span>
            </p>
            {!shown[c.id] ? (
              <button className="linkish small" onClick={() => setShown({ ...shown, [c.id]: true })}>
                <Icon name="eye" size={16} /> {t('recall.show')}
              </button>
            ) : (
              <>
                <p className="recall-a">
                  <MdInline text={c.a} />
                </p>
                {done[c.id] ? (
                  <span className="small muted">{t('recall.saved', { n: Math.max(0, Math.round(((prog.cards[c.id]?.due ?? Date.now()) - Date.now()) / 86400000)) })}</span>
                ) : (
                  <span className="recall-grade" role="group" aria-label={t('recall.how')}>
                    <button className="btn sm" onClick={() => (grade(c.id, 0), setDone({ ...done, [c.id]: true }))}>
                      <Icon name="refresh" size={14} /> {t('recall.again')}
                    </button>
                    <button className="btn sm" onClick={() => (grade(c.id, 4), setDone({ ...done, [c.id]: true }))}>
                      <Icon name="check" size={14} /> {t('recall.knew')}
                    </button>
                  </span>
                )}
              </>
            )}
          </li>
        ))}
      </ol>
    </section>
  )
}
