// Shared building blocks for the simulations: the shell (honesty badge, scenario, predict-first gate,
// challenges, model scope, live region) and small accessible controls. Self-contained on purpose: it only
// depends on React and sims.css.
import { createContext, useContext, useEffect, useId, useRef, useState, type ComponentType, type ReactNode } from 'react'

export type DocLink = { label: string; url: string }
export type ModelScope = { includes: string[]; leavesOut: string[]; links: DocLink[] }
export type PredictChoice = { id: string; label: string; correct?: boolean; feedback: string }
export type PredictSpec = { question: string; choices: PredictChoice[]; explain: string }
export type Challenge = { id: string; title: string; hint: string; done: boolean }

// ---------------------------------------------------------------- storage (per-viewer convenience only)
// Keys start with `oa.sim.`: "Reset all learning progress" (lib/progress.ts resetProgress) deletes them too.
const store = {
  get(key: string): string | null {
    try {
      return window.localStorage.getItem(key)
    } catch {
      return null
    }
  },
  set(key: string, value: string) {
    try {
      window.localStorage.setItem(key, value)
    } catch {
      /* private mode or blocked storage: the sim still works */
    }
  },
  remove(key: string) {
    try {
      window.localStorage.removeItem(key)
    } catch {
      /* nothing to do */
    }
  },
}

// ---------------------------------------------------------------- reset (one implementation for every model)
// "Reset model" remounts the whole model, so every piece of its state (React state, timers, logs, selections) is back
// to its initial value without each model having to list it. The only state kept outside React, the prediction and the
// completed challenges in localStorage, is deleted first, so the remounted model starts exactly as on a first visit
// (prediction open, nothing selected). Learning progress is never touched.
const ResetCtx = createContext<(() => void) | null>(null)

/** Wraps a model component so that SimShell can offer "Reset model". */
export function withReset(id: string, Model: ComponentType): () => JSX.Element {
  return function ResettableModel() {
    const [attempt, setAttempt] = useState(0)
    const [msg, announce] = useAnnouncer()
    const host = useRef<HTMLDivElement>(null)
    const reset = () => {
      store.remove(`oa.sim.${id}.challenges`)
      store.remove(`oa.sim.${id}.predict`)
      setAttempt((n) => n + 1)
      announce('Model reset to its starting state.')
    }
    useEffect(() => {
      if (attempt) host.current?.querySelector<HTMLElement>('.sim-title')?.focus({ preventScroll: true }) // the button pressed was replaced
    }, [attempt])
    return (
      <div className="sim-host" ref={host}>
        <ResetCtx.Provider value={reset}>
          <Model key={attempt} />
        </ResetCtx.Provider>
        <p className="sim-sr" role="status" aria-live="polite">
          {msg}
        </p>
      </div>
    )
  }
}

// ---------------------------------------------------------------- hooks
export function useReducedMotion(): boolean {
  const query = '(prefers-reduced-motion: reduce)'
  const [reduced, setReduced] = useState(() => typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia(query).matches)
  useEffect(() => {
    if (!window.matchMedia) return
    const m = window.matchMedia(query)
    const on = () => setReduced(m.matches)
    m.addEventListener?.('change', on)
    return () => m.removeEventListener?.('change', on)
  }, [])
  return reduced
}

/** Messages for the polite live region. Repeating the same text is still announced. */
export function useAnnouncer(): [string, (msg: string) => void] {
  const [msg, setMsg] = useState('')
  const flip = useRef(false)
  const announce = (m: string) => {
    flip.current = !flip.current
    setMsg(m + (flip.current ? ' ' : ''))
  }
  return [msg, announce]
}

/** Announces `text` whenever it changes (not on first render). */
export function useAnnounceChange(text: string): string {
  const [msg, announce] = useAnnouncer()
  const prev = useRef(text)
  useEffect(() => {
    if (prev.current === text) return
    prev.current = text
    announce(text)
  }, [text]) // eslint-disable-line react-hooks/exhaustive-deps
  return msg
}

