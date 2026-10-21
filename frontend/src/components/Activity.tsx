// The building blocks that make each kind of activity recognisable by what it asks the learner to do:
import { radioKeys } from '../lib/radio'
//   Learn    read (a reading column, no frame)
//   Predict  guess, ungraded, skippable (a light inline row)
//   Check    answer and submit, then feedback about the chosen answer (one framed question)
//   Explore  manipulate a model (a wide workspace)
//   Practise run commands (an environment bar and a terminal)
//   Solve    investigate (an incident board)
// Colour (--act-*) only supports orientation; right and wrong always use --ok / --bad.
import { useEffect, useMemo, useRef, useState } from 'react'
import type { Predict } from '../lib/data'
import { t } from '../lib/i18n'
import { Md, MdInline } from '../lib/md'
import { displayOrder } from '../lib/order'
import { recordAnswer, recordGuess, useProgress } from '../lib/progress'
import { questionState } from '../lib/standing'
import { Icon } from './ui'
import { focusQuietly, reveal } from '../lib/reveal'

export type ActivityKind = 'learn' | 'show' | 'try' | 'predict' | 'check' | 'order' | 'reflect' | 'explore' | 'practise' | 'solve' | 'review' | 'summary'
export const KIND: Record<ActivityKind, { icon: string; label: string; verb: string }> = {
  learn: { icon: 'book', label: 'act.learn', verb: 'act.learnVerb' },
  show: { icon: 'terminal', label: 'act.show', verb: 'act.showVerb' },
  try: { icon: 'terminal', label: 'act.try', verb: 'act.tryVerb' },
  order: { icon: 'list', label: 'act.order', verb: 'act.orderVerb' },
  reflect: { icon: 'bulb', label: 'act.reflect', verb: 'act.reflectVerb' },
  predict: { icon: 'target', label: 'act.predict', verb: 'act.predictVerb' },
  check: { icon: 'check', label: 'act.check', verb: 'act.checkVerb' },
  explore: { icon: 'shapes', label: 'act.explore', verb: 'act.exploreVerb' },
  practise: { icon: 'terminal', label: 'act.practise', verb: 'act.practiseVerb' },
  solve: { icon: 'siren', label: 'act.solve', verb: 'act.solveVerb' },
  review: { icon: 'cards', label: 'act.review', verb: 'act.reviewVerb' },
  summary: { icon: 'flag', label: 'act.summary', verb: 'act.summaryVerb' },
}
const tk = (k: string) => t(k as 'act.learn')

/** The line above every activity: what kind of activity this is and what to do, in words (not only colour). */
export function ActivityHead({ kind, extra }: { kind: ActivityKind; extra?: string }) {
  const k = KIND[kind]
  return (
    <div className={`act-head act-${kind}`}>
      <span className="act-mark" aria-hidden="true">
        <Icon name={k.icon} size={15} />
      </span>
      <span className="act-label">{tk(k.label)}</span>
      <span className="act-verb">{extra || tk(k.verb)}</span>
    </div>
  )
}

/** Shows content the learner just revealed, using the shared policy in lib/reveal (start first, never the bottom edge). */
export const scrollNear = (el: Element | null) => reveal(el)

/** One graded question. Pick, then submit; feedback follows the choices. "Try again" is always offered after an
 * answer, right or wrong: it clears the choice and the feedback on screen and the next answer is recorded as the
 * latest attempt (the first one stays the honest record, lib/progress.ts). A later visit shows the latest answer on
 * record with its feedback, and "Try again": a question is never left finished and disabled. */
/** How long a revealed answer counts as seen: within this, a right answer after a wrong one is not counted as right. */
const SHOWN_FOR = 12 * 3600 * 1000
/** What the badge on a question answered before says, by its latest answer (lib/standing.ts). */
const PRIOR = { right: 'check.answeredRight', corrected: 'check.answeredCorrected', wrong: 'check.answeredBefore' } as const

