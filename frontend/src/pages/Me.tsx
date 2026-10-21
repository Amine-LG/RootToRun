import { useRef, useState, type ReactNode } from 'react'
import { SyncPanel } from '../components/AccountSync'
import { useCardCounts } from '../components/Shell'
import { toast } from '../components/Toast'
import { Bar, Callout, Icon, LabStatusPill } from '../components/ui'
import { conceptEvidence, courseOrder, evidenceLevel, type ConceptEvidence } from '../lib/evidence'
import { useApp } from '../lib/app'
import { t } from '../lib/i18n'
import { exportProgress, importProgress, labStatus, resetProgress, useProgress, type Progress } from '../lib/progress'
import { activityDone, checksOf, tallyChecks, verifiedNow } from '../lib/standing'
import type { Curriculum } from '../lib/data'
import { continueTarget } from '../lib/next'
import { usePlannedLesson } from '../lib/planned'
import { diagnosticHref, labHref, lessonHref, trackHref } from '../lib/urls'
import { trackProgress } from './Home'
import '../pages.css'

/** One fact about the learner's work: a number, what it counts, and (where there is a total) how far along it is. */
function Stat({ n, label, tone, frac }: { n: ReactNode; label: string; tone?: string; frac?: number }) {
  return (
    <div className={`stat-card ${tone || ''}`}>
      <strong>{n}</strong>
      <span>{label}</span>
      {frac !== undefined && <Bar value={frac} label={label} />}
    </div>
  )
}

const CONCEPT_ROWS = 8

