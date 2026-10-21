// The step types of a lesson written as a teaching flow (lib/plan.ts compileFlow). Teach steps are plain prose and
// questions reuse CheckQuestion and Guess; this file holds the rest:
//   Show     a recorded command with its real output, a file, or a real screenshot, and what to notice in it
//   Try      the learner types a command; it is compared with the accepted ones (nothing runs), then the real output
//   Order    put the steps of a procedure in order
//   Reflect  say it in your own words, then compare with a model answer
import { useMemo, useRef, useState } from 'react'
import type { FlowOrder, FlowReflect, FlowShow, FlowTry, Lesson } from '../lib/data'
import { t } from '../lib/i18n'
import { Md } from '../lib/md'
import { equivalentCommand, normCommand } from '../lib/match'
import { displayOrder } from '../lib/order'
import { getProgress, noteCommand, recordAnswer, recordExplain, useProgress } from '../lib/progress'
import { focusQuietly, reveal } from '../lib/reveal'
import { CodeBlock, ShellText, Toks, useCols } from './Code'
import { formatCommand } from '../lib/cmdfmt'
import { highlightShell } from '../lib/highlight-shell'
import { CopyButton, Icon } from './ui'
import { Understand } from './Understand'
import { TryAgain } from './Activity'
import { Screenshot } from './Screenshot'

