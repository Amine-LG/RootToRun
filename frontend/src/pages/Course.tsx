import { useEffect, useMemo, useState } from 'react'
import { PageBar } from '../components/PageHead'
import { Icon, LabStatusPill, Ring } from '../components/ui'
import { useApp } from '../lib/app'
import { t } from '../lib/i18n'
import { Md, MdInline } from '../lib/md'
import { api, type Curriculum, type Diagnostic, type LessonSummary, type Route } from '../lib/data'
import { classify, studyOrder, type Verdict } from '../lib/diagnostic'
import { labStatus, setRoute, useProgress, type Progress } from '../lib/progress'
import { activityDone, tallyActivities, tallyChecks } from '../lib/standing'
import { beginHref, nextOnRoute, routeProgress } from '../lib/routes'
import { BuildsOn, JourneyMap } from '../components/JourneyMap'
import { continueTarget, nextLesson, resumeTarget } from '../lib/next'
import { usePlannedLesson } from '../lib/planned'
import { diagnosticHref, itemHref, lessonHref, labHref, refOf, trackHref } from '../lib/urls'
import { trackProgress } from './Home'
import { duration, modulesTime, trackTime } from '../lib/studytime'
import '../learn.css'

const lessonsN = (n: number) => (n === 1 ? t('learn.lessonOne') : t('learn.lessonsN', { n }))
const FIRST_LESSON = 'lx.first-steps'

/** The Learn page, read top to bottom: where to continue, your route, then the courses in the order they build. */
export function Paths() {
  const { cur } = useApp()
  const prog = useProgress()
  const route = cur?.routes?.find((r) => r.id === prog.route) || null
  const planned = usePlannedLesson(cur, prog, route)
  if (!cur) return null
  const begun = Object.keys(prog.lessons).length + Object.keys(prog.labs).length + Object.keys(prog.diagnostics).length > 0
  const target = continueTarget(cur, prog, route, planned)
  const targetRef = target && refOf(target.href)
  const targetLesson = targetRef?.kind === 'lesson' && targetRef.id
  const next = targetLesson ? cur.lessons[targetLesson] || null : null
  // a route whose lessons are all read is done, even when the course has more
  const routeDone = !!route && !planned && !target?.resume && !nextOnRoute(cur, prog, route)
  const courseOf = (module: string) => cur.tracks.find((x) => x.modules.includes(module))
  const firstLesson = cur.lessons[FIRST_LESSON]

  // the one thing to do next, and how to say it
  let hero: { title: string; text?: string; lesson?: LessonSummary; why?: string; label: string; href: string }
  if (!begun && !route && (firstLesson || next)) {
    const l = firstLesson || next!
    hero = { title: t('ln.startTitle'), text: t('ln.startText'), label: t('ln.startBtn'), href: lessonHref(l.id) }
  } else if (!begun && route) hero = { title: t('ln.routeStartTitle'), text: route.promise, label: route.begin.label, href: beginHref(route) }
  else if (target && !routeDone)
    hero = { title: t('ln.continueTitle'), lesson: next || undefined, text: next ? undefined : target.title, why: target.why === 'plan' ? t('today.planWhy') : undefined, label: t('learn.continue'), href: target.href }
  else hero = { title: route ? t('ln.routeDoneTitle') : t('ln.allDoneTitle'), text: t('ln.doneText'), label: t('ln.doneBtn'), href: trackHref('practice') }

  const all = cur.tracks.map((x) => trackProgress(cur, prog, x.id)).reduce((n, x) => ({ done: n.done + x.done, total: n.total + x.total }), { done: 0, total: 0 })
  const rp = route ? routeProgress(cur, prog, route) : all
  const lessonCourse = hero.lesson ? courseOf(hero.lesson.module) : undefined

  return (
    <div className="page learn">
      <section className="ln-now" aria-labelledby="ln-now-h" data-testid="learn-now">
        <div className="eyebrow">{t('nav.learn')}</div>
        <h1 id="ln-now-h">{hero.title}</h1>
        {hero.lesson && (
          <p className="ln-lesson">
            <strong>{hero.lesson.title}</strong>
            <span>{[lessonCourse?.title, t('ui.minutes', { n: hero.lesson.minutes }), hero.why].filter(Boolean).join(' · ')}</span>
          </p>
        )}
        {hero.text && <p className="ln-text">{hero.text}</p>}
        <a className="btn primary lg" href={hero.href} data-testid="learn-continue">
          {hero.label} <Icon name="arrow" size={17} />
        </a>
      </section>

      <section className="ln-route" aria-labelledby="ln-route-h" data-testid="learn-route">
        <div className="ln-route-pick">
          <label id="ln-route-h" htmlFor="ln-route-sel">{t('ln.route')}</label>
          <select id="ln-route-sel" value={route?.id || ''} onChange={(e) => setRoute(e.target.value || null)} data-testid="route-select">
            <option value="">{t('ln.routeNone')}</option>
            {(cur.routes || []).map((r) => (
              <option key={r.id} value={r.id}>{r.title}</option>
            ))}
          </select>
          <a className="ln-quiet" href="/#start-from">{t('ln.routeCompare')}</a>
        </div>
        {rp.total > 0 && (
          <div className="ln-route-prog">
            <span className="jm-bar" role="progressbar" aria-label={t('ln.routeProgressAria')} aria-valuenow={Math.round((100 * rp.done) / rp.total)} aria-valuemin={0} aria-valuemax={100}>
              <i style={{ width: `${(100 * rp.done) / rp.total}%` }} />
            </span>
            <span className="ln-route-n">{t('ln.routeProgress', { n: rp.done, of: rp.total })}</span>
          </div>
        )}
        <p className="ln-help" data-testid="map-route-note">{route ? route.who : t('ln.routeHelp')}</p>
      </section>

      <section className="ln-map" aria-labelledby="ln-map-h">
        <h2 id="ln-map-h">{t('ln.mapTitle')}</h2>
        <p className="ln-sub">{t('ln.mapText')}</p>
        <p className="ln-time-note">{t('ln.timeHelp')} {t('time.estimate')}</p>
        <JourneyMap cur={cur} prog={prog} route={route} here={next ? courseOf(next.module)?.id : null} />
      </section>
    </div>
  )
}

