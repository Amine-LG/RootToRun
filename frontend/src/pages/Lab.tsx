import { useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { PageActions } from '../components/Contribute'
import { Prereqs } from '../components/Prereqs'
import { ActivityHead, Guess, scrollNear } from '../components/Activity'
import { PageBar } from '../components/PageHead'
import { reveal } from '../lib/reveal'
import ChallengeRun from './Challenge'
import { CleanupReportView, PreflightBox } from '../components/ClusterSafety'
import { CommandBlock, LiveTerminal } from '../components/Term'
import { toast } from '../components/Toast'
import { Callout, fmtDate, Icon, LabStatusPill, PageSkeleton, PresentButton, Refs } from '../components/ui'
import { api, cluster, type CleanupReport, type Cmd, type Entry, type Lab, type LabData, type Recording, type Reveal, type Step, type Verification } from '../lib/data'
import { useApp, useLoad } from '../lib/app'
import { t } from '../lib/i18n'
import { Md, MdInline } from '../lib/md'
import { navigate, useLocation } from '../lib/router'
import { canonical, labHref, refOf, trackHref } from '../lib/urls'
import { attemptRev, getProgress, labStatus, labUpdate, restartAttempt, setLast, useProgress, XP, type IncidentState, type LabProgress } from '../lib/progress'
import '../practice.css'

// A lab is a guided investigation: the current step is the only thing in focus. Background, files and
// depth are one click away. In cluster mode the environment is a compact bar and the terminal opens on demand.

export function entryIndex(rec: Recording | null, extra: Entry[] = []) {
  const m = new Map<string, Entry>()
  for (const e of [...(rec?.entries || []), ...extra]) if (!m.has(`${e.step}|${e.cmd}`)) m.set(`${e.step}|${e.cmd}`, e)
  return (where: string, c: Cmd) => m.get(`${where}|${c.cmd}`)
}

const firstSentence = (text: string) => {
  const s = (text || '').replace(/\s+/g, ' ').trim()
  const m = /^(.{40,220}?[.!?])(\s|$)/.exec(s)
  return m ? m[1] : s
}

/** The one sentence that says what the learner will be able to do after this lab (shared by guided labs and incidents). */
function Goal({ lab }: { lab: Lab }) {
  return (
    <div className="goal-line">
      <Icon name="target" size={16} />
      <div>
        <span className="goal-lbl">{t('lab.goal')}</span>
        <span className="goal-text">
          <MdInline text={firstSentence(lab.objective)} />
        </span>
      </div>
    </div>
  )
}

/** Where "back" goes: the lesson the learner came from (?from=<lesson address>, old /lesson/<id> addresses included),
 *  else the list. Only addresses of this site's lessons. */
function useReturn(isInc: boolean, id: string): { href: string; label: string } {
  const loc = useLocation()
  const { cur } = useApp()
  const from = new URLSearchParams(loc.search).get('from') || ''
  const m = from.startsWith('/') ? refOf(from) : null
  if (m?.kind === 'lesson' && cur?.lessons[m.id]) return { href: canonical(from), label: t('lab.backToLesson', { title: cur.lessons[m.id].title }) }
  if (cur?.labs[id]?.kind === 'challenge') return { href: '/challenges', label: t('nav.challenges') }
  return { href: isInc ? '/incidents' : '/labs', label: isInc ? t('nav.incidents') : t('nav.labs') }
}

export default function LabPage({ id }: { id: string }) {
  const { lang, cur } = useApp()
  const { data, err } = useLoad(() => api.lab(id, lang), [id, lang])
  const isInc = data?.lab.kind === 'incident'
  const isCh = data?.lab.kind === 'challenge'
  const back = useReturn(!!isInc, id)
  const loc = useLocation()
  useEffect(() => {
    if (data) setLast(`${labHref(id)}${loc.search}`, data.lab.title) // the exact place: step or stage, and the lesson to return to
  }, [data, id, loc.search])
  // Restarting an incident or a challenge records it (lib/progress.ts restartAttempt) and remounts the run, so nothing
  // of the previous attempt stays on screen; the URL names the first stage again, and focus goes to the title.
  const [attempt, setAttempt] = useState(0)
  // the saved attempt is part of the key too: a restart made in another tab (or an imported newer attempt) remounts the
  // run here, so its handlers belong to the current attempt instead of rejecting every answer as late
  const rev = attemptRev(useProgress().labs[id])
  const [said, setSaid] = useState('')
  const title = useRef<HTMLHeadingElement>(null)
  const restart = () => {
    restartAttempt(id)
    const sp = new URLSearchParams(loc.search)
    if (isInc) sp.set('stage', 'symptom')
    const q = sp.toString()
    navigate(`${labHref(id)}${q ? `?${q}` : ''}`, { replace: true })
    setAttempt((n) => n + 1)
    setSaid(t('ex.restarted'))
    requestAnimationFrame(() => (title.current?.focus({ preventScroll: true }), scrollNear(title.current)))
  }
  if (err) return <div className="page"><Callout tone="bad">{err}</Callout></div>
  if (!data || !cur) return <div className="page"><PageSkeleton /></div>
  return (
    <div className={`page lab player practice ${isInc ? 'incident' : ''}`}>
      <PageBar className="lesson-top" actions={<PageActions ctx={{ type: data.lab.kind, id, title: data.lab.title, area: cur.tracks.find((tr) => tr.modules.includes(data.lab.module))?.title, source: data.lab.source }} />}>
        <a className="back" href={back.href} data-testid="lab-back">
          <Icon name="back" size={15} /> {back.label}
        </a>
        <span className="grow" />
        <PresentButton key={id} />
      </PageBar>
      <LabHeader data={data} title={title} />
      {isInc ? <IncidentRun key={`${attempt}:${rev}`} data={data} onRestart={restart} /> : isCh ? <ChallengeRun key={`${attempt}:${rev}`} data={data} onRestart={restart} /> : <LabRun data={data} />}
      <p className="sr-only" role="status" aria-live="polite">{said}</p>
    </div>
  )
}

function LabHeader({ data, title }: { data: LabData; title: RefObject<HTMLHeadingElement> }) {
  const { lab, recording: rec } = data
  const prog = useProgress()
  const { cur } = useApp()
  return (
    <header className="lab-h">
      <ActivityHead kind={lab.kind === 'lab' ? 'practise' : 'solve'} extra={lab.kind === 'incident' ? t('lab.solveVerb') : lab.kind === 'challenge' ? t('ch.verb') : t('lab.practiseVerb')} />
      <h1 className="lesson-title" ref={title} tabIndex={-1}>{lab.title}</h1>
      {lab.subtitle && <p className="subtitle">{lab.subtitle}</p>}
      <p className="lede">{lab.summary}</p>
      <div className="lesson-meta">
        <span>
          <Icon name="clock" size={14} /> {t('ui.minutes', { n: lab.minutes })}
        </span>
        {rec?.ok ? (
          <span className="pill ok" title={t('lab.recordedHelp')}>
            <Icon name="check" size={13} /> {t('lab.testedOn', { v: rec.cluster.openshift || '?', date: fmtDate(rec.recorded_at) })}
          </span>
        ) : (
          <span className="pill warn">{t('lab.notRecorded')}</span>
        )}
        <LabStatusPill s={labStatus(prog.labs[lab.id])} />
      </div>
      <Prereqs tools={cur?.labs[lab.id]?.tools ?? []} where="lab" versions={{ oc: rec?.cluster?.oc }} />
    </header>
  )
}

// ---------------------------------------------------------------- environment: one line in practice mode, a compact bar with a cluster
export function Environment({ lab, onVerified }: { lab: Lab; onVerified?: (v: Verification) => void }) {
  const { meta, live } = useApp()
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad' | 'info' | 'warn'; text: string } | null>(null)
  const [consent, setConsent] = useState(false)
  const [state, setState] = useState<{ project?: { exists?: boolean } } | null>(null)
  const [ver, setVer] = useState<Verification | null>(null)
  const [cleanRep, setCleanRep] = useState<CleanupReport | null>(null)
  const refresh = () => cluster.state(lab.id).then(setState, () => setState(null))
  useEffect(() => {
    if (live) refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, lab.id])

  if (meta?.mode !== 'cluster')
    return (
      <p className="env-line">
        <Icon name="play" size={14} /> {t('env.practiceLine')}{' '}
        <a href="/about#own-cluster">{t('env.ownCluster')}</a>
      </p>
    )
  if (!live)
    return (
      <p className="env-line warn">
        <Icon name="plug" size={14} /> {t('env.connectText')} <a href="/connections">{t('nav.connections')}</a>
      </p>
    )
  const exists = !!state?.project?.exists
  async function act(kind: 'prepare' | 'verify' | 'cleanup') {
    setBusy(kind)
    setMsg(null)
    try {
      if (kind === 'prepare') {
        const r: any = await cluster.prepare(lab.id, consent)
        if (r.needs_elevated) setMsg({ tone: 'warn', text: r.reason })
        else setMsg(r.ok ? { tone: 'ok', text: lab.kind === 'incident' ? t('env.incidentReady') : t('env.ready') } : { tone: 'bad', text: r.reason || t('env.failed') })
      } else if (kind === 'verify') {
        const v = await cluster.verify(lab.id)
        setVer(v)
        onVerified?.(v)
      } else {
        const r: any = await cluster.cleanup(lab.id)
        setCleanRep(r.report || null)
        const tone = r.state === 'clean' ? 'ok' : r.state === 'blocked' || r.ok === false ? 'bad' : 'info'
        setMsg({ tone, text: r.reason || t(`cleanup.result.${r.state}` as 'cleanup.result.clean') })
        setVer(null)
      }
    } catch (e) {
      setMsg({ tone: 'bad', text: String((e as Error).message) })
    }
    setBusy('')
    refresh()
  }
  return (
    <div className="env live">
      <div className="env-h">
        <span className="pulse" />
        <strong>{t('env.liveTitle')}</strong>
        <code>{lab.namespace}</code>
        <span className={`pill ${exists ? 'ok' : 'muted'}`}>{exists ? t('env.exists') : t('env.absent')}</span>
        <span className="grow" />
        <div className="env-actions">
          <button className={`btn sm ${exists ? '' : 'primary'}`} onClick={() => act('prepare')} disabled={!!busy || (lab.elevated && !consent)} data-testid="prepare">
            {busy === 'prepare' ? t('ui.working') : lab.kind === 'incident' ? t('env.startIncident') : lab.kind === 'challenge' ? (exists ? t('env.resume') : t('ch.start')) : exists ? t('env.resume') : t('env.prepare')}
          </button>
          <button className={`btn sm ${exists ? 'primary' : ''}`} onClick={() => act('verify')} disabled={!!busy || !exists} data-testid="verify">
            {busy === 'verify' ? t('ui.working') : lab.kind === 'challenge' ? t('ch.grade') : t('env.verify')}
          </button>
          <button className="btn sm ghost" onClick={() => act('cleanup')} disabled={!!busy || !exists}>
            {busy === 'cleanup' ? t('ui.working') : t('env.cleanup')}
          </button>
        </div>
      </div>
      {lab.elevated && (
        <label className="check consent">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>
            <strong>{t('env.elevatedTitle')}</strong> {lab.elevated_why || t('env.elevatedText')}
          </span>
        </label>
      )}
      {!exists && <PreflightBox labId={lab.id} />}
      {msg && (
        <div className={`env-msg ${msg.tone}`} role="status">
          {msg.text}
        </div>
      )}
      {cleanRep && <CleanupReportView rep={cleanRep} />}
      {ver && <Checks v={ver} live />}
    </div>
  )
}

export function Checks({ v, live, title }: { v: Verification; live?: boolean; title?: string }) {
  const tone = v.verdict === 'verified' ? 'ok' : v.verdict === 'partial' ? 'warn' : v.verdict === 'not-applicable' ? 'muted' : 'bad'
  return (
    <div className={`checks ${tone}`}>
      <div className="checks-h">
        {/* "Verified" is earned on the learner's own cluster: a recorded result says where it passed instead */}
        <span className={`pill ${tone}`}>{!live && v.verdict === 'verified' ? t('checks.recordedPass') : t(`verdict.${v.verdict}` as 'verdict.verified')}</span>
        <span className="muted small">{title || (live ? t('checks.live') : t('checks.recorded'))}</span>
      </div>
      <ul>
        {v.results.map((r) => (
          <li key={r.id} className={r.status}>
            <Icon name={r.status === 'pass' ? 'check' : r.status === 'error' ? 'info' : 'x'} size={15} />
            <div>
              <div>
                {r.title}
                {r.status === 'error' && <span className="pill warn small-pill"> {t('checks.couldNotCheck')}</span>}
              </div>
              <div className="observed mono">{r.observed}</div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** What monitoring would show before anyone investigates. Each incident lists these checks itself (`symptom_checks`:
 *  availability, the Route's answer, a timeout, a 403); every other check states the cause (a field's value, a missing
 *  permission, a policy) and appears only with the answer, in the debrief. Without a list, the check type decides. */
const SYMPTOM_CHECKS = new Set(['deployment_ready', 'route_http', 'endpoints', 'pods'])

function SymptomChecks({ lab, v, live }: { lab: Lab; v: Verification; live: boolean }) {
  const type = Object.fromEntries(lab.checks.map((c) => [c.id, c.type]))
  const listed = lab.symptom_checks?.length ? new Set(lab.symptom_checks) : null
  const shown = v.results.filter((r) => (listed ? listed.has(r.id) : SYMPTOM_CHECKS.has(type[r.id])))
  const hidden = v.results.length - shown.length
  return (
    <details className="more" data-testid="symptom-checks">
      <summary>{t('inc.whatMonitoringSees')}</summary>
      {shown.length > 0 && <Checks v={{ ...v, results: shown }} title={live ? t('inc.healthRecorded') : t('inc.healthNow')} />}
      {hidden > 0 && <p className="muted small" data-testid="symptom-checks-hidden">{t('inc.checksHidden', { n: hidden })}</p>}
    </details>
  )
}

export function TerminalDrawer({ lab, seed }: { lab: Lab; seed?: { cmd: string; n: number } }) {
  const { live } = useApp()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (seed) setOpen(true)
  }, [seed])
  if (!live) return null
  const toggle = () => {
    setOpen(!open)
    if (!open) reveal(box.current) // the terminal mounts below the button; show it from its title bar down
  }
  return (
    <div className="term-drawer" ref={box}>
      <button className="btn sm" onClick={toggle} aria-expanded={open}>
        <Icon name="terminal" size={15} /> {open ? t('lab.hideTerminal') : t('lab.openTerminal')}
      </button>
      {open && (
        <div className="fade-in" style={{ marginTop: 10 }}>
          <LiveTerminal namespace={lab.namespace} labId={lab.id} seed={seed} height={320} />
        </div>
      )}
    </div>
  )
}

function Before({ lab, find }: { lab: Lab; find: (w: string, c: Cmd) => Entry | undefined }) {
  const files = Object.entries(lab.files)
  const elevated = lab.elevated_setup ?? []
  if (!lab.background && !lab.setup.length && !elevated.length && !files.length && !lab.commands.length) return null
  return (
    <details className="more before">
      <summary>{t('lab.beforeYouStart')}</summary>
      {lab.background && <Md text={lab.background} />}
      {lab.setup.length > 0 && (
        <details className="more">
          <summary>{t('lab.setupShows', { n: lab.setup.length })}</summary>
          {lab.setup.map((y, i) => (
            <pre key={i} className="code yaml">
              <code>{y}</code>
            </pre>
          ))}
        </details>
      )}
      {elevated.length > 0 && (
        <details className="more" data-testid="elevated-setup">
          <summary>{t('lab.elevatedShows', { n: elevated.length })}</summary>
          {elevated.map((y, i) => (
            <pre key={i} className="code yaml">
              <code>{y}</code>
            </pre>
          ))}
        </details>
      )}
      {files.length > 0 && (
        <details className="more">
          <summary>{t('lab.files', { n: files.length })}</summary>
          {files.map(([p, y]) => (
            <div key={p}>
              <div className="file-name mono">lab/{p}</div>
              <pre className="code yaml">
                <code>{y}</code>
              </pre>
            </div>
          ))}
        </details>
      )}
      {lab.commands.length > 0 && (
        <details className="more">
          <summary>{t('lab.quickRef', { n: lab.commands.length })}</summary>
          {lab.commands.map((c, i) => (
            <CommandBlock key={i} c={c} entry={find('commands', c)} labId={lab.id} where="commands" index={i} compact />
          ))}
        </details>
      )}
    </details>
  )
}

// ---------------------------------------------------------------- guided lab
function LabRun({ data }: { data: LabData }) {
  const { lab, recording: rec } = data
  const { live } = useApp()
  const prog = useProgress()
  const lp = prog.labs[lab.id]
  const find = useMemo(() => entryIndex(rec), [rec])
  const loc = useLocation()
  const stepDoneOk = (sid: string) => !!lp?.stepResults?.[sid]?.matched
  // The URL names the step (?step=<id>, or "finish"); without it, resume at the saved step or the first open one.
  const want = new URLSearchParams(loc.search).get('step')
  // Where to resume is decided once, when the lab opens; after that only the URL moves the learner (finishing a step
  // must never jump to the next one by itself).
  const [resumeAt] = useState(() => {
    const pos = lp?.pos ? lab.steps.findIndex((s) => s.id === lp.pos) : -1
    if (pos >= 0) return pos
    const firstOpen = lab.steps.findIndex((s) => !stepDoneOk(s.id))
    return firstOpen === -1 ? 0 : firstOpen
  })
  let cur = want === 'finish' ? lab.steps.length : lab.steps.findIndex((s) => s.id === want)
  if (cur < 0 && want && /^\d+$/.test(want)) cur = Math.min(Number(want), lab.steps.length) - 1
  if (cur < 0) cur = resumeAt
  const [liveVer, setLiveVer] = useState<Verification | null>(null)
  const [seed, setSeed] = useState<{ cmd: string; n: number } | undefined>()
  const top = useRef<HTMLDivElement>(null)
  const allDone = lab.steps.length > 0 && lab.steps.every((s) => stepDoneOk(s.id))
  const finished = cur >= lab.steps.length
  const goStep = (i: number) => {
    const sp = new URLSearchParams(loc.search)
    sp.set('step', i >= lab.steps.length ? 'finish' : lab.steps[i].id)
    navigate(`${labHref(lab.id)}?${sp.toString()}`, { replace: true })
    if (i < lab.steps.length) labUpdate(lab.id, (l) => void (l.pos = lab.steps[i].id))
    scrollNear(top.current)
  }

  /** A step counts only when every command did what was expected; replaying a recording and running live are recorded separately. */
  function stepResult(s: Step, matched: boolean, live: boolean) {
    const before = getProgress().labs[lab.id]
    if (before?.stepResults?.[s.id]?.matched && !live) return
    // "practised on recordings" means every step was worked through on recordings; live runs are evidence of another kind
    const allAfter = lab.steps.every((x) => (x.id === s.id ? matched && !live : before?.stepResults?.[x.id]?.matched && before?.stepResults?.[x.id]?.source === 'recording'))
    const firstReplay = !live && allAfter && !before?.replayed
    if (firstReplay) toast(t('toast.labPractised'), t('toast.replayedNote'), 'ok', true)
    labUpdate(lab.id, (l) => {
      l.stepResults = { ...(l.stepResults || {}), [s.id]: { at: Date.now(), source: live ? 'live' : 'recording', matched } }
      if (matched) l.steps = { ...(l.steps || {}), [s.id]: Date.now() }
      if (firstReplay) l.replayed = Date.now()
    }, firstReplay ? XP.labReplay : 0)
  }
  function onVerified(v: Verification) {
    setLiveVer(v)
    if (v.verdict === 'verified' && !lp?.verified) toast(t('toast.verified'), t('toast.verifiedNote'), 'ok', true)
    labUpdate(lab.id, (l) => {
      const now = Date.now()
      l.verdict = v.verdict
      l.verdictAt = now
      if (v.verdict === 'verified') l.verified = now // the latest success; a later failure (verdictAt > verified) shows
    }, v.verdict === 'verified' && !lp?.verified ? XP.labVerified : 0)
  }

  return (
    <>
      <Goal lab={lab} />
      <Environment lab={lab} onVerified={onVerified} />
      <Before lab={lab} find={find} />

      <div ref={top} className="anchor" />
      {lab.steps.length > 0 && (
        <nav className="lesson-steps" aria-label={t('lab.steps')}>
          {lab.steps.map((s, i) => (
            <button
              key={s.id}
              className={`ls ${i === cur ? 'on' : ''} ${stepDoneOk(s.id) ? 'past' : lp?.stepResults?.[s.id] ? 'off' : ''}`}
              onClick={() => goStep(i)}
              aria-current={i === cur ? 'step' : undefined}
              aria-label={t('lab.stepAria', { n: i + 1, of: lab.steps.length, title: s.title })}
              title={s.title}
            >
              <span className="ls-bar" />
              <span className="ls-label">{s.title}</span>
            </button>
          ))}
          <button className={`ls finish-ls ${finished ? 'on' : ''} ${allDone ? 'past' : ''}`} onClick={() => goStep(lab.steps.length)} aria-label={t('lab.finish')} title={t('lab.finish')}>
            <span className="ls-bar" />
            <span className="ls-label">{t('lab.finish')}</span>
          </button>
        </nav>
      )}

      {!finished && lab.steps[cur] && (
        <StepView
          key={lab.steps[cur].id}
          lab={lab}
          s={lab.steps[cur]}
          n={cur}
          find={find}
          done={stepDoneOk(lab.steps[cur].id)}
          onResult={(matched, live) => stepResult(lab.steps[cur], matched, live)}
          onBack={cur > 0 ? () => goStep(cur - 1) : undefined}
          onNext={() => goStep(cur + 1)}
          onSeed={(c) => setSeed({ cmd: c, n: Date.now() })}
        />
      )}

      {(finished || lab.steps.length === 0) && (
        <section className="finish">
          {allDone && (
            <div className="finish-banner fade-in">
              <Icon name="check" size={22} />
              <div>
                <strong>{t('lab.practiceDone')}</strong>
                <span>{live ? t('lab.verifyHint') : t('lab.practiceDoneText')}</span>
              </div>
            </div>
          )}
          <h2 className="step-h2">{t('lab.finishTitle')}</h2>
          {live ? (
            liveVer ? <Checks v={liveVer} live /> : <p className="muted">{t('lab.verifyHint')}</p>
          ) : rec?.verify_after && rec.verify_after.verdict !== 'not-applicable' ? (
            <Checks v={rec.verify_after} />
          ) : (
            <p className="muted">{t('lab.noChecks')}</p>
          )}
          <Deeper lab={lab} />
          <div className="lesson-nav">
            <button className="btn ghost" onClick={() => goStep(Math.max(0, lab.steps.length - 1))}>
              <Icon name="back" size={15} /> {t('ui.back')}
            </button>
            <a className="btn primary" href={lab.kind === 'incident' ? '/incidents' : '/labs'}>
              {t('lab.moreLabs')} <Icon name="arrow" size={15} />
            </a>
          </div>
        </section>
      )}
      <TerminalDrawer lab={lab} seed={seed} />
    </>
  )
}

function Deeper({ lab }: { lab: Lab }) {
  return (
    <div className="deeper">
      <h3>{t('lesson.goDeeper')}</h3>
      {lab.questions.length > 0 && (
        <details className="more">
          <summary>{t('lab.questions')}</summary>
          <div className="qa">
            {lab.questions.map((q, i) => (
              <details key={i}>
                <summary>
                  <Md text={q.q} />
                </summary>
                <Md text={q.a} />
              </details>
            ))}
          </div>
        </details>
      )}
      {lab.variations.length > 0 && (
        <details className="more">
          <summary>{t('lab.variations')}</summary>
          <ul>
            {lab.variations.map((v, i) => (
              <li key={i}>
                <Md text={v} />
              </li>
            ))}
          </ul>
        </details>
      )}
      {lab.troubleshooting.length > 0 && (
        <details className="more">
          <summary>{t('lab.troubleshooting')}</summary>
          {lab.troubleshooting.map((x, i) => (
            <div key={i}>
              <strong>{x.problem}</strong>
              <Md text={x.hint} />
            </div>
          ))}
        </details>
      )}
      {lab.enterprise && (
        <details className="more">
          <summary>{t('lesson.enterprise')}</summary>
          <Md text={lab.enterprise} />
        </details>
      )}
      <details className="more">
        <summary>{t('lesson.references')}</summary>
        <Refs refs={lab.references} />
        <p className="muted small">{lab.supports}</p>
      </details>
    </div>
  )
}

function StepView({ lab, s, n, find, done, onResult, onBack, onNext, onSeed }: { lab: Lab; s: Step; n: number; find: (w: string, c: Cmd) => Entry | undefined; done: boolean; onResult: (matched: boolean, live: boolean) => void; onBack?: () => void; onNext: () => void; onSeed: (c: string) => void }) {
  const { live } = useApp()
  const prog = useProgress()
  const guessKey = `guess:lab:${lab.id}:${s.id}`
  const [predicted, setPredicted] = useState(!s.predict || done || !!prog.guesses[guessKey])
  // per command: did it do what the lab expects (exit status vs `expect`), and was it a replay or a live run
  const [ran, setRan] = useState<Map<number, { matched: boolean; live: boolean }>>(new Map())
  const [check, setCheck] = useState<Verification | null>(null)
  const [checking, setChecking] = useState(false)
  const runnable = s.commands.map((c, i) => (c.skip ? -1 : i)).filter((i) => i >= 0)
  const allRan = runnable.every((i) => ran.has(i))
  const allMatched = allRan && runnable.every((i) => ran.get(i)!.matched)
  const complete = done || allMatched
  const wentWrong = allRan && !allMatched
  useEffect(() => {
    if (allRan && predicted) onResult(allMatched, runnable.some((i) => ran.get(i)!.live))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allRan, allMatched, predicted])
  const stepChecks = [...new Set([...s.checks, ...s.wait_for])]
  const left = runnable.length - runnable.filter((i) => ran.has(i)).length

  return (
    <section className="lesson-step lab-step" aria-labelledby={`st-${s.id}`}>
      <div className="step-top">
        <span className="step-count">{t('lab.stepN', { n: n + 1, of: lab.steps.length })}</span>
        {complete && (
          <span className="pill ok step-done">
            <Icon name="check" size={12} /> {t('lab.stepDone')}
          </span>
        )}
      </div>
      <h2 className="step-h2" id={`st-${s.id}`}>
        {s.title}
      </h2>
      <Md text={s.do} className="step-do" />
      {s.predict && <Guess p={s.predict} k={guessKey} onDone={() => setPredicted(true)} label={t('lab.guessFirst')} />}
      {predicted && (
        <div className="cmds">
          {s.commands.map((c, i) => (
            <CommandBlock
              key={i}
              c={c}
              entry={find(s.id, c)}
              labId={lab.id}
              where={s.id}
              index={i}
              onResult={(res) => setRan((r) => new Map(r).set(i, { matched: res.matched && res.status !== 'error', live: res.source === 'live' }))}
            />
          ))}
        </div>
      )}
      {wentWrong && (
        <Callout tone="warn" title={t('lab.unexpectedTitle')}>
          {live ? t('lab.unexpectedLive') : t('lab.unexpectedRecorded')}
        </Callout>
      )}
      {live && predicted && s.commands.some((c) => !c.skip && c.as !== 'admin') && (
        <p className="muted small">
          {t('lab.ownTerminal')}{' '}
          <button className="linkish" onClick={() => onSeed(s.commands.find((c) => !c.skip && c.as !== 'admin')!.cmd)}>
            {t('lab.openTerminal')}
          </button>
        </p>
      )}
      {(complete || wentWrong) && predicted && (s.observe || s.why) && (
        <div className="debrief fade-in">
          {s.observe && (
            <div>
              <div className="debrief-h">
                <Icon name="eye" size={15} /> {t('lab.observe')}
              </div>
              <Md text={s.observe} />
            </div>
          )}
          {s.why && (
            <div>
              <div className="debrief-h">
                <Icon name="bulb" size={15} /> {t('lab.why')}
              </div>
              <Md text={s.why} />
            </div>
          )}
        </div>
      )}
      {live && stepChecks.length > 0 && predicted && (
        <div className="row">
          <button
            className="btn sm"
            disabled={checking}
            onClick={async () => {
              setChecking(true)
              try {
                setCheck(await cluster.check(lab.id, stepChecks))
              } finally {
                setChecking(false)
              }
            }}
          >
            {checking ? t('ui.working') : t('lab.checkStep')}
          </button>
        </div>
      )}
      {check && <Checks v={check} live title={t('checks.step')} />}
      <div className="lesson-nav">
        {onBack ? (
          <button className="btn ghost" onClick={onBack}>
            <Icon name="back" size={15} /> {t('ui.back')}
          </button>
        ) : (
          <span />
        )}
        <span className="nav-right">
          {!complete && !wentWrong && predicted && <span className="muted small">{live ? t('lab.runAllLive') : t('lab.runAll', { n: left })}</span>}
          <button className={`btn ${complete ? 'primary' : 'ghost'}`} onClick={onNext} data-testid="next-step">
            {n + 1 < lab.steps.length ? t('lab.nextStep') : t('lab.toFinish')} <Icon name="arrow" size={15} />
          </button>
        </span>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------- incident
// Solve: symptom → investigate → diagnose → debrief. The learner's place, hints and draft survive a reload. Findings of
// the investigation commands appear only after they are run. Writing a diagnosis and comparing it with the root cause
// is a self-assessment; only state checks on a real cluster verify a repair.
const STAGES = ['symptom', 'investigate', 'diagnose', 'debrief'] as const
type Stage = (typeof STAGES)[number]
const HINT_GAP_S = 15

/** What a restart would discard that the learner wrote or decided: worth a confirmation. `draft` is the text on screen,
 * which the debounced save may not have stored yet. */
const wroteSomething = (l: LabProgress | undefined, draft = '') =>
  draft.trim().length >= 20 || !!(l && ((l.incident?.draft || '').trim().length >= 20 || l.diagnosis?.trim() || l.selfCheck))

/** A request answered after a restart (or after leaving the page) belongs to an attempt that is over: `current()` says
 * whether this run is still on screen and still in the attempt it started in, before any side effect of an answer. */
export function useAttemptGuard(labId: string): () => boolean {
  const alive = useRef(true)
  const [rev] = useState(() => attemptRev(getProgress().labs[labId]))
  useEffect(() => {
    alive.current = true
    return () => void (alive.current = false)
  }, [])
  return () => alive.current && attemptRev(getProgress().labs[labId]) === rev
}

/** "Restart": a new attempt at an incident or a challenge, offered once the attempt has begun. */
export function RestartAttempt({ labId, kind, begun, onRestart, draft }: { labId: string; kind: 'incident' | 'challenge'; begun: boolean; onRestart: () => void; draft?: string }) {
  if (!begun) return null
  return (
    <div className="lab-restart">
      <button
        type="button"
        className="btn ghost sm"
        data-testid="restart-attempt"
        aria-describedby={`restart-note-${labId}`}
        onClick={() => {
          if (wroteSomething(getProgress().labs[labId], draft) && !window.confirm(t('ex.restartConfirm'))) return
          onRestart()
        }}
      >
        <Icon name="refresh" size={14} /> {t(kind === 'incident' ? 'ex.restartIncident' : 'ex.restartChallenge')}
      </button>
      <p className="muted small" id={`restart-note-${labId}`}>{t('ex.restartNote')}</p>
    </div>
  )
}

function IncidentRun({ data, onRestart }: { data: LabData; onRestart: () => void }) {
  const { lab, recording: rec } = data
  const { lang, live } = useApp()
  const prog = useProgress()
  const loc = useLocation()
  const lp = prog.labs[lab.id]
  const current = useAttemptGuard(lab.id)
  const saved: IncidentState = lp?.incident || {}
  const urlStage = new URLSearchParams(loc.search).get('stage') as Stage | null
  const answerSeen = !!(lp?.revealed || lp?.verified)
  // the URL first, then the stage of the current attempt (a restart sets it back to 0), then a revealed answer
  const asked: Stage = urlStage && STAGES.includes(urlStage) ? urlStage : STAGES[saved.stage ?? (answerSeen ? 3 : 0)] || 'symptom'
  const initial: Stage = asked === 'debrief' && !answerSeen ? 'diagnose' : asked // the debrief needs the answer
  const [stage, setStage] = useState<Stage>(initial)
  const [hints, setHints] = useState<string[]>([])
  const [diag, setDiag] = useState(saved.draft ?? lp?.diagnosis ?? '')
  const [reveal, setReveal] = useState<Reveal | null>(null)
  const [liveVer, setLiveVer] = useState<Verification | null>(null)
  const [seed, setSeed] = useState<{ cmd: string; n: number } | undefined>()
  const [ran, setRan] = useState<Set<number>>(new Set((saved.replays || []).map(Number)))
  const top = useRef<HTMLDivElement>(null)
  const find = useMemo(() => entryIndex(rec, reveal?.fix_recording || []), [rec, reveal])
  const usedHints = saved.hints ?? lp?.hints ?? 0 // hints shown in this attempt (older records: all hints used)
  const save = (patch: IncidentState) => labUpdate(lab.id, (l) => void (l.incident = { ...(l.incident || {}), ...patch }))
  const to = (s: Stage) => {
    if (s === 'debrief' && !reveal) return
    setStage(s)
    save({ stage: STAGES.indexOf(s) })
    const sp = new URLSearchParams(loc.search)
    sp.set('stage', s)
    navigate(`${labHref(lab.id)}?${sp.toString()}`, { replace: true })
    scrollNear(top.current)
  }

  useEffect(() => {
    if (usedHints) api.hints(lab.id, usedHints, lang).then(setHints, () => 0)
    if (lp?.revealed || lp?.verified) api.reveal(lab.id, lang).then(setReveal, () => 0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lab.id, lang])
  // keep the draft as the learner types (debounced), so leaving the page does not lose it
  useEffect(() => {
    const h = setTimeout(() => {
      if (diag !== (getProgress().labs[lab.id]?.incident?.draft ?? '')) save({ draft: diag })
    }, 600)
    return () => clearTimeout(h)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [diag])

  async function moreHint() {
    const n = hints.length + 1
    labUpdate(lab.id, (l) => {
      l.hints = Math.max(l.hints || 0, n)
      l.incident = { ...(l.incident || {}), hints: Math.max(l.incident?.hints || 0, n), nextHintAt: Date.now() + HINT_GAP_S * 1000 }
    })
    const h = await api.hints(lab.id, n, lang)
    if (current()) setHints(h)
  }
  async function doReveal() {
    const r = await api.reveal(lab.id, lang)
    if (!current()) return // restarted (or left) while the answer was on its way
    setReveal(r)
    const first = !lp?.revealed
    labUpdate(lab.id, (l) => {
      l.diagnosis = diag
      l.revealed = l.revealed || Date.now()
    }, first ? XP.incidentRevealed : 0)
    setStage('debrief')
    save({ stage: STAGES.indexOf('debrief') })
    const sp = new URLSearchParams(loc.search)
    sp.set('stage', 'debrief')
    navigate(`${labHref(lab.id)}?${sp.toString()}`, { replace: true })
    scrollNear(top.current)
  }
  function onVerified(v: Verification) {
    setLiveVer(v)
    if (v.verdict === 'verified' && !lp?.verified) toast(t('toast.verified'), t('toast.verifiedNote'), 'ok', true)
    labUpdate(lab.id, (l) => {
      const now = Date.now()
      l.verdict = v.verdict
      l.verdictAt = now
      if (v.verdict === 'verified') l.verified = now // the latest success; a later failure (verdictAt > verified) shows
    }, v.verdict === 'verified' && !lp?.verified ? (lp?.revealed ? XP.labVerified : XP.incidentSolved) : 0)
  }
  const idx = STAGES.indexOf(stage)
  const wrote = diag.trim().length >= 20

  return (
    <>
      <Environment lab={lab} onVerified={onVerified} />
      <div ref={top} className="anchor" />
      <nav className="lesson-steps inc-stages" aria-label={t('inc.stages')}>
        {STAGES.map((s, i) => (
          <button
            key={s}
            className={`ls ${s === stage ? 'on' : ''} ${i < idx ? 'past' : ''}`}
            onClick={() => to(s)}
            disabled={s === 'debrief' && !reveal}
            aria-current={s === stage ? 'step' : undefined}
            aria-label={t('lab.stepAria', { n: i + 1, of: STAGES.length, title: t(`inc.stage.${s}` as 'inc.stage.symptom') })}
          >
            <span className="ls-bar" />
            <span className="ls-label">{t(`inc.stage.${s}` as 'inc.stage.symptom')}</span>
          </button>
        ))}
      </nav>
      <RestartAttempt labId={lab.id} kind="incident" begun={idx > 0 || !!diag.trim() || ran.size > 0 || hints.length > 0 || !!lp?.selfCheck} onRestart={onRestart} draft={diag} />

      {stage === 'symptom' && (
        <section className="lesson-step pager-alert">
          <div className="alert-h">
            <span className="sev-dot" /> {t('inc.alert')}
          </div>
          <Md text={lab.symptom} className="symptom" />
          <Goal lab={lab} />
          {lab.background && (
            <details className="more" data-testid="activity-background">
              <summary>{t('lab.whatRunsHere')}</summary>
              <Md text={lab.background} />
            </details>
          )}
          {rec?.verify_before && rec.verify_before.results.length > 0 && <SymptomChecks lab={lab} v={rec.verify_before} live={live} />}
          <div className="lesson-nav">
            <span />
            <button className="btn primary" onClick={() => to('investigate')} data-testid="start-investigating">
              {t('inc.startInvestigating')} <Icon name="arrow" size={16} />
            </button>
          </div>
        </section>
      )}

      {stage === 'investigate' && (
        <section className="lesson-step">
          <h2 className="step-h2">{t('inc.investigateTitle')}</h2>
          <p className="muted">{live ? t('inc.investigateLive') : t('inc.investigateText')}</p>
          <div className="cmds">
            {lab.investigate.map((c, i) => (
              <div key={i} className="inv-cmd">
                <CommandBlock
                  c={{ ...c, meaning: '' }}
                  entry={find('investigate', c)}
                  labId={lab.id}
                  where="investigate"
                  index={i}
                  onResult={(res) => {
                    if (res.status === 'error') return
                    setRan((r) => {
                      const n = new Set(r).add(i)
                      save({ replays: [...n].map(String) })
                      return n
                    })
                  }}
                />
                {ran.has(i) && c.meaning && (
                  <p className="notice fade-in">
                    <span className="lbl">{t('inc.whatToNotice')}</span> <MdInline text={c.meaning} />
                  </p>
                )}
              </div>
            ))}
          </div>
          <HintBox hints={hints} total={lab.hint_count} onMore={moreHint} nextAt={lp?.incident?.nextHintAt} />
          <div className="lesson-nav">
            <button className="btn ghost" onClick={() => to('symptom')}>
              <Icon name="back" size={15} /> {t('ui.back')}
            </button>
            <button className="btn primary" onClick={() => to('diagnose')}>
              {t('inc.toDiagnose')} <Icon name="arrow" size={15} />
            </button>
          </div>
        </section>
      )}

      {stage === 'diagnose' && (
        <section className="lesson-step">
          <h2 className="step-h2">{t('inc.diagnoseTitle')}</h2>
          <p className="muted">{t('inc.diagnoseText')}</p>
          <textarea className="diag" rows={5} value={diag} onChange={(e) => setDiag(e.target.value)} placeholder={t('inc.diagnosePlaceholder')} aria-label={t('inc.diagnoseTitle')} />
          <HintBox hints={hints} total={lab.hint_count} onMore={moreHint} nextAt={lp?.incident?.nextHintAt} />
          {live && <p className="muted small">{t('inc.repairLive')}</p>}
          {live && liveVer && <Checks v={liveVer} live />}
          <div className="lesson-nav">
            <button className="btn ghost" onClick={() => to('investigate')}>
              <Icon name="back" size={15} /> {t('ui.back')}
            </button>
            <span className="nav-right">
              {!wrote && (
                <button className="linkish small" onClick={doReveal} data-testid="reveal">
                  {t('inc.revealWithout')}
                </button>
              )}
              {live && (
                <button className="btn" onClick={async () => onVerified(await cluster.verify(lab.id))}>
                  <Icon name="check" size={15} /> {t('inc.verifyRepair')}
                </button>
              )}
              {wrote && (
                <button className="btn primary" onClick={doReveal} data-testid="reveal">
                  <Icon name="eye" size={15} /> {t('inc.compare')}
                </button>
              )}
            </span>
          </div>
        </section>
      )}

      {stage === 'debrief' && reveal && (
        <section className="lesson-step debrief-full">
          <div className="compare">
            <div className="compare-col mine-col">
              <div className="debrief-h">{t('inc.yourDiagnosis')}</div>
              {lp?.diagnosis || diag ? <blockquote className="mine">{lp?.diagnosis || diag}</blockquote> : <p className="muted">{t('inc.noDiagnosis')}</p>}
            </div>
            <div className="compare-col">
              <div className="debrief-h">{t('inc.rootCause')}</div>
              <Md text={reveal.root_cause} />
            </div>
          </div>
          {(lp?.diagnosis || diag) && <SelfCheck labId={lab.id} />}
          <h3>
            <Icon name="wrench" size={16} /> {t('inc.fix')}
          </h3>
          <div className="cmds">
            {reveal.fix.map((c, i) => (
              <CommandBlock key={i} c={c} entry={find('fix', c)} labId={lab.id} where="fix" index={i} />
            ))}
          </div>
          {reveal.verify_after && <Checks v={reveal.verify_after} title={t('inc.afterFix')} />}
          {live && liveVer && <Checks v={liveVer} live />}
          <div className="deeper">
            <h3>{t('lesson.goDeeper')}</h3>
            {reveal.alternatives && (
              <details className="more">
                <summary>{t('inc.alternatives')}</summary>
                <Md text={reveal.alternatives} />
              </details>
            )}
            {reveal.sre && (
              <details className="more">
                <summary>{t('inc.sre')}</summary>
                <Md text={reveal.sre} />
              </details>
            )}
            {lab.questions.length > 0 && (
              <details className="more">
                <summary>{t('lab.questions')}</summary>
                <div className="qa">
                  {lab.questions.map((q, i) => (
                    <details key={i}>
                      <summary>
                        <Md text={q.q} />
                      </summary>
                      <Md text={q.a} />
                    </details>
                  ))}
                </div>
              </details>
            )}
            <details className="more">
              <summary>{t('lesson.references')}</summary>
              <Refs refs={lab.references} />
              <p className="muted small">{lab.supports}</p>
            </details>
          </div>
          <div className="lesson-nav">
            <span />
            <a className="btn primary" href="/incidents">
              {t('inc.nextIncident')} <Icon name="arrow" size={15} />
            </a>
          </div>
        </section>
      )}
      <TerminalDrawer lab={lab} seed={seed} />
      {live && stage !== 'symptom' && (
        <p className="muted small">
          <button className="linkish" onClick={() => setSeed({ cmd: lab.investigate[0]?.cmd || 'oc get pods', n: Date.now() })}>
            {t('inc.investigateYourWay')}
          </button>
        </p>
      )}
    </>
  )
}

/** Compare honestly: three points, ticked by the learner. Recorded as a self-assessment, never as verification. */
function SelfCheck({ labId }: { labId: string }) {
  const prog = useProgress()
  const prior = prog.labs[labId]?.selfCheck
  const [v, setV] = useState({ root: prior?.root || false, evidence: prior?.evidence || false, fix: prior?.fix || false })
  const [saved, setSaved] = useState(!!prior)
  const items = [
    ['root', t('inc.selfRoot')],
    ['evidence', t('inc.selfEvidence')],
    ['fix', t('inc.selfFix')],
  ] as const
  return (
    <div className="selfcheck-box">
      <div className="debrief-h">{t('inc.selfTitle')}</div>
      {items.map(([k, label]) => (
        <label key={k} className="check">
          <input
            type="checkbox"
            checked={v[k]}
            onChange={(e) => {
              setV({ ...v, [k]: e.target.checked })
              setSaved(false)
            }}
          />{' '}
          <span>{label}</span>
        </label>
      ))}
      <div className="row">
        <button
          className="btn sm"
          onClick={() => {
            labUpdate(labId, (l) => void (l.selfCheck = { ...v, at: Date.now() }))
            setSaved(true)
          }}
          disabled={saved}
          data-testid="self-check-save"
        >
          {saved ? t('inc.selfSaved') : t('inc.selfSave')}
        </button>
        <span className="muted small">{t('inc.selfNote')}</span>
      </div>
    </div>
  )
}

/** Hints come one at a time, with a short pause between them: a nudge first, the reasoning last. */
export function HintBox({ hints, total, onMore, nextAt }: { hints: string[]; total: number; onMore: () => void; nextAt?: number }) {
  const [now, setNow] = useState(() => Date.now())
  const wait = nextAt ? Math.max(0, Math.ceil((nextAt - now) / 1000)) : 0
  useEffect(() => {
    if (!wait) return
    const h = setTimeout(() => setNow(Date.now()), 1000)
    return () => clearTimeout(h)
  }, [wait, now])
  if (!total) return null
  return (
    <div className="hints">
      {hints.map((h, i) => (
        <div key={i} className="hint">
          <span className="hint-n">{t('inc.hintN', { n: i + 1 })}</span>
          <Md text={h} />
        </div>
      ))}
      {hints.length < total && (
        <button
          className="btn sm ghost"
          onClick={() => {
            onMore()
            setNow(Date.now())
          }}
          disabled={wait > 0}
          data-testid="hint"
        >
          <Icon name="bulb" size={14} />{' '}
          {wait > 0 ? t('inc.hintWait', { s: wait }) : hints.length ? t('inc.anotherHint', { n: hints.length + 1, of: total }) : t('inc.hint', { of: total })}
        </button>
      )}
    </div>
  )
}
