import { Fragment, useEffect, useId, useMemo, useState } from 'react'
import { gridLayout, placeLabels, routeInside, union, wordParts, type Box } from '../lib/graph'
import type { DiagramDef, DNode } from '../lib/diagrams'
import { Md } from '../lib/md'
import { GraphViewport, useSizes } from './GraphViewport'
import './graph.css'

const rootFont = () => parseFloat(getComputedStyle(document.documentElement).fontSize) || 16

/** A Studio diagram: authored grid positions, measured boxes, edges between box borders, details for a selection. */
export function FlowDiagram({ d }: { d: DiagramDef }) {
  const marker = useId().replace(/:/g, '')
  const [sel, setSel] = useState<string | null>(null)
  useEffect(() => setSel(null), [d.id])
  const [sizes, measure] = useSizes()
  const u = rootFont()
  const byId = useMemo(() => Object.fromEntries(d.nodes.map(n => [n.id, n])), [d])
  const nodeSizes = useMemo(() => Object.fromEntries(d.nodes.filter(n => sizes[`n:${n.id}`]).map(n => [n.id, sizes[`n:${n.id}`]])), [d, sizes])

  const geo = useMemo(() => {
    const zoned = !!d.zones?.length
    const layout = gridLayout(Object.fromEntries(d.nodes.map(n => [n.id, { col: n.col, row: n.row, span: n.span }])), nodeSizes,
      { gapX: u * 5.5, gapY: u * (zoned ? 4.5 : 3.5), pad: u * 1.5, top: u * (zoned ? 3 : 1.5), colWidth: u * 10, rowHeight: u * 4 })
    const zoneOf = (boxes: Record<string, Box>) => (d.zones || []).flatMap(z => {
      const inside = d.nodes.filter(n => n.col >= z.col && n.col < z.col + z.cols && n.row >= z.row && n.row < z.row + z.rows).map(n => boxes[n.id])
      if (!inside.length) return []
      const b = union(inside), frame = { x: b.x - u, y: b.y - u * 1.5, w: b.w + u * 2, h: b.h + u * 2.5 }
      const tab = sizes[`z:${z.label}`] || { w: z.label.length * u * .55 + u, h: u * 1.6 }
      return [{ label: z.label, frame, tab: { x: frame.x + u / 2, y: frame.y - tab.h / 2, w: tab.w, h: tab.h } }]
    })
    const first = zoneOf(layout.boxes)
    const r = routeInside(layout.boxes, d.edges, { clearance: u / 2, pad: u, extra: [...first.map(z => z.frame), ...first.map(z => z.tab)] })
    const boxes = r.boxes, routes = r.routes, zones = r.shift.x || r.shift.y ? zoneOf(boxes) : first, tabs = zones.map(z => z.tab)
    const labels = placeLabels(routes, d.edges.map((e, i) => e.label ? sizes[`e:${i}`] || { w: (e.caption || e.label).length * u * .5 + u * .6, h: u * 1.5 } : null),
      [...Object.values(boxes), ...tabs])
    const all = union([...Object.values(boxes), ...zones.map(z => z.frame), ...tabs, ...labels.filter((l): l is Box => !!l)])
    return { boxes, zones, routes, labels, content: { w: Math.max(r.w, all.x + all.w + u), h: Math.max(r.h, all.y + all.h + u) } }
  }, [d, nodeSizes, sizes, u])

  const node = sel ? byId[sel] : undefined
  const touches = (i: number) => !!sel && (d.edges[i].from === sel || d.edges[i].to === sel)
  const near = new Set(sel ? [sel, ...d.edges.flatMap(e => e.from === sel ? [e.to] : e.to === sel ? [e.from] : [])] : [])
  const relations = (id: string) => <ul className="graph-relations">{d.edges.filter(e => e.from === id || e.to === id).map((e, i) => <li key={i}>
    <strong>{byId[e.from]?.label || e.from}</strong> {e.both ? '↔' : '→'} <strong>{byId[e.to]?.label || e.to}</strong>{e.label ? `: ${e.label}` : e.kind === 'flow' ? ': request flow' : ': connected'}
  </li>)}</ul>
  const textVersion = <ol className="graph-list fd-list">{d.nodes.map((n: DNode) => <li key={n.id}>
    <button className="graph-list-node" aria-pressed={sel === n.id} onClick={() => setSel(sel === n.id ? null : n.id)}>{n.label}</button>
    {n.sub && <p>{n.sub}</p>}{n.detail && <Md text={n.detail} />}{relations(n.id)}
  </li>)}</ol>

  return <figure className="graph-figure" style={{ margin: 0 }} data-testid={`diagram-${d.id}`}>
    <GraphViewport title={d.title} label={d.title} content={geo.content} resetKey={d.id} textVersion={textVersion}
      keepVisible={sel ? geo.boxes[sel] : null} onCloseDetails={() => setSel(null)} onReset={() => setSel(null)}
      details={node && <div className="fd-pop" id={`detail-${marker}`}>
        <div className="fd-pop-h"><strong>{node.label}</strong>{node.sub && <small>{node.sub}</small>}</div>
        <Md text={node.detail || ''} />{relations(node.id)}
      </div>}>
      <div className="graph-content" data-selected={sel || undefined}>
        <svg className="fd-edges" width={geo.content.w} height={geo.content.h} aria-hidden="true">
          <defs>
            {['plain', 'accent'].map(k => <marker key={k} id={`${marker}-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" className={`fd-arrow ${k}`} /></marker>)}
          </defs>
          {geo.routes.map((r, i) => {
            if (!r) return null
            const e = d.edges[i], accent = e.kind === 'flow' || touches(i), m = `url(#${marker}-${accent ? 'accent' : 'plain'})`
            return <path key={i} d={r.d} data-from={e.from} data-to={e.to} className={`fd-edge ${e.kind || ''} ${touches(i) ? 'hl' : ''} ${sel && !touches(i) ? 'dim' : ''}`} markerEnd={m} markerStart={e.both ? m : undefined} />
          })}
        </svg>
        {geo.zones.map(z => <div className="fd-zone" key={z.label} style={{ left: z.frame.x, top: z.frame.y, width: z.frame.w, height: z.frame.h }} aria-hidden="true">
          <span className="fd-zone-label" ref={measure(`z:${z.label}`)} style={{ left: z.tab.x - z.frame.x, top: z.tab.y - z.frame.y }}>{z.label}</span>
        </div>)}
        {geo.labels.map((l, i) => l && <span key={i} ref={measure(`e:${i}`)} className={`fd-edge-label ${sel && !touches(i) ? 'dim' : ''}`} data-edge-index={i}
          title={d.edges[i].label} style={{ left: l.x, top: l.y }}>{d.edges[i].caption || d.edges[i].label}</span>)}
        {d.nodes.map(n => { const b = geo.boxes[n.id]; return <button key={n.id} ref={measure(`n:${n.id}`)} data-node-id={n.id}
          className={`fd-node ${n.kind || ''} ${sel === n.id ? 'on' : ''} ${sel && !near.has(n.id) ? 'dim' : ''}`} style={{ left: b.x, top: b.y, width: `calc(${n.span || 1} * 10rem + ${((n.span || 1) - 1) * 5.5}rem)` }}
          aria-pressed={sel === n.id} aria-controls={sel === n.id ? `detail-${marker}` : undefined} onClick={() => setSel(sel === n.id ? null : n.id)}>
          <strong>{wordParts(n.label).map((w, i) => <Fragment key={i}>{i > 0 && <wbr />}{w}</Fragment>)}</strong>{n.sub && <small>{n.sub}</small>}
        </button> })}
      </div>
    </GraphViewport>
    <figcaption className="graph-caption fd-caption"><Md text={d.caption} /></figcaption>
  </figure>
}
