// Keyboard and screen-reader users start a new page at its heading (App.tsx on navigation; the page area's Try again).

/** Focus the new page's h1 once it renders (pages load their content asynchronously), without scrolling. Gives up if
 *  focus has already moved into the page, or after a few seconds. Returns the cleanup. */
export function focusHeading(): () => void {
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
