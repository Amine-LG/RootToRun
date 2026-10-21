// Graph geometry shared by the Studio diagrams and the knowledge map: viewport arithmetic, layouts, and edges that
// connect box borders and bend around other boxes. Pure functions only, so every rule here is unit-tested.

export type Point = { x: number; y: number }
export type Box = { x: number; y: number; w: number; h: number }
export type View = { s: number; x: number; y: number }
export type Side = 'l' | 'r' | 't' | 'b'
export type EdgeIn = { from: string; to: string }
export type EdgeOut = { d: string; from: Point; to: Point; mid: Point; samples: Point[] }

export const center = (b: Box): Point => ({ x: b.x + b.w / 2, y: b.y + b.h / 2 })
export const inflate = (b: Box, by: number): Box => ({ x: b.x - by, y: b.y - by, w: b.w + by * 2, h: b.h + by * 2 })
export const overlaps = (a: Box, b: Box, gap = 0) => a.x < b.x + b.w + gap && a.x + a.w + gap > b.x && a.y < b.y + b.h + gap && a.y + a.h + gap > b.y
export function union(boxes: Box[]): Box {
  if (!boxes.length) return { x: 0, y: 0, w: 0, h: 0 }
  const x = Math.min(...boxes.map(b => b.x)), y = Math.min(...boxes.map(b => b.y))
  return { x, y, w: Math.max(...boxes.map(b => b.x + b.w)) - x, h: Math.max(...boxes.map(b => b.y + b.h)) - y }
}

// ---------------------------------------------------------------- viewport

/** The largest scale (never above `max`) at which the whole content fits, centred. */
export function fit(content: { w: number; h: number }, w: number, h: number, pad = 16, max = 1): View {
  const s = Math.max(.05, Math.min(max, (w - pad * 2) / Math.max(1, content.w), (h - pad * 2) / Math.max(1, content.h)))
  return { s, x: (w - content.w * s) / 2, y: (h - content.h * s) / 2 }
}
/** Zoom to scale `s` keeping the content point under (px, py) where it is. */
export function zoomAt(v: View, s: number, px: number, py: number): View {
  const k = s / v.s
  return { s, x: px - (px - v.x) * k, y: py - (py - v.y) * k }
}
/** Never lose the content: at least `keep` pixels of it stay inside the viewport on each axis. */
export function clampView(v: View, content: { w: number; h: number }, w: number, h: number, keep = 48): View {
  const cw = content.w * v.s, ch = content.h * v.s, kx = Math.min(keep, cw), ky = Math.min(keep, ch)
  return { s: v.s, x: Math.min(w - kx, Math.max(kx - cw, v.x)), y: Math.min(h - ky, Math.max(ky - ch, v.y)) }
}
/** Pan as little as possible so that box b (content coordinates) is inside the viewport. */
export function reveal(v: View, b: Box, w: number, h: number, margin = 16): View {
  const left = v.x + b.x * v.s, right = v.x + (b.x + b.w) * v.s, top = v.y + b.y * v.s, bottom = v.y + (b.y + b.h) * v.s
  let x = v.x, y = v.y
  if (right > w - margin) x -= right - (w - margin)
  if (left + (x - v.x) < margin) x += margin - (left + (x - v.x))
  if (bottom > h - margin) y -= bottom - (h - margin)
  if (top + (y - v.y) < margin) y += margin - (top + (y - v.y))
  return { s: v.s, x, y }
}
/** One wheel notch (or the equivalent trackpad distance) zooms by about 20%. */
export const wheelZoom = (deltaY: number, deltaMode: number) => Math.pow(2, -deltaY * (deltaMode === 1 ? .05 : deltaMode === 2 ? 1 : .0025))

// ---------------------------------------------------------------- edges