/** The accepted command of a try step: highlighted, split over lines when long, copyable as written. */
function OneWay({ cmd }: { cmd: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const cols = useCols(ref)
  return (
    <span className="oneway">
      <code className="oneway-cmd"><span ref={ref} className="cmd-fit"><ShellText cmd={cmd} cols={cols} /></span></code>
      <CopyButton text={cmd} label={t('ui.copyCommand')} showLabel />
    </span>
  )
}

/** Comparable form of a command: spacing is normalised outside quotes only (lib/match.ts normCommand). */
export const normCmd = normCommand

/** Which client really ran this command, with its version: kubectl, oc, or both (never inferred from the lesson). */
function clientsOf(cmd: string, c: { kubectl?: string; oc?: string }) {
  const used = [/(^|[;&|(]\s*)kubectl\s/m.test(cmd) && `kubectl ${c.kubectl || ''}`.trim(), /(^|[;&|(]\s*)oc\s/m.test(cmd) && `oc ${c.oc || ''}`.trim()].filter(Boolean)
  return used.length ? `${used.join(t('flow.and'))} ` : ''
}

/** The recording of a step's command. When a lesson runs the same command twice (before and after a change), the
 *  recorder keeps one entry per run, in order: the k-th step running that command shows the k-th entry. */
function entryFor(l: Lesson, cmd: string, step?: string) {
  const all = l.recording?.entries.filter((x) => x.cmd === cmd) ?? []
  if (all.length < 2 || !step) return all[0]
  const same = (l.flow ?? []).filter((s) => 'run' in s && s.run === cmd)
  const k = Math.max(0, same.findIndex((s) => s.id === step))
  return all[Math.min(k, all.length - 1)]
}

/** A recorded command and its real output, with the lines worth looking at emphasised. */
export function Recorded({ l, cmd, step, highlight = [] }: { l: Lesson; cmd: string; step?: string; highlight?: string[] }) {
  const e = entryFor(l, cmd, step)
  // `combined` keeps both streams in the order they arrived; older recordings only have them separately
  const text = e ? (e.combined ?? [e.stdout, e.stderr].filter(Boolean).join('\n')).replace(/\n$/, '') : ''
  const box = useRef<HTMLPreElement>(null)
  const cols = useCols(box)
  const lines = useMemo(() => formatCommand(cmd, Math.max(20, cols - 2)).split('\n'), [cmd, cols])
  const rows = useMemo(() => highlightShell(lines), [lines])
  return (
    <figure className="demo" data-testid="demo">
      <div className="codebar">
        <span className="file-name mono">{t('flow.terminal')}</span>
        <CopyButton text={cmd} label={t('ui.copyCommand')} showLabel />
      </div>
      <pre className="demo-term" tabIndex={0} aria-label={t('flow.terminal')} ref={box}>
        <code>
          {rows.map((r, i) => (
            <span key={i} className="demo-cmd">
              <span className="demo-ps" aria-hidden="true">
                {/* a new command after a `;` the display turned into a line break gets its own prompt; a continued
                    line, or a line of a command that was written over several lines, gets the shell's `> ` */}
                {i ? (cmd.includes('\n') || lines[i - 1].endsWith(' \\') ? '> ' : '$ ') : `${e?.identity ? `${e.identity} ` : ''}${e?.cwd ? `${e.cwd} ` : ''}$ `}
              </span>
              <Toks toks={r} />
              {'\n'}
            </span>
          ))}
          {e
            ? text.split('\n').map((ln, i) => (
                <span key={i} className={`demo-line ${highlight.some((h) => h && ln.includes(h)) ? 'hl' : ''}`}>
                  {ln}
                  {'\n'}
                </span>
              ))
            : null}
        </code>
      </pre>
      <figcaption className="demo-meta">
        {e ? (
          <>
            <Icon name="play" size={12} /> {t('flow.recorded', { date: (l.recording?.recorded_at || '').slice(0, 10) })}
            {l.recording?.cluster?.kubernetes ? (
              <> · {clientsOf(cmd, l.recording.cluster)}{t('flow.onCluster', { k8s: l.recording.cluster.kubernetes, where: l.recording.cluster.distribution || 'a cluster' })}</>
            ) : (
              <> · {t('flow.onWorkstation')}</>
            )}
            {e.identity ? (
              <> · {t(e.as === 'admin' ? 'flow.asAdmin' : 'flow.asUser', { who: e.identity })}</>
            ) : (
              // recorded in the workstation shell, whose cluster login is the learner identity: an ordinary user
              l.recording?.cluster?.kubernetes && /(^|[;&|(]\s*)(oc|kubectl)\s/m.test(cmd) && <> · {t('flow.asOrdinary')}</>
            )}
            {e.code !== 0 &&
              (e.expect === 'fail' ? (
                // a non-zero exit the step expects (a refusal, an error it explains, `diff` finding differences): say so,
                // so that it never reads as a broken example
                <strong className="demo-expected" data-testid="expected-failure">{t('flow.exitExpected', { code: e.code })}</strong>
              ) : (
                <> · {t('flow.exit', { code: e.code })}</>
              ))}
          </>
        ) : (
          <span className="warn">{t('flow.notRecorded')}</span>
        )}
      </figcaption>
    </figure>
  )
}

export function ShowStep({ st, l }: { st: FlowShow; l: Lesson }) {
  return (
    <div className="flow-show">
      {st.title && <h2 className="act-title">{st.title}</h2>}
      {st.body && (
        <div className="prose">
          <Md text={st.body} />
        </div>
      )}
      {st.run && <Recorded l={l} cmd={st.run} step={st.id} highlight={st.highlight} />}
      {st.image && <Screenshot img={st.image} caption={st.caption} />}
      {st.code != null && (
        <figure className="demo">
          <CodeBlock code={st.code} caption={st.caption} highlight={st.highlight} />
          {st.origin === 'example' && <figcaption className="demo-meta" data-testid="origin">{t('flow.originExample')}</figcaption>}
          {st.origin === 'lab' && <figcaption className="demo-meta" data-testid="origin"><Icon name="play" size={12} /> {t('flow.originLab')}</figcaption>}
        </figure>
      )}
      {st.notice && (
        <div className="prose notice">
          <Md text={st.notice} />
        </div>
      )}
      {st.run && st.understand && <Understand u={st.understand} />}
    </div>
  )
}

/** Guided practice. Nothing runs: the learner's command is compared with the commands that do the task, and targeted
 * hints answer the mistakes people really make. A hint is available at any time and the solution after one attempt.
 * The field never goes away: after a right answer or a revealed solution the learner can keep trying other forms, or
 * start again with "Try again" (an empty field, no hint, the solution hidden; the next result is the latest attempt).
 * Progress stays honest: only a first-try success without hint or solution counts as solved independently. */
export function TryStep({ st, l }: { st: FlowTry; l: Lesson }) {
  const key = `try:${l.id}:${st.id}`
  const prog = useProgress()
  const [text, setText] = useState('')
  const [tries, setTries] = useState(0)
  const [say, setSay] = useState('')
  const [hinted, setHinted] = useState(false)
  // 'own': solved without help; 'helped': solved after hints or wrong attempts; 'shown': the solution was revealed
  // saved as soon as anything happens, so a reload cannot turn help into "solved on your own":
  // pick -2 = tried or saw a hint, -1 = solution shown (kept on every later attempt), 0 = solved
  // A later visit shows the latest attempt; the first one only says whether it was solved without help.
  const [outcome, setOutcome] = useState<'open' | 'own' | 'helped' | 'shown'>(() => {
    const r = prog.predictions[key]
    if (!r) return 'open'
    if (r.latest.pick === -1) return 'shown'
    if (!r.latest.ok) return 'open'
    return r.first.ok ? 'own' : 'helped'
  })
  const helpedBefore = !!prog.predictions[key] && !prog.predictions[key]!.first.ok
  const markHelped = () => {
    if (!prog.predictions[key]) recordAnswer(key, false, -2)
  }
  const [lastOk, setLastOk] = useState('')
  const [note, setNote] = useState('') // announced politely: a new attempt
  const res = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const accepted = useMemo(() => st.accept.map(normCmd), [st.accept])
  const settle = (o: 'own' | 'helped' | 'shown') => {
    if (outcome === 'open') {
      if (o !== 'own') markHelped() // the first attempt on record is never a success with help
      // a solve with help is a right answer (latest.ok) whose first attempt was not
      recordAnswer(key, o !== 'shown', o === 'shown' ? -1 : 0)
    } else if (o !== 'shown') recordAnswer(key, true, outcome === 'shown' ? -1 : 0) // a later right answer is kept; a shown solution stays shown
    if (o === 'own' && st.run) noteCommand(st.run) // nothing ran: only note the command when the learner typed it
    setOutcome((cur) => (cur === 'open' ? o : cur))
    if (outcome === 'open') {
      reveal(res.current) // later attempts keep the field where it is
      if (o === 'shown') requestAnimationFrame(() => res.current?.focus({ preventScroll: true })) // the Show me button is gone
    }
  }
  const check = () => {
    const n = normCmd(text)
    if (!n) return
    // an accepted form, or the same command up to option order, grouping and path spelling (lib/match.ts)
    if (accepted.includes(n) || st.accept.some((x) => equivalentCommand(text, x))) {
      setSay('')
      setLastOk(text.trim())
      return settle(tries === 0 && !hinted && !helpedBefore ? 'own' : 'helped')
    }
    // every failed submission is recorded (the first one on record, or the latest after Try again); once the solution
    // was shown, a failure keeps saying so
    recordAnswer(key, false, outcome === 'shown' ? -1 : -2)
    setTries(tries + 1)
    setLastOk('')
    const h = st.hints.find((x) => new RegExp(x.match).test(n))
    setSay(h ? h.say : st.hint || t('flow.tryAgain'))
  }
  const again = () => {
    setText('')
    setTries(0)
    setHinted(false)
    setSay('')
    setLastOk('')
    setOutcome('open')
    setNote(t('ex.newAttempt'))
    input.current?.focus()
  }
  const done = outcome !== 'open'
  return (
    <div className={`flow-try ${done ? 'done' : ''}`} data-testid="try">
      {st.title && <h2 className="act-title">{st.title}</h2>}
      <div className="prose">
        <Md text={st.body} />
      </div>
      <p className="muted small try-note try-expectation"><Icon name="info" size={16} />{t('flow.nothingRuns')}</p>
      <form
        className="try-line"
        onSubmit={(e) => {
          e.preventDefault()
          check()
        }}
      >
        <span className="demo-ps" aria-hidden="true">
          $
        </span>
        <input
          ref={input}
          className="mono"
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-label={t('flow.typeCommand')}
          autoCapitalize="off"
          autoCorrect="off"
          autoComplete="off"
          spellCheck={false}
          data-testid="try-input"
        />
        <button className="btn primary sm" type="submit" disabled={!text.trim()} data-testid="try-check">
          {t('flow.check')}
        </button>
      </form>
      {/* always mounted, so that screen readers announce what appears in it */}
      <div className="try-live" aria-live="polite">
        {say && (
          <div className="verdict bad" data-testid="try-hint">
            <Icon name="info" size={18} />
            <Md text={say} />
          </div>
        )}
        {lastOk && done && (
          <p className="verdict ok" data-testid="try-ok">
            <Icon name="check" size={18} />
            <strong>{t('flow.tryRight')}</strong> <code>{lastOk}</code> {t('flow.doesIt')}
          </p>
        )}
      </div>
      <p className="muted small try-note">
        {!hinted && st.hint && (
          <button className="linkish small" onClick={() => { setHinted(true); setSay(st.hint); markHelped(); input.current?.focus() }} data-testid="try-hint-btn">
            <Icon name="bulb" size={14} /> {t('flow.hint')}
          </button>
        )}{' '}
        {outcome === 'open' && (tries > 0 || helpedBefore) && (
          <button className="linkish small" onClick={() => settle('shown')} data-testid="try-show">
            <Icon name="eye" size={14} /> {t('flow.showMe')}
          </button>
        )}
      </p>
      {done && (
        <div ref={res} data-testid="try-result" tabIndex={-1} className="try-result">
          <p className="try-status" data-testid="try-status">
            <Icon name={outcome === 'shown' ? 'eye' : 'check'} size={16} />
            {outcome === 'own' ? t('flow.solvedOwn') : outcome === 'helped' ? t('flow.solvedHelped') : t('flow.solutionShown')}
          </p>
          <p className="verdict">
            {t('flow.oneWay')} <OneWay cmd={st.accept[0]} />
          </p>
          {st.run && <Recorded l={l} cmd={st.run} step={st.id} />}
          {st.then && (
            <div className="prose notice">
              <Md text={st.then} />
            </div>
          )}
          {st.understand && <Understand u={st.understand} />}
          <p className="muted small try-again-row">
            <TryAgain onClick={again} testid="try-again" /> {t('flow.keepTrying')}
          </p>
        </div>
      )}
      <p className="sr-only" aria-live="polite">{note}</p>
    </div>
  )
}

/** Put the steps in order. Items start in a stable shuffled order; each can be moved up or down with buttons. After a
 * wrong order, "Try again" keeps the arrangement so the learner can fix it; after a right or shown order it starts
 * again from the shuffled order. A later visit shows a right (or shown) order with "Try again". */
type OrderStatus = 'open' | 'right' | 'wrong' | 'shown'
/** An item's words without Markdown marks, for the move buttons' names and announcements. */
const plain = (md: string) => md.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[`*_]/g, '').replace(/\s+/g, ' ').trim()
export function OrderStep({ st, l }: { st: FlowOrder; l: Lesson }) {
  const key = `order:${l.id}:${st.id}`
  const start = useMemo(() => {
    let o = displayOrder(key, st.items.length)
    if (o.every((v, i) => v === i)) o = [...o.slice(1), o[0]] // never start already solved
    return o
  }, [key, st.items.length])
  const solved = st.items.map((_, i) => i)
  const [first] = useState<OrderStatus>(() => {
    const r = getProgress().predictions[key]
    return !r ? 'open' : r.latest.pick === -1 ? 'shown' : r.latest.ok ? 'right' : 'open'
  })
  const [status, setStatus] = useState<OrderStatus>(first)
  const [earlier, setEarlier] = useState(first !== 'open')
  const [order, setOrder] = useState(first === 'open' ? start : solved)
  const [note, setNote] = useState('')
  const checked = status !== 'open'
  const res = useRef<HTMLDivElement>(null)
  const verdict = useRef<HTMLDivElement>(null)
  const list = useRef<HTMLOListElement>(null)
  const move = (i: number, d: number) => {
    const j = i + d
    if (j < 0 || j >= order.length || checked) return
    const o = [...order]
    ;[o[i], o[j]] = [o[j], o[i]]
    setOrder(o)
    setNote(t('ex.orderMoved', { item: plain(st.items[o[j]]), n: j + 1, of: o.length }))
    // focus stays on the moved item (its row keeps its key); at the top or bottom that button is disabled: use the other
    requestAnimationFrame(() => {
      const btns = list.current?.querySelectorAll<HTMLButtonElement>(`li:nth-child(${j + 1}) .icon-btn`)
      if (btns?.[d < 0 ? 0 : 1]?.disabled) btns[d < 0 ? 1 : 0]?.focus()
    })
  }
  const settle = (s: OrderStatus) => {
    setStatus(s)
    setEarlier(false)
    // the always-mounted live region says the result; focus goes to it, since the button pressed is now disabled or gone
    setNote(s === 'right' ? t('check.right') : s === 'shown' ? t('ex.orderShown') : t('flow.orderWrong'))
    requestAnimationFrame(() => {
      reveal(res.current)
      focusQuietly(verdict.current)
    })
  }
  const check = () => {
    const ok = order.every((v, i) => v === i)
    recordAnswer(key, ok, ok ? 0 : 1) // the first attempt on record decides "on the first try"; later ones are the latest
    settle(ok ? 'right' : 'wrong')
  }
  const again = () => {
    if (status !== 'wrong') setOrder(start)
    setStatus('open')
    setEarlier(false)
    setNote(t('ex.newAttempt'))
    requestAnimationFrame(() => list.current?.querySelector<HTMLElement>('.icon-btn:not(:disabled)')?.focus())
  }
  return (
    <div className="flow-order" data-testid="order">
      <div className="check-prompt">
        <Md text={st.prompt} />
      </div>
      <ol className="order-list" ref={list}>
        {order.map((v, i) => (
          <li key={v} className={!checked ? '' : v === i ? 'ok' : 'bad'} data-testid="order-item">
            <span className="order-handle" aria-hidden="true"><Icon name="list" size={16} /></span>
            <span className="order-n" aria-hidden="true">
              {i + 1}
            </span>
            <span className="order-t">
              <Md text={st.items[v]} />
            </span>
            <Icon name={v === i ? 'check' : 'x'} size={16} className={`order-state ${!checked ? 'pending' : ''}`} />
            <span className="order-btns">
              <button className="icon-btn" onClick={() => move(i, -1)} disabled={i === 0 || checked} aria-label={t('flow.moveUp', { item: plain(st.items[v]), n: i + 1 })}>
                <Icon name="arrow" size={14} />
              </button>
              <button className="icon-btn down" onClick={() => move(i, 1)} disabled={i === order.length - 1 || checked} aria-label={t('flow.moveDown', { item: plain(st.items[v]), n: i + 1 })}>
                <Icon name="arrow" size={14} />
              </button>
            </span>
          </li>
        ))}
      </ol>
      <div className="check-actions">
        <button className="btn primary" onClick={check} disabled={checked} data-testid="order-check">
          {t('flow.checkOrder')}
        </button>
      </div>
      <div ref={res} className="order-feedback-slot">
        {checked && (
          <div className={`verdict ${status === 'wrong' ? 'bad' : status === 'right' ? 'ok' : ''}`} ref={verdict} tabIndex={-1} data-testid="order-verdict">
            {earlier && <p className="ex-earlier">{t('ex.earlierAnswer')}</p>}
            <strong className="feedback-heading">
              <Icon name={status === 'right' ? 'check' : status === 'shown' ? 'eye' : 'info'} size={18} />
              {status === 'right' ? t('check.right') : status === 'shown' ? t('ex.orderShown') : t('flow.orderWrong')}
            </strong>
            {status !== 'wrong' && <Md text={st.why} />}
            <div className="check-actions">
              <TryAgain onClick={again} testid="order-again" />
              {status === 'wrong' && (
                <button
                  className="linkish small"
                  onClick={() => {
                    recordAnswer(key, false, -1, true) // the order was shown, not found
                    setOrder(solved)
                    settle('shown')
                  }}
                  data-testid="order-show"
                >
                  <Icon name="eye" size={14} /> {t('flow.showOrder')}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
      <p className="sr-only" aria-live="polite" data-testid="order-live">{note}</p>
    </div>
  )
}

/** Self-explanation: write it, then compare. Never scored; writing something is recorded, not its quality. */
export function ReflectStep({ st, l }: { st: FlowReflect; l: Lesson }) {
  const key = `reflect:${l.id}:${st.id}`
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  return (
    <div className="flow-reflect" data-testid="reflect">
      <div className="check-prompt">
        <Md text={st.prompt} />
      </div>
      {!open ? (
        <>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} placeholder={t('flow.reflectPlaceholder')} aria-label={t('learn.yourExplanation')} />
          <div className="row">
            <button
              className="linkish small"
              onClick={() => {
                setOpen(true)
                if (text.trim().length >= 20) recordExplain(key, 1, 1)
              }}
              data-testid="reflect-compare"
            >
              <Icon name="eye" size={16} /> {text.trim() ? t('flow.compare') : t('flow.justShow')}
            </button>
          </div>
        </>
      ) : (
        <>
          {text.trim() && <blockquote className="mine">{text}</blockquote>}
          <div className="model-answer" role="status">
            <span className="lbl">{t('flow.oneGoodAnswer')}</span>
            <Md text={st.model} />
          </div>
          <button className="linkish small" onClick={() => setOpen(false)} data-testid="reflect-edit">
            <Icon name="refresh" size={14} /> {t('flow.editMine')}
          </button>
        </>
      )}
    </div>
  )
}
