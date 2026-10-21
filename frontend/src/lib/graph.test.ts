import { describe, expect, it } from 'vitest'
import { DIAGRAMS } from './diagrams'
import { treeEdges, clampView, fit, gridLayout, groupedLayout, neighbourWidth, neighbourhoodLayout, overlaps, placeLabels, reveal, routeEdges, segmentHits, sides, union, wordParts, zoomAt, type Box } from './graph'

const noOverlap = (bs: Box[], gap = 0) => bs.every((a, i) => bs.every((b, j) => i >= j || !overlaps(a, b, gap - .01)))

describe('viewport arithmetic', () => {
  it('fits, never above 100%, centred', () => {
    expect(fit({ w: 400, h: 200 }, 1000, 600)).toEqual({ s: 1, x: 300, y: 200 })
    const v = fit({ w: 2000, h: 500 }, 1032, 600)
    expect(v.s).toBeCloseTo(.5); expect(v.x).toBeCloseTo(16)
  })
  it('zooms around the pointer', () => {
    const v = zoomAt({ s: 1, x: 0, y: 0 }, 2, 100, 50)
    expect(v).toEqual({ s: 2, x: -100, y: -50 }) // content point (100, 50) stays under the pointer
  })
  it('never loses the content and reveals a box with the smallest move', () => {
    expect(clampView({ s: 1, x: -5000, y: 9000 }, { w: 800, h: 400 }, 600, 300)).toEqual({ s: 1, x: -752, y: 252 })
    expect(reveal({ s: 1, x: 0, y: 0 }, { x: 20, y: 20, w: 50, h: 50 }, 600, 300)).toEqual({ s: 1, x: 0, y: 0 })
    expect(reveal({ s: 1, x: 0, y: 0 }, { x: 700, y: 10, w: 50, h: 50 }, 600, 300).x).toBe(-166)
  })
})

describe('edges', () => {
  it('choose facing sides', () => {
    expect(sides({ x: 0, y: 0, w: 100, h: 50 }, { x: 200, y: 0, w: 100, h: 50 })).toEqual(['r', 'l'])
    expect(sides({ x: 0, y: 200, w: 100, h: 50 }, { x: 0, y: 0, w: 100, h: 50 })).toEqual(['t', 'b'])
  })
  it('clip segments against boxes', () => {
    expect(segmentHits({ x: 0, y: 25 }, { x: 300, y: 25 }, { x: 100, y: 0, w: 50, h: 50 })).toBe(true)
    expect(segmentHits({ x: 0, y: 80 }, { x: 300, y: 80 }, { x: 100, y: 0, w: 50, h: 50 })).toBe(false)
  })
  it('are straight when clear and bend round a box in the way', () => {
    const boxes = { a: { x: 0, y: 0, w: 100, h: 50 }, b: { x: 0, y: 100, w: 100, h: 50 }, c: { x: 0, y: 200, w: 100, h: 50 } }
    const [ab, ac] = routeEdges(boxes, [{ from: 'a', to: 'b' }, { from: 'a', to: 'c' }])
    expect(ab!.d).toMatch(/^M[\d.,]+ L/)
    expect(ac!.d).toContain(' C')
    for (let i = 1; i < ac!.samples.length; i++) expect(segmentHits(ac!.samples[i - 1], ac!.samples[i], boxes.b)).toBe(false)
  })
  it('spread several edges on one side instead of sharing an anchor', () => {
    const boxes = { api: { x: 200, y: 0, w: 160, h: 60 }, x: { x: 0, y: 200, w: 160, h: 60 }, y: { x: 200, y: 200, w: 160, h: 60 }, z: { x: 400, y: 200, w: 160, h: 60 } }
    const r = routeEdges(boxes, ['x', 'y', 'z'].map(id => ({ from: id, to: 'api' })))
    const ends = r.map(e => e!.to.x)
    expect(new Set(ends).size).toBe(3)
    expect(ends).toEqual([...ends].sort((p, q) => p - q))
  })
})