/** Which sides of a and b an edge between them should leave from and arrive at. */
export function sides(a: Box, b: Box): [Side, Side] {
  const ca = center(a), cb = center(b), dx = cb.x - ca.x, dy = cb.y - ca.y
  const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x), oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y)
  const horizontal = oy > Math.min(a.h, b.h) * .3 ? true : ox > Math.min(a.w, b.w) * .3 ? false
    : Math.abs(dx) / ((a.w + b.w) / 2) > Math.abs(dy) / ((a.h + b.h) / 2)
  return horizontal ? (dx >= 0 ? ['r', 'l'] : ['l', 'r']) : (dy >= 0 ? ['b', 't'] : ['t', 'b'])
}
const normal: Record<Side, Point> = { l: { x: -1, y: 0 }, r: { x: 1, y: 0 }, t: { x: 0, y: -1 }, b: { x: 0, y: 1 } }
function sidePoint(b: Box, side: Side, f: number): Point {
  return side === 'l' ? { x: b.x, y: b.y + b.h * f } : side === 'r' ? { x: b.x + b.w, y: b.y + b.h * f } : side === 't' ? { x: b.x + b.w * f, y: b.y } : { x: b.x + b.w * f, y: b.y + b.h }
}
/** Does the segment p-q pass through the inside of box r? (Liang–Barsky clipping) */
export function segmentHits(p: Point, q: Point, r: Box): boolean {
  let t0 = 0, t1 = 1
  const dx = q.x - p.x, dy = q.y - p.y
  for (const [pp, qq] of [[-dx, p.x - r.x], [dx, r.x + r.w - p.x], [-dy, p.y - r.y], [dy, r.y + r.h - p.y]]) {
    if (pp === 0) { if (qq <= 0) return false; continue }
    const t = qq / pp
    if (pp < 0) { if (t > t1) return false; if (t > t0) t0 = t } else { if (t < t0) return false; if (t < t1) t1 = t }
  }
  return t1 - t0 > 1e-6
}
const cubic = (p0: Point, c1: Point, c2: Point, p1: Point, t: number): Point => {
  const u = 1 - t
  return { x: u * u * u * p0.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * p1.x, y: u * u * u * p0.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * p1.y }
}
const hits = (ps: Point[], obstacles: Box[]) => {
  let n = 0
  for (let i = 1; i < ps.length; i++) for (const o of obstacles) if (segmentHits(ps[i - 1], ps[i], o)) n++
  return n
}
const r1 = (n: number) => Math.round(n * 10) / 10

/**
 * Edges from border to border. Several edges on one side of a box are spread along it in the order of their other
 * ends, so they never share an anchor. An edge is straight when that line is clear of every other box; otherwise it
 * is a curve that leaves and enters perpendicular to the box sides and bends round the obstacles.
 */
