// One behaviour for every overlay (the phone menu, search, the Report and Edit sheets and popovers, the lesson's
// sheets): it closes when the learner chooses something in it, taps outside it, presses Escape or the phone's Back
// button, or presses its close button; one overlay is open at a time; a modal one holds the page still behind it and
// gives the focus back to what opened it. Each overlay declares what applies to it (useOverlay below).
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from 'react'
import { navigate } from './router'

const OPENED = 'rtr:overlay-open'
let locks = 0

/** Hold the page still while a modal overlay is open (a phone keeps scrolling the page under a sheet otherwise):
 *  `overflow: hidden` on the page, and, for the iOS Safari versions that scroll the page behind a sheet regardless, a
 *  finger drag that starts outside the open overlays is cancelled (one inside them scrolls them). The page itself does
 *  not move: its scroll position stays what it is (scrollY), so everything that measures it (the saved reading
 *  position, the reading progress, the page's own scroll-driven parts) goes on seeing where the reader is. */
const lockedBy = new Set<RefObject<HTMLElement | null>>()
let touchAt = { x: 0, y: 0 }
const touchStart = (e: TouchEvent) => (touchAt = { x: e.touches[0]?.clientX ?? 0, y: e.touches[0]?.clientY ?? 0 })
/** Can something from `t` up to `root` scroll further in the drag's direction (dx, dy: the finger's movement)? */
function canScroll(t: Element | null, root: HTMLElement, dx: number, dy: number): boolean {
  const vertical = Math.abs(dy) >= Math.abs(dx)
  for (let el = t; el; el = el === root ? null : el.parentElement) {
    const s = getComputedStyle(el)
    if (vertical && /(auto|scroll)/.test(s.overflowY) && el.scrollHeight > el.clientHeight + 1) {
      // a finger moving down scrolls towards the top
      if (dy > 0 ? el.scrollTop > 0 : el.scrollTop + el.clientHeight < el.scrollHeight - 1) return true
    }
    if (!vertical && /(auto|scroll)/.test(s.overflowX) && el.scrollWidth > el.clientWidth + 1) {
      if (dx > 0 ? el.scrollLeft > 0 : el.scrollLeft + el.clientWidth < el.scrollWidth - 1) return true
    }
  }
  return false
}
// a drag outside the open overlays is cancelled, and so is one inside them that nothing there can take (at a scroll
// end, or on content that does not scroll): iOS Safari would hand it on to the page (scroll chaining)
const holdTouch = (e: TouchEvent) => {
  if (!e.cancelable || e.touches.length > 1) return // two fingers: a pinch zooms
  // zoomed in with a pinch: a one-finger drag pans the zoomed view (not the page's own scrolling), never held
  if ((window.visualViewport?.scale ?? 1) > 1.01) return
  const t = e.target as Element | null
  const root = [...lockedBy].map((r) => r.current).find((r) => r && t && r.contains(t))
  if (root && t?.closest('input, textarea, select, [contenteditable]')) return // moving the caret, selecting text
  // this movement's direction: from the finger's previous position (a drag can reverse)
  const x = e.touches[0]?.clientX ?? 0, y = e.touches[0]?.clientY ?? 0
  const dx = x - touchAt.x, dy = y - touchAt.y
  touchAt = { x, y }
  if (!dx && !dy) return
  if (!root || !canScroll(t, root, dx, dy)) e.preventDefault()
}
function lockScroll(root: RefObject<HTMLElement | null>): () => void {
  lockedBy.add(root)
  if (locks++ === 0) {
    const gap = window.innerWidth - document.documentElement.clientWidth // a desktop scrollbar: no layout jump
    document.documentElement.classList.add('overlay-lock')
    document.documentElement.style.setProperty('--scrollbar-gap', `${gap}px`)
    document.addEventListener('touchstart', touchStart, { passive: true })
    document.addEventListener('touchmove', holdTouch, { passive: false })
  }
  return () => {
    lockedBy.delete(root)
    if (--locks === 0) {
      document.documentElement.classList.remove('overlay-lock')
      document.documentElement.style.removeProperty('--scrollbar-gap')
      document.removeEventListener('touchstart', touchStart)
      document.removeEventListener('touchmove', holdTouch)
    }
  }
}

/** Where the reader is on the page (also while an overlay holds it still). */
export const readingY = () => window.scrollY

