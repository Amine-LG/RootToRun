import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { PageActions } from '../components/Contribute'
import { Prereqs } from '../components/Prereqs'
import { LessonSources } from '../components/LessonSources'
import { PageBar } from '../components/PageHead'
import { RecallBreak } from '../components/RecallBreak'
import { ActivityHead, CheckQuestion, Guess, KIND } from '../components/Activity'
import { focusQuietly, footerTop, headerBottom, reducedMotion, reveal } from '../lib/reveal'
import { ExplainCard } from '../components/Learn'
import { CommandBlock } from '../components/Term'
import { OrderStep, ReflectStep, ShowStep, TryStep } from '../components/Flow'
import { toast } from '../components/Toast'
import { Callout, Icon, LabStatusPill, PageSkeleton, Refs } from '../components/ui'
import { api, type Diagnostic, type Lesson as L } from '../lib/data'
import { classify } from '../lib/diagnostic'
import { why } from './Diagnostic'
import { useApp, useLoad } from '../lib/app'
import { t } from '../lib/i18n'
import { Md } from '../lib/md'
import { compileLesson, lessonChecks, sectionOf, type Activity } from '../lib/plan'
import { lessonBeside, nextUnread } from '../lib/next'
import { anchorTarget, navigate, useLocation } from '../lib/router'
import { diagnosticHref, labHref, lessonHref, trackHref } from '../lib/urls'
import { tallyChecks } from '../lib/standing'
import {
  labStatus,
  markLessonDone,
  markLessonSeen,
  markReadingSkipped,
  migrateLegacyAnswers,
  setLast,
  setLessonPos,
  useProgress,
  type Progress,
} from '../lib/progress'
import { DIAGRAMS } from '../lib/diagrams'
import { Diagram, SimById, simTitle } from './Studio'
import { useOverlay } from '../lib/overlay'

// The lesson player. A lesson is an ordered plan of typed activities (lib/plan.ts), shown one at a time with an outline,
// or all at once ("whole lesson"). The URL names the current activity (?a=<id>), so reloads, links and resume land on
// the same place. Depth (common mistakes, limits, references) is one click away from every activity.

const ALL_CHECKS = 'checks' // the "know this already?" view: every check of the lesson, before reading