export function routeEdges(boxes: Record<string, Box>, edges: EdgeIn[], opts: { clearance?: number; obstacles?: Box[]; straight?: boolean } = {}): (EdgeOut | null)[] {
  const clearance = opts.clearance ?? 8
  const valid = (e: EdgeIn) => !!boxes[e.from] && !!boxes[e.to] && e.from !== e.to
  const othersOf = (e: EdgeIn) => [...Object.entries(boxes).filter(([id]) => id !== e.from && id !== e.to).map(([, bx]) => inflate(bx, clearance)), ...(opts.obstacles || [])]
  // sides: the facing pair, unless no curve between them is clear and another pair is
  const ALL: Side[] = ['l', 'r', 't', 'b']
  const chosen = edges.map(e => {
    if (!valid(e)) return null
    const a = boxes[e.from], b = boxes[e.to], first = sides(a, b), others = othersOf(e)
    if (opts.straight || connect(sidePoint(a, first[0], .5), sidePoint(b, first[1], .5), first, others).hits === 0) return first
    const pairs = ALL.flatMap(x => ALL.map(y => [x, y] as [Side, Side])).filter(([x, y]) => x !== first[0] || y !== first[1])
      .map(pair => ({ pair, r: connect(sidePoint(a, pair[0], .5), sidePoint(b, pair[1], .5), pair, others) }))
      .filter(c => c.r.hits === 0).sort((p, q) => p.r.length - q.r.length)
    return pairs[0]?.pair || first
  })
  // spread the anchors of every (box, side) pair in the order of the other ends
  const slots = new Map<string, { i: number; end: 0 | 1; along: number }[]>()
  edges.forEach((e, i) => {
    const s = chosen[i]; if (!s) return
    ;([[e.from, s[0], e.to, 0], [e.to, s[1], e.from, 1]] as const).forEach(([id, side, other, end]) => {
      const c = center(boxes[other]), key = `${id}|${side}`
      if (!slots.has(key)) slots.set(key, [])
      slots.get(key)!.push({ i, end, along: side === 'l' || side === 'r' ? c.y : c.x })
    })
  })
  const anchor = new Map<string, number>()
  slots.forEach(list => {
    list.sort((a, b) => a.along - b.along || a.i - b.i)
    list.forEach((s, k) => anchor.set(`${s.i}|${s.end}`, list.length === 1 ? .5 : .2 + .6 * k / (list.length - 1)))
  })
  return edges.map((e, i) => {
    const s = chosen[i]; if (!s) return null
    const p0 = sidePoint(boxes[e.from], s[0], anchor.get(`${i}|0`) ?? .5), p1 = sidePoint(boxes[e.to], s[1], anchor.get(`${i}|1`) ?? .5)
    const others = othersOf(e)
    if (opts.straight || !others.some(o => segmentHits(p0, p1, o))) {
      return { d: `M${r1(p0.x)},${r1(p0.y)} L${r1(p1.x)},${r1(p1.y)}`, from: p0, to: p1, mid: { x: (p0.x + p1.x) / 2, y: (p0.y + p1.y) / 2 }, samples: [p0, p1] }
    }
    const { c1, c2, ps } = connect(p0, p1, s, others)
    return { d: `M${r1(p0.x)},${r1(p0.y)} C${r1(c1.x)},${r1(c1.y)} ${r1(c2.x)},${r1(c2.y)} ${r1(p1.x)},${r1(p1.y)}`, from: p0, to: p1, mid: ps[12], samples: ps }
  })
}

/** A curve leaving and entering perpendicular to the sides, bent sideways as little as possible to clear obstacles. */
function connect(p0: Point, p1: Point, s: [Side, Side], others: Box[]) {
  if (!others.some(o => segmentHits(p0, p1, o))) return { c1: p0, c2: p1, ps: [p0, p1], hits: 0, length: Math.hypot(p1.x - p0.x, p1.y - p0.y) }
  const dist = Math.hypot(p1.x - p0.x, p1.y - p0.y), reach = Math.max(32, Math.min(160, dist / 2.2))
  const n0 = normal[s[0]], n1 = normal[s[1]], len = Math.max(1, dist), perp = { x: -(p1.y - p0.y) / len, y: (p1.x - p0.x) / len }
  let best: { c1: Point; c2: Point; ps: Point[]; hits: number; length: number; cost: number } | null = null
  for (const k of [0, 50, -50, 100, -100, 160, -160, 230, -230, 320, -320]) {
    const c1 = { x: p0.x + n0.x * reach + perp.x * k, y: p0.y + n0.y * reach + perp.y * k }
    const c2 = { x: p1.x + n1.x * reach + perp.x * k, y: p1.y + n1.y * reach + perp.y * k }
    const ps = Array.from({ length: 25 }, (_, t) => cubic(p0, c1, c2, p1, t / 24))
    const n = hits(ps, others), length = ps.slice(1).reduce((sum, p, j) => sum + Math.hypot(p.x - ps[j].x, p.y - ps[j].y), 0)
    if (!best || n * 1e5 + length < best.cost) best = { c1, c2, ps, hits: n, length, cost: n * 1e5 + length }
    if (n === 0) break
  }
  return best!
}

