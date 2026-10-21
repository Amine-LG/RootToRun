// Page actions: "Report a problem" (an issue form chosen by the kind of problem, with the page's public facts filled in)
// and "Edit on GitHub" (the file that defines what is on screen). Shown only when the site knows the project's
// repository (meta repo_url, from ACADEMY_REPO_URL). They sit at the top right of a page header; once that place has
// scrolled away, a compact copy waits in the site header (#page-actions-dock), so they stay one step away.
import { useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useApp } from '../lib/app'
import { editTargets, editUrl, formsFor, hasRepo, reportUrl, sectionOf, type Contrib, type EditTarget, type FormKey, type PageContext } from '../lib/contribute'
import { t } from '../lib/i18n'
import { PHONE, useMedia, useOverlay } from '../lib/overlay'
import { Icon } from './ui'
import '../contribute.css'

function useContrib(): Contrib | null {
  const { meta } = useApp()
  const m = { repo: meta?.repo_url, branch: meta?.repo_branch, version: [meta?.version, meta?.commit && `(${meta.commit})`].filter(Boolean).join(' ') }
  return hasRepo(m) ? m : null
}

const here = () => [location.pathname, sectionOf(location.hash, location.search)] as const
const ext = { target: '_blank', rel: 'noreferrer noopener' }

/** A report link. Its address is rebuilt when it is used, so the section in it is the one on screen then. */
function ReportItem({ m, form, ctx }: { m: Contrib; form: FormKey; ctx: PageContext }) {
  const id = useId()
  const thing = t(`pa.thing.${ctx.type}` as never)
  const build = () => reportUrl(m, form, ctx, ...here())
  const now = (e: { currentTarget: HTMLAnchorElement }) => void (e.currentTarget.href = build())
  return (
    <li>
      <a className="pa-item" href={build()} {...ext} onClick={now} onFocus={now} onMouseEnter={now} aria-describedby={`${id}d`} data-testid={`report-${form}`}>
        <span className="pa-item-t">
          {t(`pa.form.${form}`, { thing })}
          <span className="sr-only"> {t('pa.newTab')}</span>
        </span>
        <span className="pa-item-d" id={`${id}d`} aria-hidden="true">{t(`pa.form.${form}Help` as never)}</span>
      </a>
    </li>
  )
}

function EditItem({ e }: { e: EditTarget & { href: string } }) {
  const id = useId()
  return (
    <li>
      <a className="pa-item" href={e.href} {...ext} aria-describedby={`${id}d`} data-testid="edit-source" data-path={e.path}>
        <span className="pa-item-t">
          {t(`pa.edit.${e.key}`)}
          <span className="sr-only"> {t('pa.newTab')}</span>
        </span>
        <span className="pa-item-d" id={`${id}d`} aria-hidden="true">
          <code>{e.path.split('/').pop()}</code>
          {e.spoiler && <> · {t('pa.spoiler')}</>}
        </span>
      </a>
    </li>
  )
}

/** A button that shows a short list of links (a disclosure, not an application menu: links stay links). On a desktop
 *  it opens under the button and stays inside the window; on a phone it is a sheet from the bottom of the screen, with
 *  a title and a close button, over a dimmed page. Choosing a link, a tap outside, Escape, Back (phone) or the close
 *  button closes it (lib/overlay.ts); Escape returns the focus to the button. */
