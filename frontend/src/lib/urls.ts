// Public addresses. The server gives every track, lesson, lab and diagnostic a readable address (`path`, built by
// backend/academy/urls.py from the slugs stored in content/en/urls.yaml):
//   /learn/<track>, /learn/<track>/<lesson>, /diagnostic/<track>, /labs/<lab>, /incidents/<lab>, /challenges/<lab>
// Ids stay internal: progress, recordings and links written in content use them. Older addresses still work:
// canonical() turns /lesson/<id>, /lab/<id>, /learn/<track id>, /course[/<track id>] and /diagnostic/<track id> into
// the current address, keeping the query and the #anchor. The router applies it to every navigation (lib/router.ts),
// the Markdown renderer to every link written in content (lib/md.tsx).
import type { Curriculum } from './data'

export type Ref = { kind: 'lesson' | 'lab' | 'track' | 'diagnostic'; id: string }
type Source = Pick<Curriculum, 'tracks' | 'lessons' | 'labs' | 'diagnostics'>
type Index = {
  lessons: Map<string, string>
  labs: Map<string, string>
  tracks: Map<string, string>
  diagnostics: Map<string, string>
  at: Map<string, Ref> // current address -> what is there
  lessonSlugs: Map<string, string> // a lesson's slug -> its id (a lesson moved to another track keeps its slug)
  moved: Map<string, string> // old address -> current address
}

let index: Index = build(null)

/** Learn the addresses of a loaded curriculum (called before the app renders it, see lib/app.tsx). */
export function setAddresses(cur: Source | null) {
  index = build(cur)
}

function build(cur: Source | null): Index {
  const ix: Index = { lessons: new Map(), labs: new Map(), tracks: new Map(), diagnostics: new Map(), at: new Map(), lessonSlugs: new Map(), moved: new Map() }
  if (!cur) return ix
  const add = (map: Map<string, string>, kind: Ref['kind'], id: string, path: string | undefined) => {
    if (!path) return
    map.set(id, path)
    ix.at.set(path, { kind, id })
  }
  for (const tr of cur.tracks) add(ix.tracks, 'track', tr.id, tr.path)
  for (const l of Object.values(cur.lessons)) {
    add(ix.lessons, 'lesson', l.id, l.path)
    if (l.path) ix.lessonSlugs.set(l.path.split('/').pop()!, l.id)
  }
  for (const l of Object.values(cur.labs)) add(ix.labs, 'lab', l.id, l.path)
  for (const d of Object.values(cur.diagnostics || {})) add(ix.diagnostics, 'diagnostic', d.track, d.path)
  // the addresses used before readable URLs (the static export writes a page at each: scripts/export_static.py)
  const old: [string, string | undefined][] = [['/course', '/learn']]
  for (const [id, p] of ix.lessons) old.push([`/lesson/${id}`, p])
  for (const [id, p] of ix.labs) old.push([`/lab/${id}`, p])
  for (const [id, p] of ix.tracks) old.push([`/learn/${id}`, p], [`/course/${id}`, p])
  for (const [id, p] of ix.diagnostics) old.push([`/diagnostic/${id}`, p])
  for (const [from, to] of old) if (to && from !== to) ix.moved.set(from, to)
  return ix
}

/** The setup guide, or one of its sections: a tool id from content/en/tools.yaml, or `cluster`. */
export const setupHref = (part?: string) => (part ? `/setup#${part}` : '/setup')
export const lessonHref = (id: string) => index.lessons.get(id) ?? `/lesson/${id}`
export const labHref = (id: string) => index.labs.get(id) ?? `/lab/${id}`
export const trackHref = (id: string) => index.tracks.get(id) ?? `/learn/${id}`
export const diagnosticHref = (track: string) => index.diagnostics.get(track) ?? `/diagnostic/${track}`
/** A diagnostic's target or a review card's source: a lesson when one has this id, else a lab. */
export const itemHref = (id: string) => (index.lessons.has(id) ? lessonHref(id) : labHref(id))

const split = (href: string) => {
  const m = /^([^?#]*)([\s\S]*)$/.exec(href)!
  return { path: m[1].replace(/(.)\/+$/, '$1'), rest: m[2] }
}

/** The current address for `href` (an old one is replaced, its query and #anchor kept); anything else unchanged. */
export function canonical(href: string): string {
  if (!href.startsWith('/') || href.startsWith('//')) return href
  const { path, rest } = split(href)
  let to = index.moved.get(path)
  if (!to) {
    // a lesson under another track's address (it moved between tracks): its slug still names it
    const m = /^\/learn\/[^/]+\/([^/]+)$/.exec(path)
    const id = m && !index.at.has(path) ? index.lessonSlugs.get(m[1]) : undefined
    if (id) to = index.lessons.get(id)
  }
  return to ? to + rest : href
}

/** What a current address shows (no query or #anchor; a trailing slash is ignored), or null. */
export function resolve(path: string): Ref | null {
  return index.at.get(split(path).path) || null
}

/** The lesson or lab an address names, current or old, with or without query and #anchor (saved "continue" places
 *  and ?from= links may predate readable addresses). */
export function refOf(href: string): Ref | null {
  const { path } = split(canonical(href))
  const hit = index.at.get(path)
  if (hit) return hit
  const m = /^\/(lesson|lab)\/([^/]+)$/.exec(path) // addresses not loaded (yet): the old form still names an id
  return m ? { kind: m[1] as 'lesson' | 'lab', id: m[2] } : null
}

/** A detail page (a lesson, a lab) by the shape of its address alone, so the page chrome is right before content loads. */
export function detailKind(path: string): 'lesson' | 'lab' | null {
  const p = split(path).path
  if (/^\/learn\/[^/]+\/[^/]+$/.test(p) || /^\/lesson\/[^/]+$/.test(p)) return 'lesson'
  if (/^\/(labs|incidents|challenges|lab)\/[^/]+$/.test(p)) return 'lab'
  return null
}
