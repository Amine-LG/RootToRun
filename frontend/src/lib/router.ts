// Path-based routing (History API). Every lesson, lab and incident has a real, readable URL such as
// /learn/application-operations/working-with-the-oc-cli (lib/urls.ts), so pages can be shared, bookmarked and indexed.
// The static export writes one HTML file per route, and the local server falls back to index.html for unknown paths.
// The app is served from the site root. Old addresses (/lesson/<id>, /lab/<id>, #/…) are replaced by the current one
// without a new history entry: on every navigation, on Back/Forward, and once the curriculum has loaded (relocate).
import { useSyncExternalStore } from 'react'
import { canonical } from './urls'

/** The element a `#id` on this page means. Lesson section ids come from the content and can repeat an id of the app
 *  itself (the section `root` and the app's mount point, `<div id="root">`): the match inside the main content wins. */
export function anchorTarget(id: string): HTMLElement | null {
  const all = [...document.querySelectorAll<HTMLElement>(`#${CSS.escape(id)}`)]
  const main = document.getElementById('main')
  return all.filter((el) => el !== main && main?.contains(el)).pop() || all[0] || null
}

export type Loc = { path: string; search: string; hash: string }

const subs = new Set<() => void>()
let snapshot: Loc = read()

function read(): Loc {
  return { path: location.pathname || '/', search: location.search, hash: location.hash }
}
// Scroll position per history entry. A new page starts at the top; browser Back and Forward return to where the
// learner was reading on that page (the browser's own restoration cannot, because content renders after the event).
// A position belongs to the page as it was laid out: a page whose root names its layout (`data-layout`, for example the
// home page's first-visit and returning layouts) is only restored to the same layout. The home page a learner left
// before opening their first lesson is not the page they come back to, and a position on the old one points into the
// middle of something else.
if ('scrollRestoration' in history) history.scrollRestoration = 'manual'
type Saved = { y: number; layout?: string }
// kept in sessionStorage too, so Back after a reload still returns to where the learner was reading
const POS_KEY = 'osa.scroll.positions'
const positions = new Map<string, Saved>((() => {
  try {
    const raw = JSON.parse(sessionStorage.getItem(POS_KEY) || '[]') as [string, Saved | number][]
    return raw.map(([k, v]): [string, Saved] => [k, typeof v === 'number' ? { y: v } : v]) // a bare number: saved by an earlier version
  } catch {
    return []
  }
})())
const persist = () => {
  try {
    sessionStorage.setItem(POS_KEY, JSON.stringify([...positions].slice(-100)))
  } catch {
    /* storage unavailable: positions stay in memory */
  }
}
/** The layout the page on screen declares (`<div class="page" data-layout="…">`), if any. */
const layoutOf = () => document.querySelector<HTMLElement>('#main [data-layout]')?.dataset.layout
let seq = 0
const entryKey = () => (history.state as { k?: string } | null)?.k || 'initial'
// The entry whose page is on screen. On popstate history.state already names the destination, so positions are
// saved under this key (not entryKey()), and saved synchronously before leaving: a debounced save would be lost
// when Back follows a scroll immediately.
let shownKey = entryKey()
let saveTimer = 0
const remember = () => {
  const layout = layoutOf()
  positions.set(shownKey, layout ? { y: window.scrollY, layout } : { y: window.scrollY })
  persist()
}

/** Scroll to the saved position once the new page is tall enough to have it: content may load asynchronously, so it
 *  waits up to 3 s. It gives up, leaving the page where it is (at the top), as soon as another navigation happens or
 *  the learner scrolls, types or touches the page themselves (a late jump would move what they are reading), when
 *  the page declares a different layout from the one the position was saved on, and when the page never grows tall
 *  enough: it is not the page that was left, and its bottom is not where the learner was reading. */
let generation = 0
const NEAR = 0.5 // a page that ends within half a screen of the saved position is the same page, slightly shorter
function restore(s: Saved, gen = generation, until = performance.now() + 3000) {
  requestAnimationFrame(() => {
    if (gen !== generation) return
    const layout = layoutOf()
    if (s.layout && layout && layout !== s.layout) return
    const max = document.documentElement.scrollHeight - window.innerHeight
    const waiting = performance.now() <= until
    // a page that declared its layout when the position was saved has not rendered while it does not declare one yet
    if (max >= s.y - 1 && (!s.layout || layout)) window.scrollTo({ top: s.y })
    else if (waiting) restore(s, gen, until)
    else if (max >= s.y - window.innerHeight * NEAR && (!s.layout || layout)) window.scrollTo({ top: Math.max(0, max) })
  })
}
// the learner's own scrolling cancels a restoration still waiting for content; programmatic scrolling does not
for (const ev of ['wheel', 'touchstart', 'keydown', 'pointerdown'] as const)
  window.addEventListener(ev, () => generation++, { passive: true, capture: true })