/** Place each label on its own edge, at the first position (middle first) that covers no box and no earlier label. */
export function placeLabels(routes: (EdgeOut | null)[], sizes: ({ w: number; h: number } | null)[], boxes: Box[]): (Box | null)[] {
  const placed: Box[] = []
  return routes.map((r, i) => {
    const size = sizes[i]
    if (!r || !size) return null
    const n = r.samples.length - 1
    const at = (f: number): Point => {
      if (n === 1) return { x: r.samples[0].x + (r.samples[1].x - r.samples[0].x) * f, y: r.samples[0].y + (r.samples[1].y - r.samples[0].y) * f }
      return r.samples[Math.round(f * n)]
    }
    const candidates = [.5, .42, .58, .34, .66, .26, .74].flatMap(f => {
      const p = at(f), q = at(Math.min(1, f + .05)), o = at(Math.max(0, f - .05)), horizontal = Math.abs(q.x - o.x) >= Math.abs(q.y - o.y)
      const on = { x: p.x - size.w / 2, y: p.y - size.h / 2, w: size.w, h: size.h }
      // beside the line when it is too short or too crowded to carry the label on top of it
      const dx = horizontal ? 0 : size.w / 2 + 6, dy = horizontal ? size.h / 2 + 6 : 0
      return [on, { ...on, x: on.x - dx, y: on.y - dy }, { ...on, x: on.x + dx, y: on.y + dy }]
    })
    const spot = candidates.find(c => !boxes.some(b => overlaps(c, b, 2)) && !placed.some(b => overlaps(c, b, 2))) || candidates[0]
    placed.push(spot)
    return spot
  })
}

// ---------------------------------------------------------------- layouts

export type Grid = { col: number; row: number; span?: number }
/** Authored grid positions; every row is as tall as its tallest measured box, every column as wide as its widest. */
export function gridLayout(items: Record<string, Grid>, sizes: Record<string, { w: number; h: number }>, opts: { gapX: number; gapY: number; pad: number; top?: number; colWidth: number; rowHeight: number }) {
  const ids = Object.keys(items)
  const ncols = Math.max(1, ...ids.map(id => items[id].col + (items[id].span || 1))), nrows = Math.max(1, ...ids.map(id => items[id].row + 1))
  const size = (id: string) => sizes[id] || { w: opts.colWidth * (items[id].span || 1), h: opts.rowHeight }
  const widths = Array.from({ length: ncols }, (_, c) => Math.max(opts.colWidth, ...ids.filter(id => items[id].col === c && (items[id].span || 1) === 1).map(id => size(id).w)))
  const heights = Array.from({ length: nrows }, (_, r) => Math.max(opts.rowHeight * .5, ...ids.filter(id => items[id].row === r).map(id => size(id).h)))
  const xs: number[] = [], ys: number[] = []
  widths.reduce((x, w) => { xs.push(x); return x + w + opts.gapX }, opts.pad)
  heights.reduce((y, h) => { ys.push(y); return y + h + opts.gapY }, opts.top ?? opts.pad)
  const boxes: Record<string, Box> = {}
  for (const id of ids) {
    const it = items[id], span = it.span || 1, cellW = widths.slice(it.col, it.col + span).reduce((a, b) => a + b, 0) + opts.gapX * (span - 1)
    const { w, h } = size(id)
    boxes[id] = { x: xs[it.col] + Math.max(0, (cellW - w) / 2), y: ys[it.row] + (heights[it.row] - h) / 2, w, h }
  }
  const b = union(Object.values(boxes))
  return { boxes, width: b.x + b.w + opts.pad, height: b.y + b.h + opts.pad }
}

/** Push overlapping boxes apart (the first `fixed` boxes never move), then shift everything to start at (pad, pad). */
export function separate(boxes: Box[], gap: number, pad: number, fixed = 1): Box[] {
  const out = boxes.map(b => ({ ...b }))
  for (let pass = 0; pass < 60; pass++) {
    let moved = false
    for (let i = 0; i < out.length; i++) for (let j = i + 1; j < out.length; j++) {
      const a = out[i], b = out[j]
      if (!overlaps(a, b, gap)) continue
      const ca = center(a), cb = center(b), dx = cb.x - ca.x, dy = cb.y - ca.y
      const px = (a.w + b.w) / 2 + gap - Math.abs(dx), py = (a.h + b.h) / 2 + gap - Math.abs(dy)
      const [mi, mj] = i < fixed ? [0, 1] : j < fixed ? [1, 0] : [.5, .5]
      if (px < py) { const d = (dx >= 0 ? 1 : -1) * px; a.x -= d * mi; b.x += d * mj } else { const d = (dy >= 0 ? 1 : -1) * py; a.y -= d * mi; b.y += d * mj }
      moved = true
    }
    if (!moved) break
  }
  const all = union(out)
  return out.map(b => ({ ...b, x: b.x - all.x + pad, y: b.y - all.y + pad }))
}

