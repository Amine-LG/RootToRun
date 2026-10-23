import { useMemo, useRef, useState } from 'react'
import { useDueCount } from '../components/Shell'
import { Icon } from '../components/ui'
import type { Curriculum, LessonSummary, Route } from '../lib/data'
import { useApp } from '../lib/app'
import { t } from '../lib/i18n'
import { continueTarget, nextLesson, nextUnread } from '../lib/next'
import { usePlannedLesson } from '../lib/planned'
import { setRoute, useProgress, type Progress } from '../lib/progress'
import { useLocation } from '../lib/router'
import { reveal } from '../lib/reveal'
import { beginHref, daysAway, nextOnRoute, routeLessons, routeProgress, suggestPractice } from '../lib/routes'
import { labHref, lessonHref, refOf, trackHref } from '../lib/urls'
import { duration, trackTime } from '../lib/studytime'

export function trackProgress(cur: Curriculum, prog: Progress, trackId: string) {
  const tr = cur.tracks.find((x) => x.id === trackId)
  if (!tr) return { done: 0, total: 0, minutes: 0 }
  const lessons = tr.modules.flatMap((m) => cur.modules.find((x) => x.id === m)?.lessons || []).filter((l) => cur.lessons[l])
  const finished = (l: string) => !!(prog.lessons[l]?.done || prog.lessons[l]?.skipped)
  return { done: lessons.filter(finished).length, total: lessons.length, minutes: lessons.reduce((n, l) => n + (cur.lessons[l]?.minutes || 0), 0) }
}

const clusterChip = (c: Route['cluster']) =>
  c === 'none' ? <span className="nchip ok">{t('route.clusterNone')}</span> : c === 'optional' ? <span className="nchip info">{t('route.clusterOptional')}</span> : <span className="nchip warn">{t('route.clusterRecommended')}</span>

/** "Where are you starting from?": six routes as one radio group, and what the chosen one means. A returning learner
 *  sees it folded under their current route (RouteNow); `heading` is false there, the fold's summary names the group. */
function RoutePicker({ cur, prog, chosen, onChoose, heading = true }: { cur: Curriculum; prog: Progress; chosen: Route | null; onChoose: (id: string) => void; heading?: boolean }) {
  const routes = cur.routes || []
  const first = nextLesson(cur, { ...prog, lessons: {} } as Progress)?.id
  const keys = (e: React.KeyboardEvent, i: number) => {
    const d = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0
    if (!d) return
    e.preventDefault()
    const j = (i + d + routes.length) % routes.length
    onChoose(routes[j].id)
    requestAnimationFrame(() => document.getElementById(`rp-${routes[j].id}`)?.focus())
  }
  const rp = chosen ? routeProgress(cur, prog, chosen) : null
  // a tap shows the chosen route's start button, which would otherwise open below a phone's screen
  const go = useRef<HTMLAnchorElement>(null)
  const pick = (id: string) => {
    onChoose(id)
    requestAnimationFrame(() => reveal(go.current))
  }
  return (
    <div className="start-from">
      {heading && <h2 id="start-from-h">{t('home.startFrom')}</h2>}
      <div className="route-picks" role="radiogroup" aria-labelledby="start-from-h">
        {routes.map((r, i) => (
          <button
            key={r.id}
            id={`rp-${r.id}`}
            type="button"
            role="radio"
            aria-checked={chosen?.id === r.id}
            tabIndex={chosen ? (chosen.id === r.id ? 0 : -1) : i === 0 ? 0 : -1}
            className="route-pick"
            onClick={(e) => (e.detail ? pick(r.id) : onChoose(r.id))} // a key press keeps the focused choice on screen
            onKeyDown={(e) => keys(e, i)}
            data-testid={`route-${r.id}`}
          >
            <span className="rp-dot" aria-hidden="true">{chosen?.id === r.id && <Icon name="check" size={13} />}</span>
            <span className="rp-t">{r.title}</span>
          </button>
        ))}
      </div>
      {!chosen && (
        <div className="route-detail" data-testid="route-detail">
          <div>
            <p>{t('route.notSure')}</p>
            <p className="rd-who">{t('route.notSureWhy')}</p>
          </div>
          <div className="rd-actions">
            <a className="btn lg route-go" href={first ? lessonHref(first) : '/learn'} data-testid="start-learning">
              {t('home.start')} <Icon name="arrow" size={17} />
            </a>
            <a className="rd-alt" href="/learn">{t('route.seeMap')}</a>
          </div>
        </div>
      )}
      {chosen && (
        <div className="route-detail" data-testid="route-detail" aria-live="polite">
          <div>
            <p className="rd-who">{chosen.who}</p>
            <p>
              <strong>{t('route.promise')}</strong> {chosen.promise}
            </p>
            <div className="rd-meta">
              {clusterChip(chosen.cluster)}
              {rp && rp.total > 0 && <span className="nchip">{t('time.lessonsAndTime', { n: rp.total, d: duration(rp.minutes) })}</span>}
              {rp && rp.done > 0 && <span className="nchip ok">{t('route.doneN', { n: rp.done, of: rp.total })}</span>}
            </div>
          </div>
          <div className="rd-actions">
            <a className="btn lg route-go" href={beginHref(chosen)} data-testid="start-learning" ref={go}>
              {chosen.begin.label} <Icon name="arrow" size={17} />
            </a>
            <a className="rd-alt" href="/learn">{t('route.seeMap')}</a>
          </div>
        </div>
      )}
    </div>
  )
}