export default function Lesson({ id }: { id: string }) {
  const { cur, lang } = useApp()
  const prog = useProgress()
  const loc = useLocation()
  const { data: l, err } = useLoad(() => api.lesson(id, lang), [id, lang])
  const [deeper, setDeeper] = useState(false)
  const top = useRef<HTMLDivElement>(null)
  const plan = useMemo(() => (l ? compileLesson(l) : []), [l])
  const simNames = useSimNames()

  const params = new URLSearchParams(loc.search)
  const want = params.get('a')
  const stepParam = params.get('step')
  const testOut = want === ALL_CHECKS
  let idx = plan.findIndex((a) => a.id === want)
  if (idx < 0 && stepParam) idx = Math.min(Math.max(1, Number(stepParam) || 1), plan.length) - 1
  if (idx < 0) idx = 0
  const act = plan[idx]

  useEffect(() => {
    if (!l) return
    markLessonSeen(id)
    // positional answers from the first version belong to the old questions: never move them onto a rewritten lesson
    if (!l.flow?.length) migrateLegacyAnswers(id, l.predict.map((q, k) => q.id || `lesson:${id}:${k}`))
  }, [l, id])
  useEffect(() => {
    if (!l || !act || testOut) return
    setLessonPos(id, act.id)
    setLast(lessonHref(id), l.title) // a lesson is one article: continuing opens it, the contents list does the rest
  }, [l, id, act, idx, testOut])

  const go = (k: number) => {
    const a = plan[k]
    if (!a) return
    const el = top.current?.querySelector<HTMLElement>(`[data-step="${CSS.escape(a.id)}"]`)
    // not on the page (the "answer its questions first" view): open the article at that step
    if (!el) return navigate(`${lessonHref(id)}?a=${encodeURIComponent(a.id)}`)
    // every lesson is one article: scroll to the step (the root's scroll-padding keeps it clear of the header)
    el.scrollIntoView({ block: 'start', behavior: reducedMotion() ? 'auto' : 'smooth' })
    focusQuietly(el)
  }
  const goId = (aid: string) => go(plan.findIndex((a) => a.id === aid))

  if (err) return <div className="page"><Callout tone="bad">{err}</Callout></div>
  if (!l || !cur) return <div className="page"><PageSkeleton /></div>

  const mod = cur.modules.find((m) => m.lessons.includes(id))
  const track = cur.tracks.find((tr) => mod && tr.modules.includes(mod.id))
  const posInModule = mod ? mod.lessons.indexOf(id) + 1 : 0
  const checks = lessonChecks(plan)
  const rec = prog.lessons[id]
  // previous and next follow the learner's route when this lesson is on it, else the course (lib/next.ts)
  const route = cur.routes?.find((r) => r.id === prog.route) || null
  const after = lessonBeside(cur, id, route, 1)
  const before = lessonBeside(cur, id, route, -1)
  // the end-of-lesson button: the next lesson still to read (a lesson already read or skipped is passed over)
  const unread = nextUnread(cur, id, route, prog)
  const next = unread ? { id: unread.id, title: unread.title } : null
  const render = (a: Activity) => (
    <ActivityView a={a} l={l} plan={plan} goId={goId} next={next} simNames={simNames} />
  )

  return (
    <div className={`page lesson2 t-${track?.accent || 'blue'}`} ref={top}>
      {/* three kinds of action, in reading order: supporting material, contribution (the slot), then the way through
          the course, with Next as the one button */}
      <PageBar
        className="lesson-bar"
        actions={<PageActions ctx={{ type: 'lesson', id: l.id, title: l.title, area: track?.title, source: l.source }} />}
        end={
          (before || after) && (
            <nav className="lesson-pager" aria-label={t('lesson.pager')}>
              {before && (
                <a className="linkish small pager-prev" href={lessonHref(before.id)} rel="prev" title={before.title} data-testid="pager-prev">
                  <Icon name="back" size={14} /> {t('lesson.prevLesson')}
                  <span className="sr-only">: {before.title}</span>
                </a>
              )}
              {after && (
                <a className="btn sm pager-next" href={lessonHref(after.id)} rel="next" title={after.title} data-testid="pager-next">
                  {t('lesson.nextLesson')}
                  <span className="sr-only">: {after.title}</span> <Icon name="arrow" size={14} />
                </a>
              )}
            </nav>
          )
        }
      >
        <a className="back terr-back" href={track ? trackHref(track.id) : '/learn'}>
          <Icon name="back" size={15} /> <span className="terr-dot" aria-hidden="true" /> {track?.title}
        </a>
        <span className="grow" />
        <button className="linkish small lesson-deeper" onClick={() => setDeeper(true)} aria-haspopup="dialog" data-testid="go-deeper">
          <Icon name="layers" size={14} /> <span className="pb-long">{t('lesson.deeperRefs')}</span><span className="pb-short">{t('lesson.deeperShort')}</span>
        </button>
      </PageBar>

      {l.lang_status && l.lang_status !== 'translated' && (
        <p className="callout warn small" role="note" data-testid="lang-note">
          {l.lang_status === 'missing' ? t('lesson.langMissing') : t('lesson.langStale')}
        </p>
      )}
      <header className="lesson-h">
        <div className="lesson-where">
          {mod ? t('lesson.where', { module: mod.title, n: posInModule, of: mod.lessons.length }) : null}
        </div>
        <h1>{l.title}</h1>
        {l.subtitle && <p className="subtitle">{l.subtitle}</p>}
        <div className="lesson-facts">
          <span>
            <Icon name="clock" size={14} /> {t('ui.minutes', { n: l.minutes })}
          </span>
          {l.prerequisites.filter((p) => cur.lessons[p]).length > 0 && (
            <span>
              {t('lesson.buildsOn')}{' '}
              {l.prerequisites
                .filter((p) => cur.lessons[p])
                .map((p, k, arr) => (
                  <span key={p}>
                    <a href={lessonHref(p)}>{cur.lessons[p].title}</a>
                    {k < arr.length - 1 ? ', ' : ''}
                  </span>
                ))}
            </span>
          )}
          <LessonFacts plan={plan} lessonId={id} />
        </div>
        {/* the lesson's brief: what it teaches beside what practising it needs, as wide as the lesson below */}
        <div className="lesson-brief" data-testid="lesson-brief">
          <div className="lesson-goal">
            <span className="lbl">{t('lesson.youWill')}</span>
            <Md text={l.objective} />
          </div>
          <Prereqs tools={cur.lessons[id]?.tools ?? []} where={cur.lessons[id]?.record_on ?? 'host'} versions={{ podman: l.host?.podman, oc: l.recording?.cluster?.oc, kubectl: l.recording?.cluster?.kubectl }} />
        </div>
        {track && <DiagNote trackId={track.id} lessonId={id} />}
        {!testOut && checks.length > 0 && !rec?.skipped && (
          <p className="testout">
            {t('lesson.knowIt')}{' '}
            <a href={`${lessonHref(id)}?a=${ALL_CHECKS}`} data-testid="test-out">
              {checks.length === 1 ? t('lesson.answerCheck') : t('lesson.answerChecks', { n: checks.length })}
            </a>
          </p>
        )}
      </header>

      {!testOut && <LessonSources key={l.id} files={l.files} />}
      {testOut ? <TestOut l={l} plan={plan} onRead={goId} /> : <FlowArticle l={l} plan={plan} focus={want || (stepParam && idx > 0 ? act.id : null)} render={render} />}

      {deeper && <DeeperPanel l={l} onClose={() => setDeeper(false)} />}
    </div>
  )
}