/** How the page on screen was reached: first load, a link or navigate() (push/replace), or Back/Forward (pop), and
 *  whether a saved scroll position is being restored. App reads it to decide whether focus moves to the new page. */
export let lastNav: { kind: 'load' | 'push' | 'replace' | 'pop'; restored: boolean } = { kind: 'load', restored: false }

function notify(kind: 'push' | 'replace' | 'pop', redirect = false) {
  const pop = kind === 'pop'
  const next = read()
  if (pop) {
    remember() // the page being left, at its current position
    clearTimeout(saveTimer)
    shownKey = entryKey()
  }
  if (next.path === snapshot.path && next.search === snapshot.search && next.hash === snapshot.hash) return
  const pathChanged = next.path !== snapshot.path
  snapshot = next
  // Back/Forward restores the saved position, except to an anchor entry the router did not create (go to the anchor)
  const ours = (history.state as { k?: string } | null)?.k !== undefined
  const saved = pop && (ours || !next.hash) ? positions.get(entryKey()) : undefined
  generation++ // a restoration still waiting for the previous page stops here
  // a redirect from an old address continues the navigation that reached it (a first load stays a first load)
  if (!redirect) lastNav = { kind, restored: saved !== undefined }
  subs.forEach((f) => f())
  // another page's position never lingers: a restoration that gives up leaves the page at its top
  if (saved !== undefined) (pathChanged && window.scrollTo({ top: 0 }), restore(saved))
  else if (pathChanged && !next.hash) window.scrollTo({ top: 0 })
  if (next.hash && saved === undefined) requestAnimationFrame(() => anchorTarget(decodeURIComponent(next.hash.slice(1)))?.scrollIntoView({ block: 'start' }))
}

/** Links written as "#/x" by older versions keep working. */
if (location.hash.startsWith('#/')) {
  history.replaceState(null, '', location.hash.slice(1))
  snapshot = read()
}

export function navigate(to: string, opts: { replace?: boolean } = {}) {
  to = canonical(to) // an old address goes straight to the current one
  if (to === location.pathname + location.search + location.hash) return
  if (opts.replace) history.replaceState(history.state, '', to)
  else {
    remember()
    clearTimeout(saveTimer)
    history.pushState({ k: `e${Date.now().toString(36)}${++seq}` }, '', to)
    shownKey = entryKey()
  }
  notify(opts.replace ? 'replace' : 'push')
}

/** The address on screen is an old one (/lesson/<id>…): show the current address instead, with the same query and
 *  #anchor and no new history entry. lib/app.tsx calls it once the curriculum, which knows the addresses, has loaded. */
export function relocate() {
  const here = location.pathname + location.search + location.hash
  const to = canonical(here)
  if (to === here) return
  history.replaceState(history.state, '', to)
  notify('replace', true)
}

window.addEventListener('popstate', () => {
  // an entry saved under an old address: the same entry (and its reading position), at the current address
  const here = location.pathname + location.search + location.hash
  const to = canonical(here)
  if (to !== here) history.replaceState(history.state, '', to)
  notify('pop')
})
window.addEventListener('pagehide', remember)
window.addEventListener('scroll', () => {
  clearTimeout(saveTimer)
  saveTimer = window.setTimeout(remember, 120)
}, { passive: true })

// Same-origin <a href="/..."> links navigate without a page load.
document.addEventListener('click', (e) => {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
  const a = (e.target as Element | null)?.closest?.('a')
  if (!a) return
  const href = a.getAttribute('href')
  if (href && href.startsWith('#') && href.length > 1 && !href.startsWith('#/') && !a.target) {
    // an anchor on this page: a history entry of our own, so that popstate never mistakes it for Back and restores
    // another page's position (and the same anchor clicked again still scrolls)
    e.preventDefault()
    const to = location.pathname + location.search + href
    if (to === location.pathname + location.search + location.hash) anchorTarget(decodeURIComponent(href.slice(1)))?.scrollIntoView({ block: 'start' })
    else navigate(to)
    return
  }
  if (!href || !href.startsWith('/') || href.startsWith('//') || a.target || a.hasAttribute('download')) return
  if (/^\/(api|data|assets)\//.test(href) || /\.(txt|json|xml)$/.test(href)) return // files, not pages
  e.preventDefault()
  navigate(href)
})

export function useLocation(): Loc {
  return useSyncExternalStore(
    (f) => {
      subs.add(f)
      return () => subs.delete(f)
    },
    () => snapshot,
  )
}
