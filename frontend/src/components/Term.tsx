// Terminal components. Not a PTY emulator: commands here are discrete (recorded or policy-checked), so a
// transcript of entries renders better than a character grid. Layout rules that avoid nested scrollbars:
//   * a transcript has exactly one scroll container (.tx-body), vertical only; outputs wrap in both presentation modes;
//   * an output pane inside a lesson never scrolls vertically: long outputs collapse with "show N more lines";
//   * structured tables versus plain text is a per-view toggle, remembered in the browser.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { cluster, type Cmd, type CommandRef, type Entry, type RunResult } from '../lib/data'
import { useApp } from '../lib/app'
import { t } from '../lib/i18n'
import { exact, norm, similar } from '../lib/match'
import { noteCommand } from '../lib/progress'
import { labHref, lessonHref } from '../lib/urls'
import { coarsePointer, focusQuietly, reveal } from '../lib/reveal'
import { ShellText, useCols } from './Code'
import { CopyButton, Icon } from './ui'
import { Marked, Stream } from './transcript/Stream'
import { commandResult, type CommandResult } from './transcript/result'
import './transcript.css'
export { parseTable } from './transcript/parse'
export { Stream } from './transcript/Stream'
export type { CommandResult } from './transcript/result'

const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

function usePref(key: string, initial: boolean): [boolean, (v: boolean) => void] {
  const [v, setV] = useState<boolean>(() => {
    try {
      const s = localStorage.getItem(key)
      return s === null ? initial : s === '1'
    } catch {
      return initial
    }
  })
  const set = (x: boolean) => {
    setV(x)
    try {
      localStorage.setItem(key, x ? '1' : '0')
    } catch {
      /* ignore */
    }
  }
  return [v, set]
}

