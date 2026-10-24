// Page code (and the models' code) is loaded when it is first needed, from files under /assets/ whose names contain
// a hash of their content. Two things make such a load fail:
//   - a new deployment: a tab opened before it asks for names that no longer exist (the production nginx answers
//     404 with an HTML page), and only a reload fetches the new index with the new names;
//   - the network: offline, or the request dropped; asking again once it is back is enough.
// Either way the import rejects. It rejects with a ChunkError, so the page's recovery (components/PageBoundary.tsx)
// can tell it from a mistake in a page, and ask the server which of the two it was (probe) before reloading.
//
// Chromium remembers a failed import, and every file it preloaded with it, for the life of the document: a later
// import() fails at once without asking the server. A retry asks for the failed file under a new address, but a
// shared file that failed with it (a lesson's code statically imports the Studio and Diagnostic chunks) keeps
// failing: then only a reload recovers, which is why Reload stays the panel's first button.
import { progressSaved } from './progress'

export class ChunkError extends Error {
  /** attempt: 0 for the first load of this code, more for a retry; file: the site's file that failed, if known. */
  constructor(readonly reason: unknown, readonly attempt = 0, readonly file: string | null = null) {
    super(`The site's code could not be loaded (${reason instanceof Error ? reason.message : String(reason)})`)
    this.name = 'ChunkError'
  }
}

/** The site's own file that a failed load names: Chromium and Firefox name the script, Vite names the stylesheet
 *  (Safari names neither: a later attempt then repeats the same import). */