const NARROW = 600
/** Width of a concept box in the neighbourhood layout for a given available width (two columns when narrow). */
export const neighbourWidth = (width: number, pad = 24, gap = 20) => width < NARROW ? Math.floor(width < 340 ? width - pad * 2 : (width - pad * 2 - gap) / 2) : 176

/** The selected concept in the middle and its neighbours round it (wide), or below it in two columns (narrow). */
export function neighbourhoodLayout(focus: string, around: string[], sizes: Record<string, { w: number; h: number }>, width: number, opts = { pad: 24, gap: 20 }) {
  const size = (id: string) => sizes[id] || { w: neighbourWidth(width, opts.pad, opts.gap), h: 64 }
  const f = size(focus)
  let boxes: Box[]
  if (width < NARROW) {
    const cols = width < 340 ? 1 : 2, cw = (width - opts.pad * 2 - opts.gap * (cols - 1)) / cols
    boxes = [{ x: (width - f.w) / 2, y: opts.pad, w: f.w, h: f.h }]
    // each row starts below the tallest box of the previous one; the first leaves room for the connecting lines
    let y = opts.pad + f.h + 56
    for (let r = 0; r * cols < around.length; r++) {
      const ids = around.slice(r * cols, r * cols + cols)
      ids.forEach((id, col) => { const s = size(id); boxes.push({ x: opts.pad + col * (cw + opts.gap) + (cw - s.w) / 2, y, w: s.w, h: s.h }) })
      y += Math.max(...ids.map(id => size(id).h)) + opts.gap
    }
    const all = union(boxes)
    return { boxes: Object.fromEntries([focus, ...around].map((id, k) => [id, boxes[k]])), width, height: all.y + all.h + opts.pad }
  }
  const n = Math.max(1, around.length), maxW = Math.max(f.w, ...around.map(id => size(id).w)), maxH = Math.max(f.h, ...around.map(id => size(id).h))
  const rx = Math.max(maxW + opts.gap * 2, (maxW + opts.gap) * n / (2 * Math.PI) * 1.6), ry = Math.max(maxH * 1.9, rx * .5)
  boxes = [{ x: -f.w / 2, y: -f.h / 2, w: f.w, h: f.h }, ...around.map((id, k) => {
    const a = -Math.PI / 2 + (2 * Math.PI * k) / n, s = size(id)
    return { x: Math.cos(a) * rx - s.w / 2, y: Math.sin(a) * ry - s.h / 2, w: s.w, h: s.h }
  })]
  boxes = separate(boxes, opts.gap, opts.pad)
  const all = union(boxes)
  return { boxes: Object.fromEntries([focus, ...around].map((id, k) => [id, boxes[k]])), width: all.x + all.w + opts.pad, height: all.y + all.h + opts.pad }
}

/**
 * Every concept, grouped under headings, read down the columns in order. The columns are balanced: a group that does
 * not fit in what is left of a column continues at the top of the next one under the same heading.
 */