function useSimNames() {
  const [names, setNames] = useState<Record<string, string>>({})
  useEffect(() => {
    simTitle().then(setNames, () => setNames({}))
  }, [])
  return (id: string) => names[id] || t('lesson.model')
}

/** What the learner has done in this lesson, as separate facts (never one "understood" percentage). */
function LessonFacts({ plan, lessonId }: { plan: Activity[]; lessonId: string }) {
  const prog = useProgress()
  const checks = lessonChecks(plan)
  const c = tallyChecks(checks.map((q) => q.qid), prog) // the rules every page uses (lib/standing.ts)
  const rec = prog.lessons[lessonId]
  return (
    <span className="facts" data-testid="lesson-facts">
      {rec?.done ? t('facts.read') : rec?.skipped ? t('facts.skipped') : t('facts.notRead')}
      {checks.length > 0 &&
        ` · ${c.answered ? t(c.corrected ? 'facts.checksShown' : 'facts.checks', { right: c.right, of: c.total, shown: c.corrected }) : checks.length === 1 ? t('facts.oneCheck') : t('facts.nChecks', { n: checks.length })}`}
    </span>
  )
}

function ActivityView({ a, l, plan, goId, next, simNames }: { a: Activity; l: L; plan: Activity[]; goId: (id: string) => void; next: { id: string; title: string } | null; simNames: (id: string) => string }) {
  switch (a.kind) {
    case 'learn':
      return (
        <>
          {a.section.title && <h2 className="act-title">{a.section.title}</h2>}
          <div className="prose">
            <Md text={a.section.body} />
          </div>
        </>
      )
    case 'show':
      return <ShowStep st={a.step} l={l} />
    case 'try':
      return (
        <>
          <ActivityHead kind="try" />
          <TryStep st={a.step} l={l} />
        </>
      )
    case 'order':
      return (
        <>
          <ActivityHead kind="order" />
          <OrderStep st={a.step} l={l} />
        </>
      )
    case 'reflect':
      return (
        <>
          <ActivityHead kind="reflect" />
          <ReflectStep st={a.step} l={l} />
        </>
      )
    case 'predict':
      return (
        <>
          <Guess p={a.question.q} k={`guess:${a.question.qid}`} label={t('lesson.guessFirst')} />
        </>
      )
    case 'check': {
      const src = sectionOf(plan, a.anchor)
      const asked = l.flow?.find((s) => s.id === a.anchor)
      const recalls = asked && asked.kind === 'ask' ? asked.recalls : ''
      return (
        <>
          {recalls && <RecallFrom id={recalls} />}
          {a.questions.map((q, k) => (
            <CheckQuestion
              key={q.qid}
              q={q.q}
              qid={q.qid}
              n={k + 1}
              of={a.questions.length}
              source={src && src.kind === 'learn' && src.section.title ? { label: src.section.title, onOpen: () => goId(src.id) } : undefined}
            />
          ))}
        </>
      )
    }
    case 'explore':
      return (
        <>
          <ActivityHead kind="explore" extra={a.sim ? t('lesson.exploreModel') : t('lesson.exploreDiagram')} />
          {a.sim && <h2 className="act-title">{simNames(a.sim)}</h2>}
          {a.body && (
            <div className="prose">
              <Md text={a.body} />
            </div>
          )}
          <div className="explore-stage">{a.diagram ? <Diagram id={a.diagram} /> : a.sim ? <SimById id={a.sim} bare /> : null}</div>
        </>
      )
    case 'practise':
      return <PractiseView l={l} />
    case 'summary':
      return <SummaryView l={l} plan={plan} next={next} goId={goId} />
  }
}

/** A question about an earlier lesson says which one, with a link, and says so plainly when the learner has not been
 * through it yet (progress is per browser: a new browser, or one cleared, has no record). */
function RecallFrom({ id }: { id: string }) {
  const { cur } = useApp()
  const prog = useProgress()
  const src = cur?.lessons[id]
  if (!src) return null
  const seen = !!(prog.lessons[id]?.done || prog.lessons[id]?.seen || prog.lessons[id]?.skipped)
  return (
    <p className="recall-from small" data-testid="recall-from">
      <Icon name="refresh" size={13} /> {t('lesson.recallFrom')} <a href={lessonHref(id)}>{src.title}</a>
      {!seen && <span className="muted recall-note">{t('lesson.recallNotYet')}</span>}
    </p>
  )
}

