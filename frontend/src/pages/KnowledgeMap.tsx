import { useEffect, useMemo, useState } from 'react'
import { GraphViewport, useSizes, useWidth } from '../components/GraphViewport'
import { PageHead } from '../components/PageHead'
import { Icon } from '../components/ui'
import { useApp } from '../lib/app'
import type { Concept } from '../lib/data'
import { conceptEvidence, evidenceLevel, type EvidenceLevel } from '../lib/evidence'
import { groupedLayout, neighbourWidth, neighbourhoodLayout, routeEdges, routeInside, treeEdges, type Box } from '../lib/graph'
import { t } from '../lib/i18n'
import { useProgress } from '../lib/progress'
import { navigate } from '../lib/router'
import { labHref, lessonHref, refOf } from '../lib/urls'
import '../components/graph.css'
import '../explore.css'

const LEVEL: Record<EvidenceLevel, string> = { none: 'Not started', read: 'Read', checked: 'Checked', practised: 'Practised', verified: 'Verified on a cluster' }
const overviewCol = (width: number) => width < 600 ? Math.floor((width - 32 - 20) / 2) : 184

/**
 * The concepts of the course and how they relate. "Neighbourhood" puts one concept in the middle with every concept
 * related to it around it; "Everything" shows all concepts grouped by territory, with the links of the concept under
 * the pointer or selected. Relationships are symmetric, so lines have no arrows.
 */