/** A returning learner's route, in one line, with the full choice folded under it: they chose (or did not) already,
 *  so the question is not asked again in full. It opens when the address asks for it (/#start-from). */
function RouteNow({ cur, prog, chosen, onChoose }: { cur: Curriculum; prog: Progress; chosen: Route | null; onChoose: (id: string) => void }) {
  const loc = useLocation()
  const rp = chosen ? routeProgress(cur, prog, chosen) : null
  return (
    <details className="route-now" open={loc.hash === '#start-from' || undefined} data-testid="route-now">
      <summary>
        <span className="rn-text">
          <span className="rn-label" id="start-from-h">{t('home.routeNow')}</span>
          <strong className="rn-route">{chosen ? chosen.title : t('home.routeNone')}</strong>
          {rp && rp.total > 0 && <span className="rn-meta">{t('route.doneN', { n: rp.done, of: rp.total })}</span>}
        </span>
        <span className="rn-change">{chosen ? t('home.routeChange') : t('home.routeChoose')}</span>
      </summary>
      <div className="rn-body">
        <p className="rn-sub">{t('hx.startSub')}</p>
        <RoutePicker cur={cur} prog={prog} chosen={chosen} onChoose={onChoose} heading={false} />
      </div>
    </details>
  )
}

const SESSION = 30 // minutes: one honest, bounded session

type SessionItem = { href: string; what: string; why: string; min: number; testid: string }

/** The next session, in the order to do it: recall when cards are due, the lesson being resumed (the same one the
 *  Continue button opens), then the lesson after it, then practice on what was studied, within about 30 minutes. */