function PractiseView({ l }: { l: L }) {
  const { cur, live, meta } = useApp()
  const prog = useProgress()
  if (!cur) return null
  const labs = l.labs.map((id) => cur.labs[id]).filter(Boolean)
  const back = `${lessonHref(l.id)}?a=practise`
  return (
    <>
      <ActivityHead kind="practise" />
      <h2 className="act-title">{t('lesson.practiseTitle')}</h2>
      <p className="env-note">
        <Icon name={labs.length ? (live ? 'plug' : 'play') : 'terminal'} size={15} />{' '}
        {!labs.length ? t('lesson.envWorkstation') : live ? t('lesson.envLive') : meta?.mode === 'cluster' ? t('lesson.envConnect') : t('lesson.envRecorded')}
      </p>
      {labs.length > 0 && (
        <div className="practice-labs">
          {labs.map((lab, i) => (
            <a key={lab.id} href={`${labHref(lab.id)}?from=${encodeURIComponent(back)}`} className={`practice-lab ${i === 0 ? 'primary' : ''} ${lab.kind}`}>
              <Icon name={lab.kind === 'incident' ? 'siren' : lab.kind === 'challenge' ? 'target' : 'flask'} size={20} />
              <span>
                <small>{lab.kind === 'incident' ? t('lesson.tryIncident') : lab.kind === 'challenge' ? t('lesson.tryChallenge') : t('lesson.tryLab')}</small>
                <strong>{lab.title}</strong>
                <span className="muted small">{t('ui.minutes', { n: lab.minutes })}</span>
              </span>
              <LabStatusPill s={labStatus(prog.labs[lab.id])} />
              <Icon name="arrow" size={16} />
            </a>
          ))}
        </div>
      )}
      {l.commands.length > 0 && (
        <details className="more" open={!labs.length}>
          <summary>{t('lesson.tryHost')}</summary>
          <p className="muted small">{t('lesson.tryHostHelp', { tools: Object.entries(l.host || {}).map(([k, v]) => `${k} ${v}`).join(', ') || '-' })}</p>
          {Object.entries(l.files).map(([name, body]) => (
            <div key={name}>
              <div className="file-name mono">{name}</div>
              <pre className="code" tabIndex={0} aria-label={name}>
                <code>{body}</code>
              </pre>
            </div>
          ))}
          <div className="cmds host-cmds">
            {l.commands.map((c, i) => (
              <CommandBlock key={i} c={{ ...c, run: null, stdin: null, as: 'host', skip: '', timeout: 0 }} entry={l.recording?.entries.find((e) => e.cmd === c.cmd)} />
            ))}
          </div>
        </details>
      )}
    </>
  )
}

/** A lesson written as a teaching flow is read as one article: every step is on the page, grouped into sections under
 * their headings, and the page scrolls normally. Questions, typed commands and ordering tasks stay interactive where
 * they are; nothing is hidden behind a Continue button. The contents list on the side links to each section through
 * the router (`#<section>`), so Back and Forward work, and it marks the section being read. Headings are kept clear of
 * the sticky header with `scroll-margin-top` (CSS), not by scrolling in JavaScript after the fact. */
type Part = { id: string; title: string; acts: Activity[] }
export function flowParts(plan: Activity[], summaryTitle: string, practiseTitle: string): Part[] {
  const parts: Part[] = [{ id: 'start', title: '', acts: [] }]
  for (const a of plan) {
    if (a.kind === 'learn' && a.section.title) parts.push({ id: a.section.id, title: a.section.title, acts: [] })
    else if (a.kind === 'summary') parts.push({ id: 'summary', title: summaryTitle, acts: [] })
    else if (a.kind === 'practise') parts.push({ id: 'practise', title: practiseTitle, acts: [] })
    parts[parts.length - 1].acts.push(a)
  }
  return parts.filter((p) => p.acts.length)
}