// ---------------------------------------------------------------- icons (stroke, currentColor, decorative)
const PATHS: Record<string, string> = {
  check: 'M4 12l5 5L20 6',
  x: 'M6 6l12 12M18 6L6 18',
  alert: 'M12 3l9.5 17h-19zM12 10v4M12 17.5v.5',
  info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v6M12 7.5v.5',
  play: 'M7 4l13 8-13 8z',
  step: 'M5 5l9 7-9 7zM18 5v14',
  reset: 'M4 4v6h6M4.5 15a8 8 0 1 0 1.9-8.3L4 10',
  flask: 'M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3M7 15h10',
  target: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 12h.01',
  bulb: 'M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z',
  ext: 'M14 4h6v6M20 4l-9 9M18 14v6H4V6h6',
  arrow: 'M5 12h14M13 6l6 6-6 6',
  undo: 'M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3',
}
export function SimIcon({ name, size = 16 }: { name: keyof typeof PATHS | string; size?: number }) {
  return (
    <svg className="sim-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={PATHS[name] || PATHS.info} />
    </svg>
  )
}

// ---------------------------------------------------------------- shell
export function SimShell(props: {
  id: string
  title: string
  scenario: ReactNode
  /** Omit when the model provides its own prediction for each edited scenario. */
  predict?: PredictSpec
  scope: ModelScope
  challenges: Challenge[]
  announcement: string
  children: ReactNode
}) {
  const { id, title, scenario, predict, scope, challenges, announcement, children } = props
  const headingId = useId()
  const [picked, setPicked] = useState<string | null>(() => store.get(`oa.sim.${id}.predict`))
  const [done, setDone] = useState<string[]>(() => {
    const raw = store.get(`oa.sim.${id}.challenges`)
    return raw ? raw.split(',').filter(Boolean) : []
  })
  const [shellMsg, announceShell] = useAnnouncer()
  const reset = useContext(ResetCtx)
  const [opened, setOpened] = useState(() => !predict || !!picked) // the model stays open while the prediction is answered again

  // challenges stay completed once met
  useEffect(() => {
    const fresh = challenges.filter((c) => c.done && !done.includes(c.id))
    if (!fresh.length) return
    const next = [...done, ...fresh.map((c) => c.id)]
    setDone(next)
    store.set(`oa.sim.${id}.challenges`, next.join(','))
    announceShell(`Challenge complete: ${fresh.map((c) => c.title).join('; ')}`)
  }, [challenges.map((c) => `${c.id}:${c.done}`).join('|')])

  const answer = (choice: string) => {
    if (picked) return
    setPicked(choice)
    store.set(`oa.sim.${id}.predict`, choice)
    const c = predict?.choices.find((x) => x.id === choice)
    announceShell(`${c?.correct ? 'Correct.' : 'Not quite.'}${opened ? '' : ' The simulator is now open below.'}`)
    setOpened(true)
  }
  /** Answer the prediction again (not scored, not recorded as progress). */
  const predictAgain = () => {
    setPicked(null)
    store.remove(`oa.sim.${id}.predict`)
    announceShell('Prediction cleared: choose again.')
  }

  return (
    <section className="sim-root" aria-labelledby={headingId} data-sim={id}>
      <header className="sim-head">
        <div className="sim-head-row">
          <h2 className="sim-title" id={headingId} tabIndex={-1}>
            {title}
          </h2>
          <span className="sim-badge" title="A simplified, deterministic model running in your browser. Nothing here touches a cluster.">
            <SimIcon name="flask" size={14} /> Model — not a real cluster
          </span>
          {reset && opened && (
            <button type="button" className="sim-btn sim-reset" data-variant="quiet" onClick={reset} data-testid="sim-reset" title="Back to the starting state of this model; your learning progress is not changed">
              <SimIcon name="reset" />
              <span>Reset model</span>
            </button>
          )}
        </div>
        <div className="sim-scenario">{scenario}</div>
      </header>

      {predict && <Predict spec={predict} picked={picked} onPick={answer} onAgain={predictAgain} />}

      {!predict || opened ? (
        <div className="sim-body">
          {children}
          {challenges.length > 0 && <Challenges items={challenges} done={done} />}
        </div>
      ) : (
        <p className="sim-locked">
          <SimIcon name="target" />
          <span className="sim-locked-t">Answer the prediction to open the simulator. There is no penalty for a wrong guess: the point is to notice what surprises you.</span>{' '}
          <button
            type="button"
            className="sim-skip"
            data-testid="sim-skip"
            onClick={() => {
              // an expert may open the model directly; the skip is remembered as a skip, not as an answer
              setPicked('skipped')
              setOpened(true)
              store.set(`oa.sim.${id}.predict`, 'skipped')
              announceShell('The simulator is now open below.')
            }}
          >
            Skip the prediction and open the model
          </button>
        </p>
      )}

      <ScopePanel scope={scope} />
      <p className="sim-sr" role="status" aria-live="polite">
        {announcement}
      </p>
      <p className="sim-sr" role="status" aria-live="polite">
        {shellMsg}
      </p>
    </section>
  )
}

