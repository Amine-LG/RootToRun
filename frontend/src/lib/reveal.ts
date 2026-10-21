// One policy for every piece of content that appears because the learner asked for it: command output, a terminal,
// the next activity or lab step, a check verdict, an expanded section.
//
// 1. If the new content is already fully visible, nothing moves.
// 2. If it fits on screen, scroll the smallest distance that shows all of it (its start stays visible).
// 3. If it is taller than the screen, show its start: either it already sits in the upper part of the screen, or it is
//    aligned just under the sticky header. Content is never aligned by its bottom edge.
// The decision waits until layout has settled (two frames), measures the real sticky header, and honours reduced
// motion. Focus never scrolls the page on its own: callers use focusQuietly() and let this policy decide.

export const reducedMotion = () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** Bottom edge of the sticky bars that would cover `target` once the page has scrolled: the header, and on phones
 * the lesson outline bar under it. A sticky element only covers the target if it spans the target's middle: on desktop
 * the outline is a side column beside the reading column, and a box as wide as the page (the lesson's "Before you
 * start") reaches over that column without being covered by it. Without a target, only the header counts. */
export function headerBottom(target?: Element | null): number {
  const t = target?.getBoundingClientRect()
  const mid = t ? (t.left + t.right) / 2 : 0
  let bottom = 0
  for (const el of document.querySelectorAll<HTMLElement>('.topbar, .outline, [data-sticky]')) {
    const cs = getComputedStyle(el)
    if (cs.position !== 'sticky' && cs.position !== 'fixed') continue
    if (target && el.contains(target)) continue
    const r = el.getBoundingClientRect()
    if (!r.height || cs.display === 'none') continue
    const isHeader = el.classList.contains('topbar')
    if (!isHeader && (!t || mid < r.left || mid > r.right)) continue
    const top = parseFloat(cs.top) || 0
    bottom = Math.max(bottom, top + r.height)
  }
  return bottom
}

/** Top edge of what covers the bottom of the window: the phone's tab bar when it is shown (it is hidden while the
 *  on-screen keyboard is up, and on desktop), else the window's own bottom. */
export function footerTop(): number {
  const tabs = typeof document !== 'undefined' ? document.querySelector<HTMLElement>('.shell > .tabbar') : null
  if (!tabs || getComputedStyle(tabs).display === 'none') return window.innerHeight
  return Math.min(window.innerHeight, tabs.getBoundingClientRect().top)
}

const GAP = 12 // breathing room under the header and above the bottom edge
const START_ZONE = 0.4 // a tall block whose start is in the top 40% of the usable screen is already readable

/** How far the window should scroll so that `el` is usefully visible; 0 when it already is. Exported for tests. */
export function revealDelta(r: { top: number; bottom: number; height: number }, viewTop: number, viewBottom: number): number {
  const top = viewTop + GAP
  const bottom = viewBottom - GAP
  const avail = bottom - top
  if (r.top >= top && r.bottom <= bottom) return 0 // rule 1
  if (r.height <= avail) return r.top < top ? r.top - top : r.bottom - bottom // rule 2
  if (r.top >= top && r.top <= top + avail * START_ZONE) return 0 // rule 3, start already readable
  return r.top - top // rule 3, align the start under the header
}

const afterLayout = (f: () => void) => requestAnimationFrame(() => requestAnimationFrame(f))

/** Whether `el` sits in a fixed layer (a sheet, a dialog, the menu): scrolling the window cannot move it, and would only
 *  move the page behind it. Such a layer scrolls itself. */
export function inFixedLayer(el: Element | null | undefined): boolean {
  for (let e = el?.parentElement; e; e = e.parentElement) if (getComputedStyle(e).position === 'fixed') return true
  return false
}

/** Apply the policy to `el` once layout has settled. */
export function reveal(el: Element | null | undefined, opts: { then?: () => void } = {}) {
  if (!el) return
  afterLayout(() => {
    if (!el.isConnected) return
    if (inFixedLayer(el)) return opts.then?.()
    const r = el.getBoundingClientRect()
    const d = revealDelta(r, headerBottom(el), footerTop()) // never under the phone's tab bar
    if (Math.abs(d) >= 1) window.scrollBy({ top: d, behavior: reducedMotion() ? 'auto' : 'smooth' })
    opts.then?.()
  })
}

/** Move keyboard focus without letting the browser scroll the page to the focused element. */
export function focusQuietly(el: HTMLElement | null | undefined) {
  el?.focus({ preventScroll: true })
}

/** Touch-first devices open an on-screen keyboard on focus, so text fields are not focused for them automatically. */
export const coarsePointer = () => !!window.matchMedia?.('(pointer: coarse)').matches && !window.matchMedia?.('(pointer: fine)').matches

// ---------------------------------------------------------------- disclosure sections (<details>)
// A section the learner opens is revealed by the same policy (summary first). A section the learner closes keeps its
// summary on screen: if closing it would leave the summary above the header, the page moves back to the summary.
// -Infinity, not 0: a <details> rendered open (the lesson contents on wide screens) fires `toggle` while the page loads,
// often within 600 ms of time origin, and must not count as the learner opening it (the lesson jumped down on load)
let lastSummaryClick = -Infinity
if (typeof document !== 'undefined') {
  document.addEventListener('click', (e) => {
    if ((e.target as Element | null)?.closest?.('summary')) lastSummaryClick = performance.now()
  }, true)
  document.addEventListener('keydown', (e) => {
    if ((e.key === 'Enter' || e.key === ' ') && (e.target as Element | null)?.closest?.('summary')) lastSummaryClick = performance.now()
  }, true)
  document.addEventListener('toggle', (e) => {
    const d = e.target as HTMLDetailsElement
    if (!(d instanceof HTMLDetailsElement) || performance.now() - lastSummaryClick > 600) return
    if (d.closest('[data-reveal="off"]') || inFixedLayer(d)) return
    if (d.open) reveal(d)
    else {
      const s = d.querySelector(':scope > summary')
      afterLayout(() => {
        const r = s?.getBoundingClientRect()
        const top = headerBottom(s) + GAP
        if (r && r.top < top) window.scrollBy({ top: r.top - top, behavior: 'auto' })
      })
    }
  }, true)
}

/** Show `el` from its first line: used when more lines appear below the point the learner was reading (for example
 * "Show more retained lines"). Works inside a nested scroll box (a terminal) as well as on the page. Nothing moves if
 * the start is already in the upper part of the visible area. */
export function revealStart(el: Element | null | undefined) {
  if (!el) return
  afterLayout(() => {
    if (!el.isConnected) return
    let box: HTMLElement | null = el.parentElement
    while (box && box !== document.body) {
      const oy = getComputedStyle(box).overflowY
      if ((oy === 'auto' || oy === 'scroll') && box.scrollHeight > box.clientHeight + 1) break
      box = box.parentElement
    }
    const r = el.getBoundingClientRect()
    if (box && box !== document.body) {
      const b = box.getBoundingClientRect()
      const rel = r.top - b.top
      if (rel < 0 || rel > box.clientHeight * START_ZONE) box.scrollTo({ top: box.scrollTop + rel - 8, behavior: 'auto' })
      reveal(box) // and make sure the scroll box itself is on screen
      return
    }
    const top = headerBottom(el) + GAP
    const avail = footerTop() - GAP - top
    if (r.top < top || r.top > top + avail * START_ZONE) window.scrollBy({ top: r.top - top, behavior: reducedMotion() ? 'auto' : 'smooth' })
  })
}