function FlowArticle({ l, plan, focus, render }: { l: L; plan: Activity[]; focus: string | null; render: (a: Activity) => ReactNode }) {
  const loc = useLocation()
  const parts = useMemo(() => flowParts(plan, t('lesson.summaryTitle'), t('lesson.practiseIt')), [plan])
  const titled = useMemo(() => parts.filter((p) => p.title), [parts])
  const [active, setActive] = useState('') // nothing is marked while the introduction, above every heading, is read
  const bar = useRef<HTMLDivElement>(null)
  const col = useRef<HTMLDivElement>(null)
  // A section the learner jumped to (contents link, Back/Forward, a shared #link) stays marked until they scroll
  // themselves: near the end of a lesson the page cannot scroll a short section's heading up to the reading line.
  const jumped = useRef<string | null>(loc.hash ? decodeURIComponent(loc.hash.slice(1)) : null)
  const recalc = useRef(() => {})
  // a section of this article, looked up inside it: a section id can repeat an id of the app (`root`, the mount point,
  // which starts above every reading line and so was always "current")
  const partEl = (id: string) => col.current?.querySelector<HTMLElement>(`:scope > section#${CSS.escape(id)}`) ?? null
  // The section being read: the last heading above a reading line (none above the first heading). The line sits just under the sticky header and,
  // through the last screen of scrolling, moves down to the bottom of the window, so the headings of short final
  // sections each become current in turn and the last one is current at the end of the page.
  useEffect(() => {
    let frame = 0
    const update = () => {
      frame = 0
      const doc = document.documentElement
      const max = doc.scrollHeight - window.innerHeight
      bar.current?.style.setProperty('--read', `${max > 0 ? Math.min(1, window.scrollY / max) : 1}`)
      if (jumped.current && titled.some((p) => p.id === jumped.current)) return setActive(jumped.current)
      const top = headerBottom() + 120
      const bottom = window.innerHeight - 48
      const span = Math.max(1, bottom - top)
      const line = top + span * Math.min(1, Math.max(0, 1 - (max - window.scrollY) / span))
      let cur = ''
      for (const p of titled) {
        const el = partEl(p.id)
        if (el && el.getBoundingClientRect().top <= line) cur = p.id
      }
      setActive(cur)
    }
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update)
    }
    // the learner's own scrolling (wheel, touch, keys, scrollbar) releases a jump; programmatic scrolling does not
    const release = () => {
      if (jumped.current) {
        jumped.current = null
        onScroll()
      }
    }
    const inputs = ['wheel', 'touchmove', 'keydown', 'pointerdown'] as const
    recalc.current = onScroll
    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    for (const ev of inputs) window.addEventListener(ev, release, { passive: true })
    // answers, feedback and images change the page's height without scrolling it
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(onScroll) : null
    if (col.current) ro?.observe(col.current)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      for (const ev of inputs) window.removeEventListener(ev, release)
      ro?.disconnect()
      cancelAnimationFrame(frame)
    }
  }, [titled])
  // Back, Forward and contents links change the hash: mark that section; an address without one (or with another
  // anchor) releases the mark, and the reading position decides again once the router has restored it
  useEffect(() => {
    const id = loc.hash ? decodeURIComponent(loc.hash.slice(1)) : null
    if (id && titled.some((p) => p.id === id)) {
      jumped.current = id
      setActive(id)
    } else if (jumped.current) {
      jumped.current = null
      recalc.current()
    }
  }, [loc.hash, titled])
  // A link to a section (#id) or to a step (?a=) opens the page there once the lesson has rendered. Plain links to the
  // lesson start at the top (the router does that).
  useEffect(() => {
    const target = loc.hash ? partEl(decodeURIComponent(loc.hash.slice(1))) || anchorTarget(decodeURIComponent(loc.hash.slice(1))) : focus ? document.querySelector<HTMLElement>(`[data-step="${CSS.escape(focus)}"]`) : null
    target?.scrollIntoView({ block: 'start' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [l.id])
  const toc = useRef<HTMLDetailsElement>(null)
  // wide screens show the contents open beside the lesson; phones and tablets a bar that opens over it. Followed live:
  // a window resized across the breakpoint opens or closes the list with the layout (the `open` prop below)
  const [wide, setWide] = useState(() => typeof window !== 'undefined' && !!window.matchMedia?.('(min-width: 901px)').matches)
  useEffect(() => {
    const mq = window.matchMedia?.('(min-width: 901px)')
    const f = (e: MediaQueryListEvent) => setWide(e.matches)
    mq?.addEventListener('change', f)
    return () => mq?.removeEventListener('change', f)
  }, [])
  const toPart = (e: React.MouseEvent, id: string) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return // new tab or window: the browser's job
    e.preventDefault()
    // through the router: one history entry per jump, scrolled by the router with the heading's scroll margin
    // the same link again: the URL does not change, so scroll here (the root's scroll-padding keeps it under the header)
    if (!wide && toc.current) toc.current.open = false // on a phone the list closes and the page shows the section
    jumped.current = id
    setActive(id)
    if (decodeURIComponent(loc.hash.slice(1)) === id) partEl(id)?.scrollIntoView({ block: 'start' })
    else navigate(`${loc.path}#${id}`)
    focusQuietly(partEl(id))
  }
  // on phones the contents bar is sticky under the header: its height joins the sticky chrome (--hdr, tokens.css), so
  // headings reached from it land below both. The header and the page bar measure themselves (Shell, PageBar).
  useEffect(() => {
    const root = document.documentElement
    const bar = document.querySelector<HTMLElement>('.flow-parts')
    const set = () => {
      const sticky = !!bar && getComputedStyle(bar).position === 'sticky' && !window.matchMedia?.('(min-width: 901px)').matches
      // the closed bar (its toggle row and border): an open list covers the page only while the learner reads it
      const closed = (bar?.querySelector(':scope > details > summary')?.getBoundingClientRect().height || 0) + 1
      root.style.setProperty('--outline-bar-h', `${sticky ? Math.round(closed) : 0}px`)
    }
    set()
    const ro = typeof ResizeObserver !== 'undefined' && bar ? new ResizeObserver(set) : null
    if (bar) ro?.observe(bar)
    window.addEventListener('resize', set)
    return () => {
      ro?.disconnect()
      window.removeEventListener('resize', set)
      root.style.removeProperty('--outline-bar-h')
    }
  }, [])
  // phones: the open list lies over the page under its bar. A tap outside it (on the scrim, or on the site header),
  // Escape, or the keyboard focus leaving it closes it; the scrim takes that tap, so it never also follows a link or
  // presses a button underneath.
  const [tocOpen, setTocOpen] = useState(false)
  const closeToc = (refocus: boolean) => {
    if (toc.current) toc.current.open = false
    if (refocus) focusQuietly(toc.current?.querySelector<HTMLElement>(':scope > summary'))
  }
  // the list fits between its bar and the bottom of the window (--toc-room, CSS), also when the window changes size while
  // it is open; a bar opened while it is still low on the screen (before it sticks) first moves up to where it sticks,
  // so the list has room
  const fitToc = (opening: boolean) => {
    const d = toc.current, ol = d?.querySelector<HTMLElement>('ol'), s = d?.querySelector(':scope > summary')?.getBoundingClientRect()
    if (!d || !ol || !s) return
    // the phone's tab bar lies over the bottom of the window: the list ends above it (its last links were under it)
    const floor = footerTop()
    let room = floor - s.bottom - 12
    if (opening && room < 200) {
      const stick = parseFloat(getComputedStyle(d.parentElement!).top) || 0
      window.scrollBy({ top: s.top - stick, behavior: 'auto' })
      room = floor - stick - s.height - 12
    }
    ol.style.setProperty('--toc-room', `${Math.round(room)}px`)
  }
  // on phones, listening the whole time and asking the list itself whether it is open: its toggle event (and so
  // tocOpen) comes a task after it opens in Chrome, and a tap or Escape in between must close it too
  useEffect(() => {
    if (wide) return
    const away = (e: PointerEvent) => {
      const el = e.target as Element | null
      if (toc.current?.open && !toc.current.contains(el) && !el?.closest?.('.toc-scrim')) closeToc(false)
    }
    const key = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || !toc.current?.open || e.defaultPrevented) return
      e.preventDefault()
      closeToc(true)
    }
    const fit = () => toc.current?.open && fitToc(false)
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', key)
    window.addEventListener('resize', fit)
    return () => {
      document.removeEventListener('pointerdown', away)
      document.removeEventListener('keydown', key)
      window.removeEventListener('resize', fit)
    }
  }, [wide]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="lesson-flow lesson-article">
      <div className="read-progress" ref={bar} aria-hidden="true" />
      {/* data-reveal="off": the list opens in place in its sticky bar; the page must not scroll for it (lib/reveal.ts) */}
      <nav
        className="flow-parts"
        aria-label={t('flow.parts')}
        data-sticky
        data-reveal="off"
        onBlur={(e) => !wide && toc.current?.open && e.relatedTarget && !e.currentTarget.contains(e.relatedTarget as Node) && closeToc(false)}
      >
        <details
          className="flow-toc"
          open={wide}
          ref={toc}
          onToggle={(e) => {
            setTocOpen(e.currentTarget.open)
            if (e.currentTarget.open && !wide) fitToc(true)
          }}
        >
          <summary>
            {t('flow.parts')}
            {!wide && active && <span className="toc-now"> · {titled.find((p) => p.id === active)?.title}</span>}
          </summary>
          <ol>
            {titled.map((p) => (
              <li key={p.id}>
                <a href={`#${p.id}`} onClick={(e) => toPart(e, p.id)} aria-current={active === p.id ? 'location' : undefined} data-testid="toc-link">
                  {p.title}
                </a>
              </li>
            ))}
          </ol>
        </details>
      </nav>
      {tocOpen && !wide && <div className="toc-scrim" aria-hidden="true" onClick={() => closeToc(false)} data-testid="toc-scrim" />}
      <div className="flow-col" ref={col}>
        {parts.map((p) => (
          <section key={p.id} id={p.title ? p.id : undefined} className={`lesson-part ${p.title ? 'titled' : ''}`} tabIndex={p.title ? -1 : undefined} data-testid="lesson-part">
            {p.acts.map((a) => (
              <div key={a.id} className={`flow-step act-${a.kind}`} data-step={a.id} data-kind={a.kind} data-testid="flow-step">
                {render(a)}
              </div>
            ))}
          </section>
        ))}
      </div>
    </div>
  )
}

