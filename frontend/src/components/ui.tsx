import { useEffect, useState, type ReactNode } from 'react'
import type { Mode } from '../lib/data'
import { t } from '../lib/i18n'
import type { LabStatus } from '../lib/progress'

// ---------------------------------------------------------------- icons (simple strokes, currentColor)
const P: Record<string, ReactNode> = {
  home: <path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z" />,
  map: <path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14" />,
  flask: <path d="M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3M7 15h10" />,
  siren: <path d="M7 18v-6a5 5 0 0 1 10 0v6M5 21h14v-3H5zM12 3v2M4.2 6.2l1.4 1.4M19.8 6.2l-1.4 1.4" />,
  terminal: <path d="M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM7 10l3 2-3 2M12 15h5" />,
  book: <path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM4 21V5M8 7h7" />,
  cards: <path d="M7 4h12a1 1 0 0 1 1 1v12M4 8h12a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z" />,
  shapes: <path d="M8 3l4 7H4zM17 14a4 4 0 1 0 0 .1M3 14h7v7H3z" />,
  compass: <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM15.5 8.5l-2 5-5 2 2-5z" />,
  plug: <path d="M9 2v5M15 2v5M6 7h12v4a6 6 0 0 1-12 0zM12 17v5" />,
  user: <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0" />,
  info: <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v6M12 7.5v.5" />,
  search: <path d="M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4" />,
  play: <path d="M7 4l13 8-13 8z" />,
  check: <path d="M4 12l5 5L20 6" />,
  flag: <path d="M5 21V4M5 4h11l-2.5 4L16 12H5" />,
  list: <path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01" />,
  expand: <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  copy: <path d="M9 9h11v11H9zM5 15H4V4h11v1" />,
  sun: <path d="M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" />,
  moon: <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />,
  flame: <path d="M12 22c4 0 7-3 7-7 0-5-5-7-5-12-3 2-4 5-4 7-1-1-2-2-2-4-2 2-3 5-3 9 0 4 3 7 7 7z" />,
  bolt: <path d="M13 2L4 14h7l-1 8 9-12h-7z" />,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  back: <path d="M19 12H5M11 6l-6 6 6 6" />,
  lock: <path d="M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4" />,
  bulb: <path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z" />,
  eye: <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />,
  layers: <path d="M12 3l9 5-9 5-9-5zM3 13l9 5 9-5M3 17l9 5 9-5" />,
  shield: <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" />,
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  globe: <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18" />,
  clock: <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2" />,
  target: <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 12h.01" />,
  refresh: <path d="M20 11a8 8 0 0 0-14.9-3M4 4v4h4M4 13a8 8 0 0 0 14.9 3M20 20v-4h-4" />,
  external: <path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6" />,
  wrap: <path d="M4 6h16M4 12h13a3 3 0 0 1 0 6h-4M15 15l-3 3 3 3M4 18h5" />,
  trash: <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" />,
  file: <path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zM14 3v5h5M9 13h6M9 17h6" />,
  grid: <path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" />,
  minus: <path d="M5 12h14" />,
  plus: <path d="M12 5v14M5 12h14" />,
  fit: <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />,
  box: <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12v9M12 12L4 7.5" />,
  rocket: <path d="M5 15c-1.5 1.5-2 5-2 5s3.5-.5 5-2M9 15l-3-3c1.5-4 5-9 13-9 0 8-5 11.5-9 13zM15 9.01V9" />,
  building: <path d="M4 21V5l8-2v18M12 7l8 2v12M3 21h18M7 8h2M7 12h2M7 16h2M15 12h2M15 16h2" />,
  route: <path d="M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM6 15V9a4 4 0 0 1 4-4h6M18 9v6a4 4 0 0 1-4 4H8" />,
  wrench: <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z" />,
}
export function Icon({ name, size = 18, className }: { name: keyof typeof P | string; size?: number; className?: string }) {
  return (
    <svg className={`icon ${className || ''}`} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {P[name] ?? P.info}
    </svg>
  )
}

// ---------------------------------------------------------------- small pieces
export function ModeBadge({ mode }: { mode: Mode }) {
  return (
    <span className={`badge mode-${mode}`} title={t(`mode.${mode}.help` as 'mode.REAL_LAB.help')}>
      {t(`mode.${mode}` as 'mode.REAL_LAB')}
    </span>
  )
}

export function LevelDots({ level }: { level: number }) {
  return (
    <span className="level" title={t('ui.level', { n: level })} aria-label={t('ui.level', { n: level })}>
      {[1, 2, 3].map((n) => (
        <i key={n} className={n <= level ? 'on' : ''} />
      ))}
    </span>
  )
}

export function Ring({ value, size = 44, stroke = 4, label }: { value: number; size?: number; stroke?: number; label?: ReactNode }) {
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const v = Math.max(0, Math.min(1, value))
  return (
    <span className="ring" style={{ width: size, height: size }}>
      <svg width={size} height={size} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} strokeWidth={stroke} className="ring-bg" />
        <circle cx={size / 2} cy={size / 2} r={r} strokeWidth={stroke} className="ring-fg" strokeDasharray={c} strokeDashoffset={c * (1 - v)} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      </svg>
      <span className="ring-label">{label ?? `${Math.round(v * 100)}%`}</span>
    </span>
  )
}

export function Bar({ value, tone, label }: { value: number; tone?: string; label?: string }) {
  return (
    <span className={`bar ${tone || ''}`} role="progressbar" aria-label={label || t('ui.progress')} aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <i style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
    </span>
  )
}

const STATUS_TONE: Record<LabStatus, string> = { new: 'muted', started: 'info', replayed: 'info', diagnosed: 'info', revealed: 'warn', partial: 'warn', failed: 'bad', verified: 'ok' }
export function LabStatusPill({ s }: { s: LabStatus }) {
  if (s === 'new') return null
  return <span className={`pill ${STATUS_TONE[s]}`}>{t(`status.${s}` as 'status.new')}</span>
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>
}

