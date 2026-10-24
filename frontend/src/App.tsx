import { Suspense, useEffect } from 'react'
import { AccountSyncProvider } from './components/AccountSync'
import { lazyPage, PageBoundary } from './components/PageBoundary'
import { Shell } from './components/Shell'
import { Callout, NotFound, PageSkeleton } from './components/ui'
import { useApp } from './lib/app'
import type { Curriculum } from './lib/data'
import { DIAGRAMS } from './lib/diagrams'
import { focusHeading } from './lib/focus'
import { anchorTarget, lastNav, useLocation } from './lib/router'
import { resolve, type Ref } from './lib/urls'
import { t } from './lib/i18n'
import Home from './pages/Home'

const About = lazyPage(() => import('./pages/About'))
const Commands = lazyPage(() => import('./pages/Commands'))
const Connections = lazyPage(() => import('./pages/Connections'))
const Course = lazyPage(() => import('./pages/Course'))
const Paths = lazyPage(() => import('./pages/Course'), (m) => m.Paths)
const Diagnostic = lazyPage(() => import('./pages/Diagnostic'))
const Explorer = lazyPage(() => import('./pages/Explorer'))
const Handbook = lazyPage(() => import('./pages/Handbook'))
const CasePage = lazyPage(() => import('./pages/Handbook'), (m) => m.CasePage)
const RunbookPage = lazyPage(() => import('./pages/Handbook'), (m) => m.RunbookPage)
const LabPage = lazyPage(() => import('./pages/Lab'))
const KnowledgeMap = lazyPage(() => import('./pages/KnowledgeMap'))
const Setup = lazyPage(() => import('./pages/Setup'))
const Lesson = lazyPage(() => import('./pages/Lesson'))
const Challenges = lazyPage(() => import('./pages/Lists'), (m) => m.Challenges)
const Incidents = lazyPage(() => import('./pages/Lists'), (m) => m.Incidents)
const Labs = lazyPage(() => import('./pages/Lists'), (m) => m.Labs)
const Me = lazyPage(() => import('./pages/Me'))
const Review = lazyPage(() => import('./pages/Review'))
const Studio = lazyPage(() => import('./pages/Studio'))
const TerminalPage = lazyPage(() => import('./pages/Terminal'))
const Author = lazyPage(() => import('./pages/Author'))

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

  useEffect(() => {
    if (!cur || !loc.hash || lastNav.restored) return
    let id: string
    try { id = decodeURIComponent(loc.hash.slice(1)) } catch { return }
    const main = document.getElementById('main')
    if (!main) return
    // The router's immediate anchor jump may precede a lazy page. Retry when its content arrives.
    const jump = () => {
      const target = anchorTarget(id)
      if (!target || !main.contains(target)) return false
      target.scrollIntoView({ block: 'start' })
      return true
    }
    if (jump()) return
    const stop = () => {
      observer.disconnect()
      clearTimeout(timer)
      for (const event of events) window.removeEventListener(event, stop, true)
    }
    const observer = new MutationObserver(() => { if (jump()) stop() })
    const timer = window.setTimeout(stop, 4000)
    const events = ['wheel', 'touchstart', 'keydown', 'pointerdown'] as const
    observer.observe(main, { childList: true, subtree: true })
    for (const event of events) window.addEventListener(event, stop, { capture: true, passive: true })
    return stop
  }, [cur, loc.path, loc.search, loc.hash])

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
        <PageBoundary at={route}>
          <Suspense fallback={<div className="page"><PageSkeleton /></div>}>{page}</Suspense>
        </PageBoundary>
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