describe('Studio diagrams', () => {
  const u = 16
  for (const d of DIAGRAMS) it(`${d.id}: boxes apart, edges and labels clear of boxes`, () => {
    const zoned = !!d.zones?.length
    const sizes = Object.fromEntries(d.nodes.map(n => [n.id, { w: 160 * (n.span || 1) + 88 * ((n.span || 1) - 1), h: 72 }]))
    const l = gridLayout(Object.fromEntries(d.nodes.map(n => [n.id, n])), sizes, { gapX: u * 5.5, gapY: u * (zoned ? 4.5 : 3.5), pad: u * 1.5, top: u * (zoned ? 3 : 1.5), colWidth: u * 10, rowHeight: u * 4 })
    const boxes = Object.values(l.boxes)
    expect(noOverlap(boxes, 16)).toBe(true)
    const routes = routeEdges(l.boxes, d.edges, { clearance: u / 2 })
    routes.forEach((r, i) => {
      expect(r, d.edges[i].from + '→' + d.edges[i].to).not.toBeNull()
      const others = d.nodes.filter(n => n.id !== d.edges[i].from && n.id !== d.edges[i].to).map(n => l.boxes[n.id])
      for (let k = 1; k < r!.samples.length; k++) for (const o of others) expect(segmentHits(r!.samples[k - 1], r!.samples[k], o), `${d.id} ${d.edges[i].from}→${d.edges[i].to}`).toBe(false)
    })
    const labels = placeLabels(routes, d.edges.map(e => e.label ? { w: 80, h: 22 } : null), boxes).filter((b): b is Box => !!b)
    expect(labels.every(lb => !boxes.some(b => overlaps(lb, b)))).toBe(true)
  })
})

describe('knowledge map layouts', () => {
  const sizes = (ids: string[], w: number) => Object.fromEntries(ids.map((id, i) => [id, { w, h: 56 + (i % 3) * 18 }]))
  for (const n of [1, 2, 3, 5, 7, 10]) for (const width of [360, 1046]) it(`${n} neighbours at ${width}px do not overlap and fit the width when narrow`, () => {
    const around = Array.from({ length: n }, (_, i) => `c${i}`), w = neighbourWidth(width)
    const l = neighbourhoodLayout('focus', around, sizes(['focus', ...around], w), width)
    const bs = Object.values(l.boxes)
    expect(bs).toHaveLength(n + 1)
    expect(noOverlap(bs, 12)).toBe(true)
    if (width < 600) expect(union(bs).x + union(bs).w).toBeLessThanOrEqual(width)
  })
  it('groups fill as many columns as the width allows, without overlap', () => {
    const groups = [{ id: 'a', items: ['a1', 'a2', 'a3'] }, { id: 'b', items: ['b1'] }, { id: 'c', items: ['c1', 'c2'] }]
    const all = groups.flatMap(g => g.items)
    const wide = groupedLayout(groups, sizes(all, 184), 1000), narrow = groupedLayout(groups, sizes(all, 184), 360)
    expect(noOverlap([...Object.values(wide.boxes), ...wide.heads.map(h => h.box)])).toBe(true)
    expect(new Set(Object.values(wide.boxes).map(b => b.x)).size).toBeGreaterThan(1)
    expect(new Set(Object.values(narrow.boxes).map(b => b.x)).size).toBe(1)
    expect(narrow.width).toBeLessThanOrEqual(360)
  })
  it('balances columns: a long group continues under the same heading', () => {
    const groups = [{ id: 'long', items: Array.from({ length: 30 }, (_, i) => `l${i}`) }, { id: 'short', items: ['s1', 's2'] }]
    const l = groupedLayout(groups, {}, 1000)
    const xs = new Set(Object.values(l.boxes).map(b => b.x))
    expect(xs.size).toBe(4)
    expect(l.heads.filter(h => h.id === 'long').length).toBeGreaterThan(1)
    expect(l.height).toBeLessThan(30 * 54 / 2)
  })
})

describe('narrow neighbourhood links', () => {
  for (const width of [300, 420]) it(`never cross a box at ${width}px`, () => {
    const around = Array.from({ length: 7 }, (_, i) => `c${i}`), w = neighbourWidth(width)
    const l = neighbourhoodLayout('f', around, Object.fromEntries(['f', ...around].map(id => [id, { w, h: 60 }])), width)
    const edges = treeEdges(l.boxes.f, around.map(id => l.boxes[id]))
    edges.forEach((e, k) => {
      for (let i = 1; i < e.samples.length; i++) for (const [id, b] of Object.entries(l.boxes)) if (id !== around[k] && id !== 'f') expect(segmentHits(e.samples[i - 1], e.samples[i], b)).toBe(false)
      expect(e.samples.every(p => p.x >= 0 && p.x <= width)).toBe(true)
    })
  })
})

describe('wordParts', () => {
  it('splits CamelCase names between their words only', () => {
    expect(wordParts('ClusterRoleBinding')).toEqual(['Cluster', 'Role', 'Binding'])
    expect(wordParts('Role / ClusterRole')).toEqual(['Role / Cluster', 'Role'])
    expect(wordParts('kube-apiserver')).toEqual(['kube-apiserver'])
    expect(wordParts('PVC (claim)')).toEqual(['PVC (claim)'])
    expect(wordParts('EndpointSlices').join('')).toBe('EndpointSlices')
  })
})
