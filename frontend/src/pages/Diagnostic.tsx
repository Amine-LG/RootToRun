import { useEffect, useMemo, useRef, useState } from 'react'
import { radioKeys } from '../lib/radio'
import { PageActions } from '../components/Contribute'
import { PageBar } from '../components/PageHead'
import { Icon } from '../components/ui'
import { useApp } from '../lib/app'
import { api, type Diagnostic as DiagnosticData } from '../lib/data'
import { classify, CONF_GUESS, moduleOf, ordered, studyOrder, type TargetResult, type Verdict } from '../lib/diagnostic'
import { t } from '../lib/i18n'
import { Md, MdInline } from '../lib/md'
import { diagAnswer, diagClear, diagFinish, diagStart, getProgress, useProgress } from '../lib/progress'
import { focusQuietly, reveal } from '../lib/reveal'
import { itemHref, trackHref } from '../lib/urls'
import '../pages.css'

const CONF = ['diag.conf0', 'diag.conf1', 'diag.conf2'] as const

/** A track-wide diagnostic: answer with a confidence level, then get a study plan. Nothing is marked as done. */
export default function Diagnostic({ track }: { track: string }) {
  const { cur, lang } = useApp()
  const prog = useProgress()
  const [d, setD] = useState<DiagnosticData | null>(null)
  const [err, setErr] = useState(false)
  useEffect(() => {
    api.diagnostic(track, lang).then(setD, () => setErr(true))
  }, [track, lang])
  const rec = prog.diagnostics[track]
  const tr = cur?.tracks.find((x) => x.id === track)
  if (err || (cur && !tr))
    return (
      <div className="page pg pg-diag">
        <p>{t('diag.missing')}</p>
        <a href="/learn">{t('learn.allPaths')}</a>
      </div>
    )
  if (!cur || !d || !tr) return null
  return (
    <div className={`page pg pg-diag diagnostic t-${tr.accent || 'blue'}`}>
      <PageBar actions={<PageActions ctx={{ type: 'diagnostic', id: d.track, title: d.title, area: tr.title, source: d.source }} />}>
        <a className="back terr-back" href={trackHref(track)}>
          <Icon name="back" size={15} /> <span className="terr-dot" aria-hidden="true" /> {tr.title}
        </a>
      </PageBar>
      <header className="pg-head">
        <div className="eyebrow">{t('diag.eyebrow')}</div>
        <h1>{d.title}</h1>
        {!rec && <p className="pg-purpose">{t('diag.purpose')}</p>}
      </header>
      {!rec ? <Intro d={d} onStart={() => diagStart(track)} /> : rec.finished ? <Results d={d} /> : <Quiz d={d} />}
    </div>
  )
}

function Intro({ d, onStart }: { d: DiagnosticData; onStart: () => void }) {
  return (
    <section className="dgq-intro" data-testid="diag-intro">
      <Md text={d.intro} />
      <ul className="diag-facts">
        <li>
          <Icon name="clock" size={18} />
          <span>{t('diag.factCount', { n: d.items.length, min: d.minutes })}</span>
        </li>
        <li>
          <Icon name="target" size={18} />
          <span>{t('diag.factConfidence')}</span>
        </li>
        <li>
          <Icon name="shield" size={18} />
          <span>{t('diag.factNothingDone')}</span>
        </li>
      </ul>
      <button className="btn primary lg" onClick={onStart} data-testid="diag-start">
        {t('diag.start')} <Icon name="arrow" size={16} />
      </button>
    </section>
  )
}

