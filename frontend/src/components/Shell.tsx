import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, type CommandRef, type LabSummary, type ReviewCard } from '../lib/data'
import { useApp } from '../lib/app'
import { getLang, LANG_NAMES, setLang, t } from '../lib/i18n'
import { plain, searchRanked } from '../lib/match'
import { DIAGRAMS } from '../lib/diagrams'
import { loadSims, type SimDef } from '../pages/Studio'
import { useProgress, useSaveFailed } from '../lib/progress'
import { cardQueue } from '../lib/standing'
import { detailKind, labHref, lessonHref } from '../lib/urls'
import { COPYRIGHT, CREATOR } from '../lib/brand'
import { openPageActions, ReportSiteLink, usePageActions } from './Contribute'
import { hasRepo } from '../lib/contribute'
import { Toasts } from './Toast'
import { trapTab, useOverlay } from '../lib/overlay'
import { Icon, Kbd } from './ui'

export function useTheme() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || 'dark')
  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])
  const toggle = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    try {
      localStorage.setItem('osa.theme', next) // remembered only once the visitor chooses
    } catch {
      /* ignore */
    }
  }
  return [theme, toggle] as const
}

/** Recall cards ready in Review: new ones and ones due again (lib/standing.ts cardQueue). */
export function useCardCounts() {
  const { lang } = useApp()
  const prog = useProgress()
  const [cards, setCards] = useState<ReviewCard[]>([])
  useEffect(() => {
    api.cards(lang).then(setCards, () => setCards([]))
  }, [lang])
  const q = cardQueue(cards, prog)
  return { ready: q.ready.length, fresh: q.fresh.length, again: q.again.length }
}
export const useDueCount = () => useCardCounts().ready

// Information architecture: four sections in the top bar. Each section has a few tabs, shown only on its hub
// pages; lessons, labs and other detail pages get no extra chrome. Cluster tools exist only in cluster mode.
export type Section = { id: string; label: string; href: string; tabs: { href: string; label: string; match: string[] }[]; match: string[] }

export function sections(cluster: boolean): Section[] {
  const s: Section[] = [
    {
      id: 'learn', label: t('nav.learn'), href: '/learn', match: ['learn', 'course', 'lesson', 'review', 'me'],
      tabs: [
        { href: '/learn', label: t('nav.paths'), match: ['learn', 'course'] },
        { href: '/review', label: t('nav.review'), match: ['review'] },
        { href: '/me', label: t('nav.me'), match: ['me'] },
      ],
    },
    {
      id: 'practice', label: t('nav.practice'), href: '/labs', match: ['labs', 'lab', 'incidents', 'challenges', 'terminal'],
      tabs: [
        { href: '/labs', label: t('nav.labs'), match: ['labs'] },
        { href: '/incidents', label: t('nav.incidents'), match: ['incidents'] },
        { href: '/challenges', label: t('nav.challenges'), match: ['challenges'] },
        { href: '/terminal', label: t('nav.terminal'), match: ['terminal'] },
      ],
    },
    {
      id: 'explore', label: t('nav.explore'), href: '/studio', match: ['studio', 'map'],
      tabs: [
        { href: '/studio', label: t('nav.studio'), match: ['studio'] },
        { href: '/map', label: t('nav.map'), match: ['map'] },
      ],
    },
    {
      id: 'reference', label: t('nav.reference'), href: '/commands', match: ['commands', 'handbook', 'runbook', 'case', 'setup'],
      tabs: [
        { href: '/commands', label: t('nav.commands'), match: ['commands'] },
        { href: '/handbook', label: t('nav.handbook'), match: ['handbook'] },
        { href: '/setup', label: t('nav.setup'), match: ['setup'] },
      ],
    },
  ]
  if (cluster)
    s.push({
      id: 'cluster', label: t('nav.cluster'), href: '/connections', match: ['connections', 'explorer'],
      tabs: [
        { href: '/connections', label: t('nav.connections'), match: ['connections'] },
        { href: '/explorer', label: t('nav.explorer'), match: ['explorer'] },
      ],
    })
  return s
}

/** Pages whose section tabs are shown (hubs). Detail pages (a lesson, a lab) stay focused. */
const HUBS = new Set(['learn', 'course', 'review', 'me', 'labs', 'incidents', 'challenges', 'terminal', 'studio', 'map', 'commands', 'handbook', 'setup', 'connections', 'explorer'])