export function failedFile(e: unknown, kind: 'js' | 'css', here = location.href): string | null {
  const text = e instanceof Error ? e.message : String(e)
  const m = kind === 'css' ? text.match(/Unable to preload CSS for (\S+\.css)/) : text.match(/(\S*\/assets\/[^\s?#'"]+\.js)/)
  if (!m) return null
  try {
    const u = new URL(m[1], here)
    return u.origin === new URL(here).origin && u.pathname.startsWith('/assets/') ? u.pathname : null
  } catch {
    return null
  }
}

// WebKit keeps a <link rel="modulepreload"> that failed (Vite adds one for a page's code and for each file it
// imports) and answers every later load of that address with the failure, even after a reload, without asking the
// server: Try again and Reload both failed until the browser dropped it (seen in Playwright's WebKit, the engine of
// every iPhone browser). Fetching the address again with cache: 'reload' replaces what it kept, so the site's files
// whose preload failed are noted here and fetched again before another attempt or a reload.
const failedPreloads = new Set<string>()
if (typeof document !== 'undefined') {
  document.addEventListener('error', (e) => {
    const link = e.target
    if (!(link instanceof HTMLLinkElement) || !/\b(modulepreload|preload|stylesheet)\b/.test(link.rel)) return
    try {
      if (new URL(link.href).pathname.startsWith('/assets/')) failedPreloads.add(link.href)
    } catch {
      /* not an address */
    }
  }, true) // error events do not bubble: caught on the way down
}

/** Fetch the site's files whose preload failed again, past every cache (see above); a file that answers is
 *  forgotten, one that does not stays noted for the next attempt. Gives up after timeoutMs. */
export async function refreshFailed(timeoutMs = 4000): Promise<void> {
  if (!failedPreloads.size) return
  const stop = new AbortController()
  const timer = setTimeout(() => stop.abort(), timeoutMs)
  await Promise.all([...failedPreloads].map(async (href) => {
    try {
      if ((await fetch(href, { cache: 'reload', credentials: 'same-origin', signal: stop.signal })).ok) failedPreloads.delete(href)
    } catch {
      /* still failing */
    }
  }))
  clearTimeout(timer)
}

/** Reload the address on screen, after refreshing what the browser may remember as failed. */
export async function reloadPage(): Promise<void> {
  await refreshFailed()
  location.reload()
}

function stylesheet(href: string, attempt: number, file: string): Promise<void> {
  return new Promise((done, fail) => {
    const link = Object.assign(document.createElement('link'), { rel: 'stylesheet', href })
    link.addEventListener('load', () => done())
    link.addEventListener('error', () => fail(new ChunkError(new Error(`Unable to load ${href}`), attempt, file)))
    document.head.appendChild(link)
  })
}

/** load(), made retryable; every failure rejects with a ChunkError. It is always attempted, even when the browser
 *  says it is offline (some report that wrongly). Vite never adds a stylesheet a second time, and Chromium answers a
 *  repeated import() from its record of the failure: so a later attempt asks for the failed file under a new
 *  address (?retry=n). */
export function retrying<M>(load: () => Promise<M>): () => Promise<M> {
  let attempt = 0
  let css: string | null = null
  return async () => {
    const n = attempt++
    try {
      if (n > 0) await refreshFailed()
      if (css) {
        await stylesheet(`${css}?retry=${n}`, n, css)
        css = null
      }
      return await load()
    } catch (e) {
      if (e instanceof ChunkError) throw e
      css = failedFile(e, 'css') || css
      const js = failedFile(e, 'js')
      if (!js || n === 0) throw new ChunkError(e, n, js || css)
      try {
        return (await import(/* @vite-ignore */ `${js}?retry=${n}`)) as M
      } catch (again) {
        throw new ChunkError(again, n, js)
      }
    }
  }
}

/** The entry script named by an index page's HTML (the first module script with a src), as a path. */
export function entryIn(html: string, base: string): string | null {
  for (const tag of html.match(/<script\b[^>]*>/gi) || []) {
    if (!/\btype\s*=\s*["']?module\b/i.test(tag)) continue
    const src = tag.match(/\bsrc\s*=\s*["']([^"']+)["']/i)
    if (src) return new URL(src[1], base).pathname
  }
  return null
}

/** The entry script this page is running. */
function runningEntry(): string | null {
  const s = document.querySelector<HTMLScriptElement>('script[type="module"][src]')
  return s ? new URL(s.src, location.href).pathname : null
}

/** What the server says about the code that failed to load, asked without any cache:
 *  'replaced': a new deployment: the failed file is gone (404, or an HTML page in its place), or, when the browser
 *     does not name the file (Safari), the site's index now names another entry script than the one this page runs;
 *  'served': the same deployment: the file is there, or the index names the same entry script: the network failed,
 *     or the browser remembers an earlier failure;
 *  'answers': the site answers but says neither (an index without a module script);
 *  'unreachable': no answer (no internet behind the Wi-Fi, a captive portal's error, a timeout): a reload would land
 *     on the browser's error page. */
export type Probe = 'replaced' | 'served' | 'answers' | 'unreachable'
export async function probe(file: string | null, timeoutMs = 5000): Promise<Probe> {
  const stop = new AbortController()
  const timer = setTimeout(() => stop.abort(), timeoutMs)
  const ask = { cache: 'no-store', credentials: 'same-origin', redirect: 'follow', signal: stop.signal } as const
  try {
    if (file) {
      const r = await fetch(file, { ...ask, method: 'HEAD' })
      const html = /text\/html/i.test(r.headers.get('content-type') || '')
      if (r.status === 404 || r.status === 410 || (r.ok && html)) return 'replaced'
      return r.ok ? 'served' : 'unreachable'
    }
    const r = await fetch('/', ask)
    if (!r.ok) return 'unreachable'
    const now = entryIn(await r.text(), location.href)
    const mine = runningEntry()
    if (!now || !mine) return 'answers'
    return now === mine ? 'served' : 'replaced'
  } catch {
    return 'unreachable'
  } finally {
    clearTimeout(timer)
  }
}

/** Whether a reload helps after `e`, given the server's answer: a new deployment (or a site that answers without
 *  saying), or the same deployment yet a retry failed again (the browser remembers the failure). Never when the server
 *  did not answer, and never for a first failure on the same deployment: Try again is enough. */
export function reloadHelps(e: ChunkError, found: Probe): boolean {
  return found === 'replaced' || found === 'answers' || (found === 'served' && e.attempt > 0)
}

// One automatic reload per address per minute, recorded in sessionStorage: if the new deployment does not have the
// file either, the next failure shows the recovery panel instead of reloading again. The address is the path without
// a trailing slash: a host may answer /a/b with a redirect to /a/b/ (the page's index.html), the same page.
const MARK = 'osa.reloadedFor'
const WINDOW_MS = 60_000
const here = () => location.pathname.replace(/\/+$/, '') || '/'

/** An automatic reload is allowed and cannot loop: the browser does not say it is offline, progress is being saved (a
 *  reload would lose what this tab holds), sessionStorage works (the attempt can be remembered) and no reload was
 *  made for this address in the last minute. Whether it would help is the server's answer (probe, reloadHelps). */
export function mayReload(): boolean {
  if (!navigator.onLine || !progressSaved()) return false
  try {
    const m = JSON.parse(sessionStorage.getItem(MARK) || 'null') as { path?: string; at?: number } | null
    return !(m && m.path === here() && typeof m.at === 'number' && Math.abs(Date.now() - m.at) < WINDOW_MS)
  } catch {
    return false
  }
}

/** Reload the address on screen (path, query and #anchor) to fetch the new index and file names. Progress is written
 *  to localStorage as it changes (lib/progress.ts), and the router saves reading positions on pagehide, so nothing is
 *  pending. False, without reloading, when the attempt cannot be recorded. */
export async function reloadOnce(stillWanted: () => boolean = () => true): Promise<boolean> {
  const path = here()
  try {
    const mark = JSON.stringify({ path, at: Date.now() })
    sessionStorage.setItem(MARK, mark)
    if (sessionStorage.getItem(MARK) !== mark) return false
  } catch {
    return false
  }
  await refreshFailed()
  // the refresh can take seconds: a learner who has moved on meanwhile must not have the page they moved to reloaded
  if (!stillWanted() || here() !== path) return false
  location.reload()
  return true
}