export default function KnowledgeMap({ query }: { query?: URLSearchParams }) {
  const { cur } = useApp(), prog = useProgress()
  const requested = query?.get('concept') || ''
  const concepts = cur?.concepts || {}
  const fallback = cur?.lessons[(prog.last && refOf(prog.last.href)?.id) || '']?.concepts.find(c => concepts[c]) || Object.keys(concepts)[0] || ''
  const [focus, setFocus] = useState(concepts[requested] ? requested : fallback)
  const [mode, setMode] = useState<'near' | 'all'>(query?.get('view') === 'all' ? 'all' : 'near')
  const [picked, setPicked] = useState<string | null>(null), [hover, setHover] = useState<string | null>(null)
  const [track, setTrack] = useState('all'), [search, setSearch] = useState('')
  useEffect(() => { if (concepts[requested]) { setFocus(requested); setMode('near') } else if (!concepts[focus] && fallback) setFocus(fallback) }, [requested, cur])

  const [wrap, outer] = useWidth<HTMLDivElement>()
  const width = Math.max(0, outer - 34) // the frame's borders and the viewport's 16px padding on each side: layouts fit at 100%
  const [sizes, measure] = useSizes()

  // symmetric adjacency, the territory of every concept, and the evidence of every concept
  const { links, nb, trackOf } = useMemo(() => {
    const seen = new Set<string>(), links: [string, string][] = [], nb: Record<string, string[]> = {}
    for (const c of Object.values(concepts)) for (const r of c.related) {
      if (!concepts[r]) continue
      const key = [c.id, r].sort().join('|'); if (seen.has(key)) continue
      seen.add(key); links.push([c.id, r]); (nb[c.id] ||= []).push(r); (nb[r] ||= []).push(c.id)
    }
    const trackOf: Record<string, number> = {}
    cur?.tracks.forEach((tr, i) => tr.modules.forEach(m => Object.values(concepts).forEach(c => { if (c.module === m && trackOf[c.id] === undefined) trackOf[c.id] = i })))
    return { links, nb, trackOf }
  }, [cur])
  const evidence = useMemo(() => Object.fromEntries(Object.keys(concepts).map(id => [id, conceptEvidence(cur!, prog, id)])), [cur, prog])
  const order = useMemo(() => {
    const pos: Record<string, number> = {}
    cur?.tracks.forEach((tr, i) => tr.modules.forEach((m, j) => { pos[m] = i * 1000 + j }))
    return (a: string, b: string) => (pos[concepts[a]?.module] ?? 1e9) - (pos[concepts[b]?.module] ?? 1e9) || concepts[a].title.localeCompare(concepts[b].title)
  }, [cur])

  const go = (id: string) => {
    setFocus(id); setMode('near'); setPicked(null); setHover(null); setSearch('')
    navigate(`/map?concept=${encodeURIComponent(id)}`, { replace: true })
  }

  const graph = useMemo(() => {
    if (!width) return null
    if (mode === 'near') {
      const around = [...(nb[focus] || [])].sort(order)
      const ns = Object.fromEntries([focus, ...around].filter(id => sizes[id]).map(id => [id, sizes[id]]))
      const l = neighbourhoodLayout(focus, around, ns, width)
      // links between neighbours help on a ring; in the narrow two-column layout they would loop round everything
      const pairs = [...around.map(id => [focus, id] as [string, string]), ...(width < 600 ? [] : links.filter(([a, b]) => a !== focus && b !== focus && l.boxes[a] && l.boxes[b]))]
      if (width < 600) return { ids: [focus, ...around], boxes: l.boxes, heads: [] as { id: string; box: Box }[], pairs, routes: treeEdges(l.boxes[focus], around.map(id => l.boxes[id])), content: { w: l.width, h: l.height } }
      const r = routeInside(l.boxes, pairs.map(([from, to]) => ({ from, to })), { clearance: 6, pad: 16 })
      return { ids: [focus, ...around], boxes: r.boxes, heads: [] as { id: string; box: Box }[], pairs, routes: r.routes, content: { w: Math.max(l.width, r.w), h: Math.max(l.height, r.h) } }
    }
    const groups = (cur?.tracks || []).map((tr, i) => ({ id: tr.id, items: Object.keys(concepts).filter(id => trackOf[id] === i).sort(order) }))
      .filter(g => track === 'all' || g.id === track)
    const ns = Object.fromEntries(Object.keys(concepts).filter(id => sizes[id]).map(id => [id, sizes[id]]))
    const l = groupedLayout(groups, ns, width, { pad: 16, colW: overviewCol(width), gapX: width < 600 ? 20 : 44, gapY: 10, head: 34, groupGap: 28 })
    const active = picked || hover
    const pairs = active ? links.filter(([a, b]) => (a === active || b === active) && l.boxes[a] && l.boxes[b]) : []
    // the links of the concept under the pointer never move the layout (that would move the box away from the pointer)
    const routes = routeEdges(l.boxes, pairs.map(([from, to]) => ({ from, to })), { clearance: 4, obstacles: l.heads.map(hd => hd.box) })
    return { ids: Object.keys(l.boxes), boxes: l.boxes, heads: l.heads, pairs, routes, content: { w: l.width, h: l.height } }
  }, [width, mode, focus, nb, links, sizes, order, track, picked, hover, cur, trackOf])

  if (!cur) return null
  const squash = (x: string) => x.toLowerCase().replace(/[\s\-_./]+/g, '')
  const words = search.trim() ? search.toLowerCase().split(/\s+/).filter(Boolean) : []
  // every word must appear; spaces and punctuation never matter ("network pol" finds NetworkPolicies)
  const matches = words.length ? Object.values(concepts).filter(c => { const hay = squash(`${c.title} ${c.id}`); return hay.includes(squash(search)) || words.every(w => hay.includes(squash(w))) }).slice(0, 24) : []
  const selected = mode === 'near' ? focus : picked
  const active = mode === 'all' ? picked || hover : focus
  const moduleTitle = (c: Concept) => cur.modules.find(m => m.id === c.module)?.title || c.module
  const trackTitle = (id: string) => cur.tracks[trackOf[id]]?.title || ''

  const details = selected && concepts[selected] ? (() => {
    const c = concepts[selected], e = evidence[c.id]
    const lessons = Object.values(cur.lessons).filter(l => l.concepts.includes(c.id)), labs = Object.values(cur.labs).filter(l => l.concepts.includes(c.id))
    return <div className="fd-pop km-details" data-testid="km-details">
      <div className="fd-pop-h"><strong>{c.title}</strong><small>{trackTitle(c.id)} · {moduleTitle(c)}</small></div>
      <p>Reading: {e.read}/{e.lessons} lessons. Checks: {e.checksCorrect}/{e.checks} correct on latest recorded attempts ({e.checksAnswered} answered).</p>
      <p>Practice completed: {e.practised}/{e.labs}. Verified on a cluster: {e.verified}. These are separate achievements.</p>
      {mode === 'all' && <p><button className="btn sm" onClick={() => go(c.id)}>Explore its neighbourhood</button></p>}
      {(lessons.length > 0 || labs.length > 0) && <div className="km-links">
        {lessons.map(l => <a key={l.id} href={lessonHref(l.id)}>{l.title}</a>)}
        {labs.map(l => <a key={l.id} href={labHref(l.id)}>{l.kind === 'incident' ? 'Solve' : 'Practise'}: {l.title}</a>)}
      </div>}
      {(nb[c.id] || []).length > 0 && <><p className="km-related-h">{t('km.related')}</p>
        <div className="km-related">{[...nb[c.id]].sort(order).map(id => <button key={id} className="chip" onClick={() => go(id)}>{concepts[id].title}</button>)}</div></>}
    </div>
  })() : null

  const textVersion = mode === 'near'
    ? <ul className="graph-list km-text">{(graph?.ids || [focus]).map(id => <li key={id}>
        <button className="graph-list-node" aria-pressed={id === focus} onClick={() => go(id)}>{concepts[id]?.title}</button>
        <p>{LEVEL[evidenceLevel(evidence[id])]} · {trackTitle(id)}</p>
      </li>)}</ul>
    : <div className="graph-list km-text">{cur.tracks.map((tr, i) => {
        const ids = Object.keys(concepts).filter(id => trackOf[id] === i).sort(order)
        return ids.length > 0 && (track === 'all' || track === tr.id) ? <section key={tr.id}><h3>{tr.title}</h3><ul>{ids.map(id => <li key={id}>
          <button className="graph-list-node" onClick={() => go(id)}>{concepts[id].title}</button> <small>{LEVEL[evidenceLevel(evidence[id])]}</small></li>)}</ul></section> : null
      })}</div>

  const nodeWidth = mode === 'near' ? neighbourWidth(width) : overviewCol(width)
  const title = mode === 'near' ? `${concepts[focus]?.title || 'Concept'} and the ${(nb[focus] || []).length} concepts related to it` : `All ${(graph ? Object.keys(graph.boxes) : Object.keys(concepts)).length} concepts${track !== 'all' ? ` · ${cur.tracks.find(tr => tr.id === track)?.title}` : ''}`

  return <div className="page kmap xp">
    {/* no Report or Edit on the map: it organises the course; the lessons and models it links to have their own */}
    <PageHead eyebrow={t('nav.explore')} title={t('km.title')} lede={t('xp.kmLede')} />
    <div className="xp-filters">
      <div className="search-in">
        <Icon name="search" size={16} />
        <input id="concept-search" type="search" value={search} onChange={e => setSearch(e.target.value)} aria-label={t('xp.kmSearch')} placeholder={t('xp.kmPlaceholder')}
          onKeyDown={e => { if (e.key === 'Enter' && matches[0]) go(matches[0].id) }} />
      </div>
      <div className="chips" role="group" aria-label={t('xp.kmScope')}>
        <button className={`chip ${mode === 'near' ? 'on' : ''}`} aria-pressed={mode === 'near'} onClick={() => { setMode('near'); setPicked(null) }}>{t('xp.kmNeighbourhood')}</button>
        <button className={`chip ${mode === 'all' ? 'on' : ''}`} aria-pressed={mode === 'all'} onClick={() => { setMode('all'); setTrack('all'); setPicked(null) }}>{t('km.all')}</button>
      </div>
    </div>
    {search.trim() && <div className="graph-map-results" role="group" aria-label="Concept search results">
      {matches.length ? matches.map(c => <button key={c.id} className="chip" onClick={() => go(c.id)}>{c.title}</button>) : <p>No matching concepts.</p>}
    </div>}
    {mode === 'all' && <div className="xp-scope" role="group" aria-label={t('km.focus')}>
      <span className="xp-scope-label">{t('xp.kmTerritory')}</span>
      {cur.tracks.filter((_, i) => Object.values(trackOf).includes(i)).map(tr => <button key={tr.id} className={`chip ${track === tr.id ? 'on' : ''}`} aria-pressed={track === tr.id}
        onClick={() => { setTrack(track === tr.id ? 'all' : tr.id); setPicked(null) }}>{tr.title}</button>)}
    </div>}
    <div ref={wrap} className="km-wrap">
      {graph && <GraphViewport title={title} label={t('km.title')} content={graph.content} resetKey={`${mode}:${mode === 'near' ? focus : track}`} maxHeight={100000}
        textVersion={textVersion} details={details} onCloseDetails={mode === 'all' && picked ? () => setPicked(null) : undefined}
        keepVisible={mode === 'all' && picked ? graph.boxes[picked] : null}
        help={mode === 'near' ? 'Select a related concept to move to it.' : 'Point at or select a concept to see its links.'}>
        <div className={`graph-content km-${mode}`}>
          {graph.heads.map(({ id, box: b }, k) => { const i = cur.tracks.findIndex(tr => tr.id === id), again = graph.heads.findIndex(h => h.id === id) < k, tr = cur.tracks[i]
            // the layout leaves one line for a heading: the short name, never wrapped (a second line would cover the first box)
            return <div key={`${id}-${k}`} className="km-head" data-track={i} title={`${tr?.title}${again ? ' (continued)' : ''}`}
              style={{ left: b.x, top: b.y, width: b.w, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{tr?.short || tr?.title}{again && <span className="km-cont"> (continued)</span>}</div> })}
          <svg className="fd-edges" width={graph.content.w} height={graph.content.h} aria-hidden="true">
            {graph.routes.map((r, i) => r && <path key={graph.pairs[i].join('|')} d={r.d} data-from={graph.pairs[i][0]} data-to={graph.pairs[i][1]} className={`fd-edge km-edge ${graph.pairs[i].includes(active || '') ? 'hl' : 'faint'}`} />)}
          </svg>
          {graph.ids.map(id => { const b = graph.boxes[id], lvl = evidenceLevel(evidence[id]); return <button key={id} ref={measure(id)} data-node-id={id} data-track={trackOf[id]}
            className={`fd-node km-node ${id === selected ? 'on' : ''} ${id === focus && mode === 'near' ? 'km-focus' : ''} ${mode === 'all' && active && id !== active && !(nb[active] || []).includes(id) ? 'dim' : ''}`}
            style={{ left: b.x, top: b.y, width: nodeWidth }} aria-pressed={id === selected}
            onMouseEnter={() => mode === 'all' && setHover(id)} onMouseLeave={() => mode === 'all' && setHover(h => h === id ? null : h)}
            onClick={() => mode === 'near' ? (id !== focus && go(id)) : setPicked(picked === id ? null : id)}>
            <strong>{concepts[id].title}</strong>
            <small className={`km-ev ${lvl}`}><span className="km-dot" aria-hidden="true" />{LEVEL[lvl]}</small>
          </button> })}
        </div>
      </GraphViewport>}
    </div>
    <p className="km-legend" aria-label="Legend">
      {(['none', 'read', 'checked', 'practised', 'verified'] as EvidenceLevel[]).map(l => <span key={l} className={`km-ev ${l}`}><span className="km-dot" aria-hidden="true" />{LEVEL[l]}</span>)}
      <span className="km-legend-note">Lines join related concepts. A concept's territory is named in its details, and Everything groups the concepts by territory.</span>
    </p>
  </div>
}