/** One path: chapters (modules) as an accordion, the chapter with the next lesson open. */
export default function Course({ track }: { track: string }) {
  const { cur } = useApp()
  const prog = useProgress()
  const tr = cur?.tracks.find((x) => x.id === track)
  // the lesson started last in this course while it is unread, else the course's next unread lesson
  const resumed = cur && tr ? resumeTarget(cur, prog, tr.id) : null
  const resumedRef = resumed && refOf(resumed.href)
  const next = cur && tr ? (resumedRef?.kind === 'lesson' && cur.lessons[resumedRef.id]) || nextLesson(cur, prog, tr.id) : null
  const nextModule = next?.module
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const { lang } = useApp()
  const hasDiag = !!cur?.diagnostics?.[track]
  const dk = cur?.diagnostics?.[track]?.track || track // the diagnostic that covers this path
  const [diag, setDiag] = useState<Diagnostic | null>(null)
  useEffect(() => {
    if (hasDiag) api.diagnostic(dk, lang).then(setDiag, () => setDiag(null))
  }, [hasDiag, dk, lang])
  const drec = prog.diagnostics[dk]
  const dres = useMemo(() => (cur && diag && drec ? classify(cur, diag, drec) : null), [cur, diag, drec])
  const vtag = (id: string) => {
    const v: Verdict | undefined = dres?.byTarget[id]?.verdict
    return v && v !== 'unassessed' ? <span className={`pill diag-v ${v === 'study' ? 'warn' : v === 'review' ? 'info' : 'muted'}`} title={t('diag.eyebrow')}>{t(`diag.v.${v}`)}</span> : null
  }
  // The first topic the diagnostic says to study, in path order, that the learner has not finished yet.
  const suggested = dres && drec?.finished ? studyOrder(dres).map((r) => r.id).find((id) => !prog.lessons[id]?.done && !prog.lessons[id]?.skipped) : undefined
  if (!cur) return null
  if (!tr)
    return (
      <div className="page">
        <a href="/learn">{t('learn.title')}</a>
      </div>
    )
  const p = trackProgress(cur, prog, tr.id)
  const idx = cur.tracks.indexOf(tr)
  const lands = cur.tracks.filter((x) => x.id !== 'practice')
  const following = cur.tracks[idx + 1]
  const nextTitle = next ? next.title : null

  return (
    <div className={`page path learn t-${tr.accent || 'blue'}`}>
      {/* no Report or Edit on a course page: it lists lessons; each lesson, lab and challenge has its own */}
      <PageBar>
        <a className="ln-back" href="/learn">
          <Icon name="back" size={15} /> {t('ln.back')}
        </a>
      </PageBar>
      <header className="ln-course-h">
        <div className="ln-course-top">
          <span className="ln-course-icon" aria-hidden="true">
            <Icon name={tr.icon || 'layers'} size={26} />
          </span>
          <div>
            <div className="eyebrow">{tr.id === 'practice' ? t('map.arenaEyebrow') : t('ln.courseN', { n: idx + 1, of: lands.length })} · {tr.level}</div>
            <h1>{tr.title}</h1>
          </div>
        </div>
        <p className="lede">{tr.tagline}</p>
        <p className="ln-from">
          <BuildsOn cur={cur} id={tr.id} links />
        </p>
        <CourseTime cur={cur} prog={prog} track={tr.id} />
        <div className="ln-course-go" data-testid="path-progress">
          {p.total > 0 && <Ring value={p.done / p.total} size={64} stroke={6} label={`${p.done}/${p.total}`} />}
          {suggested && (
            <a className="btn primary lg" href={itemHref(suggested)} data-testid="path-plan">
              {t('diag.startPlan')} <Icon name="arrow" size={16} />
            </a>
          )}
          {next && (
            <a className={`btn lg ${suggested ? '' : 'primary'}`} href={lessonHref(next.id)} data-testid="path-next">
              {p.done || prog.lessons[next.id]?.seen ? t('learn.continue') : t('learn.begin')} <Icon name="arrow" size={16} />
            </a>
          )}
        </div>
        {nextTitle && (
          <p className="ln-upnext">
            {t('learn.upNext')}: <a href={lessonHref(next!.id)}>{nextTitle}</a>
            {suggested && suggested !== next!.id && (
              <>
                {' · '}
                {t('diag.suggested')}: <a href={itemHref(suggested)} data-testid="diag-suggested">{cur.lessons[suggested]?.title || cur.labs[suggested]?.title}</a>
              </>
            )}
          </p>
        )}
      </header>
      {tr.status === 'coming-soon' && (
        <div className="callout warn soon-box" role="note" data-testid="coming-soon">
          <strong>{t('learn.comingSoonTitle')}</strong> {t('learn.comingSoonText')}
          {tr.roadmap && tr.roadmap.length > 0 && (
            <>
              <p className="small" style={{ margin: '8px 0 4px' }}>{t('learn.plannedTopics')}</p>
              <ul className="small roadmap">
                {tr.roadmap.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
      {hasDiag && (
        <DiagCard track={dk} meta={cur.diagnostics![track]} rec={drec} counts={dres ? Object.values(dres.byTarget).reduce((c, r) => ((c[r.verdict] = (c[r.verdict] || 0) + 1), c), {} as Record<string, number>) : null} />
      )}

      <ol className="chapters">
        {tr.modules.map((mid, mi) => {
          const m = cur.modules.find((x) => x.id === mid)
          if (!m) return null
          const lessons = m.lessons.filter((l) => cur.lessons[l])
          const done = lessons.filter((l) => prog.lessons[l]?.done || prog.lessons[l]?.skipped).length
          const minutes = lessons.reduce((n, l) => n + cur.lessons[l].minutes, 0)
          const isOpen = open[mid] ?? (mid === nextModule || (!nextModule && mi === 0))
          const practice = [...new Set(lessons.flatMap((l) => cur.lessons[l].labs))].map((id) => cur.labs[id]).filter(Boolean)
          const incidents = Object.values(cur.labs).filter((l) => l.kind === 'incident' && l.module === mid)
          const items = (m.labs || []).map((id) => cur.labs[id]).filter(Boolean)
          if (items.length || (m.labs && !lessons.length)) {
            const isOpenP = open[mid] ?? mi === 0
            const solved = items.filter((lab) => activityDone(lab.kind, prog.labs[lab.id])).length
            return (
              <li key={mid} className={`chapter ${isOpenP ? 'open' : ''}`}>
                <button className="chapter-h" onClick={() => setOpen({ ...open, [mid]: !isOpenP })} aria-expanded={isOpenP}>
                  <span className="chapter-n">{mi + 1}</span>
                  <span className="chapter-title">
                    <strong>{m.title}</strong>
                    <small>{items.length ? t('learn.practiceN', { n: items.length }) : t('learn.practiceNone')}{solved > 0 && ` · ${t('learn.doneN', { n: solved })}`}</small>
                  </span>
                  <Icon name="arrow" size={16} className="chev" />
                </button>
                {isOpenP && (
                  <div className="chapter-b">
                    <p className="muted small chapter-sum">
                      <MdInline text={m.summary} />
                    </p>
                    {items.length === 0 && <p className="muted small">{t('learn.practiceNone')}</p>}
                    <ol className="lesson-list">
                      {items.map((lab) => (
                        <li key={lab.id}>
                          <a href={labHref(lab.id)}>
                            <span className="tick">
                              <Icon name={lab.kind === 'incident' ? 'siren' : lab.kind === 'challenge' ? 'target' : 'flask'} size={13} />
                            </span>
                            <span className="l-title">{lab.title}</span>
                            {vtag(lab.id)}
                            <LabStatusPill s={labStatus(prog.labs[lab.id])} />
                            <span className="l-facts">{lab.recorded ? t('learn.gradedLive') : t('learn.notYetRecorded')}</span>
                            <span className="l-min">{t('ui.minutes', { n: lab.minutes })}</span>
                          </a>
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
              </li>
            )
          }
          return (
            <li key={mid} className={`chapter ${isOpen ? 'open' : ''} ${done === lessons.length && lessons.length ? 'complete' : ''}`}>
              <button className="chapter-h" onClick={() => setOpen({ ...open, [mid]: !isOpen })} aria-expanded={isOpen}>
                <span className="chapter-n">{done === lessons.length && lessons.length ? <Icon name="check" size={15} /> : mi + 1}</span>
                <span className="chapter-title">
                  <strong>{m.title}</strong>
                  <small>
                    {done === 0
                      ? `${lessonsN(lessons.length)} · ${duration(minutes)}`
                      : done < lessons.length
                        ? `${t('learn.completedOf', { n: done, of: lessons.length })} · ${t('time.left', { d: duration(modulesTime(cur, prog, [mid]).left) })}`
                        : t('learn.completedOf', { n: done, of: lessons.length })}
                  </small>
                  {done > 0 && done < lessons.length && (
                    <>
                      <span className="chapter-bar" aria-hidden="true">
                        <i style={{ transform: `scaleX(${done / lessons.length})` }} />
                      </span>
                      {!isOpen && <small className="chapter-next">{t('learn.nextIn', { title: cur.lessons[lessons.find((l) => !(prog.lessons[l]?.done || prog.lessons[l]?.skipped))!].title })}</small>}
                    </>
                  )}
                </span>
                <Icon name="arrow" size={16} className="chev" />
              </button>
              {isOpen && (
                <div className="chapter-b">
                  <p className="muted small chapter-sum">
                    <MdInline text={m.summary} />
                  </p>
                  <ol className="lesson-list">
                    {lessons.map((lid) => {
                      const l = cur.lessons[lid]
                      const st = prog.lessons[lid]
                      const isNext = next?.id === lid
                      const finished = st?.done || st?.skipped
                      const c = tallyChecks(l.checks || [], prog)
                      return (
                        <li key={lid}>
                          <a href={lessonHref(lid)} className={`${finished ? 'done' : st?.seen ? 'seen' : ''} ${isNext ? 'next' : ''}`}>
                            <span className="tick">{finished ? <Icon name="check" size={13} /> : null}</span>
                            <span className="l-title">{l.title}</span>
                            {isNext && <span className="pill info">{t('learn.next')}</span>}
                            {vtag(lid)}
                            {(finished || c.answered > 0) && (
                              <span className="l-facts">
                                {st?.skipped ? t('learn.skippedMark') : st?.done ? t('learn.readMark') : ''}
                                {c.answered > 0 ? `${finished ? ' · ' : ''}${t('learn.checksOf', { right: c.right, of: c.total })}` : ''}
                              </span>
                            )}
                            <span className="l-min">{t('ui.minutes', { n: l.minutes })}</span>
                          </a>
                        </li>
                      )
                    })}
                  </ol>
                  {(practice.length > 0 || incidents.length > 0) && (
                    <div className="chapter-practice">
                      <span className="muted small">{t('learn.practiseWith')}</span>
                      {practice.map((lab) => (
                        <a key={lab.id} href={labHref(lab.id)} className={`lab-chip ${lab.kind === 'incident' ? 'incident' : ''}`}>
                          <Icon name={lab.kind === 'incident' ? 'siren' : lab.kind === 'challenge' ? 'target' : 'flask'} size={14} /> {lab.title} <LabStatusPill s={labStatus(prog.labs[lab.id])} />
                        </a>
                      ))}
                      {incidents
                        .filter((l) => !practice.includes(l))
                        .map((lab) => (
                          <a key={lab.id} href={labHref(lab.id)} className="lab-chip incident">
                            <Icon name="siren" size={14} /> {lab.title} <LabStatusPill s={labStatus(prog.labs[lab.id])} />
                          </a>
                        ))}
                    </div>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ol>

      {following && (
        <a className="ln-nextcourse" href={trackHref(following.id)} data-testid="next-course">
          <span>
            <small>{t('ln.nextCourse')}</small>
            <strong>{following.title}</strong>
          </span>
          <Icon name="arrow" size={18} />
        </a>
      )}

      <details className="more">
        <summary>{t('ln.aboutCourse')}</summary>
        <Md text={tr.summary} />
        <p>
          <strong>{t('course.audience')}</strong> {tr.audience}
        </p>
        <p>
          <strong>{t('learn.outcome')}</strong> <MdInline text={tr.outcome} />
        </p>
      </details>
    </div>
  )
}

function DiagCard({ track, meta, rec, counts }: { track: string; meta: { title: string; minutes: number; count: number }; rec?: { started: number; finished?: number }; counts: Record<string, number> | null }) {
  const href = diagnosticHref(track)
  if (rec?.finished && counts)
    return (
      <div className="callout diag-card" data-testid="diag-card">
        <span>{t('diag.cardDone', { date: new Date(rec.finished).toLocaleDateString(), study: counts.study || 0, review: counts.review || 0, shown: counts.shown || 0 })}</span>
        <a className="btn sm" href={href}>{t('diag.cardResults')}</a>
      </div>
    )
  return (
    <div className="callout diag-card" data-testid="diag-card">
      <span>
        <strong>{t('diag.cardTitle')}</strong> {t('diag.cardText', { n: meta.count, min: meta.minutes })}
      </span>
      <a className="btn sm" href={href} data-testid="diag-card-link">{rec ? t('diag.cardResume') : t('diag.cardTake')}</a>
    </div>
  )
}

/** What the learner has shown in a course, kept apart: lessons read (or marked as known), questions answered
 * correctly, and practice completed or verified on a real cluster (lib/standing.ts). Reading alone is not shown as
 * competence. */
function Competence({ cur, prog, track }: { cur: Curriculum; prog: Progress; track: string }) {
  const tr = cur.tracks.find((x) => x.id === track)
  const lessons = (tr?.modules || []).flatMap((m) => cur.modules.find((x) => x.id === m)?.lessons || []).filter((l) => cur.lessons[l])
  const done = lessons.filter((l) => prog.lessons[l]?.done || prog.lessons[l]?.skipped).length
  const c = tallyChecks(lessons.flatMap((l) => cur.lessons[l].checks || []), prog)
  // the activities the course shows: linked from its lessons, listed by its modules, and incidents set in its modules
  const mods = new Set(tr?.modules || [])
  const labs = [
    ...new Set([
      ...lessons.flatMap((l) => cur.lessons[l].labs),
      ...[...mods].flatMap((m) => cur.modules.find((x) => x.id === m)?.labs || []),
      ...Object.values(cur.labs).filter((l) => l.kind === 'incident' && mods.has(l.module)).map((l) => l.id),
    ]),
  ].filter((id) => cur.labs[id])
  const a = tallyActivities(cur, labs, prog)
  if (!done && !c.answered && !a.done && !a.verified) return null
  return (
    <>
      {lessons.length > 0 && (
        <div>
          <dt>{t('ln.progLessons')}</dt>
          <dd>{t('learn.completedOf', { n: done, of: lessons.length })}</dd>
        </div>
      )}
      {c.answered > 0 && (
        <div>
          <dt>{t('ln.progChecks')}</dt>
          <dd>{t(c.corrected ? 'ln.progChecksShown' : 'ln.progChecksN', { right: c.right, of: c.total, shown: c.corrected })}</dd>
        </div>
      )}
      {a.done + a.verified > 0 && (
        <div>
          <dt>{t('ln.progPractice')}</dt>
          <dd>{t('ln.progPracticeN', { done: a.done, of: a.total, v: a.verified })}</dd>
        </div>
      )}
    </>
  )
}

/** A course's size and study time: lessons (reading, questions, in-browser practice) and, apart, the optional labs. */
function CourseTime({ cur, prog, track }: { cur: Curriculum; prog: Progress; track: string }) {
  const tm = trackTime(cur, prog, track)
  if (!tm.lessons && !tm.labs) return null
  const begun = tm.left < tm.minutes
  return (
    <dl className="ln-time" data-testid="course-time">
      {tm.lessons > 0 && (
        <div>
          <dt>{t('ln.timeLessons')}</dt>
          <dd>{t('time.lessonsAndTime', { n: tm.lessons, d: duration(tm.minutes) })}</dd>
        </div>
      )}
      {tm.labs > 0 && (
        <div>
          <dt>{t('ln.timeLabs')}</dt>
          <dd>{t('time.labsOptionalN', { n: tm.labs, d: duration(tm.labMinutes) })}</dd>
        </div>
      )}
      {begun && tm.left > 0 && (
        <div>
          <dt>{t('ln.timeLeft')}</dt>
          <dd>{duration(tm.left)}</dd>
        </div>
      )}
      <Competence cur={cur} prog={prog} track={track} />
    </dl>
  )
}