function SummaryView({ l, plan, next, goId }: { l: L; plan: Activity[]; next: { id: string; title: string } | null; goId: (id: string) => void }) {
  const prog = useProgress()
  const rec = prog.lessons[l.id]
  const finished = !!(rec?.done || rec?.skipped)
  const checks = lessonChecks(plan)
  const c = tallyChecks(checks.map((q) => q.qid), prog)
  const missed = checks.filter((q) => c.wrong.includes(q.qid))
  const unanswered = checks.filter((q) => c.unanswered.includes(q.qid))
  const anchorOf = (qid: string) => plan.find((a) => a.kind === 'check' && a.questions.some((q) => q.qid === qid))
  return (
    <>
      <h2 className="act-title">{t('lesson.summaryTitle')}</h2>
      <ul className="summary-facts">
        <li>
          <Icon name="book" size={15} /> {rec?.skipped ? t('summary.skipped') : finished ? t('summary.read') : t('summary.reachedEnd')}
        </li>
        {checks.length > 0 && (
          <li>
            <Icon name="check" size={15} /> {t(c.corrected ? 'summary.checksShown' : 'summary.checks', { right: c.right, of: c.total, shown: c.corrected })}
            {(missed.length > 0 || unanswered.length > 0) && (
              <span className="muted">
                {' '}
                ·{' '}
                {[...missed, ...unanswered].slice(0, 4).map((q, k) => {
                  const a = anchorOf(q.qid)
                  return a ? (
                    <span key={q.qid}>
                      {k ? ', ' : `${t('summary.revisit')} `}
                      <button className="linkish" onClick={() => goId(a.id)}>
                        {t('summary.questionN', { n: checks.findIndex((c) => c.qid === q.qid) + 1 })}
                      </button>
                    </span>
                  ) : null
                })}
              </span>
            )}
          </li>
        )}
        {l.review.length > 0 && (
          <li>
            <Icon name="cards" size={15} /> {finished ? t('summary.cardsAdded', { n: l.review.length }) : t('summary.cardsWillAdd', { n: l.review.length })}
          </li>
        )}
      </ul>
      <div className="summary-actions">
        {!finished ? (
          <button
            className="btn primary lg"
            onClick={(e) => {
              const actions = e.currentTarget.parentElement
              markLessonDone(l.id)
              toast(t('toast.lessonDone'), t('toast.lessonNote'), 'ok', true)
              // the button goes away: keyboard focus moves to what comes next instead of falling to the page
              requestAnimationFrame(() => actions?.querySelector<HTMLElement>('[data-testid=next-lesson]')?.focus({ preventScroll: true }))
            }}
            data-testid="lesson-done"
          >
            <Icon name="check" size={16} /> {t('lesson.finish')}
          </button>
        ) : null}
        {next && (
          <a className={`btn ${finished ? 'primary' : 'ghost'} lg`} href={lessonHref(next.id)} data-testid="next-lesson">
            {t('lesson.nextLesson')}: {next.title} <Icon name="arrow" size={15} />
          </a>
        )}
      </div>
      <RecallBreak lessonId={l.id} />
      {l.explain.length > 0 && (
        <details className="more explain-more">
          <summary>{t('lesson.explainOptional')}</summary>
          {l.explain.map((e, k) => (
            <ExplainCard key={k} e={e} k={`lesson:${l.id}:${k}`} />
          ))}
        </details>
      )}
    </>
  )
}