export function CheckQuestion({ q, qid, n, of, onAnswered, source, restore = true }: { q: Predict; qid: string; n?: number; of?: number; onAnswered?: (ok: boolean) => void; source?: { label: string; onOpen: () => void }; /** false: always start unanswered (a "know this already?" session) */ restore?: boolean }) {
  const prog = useProgress()
  const prior = prog.predictions[qid]
  const priorBadge = useRef(prior).current // keep the metadata row stable while this question is answered
  // the latest answer on record, shown again on a later visit (older records without the choice start unanswered)
  const [restored] = useState(() => {
    const p = restore ? priorBadge?.latest.pick : undefined
    return p !== undefined && p >= 0 && p < q.choices.length ? p : null
  })
  const [pick, setPick] = useState<number | null>(restored)
  const [submitted, setSubmitted] = useState<number | null>(restored)
  const [earlier, setEarlier] = useState(restored !== null) // the feedback on screen is for an answer from an earlier visit
  const [said, setSaid] = useState('') // the always-mounted live region's text: set after submitting, so it is announced
  const res = useRef<HTMLDivElement>(null)
  const group = useRef<HTMLDivElement>(null)
  const acted = useRef<'' | 'submit' | 'retry'>('') // nothing moves focus on arrival, only the learner's own actions
  // when this mount last revealed the answer: a wrong answer shows the right one, also one shown again from before
  const wrongAt = useRef(restored !== null && restored !== q.answer ? Date.now() : 0)
  const order = useMemo(() => displayOrder(qid, q.choices.length), [qid, q.choices.length])
  useEffect(() => {
    // After checking, focus moves to feedback; after "Try again", to the choices.
    if (acted.current === 'submit' && submitted !== null) (scrollNear(res.current), focusQuietly(res.current))
    else if (acted.current === 'retry') focusQuietly(group.current?.querySelector<HTMLElement>('[role=radio][tabindex="0"]'))
  }, [submitted])
  const done = submitted !== null
  const ok = done && submitted === q.answer
  const submit = () => {
    if (pick === null) return
    acted.current = 'submit'
    setSubmitted(pick)
    setEarlier(false)
    setSaid(pick === q.answer ? t('check.right') : t('check.notQuite'))
    // A wrong answer puts the right one on screen. An answer within SHOWN_FOR of the latest revelation (here, or
    // recorded: a wrong answer, or a right one already given after a revelation) is recorded as shown, across
    // reloads and views of the lesson; later, it is recall.
    const recorded = !prior ? 0 : !prior.latest.ok ? prior.latest.at : prior.latest.shown ? prior.latest.revealedAt || prior.latest.at : 0
    const revealedAt = Math.max(wrongAt.current, recorded)
    const shown = revealedAt > 0 && Date.now() - revealedAt < SHOWN_FOR
    const right = pick === q.answer
    recordAnswer(qid, right, pick, shown, shown ? revealedAt : undefined)
    if (!right) wrongAt.current = Date.now()
    onAnswered?.(right && !shown)
  }
  /** A new attempt on screen: nothing recorded is erased. */
  const again = () => {
    acted.current = 'retry'
    setPick(null)
    setSubmitted(null)
    setEarlier(false)
    setSaid(t('ex.newAttempt'))
  }
  return (
    <div className={`check-q ${done ? (ok ? 'is-right' : 'is-wrong') : ''}`} data-testid="check">
      <div className="check-q-top">
        {of && of > 1 ? <span className="check-n">{t('check.nOf', { n: n || 1, of })}</span> : null}
        {priorBadge && <span className="check-prior" aria-hidden={done}>{t(PRIOR[questionState(priorBadge) as keyof typeof PRIOR])}</span>}
      </div>
      <div className="check-prompt">
        <Md text={q.prompt} />
      </div>
      <div className="check-choices" role="radiogroup" aria-label={t('check.choices')} onKeyDown={radioKeys} ref={group}>
        {order.map((i, d) => {
          const c = q.choices[i]
          const chosen = submitted === i
          const isAnswer = done && i === q.answer
          return (
            <div key={i} className={`check-choice-wrap ${chosen ? 'chosen' : ''}`}>
              <button
                role="radio"
                aria-checked={pick === i}
                tabIndex={pick === i || (pick === null && d === 0) ? 0 : -1}
                className={`check-choice ${pick === i ? 'on' : ''} ${isAnswer ? 'answer' : ''} ${chosen && !ok ? 'wrong' : ''}`}
                disabled={done}
                onClick={() => setPick(i)}
                data-testid="choice"
                data-choice={i}
              >
                <span className="choice-radio" aria-hidden="true">
                  {(isAnswer || pick === i) && <Icon name={chosen && !ok ? 'x' : 'check'} size={14} />}
                </span>
                <span className="choice-k" aria-hidden="true">
                  {String.fromCharCode(65 + d)}
                </span>
                <span className="choice-t">
                  <MdInline text={c} />
                  <span className="choice-answer-label" aria-hidden={!isAnswer}>{t('check.theAnswer', { k: String.fromCharCode(65 + d) })}</span>
                </span>
              </button>
            </div>
          )
        })}
      </div>
      <div className="check-actions">
        <button className="btn primary" disabled={pick === null || done} onClick={submit} data-testid="check-submit">
          {t('check.submit')}
        </button>
      </div>
      <div className="check-feedback-slot">
        {done && (
          <div className="check-after">
            <div className={`verdict ${ok ? 'ok' : 'bad'}`} ref={res} tabIndex={-1} data-testid="verdict">
              {earlier && <p className="ex-earlier" data-testid="check-earlier">{t('ex.earlierAnswer')}</p>}
              <strong className="feedback-heading"><Icon name={ok ? 'check' : 'x'} size={18} />{ok ? t('check.right') : t('check.notQuite')}</strong>
              {q.feedback?.[submitted] ? <Md text={q.feedback[submitted]} /> : !ok ? null : <Md text={q.explain} />}
              {!ok && q.answer !== null && (
                <div className="check-answer">
                  <span className="lbl">{t('check.theAnswer', { k: String.fromCharCode(65 + order.indexOf(q.answer)) })}</span>
                  {q.feedback?.[q.answer] ? <Md text={q.feedback[q.answer]} /> : <Md text={q.explain} />}
                </div>
              )}
              {q.feedback?.length && q.explain.trim() !== (q.feedback[q.answer ?? -1] || '').trim() ? (
                <div className="check-key">
                  <span className="lbl">{t('check.keyIdea')}</span>
                  <Md text={q.explain} />
                </div>
              ) : null}
            </div>
            <div className="check-actions">
              <TryAgain onClick={again} testid="check-again" />
              {!ok && source && (
                <button className="linkish small" onClick={source.onOpen}>
                  {t('check.reread', { part: source.label })}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
      <p className="sr-only" aria-live="polite" data-testid="check-live">{said}</p>
    </div>
  )
}

/** The one "Try again" control of the exercises (a new attempt of the same exercise; never a reset of progress). */
export function TryAgain({ onClick, testid }: { onClick: () => void; testid: string }) {
  return (
    <button type="button" className="btn ghost sm ex-again" onClick={onClick} data-testid={testid}>
      <Icon name="refresh" size={14} /> {t('check.again')}
    </button>
  )
}

/** An ungraded guess before seeing the answer. Never counts as evidence; skipping is fine and recorded as a skip.
 * Only the first guess is recorded (lib/progress.ts recordGuess); a later visit shows it again, and "Try again" lets
 * the learner choose again without recording it. */
export function Guess({ p, k, onDone, label }: { p: Predict; k: string; onDone?: () => void; label?: string }) {
  const prog = useProgress()
  const prior = useRef(prog.guesses[k]).current
  const open = !p.choices.length
  const [pick, setPick] = useState<number | null>(() => {
    const x = prior?.pick
    return x !== undefined && (open ? x === -1 : x >= 0 && x < p.choices.length) ? x : null
  })
  const [skipped, setSkipped] = useState(() => !!prior?.skipped)
  const [said, setSaid] = useState('')
  const gorder = useMemo(() => displayOrder(k, p.choices.length), [k, p.choices.length])
  const done = pick !== null || skipped
  const res = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const acted = useRef<'' | 'answer' | 'retry'>('') // a later visit shows the earlier guess without moving focus
  useEffect(() => {
    if (acted.current === 'answer' && done) (scrollNear(res.current), focusQuietly(res.current)) // the choices are disabled: keep focus in the activity
    else if (acted.current === 'retry' && !done) focusQuietly(box.current?.querySelector<HTMLElement>('.guess-choice, .guess-actions button'))
  }, [done])
  const choose = (i: number | null) => {
    acted.current = 'answer'
    if (i === null) setSkipped(true)
    else setPick(i)
    recordGuess(k, i)
    onDone?.()
    setSaid(i === null ? t('guess.skipped') : i >= 0 && p.answer !== null ? (i === p.answer ? t('guess.matched') : t('guess.differs', { k: String.fromCharCode(65 + gorder.indexOf(p.answer)) })) : t('guess.answerShown'))
  }
  const again = () => {
    acted.current = 'retry'
    setPick(null)
    setSkipped(false)
    setSaid(t('ex.newAttempt'))
  }
  return (
    <div className={`guess ${done ? 'done' : ''}`} data-testid="guess" ref={box}>
      <div className="guess-h">
        <Icon name="target" size={15} /> <span>{label || t('guess.label')}</span>
        <span className="guess-note">{t('guess.notScored')}</span>
        {prior && <span className="guess-note guess-prior" aria-hidden={done}>· {t('guess.before')}</span>}
      </div>
      <div className="guess-prompt">
        <Md text={p.prompt} />
      </div>
      {!open && (
        <div className="guess-choices">
          {gorder.map((i, d) => (
            <button
              key={i}
              data-choice={i}
              className={`guess-choice ${pick === i ? 'on' : ''} ${done && p.answer === i ? 'answer' : ''} ${done && pick === i && p.answer !== null && pick !== p.answer ? 'wrong' : ''}`}
              disabled={done}
              onClick={() => choose(i)}
            >
              <span className="choice-radio" aria-hidden="true">
                {(pick === i || (done && p.answer === i)) && <Icon name={pick === i && p.answer !== null && pick !== p.answer ? 'x' : 'check'} size={14} />}
              </span>
              <span className="choice-k" aria-hidden="true">{String.fromCharCode(65 + d)}</span>
              <span className="choice-t"><MdInline text={p.choices[i]} />
                <span className="choice-answer-label" aria-hidden={!(done && p.answer === i)}>{t('check.theAnswer', { k: String.fromCharCode(65 + d) })}</span>
              </span>
            </button>
          ))}
        </div>
      )}
      <div className="guess-actions">
        {open && (
          <button
            className="btn sm"
            disabled={done}
            onClick={() => choose(-1)}
          >
            {t('guess.thought')}
          </button>
        )}
        <button
          className="linkish small"
          disabled={done}
          onClick={() => choose(null)}
          data-testid="skip-guess"
        >
          {t('guess.skip')}
        </button>
      </div>
      <div className="guess-feedback-slot">
        {done && (
          <div className={`guess-res ${pick !== null && pick >= 0 && pick === p.answer ? 'ok' : 'off'}`} ref={res} tabIndex={-1}>
            {pick !== null && pick >= 0 && p.answer !== null && (
              <strong className={`feedback-heading ${pick === p.answer ? 'ok' : 'off'}`}><Icon name={pick === p.answer ? 'check' : 'info'} size={18} />{pick === p.answer ? t('guess.matched') : t('guess.differs', { k: String.fromCharCode(65 + gorder.indexOf(p.answer)) })} </strong>
            )}
            {pick !== null && pick >= 0 && p.feedback?.[pick] ? <Md text={p.feedback[pick]} /> : <Md text={p.explain} />}
          </div>
        )}
        {done && (
          <div className="guess-again-row">
            <TryAgain onClick={again} testid="guess-again" />
          </div>
        )}
      </div>
      <p className="sr-only" aria-live="polite">{said}</p>
    </div>
  )
}
