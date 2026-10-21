import { useEffect, useMemo, useRef, useState } from 'react'
import { Bar, Callout, Empty, Icon, PageSkeleton } from '../components/ui'
import { api, type ReviewCard } from '../lib/data'
import { useApp, useLoad } from '../lib/app'
import { getLang, t } from '../lib/i18n'
import { Md } from '../lib/md'
import { grade, useProgress } from '../lib/progress'
import { cardQueue, questionState } from '../lib/standing'
import { labHref, lessonHref } from '../lib/urls'
import '../pages.css'

/** Questions whose latest answer was wrong (lib/standing.ts: one corrected since is no longer outstanding): retrieval
 *  practice where it is most useful, linked to the exact Check. */
function Revisit() {
  const { cur } = useApp()
  const prog = useProgress()
  if (!cur) return null
  const items = Object.values(cur.lessons).flatMap((l) =>
    (l.checks || []).filter((q) => questionState(prog.predictions[q]) === 'wrong').map((q) => ({ lesson: l, after: l.check_after?.[q] })),
  )
  if (!items.length) return null
  const seen = new Set<string>()
  const unique = items.filter((i) => {
    const k = `${i.lesson.id}|${i.after}`
    return seen.has(k) ? false : (seen.add(k), true)
  })
  return (
    <section className="rev-again" data-testid="revisit" aria-labelledby="rev-again-h">
      <h2 id="rev-again-h">{t('rev.revisitTitle')}</h2>
      <p>{t('rev.revisitText2', { n: items.length })}</p>
      <ul>
        {unique.map((i) => (
          <li key={`${i.lesson.id}|${i.after}`}>
            <a href={`${lessonHref(i.lesson.id)}${i.after ? `?a=${encodeURIComponent(`check:${i.after}`)}` : '?a=checks'}`}>{i.lesson.title}</a>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** "in 3 hours", "tomorrow": when the next card comes back, in the learner's language. */
function whenDue(at: number, now: number) {
  const f = new Intl.RelativeTimeFormat(getLang(), { numeric: 'auto' })
  const minutes = Math.max(1, Math.round((at - now) / 60000))
  if (minutes < 60) return f.format(minutes, 'minute')
  const hours = Math.round(minutes / 60)
  return hours < 24 ? f.format(hours, 'hour') : f.format(Math.round(hours / 24), 'day')
}

export default function Review() {
  const { lang } = useApp()
  const prog = useProgress()
  const { data } = useLoad(() => api.cards(lang), [lang])
  const [cram, setCram] = useState(false)
  const [flip, setFlip] = useState(false)
  const [doneNow, setDoneNow] = useState(0)
  const [skip, setSkip] = useState<Set<string>>(new Set())
  const base = useRef(0) // answers given before "review everything" started, so its progress bar starts empty
  const answerBox = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (flip) answerBox.current?.focus({ preventScroll: true }) // the "show" button is gone; the answer is read next
  }, [flip])

  const now = Date.now()
  // the same reading as the Review tab's count and the home page (lib/standing.ts): new cards and cards due again
  const { deck, fresh, again, ready: due } = useMemo(() => cardQueue(data || [], prog, now), [data, prog]) // eslint-disable-line react-hooks/exhaustive-deps
  const queue = (cram ? deck : due).filter((c) => !skip.has(c.id))
  const card: ReviewCard | undefined = queue[0]
  if (!data) return <div className="page"><PageSkeleton /></div>

  const learned = deck.filter((c) => (prog.cards[c.id]?.reps ?? 0) >= 2).length
  const nextDue = Math.min(Infinity, ...deck.map((c) => prog.cards[c.id]?.due ?? 0).filter((d) => d > now))
  const session = doneNow - base.current
  function answer(q: 0 | 3 | 4 | 5) {
    if (!card) return
    grade(card.id, q)
    if (cram) setSkip(new Set(skip).add(card.id))
    setFlip(false)
    setDoneNow(doneNow + 1)
    // keyboard continuity: the next card's "show answer" is where focus goes, not the page footer
    // (the new question is read first, and the next Tab reaches its "show answer" button)
    requestAnimationFrame(() => (document.querySelector<HTMLElement>('[data-testid=fc-q]') || document.querySelector<HTMLElement>('.review h1'))?.focus())
  }

  return (
    <div className="page review pg pg-review">
      <header className="pg-head">
        <div className="eyebrow">{t('rev.eyebrow')}</div>
        <h1 tabIndex={-1}>{t('rev.title')}</h1>
        <p className="pg-purpose">{t('rev.lede')}</p>
      </header>

      {deck.length > 0 && (
        <div className="rev-stats">
          <div className="rev-due" data-testid="rev-new">
            <strong>{fresh.length}</strong>
            <span>{t('rev.new')}</span>
          </div>
          <div className="rev-due" data-testid="rev-again">
            <strong>{again.length}</strong>
            <span>{t('rev.dueAgain')}</span>
          </div>
          <div>
            <strong>{deck.length}</strong>
            <span>{t('rev.inDeck')}</span>
          </div>
          <div>
            <strong>{learned}</strong>
            <span>{t('rev.learned')}</span>
          </div>
        </div>
      )}
      {deck.length > 0 && <p className="rev-what" data-testid="rev-what">{t('rev.whatCards')}</p>}

      {deck.length === 0 ? (
        <Empty icon="lock">
          <p>{t('rev.empty')}</p>
          <a className="btn primary" href="/learn">
            {t('home.start')}
          </a>
        </Empty>
      ) : card ? (
        <div className="flashcard-wrap">
          <div className="rev-progress">
            <span>{t('rev.left', { n: queue.length })}</span>
            <Bar value={session / Math.max(1, session + queue.length)} label={t('rev.progress')} />
          </div>
          <div className={`flashcard ${flip ? 'flipped' : ''}`} key={card.id}>
            <div className="fc-src">
              <Icon name={card.source === 'lesson' ? 'book' : card.source === 'incident' ? 'siren' : 'flask'} size={14} />
              <a href={card.source === 'lesson' ? lessonHref(card.ref) : labHref(card.ref)}>{card.title}</a>
            </div>
            <div className="fc-q" tabIndex={-1} data-testid="fc-q">
              <Md text={card.q} />
            </div>
            {flip ? (
              <div className="fc-a" ref={answerBox} tabIndex={-1}>
                <Md text={card.a} />
              </div>
            ) : (
              <button className="btn primary lg" onClick={() => setFlip(true)} data-testid="flip">
                <Icon name="eye" size={18} /> {t('rev.show')}
              </button>
            )}
          </div>
          {flip ? (
            <div className="grades" role="group" aria-label={t('rev.how')}>
              <button className="grade again" onClick={() => answer(0)}>
                <Icon name="refresh" size={16} />
                {t('rev.again')}
                <small>{t('rev.againHint')}</small>
              </button>
              <button className="grade hard" onClick={() => answer(3)}>
                <Icon name="clock" size={16} />
                {t('rev.hard')}
                <small>{t('rev.hardHint')}</small>
              </button>
              <button className="grade good" onClick={() => answer(4)} data-testid="grade-good">
                <Icon name="check" size={16} />
                {t('rev.good')}
                <small>{t('rev.goodHint')}</small>
              </button>
              <button className="grade easy" onClick={() => answer(5)}>
                <Icon name="check" size={16} />
                {t('rev.easy')}
                <small>{t('rev.easyHint')}</small>
              </button>
            </div>
          ) : (
            <p className="rev-honest">{t('rev.honest')}</p>
          )}
        </div>
      ) : (
        <Callout tone="ok" title={t('rev.allDone', { n: doneNow })}>
          <p>{t('rev.allDoneText')}</p>
          {nextDue !== Infinity && <p className="rev-next">{t('rev.nextDue', { when: whenDue(nextDue, now) })}</p>}
          <button
            className="btn sm"
            onClick={() => {
              base.current = doneNow
              setCram(true)
              setSkip(new Set())
            }}
          >
            {t('rev.cram', { n: deck.length })}
          </button>
        </Callout>
      )}
      <Revisit />
    </div>
  )
}