export function Shell({ route, children }: { route: string; children: ReactNode }) {
  const { meta, status, live, cur } = useApp()
  const repo = hasRepo({ repo: meta?.repo_url }) ? meta!.repo_url! : '' // the public repository, when the build names one
  const saveFailed = useSaveFailed()
  const prog = useProgress() // re-render the shell (badges, due count) when progress changes
  const [theme, toggleTheme] = useTheme()
  const [menu, setMenu] = useState(false)
  const [palette, setPalette] = useState(false)
  const due = useDueCount()
  // a lesson or a lab lives under its hub's address (/learn/<track>/<lesson>, /incidents/<incident>) but is a detail
  // page: the section is highlighted, its tabs are not shown
  const detail = detailKind(route)
  const top = route.split('/')[1] || ''
  const head = detail === 'lab' ? (top === 'incidents' || route.startsWith('/lab/inc.') ? 'incidents' : top === 'challenges' || route.startsWith('/lab/ch.') ? 'challenges' : 'lab') : detail || top
  const secs = sections(meta?.mode === 'cluster')
  // how many activities each practice list has, counted from the content
  const kinds: Record<string, LabSummary['kind']> = { '/labs': 'lab', '/incidents': 'incident', '/challenges': 'challenge' }
  const total = (href: string) => (kinds[href] && cur ? Object.values(cur.labs).filter((l) => l.kind === kinds[href]).length : 0)
  const active = secs.find((s) => s.match.includes(head))

  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      // another modal is open (the Go deeper sheet, an enlarged screenshot, the phone menu): search would open behind it
      // or share its keys, so the shortcuts wait until it is closed
      if ([...document.querySelectorAll('[aria-modal="true"], dialog[open]')].some((d) => !d.classList.contains('palette-wrap'))) return
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPalette((p) => !p)
      } else if (e.key === '/' && !/input|textarea|select/i.test((e.target as HTMLElement).tagName)) {
        e.preventDefault()
        setPalette(true)
      }
    }
    window.addEventListener('keydown', f)
    return () => window.removeEventListener('keydown', f)
  }, [])
  useEffect(() => setMenu(false), [route])
  const menuBtn = useRef<HTMLButtonElement>(null), searchBtn = useRef<HTMLButtonElement>(null)
  // the header's real height (it wraps on narrow screens) starts the sticky chrome (--hdr-site, tokens.css)
  const bar = useRef<HTMLElement>(null)
  useEffect(() => {
    const el = bar.current
    if (!el) return
    const set = () => document.documentElement.style.setProperty('--hdr-site', `${Math.round(el.getBoundingClientRect().height)}px`)
    set()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(set) : null
    ro?.observe(el)
    return () => ro?.disconnect()
  }, [])
  // the open phone menu is modal: what it covers (section tabs, the page, the footer) is inert, so neither Tab nor a
  // screen reader's virtual cursor reaches it (React 18 has no `inert` prop: set on the elements)
  useEffect(() => {
    if (!menu) return
    const covered = [...document.querySelectorAll<HTMLElement>('.shell > .topbar, .shell > .subnav, .shell > main, .shell > .site-foot, .shell > .tabbar')]
    covered.forEach((el) => el.setAttribute('inert', ''))
    // widening the window hides the sheet (CSS, above 880px): close the menu so the page it covered is usable again
    const wide = window.matchMedia('(min-width: 881px)')
    const closeIfWide = () => wide.matches && setMenu(false)
    wide.addEventListener('change', closeIfWide)
    return () => (wide.removeEventListener('change', closeIfWide), covered.forEach((el) => el.removeAttribute('inert')))
  }, [menu])
  // the phone menu: chosen link, a tap outside it, Escape, Back or its close button close it (lib/overlay.ts)
  const sheet = useRef<HTMLDivElement>(null)
  const closeMenuThen = useOverlay(menu, () => setMenu(false), { id: 'menu', root: sheet, opener: menuBtn, modal: true })
  const pageActions = usePageActions()
  // the phone tab bar: the four places a learner goes most, and their progress (the menu has everything)
  const tabs = [
    { id: 'home', href: '/', label: t('nav.home'), icon: 'home', on: route === '/' },
    { id: 'learn', href: '/learn', label: t('nav.learn'), icon: 'map', on: active?.id === 'learn' && head !== 'me' },
    { id: 'practice', href: '/labs', label: t('nav.practice'), icon: 'flask', on: active?.id === 'practice' },
    { id: 'explore', href: '/studio', label: t('nav.explore'), icon: 'shapes', on: active?.id === 'explore' },
    { id: 'me', href: '/me', label: t('nav.me'), icon: '', on: head === 'me' },
  ]

  return (
    <div className="shell">
      <a className="skip" href="#main" onClick={(e) => (e.preventDefault(), document.getElementById('main')?.focus())}>
        {t('nav.skip')}
      </a>
      <header className="topbar" ref={bar}>
        <a className="brand" href="/" title={t('nav.home')}>
          <Logo size={30} />
          <strong className="brand-name">{t('app.nameLine1')}{t('app.nameLine2') && <span>{t('app.nameLine2')}</span>}</strong>
        </a>
        <nav className="topnav" aria-label={t('nav.main')}>
          {secs.map((s) => (
            <a key={s.id} href={s.href} className={active?.id === s.id ? 'on' : ''} aria-current={active?.id === s.id ? 'page' : undefined}>
              {s.label}
              {s.id === 'learn' && due > 0 && <span className="dot-badge" aria-label={t('nav.dueCards', { n: due })} />}
              {s.id === 'cluster' && <span className={`dot-status ${live ? 'ok' : ''}`} aria-label={live ? t('mode.liveHelp') : t('mode.connectHelp')} />}
            </a>
          ))}
        </nav>
        <span className="grow" />
        <div id="page-actions-dock" />{/* a page's Report and Edit, once its own have scrolled away (components/Contribute.tsx) */}
        <button ref={searchBtn} className="search-btn" onClick={() => setPalette(true)} title={t('nav.searchHelp')} data-testid="search-open">
          <Icon name="search" size={16} /> <span>{t('nav.search')}</span>
          <span aria-hidden="true">
            <Kbd>Ctrl K</Kbd>
          </span>
        </button>
        <a href="/me" className="me-link" title={t('me.progressTitle')}>
          <ProgressMark cur={cur} prog={prog} /> <span className="me-link-text">{t('me.progressShort')}</span>
        </a>
        {/* a toggle named by what it turns on, with its state: "Dark theme", pressed or not (a11y) */}
        <button className="icon-btn theme-toggle" onClick={toggleTheme} aria-label={t('nav.darkTheme')} aria-pressed={theme === 'dark'} title={theme === 'dark' ? t('nav.toLight') : t('nav.toDark')} data-testid="theme-toggle">
          <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
        </button>
        <button ref={menuBtn} className="nav-toggle" onClick={() => setMenu(!menu)} aria-expanded={menu} aria-controls={menu ? 'menu-sheet' : undefined} aria-haspopup="dialog" data-testid="menu-open">
          <Icon name="menu" /> <span>{t('nav.menu')}</span>
        </button>
      </header>
      {menu && (
        // a drawer over a dimmed page: Tab stays inside it (a11y); a tap on the dimmed page closes it
        <div className="menu-backdrop" data-testid="menu-backdrop">
          <div className="menu-sheet" id="menu-sheet" ref={sheet} role="dialog" aria-modal="true" aria-labelledby="menu-title" onKeyDown={(e) => cycleTab(e, e.currentTarget)}>
            <div className="menu-top">
              <strong id="menu-title">{t('nav.menu')}</strong>
              <button className="icon-btn" onClick={() => setMenu(false)} aria-label={t('ui.close')} data-testid="menu-close">
                <Icon name="x" />
              </button>
            </div>
            {pageActions && (
              <div className="menu-group">
                <div className="menu-h">{t('nav.thisPage')}</div>
                <button className="menu-item" onClick={() => closeMenuThen(openPageActions)} data-testid="menu-page-actions">
                  <Icon name="flag" size={18} /> {pageActions.label}
                </button>
              </div>
            )}
            {secs.map((s) => (
              <div key={s.id} className="menu-group">
                <div className="menu-h">{s.label}</div>
                {s.tabs.map((tb) => (
                  <a key={tb.href} href={tb.href} className={`menu-item ${tb.match.includes(head) ? 'on' : ''}`} aria-current={tb.match.includes(head) ? 'page' : undefined}>
                    {tb.label}
                    {tb.href === '/review' && due > 0 && <span className="count">{due}</span>}
                  </a>
                ))}
              </div>
            ))}
            <div className="menu-group">
              <div className="menu-h">{t('nav.settings')}</div>
              <button className="menu-item" onClick={toggleTheme} aria-pressed={theme === 'dark'} data-testid="menu-theme">
                <Icon name={theme === 'dark' ? 'moon' : 'sun'} size={18} /> {t('nav.darkTheme')}
                <span className={`switch ${theme === 'dark' ? 'on' : ''}`} aria-hidden="true"><i /></span>
              </button>
              <a href="/about" className="menu-item">{t('nav.about')}</a>
            </div>
          </div>
        </div>
      )}
      {active && !detail && HUBS.has(top) && (
        <nav className="subnav" aria-label={active.label}>
          <div className="subnav-in">
            {active.tabs.map((tb) => {
              const on = tb.match.includes(head)
              return (
                <a key={tb.href} href={tb.href} className={on ? 'on' : ''} aria-current={on ? 'page' : undefined}>
                  {tb.label}
                  {tb.href === '/review' && due > 0 && <span className="count">{due}</span>}
                  {total(tb.href) > 0 && <small className="tab-n">{total(tb.href)}</small>}
                </a>
              )
            })}
          </div>
        </nav>
      )}
      <main id="main" tabIndex={-1}>
        {saveFailed && (
          <p className="callout warn save-failed" role="alert" data-testid="save-failed">
            {t('app.saveFailed')} <a href="/me">{t('app.saveFailedExport')}</a>
          </p>
        )}
        {children}
      </main>
      <footer className="site-foot">
        <span>{meta?.mode === 'cluster' ? (live ? t('mode.live', { v: status?.crc?.openshiftVersion || '' }) : t('mode.clusterNotConnected')) : t('mode.practice')}</span>
        <a href="/about">{t('nav.about')}</a>
        <a href="/about#own-cluster">{t('foot.ownCluster')}</a>
        <a href="/setup">{t('nav.setup')}</a>
        <ReportSiteLink />
        <p className="foot-credit" data-testid="foot-credit">
          {t('foot.createdBy')} <a href={CREATOR.url} rel="author">{CREATOR.name}</a>
          {' · '}<a href={repo || '/about#licences'}>{t('foot.openSource')}</a>
          {repo && <>{' · '}<a href={`${repo}/graphs/contributors`}>{t('foot.contributors')}</a></>}
          {' · '}<a href="/about#licences">{t('foot.licences')}</a>
        </p>
        <p className="foot-legal">{COPYRIGHT}. {t('foot.notice', { brand: t('app.name') })}</p>
      </footer>
      <nav className="tabbar" aria-label={t('nav.mobileMain')} data-testid="tabbar">
        {tabs.map((tb) => (
          <a key={tb.id} href={tb.href} className={tb.on ? 'on' : ''} aria-current={tb.on ? 'page' : undefined} data-testid={`tab-${tb.id}`}>
            <span className="tab-icon">
              {tb.icon ? <Icon name={tb.icon} size={22} /> : <ProgressMark cur={cur} prog={prog} size={22} />}
              {tb.id === 'learn' && due > 0 && <span className="dot-badge" aria-label={t('nav.dueCards', { n: due })} />}
            </span>
            <span className="tab-label">{tb.label}</span>
          </a>
        ))}
      </nav>
      {palette && <Palette onClose={() => setPalette(false)} trigger={searchBtn} />}
      <Toasts />
    </div>
  )
}