function sessionPlan(cur: Curriculum, prog: Progress, route: Route | null, planned: LessonSummary | null, next: ReturnType<typeof continueTarget>, due: number): SessionItem[] {
  const items: SessionItem[] = []
  if (due > 0) items.push({ href: '/review', what: t('today.review', { n: Math.min(due, 15) }), why: t('today.reviewWhy'), min: Math.min(10, Math.max(3, Math.round(Math.min(due, 15) * 0.6))), testid: 'today-review' })
  let left = SESSION - items.reduce((n, x) => n + x.min, 0)
  const lessonItem = (l: LessonSummary, href: string, why: string, testid: string) => {
    const part = Math.min(l.minutes, Math.max(10, left))
    items.push({ href, what: l.title, why: part < l.minutes ? `${why} · ${t('today.firstPart')}` : why, min: part, testid })
    left -= part
  }
  const ref = next?.resume && next.kind === 'lesson' ? refOf(next.href) : null
  const resumed = ref?.kind === 'lesson' ? cur.lessons[ref.id] : undefined
  if (resumed) lessonItem(resumed, next!.href, t('today.resumeWhy'), 'today-resume')
  // the next lesson to read: the diagnostic plan, else the one after the lesson being resumed, else the route or course
  const after = resumed ? (planned && planned.id !== resumed.id ? planned : nextUnread(cur, resumed.id, route, prog)) : planned || (route ? nextOnRoute(cur, prog, route) : nextLesson(cur, prog))
  if (after && left >= 5) {
    const onRoute = !!route && routeLessons(cur, route).includes(after.id)
    lessonItem(after, lessonHref(after.id), t(planned && after.id === planned.id ? 'today.planWhy' : onRoute ? 'today.lessonWhy' : 'today.courseWhy'), 'today-lesson')
  }
  const practice = suggestPractice(cur, prog, route)
  if (practice && practice.lab.minutes <= left + 5)
    items.push({ href: labHref(practice.lab.id), what: practice.lab.title, why: practice.reason === 'studied' ? (practice.lab.kind === 'challenge' ? t('today.challengeWhy') : t('today.incidentWhy')) : t('today.routePractice'), min: practice.lab.minutes, testid: 'today-practice' })
  return items
}

/** The returning learner's side of the hero: where they were, one action to resume (recall first after a long break)
 *  and the next session under it. The courses panel stays beside it, where a first visit has it. */
function WelcomeBack({ cur, prog, route, planned, next }: { cur: Curriculum; prog: Progress; route: Route | null; planned: LessonSummary | null; next: ReturnType<typeof continueTarget> }) {
  const due = useDueCount()
  const away = daysAway(prog)
  const longGap = away !== null && away >= 21
  const items = sessionPlan(cur, prog, route, planned, next, due)
  const total = items.reduce((n, x) => n + x.min, 0)
  const last = prog.last
  const recall = longGap && due > 0
  return (
    <div className="hx-copy">
      <h1 id="home-h">{longGap ? t('home.welcomeLong', { w: Math.round(away! / 7) }) : t('home.welcomeBack')}</h1>
      {longGap && <p className="hx-lede">{t('home.gapNote')}</p>}
      {last && (
        <p className="hx-last">
          {t('home.lastTime')} <strong>{last.title}</strong>
        </p>
      )}
      <div className="hx-actions">
        {recall && (
          <a className="btn primary lg" href="/review" data-testid="recall-first">
            {t('home.recallFirst')} <Icon name="arrow" size={17} />
          </a>
        )}
        {next ? (
          <a className={`btn lg ${recall ? '' : 'primary'}`} href={next.href} data-testid="hero-continue">
            {next.resume ? t(next.kind === 'lesson' ? 'home.continueLesson' : next.kind === 'lab' ? 'home.continueLab' : 'home.continueIncident') : t('home.continueWith', { title: next.title })} <Icon name="arrow" size={17} />
          </a>
        ) : (
          <a className={`btn lg ${recall ? '' : 'primary'}`} href={trackHref('practice')} data-testid="hero-continue">
            {t('me.practiseNext')} <Icon name="arrow" size={17} />
          </a>
        )}
        <a className="hx-alt" href="/learn">{t('hx.allCourses')}</a>
      </div>
      {!next && <p className="hx-note">{t('home.allRead')}</p>}
      {items.length > 0 && (
        <div className="hx-session" data-testid="session">
          <h2>{t('today.title', { min: total })}</h2>
          <ol className="session">
            {items.map((x, i) => (
              <li key={x.testid}>
                <a href={x.href} data-testid={x.testid}>
                  <span className="s-n">{i + 1}</span>
                  <span className="s-what">
                    {x.what}
                    <small>{x.why}</small>
                  </span>
                  <span className="s-min">{t('ui.minutes', { n: x.min })}</span>
                </a>
              </li>
            ))}
          </ol>
          <p className="hx-session-note">{t('today.text')}</p>
        </div>
      )}
    </div>
  )
}

