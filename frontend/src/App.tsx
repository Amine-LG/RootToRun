import { lazy, Suspense, useEffect } from 'react'
import { AccountSyncProvider } from './components/AccountSync'
import { Shell } from './components/Shell'
import { Callout, NotFound, PageSkeleton } from './components/ui'
import { useApp } from './lib/app'
import type { Curriculum } from './lib/data'
import { DIAGRAMS } from './lib/diagrams'
import { lastNav, useLocation } from './lib/router'
import { resolve, type Ref } from './lib/urls'
import { t } from './lib/i18n'
import About from './pages/About'
import Commands from './pages/Commands'
import Connections from './pages/Connections'
import Course, { Paths } from './pages/Course'
import Diagnostic from './pages/Diagnostic'
import Explorer from './pages/Explorer'
import Handbook, { CasePage, RunbookPage } from './pages/Handbook'
import Home from './pages/Home'
import LabPage from './pages/Lab'
import KnowledgeMap from './pages/KnowledgeMap'
import Setup from './pages/Setup'
import Lesson from './pages/Lesson'
import { Challenges, Incidents, Labs } from './pages/Lists'
import Me from './pages/Me'
import Review from './pages/Review'
import Studio from './pages/Studio'
import TerminalPage from './pages/Terminal'

const Author = lazy(() => import('./pages/Author'))

export default function App() {
  const loc = useLocation()
  const { cur, meta, error } = useApp()
  const route = loc.path.replace(/\/+$/, '') || '/'
  const query = new URLSearchParams(loc.search)
  const [, a = '', b = '', c = ''] = route.split('/')
  const hit = cur ? resolve(route) : null // the track, lesson, lab or diagnostic at this address (lib/urls.ts)
  const missing = !!cur && isMissing(cur, a, b, hit)
  const name = cur && meta ? (missing ? t('app.notFound') : pageName(cur, a, b, c, meta.mode === 'cluster', hit)) : undefined
  useEffect(() => {
    if (name !== undefined) document.title = name ? `${name} · ${t('app.name')}` : t('app.name') // until loaded: the HTML's title
  }, [name])
  useEffect(() => {
    // A new page reached by a link: keyboard and screen-reader users start at its heading. Not on first load, not on a
    // jump to an anchor (#id), not when Back/Forward restores a reading position.
    if (lastNav.kind === 'load' || loc.hash) return
    // Back/Forward to a saved reading position: focus the page region without moving it, so focus is not lost
    if (lastNav.restored) return void document.getElementById('main')?.focus({ preventScroll: true })
    return focusHeading()
  }, [loc.path]) // eslint-disable-line react-hooks/exhaustive-deps

  let page
  if (error && !cur) page = <div className="page"><Callout tone="bad" title={t('app.loadError')}>{error}</Callout></div>
  else if (!cur || !meta) page = <div className="page"><PageSkeleton /></div>
  else if (a === 'author') page = meta.authoring && meta.mode !== 'static' ? <Suspense fallback={<PageSkeleton />}><Author /></Suspense> : <div className="page"><h1>{t('author.off')}</h1><p>{t('author.offHelp')}</p></div>
  else if (missing) page = <NotFound />
  else if (a === '') page = <Home />
  else if (a === 'learn') page = !hit ? <Paths /> : hit.kind === 'lesson' ? <Lesson id={hit.id} /> : <Course track={hit.id} />
  else if (a === 'diagnostic') page = <Diagnostic track={hit!.id} />
  else if (hit?.kind === 'lab') page = <LabPage id={hit.id} />
  else if (a === 'labs') page = <Labs />
  else if (a === 'incidents') page = <Incidents />
  else if (a === 'challenges') page = <Challenges />
  else if (a === 'review') page = <Review />
  else if (a === 'handbook') page = <Handbook />
  else if (a === 'runbook') page = <RunbookPage id={b} />
  else if (a === 'case') page = <CasePage id={b} />
  else if (a === 'terminal') page = <TerminalPage />
  else if (a === 'commands') page = <Commands query={query} />
  else if (a === 'map') page = <KnowledgeMap query={query} />
  else if (a === 'setup') page = <Setup />
  else if (a === 'studio') page = <Studio view={c ? `${b}/${c}` : b || 'index'} />
  else if (a === 'me') page = <Me />
  else if (a === 'about') page = <About />
  else if (a === 'explorer' && meta.mode === 'cluster') page = <Explorer kind={query.get('kind') || undefined} ns={query.get('ns') || undefined} name={query.get('name') || undefined} />
  else if (a === 'connections' && meta.mode === 'cluster') page = <Connections />
  else page = <NotFound />

  return (
    <AccountSyncProvider>
    <Shell route={route} key={meta?.mode}>
      <div className="page-enter" key={a === 'studio' ? `${a}/${b}` : route}>
        {page}
      </div>
    </Shell>
    </AccountSyncProvider>
  )
}