/** "Know this already?": every check of the lesson, then an honest result. Passing allows skipping the reading. */
function TestOut({ l, plan, onRead }: { l: L; plan: Activity[]; onRead: (id: string) => void }) {
  const prog = useProgress()
  const checks = lessonChecks(plan)
  const [answered, setAnswered] = useState<Record<string, boolean>>({})
  const all = checks.every((q) => q.qid in answered)
  const right = checks.filter((q) => answered[q.qid])
  const anchorOf = (qid: string) => plan.find((a) => a.kind === 'check' && a.questions.some((q) => q.qid === qid))
  const skipped = !!prog.lessons[l.id]?.skipped
  return (
    <section className="activity act-check testout-view" data-kind="check">
      <ActivityHead kind="check" extra={t('testout.verb', { n: checks.length })} />
      <p className="muted">{t('testout.explain')}</p>
      {checks.map((q, k) => (
        <CheckQuestion key={q.qid} q={q.q} qid={q.qid} n={k + 1} of={checks.length} restore={false} onAnswered={(ok) => setAnswered((s) => (q.qid in s ? s : { ...s, [q.qid]: ok }))} /* the first answer decides: a retry follows the revealed answer */ />
      ))}
      {all && (
        <div className="testout-result" role="status">
          {right.length === checks.length ? (
            <>
              <p>
                <strong>{t('testout.allRight', { n: checks.length })}</strong> {t('testout.honest')}
              </p>
              <div className="summary-actions">
                <button
                  className="btn primary"
                  onClick={() => {
                    markReadingSkipped(l.id)
                    onRead('summary')
                  }}
                  disabled={skipped}
                  data-testid="skip-reading"
                >
                  {t('testout.skip')}
                </button>
                <button className="btn ghost" onClick={() => onRead(plan[0].id)}>
                  {t('testout.readAnyway')}
                </button>
              </div>
            </>
          ) : (
            <>
              <p>
                <strong>{t('testout.some', { right: right.length, of: checks.length })}</strong> {t('testout.readThese')}
              </p>
              <ul>
                {checks
                  .filter((q) => !answered[q.qid])
                  .map((q) => {
                    const a = anchorOf(q.qid)
                    const src = a && a.kind === 'check' ? sectionOf(plan, a.anchor) : undefined
                    return src && src.kind === 'learn' ? (
                      <li key={q.qid}>
                        <button className="linkish" onClick={() => onRead(src.id)}>
                          {src.section.title}
                        </button>
                      </li>
                    ) : null
                  })}
              </ul>
              <button className="btn primary" onClick={() => onRead(plan[0].id)}>
                {t('testout.start')}
              </button>
            </>
          )}
        </div>
      )}
    </section>
  )
}