export function Logo({ size = 34 }: { size?: number }) {
  // The mark: one path climbs three levels (the layers of the stack) by turning back on itself, from a start to a
  // summit: learning that returns to earlier ideas from higher up.
  return (
    <svg className="logo" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect x="0.5" y="0.5" width="31" height="31" rx="8" fill="var(--accent)" />
      <path d="M8 24H21.5A3.5 3.5 0 0 0 21.5 17H10.5A3.5 3.5 0 0 1 10.5 10H22" fill="none" stroke="var(--accent-ink)" strokeWidth="2.4" strokeLinecap="round" opacity="0.85" />
      <circle cx="8" cy="24" r="2.4" fill="var(--accent-ink)" />
      <circle cx="23" cy="10" r="3.4" fill="var(--accent-ink)" />
    </svg>
  )
}

/** A small ring of the lessons completed, in place of a person icon: the header shows progress, not an account. */
function ProgressMark({ cur, prog, size = 18 }: { cur: ReturnType<typeof useApp>['cur']; prog: ReturnType<typeof useProgress>; size?: number }) {
  const ids = cur ? Object.keys(cur.lessons) : []
  const f = ids.length ? ids.filter((l) => prog.lessons[l]?.done || prog.lessons[l]?.skipped).length / ids.length : 0
  const c = 2 * Math.PI * 6.5
  return (
    <svg className="progress-mark" width={size} height={size} viewBox="0 0 18 18" aria-hidden="true">
      <circle cx="9" cy="9" r="6.5" fill="none" stroke="var(--muted)" strokeWidth="2.5" />
      {f > 0 && <circle cx="9" cy="9" r="6.5" fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" strokeDasharray={`${Math.max(1.5, f * c)} ${c}`} transform="rotate(-90 9 9)" />}
    </svg>
  )
}

/** Keep Tab inside a modal layer (a11y): its visible controls only (lib/overlay.ts). */
const cycleTab = (e: React.KeyboardEvent, box: HTMLElement, wrapTo?: HTMLElement | null) => trapTab(e, box, wrapTo)

// ---------------------------------------------------------------- command palette
type Hit = { kind: string; title: string; sub?: string; href: string; icon: string }

function Palette({ onClose, trigger }: { onClose: () => void; trigger: React.RefObject<HTMLButtonElement | null> }) {
  const { cur, lang } = useApp()
  const box = useRef<HTMLDivElement>(null)
  // Back, Escape and a tap outside close it; a chosen result closes it, then opens its page (lib/overlay.ts)
  const closeAndGo = useOverlay(true, onClose, { id: 'search', root: box, opener: trigger, modal: true })
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(0)
  const [cmds, setCmds] = useState<CommandRef[]>([])
  const [sims, setSims] = useState<SimDef[]>([])
  const inp = useRef<HTMLInputElement>(null)
  const opener = useRef(document.activeElement as HTMLElement | null)
  // closed: the focus goes back where it was (a11y), unless the page has moved it since (a chosen result's heading)
  useEffect(() => () => void (opener.current?.isConnected && !document.querySelector('#main')?.contains(document.activeElement) && opener.current.focus({ preventScroll: true })), [])
  useEffect(() => {
    inp.current?.focus()
    api.commands(lang).then(setCmds, () => setCmds([]))
    loadSims().then(setSims, () => setSims([]))
  }, [lang])

  const all = useMemo<Hit[]>(() => {
    const out: Hit[] = [
      { kind: t('pal.page'), title: t('nav.home'), href: '/', icon: 'home' },
      { kind: t('pal.page'), title: t('nav.paths'), href: '/learn', icon: 'map' },
      { kind: t('pal.page'), title: t('nav.labs'), href: '/labs', icon: 'flask' },
      { kind: t('pal.page'), title: t('nav.incidents'), href: '/incidents', icon: 'siren' },
      { kind: t('pal.page'), title: t('nav.review'), href: '/review', icon: 'cards' },
      { kind: t('pal.page'), title: t('nav.handbook'), href: '/handbook', icon: 'wrench' },
      { kind: t('pal.page'), title: t('nav.terminal'), href: '/terminal', icon: 'terminal' },
      { kind: t('pal.page'), title: t('nav.commands'), href: '/commands', icon: 'book' },
      { kind: t('pal.page'), title: t('nav.studio'), href: '/studio', icon: 'shapes' },
      { kind: t('pal.page'), title: t('nav.map'), href: '/map', icon: 'grid' },
      { kind: t('pal.page'), title: t('nav.me'), href: '/me', icon: 'user' },
    ]
    if (cur) {
      for (const l of Object.values(cur.lessons)) out.push({ kind: t('pal.lesson'), title: l.title, sub: plain(l.objective).slice(0, 110), href: lessonHref(l.id), icon: 'book' })
      for (const s of sims) out.push({ kind: t('pal.model'), title: s.title, sub: s.summary, href: `/studio/model/${s.id}`, icon: 'shapes' })
      for (const d of DIAGRAMS) out.push({ kind: t('pal.diagram'), title: d.title, sub: plain(d.caption || '').slice(0, 110), href: `/studio/diagram/${d.id}`, icon: 'map' })
      for (const l of Object.values(cur.labs)) out.push({ kind: l.kind === 'incident' ? t('pal.incident') : t('pal.lab'), title: l.title, sub: plain(l.summary), href: labHref(l.id), icon: l.kind === 'incident' ? 'siren' : 'flask' })
      for (const l of Object.values(cur.labs))
        for (const st of l.steps || []) out.push({ kind: t('pal.step'), title: st.title, sub: l.title, href: `${labHref(l.id)}?step=${encodeURIComponent(st.id)}`, icon: 'flask' })
      for (const r of cur.runbooks) out.push({ kind: t('pal.runbook'), title: r.title, sub: r.when, href: `/runbook/${r.id}`, icon: 'wrench' })
      for (const c of cur.cases) out.push({ kind: t('pal.case'), title: c.title, href: `/case/${c.id}`, icon: 'layers' })
      for (const c of Object.values(cur.concepts)) out.push({ kind: t('pal.concept'), title: c.title, href: `/map?concept=${encodeURIComponent(c.id)}`, icon: 'layers' })
    }
    const seen = new Set<string>()
    for (const c of cmds)
      if (c.tested && !seen.has(c.cmd)) {
        seen.add(c.cmd)
        out.push({ kind: t('pal.command'), title: c.cmd, sub: c.meaning && plain(c.meaning), href: `/commands?q=${encodeURIComponent(c.cmd)}`, icon: 'terminal' })
      }
    return out
  }, [cur, cmds, sims])

  const hits = useMemo(() => searchRanked(all, q, (h) => h.title, (h) => `${h.title} ${h.sub || ''} ${h.kind}`).slice(0, 40), [all, q])
  useEffect(() => setSel(0), [q])
  const list = useRef<HTMLUListElement>(null)
  // the active option stays in view as the arrows move it (the focus stays in the field: combobox pattern)
  useEffect(() => {
    list.current?.querySelector<HTMLElement>(`#pal-opt-${sel}`)?.scrollIntoView({ block: 'nearest' })
  }, [sel])
  const open = (h: Hit) => closeAndGo(h.href)

  // A combobox (the field keeps the focus) controlling a listbox of options; the active option is announced through
  // aria-activedescendant. Options are not links: Enter or a click opens the result (ARIA APG, combobox with listbox).
  return (
    <div className="palette-wrap" role="dialog" aria-modal="true" aria-label={t('nav.search')} onClick={onClose} onKeyDown={(e) => (e.key === 'Escape' ? onClose() : cycleTab(e, e.currentTarget))}>{/* Escape from a result too, not only the field */}
      <div className="palette" ref={box} onClick={(e) => e.stopPropagation()}>
        <div className="palette-in">
          <Icon name="search" />
          <input
            ref={inp}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t('pal.placeholder')}
            role="combobox"
            aria-expanded={hits.length > 0}
            aria-controls="pal-list"
            aria-autocomplete="list"
            aria-activedescendant={hits[sel] ? `pal-opt-${sel}` : undefined}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') (e.preventDefault(), setSel((s) => Math.min(s + 1, hits.length - 1)))
              else if (e.key === 'ArrowUp') (e.preventDefault(), setSel((s) => Math.max(s - 1, 0)))
              else if (e.key === 'Home' && e.ctrlKey) (e.preventDefault(), setSel(0))
              else if (e.key === 'End' && e.ctrlKey) (e.preventDefault(), setSel(Math.max(0, hits.length - 1)))
              else if (e.key === 'Enter' && hits[sel]) (e.preventDefault(), open(hits[sel]))
            }}
            aria-label={t('nav.search')}
            data-testid="palette-input"
          />
          <Kbd>Esc</Kbd>
          <button type="button" className="pal-cancel" onClick={onClose} data-testid="palette-cancel">{t('pal.cancel')}</button>
        </div>
        <ul className="palette-list" role="listbox" id="pal-list" aria-label={t('nav.search')} ref={list}>
          {hits.map((h, i) => (
            <li key={h.href + h.title} id={`pal-opt-${i}`} role="option" aria-selected={i === sel} className={i === sel ? 'on' : ''} onMouseEnter={() => setSel(i)} onClick={() => open(h)} data-href={h.href}>
              <Icon name={h.icon} size={16} />
              <span className="ph-main">
                <span className={h.kind === t('pal.command') ? 'mono' : ''}>{h.title}</span>
                {h.sub && <small>{h.sub}</small>}
              </span>
              <span className="ph-kind">{h.kind}</span>
            </li>
          ))}
        </ul>
        {hits.length === 0 && <p className="muted pad" role="status">{t('pal.none')}</p>}
      </div>
    </div>
  )
}