function Disclosure({ label, icon, compact, text, testid, title, open, setOpen, children }: {
  label: string; icon: string; compact?: boolean; text?: string; testid: string; title?: string
  open: boolean; setOpen: (v: boolean) => void; children: ReactNode
}) {
  const id = useId()
  const phone = useMedia(PHONE)
  const box = useRef<HTMLDivElement>(null), pop = useRef<HTMLDivElement>(null), btn = useRef<HTMLButtonElement>(null)
  useOverlay(open, () => setOpen(false), { id: `pa${id}`, root: pop, opener: btn, modal: phone, focusTrap: phone })
  // the sheet follows the visible area (Android's keyboard shrinks it, not the layout viewport)
  useEffect(() => {
    const vv = window.visualViewport
    if (!open || !phone || !vv) return
    const root = document.documentElement.style
    const set = () => (root.setProperty('--vv-top', `${vv.offsetTop}px`), root.setProperty('--vv-height', `${vv.height}px`))
    set()
    vv.addEventListener('resize', set)
    vv.addEventListener('scroll', set)
    return () => {
      vv.removeEventListener('resize', set)
      vv.removeEventListener('scroll', set)
      root.removeProperty('--vv-top')
      root.removeProperty('--vv-height')
    }
  }, [open, phone])
  // a popover stays inside the window: shifted right when its button sits too far left for it to open leftwards
  useLayoutEffect(() => {
    const el = pop.current
    if (!open || phone || !el) return
    el.style.removeProperty('--pa-shift')
    const r = el.getBoundingClientRect(), room = document.documentElement.clientWidth
    const shift = r.left < 8 ? 8 - r.left : r.right > room - 8 ? room - 8 - r.right : 0
    if (shift) el.style.setProperty('--pa-shift', `${Math.round(shift)}px`)
  }, [open, phone])
  const panel = phone ? (
    createPortal(
      <div className="pa-backdrop" data-testid={`${testid}-backdrop`}>
        <div id={id} ref={pop} className="pa-sheet" role="dialog" aria-modal="true" aria-labelledby={`${id}t`} tabIndex={-1} data-testid={`${testid}-sheet`}>
          <div className="pa-sheet-h">
            <h2 id={`${id}t`}>{title || label}</h2>
            <button type="button" className="icon-btn" onClick={() => setOpen(false)} aria-label={t('ui.close')} data-testid={`${testid}-close`}>
              <Icon name="x" size={18} />
            </button>
          </div>
          {children}
        </div>
      </div>,
      document.body,
    )
  ) : (
    <div id={id} ref={pop} className="pa-pop" hidden={!open}>
      {children}
    </div>
  )
  return (
    <div className="pa-menu" ref={box}>
      <button ref={btn} type="button" className={`pa-btn ${compact && !text ? 'pa-icon' : ''}`} aria-expanded={open} aria-controls={open ? id : undefined}
        aria-haspopup={phone ? 'dialog' : undefined} onClick={() => setOpen(!open)}
        aria-label={compact && !text ? label : text ? label : undefined} title={compact ? label : undefined} data-testid={testid}>
        <Icon name={icon} size={compact && !text ? 17 : 14} />
        {(text || !compact) && <span aria-hidden={text ? 'true' : undefined}>{text || label}</span>}
        {!compact && <svg className="pa-caret" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 3.5l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>}
      </button>
      {(open || !phone) && panel}
    </div>
  )
}

// The page's actions, for the phone menu's "This page" group (components/Shell.tsx): which page has them, and a way
// to open them from there.
type PageActionsInfo = { label: string }
const subs = new Set<() => void>()
let current: PageActionsInfo | null = null
const OPEN_PA = 'rtr:open-page-actions'
export function usePageActions(): PageActionsInfo | null {
  return useSyncExternalStore((f) => (subs.add(f), () => void subs.delete(f)), () => current)
}
export const openPageActions = () => window.dispatchEvent(new Event(OPEN_PA))