export function groupedLayout(groups: { id: string; items: string[] }[], sizes: Record<string, { w: number; h: number }>, width: number, opts = { pad: 16, colW: 184, gapX: 44, gapY: 10, head: 34, groupGap: 28 }) {
  const cols = Math.max(1, Math.floor((width - opts.pad * 2 + opts.gapX) / (opts.colW + opts.gapX)))
  const h = (id: string) => sizes[id]?.h || 44
  const live = groups.filter(g => g.items.length)
  const total = live.reduce((sum, g) => sum + opts.head + opts.groupGap + g.items.reduce((a, id) => a + h(id) + opts.gapY, 0), 0)
  const target = Math.max(total / cols, ...live.flatMap(g => g.items.map(id => opts.head + h(id))))
  const boxes: Record<string, Box> = {}, heads: { id: string; box: Box }[] = []
  let col = 0, y = opts.pad
  const x = () => opts.pad + col * (opts.colW + opts.gapX)
  for (const g of live) {
    // a heading never ends a column on its own
    if (y > opts.pad && y + opts.head + h(g.items[0]) - opts.pad > target && col < cols - 1) { col++; y = opts.pad }
    heads.push({ id: g.id, box: { x: x(), y, w: opts.colW, h: opts.head - 8 } }); y += opts.head
    g.items.forEach((id, k) => {
      if (k > 0 && y + h(id) - opts.pad > target + 24 && col < cols - 1) {
        col++; y = opts.pad
        heads.push({ id: g.id, box: { x: x(), y, w: opts.colW, h: opts.head - 8 } }); y += opts.head
      }
      boxes[id] = { x: x(), y, w: opts.colW, h: h(id) }; y += h(id) + opts.gapY
    })
    y += opts.groupGap - opts.gapY
  }
  const all = union([...Object.values(boxes), ...heads.map(hd => hd.box)])
  return { boxes, heads, width: all.x + all.w + opts.pad, height: all.y + all.h + opts.pad }
}

/** The extent of boxes and edges, and the shift that keeps all of it at least `pad` inside the canvas. */
export function extent(boxes: Box[], routes: (EdgeOut | null)[], pad: number) {
  const pts = routes.flatMap(r => r ? r.samples.map(p => ({ x: p.x, y: p.y, w: 0, h: 0 })) : [])
  const all = union([...boxes, ...pts])
  const shift = { x: Math.max(0, pad - all.x), y: Math.max(0, pad - all.y) }
  return { shift, w: all.x + all.w + shift.x + pad, h: all.y + all.h + shift.y + pad }
}

/** Route, then move everything right/down if an edge bends outside the canvas (routing is translation-invariant). */
export function routeInside<T extends Record<string, Box>>(boxes: T, edges: EdgeIn[], opts: Parameters<typeof routeEdges>[2] & { pad: number; extra?: Box[] }) {
  let routes = routeEdges(boxes, edges, opts)
  const e = extent([...Object.values(boxes), ...(opts.extra || [])], routes, opts.pad)
  if (!e.shift.x && !e.shift.y) return { boxes, routes, shift: e.shift, w: e.w, h: e.h }
  const move = (b: Box) => ({ ...b, x: b.x + e.shift.x, y: b.y + e.shift.y })
  const moved = Object.fromEntries(Object.entries(boxes).map(([k, b]) => [k, move(b)])) as T
  routes = routeEdges(moved, edges, { ...opts, obstacles: opts.obstacles?.map(move) })
  return { boxes: moved, routes, shift: e.shift, w: e.w, h: e.h }
}

/**
 * Narrow neighbourhood: a trunk from the selected box and a branch to each other box. With two columns the trunk runs
 * down the gutter between them; with one column it runs down the left margin.
 */
export function treeEdges(focus: Box, around: Box[]): EdgeOut[] {
  const mid = focus.x + focus.w / 2, gutter = around.every(b => b.x + b.w <= mid || b.x >= mid)
  const tx = gutter ? mid : Math.min(focus.x, ...around.map(b => b.x)) - 12
  const start = gutter ? { x: tx, y: focus.y + focus.h } : { x: focus.x, y: focus.y + focus.h / 2 }
  return around.map(b => {
    const cy = b.y + b.h / 2, ex = b.x + b.w / 2 < tx ? b.x + b.w : b.x
    const samples = gutter ? [start, { x: tx, y: cy }, { x: ex, y: cy }] : [start, { x: tx, y: start.y }, { x: tx, y: cy }, { x: ex, y: cy }]
    return { d: samples.map((p, i) => `${i ? 'L' : 'M'}${r1(p.x)},${r1(p.y)}`).join(' '), from: start, to: samples[samples.length - 1], mid: samples[1], samples }
  })
}

/** A box label's break points: a long CamelCase name (ClusterRoleBinding) may wrap between its words, never mid-word. */
export const wordParts = (label: string): string[] => label.split(/(?<=[a-z])(?=[A-Z][a-z])/)
