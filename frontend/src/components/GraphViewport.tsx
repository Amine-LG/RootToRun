import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { clampView, fit, reveal, wheelZoom, zoomAt, type Box, type View } from '../lib/graph'
import { Icon } from './ui'
import './graph.css'
import { useOverlay } from '../lib/overlay'

const PAD = 16, MIN_HEIGHT = 200

/** Sizes of rendered elements by id, measured before paint and again whenever they change (fonts, theme, text). */
export function useSizes() {
  const els = useRef(new Map<string, HTMLElement>()), refs = useRef(new Map<string, (el: HTMLElement | null) => void>())
  const ro = useRef<ResizeObserver | null>(null)
  const [sizes, setSizes] = useState<Record<string, { w: number; h: number }>>({})
  const read = useCallback(() => {
    const next: Record<string, { w: number; h: number }> = {}
    els.current.forEach((el, id) => { if (el.isConnected && el.offsetWidth) next[id] = { w: el.offsetWidth, h: el.offsetHeight } })
    setSizes(old => {
      const ks = Object.keys(next)
      return ks.length === Object.keys(old).length && ks.every(k => old[k] && Math.abs(old[k].w - next[k].w) < .5 && Math.abs(old[k].h - next[k].h) < .5) ? old : next
    })
  }, [])
  useLayoutEffect(() => {
    ro.current = new ResizeObserver(read)
    els.current.forEach(el => ro.current!.observe(el))
    read(); document.fonts?.ready.then(read)
    return () => { ro.current?.disconnect(); ro.current = null }
  }, [read])
  useLayoutEffect(read) // after every render, before paint: new or changed elements are measured at once
  const measure = useCallback((id: string) => {
    let ref = refs.current.get(id)
    if (!ref) {
      ref = (el: HTMLElement | null) => {
        const old = els.current.get(id)
        if (old && old !== el) { ro.current?.unobserve(old); els.current.delete(id) }
        if (el) { els.current.set(id, el); ro.current?.observe(el) }
      }
      refs.current.set(id, ref)
    }
    return ref
  }, [])
  return [sizes, measure] as const
}

/** The width available to an element, followed as it changes. */
export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null), [w, setW] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current; if (!el) return
    const ro = new ResizeObserver(() => setW(el.clientWidth)); ro.observe(el); setW(el.clientWidth)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

type Props = {
  title: ReactNode; label: string
  content: { w: number; h: number }
  children: ReactNode
  /** the camera is reset (fitted) when this changes */
  resetKey: unknown
  /** largest embedded height in px (default: 70% of the window, at most 680) */
  maxHeight?: number
  textVersion?: ReactNode
  details?: ReactNode
  onCloseDetails?: () => void
  /** a box (content coordinates) to keep in view, such as the selected node */
  keepVisible?: Box | null
  toolbarExtra?: ReactNode
  help?: string
  /** "Reset": back to the starting view (everything in view, nothing selected); the owner clears its own selection */
  onReset?: () => void
}

/**
 * A diagram's frame: zoom and pan (buttons, Ctrl/⌘ + wheel or pinch, drag, keys), full-screen view, a text version,
 * and a details panel in the normal page flow. Plain wheel scrolling and one-finger swipes always scroll the page.
 */