/** An internal page link the router handles (lib/router.ts): same rules. */
function internalHref(a: HTMLAnchorElement): string | null {
  const href = a.getAttribute('href')
  if (!href || a.target || a.hasAttribute('download')) return null
  if (href.startsWith('#') && href.length > 1 && !href.startsWith('#/')) return location.pathname + location.search + href
  if (!href.startsWith('/') || href.startsWith('//')) return null
  if (/^\/(api|data|assets)\//.test(href) || /\.(txt|json|xml)$/.test(href)) return null
  return href
}

// The overlays' history entry. At most one exists, shared: only one overlay is open at a time, so opening another hands
// it over (replaceState) instead of piling up entries. Closing an overlay takes it back with history.back(), which
// answers later (popstate): until it has, whatever needs the history settled (a new entry, a navigation) waits.
let seq = 0
let owner: { token: string; onPop: () => void } | null = null
let backs = 0 // our history.back() calls not yet answered
const queue: (() => void)[] = []
const live = new Set<string>() // overlays open now (an entry taken for one that already closed would be orphaned)
const marker = () => (history.state as { overlay?: string } | null)?.overlay
const settled = (f: () => void) => (backs ? queue.push(f) : f())
const stepBack = () => (backs++, history.back())
if (typeof window !== 'undefined') {
  window.addEventListener('popstate', () => {
    if (backs > 0) {
      if (--backs === 0) queue.splice(0).forEach((f) => f())
      return
    }
    if (owner && marker() !== owner.token) {
      // the learner's Back: the overlay that held the entry closes
      const o = owner
      owner = null
      o.onPop()
    } else if (marker() && !owner) stepBack() // an entry nobody holds (Forward onto a closed overlay's): step over it
  })
  // a reload with an overlay open keeps its entry but not the overlay: step back over it at once
  if (marker()) stepBack()
}
function takeEntry(token: string, onPop: () => void) {
  settled(() => {
    if (!live.has(token)) return
    if (marker()) history.replaceState({ ...(history.state || {}), overlay: token }, '') // handed over
    else history.pushState({ ...(history.state || {}), overlay: token }, '')
    owner = { token, onPop }
  })
}
function releaseEntry(token: string, then: (() => void) | null) {
  live.delete(token)
  if (owner?.token === token) {
    owner = null
    if (marker() === token) {
      if (then) queue.push(then)
      stepBack()
      return
    }
  }
  if (then) settled(then)
}

/** Keep Tab inside `box` (a modal layer): visible controls only. */
export function trapTab(e: KeyboardEvent | ReactKeyboardEvent, box: HTMLElement, wrapTo?: HTMLElement | null) {
  if (e.key !== 'Tab') return
  const f = [...box.querySelectorAll<HTMLElement>('a[href], button:not(:disabled), input, select, textarea, summary, [tabindex="0"]')].filter((el) => el.getClientRects().length > 0)
  if (!f.length) return
  const [first, last] = [f[0], f[f.length - 1]]
  const at = document.activeElement
  if (e.shiftKey && (at === first || at === box)) (e.preventDefault(), last.focus())
  else if (!e.shiftKey && (at === last || !box.contains(at))) (e.preventDefault(), (wrapTo || first).focus())
}

export type OverlayOptions = {
  /** a name, unique among the overlays open at once */
  id: string
  /** the overlay's own box: a tap outside it closes it (when `outside`) */
  root: RefObject<HTMLElement | null>
  /** what opened it (a tap on it toggles, it is not "outside"; the focus returns to it) */
  opener?: RefObject<HTMLElement | null>
  modal?: boolean // holds the page still; Back closes it
  outside?: boolean // default true
  closeOnPick?: boolean // a link chosen inside closes it (default true)
  back?: boolean // the phone's Back closes it (default: modal)
  focusTrap?: boolean // moves the focus into it, keeps Tab inside and makes the page behind inert (its own otherwise)
}

/** Wire an overlay's dismissal. `open` is its state, `close` closes it (and only that). Returns `closeAndGo(next)`:
 *  close, then open a page (a href: choices that are not links, such as search results) or do something else (a
 *  function, such as opening another overlay), once the overlay's own history entry is gone. */
export function useOverlay(open: boolean, close: () => void, o: OverlayOptions): (next: string | (() => void)) => void {
  const closeRef = useRef(close)
  closeRef.current = close
  const goRef = useRef<((next: string | (() => void)) => void) | null>(null)
  const { id, root, opener, modal = false, outside = true, closeOnPick = true, focusTrap = false } = o
  const back = o.back ?? modal
  useEffect(() => {
    if (!open) return
    const done = () => closeRef.current()
    const token = `${id}:${++seq}`
    live.add(token)
    let pendingNav: string | (() => void) | null = null
    goRef.current = (next) => ((pendingNav = next), done())
    // one at a time: opening another overlay closes this one
    window.dispatchEvent(new CustomEvent(OPENED, { detail: id }))
    const other = (e: Event) => (e as CustomEvent).detail !== id && done()
    window.addEventListener(OPENED, other)
    const key = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      e.preventDefault()
      done()
      opener?.current?.focus({ preventScroll: true })
    }
    document.addEventListener('keydown', key)
    // outside: a popover closes as soon as the pointer goes down elsewhere, and that click does what it does there; a
    // modal overlay closes on the whole tap over its dimmed page, which the tap ends on (removed at pointerdown, the
    // tap's click would land on whatever lay under it: a ghost click)
    const isOut = (t: Node) => outside && !root.current?.contains(t) && !opener?.current?.contains(t)
    const away = (e: Event) => {
      if (!isOut(e.target as Node)) return
      if (modal) (e.preventDefault(), e.stopPropagation())
      done()
    }
    document.addEventListener(modal ? 'click' : 'pointerdown', away, true)
    // a link chosen inside: close; an internal one first takes back the overlay's own history entry, then navigates,
    // so Back afterwards returns to the page the learner came from (not to the same page again)
    const pick = (e: MouseEvent) => {
      const a = (e.target as Element | null)?.closest?.('a')
      if (!closeOnPick || !a || !root.current?.contains(a) || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
      const to = internalHref(a as HTMLAnchorElement)
      if (to && back) {
        e.preventDefault()
        e.stopPropagation()
        pendingNav = to
        done()
        return
      }
      done() // an external link opens (a new tab): the overlay closes behind it
    }
    document.addEventListener('click', pick, true)
    // the phone's Back closes a modal overlay: it holds the overlays' history entry (same address, same scroll key)
    if (back) takeEntry(token, done)
    const unlock = modal ? lockScroll(root) : () => {}
    // a sheet outside the app (a portal): the focus moves into it, Tab stays in it, the app behind is inert
    const app = focusTrap && root.current && !root.current.closest('.shell') ? document.querySelector<HTMLElement>('.shell') : null
    app?.setAttribute('inert', '')
    const tab = (e: KeyboardEvent) => root.current && trapTab(e, root.current)
    if (focusTrap) {
      document.addEventListener('keydown', tab)
      requestAnimationFrame(() => root.current && !root.current.contains(document.activeElement) && root.current.focus({ preventScroll: true }))
    }
    return () => {
      window.removeEventListener(OPENED, other)
      document.removeEventListener('keydown', key)
      document.removeEventListener(modal ? 'click' : 'pointerdown', away, true)
      document.removeEventListener('click', pick, true)
      document.removeEventListener('keydown', tab)
      app?.removeAttribute('inert')
      unlock()
      goRef.current = null
      const nav = pendingNav
      const then = nav === null ? null : typeof nav === 'string' ? () => navigate(nav) : nav
      // closed another way than Back (its button, Escape, outside, a choice): its history entry goes (unless another
      // overlay took it over), then what was chosen happens
      releaseEntry(token, then)
      // the focus was inside the overlay that is now gone: back to what opened it (a new page places it itself)
      const lost = !document.activeElement || document.activeElement === document.body || root.current?.contains(document.activeElement)
      if (!nav && lost) opener?.current?.focus({ preventScroll: true })
    }
  }, [open, id, modal, outside, closeOnPick, back, focusTrap]) // eslint-disable-line react-hooks/exhaustive-deps
  return (next) => (goRef.current ? goRef.current(next) : (close(), typeof next === 'string' ? navigate(next) : next()))
}

/** Follows a media query (the phone layout below 881px: `PHONE`). */
export const PHONE = '(max-width: 880px)'
export function useMedia(query: string): boolean {
  const [on, setOn] = useState(() => typeof window !== 'undefined' && !!window.matchMedia?.(query).matches)
  useEffect(() => {
    const mq = window.matchMedia?.(query)
    if (!mq) return
    const f = () => setOn(mq.matches)
    f()
    mq.addEventListener('change', f)
    return () => mq.removeEventListener('change', f)
  }, [query])
  return on
}