/** Depth and sources, reachable from every activity without losing the place. A modal side sheet, rendered at the
 * end of the document: inside the page it shared the page's stacking layer (its entry animation makes one), so the
 * sticky site header covered the sheet's title and its close button. */
function DeeperPanel({ l, onClose }: { l: L; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const opener = useRef<Element | null>(document.activeElement)
  // a link chosen in it, a tap outside it and the phone's Back close it too; one overlay at a time (lib/overlay.ts)
  useOverlay(true, onClose, { id: 'deeper', root: ref, modal: true })
  useEffect(() => {
    focusQuietly(ref.current) // the page behind keeps its place
    const f = (e: KeyboardEvent) => {
      if (e.key === 'Escape') return onClose()
      if (e.key !== 'Tab' || !ref.current) return
      // a modal keeps keyboard focus inside it: Tab past the last control comes back to the first, and Shift+Tab
      // visible controls only: links inside a closed section cannot take focus
      const all = [...ref.current.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), summary, input, select, textarea, [tabindex]:not([tabindex="-1"])')].filter((el) => el.getClientRects().length > 0)
      if (!all.length) return
      const first = all[0], last = all[all.length - 1]
      const at = document.activeElement
      const onPanel = at === ref.current || !ref.current.contains(at) // the panel itself has focus when it opens
      if (e.shiftKey && (at === first || onPanel)) (e.preventDefault(), last.focus())
      else if (!e.shiftKey && (at === last || onPanel)) (e.preventDefault(), first.focus())
    }
    window.addEventListener('keydown', f)
    const back = opener.current
    return () => {
      window.removeEventListener('keydown', f)
      ;(back as HTMLElement | null)?.focus?.({ preventScroll: true }) // back to the button, where the learner was reading
    }
  }, [onClose])
  const deep = l.sections.filter((s) => s.depth)
  const items: { title: string; body: ReactNode }[] = [
    ...deep.map((s) => ({ title: s.title, body: <Md text={s.body} /> })),
    ...(l.limits ? [{ title: t('lesson.limits'), body: <Md text={l.limits} /> }] : []),
    ...(l.enterprise ? [{ title: t('lesson.enterprise'), body: <Md text={l.enterprise} /> }] : []),
  ]
  return createPortal(
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet deeper-panel" role="dialog" aria-modal="true" aria-labelledby="deeper-title" ref={ref} tabIndex={-1} onClick={(e) => e.stopPropagation()}>
        <div className="sheet-h">
          <h2 id="deeper-title">{t('lesson.deeperRefs')}</h2>
          <button className="icon-btn" onClick={onClose} aria-label={t('ui.close')} data-testid="deeper-close">
            <Icon name="x" size={18} />
          </button>
        </div>
        {items.map((it) => (
          <details key={it.title} className="more">
            <summary>{it.title}</summary>
            {it.body}
          </details>
        ))}
        {l.references.length > 0 && (
          <>
            <h3>{t('lesson.references')}</h3>
            <Refs refs={l.references} />
          </>
        )}
        <p className="muted small">
          <strong>{t('lesson.testedOn')}</strong> {l.supports}
        </p>
        {l.recording?.experiment && (
          <p className={`small ${l.recording.experiment.restored ? 'muted' : 'warn'}`} data-testid="experiment">
            <strong>{t('lesson.experiment', { id: l.recording.experiment.id })}</strong>{' '}
            {l.recording.experiment.restored
              ? t('lesson.experimentRestored', { snapshots: l.recording.experiment.snapshot.length, checks: l.recording.experiment.verify.length })
              : t('lesson.experimentNotRestored')}
          </p>
        )}
      </div>
    </div>,
    document.body,
  )
}

/** What the learner's diagnostic for this path said about this lesson, if they took it. */
function DiagNote({ trackId, lessonId }: { trackId: string; lessonId: string }) {
  const { cur, lang } = useApp()
  const prog = useProgress()
  const dk = cur?.diagnostics?.[trackId]?.track || trackId
  const rec = prog.diagnostics[dk]
  const finished = !!rec?.finished
  const [d, setD] = useState<Diagnostic | null>(null)
  useEffect(() => {
    if (finished && cur?.diagnostics?.[trackId]) api.diagnostic(dk, lang).then(setD, () => setD(null))
  }, [finished, trackId, dk, lang, cur])
  if (!finished || !d || !cur) return null
  const r = classify(cur, d, rec).byTarget[lessonId]
  if (!r || r.verdict === 'unassessed') return null
  return (
    <p className="small diag-note" data-testid="diag-note">
      {t('diag.lessonNote')}{' '}
      <span className={`pill diag-v ${r.verdict === 'study' ? 'warn' : r.verdict === 'review' ? 'info' : 'muted'}`}>{t(`diag.v.${r.verdict}`)}</span> ({why(r)}) ·{' '}
      <a href={diagnosticHref(dk)}>{t('diag.cardResults')}</a>
    </p>
  )
}