function Predict({ spec, picked, onPick, onAgain }: { spec: PredictSpec; picked: string | null; onPick: (id: string) => void; onAgain: () => void }) {
  const qid = useId()
  const chosen = spec.choices.find((c) => c.id === picked)
  const group = useRef<HTMLDivElement>(null)
  const again = () => {
    onAgain()
    requestAnimationFrame(() => group.current?.querySelector<HTMLElement>('.sim-choice')?.focus())
  }
  return (
    <section className="sim-predict" aria-labelledby={qid}>
      <h3 className="sim-kicker" id={qid}>
        <SimIcon name="bulb" /> Predict first
      </h3>
      <p className="sim-predict-q">{spec.question}</p>
      <div className="sim-choices" role="group" aria-label="Your prediction" ref={group}>
        {spec.choices.map((c) => {
          const state = !picked ? 'open' : c.correct ? 'correct' : c.id === picked ? 'wrong' : 'other'
          return (
            <button key={c.id} type="button" className="sim-choice" data-state={state} aria-pressed={picked === c.id} aria-disabled={!!picked} onClick={() => onPick(c.id)}>
              <span className="sim-choice-mark" aria-hidden="true">
                {state === 'correct' ? <SimIcon name="check" /> : state === 'wrong' ? <SimIcon name="x" /> : null}
              </span>
              <span>{c.label}</span>
            </button>
          )
        })}
      </div>
      {chosen && (
        <div className="sim-feedback" data-tone={chosen.correct ? 'ok' : 'warn'}>
          <p>
            <strong>{chosen.correct ? 'Correct.' : 'Not quite.'}</strong> {chosen.feedback}
          </p>
          <p>{spec.explain}</p>
        </div>
      )}
      {picked && (
        <button type="button" className="sim-btn sim-again" data-variant="quiet" onClick={again} data-testid="sim-predict-again">
          <SimIcon name="reset" />
          <span>Try again</span>
        </button>
      )}
    </section>
  )
}