function Quiz({ d }: { d: DiagnosticData }) {
  const { cur } = useApp()
  const prog = useProgress()
  const rec = prog.diagnostics[d.track]!
  const items = useMemo(() => ordered(cur!, d), [cur, d])
  const firstOpen = Math.max(0, items.findIndex((it) => !rec.answers[it.id]))
  const [at, setAt] = useState(firstOpen === -1 ? items.length - 1 : firstOpen)
  const it = items[Math.min(at, items.length - 1)]
  const prior = rec.answers[it.id]
  const [pick, setPick] = useState<number | null>(prior ? prior.pick : null)
  const [conf, setConf] = useState<number | null>(prior ? prior.conf : null)
  const card = useRef<HTMLElement>(null)
  const head = useRef<HTMLDivElement>(null)
  const moved = useRef(false)
  useEffect(() => focusQuietly(head.current), [])
  useEffect(() => {
    if (moved.current) {
      reveal(card.current)
      focusQuietly(head.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [at])
  const mid = moduleOf(cur!, d.track, it.targets[0])
  const mtitle = cur!.modules.find((m) => m.id === mid)?.title
  const answeredN = items.filter((x) => rec.answers[x.id]).length
  const go = (n: number) => {
    moved.current = true
    // the new question's answer is set in the same update as the question itself: reset in an effect after the
    // render, it erased a choice clicked in between (the next question was already on screen)
    const a = getProgress().diagnostics[d.track]?.answers[items[Math.min(n, items.length - 1)].id]
    setPick(a ? a.pick : null)
    setConf(a ? a.conf : null)
    setAt(n)
  }
  const next = (p: number, c: number) => {
    diagAnswer(d.track, it.id, { pick: p, conf: c as 0 | 1 | 2, ok: p === it.answer })
    if (at + 1 < items.length) go(at + 1)
    else diagFinish(d.track)
  }
  const ready = pick !== null && (pick === -1 || conf !== null)
  return (
    <section className="dgq" ref={card} aria-labelledby="diag-q-n" data-testid="diag-question">
      <div className="dgq-top" ref={head} tabIndex={-1}>
        <span id="diag-q-n">{t('diag.qOf', { n: at + 1, of: items.length })}</span>
        {mtitle && <span className="dgq-module">{mtitle}</span>}
      </div>
      <div className="dgq-bar" aria-hidden="true">
        <span style={{ width: `${(answeredN / items.length) * 100}%` }} />
      </div>
      <div className="dgq-body" key={it.id}>
        <div className="check-prompt">
          <Md text={it.prompt} />
        </div>
        {it.evidence && (
          <pre className="diag-evidence" tabIndex={0} aria-label={t('diag.evidence')}>
            <code>{it.evidence.replace(/\n$/, '')}</code>
          </pre>
        )}
        <div className="check-choices" role="radiogroup" aria-label={t('check.choices')} onKeyDown={radioKeys}>
          {it.choices.map((c, i) => (
            <button key={i} role="radio" aria-checked={pick === i} tabIndex={pick === i || (pick === null && i === 0) ? 0 : -1} className={`check-choice ${pick === i ? 'on' : ''}`} onClick={() => setPick(i)} data-testid="diag-choice">
              <span className="choice-radio" aria-hidden="true">{pick === i && <Icon name="check" size={14} />}</span>
              <span className="choice-k" aria-hidden="true">
                {String.fromCharCode(65 + i)}
              </span>
              <span className="choice-t">
                <MdInline text={c} />
              </span>
            </button>
          ))}
          <button role="radio" aria-checked={pick === -1} tabIndex={pick === -1 ? 0 : -1} className={`check-choice idk ${pick === -1 ? 'on' : ''}`} onClick={() => setPick(-1)} data-testid="diag-idk">
            <span className="choice-radio" aria-hidden="true">{pick === -1 && <Icon name="check" size={14} />}</span>
            <span className="choice-k" aria-hidden="true">?</span>
            <span className="choice-t">{t('diag.idk')}</span>
          </button>
        </div>
        <div className="dgq-conf-slot">
          {pick !== null && pick >= 0 && (
            <div className="diag-conf" role="radiogroup" aria-label={t('diag.howSure')} onKeyDown={radioKeys}>
              <span className="small">{t('diag.howSure')}</span>
              {CONF.map((k, i) => (
                <button key={k} role="radio" aria-checked={conf === i} tabIndex={conf === i || (conf === null && i === 0) ? 0 : -1} className={`chip ${conf === i ? 'on' : ''}`} onClick={() => setConf(i)} data-testid={`diag-conf-${i}`}>
                  {t(k)}
                </button>
              ))}
            </div>
          )}
          {pick === -1 && <p className="dgq-idk small">{t('diag.idkHint')}</p>}
        </div>
      </div>
      <div className="dgq-actions">
        {at > 0 && (
          <button className="btn ghost" onClick={() => go(at - 1)} data-testid="diag-back">
            <Icon name="back" size={15} /> {t('diag.prev')}
          </button>
        )}
        <button className="btn primary" disabled={!ready} onClick={() => next(pick!, pick === -1 ? CONF_GUESS : conf!)} data-testid="diag-next">
          {at + 1 < items.length ? t('diag.next') : t('diag.finish')}
        </button>
        {answeredN > 0 && (
          <button className="linkish small" onClick={() => diagFinish(d.track)} data-testid="diag-stop">
            {t('diag.stopNow', { n: answeredN })}
          </button>
        )}
      </div>
    </section>
  )
}

const targetTitle = (cur: ReturnType<typeof useApp>['cur'], id: string) => cur?.lessons[id]?.title || cur?.labs[id]?.title || id
const targetHref = (_cur: ReturnType<typeof useApp>['cur'], id: string) => itemHref(id)
const VERDICT_PILL: Record<Verdict, string> = { study: 'warn', review: 'info', shown: 'ok', partial: 'muted', unassessed: 'muted' }

export function why(r: TargetResult) {
  if (r.confidentWrong) return t('diag.whyConfident')
  if (r.missed) return t('diag.whyMissed', { n: r.missed, of: r.items.length })
  if (r.guessed) return t('diag.whyGuessed', { n: r.guessed })
  if (r.verdict === 'partial') return t('diag.whyPartial', { n: r.right, of: r.items.length })
  return t('diag.whyShown', { n: r.right })
}

function Results({ d }: { d: DiagnosticData }) {
  const { cur } = useApp()
  const prog = useProgress()
  const rec = prog.diagnostics[d.track]!
  const res = useMemo(() => classify(cur!, d, rec), [cur, d, rec])
  const items = useMemo(() => ordered(cur!, d), [cur, d])
  const resultsHead = useRef<HTMLHeadingElement>(null)
  useEffect(() => focusQuietly(resultsHead.current), [])
  const all = res.modules.flatMap((m) => m.targets)
  const study = studyOrder(res)
  const review = all.filter((r) => r.verdict === 'review')
  const shown = all.filter((r) => r.verdict === 'shown')
  const partial = all.filter((r) => r.verdict === 'partial')
  const unassessed = all.filter((r) => r.verdict === 'unassessed')
  const list = (rs: TargetResult[], testid: string) => (
    <ul className="diag-list" data-testid={testid}>
      {rs.map((r) => (
        <li key={r.id}>
          <a href={targetHref(cur, r.id)}>{targetTitle(cur, r.id)}</a>
          <span className="dr-why">{why(r)}</span>
        </li>
      ))}
    </ul>
  )
  const retake = () => {
    diagClear(d.track)
    diagStart(d.track)
  }
  return (
    <section className="dr" data-testid="diag-results">
      <div className="dr-summary">
        <h2 tabIndex={-1} ref={resultsHead}>{t('diag.resultsTitle')}</h2>
        <p className="dr-score" role="status">
          {t('diag.score', { right: res.right, answered: res.answered })}
          {res.answered < res.total && <> · {t('diag.unanswered', { n: res.total - res.answered })}</>}
        </p>
        <p className="dr-note">{t('diag.notDone')}</p>
        <div className="dr-actions">
          {study[0] && (
            <a className="btn primary" href={targetHref(cur, study[0].id)} data-testid="diag-first">
              {t('diag.startWith', { title: targetTitle(cur, study[0].id) })} <Icon name="arrow" size={16} />
            </a>
          )}
          <a className="btn" href={trackHref(d.track)}>
            {t('diag.toPath')}
          </a>
          <button className="btn ghost" onClick={retake} data-testid="diag-retake">
            {t('diag.retake')}
          </button>
        </div>
      </div>

      <h2 className="dr-h">{t('diag.planTitle')}</h2>
      {study.length > 0 && (
        <div className="dr-group dr-study">
          <h3>{t('diag.studyTitle')}</h3>
          <p>{t('diag.studyText')}</p>
          {list(study, 'diag-study')}
        </div>
      )}
      {review.length > 0 && (
        <div className="dr-group dr-review">
          <h3>{t('diag.reviewTitle')}</h3>
          <p>{t('diag.reviewText')}</p>
          {list(review, 'diag-review')}
        </div>
      )}
      {res.practise.length > 0 && (
        <div className="dr-group dr-practise">
          <h3>{t('diag.practiseTitle')}</h3>
          <ul className="diag-list">
            {res.practise.map((id) => (
              <li key={id}>
                <a href={targetHref(cur, id)}>{targetTitle(cur, id)}</a>
              </li>
            ))}
          </ul>
        </div>
      )}
      {partial.length > 0 && (
        <div className="dr-group dr-partial">
          <h3>{t('diag.partialTitle')}</h3>
          <p>{t('diag.partialText')}</p>
          {list(partial, 'diag-partial')}
        </div>
      )}
      {shown.length > 0 && (
        <div className="dr-group dr-shown">
          <h3>{t('diag.shownTitle')}</h3>
          <p>{t('diag.shownText')}</p>
          {list(shown, 'diag-shown')}
        </div>
      )}
      {unassessed.length > 0 && <p className="dr-note">{t('diag.unassessed', { n: unassessed.length })}</p>}

      <h2 className="dr-h">{t('diag.modulesTitle')}</h2>
      <div className="dr-modules">
        {res.modules.map((m) => (
          <div key={m.id} className="dr-mod">
            <div className="dr-mod-h">
              <strong>{m.title}</strong>
              <span>{t('diag.modScore', { right: m.right, total: m.total })}</span>
            </div>
            <div className="dgq-bar" aria-hidden="true">
              <span style={{ width: `${m.total ? (m.right / m.total) * 100 : 0}%` }} />
            </div>
            <div className="dr-tags">
              {m.targets.map((r) => (
                <a key={r.id} href={targetHref(cur, r.id)} className={`pill ${VERDICT_PILL[r.verdict]}`} title={why(r)}>
                  {targetTitle(cur, r.id)} · {t(`diag.v.${r.verdict}`)}
                </a>
              ))}
            </div>
          </div>
        ))}
      </div>

      <details className="more diag-answers">
        <summary>{t('diag.answersTitle')}</summary>
        <ol>
          {items.map((it) => {
            const a = rec.answers[it.id]
            return (
              <li key={it.id} className={a ? (a.ok ? 'ok' : 'bad') : ''}>
                <Md text={it.prompt} />
                {it.evidence && (
                  <pre className="diag-evidence" tabIndex={0} aria-label={t('diag.evidence')}>
                    <code>{it.evidence.replace(/\n$/, '')}</code>
                  </pre>
                )}
                <p className="small">
                  <strong>{t('diag.yourAnswer')}</strong>{' '}
                  {!a ? t('diag.notAnswered') : a.pick < 0 ? t('diag.idk') : <MdInline text={`${String.fromCharCode(65 + a.pick)}. ${it.choices[a.pick]}`} />}
                  {a && a.pick >= 0 && <span className="muted"> ({t(CONF[a.conf])})</span>}
                </p>
                {(!a || !a.ok) && (
                  <p className="small">
                    <strong>{t('diag.correct')}</strong> <MdInline text={`${String.fromCharCode(65 + it.answer)}. ${it.choices[it.answer]}`} />
                  </p>
                )}
                {a && a.pick >= 0 && it.feedback[a.pick] && <Md className="small" text={it.feedback[a.pick]} />}
                <div className="check-key small">
                  <span className="lbl">{t('check.keyIdea')}</span> <Md text={it.explain} />
                </div>
                <p className="small">
                  {it.targets.map((x, i) => (
                    <span key={x}>
                      {i ? ' · ' : ''}
                      <a href={targetHref(cur, x)}>{targetTitle(cur, x)}</a>
                    </span>
                  ))}
                </p>
              </li>
            )
          })}
        </ol>
      </details>
    </section>
  )
}