/** Where a concept is taught and practised, with what the learner has done in each, linked to the page itself. */
function ConceptWhere({ cur, prog, e, id }: { cur: Curriculum; prog: Progress; e: ConceptEvidence; id: string }) {
  // which course each lesson or activity is in: a concept is often practised in a later course than it is taught in
  const course = (module: string) => cur.tracks.find((tr) => tr.modules.includes(module))?.title
  return (
    <div className="ev-where" id={id} data-testid="concept-where">
      <h4>{t('me.lessonsH')}</h4>
      <ul>
        {e.lessonIds.map((l) => (
          <li key={l}>
            <a href={lessonHref(l)}>{cur.lessons[l].title}</a>{' '}
            <span className="muted small">{course(cur.lessons[l].module) && `${course(cur.lessons[l].module)} · `}{prog.lessons[l]?.done ? t('me.lessonRead') : prog.lessons[l]?.skipped ? t('learn.skippedMark') : t('me.lessonOpen')}</span>
          </li>
        ))}
      </ul>
      {e.labIds.length > 0 && (
        <>
          <h4>{t('me.practiceH')}</h4>
          <ul>
            {e.labIds.map((id) => {
              const lab = cur.labs[id]
              const s = labStatus(prog.labs[id])
              return (
                <li key={id} data-testid="concept-activity">
                  <Icon name={lab.kind === 'incident' ? 'siren' : lab.kind === 'challenge' ? 'target' : 'flask'} size={14} /> <a href={labHref(id)}>{lab.title}</a>{' '}
                  {s === 'new' ? <span className="muted small">{t('me.notStarted')}</span> : <LabStatusPill s={s} />}
                  {/* completion is a fact once reached; the status beside it is what is true now (a later failed live check) */}
                  {activityDone(lab.kind, prog.labs[id]) && !['replayed', 'diagnosed', 'verified'].includes(s) && <span className="pill ok">{t('me.completed')}</span>}
                  <span className="ev-rule muted small">
                    {t(`me.kind.${lab.kind}` as 'me.kind.lab')}
                    {course(lab.module) && ` · ${course(lab.module)}`} · {t(`me.done.${lab.kind}` as 'me.done.lab')}
                  </span>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </div>
  )
}

export default function Me() {
  const { cur, meta } = useApp()
  const prog = useProgress()
  const { ready: due, fresh } = useCardCounts()
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad' | 'info'; text: string } | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)
  const [allConcepts, setAllConcepts] = useState(false)
  const [where, setWhere] = useState<string | null>(null) // the concept whose lessons and practice are listed
  const file = useRef<HTMLInputElement>(null)
  const resetBtn = useRef<HTMLButtonElement>(null)
  const route = cur?.routes?.find((r) => r.id === prog.route) || null
  const planned = usePlannedLesson(cur, prog, route)
  if (!cur) return null
  const labs = Object.values(cur.labs)
  // the course's Check questions only (typed commands and ordering tasks are recorded apart), read by lib/standing.ts
  const checks = tallyChecks(checksOf(cur, courseOrder(cur)), prog)

  // Evidence per concept, as separate facts: read, checked (latest answer right), practice completed, verified live.
  const concepts = Object.values(cur.concepts)
    .map((c) => ({ c, e: conceptEvidence(cur, prog, c.id) }))
    .filter(({ e }) => e.read || e.checksAnswered || e.begun || e.practised || e.verified)
    .sort((a, b) => b.e.checksAnswered - b.e.checksCorrect - (a.e.checksAnswered - a.e.checksCorrect))
  const shownConcepts = allConcepts ? concepts : concepts.slice(0, CONCEPT_ROWS)
  const target = continueTarget(cur, prog, route, planned)
  const lessonsTotal = Object.keys(cur.lessons).length
  const finishedLessons = Object.values(prog.lessons).filter((l) => l.done || l.skipped).length
  const practicable = labs.filter((l) => l.kind === 'lab')
  const practised = practicable.filter((l) => activityDone(l.kind, prog.labs[l.id])).length
  const verified = labs.filter((l) => verifiedNow(prog.labs[l.id])).length
  const tracks = cur.tracks.filter((tr) => trackProgress(cur, prog, tr.id).total > 0)

  return (
    <div className="page pg pg-me">
      <header className="pg-head">
        <div className="eyebrow">{t('me.eyebrow')}</div>
        <h1>{t('me.title')}</h1>
        <p className="pg-purpose">{t('me.purpose')}</p>
      </header>

      <section className="pg-now" aria-labelledby="me-now">
        <div className="pg-now-text">
          <div className="eyebrow">{t('me.nowEyebrow')}</div>
          {target ? (
            <>
              <h2 id="me-now">{target.title}</h2>
              <p>
                {t(`me.kind.${target.kind}` as 'me.kind.lesson')} · {t('me.lessonsRead', { n: finishedLessons, of: lessonsTotal })}
              </p>
            </>
          ) : (
            <>
              <h2 id="me-now">{t('me.nowDone')}</h2>
              <p>{t('me.nowDoneText')}</p>
            </>
          )}
          {due > 0 && (
            <p>
              <a className="pg-now-link" href="/review">
                {t('me.dueLink', { n: due, fresh })}
              </a>
            </p>
          )}
        </div>
        <a className="btn primary lg" href={target ? target.href : trackHref('practice')}>
          {target ? t('me.continueShort') : t('me.practiseNext')} <Icon name="arrow" size={16} />
        </a>
      </section>

      <section className="pg-sec" aria-labelledby="me-ev">
        <h2 id="me-ev">{t('me.evTitle')}</h2>
        <p className="pg-sub">{t('me.evSub')}</p>
        <div className="me-grid">
          <div className="me-group" role="group" aria-labelledby="me-g-read">
            <h3 id="me-g-read">{t('me.groupRead')}</h3>
            <Stat n={finishedLessons} label={t('me.lessonsDone', { n: lessonsTotal })} frac={lessonsTotal ? finishedLessons / lessonsTotal : 0} />
            <Stat n={checks.answered ? `${checks.right}/${checks.answered}` : '–'} label={t(checks.corrected ? 'me.checksLatestShown' : 'me.checksLatest', { shown: checks.corrected })} />
            <Stat n={checks.answered ? `${checks.firstTry}/${checks.answered}` : '–'} label={t('me.checksFirst')} />
          </div>
          <div className="me-group" role="group" aria-labelledby="me-g-practised">
            <h3 id="me-g-practised">{t('me.groupPractised')}</h3>
            <Stat n={practised} label={t('me.labsPractised')} frac={practicable.length ? practised / practicable.length : 0} />
            <Stat n={labs.filter((l) => l.kind === 'incident' && activityDone(l.kind, prog.labs[l.id])).length} label={t('me.incidents')} />
            <Stat n={Object.keys(prog.cmds).length} label={t('me.commands')} />
          </div>
          <div className="me-group" role="group" aria-labelledby="me-g-live">
            <h3 id="me-g-live">{t('me.groupLive')}</h3>
            <Stat n={verified} label={t('me.verified')} tone={verified ? 'ok' : ''} />
            <p className="me-note">{t(meta?.mode === 'cluster' ? 'me.liveHintCluster' : 'me.liveHint')}</p>
          </div>
        </div>
      </section>

      {tracks.length > 0 && (
        <section className="pg-sec" aria-labelledby="me-tracks">
          <h2 id="me-tracks">{t('me.tracks')}</h2>
          <ul className="me-tracks">
            {tracks.map((tr) => {
              const p = trackProgress(cur, prog, tr.id)
              const diag = cur.diagnostics?.[tr.id]?.track === tr.id
              return (
                <li key={tr.id} className={`me-track t-${tr.accent || 'blue'}`}>
                  <a className="me-track-name" href={trackHref(tr.id)}>
                    <span className="terr-dot" aria-hidden="true" /> {tr.title}
                  </a>
                  <Bar value={p.total ? p.done / p.total : 0} label={tr.title} />
                  <span className="me-track-n">{t('me.trackN', { n: p.done, of: p.total })}</span>
                  {diag && (
                    <a className="me-track-diag" href={diagnosticHref(tr.id)}>
                      {prog.diagnostics[tr.id]?.finished ? t('me.diagTaken', { date: new Date(prog.diagnostics[tr.id].finished!).toLocaleDateString() }) : t('diag.cardTake')}
                    </a>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      )}

      <section className="pg-sec" aria-labelledby="me-map">
        <h2 id="me-map">{t('me.map')}</h2>
        <p className="pg-sub">{t('me.mapHelp')}</p>
        {concepts.length === 0 ? (
          <p className="pg-empty">{t('me.mapEmpty')}</p>
        ) : (
          <>
            <table className="evidence-table">
              <thead>
                <tr>
                  <th>{t('me.concept')}</th>
                  <th>{t('me.evRead')}</th>
                  <th>{t('me.evChecks')}</th>
                  <th>{t('me.evPractised')}</th>
                  <th>{t('me.evVerified')}</th>
                </tr>
              </thead>
              <tbody>
                {shownConcepts.flatMap(({ c, e }) => {
                  const weak = e.checksAnswered > e.checksCorrect
                  // the concept links to where it is taught: the first lesson not finished yet, else the first
                  const lesson = e.lessonIds.find((l) => !(prog.lessons[l]?.done || prog.lessons[l]?.skipped)) || e.lessonIds[0]
                  const open = where === c.id
                  const panel = `ev-where-${c.id.replace(/[^\w-]/g, '-')}`
                  return [
                    <tr key={c.id} className={`ev-${evidenceLevel(e)}`} data-testid="concept-row" data-concept={c.id}>
                      <th scope="row">
                        {lesson ? <a href={lessonHref(lesson)}>{c.title}</a> : c.title}
                        {weak && <span className="ev-flag">{t('me.toReview')}</span>}
                        <button className="linkish small ev-where-btn" aria-expanded={open} aria-controls={open ? panel : undefined} onClick={() => setWhere(open ? null : c.id)} data-testid="concept-where-btn">
                          {t('me.where')} <span className="sr-only">{t('me.whereFor', { concept: c.title })}</span>
                        </button>
                      </th>
                      <td data-label={t('me.evRead')}>{e.lessons ? `${e.read}/${e.lessons}` : '–'}</td>
                      <td data-label={t('me.evChecks')} className={weak ? 'weak' : ''}>
                        {e.checks ? `${e.checksCorrect}/${e.checks}` : '–'}
                      </td>
                      <td data-label={t('me.evPractised')}>{e.labs ? `${e.practised}/${e.labs}` : '–'}</td>
                      <td data-label={t('me.evVerified')}>{e.labs ? `${e.verified}/${e.labs}` : '–'}</td>
                    </tr>,
                    open && (
                      <tr key={`${c.id}-where`} className="ev-where-row">
                        <td colSpan={5}>
                          <ConceptWhere cur={cur} prog={prog} e={e} id={panel} />
                        </td>
                      </tr>
                    ),
                  ]
                })}
              </tbody>
            </table>
            {concepts.length > CONCEPT_ROWS && (
              <button className="btn sm ghost me-more" onClick={() => setAllConcepts(!allConcepts)} aria-expanded={allConcepts}>
                {allConcepts ? t('me.showFewer') : t('me.showAll', { n: concepts.length })}
              </button>
            )}
          </>
        )}
      </section>

      <section className="pg-sec" aria-labelledby="me-data">
        <h2 id="me-data">{t('me.data')}</h2>
        <div className="pg-card me-data">
          <p>{t('me.dataHelp')}</p>
          {meta?.accounts && meta.mode !== 'static' && <p className="small muted">{t('sync.localHelp')}</p>}
          <div className="me-actions">
            <button
              className="btn"
              onClick={() => {
                const a = document.createElement('a')
                a.href = URL.createObjectURL(new Blob([exportProgress()], { type: 'application/json' }))
                a.download = `roottorun-progress-${new Date().toISOString().slice(0, 10)}.json`
                a.click()
              }}
            >
              <Icon name="arrow" size={14} /> {t('me.export')}
            </button>
            <button className="btn" onClick={() => file.current?.click()}>
              {t('me.import')}
            </button>
            <input
              ref={file}
              type="file"
              accept="application/json"
              hidden
              onChange={async (e) => {
                const f = e.target.files?.[0]
                if (!f) return
                try {
                  const r = importProgress(await f.text())
                  const text = t('me.importedN', { lessons: r.lessons, answers: r.answers, labs: r.labs })
                  setMsg(r.saved ? { tone: 'ok', text } : { tone: 'bad', text: `${text} ${t('me.notSaved')}` })
                } catch (err) {
                  setMsg({ tone: 'bad', text: `${t('me.importFailed')} ${String((err as Error).message)}` })
                }
                e.target.value = ''
              }}
            />
            {!confirmReset ? (
              <button ref={resetBtn} className="btn ghost danger me-reset" onClick={() => setConfirmReset(true)} data-testid="reset" aria-describedby="me-reset-scope">
                {t('me.reset')}
              </button>
            ) : (
              <span className="me-confirm" role="group" aria-label={t('me.reset')}>
                <span>{t('me.resetConfirm')}</span>
                <button
                  className="btn danger"
                  data-testid="reset-confirm"
                  onClick={() => {
                    const r = resetProgress()
                    setConfirmReset(false)
                    setMsg(r.ok ? { tone: 'ok', text: t('me.resetDone') } : { tone: 'bad', text: t('me.resetFailed') })
                    if (r.ok) toast(t('me.resetDone'), '', 'ok')
                    requestAnimationFrame(() => resetBtn.current?.focus()) // the confirm group is gone; keep keyboard focus here
                  }}
                >
                  {t('me.resetYes')}
                </button>
                <button
                  className="btn ghost"
                  autoFocus // the button that opened this group is gone; the safe choice takes focus
                  onClick={() => {
                    setConfirmReset(false)
                    requestAnimationFrame(() => resetBtn.current?.focus())
                  }}
                >
                  {t('ui.cancel')}
                </button>
              </span>
            )}
          </div>
          <p className="small muted" id="me-reset-scope">{t('me.resetScope')}</p>
          {msg && (
            <Callout tone={msg.tone} role="status">
              {msg.text}
            </Callout>
          )}
        </div>
        <div className="pg-sync">
          <SyncPanel />
        </div>
      </section>
    </div>
  )
}