function Challenges({ items, done }: { items: Challenge[]; done: string[] }) {
  const n = items.filter((c) => done.includes(c.id)).length
  return (
    <section className="sim-challenges" aria-label="Challenges">
      <h3 className="sim-kicker">
        <SimIcon name="target" /> Challenges <span className="sim-count">{n} / {items.length}</span>
      </h3>
      <ol className="sim-challenge-list">
        {items.map((c) => {
          const ok = done.includes(c.id)
          return (
            <li key={c.id} className="sim-challenge" data-done={ok}>
              <span className="sim-challenge-mark" aria-hidden="true">
                {ok ? <SimIcon name="check" /> : null}
              </span>
              <div>
                <p className="sim-challenge-title">
                  {c.title}
                  <span className="sim-sr">{ok ? ' (completed)' : ' (not completed yet)'}</span>
                </p>
                <details className="sim-hint">
                  <summary>Hint</summary>
                  <p>{c.hint}</p>
                </details>
              </div>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

function ScopePanel({ scope }: { scope: ModelScope }) {
  return (
    <details className="sim-scope">
      <summary>
        <SimIcon name="info" /> What this model includes / leaves out
      </summary>
      <div className="sim-scope-grid">
        <div>
          <h4>Includes</h4>
          <ul>
            {scope.includes.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
        <div>
          <h4>Leaves out or simplifies</h4>
          <ul>
            {scope.leavesOut.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
      </div>
      <h4>Official documentation</h4>
      <ul className="sim-links">
        {scope.links.map((l) => (
          <li key={l.url}>
            <a href={l.url} target="_blank" rel="noreferrer noopener">
              {l.label} <SimIcon name="ext" size={12} />
              <span className="sim-sr"> (opens in a new tab)</span>
            </a>
          </li>
        ))}
      </ul>
    </details>
  )
}

// ---------------------------------------------------------------- controls
export function Panel({ title, children, className, aside }: { title: ReactNode; children: ReactNode; className?: string; aside?: ReactNode }) {
  const id = useId()
  return (
    <section className={`sim-panel ${className || ''}`} aria-labelledby={id}>
      <div className="sim-panel-head">
        <h3 className="sim-panel-title" id={id}>
          {title}
        </h3>
        {aside}
      </div>
      {children}
    </section>
  )
}

export function NumField({ label, value, onChange, min, max, step = 1, unit, hint, disabled }: { label: ReactNode; value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; unit?: string; hint?: ReactNode; disabled?: boolean }) {
  const [text, setText] = useState(String(value))
  const hintId = useId()
  useEffect(() => setText(String(value)), [value])
  const commit = (raw: string) => {
    setText(raw)
    if (raw.trim() === '') return
    let v = Number(raw)
    if (!Number.isFinite(v)) return
    if (min !== undefined) v = Math.max(min, v)
    if (max !== undefined) v = Math.min(max, v)
    if (v !== value) onChange(v)
  }
  return (
    <label className="sim-field">
      <span className="sim-label">{label}</span>
      <span className="sim-input-wrap">
        <input type="number" inputMode="numeric" value={text} min={min} max={max} step={step} disabled={disabled} aria-describedby={hint ? hintId : undefined} onChange={(e) => commit(e.target.value)} onBlur={() => setText(String(value))} />
        {unit && <span className="sim-unit">{unit}</span>}
      </span>
      {hint && (
        <span className="sim-hint-text" id={hintId}>
          {hint}
        </span>
      )}
    </label>
  )
}

export function TextField({ label, value, onChange, hint, mono = true, placeholder }: { label: ReactNode; value: string; onChange: (v: string) => void; hint?: ReactNode; mono?: boolean; placeholder?: string }) {
  const hintId = useId()
  return (
    <label className="sim-field">
      <span className="sim-label">{label}</span>
      <input type="text" className={mono ? 'sim-mono' : ''} value={value} placeholder={placeholder} spellCheck={false} autoCapitalize="off" autoCorrect="off" aria-describedby={hint ? hintId : undefined} onChange={(e) => onChange(e.target.value)} />
      {hint && (
        <span className="sim-hint-text" id={hintId}>
          {hint}
        </span>
      )}
    </label>
  )
}

export function SelectField<T extends string>({ label, value, options, onChange, hint }: { label: ReactNode; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; hint?: ReactNode }) {
  const hintId = useId()
  const labelId = useId() // the name is the label alone; the hint is a description, not part of the name
  return (
    <label className="sim-field">
      <span className="sim-label" id={labelId}>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value as T)} aria-labelledby={labelId} aria-describedby={hint ? hintId : undefined}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {hint && (
        <span className="sim-hint-text" id={hintId}>
          {hint}
        </span>
      )}
    </label>
  )
}

export function Toggle({ label, checked, onChange, hint, disabled }: { label: ReactNode; checked: boolean; onChange: (v: boolean) => void; hint?: ReactNode; disabled?: boolean }) {
  const hintId = useId()
  const labelId = useId() // name = label only; the hint describes
  return (
    <label className="sim-toggle" data-disabled={disabled || undefined}>
      <input type="checkbox" role="switch" checked={checked} disabled={disabled} aria-labelledby={labelId} aria-describedby={hint ? hintId : undefined} onChange={(e) => onChange(e.target.checked)} />
      <span className="sim-switch" aria-hidden="true" />
      <span className="sim-toggle-text">
        <span id={labelId}>{label}</span>
        {hint && (
          <span className="sim-hint-text" id={hintId}>
            {hint}
          </span>
        )}
      </span>
    </label>
  )
}

/** Segmented control built on native radio buttons (arrow keys work). */
export function Segmented<T extends string>({ label, value, options, onChange, hint }: { label: ReactNode; value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void; hint?: ReactNode }) {
  const name = useId()
  return (
    <fieldset className="sim-seg-field">
      <legend className="sim-label">{label}</legend>
      <div className="sim-seg">
        {options.map((o) => (
          <label key={o.value}>
            <input type="radio" name={name} value={o.value} checked={value === o.value} onChange={() => onChange(o.value)} />
            <span>{o.label}</span>
          </label>
        ))}
      </div>
      {hint && <span className="sim-hint-text">{hint}</span>}
    </fieldset>
  )
}

export function Btn({ children, onClick, variant = 'default', disabled, icon, title }: { children: ReactNode; onClick: () => void; variant?: 'default' | 'primary' | 'danger' | 'quiet'; disabled?: boolean; icon?: string; title?: string }) {
  return (
    <button type="button" className="sim-btn" data-variant={variant} onClick={onClick} disabled={disabled} title={title}>
      {icon && <SimIcon name={icon} />}
      <span>{children}</span>
    </button>
  )
}

export type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'muted' | 'accent' | 'violet'
export function Chip({ tone = 'muted', children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span className="sim-chip" data-tone={tone} title={title}>
      {children}
    </span>
  )
}

export function Code({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <pre className="sim-code" aria-label={label}>
      <code>{children}</code>
    </pre>
  )
}

/** Event log that grows downwards; shows the latest entries and lets the learner expand the rest (no inner scrollbar). */
export function Log<T>({ items, render, keyOf, empty, initial = 6, label = 'Event log' }: { items: T[]; render: (item: T) => ReactNode; keyOf: (item: T, i: number) => string | number; empty: ReactNode; initial?: number; label?: string }) {
  const [all, setAll] = useState(false)
  const shown = all ? items : items.slice(-initial)
  const hidden = items.length - shown.length
  return (
    <div className="sim-log-wrap">
      {items.length === 0 ? (
        <p className="sim-empty">{empty}</p>
      ) : (
        <>
          {hidden > 0 && (
            <button type="button" className="sim-linkbtn" onClick={() => setAll(true)}>
              Show {hidden} earlier {hidden === 1 ? 'entry' : 'entries'}
            </button>
          )}
          <ol className="sim-log" aria-label={label}>
            {shown.map((it, i) => (
              <li key={keyOf(it, i)}>{render(it)}</li>
            ))}
          </ol>
          {all && items.length > initial && (
            <button type="button" className="sim-linkbtn" onClick={() => setAll(false)}>
              Show only the latest {initial}
            </button>
          )}
        </>
      )}
    </div>
  )
}

/** Small horizontal meter (value 0..max) with an optional highlighted segment. */
export function Meter({ value, max, extra = 0, label, tone = 'accent' }: { value: number; max: number; extra?: number; label: string; tone?: Tone }) {
  const pct = (v: number) => `${Math.max(0, Math.min(100, (v / max) * 100))}%`
  const over = value + extra > max
  return (
    <div className="sim-meter" role="img" aria-label={label} data-over={over || undefined}>
      <span className="sim-meter-fill" data-tone={tone} style={{ width: pct(value) }} />
      {extra > 0 && <span className="sim-meter-extra" style={{ left: pct(value), width: pct(Math.min(extra, Math.max(0, max - value))) }} />}
    </div>
  )
}

export function Stat({ label, value, tone }: { label: ReactNode; value: ReactNode; tone?: Tone }) {
  return (
    <div className="sim-stat" data-tone={tone}>
      <span className="sim-stat-value">{value}</span>
      <span className="sim-stat-label">{label}</span>
    </div>
  )
}