/** The courses in the order they build, with their size and estimated time; progress once begun. */
function PathCard({ cur, prog, begun }: { cur: Curriculum; prog: Progress; begun: boolean }) {
  const lands = cur.tracks.filter((x) => x.id !== 'practice')
  const arena = cur.tracks.find((x) => x.id === 'practice')
  const times = lands.map((tr) => trackTime(cur, prog, tr.id))
  const all = times.reduce((n, x) => n + x.minutes, 0)
  const arenaN = arena ? arena.modules.flatMap((m) => cur.modules.find((x) => x.id === m)?.labs || []).filter((id) => cur.labs[id]).length : 0
  // the course of the lesson last studied: where the learner is on the path
  const lastRef = begun && prog.last ? refOf(prog.last.href) : null
  const lastMod = lastRef?.kind === 'lesson' ? cur.lessons[lastRef.id]?.module : undefined
  const here = lastMod ? lands.find((tr) => tr.modules.includes(lastMod))?.id : undefined
  return (
    <div className="hx-panel hx-path" data-testid="path-card">
      <h2 className="hx-panel-h">{begun ? t('hx.yourCourses') : t('hx.pathTitle')}</h2>
      {!begun && <p className="hx-panel-sub">{t('hx.pathSub', { d: duration(all) })}</p>}
      <ol className="hx-tracks" aria-label={t('hx.pathAria')}>
        {lands.map((tr, i) => {
          const tm = times[i]
          const done = tm.lessons - lessonsLeft(cur, prog, tr.id)
          const complete = tm.lessons > 0 && done === tm.lessons
          return (
            <li key={tr.id} className={`${complete ? 'done' : done > 0 || tr.id === here ? 'started' : ''} ${tr.id === here ? 'here' : ''}`}>
              <a href={trackHref(tr.id)} aria-current={tr.id === here ? 'step' : undefined} data-testid={tr.id === here ? 'course-here' : undefined}>
                <span className="hx-n" aria-hidden="true">{complete ? <Icon name="check" size={14} /> : i + 1}</span>
                <span className="hx-t">{tr.title}</span>
                <span className="hx-m">
                  {tr.id === here && <span className="hx-here">{t('home.hereNow')} · </span>}
                  {begun && done > 0 ? `${t('hx.doneOf', { n: done, of: tm.lessons })}${tm.left > 0 ? ` · ${t('time.left', { d: duration(tm.left) })}` : ''}` : t('time.lessonsAndTime', { n: tm.lessons, d: duration(tm.minutes) })}
                </span>
                {begun && done > 0 && (
                  <span className="hx-bar" aria-hidden="true">
                    <i style={{ width: `${(100 * done) / tm.lessons}%` }} />
                  </span>
                )}
              </a>
            </li>
          )
        })}
      </ol>
      {arena && (
        <a className="hx-arena" href={trackHref('practice')}>
          <Icon name="target" size={16} />
          <span className="hx-t">{t('hx.practiceRow')}</span>
          <span className="hx-m">{t('hx.practiceN', { n: arenaN })}</span>
        </a>
      )}
    </div>
  )
}

const lessonsLeft = (cur: Curriculum, prog: Progress, trackId: string) => {
  const p = trackProgress(cur, prog, trackId)
  return p.total - p.done
}

/** One page for every visitor, in one layout: the hero (an introduction, or where a returning learner left off) with
 *  the courses beside it, then how learning works (first visit only), then the starting point (asked in full on a first
 *  visit, one line with the choice folded under it afterwards). The root names its layout (data-layout) so that Back
 *  never restores a position saved on the other one (lib/router.ts). */