export function GraphViewport({ title, label, content, children, resetKey, maxHeight, textVersion, details, onCloseDetails, keepVisible, toolbarExtra, help, onReset }: Props) {
  const uid = useId()
  const vp = useRef<HTMLDivElement>(null), frame = useRef<HTMLDivElement>(null), expandBtn = useRef<HTMLButtonElement>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [view, setView] = useState<View>({ s: 1, x: PAD, y: PAD }), viewRef = useRef(view)
  const [expanded, setExpanded] = useState(false), [asText, setAsText] = useState(false), [dragging, setDragging] = useState(false)
  const touched = useRef(false), lastKey = useRef(resetKey), lastExpanded = useRef(false)
  const [said, setSaid] = useState('')
  const contentRef = useRef(content); contentRef.current = content

  const cap = maxHeight ?? Math.min(680, Math.round(window.innerHeight * .7))
  const fitScale = size.w ? Math.min(1, (size.w - PAD * 2) / Math.max(1, content.w)) : 1
  const embeddedHeight = Math.round(Math.max(MIN_HEIGHT, Math.min(cap, content.h * fitScale + PAD * 2)))
  const W = size.w, H = expanded ? size.h : embeddedHeight

  const commit = useCallback((v: View) => { const c = contentRef.current, el = vp.current; const next = el ? clampView(v, c, el.clientWidth, el.clientHeight) : v; viewRef.current = next; setView(next) }, [])
  const fitAll = useCallback(() => { touched.current = false; const el = vp.current; if (el) commit(fit(contentRef.current, el.clientWidth, el.clientHeight, PAD)) }, [commit])
  const zoomBy = useCallback((k: number, px?: number, py?: number) => {
    const el = vp.current; if (!el) return
    const v = viewRef.current, floor = Math.min(.25, fit(contentRef.current, el.clientWidth, el.clientHeight, PAD).s)
    const s = Math.min(3, Math.max(floor, v.s * k)); if (Math.abs(s - v.s) < 1e-6) return
    touched.current = true; commit(zoomAt(v, s, px ?? el.clientWidth / 2, py ?? el.clientHeight / 2))
  }, [commit])
  const panBy = (dx: number, dy: number) => { touched.current = true; commit({ ...viewRef.current, x: viewRef.current.x + dx, y: viewRef.current.y + dy }) }

  // viewport size
  useLayoutEffect(() => {
    const el = vp.current; if (!el || asText) return
    const read = () => setSize(old => old.w === el.clientWidth && old.h === el.clientHeight ? old : { w: el.clientWidth, h: el.clientHeight })
    const ro = new ResizeObserver(read); ro.observe(el); read(); return () => ro.disconnect()
  }, [expanded, asText])
  // fit whenever the content or the space changes, unless the learner moved the camera; a new resetKey always refits
  useLayoutEffect(() => {
    if (lastKey.current !== resetKey || lastExpanded.current !== expanded) { lastKey.current = resetKey; lastExpanded.current = expanded; touched.current = false }
    if (!W || !H) return
    const v = touched.current ? clampView(viewRef.current, content, W, H) : fit(content, W, H, PAD)
    viewRef.current = v; setView(v)
  }, [W, H, content.w, content.h, resetKey, expanded])
  // keep the selection in view (no movement when it already is)
  useEffect(() => {
    if (!keepVisible || !W || !H) return
    const v = reveal(viewRef.current, keepVisible, W, H)
    if (v.x !== viewRef.current.x || v.y !== viewRef.current.y) commit(v)
  }, [keepVisible?.x, keepVisible?.y, keepVisible?.w, keepVisible?.h, W, H])

  // wheel and two-finger gestures need non-passive listeners
  useEffect(() => {
    const el = vp.current; if (!el || asText) return
    const wheel = (e: WheelEvent) => {
      if (!expanded && !e.ctrlKey && !e.metaKey) return // the page scrolls
      e.preventDefault()
      const r = el.getBoundingClientRect(); zoomBy(wheelZoom(e.deltaY, e.deltaMode), e.clientX - r.left, e.clientY - r.top)
    }
    let last: { x: number; y: number; d: number } | null = null
    const read = (ts: TouchList) => { const r = el.getBoundingClientRect(), a = ts[0], b = ts[1]; return { x: (a.clientX + b.clientX) / 2 - r.left, y: (a.clientY + b.clientY) / 2 - r.top, d: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY) } }
    const start = (e: TouchEvent) => { if (e.touches.length === 2) { e.preventDefault(); last = read(e.touches) } else last = null }
    const move = (e: TouchEvent) => {
      if (e.touches.length !== 2 || !last) return
      e.preventDefault(); const next = read(e.touches)
      zoomBy(next.d / Math.max(1, last.d), last.x, last.y); panBy(next.x - last.x, next.y - last.y); last = next
    }
    const end = () => { last = null }
    el.addEventListener('wheel', wheel, { passive: false }); el.addEventListener('touchstart', start, { passive: false })
    el.addEventListener('touchmove', move, { passive: false }); el.addEventListener('touchend', end); el.addEventListener('touchcancel', end)
    return () => { el.removeEventListener('wheel', wheel); el.removeEventListener('touchstart', start); el.removeEventListener('touchmove', move); el.removeEventListener('touchend', end); el.removeEventListener('touchcancel', end) }
  }, [expanded, asText, zoomBy])

  // drag to pan; a drag that started on a node does not also click it
  const drag = useRef<{ id: number; x: number; y: number; moved: boolean } | null>(null), suppressClick = useRef(false)
  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0 || (e.pointerType === 'touch' && !expanded)) return
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, moved: false }
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current; if (!d || d.id !== e.pointerId) return
    if (!d.moved) {
      if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < 5) return
      d.moved = true; setDragging(true); vp.current?.setPointerCapture(e.pointerId)
    }
    panBy(e.clientX - d.x, e.clientY - d.y); d.x = e.clientX; d.y = e.clientY
  }
  const endDrag = () => { if (drag.current?.moved) { suppressClick.current = true; setTimeout(() => { suppressClick.current = false }, 0) } drag.current = null; setDragging(false) }

  const close = useCallback(() => { setExpanded(false); requestAnimationFrame(() => expandBtn.current?.focus({ preventScroll: true })) }, [])
  // full screen: the phone's Back closes it, and one overlay at a time (lib/overlay.ts)
  useOverlay(expanded, close, { id: `graph${uid}`, root: frame, opener: expandBtn, modal: true, outside: false, closeOnPick: false })
  useEffect(() => {
    if (!expanded) return
    const old = document.body.style.overflow; document.body.style.overflow = 'hidden'; frame.current?.focus()
    return () => { document.body.style.overflow = old }
  }, [expanded])

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { if (expanded) { e.preventDefault(); close() } else if (details && onCloseDetails) { e.preventDefault(); onCloseDetails() } return }
    if (expanded && e.key === 'Tab') {
      const els = [...(frame.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input,[tabindex="0"]') || [])].filter(x => x.getClientRects().length)
      if (!els.length) return
      if (e.shiftKey && (document.activeElement === els[0] || document.activeElement === frame.current)) { e.preventDefault(); els[els.length - 1].focus() }
      else if (!e.shiftKey && document.activeElement === els[els.length - 1]) { e.preventDefault(); els[0].focus() }
    }
  }
  const onViewportKey = (e: React.KeyboardEvent) => {
    if (e.target !== e.currentTarget && !(e.target as HTMLElement).matches('.fd-node')) return
    const step: Record<string, [number, number]> = { ArrowLeft: [60, 0], ArrowRight: [-60, 0], ArrowUp: [0, 60], ArrowDown: [0, -60] }
    if (step[e.key] && e.target === e.currentTarget) { e.preventDefault(); panBy(...step[e.key]); return }
    if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomBy(1.25) }
    else if (e.key === '-') { e.preventDefault(); zoomBy(1 / 1.25) }
    else if (e.key === '0') { e.preventDefault(); fitAll() }
  }
  // a node reached with Tab is brought into view
  const onFocusNode = (e: React.FocusEvent) => {
    const el = e.target as HTMLElement; if (!el.matches('.fd-node') || !W || !H) return
    const v = reveal(viewRef.current, { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight }, W, H)
    if (v.x !== viewRef.current.x || v.y !== viewRef.current.y) commit(v)
  }

  const pct = Math.round(view.s * 100)
  const body = <div ref={frame} className={`fd graph-workspace ${expanded ? 'graph-expanded' : ''}`} tabIndex={-1} onKeyDown={onKeyDown} data-keys="own"
    role={expanded ? 'dialog' : 'group'} aria-modal={expanded || undefined} aria-labelledby={uid}>
    <div className="graph-heading"><strong className="title" id={uid}>{title}</strong>{toolbarExtra}</div>
    <div className="fd-toolbar graph-toolbar" role="group" aria-label="Diagram controls">
      {!asText && <div className="graph-controls">
        <button className="icon-btn" aria-label="Zoom out" title="Zoom out (−)" onClick={() => zoomBy(1 / 1.25)}><Icon name="minus" /></button>
        <button className="zoom btn sm ghost" aria-label={`Zoom ${pct}%: set to 100%`} title="Actual size" onClick={() => { const el = vp.current; if (el) { touched.current = true; commit(zoomAt(viewRef.current, 1, el.clientWidth / 2, el.clientHeight / 2)) } }}>{pct}%</button>
        <button className="icon-btn" aria-label="Zoom in" title="Zoom in (+)" onClick={() => zoomBy(1.25)}><Icon name="plus" /></button>
        <button className="btn sm ghost" title="Show everything (0)" onClick={fitAll}>Fit</button>
      </div>}
      <span className="graph-toolbar-gap" />
      {onReset && <button className="btn sm ghost" data-testid="diagram-reset" title="Back to the starting view: everything in view, nothing selected"
        onClick={() => { onReset(); fitAll(); setSaid(said === 'Diagram reset.' ? 'Diagram reset. ' : 'Diagram reset.') }}>Reset</button>}
      {textVersion && <button className="btn sm ghost" aria-pressed={asText} onClick={() => setAsText(!asText)}>{asText ? 'Show diagram' : 'Text version'}</button>}
      {expanded ? <button className="btn sm" onClick={close}>Close full screen</button>
        : <button ref={expandBtn} className="btn sm" onClick={() => { setAsText(false); setExpanded(true) }}>Full screen</button>}
    </div>
    <div className={`graph-stage ${details ? 'graph-has-inspector' : ''}`}>
      <div className="graph-primary">
        {asText ? <div className="graph-list-view">{textVersion}</div>
          : <div ref={vp} className={`fd-viewport graph-viewport ${dragging ? 'dragging' : ''}`} style={expanded ? undefined : { height: embeddedHeight }}
            tabIndex={0} role="group" aria-label={`${label}: diagram`} aria-describedby={`${uid}-help`}
            onKeyDown={onViewportKey} onFocus={onFocusNode}
            // the diagram pans with a transform; a browser that scrolls this clipped box to show a focused node
            // (Firefox does) would shift every later view, so any native scroll is undone
            onScroll={e => { const t = e.currentTarget; if (t.scrollLeft || t.scrollTop) { t.scrollLeft = 0; t.scrollTop = 0 } }}
            onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={endDrag}
            onClickCapture={e => { if (suppressClick.current) { e.stopPropagation(); e.preventDefault() } }}>
            <div className="fd-canvas graph-canvas" style={{ width: content.w, height: content.h, transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})` }}>{children}</div>
          </div>}
      </div>
      {details && <aside className="graph-inspector" aria-label="Selection details" aria-live="polite">
        {details}
        {onCloseDetails && <button className="btn sm ghost graph-inspector-close" onClick={onCloseDetails}>Close details</button>}
      </aside>}
    </div>
    <p className="sr-only" role="status" aria-live="polite">{said}</p>
    {!asText && <p className="graph-help" id={`${uid}-help`}>{help || 'Select a box for its details.'} Drag to move; Ctrl or ⌘ + scroll, or pinch, to zoom; Fit shows everything.</p>}
  </div>
  return expanded ? <><div className="graph-expanded-placeholder">{label}: open in full screen</div>{createPortal(body, document.body)}</> : body
}