// ---------------------------------------------------------------- highlighting
export function HiCmd({ text }: { text: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const cols = useCols(ref)
  return (
    <span ref={ref} className="cmd-fit">
      <ShellText cmd={text} cols={cols} />
    </span>
  )
}

/** Backwards-compatible single output (used by the command reference). */
export function Output({ stdout, stderr, q }: { stdout: string; stderr?: string; code?: number | null; q?: string }) {
  return (
    <div className="transcript-reference">
      <p className="transcript-note">Recorded output. Very long output may have been shortened; copying keeps the two streams apart.</p>
      <Stream text={stdout} q={q} />
      {stderr && <Stream text={stderr} err q={q} />}
    </div>
  )
}

function ExitBadge({ code, expectFail, running }: { code?: number | null; expectFail?: boolean; running?: boolean }) {
  if (running)
    return (
      <span className="exit run">
        <span className="spin" style={{ width: 10, height: 10, display: 'inline-block', verticalAlign: '-1px', marginRight: 4 }} />
        {t('term.running')}
      </span>
    )
  if (code === null || code === undefined) return null
  if (code === -1) return <span className="exit bad">{t('term.failedToRun')}</span>
  return (
    <span className={`exit ${code === 0 ? 'ok' : expectFail ? 'expected' : 'bad'}`} title={code !== 0 && expectFail ? t('term.expectedFailHelp') : undefined}>
      {t('term.exit', { code })}
      {code !== 0 && expectFail ? ` · ${t('term.expectedFail')}` : ''}
    </span>
  )
}

// ---------------------------------------------------------------- command block (lessons, labs, incidents)
// Recorded examples appear immediately; replay does not pretend to execute by animating typing.

type Result = { source: 'recorded' | 'live'; code: number; stdout: string; stderr: string; run?: string | null; expectFail?: boolean }

/** One command: what it means, its recorded output (replay), or a live run on the learner's cluster. */
export function CommandBlock({ c, entry, labId, where, index, onRan, onResult, compact }: { c: Cmd; entry?: Entry; labId?: string; where?: string; index?: number; onRan?: (ok: boolean, live: boolean) => void; onResult?: (r: CommandResult) => void; compact?: boolean }) {
  const { live } = useApp()
  const [phase, setPhase] = useState<'idle' | 'shown' | 'running' | 'confirm'>('idle')
  const [res, setRes] = useState<Result | null>(null)
  const [confirmText, setConfirmText] = useState('')
  const [admin, setAdmin] = useState(false)
  const [err, setErr] = useState('')
  const [showRec, setShowRec] = useState(false)
  const [wrap, setWrap] = usePref('osa.wrap.block2', true)
  const canLive = live && labId && where !== undefined && index !== undefined && !c.skip && c.as !== 'host'
  const typedText = res?.run && !/\{(pod|anypod|rs|ns|route-host)[:}]/.test(res.run) ? res.run : c.cmd
  const root = useRef<HTMLDivElement>(null)
  const asked = useRef(false) // set by the learner's click; ordinary rerenders never move the page
  useEffect(() => {
    if (!asked.current || phase === 'running') return
    asked.current = false
    reveal(root.current)
  }, [res, phase, err])

  function replay() {
    if (!entry || entry.skipped) return
    asked.current = true
    setRes({ source: 'recorded', code: entry.code, stdout: entry.stdout, stderr: entry.stderr, run: entry.run, expectFail: entry.expect === 'fail' })
    setPhase('shown')
    noteCommand(c.cmd)
    onRan?.(entry.ok, false)
    onResult?.(commandResult('recording', c.expect, entry.code))
  }

  async function runLive(confirm = false) {
    if (!canLive) return
    asked.current = true
    setPhase('running')
    setErr('')
    try {
      const r: RunResult = await cluster.exec(labId!, where!, index!, confirm)
      if (r.refused) {
        setErr(r.reason || 'refused')
        onResult?.(commandResult('live', c.expect))
        setPhase(res ? 'shown' : 'idle')
      } else if (r.needs_confirm) {
        setConfirmText(r.display || c.cmd)
        setAdmin(!!r.admin)
        setPhase('confirm')
      } else {
        const okExpect = c.expect === 'any' || (c.expect === 'ok') === (r.code === 0)
        setRes({ source: 'live', code: r.code ?? -1, stdout: r.stdout || '', stderr: r.stderr || '', run: r.run, expectFail: c.expect === 'fail' })
        setPhase('shown')
        noteCommand(c.cmd)
        onRan?.(okExpect, true)
        onResult?.(commandResult('live', c.expect, r.code, (r as RunResult & { status?: string }).status))
      }
    } catch (e) {
      setErr(String((e as Error).message))
      onResult?.(commandResult('live', c.expect))
      setPhase(res ? 'shown' : 'idle')
    }
  }

  const who = c.as !== 'learner' ? <span className={`who who-${c.as}`}>{c.as === 'reader' ? t('term.asReader') : c.as === 'host' ? t('term.asHost') : t('term.asAdmin')}</span> : null
  const output = res ? [res.stdout, res.stderr].filter(Boolean).join('\n') : ''
  return (
    <div ref={root} data-keys="own" onKeyDown={e => e.stopPropagation()} className={`cmdblock transcript-command ${compact ? 'compact' : ''} ${phase !== 'idle' ? 'opened' : ''}`}>
      <div className="cmd-row">
        <span className="prompt" aria-hidden="true">
          $
        </span>
        <code className="cmd-text">
          <HiCmd text={c.cmd} />
        </code>
        {who}
        <span className="cmd-actions">
          <CopyButton text={c.cmd} label={t('term.copyCommand')} />
          {c.skip ? (
            <span className="pill muted" title={c.skip}>
              {t('term.notRun')}
            </span>
          ) : canLive ? (
            <button className="run-btn live" onClick={() => runLive()} disabled={phase === 'running'} data-testid="run-live">
              <Icon name="play" size={13} /> {phase === 'running' ? t('term.running') : t('term.runLive')}
            </button>
          ) : entry && !entry.skipped ? (
            <button className="run-btn" onClick={replay} data-testid="replay" aria-label={`${res ? t('term.replayAgain') : t('term.replay')}: ${c.cmd}`}>
              <Icon name={res ? 'refresh' : 'play'} size={13} /> {res ? t('term.replayAgain') : t('term.replay')}
            </button>
          ) : null}
        </span>
      </div>
      {c.meaning && <div className="cmd-meaning">{c.meaning}</div>}
      {c.skip && <div className="cmd-meaning muted">{c.skip}</div>}
      {phase === 'confirm' && (
        <div className={`confirm ${admin ? 'admin' : ''}`} role="alertdialog" aria-label={t('term.confirmTitle')}>
          <Icon name={admin ? 'shield' : 'bolt'} size={16} />
          <span>{admin ? t('term.confirmAdmin') : t('term.confirmWrite')}</span>
          <code>{confirmText}</code>
          <button className="btn primary sm" onClick={() => runLive(true)} data-testid="confirm-run" autoFocus>
            {t('term.confirmRun')}
          </button>
          <button className="btn sm" onClick={() => setPhase(res ? 'shown' : 'idle')}>
            {t('ui.cancel')}
          </button>
        </div>
      )}
      {err && (
        <div className="cmd-err" role="alert">
          {err}
        </div>
      )}
      {phase === 'running' && !res && (
        <div className="screen transcript live" aria-live="polite">
          <div className="screen-bar">
            <span className="screen-src">{t('term.liveOutput')}</span>
            <ExitBadge running />
          </div>
        </div>
      )}
      {res && phase !== 'idle' && (
        <div className={`screen transcript ${res.source} ${wrap ? 'wrap' : ''}`} aria-live="polite">
          <div className="screen-bar">
            <span className="screen-src">
              <span className={`tx-tag ${res.source === 'live' ? 'live' : 'rec'}`}>{res.source === 'live' ? t('term.tagLive') : t('term.tagRecorded')}</span>
            </span>
            {phase === 'running' ? <ExitBadge running /> : <ExitBadge code={res.code} expectFail={res.expectFail} />}
            <button className="icon-btn" aria-pressed={wrap} onClick={() => setWrap(!wrap)} title="Format tables; turn off for plain text" aria-label="Format tables">
              <Icon name="wrap" size={15} />
            </button>
            {output && <CopyButton text={output} label={t('term.copyOutput')} />}
          </div>
          <div className="screen-body">
            <div className="tx-inner">
              <div className="typed">
                <span className="tx-prompt">$</span>
                {typedText}
              </div>
              <p className="transcript-note">{res.source === 'recorded' ? 'Recorded output' : 'Live output'}. Very long output may have been shortened; copying keeps stdout and stderr apart.</p>
              <>
                  {!output && <div className="tx-hint">{t('term.noOutput')}</div>}
                  <Stream text={res.stdout} wrap={wrap} />
                  <Stream text={res.stderr} err wrap={wrap} />
              </>
            </div>
          </div>
          {res.source === 'live' && entry && !entry.skipped && (
            <div className="screen-foot">
              <button className="linkish" onClick={() => setShowRec(!showRec)} aria-expanded={showRec}>
                {showRec ? t('term.hideRecorded') : t('term.compareRecorded')}
              </button>
              {showRec && (
                <div className="tx-inner" >
                  <Stream text={entry.stdout} />
                  <Stream text={entry.stderr} err />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- transcript (practice and live terminals)
export type TxEntry = { id: number; cmd?: string; stdout?: string; stderr?: string; code?: number | null; running?: boolean; expectFail?: boolean; info?: string; node?: ReactNode }

export function Transcript({ title, tag, entries, onClear, input, extra, empty, height, live: isLive }: { title: string; tag: ReactNode; entries: TxEntry[]; onClear: () => void; input: ReactNode; extra?: ReactNode; empty: ReactNode; height?: number; live?: boolean }) {
  const body = useRef<HTMLDivElement>(null)
  const [wrap, setWrap] = usePref('osa.wrap.term2', true)
  const [searching, setSearching] = useState(false)
  const [q, setQ] = useState('')
  const [stuck, setStuck] = useState(true)
  const [fresh, setFresh] = useState(false)

  const onScroll = useCallback(() => {
    const el = body.current
    if (!el) return
    // "following" = the newest command's start is on screen or the panel is at its end
    const last = el.querySelector('.tx-entry:last-child') as HTMLElement | null
    const lastTop = last ? last.getBoundingClientRect().top - el.getBoundingClientRect().top : 0
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24 || (lastTop >= -8 && lastTop < el.clientHeight)
    setStuck(atBottom)
    if (atBottom) setFresh(false)
  }, [])
  // The learner reads from the top of each command down. When they are following along (at the end), a new command
  // scrolls into view with its command line first; if its output is longer than the panel, the rest stays below for
  // them to scroll. When they have scrolled up to read history, nothing moves and a "new output" button appears.
  useLayoutEffect(() => {
    const el = body.current
    if (!el) return
    if (!stuck) return setFresh(entries.length > 0)
    const last = el.querySelector('.tx-entry:last-child') as HTMLElement | null
    const max = el.scrollHeight - el.clientHeight
    const start = last ? last.getBoundingClientRect().top - el.getBoundingClientRect().top + el.scrollTop - 6 : max
    el.scrollTo({ top: Math.max(0, Math.min(start, max)), behavior: 'auto' }) // instant: the reader's eye is on the new command
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries])
  const matches = useMemo(() => {
    if (!q) return 0
    const ql = q.toLowerCase()
    return entries.reduce((n, e) => n + [e.cmd, e.stdout, e.stderr].filter(Boolean).join('\n').toLowerCase().split(ql).length - 1, 0)
  }, [entries, q])
  const all = entries.map((e) => [e.cmd ? `$ ${e.cmd}` : '', e.stdout || '', e.stderr || '', e.info || ''].filter(Boolean).join('\n')).join('\n\n')

  return (
    <section data-keys="own" onKeyDown={e => e.stopPropagation()} className={`tx transcript ${wrap ? 'wrap' : ''} ${isLive ? 'live' : ''}`} aria-label={title}>
      <div className="tx-head">
        <span className="tx-title">
          <Icon name="terminal" size={15} /> {title} {tag}
        </span>
        {extra}
        <button className="icon-btn" aria-pressed={searching} onClick={() => (setSearching(!searching), setQ(''))} title={t('term.search')} aria-label={t('term.search')}>
          <Icon name="search" size={15} />
        </button>
        <button className="icon-btn" aria-pressed={wrap} onClick={() => setWrap(!wrap)} title="Format tables; turn off for plain text" aria-label="Format tables">
          <Icon name="wrap" size={15} />
        </button>
        {all && <CopyButton text={all} label={t('term.copyAll')} />}
        <button className="icon-btn" onClick={onClear} title={t('play.clear')} aria-label={t('play.clear')}>
          <Icon name="trash" size={15} />
        </button>
      </div>
      {searching && (
        <div className="tx-search">
          <Icon name="search" size={14} />
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Escape' && (setSearching(false), setQ(''))} placeholder={t('term.searchPlaceholder')} aria-label={t('term.search')} />
          <span className="count" aria-live="polite">
            {q ? t('term.matches', { n: matches }) : ''}
          </span>
        </div>
      )}
      <div className="tx-body" style={{ maxHeight: height || 520 }} ref={body} onScroll={onScroll} role="log" aria-live="polite" aria-relevant="additions" tabIndex={0}>
        <div className="tx-inner">
          {entries.length === 0 && <div className="tx-hint">{empty}</div>}
          {entries.map((e) => (
            <div className="tx-entry" key={e.id}>
              {e.cmd && (
                <div className="tx-cmdline">
                  <span className="tx-prompt" aria-hidden="true">
                    $
                  </span>
                  <span className="cmd">
                    {q ? <Marked text={e.cmd} q={q} /> : <HiCmd text={e.cmd} />}
                  </span>
                  <span className="tx-meta">
                    <ExitBadge code={e.code} expectFail={e.expectFail} running={e.running} />
                  </span>
                </div>
              )}
              {(e.stdout || e.stderr) && <p className="transcript-note">{isLive ? 'Live output. Very long output may have been shortened.' : 'Recorded output. Very long output may have been shortened.'}</p>}
              {e.stdout && <Stream text={e.stdout} q={q} maxLines={200} wrap={wrap} />}
              {e.stderr && <Stream text={e.stderr} err q={q} maxLines={200} wrap={wrap} />}
              {e.info && <div className="tx-info">{e.info}</div>}
              {e.node && <div className="tx-node">{e.node}</div>}
            </div>
          ))}
        </div>
      </div>
      {fresh && !stuck && (
        <div className="tx-jump-wrap">
          <button className="tx-jump" onClick={() => {
            // go to the start of the newest command, not the tail of its output
            const el = body.current
            const last = el?.querySelector('.tx-entry:last-child') as HTMLElement | null
            if (!el) return
            const top = last ? last.getBoundingClientRect().top - el.getBoundingClientRect().top + el.scrollTop - 6 : el.scrollHeight
            el.scrollTo({ top: Math.min(top, el.scrollHeight - el.clientHeight), behavior: reduced() ? 'auto' : 'smooth' })
          }}>
            {t('term.jump')} ↓
          </button>
        </div>
      )}
      {input}
    </section>
  )
}

/** Command line with history (Up/Down), Ctrl+L to clear, Escape to empty. */
function PromptInput({ onSubmit, onClear, seed, placeholder, busy, testid, suggestions }: { onSubmit: (cmd: string) => void; onClear: () => void; seed?: { cmd: string; n: number }; placeholder: string; busy?: boolean; testid: string; suggestions?: (typed: string) => string[] }) {
  const [input, setInput] = useState('')
  const hist = useRef<string[]>([])
  const hi = useRef(-1)
  const inp = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (seed?.cmd) {
      setInput(seed.cmd)
      // Show the whole terminal (its start first); focus only where it will not pop up an on-screen keyboard.
      reveal(inp.current?.closest('.transcript'), { then: () => !coarsePointer() && focusQuietly(inp.current) })
    }
  }, [seed?.n])
  const sug = suggestions && input.trim().length >= 4 ? suggestions(input).filter((s) => s !== input.trim()).slice(0, 4) : []
  function submit(cmd: string) {
    const c = cmd.trim()
    if (!c || busy) return
    hist.current = [c, ...hist.current.filter((x) => x !== c)].slice(0, 100)
    hi.current = -1
    onSubmit(c)
    setInput('')
  }
  return (
    <>
      <form
        className="tx-in"
        onSubmit={(e) => {
          e.preventDefault()
          submit(input)
        }}
      >
        <span className="tx-prompt" aria-hidden="true">
          $
        </span>
        <input
          ref={inp}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowUp' && hist.current.length) {
              hi.current = Math.min(hi.current + 1, hist.current.length - 1)
              setInput(hist.current[hi.current])
              e.preventDefault()
            } else if (e.key === 'ArrowDown') {
              hi.current = Math.max(hi.current - 1, -1)
              setInput(hi.current < 0 ? '' : hist.current[hi.current])
              e.preventDefault()
            } else if (e.key === 'Escape') setInput('')
            else if (e.key.toLowerCase() === 'l' && e.ctrlKey) {
              e.preventDefault()
              onClear()
            }
          }}
          placeholder={placeholder}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          autoComplete="off"
          enterKeyHint="send"
          aria-label={t('term.command')}
          data-testid={testid}
        />
        <button className="btn primary sm" disabled={busy}>
          {busy ? t('term.running') : t('term.enter')}
        </button>
      </form>
      {sug.length > 0 && (
        <div className="tx-suggest" role="group" aria-label={t('play.similar')}>
          {sug.map((s) => (
            <button key={s} type="button" onClick={() => (setInput(s), focusQuietly(inp.current))} title={s}>
              {s}
            </button>
          ))}
        </div>
      )}
    </>
  )
}

/** Practice: answers with the outputs recorded on a real cluster; never invents output. */
export function PracticeTerminal({ corpus, seed, height, starters = [] }: { corpus: CommandRef[]; seed?: { cmd: string; n: number }; height?: number; starters?: string[] }) {
  const tested = useMemo(() => corpus.filter((c) => c.tested), [corpus])
  const [entries, setEntries] = useState<TxEntry[]>([])
  const nextId = useRef(1)
  const add = (e: Omit<TxEntry, 'id'>) => setEntries((l) => [...l, { ...e, id: nextId.current++ }])

  function submit(c: string) {
    if (c === 'clear') return setEntries([])
    if (c === 'help') return add({ cmd: c, info: t('play.help', { n: tested.length }) })
    const m = exact(tested, c)
    if (m) {
      noteCommand(m.cmd)
      add({
        cmd: c,
        stdout: m.stdout || (m.stderr ? '' : t('term.noOutput')),
        stderr: m.stderr,
        code: m.code,
        expectFail: (m.code ?? 0) !== 0,
        node: (
          <>
            {t('play.from', { lab: m.lab_title })} · <a href={m.kind === 'lesson' ? lessonHref(m.lab) : labHref(m.lab)}>{t('play.openLab')}</a>
            {m.run && norm(m.run) !== norm(m.cmd) ? ` · ${t('play.ranAs')} ${m.run}` : ''}
            {m.viaOc ? ` · ${t('play.viaOc', { cmd: m.run || m.cmd })}` : ''}
          </>
        ),
      })
      return
    }
    const sim = similar(tested, c)
    add({
      cmd: c,
      node: (
        <div className="tx-nomatch">
          <div>{/^(oc|kubectl|podman|skopeo|helm) /.test(c) ? t('play.notRecorded') : t('play.onlyOc')}</div>
          {sim.length > 0 && (
            <>
              <div className="muted">{t('play.similar')}</div>
              <ul>
                {sim.map((s) => {
                  const runnable = s.cmd.includes('<') && s.run ? s.run : s.cmd
                  return (
                    <li key={s.cmd + s.lab}>
                      <button className="linkish mono" onClick={() => submit(runnable)}>
                        {runnable}
                      </button>
                    </li>
                  )
                })}
              </ul>
            </>
          )}
        </div>
      ),
    })
  }

  return (
    <div>
      <Transcript
        title={t('play.title')}
        height={height}
        tag={<span className="tx-tag rec">{t('play.recordedBadge', { n: tested.length })}</span>}
        entries={entries}
        onClear={() => setEntries([])}
        empty={
          <>
            <p style={{ margin: '0 0 10px' }}>{t('play.intro')}</p>
            {starters.length > 0 && (
              <div className="starters">
                {starters.map((c) => (
                  <button key={c} type="button" onClick={() => submit(c)}>
                    <Icon name="play" size={12} /> {c}
                  </button>
                ))}
              </div>
            )}
          </>
        }
        input={<PromptInput onSubmit={submit} onClear={() => setEntries([])} seed={seed} placeholder={t('term.placeholder')} testid="term-input" suggestions={(typed) => similar(tested, typed, 4).map((s) => (s.cmd.includes('<') && s.run ? s.run : s.cmd))} />}
      />
    </div>
  )
}

/** Live: real commands on the learner's cluster, through the server's policy. */
export function LiveTerminal({ namespace, labId, seed, height }: { namespace?: string; labId?: string; seed?: { cmd: string; n: number }; height?: number }) {
  const { status } = useApp()
  const [identity, setIdentity] = useState<'learner' | 'reader'>('learner')
  const [entries, setEntries] = useState<TxEntry[]>([])
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState<{ display: string; command: string; id: number } | null>(null)
  const [yaml, setYaml] = useState('')
  const [showYaml, setShowYaml] = useState(false)
  const nextId = useRef(1)
  const patch = (id: number, p: Partial<TxEntry>) => setEntries((l) => l.map((e) => (e.id === id ? { ...e, ...p } : e)))

  async function run(command: string, confirm = false, existing?: number) {
    setBusy(true)
    const id = existing ?? nextId.current++
    if (!existing) setEntries((l) => [...l, { id, cmd: command, running: true }])
    else patch(id, { running: true, info: undefined })
    try {
      const r = await cluster.run({ command, identity, namespace, confirm, lab_id: labId, stdin: /\s-f\s+-(\s|$)/.test(command) ? yaml : undefined })
      if (r.refused) patch(id, { running: false, info: `${t('term.refused')}: ${r.reason}` })
      else if (r.needs_confirm) {
        patch(id, { running: false, info: t('term.awaitingConfirm') })
        setPending({ display: r.display || command, command, id })
      } else {
        noteCommand(command)
        const timedOut = r.code === -1 && /timed out/i.test(r.stderr || '')
        patch(id, { running: false, code: r.code, stdout: r.stdout || '', stderr: r.stderr || '', info: timedOut ? t('term.timedOut') : !r.stdout && !r.stderr ? t('term.noOutput') : undefined })
      }
    } catch (e) {
      patch(id, { running: false, code: -1, stderr: String((e as Error).message) })
    }
    setBusy(false)
  }

  const connected = status?.identities?.[identity]?.connected
  return (
    <div>
      <Transcript
        live
        title={t('term.liveTitle')}
        height={height}
        tag={<span className={`tx-tag ${connected ? 'live' : 'warn'}`}>{connected ? t('term.tagLive') : t('term.notConnected')}</span>}
        entries={entries}
        onClear={() => setEntries([])}
        empty={t('term.liveIntro')}
        extra={
          <>
            <select value={identity} onChange={(e) => setIdentity(e.target.value as 'learner' | 'reader')} aria-label={t('term.identity')}>
              <option value="learner">{t('term.idLearner')}</option>
              <option value="reader">{t('term.idReader')}</option>
            </select>
            {namespace && <span className="tx-tag">-n {namespace}</span>}
            <button className="icon-btn" aria-pressed={showYaml} onClick={() => setShowYaml(!showYaml)} title={t('term.yaml')} aria-label={t('term.yaml')}>
              <Icon name="file" size={15} />
            </button>
          </>
        }
        input={
          <>
            {showYaml && <textarea className="yaml-in" value={yaml} onChange={(e) => setYaml(e.target.value)} placeholder={t('term.yamlHint')} rows={8} spellCheck={false} aria-label="YAML" />}
            {pending && (
              <div className="tx-confirm" role="alertdialog" aria-label={t('term.confirmTitle')}>
                <Icon name="bolt" size={16} />
                <span>{t('term.confirmWrite')}</span>
                <code>{pending.display}</code>
                <button
                  className="btn primary sm"
                  autoFocus
                  onClick={() => {
                    const p = pending
                    setPending(null)
                    run(p.command, true, p.id)
                  }}
                  data-testid="term-confirm"
                >
                  {t('term.confirmRun')}
                </button>
                <button
                  className="btn sm"
                  onClick={() => {
                    patch(pending.id, { info: t('ui.cancelled') })
                    setPending(null)
                  }}
                >
                  {t('ui.cancel')}
                </button>
              </div>
            )}
            <PromptInput onSubmit={(c) => run(c)} onClear={() => setEntries([])} seed={seed} placeholder="oc get pods" busy={busy} testid="live-input" />
          </>
        }
      />
    </div>
  )
}

/** Learner-controlled recorded examples: no autoplay or fake typing timers. */
export function ReplayReel({ items, label }: { items: CommandRef[]; label: string }) {
  const [i, setI] = useState(0)
  const cur = items.length ? items[i % items.length] : undefined
  if (!cur) return <div className="hero-term sk" style={{ minHeight: 220 }} />
  return <section className="tx transcript wrap hero-term" aria-label={label}>
    <div className="tx-head"><span className="tx-title"><Icon name="terminal" size={15} /> {t('home.heroTermTitle')}</span>
      <a className="tx-tag" href={cur.kind === 'lesson' ? lessonHref(cur.lab) : labHref(cur.lab)}>{cur.lab_title}</a></div>
    <div className="tx-body"><div className="tx-inner"><div className="tx-cmdline"><span className="tx-prompt" aria-hidden="true">$</span><span className="cmd"><HiCmd text={cur.cmd} /></span></div>
      <Stream text={cur.stdout} maxLines={9} />{cur.stderr && <Stream text={cur.stderr} err maxLines={4} />}
      <p className="transcript-note">Recorded output. Very long output may have been shortened.</p>
    </div></div>
    {items.length > 1 && <div className="transcript-reel-controls"><button className="btn sm ghost" onClick={() => setI(x => (x + items.length - 1) % items.length)}>Previous example</button><button className="btn sm ghost" onClick={() => setI(x => (x + 1) % items.length)}>Next example</button></div>}
  </section>
}