/** A lesson, lab, path, runbook or case that the curriculum does not have. Old addresses (/lesson/<id>, /lab/<id>,
 *  /course) are replaced by the current one before the curriculum renders (lib/router.ts relocate): one
 *  still on screen names nothing. */
function isMissing(cur: Curriculum, a: string, b: string, hit: Ref | null): boolean {
  if (a === 'lesson' || a === 'lab' || a === 'course') return true
  if (a === 'learn') return !!b && !hit
  if (a === 'labs' || a === 'incidents' || a === 'challenges') return !!b && hit?.kind !== 'lab'
  if (a === 'diagnostic') return hit?.kind !== 'diagnostic'
  if (a === 'runbook') return !cur.runbooks.some((r) => r.id === b)
  if (a === 'case') return !cur.cases.some((x) => x.id === b)
  return false
}

/** The page's name for document.title ('' on the home page: the site name alone; null: not a page). The same names as
 *  the static export (scripts/export_static.py), so a direct load and an in-app navigation agree. */
function pageName(cur: Curriculum, a: string, b: string, c: string, cluster: boolean, hit: Ref | null): string | null {
  const named: Record<string, string> = {
    labs: t('title.labs'), incidents: t('title.incidents'), challenges: t('title.challenges'), review: t('title.review'), handbook: t('title.handbook'), terminal: t('title.terminal'),
    commands: t('title.commands'), map: t('title.map'), me: t('title.me'), about: t('title.about'), author: t('title.author'), setup: t('setup.title'),
  }
  if (a === '') return ''
  if (hit?.kind === 'lesson') return cur.lessons[hit.id].title
  if (hit?.kind === 'lab') return cur.labs[hit.id].title
  if (hit?.kind === 'track') return cur.tracks.find((x) => x.id === hit.id)!.title
  if (a in named) return named[a]
  if (a === 'learn') return t('title.learn')
  if (a === 'runbook') return cur.runbooks.find((r) => r.id === b)!.title
  if (a === 'case') return cur.cases.find((x) => x.id === b)!.title
  if (a === 'diagnostic') return cur.diagnostics?.[hit!.id]?.title || t('title.diagnostic')
  // a model and a diagram may share an id (rbac): only diagram addresses take a diagram's title
  if (a === 'studio') return !b ? t('title.studio') : b === 'model' ? t('title.explore') : DIAGRAMS.find((d) => d.id === (c || b))?.title || t('title.explore')
  if (cluster && a === 'explorer') return t('title.explorer')
  if (cluster && a === 'connections') return t('title.connections')
  return t('app.notFound')
}

/** Focus the new page's h1 once it renders (pages load their content asynchronously), without scrolling. Gives up if
 *  focus has already moved into the page, or after a few seconds. Returns the cleanup. */
function focusHeading(): () => void {
  const main = document.getElementById('main')
  if (!main) return () => {}
  const attempt = () => {
    const f = document.activeElement
    if (f && f !== main && main.contains(f)) return true // the page placed focus itself (a step, a field)
    const h = main.querySelector<HTMLElement>('h1')
    if (!h) return false
    if (!h.hasAttribute('tabindex')) h.tabIndex = -1
    h.focus({ preventScroll: true })
    return true
  }
  if (attempt()) return () => {}
  const mo = new MutationObserver(() => attempt() && stop())
  const timer = window.setTimeout(() => stop(), 4000)
  const stop = () => (mo.disconnect(), clearTimeout(timer))
  mo.observe(main, { childList: true, subtree: true })
  return stop
}
