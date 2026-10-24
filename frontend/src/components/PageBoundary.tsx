import { Component, createElement, lazy, useEffect, useState, type ComponentType, type ErrorInfo, type ReactNode } from 'react'
import { ChunkError, mayReload, probe, reloadHelps, reloadOnce, reloadPage, retrying } from '../lib/chunks'
import { focusHeading } from '../lib/focus'
import { t } from '../lib/i18n'
import { useSaveFailed } from '../lib/progress'
import { Icon, PageSkeleton } from './ui'

// Every page area shown afresh (a navigation, Try again) is a new generation: a page whose code failed to load asks
// for it again then. React.lazy keeps a failed import for good, so that page gets a new lazy component; a page whose
// code loaded is untouched. Within one generation a failure stays put, so React re-rendering the failed page does not
// start another request.
let generation = 0

/** A page component whose code is loaded when it is first shown, like React.lazy, and loaded again after a failure
 *  when the page is shown again. `pick` chooses the module's export (default: its default export). */
export function lazyPage<M extends { default: ComponentType<never> }>(load: () => Promise<M>): M['default']
export function lazyPage<M, C extends ComponentType<never>>(load: () => Promise<M>, pick: (m: M) => C): C
export function lazyPage(load: () => Promise<unknown>, pick = (m: unknown) => (m as { default: ComponentType }).default) {
  const again = retrying(load)
  let failedIn: number | null = null // the generation in which the current lazy component failed
  const make = () => lazy(() => again().then((m) => ({ default: pick(m) }), (e) => {
    failedIn = generation
    throw e
  }))
  let Lazy = make()
  return function Page(props: object) {
    if (failedIn !== null && failedIn !== generation) {
      failedIn = null
      Lazy = make()
    }
    return createElement(Lazy, props)
  }
}

// reloading: a chunk failed and an automatic reload is allowed: the server is asked whether it would help (the page
// area shows the skeleton meanwhile), then the page reloads or the panel shows.
type State = { failure: { error: unknown } | null; reloading: boolean }
const RELOAD_GRACE_MS = 8000 // a reload that has not replaced the page by then did not happen: show the panel

/** The page area's safety net (App.tsx). A page whose code cannot load, or that fails while rendering, is replaced by
 *  a way to recover, and the shell around it (header, tab bar, menu) keeps working. Code that cannot load after a
 *  deployment is fetched by one automatic reload, made only when it is allowed and the server answers that it would
 *  help (lib/chunks.ts); otherwise the panel offers Reload and Try again. `at` is the address: a navigation clears
 *  the failure. */
export class PageBoundary extends Component<{ at: string; children: ReactNode }, State> {
  state: State = { failure: null, reloading: false }
  private gone = false
  private timer = 0

  constructor(props: { at: string; children: ReactNode }) {
    super(props)
    generation++ // a new page area (App keys it by address): a page that failed before is asked for again
  }

  static getDerivedStateFromError(error: unknown): State {
    return { failure: { error }, reloading: error instanceof ChunkError && mayReload() }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    const head = String(error)
    const stack = (error instanceof Error && error.stack) || ''
    console.error(`The page area caught: ${stack.startsWith(head) ? stack : `${head}\n${stack}`}${info.componentStack || ''}`)
    if (this.state.reloading && error instanceof ChunkError) void this.reloadIfHelps(error)
  }

  componentWillUnmount() {
    this.gone = true
    clearTimeout(this.timer)
  }

  private async reloadIfHelps(error: ChunkError) {
    const found = await probe(error.file)
    if (this.gone || this.state.failure?.error !== error) return // navigated away, or tried again, meanwhile
    if (reloadHelps(error, found) && (await reloadOnce(() => !this.gone && this.state.failure?.error === error))) {
      this.timer = window.setTimeout(() => this.setState({ reloading: false }), RELOAD_GRACE_MS)
      return
    }
    this.setState({ reloading: false })
  }

  componentDidUpdate(prev: { at: string }) {
    if (prev.at !== this.props.at && this.state.failure) this.retry()
  }

  retry = () => {
    generation++
    clearTimeout(this.timer)
    // the button that was clicked goes away with the panel: focus moves to the page's heading once it renders
    this.setState({ failure: null, reloading: false }, () => void focusHeading())
  }

  render() {
    const { failure, reloading } = this.state
    if (!failure) return this.props.children
    if (reloading) return <div className="page"><PageSkeleton /></div>
    return <PageError chunk={failure.error instanceof ChunkError} onRetry={this.retry} />
  }
}

/** navigator.onLine, kept up to date: only for what a message says, never to decide whether to ask the network. */
export function useOnline(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine)
  useEffect(() => {
    const update = () => setOnline(navigator.onLine)
    window.addEventListener('online', update)
    window.addEventListener('offline', update)
    return () => {
      window.removeEventListener('online', update)
      window.removeEventListener('offline', update)
    }
  }, [])
  return online
}

/** What the learner sees instead of the page: what happened, that their progress is kept, and how to go on. */
function PageError({ chunk, onRetry }: { chunk: boolean; onRetry: () => void }) {
  const online = useOnline()
  const unsaved = useSaveFailed()
  return (
    <div className="page page-error" data-testid="page-error" data-kind={chunk ? 'chunk' : 'render'}>
      <h1>{t(chunk ? 'app.pageLoadFailed' : 'app.pageError')}</h1>
      <p>{t(!chunk ? 'app.pageErrorText' : online ? 'app.pageLoadFailedText' : 'app.pageOffline')}</p>
      <p>{t(unsaved ? 'app.pageProgressAtRisk' : 'app.pageProgressKept')}</p>
      <p className="row">
        <button type="button" className="btn primary" onClick={() => void reloadPage()} data-testid="page-reload">
          <Icon name="refresh" size={16} /> {t('app.pageReload')}
        </button>
        {chunk ? (
          <button type="button" className="btn" onClick={onRetry} data-testid="page-retry">
            {t('app.pageRetry')}
          </button>
        ) : (
          <a href="/" data-testid="page-home">{t('app.pageHome')}</a>
        )}
      </p>
    </div>
  )
}