/** "Report a problem" and "Edit on GitHub" for one page. `ctx` says what the page shows (lib/contribute.ts). */
export function PageActions({ ctx }: { ctx: PageContext }) {
  const m = useContrib()
  const wrap = useRef<HTMLDivElement>(null), dockRef = useRef<HTMLDivElement>(null)
  const [docked, setDocked] = useState(false)
  const [dock, setDock] = useState<HTMLElement | null>(null)
  const [openReport, setOpenReport] = useState(false), [openEdit, setOpenEdit] = useState(false)
  const [openMore, setOpenMore] = useState(false), [openDocked, setOpenDocked] = useState(false)
  useEffect(() => {
    const el = wrap.current
    setDock(document.getElementById('page-actions-dock'))
    if (!el || typeof IntersectionObserver === 'undefined') return
    const top = () => document.querySelector('.topbar')?.getBoundingClientRect().height || 60
    // docked once the actions have gone up behind the site header; back when they are on screen again, and a focus
    // held by the docked copy moves to the page's own button instead of being lost
    const io = new IntersectionObserver(([e]) => {
      const gone = !e.isIntersecting && e.boundingClientRect.top < top()
      if (!gone && dockRef.current?.contains(document.activeElement))
        [...el.querySelectorAll<HTMLElement>('.pa-wide > .pa-menu > button, .pa-narrow button')].find((x) => x.offsetParent)?.focus({ preventScroll: true })
      setDocked(gone)
      if (!gone) setOpenDocked(false) // the docked copy goes away: its panel with it
    }, { rootMargin: `-${Math.round(top())}px 0px 0px 0px` })
    io.observe(el)
    return () => io.disconnect()
  }, [m?.repo])
  const edits = m ? editTargets(ctx).flatMap((e) => {
    const href = editUrl(m, e.path)
    return href ? [{ ...e, href }] : []
  }) : []
  const thing = t(`pa.thing.${ctx.type}` as never)
  const moreLabel = edits.length ? t('pa.moreLabel', { thing }) : t('pa.reportMenu', { thing })
  // the phone menu's "This page" group offers the same actions (components/Shell.tsx), and opens this sheet
  useEffect(() => {
    if (!m) return
    current = { label: moreLabel }
    subs.forEach((f) => f())
    const open = () => setOpenMore(true)
    window.addEventListener(OPEN_PA, open)
    return () => {
      window.removeEventListener(OPEN_PA, open)
      current = null
      subs.forEach((f) => f())
    }
  }, [m?.repo, moreLabel]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!m) return null
  const forms = formsFor(ctx.type)
  const reports = (
    <ul className="pa-list" role="list">
      {forms.map((f) => <ReportItem key={f} m={m} form={f} ctx={ctx} />)}
    </ul>
  )
  const editList = (
    <ul className="pa-list" role="list">
      {edits.map((e) => <EditItem key={e.path + e.key} e={e} />)}
    </ul>
  )
  const both = (
    <>
      <p className="pa-h">{t('pa.report')}</p>
      {reports}
      {edits.length > 0 && (
        <>
          <p className="pa-h">{t('pa.editHead')}</p>
          {editList}
        </>
      )}
    </>
  )
  const direct = edits.length === 1 && !edits[0].spoiler ? edits[0] : null // one plain file: a direct link
  return (
    <div className="pa" ref={wrap} role="group" aria-label={t('pa.label')} data-testid="page-actions">
      <div className="pa-wide">
        <Disclosure label={t('pa.report')} icon="flag" testid="report-menu" open={openReport} setOpen={setOpenReport}>{reports}</Disclosure>
        {direct ? (
          <a className="pa-btn" href={direct.href} {...ext} data-testid="edit-source" data-path={direct.path}>
            <Icon name="file" size={14} />
            <span>{t(`pa.edit.${direct.key}`)}</span>
            <span className="sr-only"> {t('pa.newTab')}</span>
          </a>
        ) : edits.length > 0 && (
          <Disclosure label={t('pa.editHead')} icon="file" testid="edit-menu" open={openEdit} setOpen={setOpenEdit}>{editList}</Disclosure>
        )}
      </div>
      <div className="pa-narrow">
        <Disclosure label={moreLabel} icon="flag" compact text={edits.length ? t('pa.narrowBoth') : t('pa.narrowReport')} title={moreLabel}
          testid="page-actions-more" open={openMore} setOpen={setOpenMore}>{both}</Disclosure>
      </div>
      {docked && dock && createPortal(
        <div className="pa-dock" ref={dockRef} role="group" aria-label={t('pa.label')} data-testid="page-actions-dock">
          <Disclosure label={moreLabel} icon="flag" compact testid="page-actions-docked" open={openDocked} setOpen={setOpenDocked}>{both}</Disclosure>
        </div>,
        dock,
      )}
    </div>
  )
}

/** The footer's "Report a problem": a website defect, on every page, with its relative address and the site version. */
export function ReportSiteLink() {
  const m = useContrib()
  if (!m) return null
  const now = (e: { currentTarget: HTMLAnchorElement }) => void (e.currentTarget.href = reportUrl(m, 'website', null, location.pathname))
  return (
    <a href={reportUrl(m, 'website', null, location.pathname)} {...ext} onClick={now} onFocus={now} onMouseEnter={now} aria-label={t('foot.reportLabel')} data-testid="foot-report">
      {t('foot.report')}
    </a>
  )
}
