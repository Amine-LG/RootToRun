import { useEffect, useRef, type ReactNode } from 'react'
import '../explore.css'

/** Where a page's contribution actions go ("Edit", "Report"): the top-right end of the page bar or of the page head.
 *  An empty slot takes no room. */
export function ActionsSlot({ children }: { children?: ReactNode }) {
  return (
    <div className="page-actions-slot" data-testid="page-actions-slot">
      {children}
    </div>
  )
}

/** The header every Explore, Reference and list page shares: where you are (the section), what this page is (the
 *  title) and what it is for (one purpose line). `aside` holds one small fact such as a score; `actions` fills the
 *  top-right slot. */
export function PageHead({ eyebrow, title, lede, aside, actions }: { eyebrow: string; title: ReactNode; lede?: ReactNode; aside?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="xp-head">
      <div className="xp-head-text">
        <p className="xp-eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {lede && <p className="xp-lede">{lede}</p>}
      </div>
      {aside && <div className="xp-head-aside">{aside}</div>}
      <ActionsSlot>{actions}</ActionsSlot>
    </header>
  )
}

/** The bar at the top of a detail page (a lesson, a lab, an incident, a challenge): the way back first, the page's own
 *  controls after it, and the contribution actions' slot at the right end, or before `end` (a lesson's pager). On wide screens it stays under the site
 *  header while the page scrolls, so the way back, the pager and the actions stay within reach; its height joins the
 *  sticky chrome (--page-bar-h, tokens.css) so anchors and sticky columns start below it. On phones it scrolls away
 *  (the lesson contents bar is the sticky one there). */
export function PageBar({ className = '', children, actions, end }: { className?: string; children: ReactNode; actions?: ReactNode; end?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const root = document.documentElement
    const set = () => root.style.setProperty('--page-bar-h', getComputedStyle(el).position === 'sticky' ? `${Math.round(el.getBoundingClientRect().height)}px` : '0px')
    set()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(set) : null
    ro?.observe(el)
    window.addEventListener('resize', set)
    return () => {
      ro?.disconnect()
      window.removeEventListener('resize', set)
      root.style.removeProperty('--page-bar-h')
    }
  }, [])
  return (
    <div ref={ref} className={`page-bar ${className}`} data-sticky data-testid="page-bar">
      {children}
      <ActionsSlot>{actions}</ActionsSlot>
      {end}
    </div>
  )
}