export default function Home() {
  const { cur } = useApp()
  const prog = useProgress()
  const [picked, setPicked] = useState<string | null>(prog.route || null)
  const route = useMemo(() => cur?.routes?.find((r) => r.id === picked) || null, [cur, picked])
  const planned = usePlannedLesson(cur, prog, route)
  if (!cur) return null
  const returning = Object.keys(prog.lessons).length + Object.keys(prog.labs).length + Object.keys(prog.diagnostics).length > 0
  const choose = (id: string) => {
    setPicked(id)
    setRoute(id)
  }
  // a chosen route counts as a start: its starting point, not the first Linux lesson
  const next = returning || route ? continueTarget(cur, prog, route, planned) : null
  const apps = cur.tracks.find((x) => x.id === 'admin1')
  const appsFirst = nextLesson(cur, prog, 'admin1') // the lesson the course page's Begin opens
  const allDone = (returning || !!route) && !next
  return (
    <div className={`page home hx ${returning ? 'is-returning' : 'is-first'}`} data-layout={returning ? 'returning' : 'first'}>
      <section className={`hx-hero ${returning ? 'returning' : ''}`} aria-labelledby="home-h" data-testid={returning ? 'welcome' : 'intro'}>
        {returning ? (
          <WelcomeBack cur={cur} prog={prog} route={route} planned={planned} next={next} />
        ) : (
          <div className="hx-copy">
            <p className="hx-kicker">{t('hx.kicker')}</p>
            <h1 id="home-h">{t('hx.title')}</h1>
            <p className="hx-lede">{t('hx.lede')}</p>
            <div className="hx-actions">
              {next ? (
                <a className="btn primary lg" href={next.href} data-testid="hero-continue">
                  {next.why === 'begin' ? next.title : t('home.continueWith', { title: next.title })} <Icon name="arrow" size={17} />
                </a>
              ) : allDone ? (
                <a className="btn primary lg" href={trackHref('practice')} data-testid="hero-continue">
                  {t('me.practiseNext')} <Icon name="arrow" size={17} />
                </a>
              ) : (
                <a className="btn primary lg" href={appsFirst ? lessonHref(appsFirst.id) : trackHref('admin1')} data-testid="hero-start" aria-describedby={apps ? 'hx-level' : undefined}>
                  {apps ? t('hx.start') : t('home.startFirst')} <Icon name="arrow" size={17} />
                </a>
              )}
              <a className="hx-alt hero-alt" href="#start-from">{t('hx.findStart')}</a>
            </div>
            {!next && !allDone && apps && <p className="hx-level" id="hx-level" data-testid="hero-level">{t('hx.startLevel')}</p>}
            <p className="hx-new">
              {t('hx.newHere')} <a href={lessonHref('lx.first-steps')}>{t('hx.firstLesson', { min: cur.lessons['lx.first-steps']?.minutes || 12 })}</a>
            </p>
          </div>
        )}
        <PathCard cur={cur} prog={prog} begun={returning} />
      </section>

      {!returning && (
        <section className="hx-section" aria-labelledby="how-h">
          <h2 id="how-h" className="hx-h2">{t('hx.howTitle')}</h2>
          <ol className="hx-how">
            {([['book', t('hx.how1t'), t('hx.how1')], ['check', t('hx.how2t'), t('hx.how2')], ['terminal', t('hx.how3t'), t('hx.how3')]] as const).map(([icon, title, text]) => (
              <li key={icon}>
                <span className="hx-how-i" aria-hidden="true"><Icon name={icon} size={20} /></span>
                <h3>{title}</h3>
                <p>{text}</p>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section className="hx-section start-section" id="start-from" aria-labelledby="start-from-h">
        {returning ? <RouteNow cur={cur} prog={prog} chosen={route} onChoose={choose} /> : <RoutePicker cur={cur} prog={prog} chosen={route} onChoose={choose} />}
      </section>

      <p className="hx-foot-note">{t('home.noAccount')}</p>
    </div>
  )
}