/** Copies `text` exactly. Keyboard accessible; the result is announced ("Copied") and shown on the button. */
export function CopyButton({ text, label, showLabel = false }: { text: string; label?: string; showLabel?: boolean }) {
  const [state, setState] = useState<'idle' | 'done' | 'failed'>('idle')
  const copy = async () => {
    let ok = false
    try {
      await navigator.clipboard.writeText(text)
      ok = true
    } catch {
      const ta = document.createElement('textarea') // clipboard API unavailable (insecure origin, old browser)
      ta.value = text
      ta.setAttribute('readonly', '')
      ta.style.cssText = 'position:fixed;opacity:0;top:0'
      document.body.appendChild(ta)
      ta.select()
      try { ok = document.execCommand('copy') } catch { ok = false }
      ta.remove()
    }
    setState(ok ? 'done' : 'failed')
    setTimeout(() => setState('idle'), 1500)
  }
  return (
    <>
      <button type="button" className={showLabel ? 'copy-btn' : 'icon-btn'} title={label || t('ui.copy')} aria-label={label || t('ui.copy')} onClick={copy} data-testid="copy">
        <Icon name={state === 'done' ? 'check' : 'copy'} size={15} />
        {showLabel && <span aria-hidden="true">{state === 'done' ? t('ui.copied') : t('ui.copy')}</span>}
      </button>
      <span className="sr-only" role="status" aria-live="polite">{state === 'done' ? t('ui.copied') : state === 'failed' ? t('ui.copyFailed') : ''}</span>
    </>
  )
}

export function Empty({ children, icon = 'info' }: { children: ReactNode; icon?: string }) {
  return (
    <div className="empty">
      <Icon name={icon} size={22} />
      <div>{children}</div>
    </div>
  )
}

/** Placeholder with the shape of a page while it loads. */
export function PageSkeleton() {
  return (
    <div className="sk-page" aria-busy="true" aria-label={t('ui.loading')}>
      <div className="sk sk-line" style={{ width: '30%' }} />
      <div className="sk sk-title" />
      <div className="sk sk-line" style={{ width: '80%' }} />
      <div className="sk sk-line" style={{ width: '65%' }} />
      <div className="sk sk-block" />
      <div className="sk sk-block" />
    </div>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="spinner" role="status">
      <span className="spin" />
      {label ?? t('ui.loading')}
    </div>
  )
}

/** A missing page, lesson or lab: a real heading (the page has one h1) and a way back to the map. */
export function NotFound({ text }: { text?: ReactNode }) {
  return (
    <div className="page not-found" data-testid="not-found">
      <h1>{t('app.notFound')}</h1>
      <p>{text || t('app.notFoundText')}</p>
      <p>
        <a href="/learn">{t('app.notFoundBack')}</a>
      </p>
    </div>
  )
}

export function Callout({ tone = 'info', title, children, icon, role }: { tone?: 'info' | 'ok' | 'warn' | 'bad' | 'tip'; title?: ReactNode; children: ReactNode; icon?: string; role?: string }) {
  return (
    <div className={`callout ${tone}`} role={role}>
      <Icon name={icon || { info: 'info', ok: 'check', warn: 'bulb', bad: 'siren', tip: 'bulb' }[tone]} size={18} />
      <div>
        {title && <div className="callout-t">{title}</div>}
        {children}
      </div>
    </div>
  )
}

export function Crumbs({ items }: { items: [string, string?][] }) {
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      {items.map(([label, href], i) => (
        <span key={i}>
          {href ? <a href={href}>{label}</a> : <span aria-current="page">{label}</span>}
          {i < items.length - 1 && <span className="sep">/</span>}
        </span>
      ))}
    </nav>
  )
}

export function Refs({ refs }: { refs: { title: string; url: string }[] }) {
  if (!refs?.length) return null
  return (
    <ul className="refs">
      {refs.map((r) => (
        <li key={r.url}>
          <a href={r.url} target="_blank" rel="noreferrer">
            {r.title} <Icon name="external" size={13} />
          </a>
        </li>
      ))}
    </ul>
  )
}

/** Projector-friendly view of the page that renders it: hides navigation, enlarges text. Esc or Exit leaves it.
 * The class lives on <html>, so it is removed when this component unmounts: leaving the page always ends it. */
export function PresentButton() {
  const [on, setOn] = useState(false)
  useEffect(() => {
    if (!on) return
    const el = document.documentElement
    el.classList.add('present')
    const off = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOn(false)
    }
    window.addEventListener('keydown', off)
    return () => {
      window.removeEventListener('keydown', off)
      el.classList.remove('present')
    }
  }, [on])
  return (
    <>
      <button className="btn sm ghost present-btn" aria-pressed={on} onClick={() => setOn(!on)} title={t('ui.presentHelp')}>
        <Icon name="eye" size={14} /> {t('ui.present')}
      </button>
      {on && (
        <button className="btn sm present-exit" onClick={() => setOn(false)} data-testid="present-exit">
          <Icon name="x" size={14} /> {t('ui.presentExit')}
        </button>
      )}
    </>
  )
}

export function fmtDate(iso?: string | null) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  } catch {
    return iso.slice(0, 10)
  }
}

export function Panel({ title, children, actions, className, testid }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; className?: string; testid?: string }) {
  return (
    <section className={`panel ${className || ''}`} data-testid={testid}>
      {(title || actions) && (
        <header className="panel-h">
          <h3>{title}</h3>
          <div className="panel-actions">{actions}</div>
        </header>
      )}
      <div className="panel-b">{children}</div>
    </section>
  )
}
