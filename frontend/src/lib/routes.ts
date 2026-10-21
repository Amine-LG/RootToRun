// Routes: recommended journeys across the map (content/en/routes.yaml). A route only orders existing territories
// (tracks) and modules; it never hides or locks anything. Pure functions, unit-tested.
import type { Curriculum, Route } from './data'
import type { Progress } from './progress'
import { activityDone } from './standing'
import { diagnosticHref, labHref, lessonHref, trackHref } from './urls'

const finished = (prog: Progress, id: string) => !!(prog.lessons[id]?.done || prog.lessons[id]?.skipped)

/** The modules a route walks through, in order (a track step expands to its modules). */
export function routeModules(cur: Curriculum, route: Route): string[] {
  const out: string[] = []
  for (const s of route.steps) {
    const tr = cur.tracks.find((t) => t.id === s)
    for (const m of tr ? tr.modules : [s]) if (!out.includes(m) && cur.modules.some((x) => x.id === m)) out.push(m)
  }
  return out
}

/** The lessons of a route, in order (practice modules contribute none). */
export function routeLessons(cur: Curriculum, route: Route): string[] {
  return routeModules(cur, route).flatMap((m) => (cur.modules.find((x) => x.id === m)?.lessons || []).filter((l) => cur.lessons[l]))
}

/** How a territory relates to a route: all of its modules are on it, some are, or none. */
export function territoryOnRoute(cur: Curriculum, route: Route | null | undefined, trackId: string): 'on' | 'part' | 'off' | null {
  if (!route) return null
  const tr = cur.tracks.find((t) => t.id === trackId)
  if (!tr) return 'off'
  const mods = new Set(routeModules(cur, route))
  const n = tr.modules.filter((m) => mods.has(m)).length
  return n === 0 ? 'off' : n === tr.modules.length ? 'on' : 'part'
}

/** The courses (tracks) a course builds directly on, in order, for the "builds on" line of the learning map. The course
 * is a chain (each track assumes the one before it); the practice arena assumes both application tracks. A track the
 * list does not know falls back to the course before it, so a new track is never shown as having no prerequisite. */
const BUILDS_ON: Record<string, string[]> = { linux: [], containers: ['linux'], start: ['containers'], admin1: ['start'], admin2: ['admin1'], platform: ['admin2'], practice: ['admin1', 'admin2'] }
export function buildsOn(cur: Curriculum, trackId: string): string[] {
  const ids = cur.tracks.map((t) => t.id)
  const known = BUILDS_ON[trackId]
  if (known) return known.filter((id) => ids.includes(id))
  const i = ids.indexOf(trackId)
  return i > 0 ? [ids[i - 1]] : []
}

/** The next unfinished lesson on a route, or null when every lesson on it is read or skipped. */
export function nextOnRoute(cur: Curriculum, prog: Progress, route: Route) {
  const id = routeLessons(cur, route).find((l) => !finished(prog, l))
  return id ? cur.lessons[id] : null
}

export function routeProgress(cur: Curriculum, prog: Progress, route: Route) {
  const ls = routeLessons(cur, route)
  return { done: ls.filter((l) => finished(prog, l)).length, total: ls.length, minutes: ls.reduce((n, l) => n + (cur.lessons[l]?.minutes || 0), 0) }
}

export function beginHref(route: Route): string {
  const b = route.begin
  return b.kind === 'lesson' ? lessonHref(b.id) : b.kind === 'diagnostic' ? diagnosticHref(b.id) : b.kind === 'lab' ? labHref(b.id) : trackHref(b.id)
}

/** Whole days since the learner last studied (from the dates progress keeps), or null for a first visit. */
export function daysAway(prog: Progress, now = new Date()): number | null {
  const last = [...prog.days].sort().pop()
  if (!last) return null
  const [y, m, d] = last.split('-').map(Number)
  const then = Date.UTC(y, m - 1, d)
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  return Math.max(0, Math.round((today - then) / 86400000))
}

/** A practice item worth doing next, with the reason: a challenge or incident linked from a lesson the learner has
 * read ("studied"), or else one on the route's practice modules ("route") once the learner has read anything at all.
 * Nothing is suggested to someone who has not studied yet: practice needs its prerequisites. */
export function suggestPractice(cur: Curriculum, prog: Progress, route?: Route | null): { lab: Curriculum['labs'][string]; reason: 'studied' | 'route' } | null {
  const solved = (id: string) => activityDone(cur.labs[id].kind, prog.labs[id])
  const read = Object.keys(prog.lessons).filter((l) => (prog.lessons[l]?.done || prog.lessons[l]?.skipped) && cur.lessons[l])
  if (!read.length) return null
  const labs = Object.values(cur.labs).filter((l) => l.kind !== 'lab' && !solved(l.id))
  const linked = new Set(read.flatMap((l) => cur.lessons[l].labs))
  const studied = labs.find((l) => linked.has(l.id))
  if (studied) return { lab: studied, reason: 'studied' }
  const practice = route ? routeModules(cur, route).flatMap((m) => cur.modules.find((x) => x.id === m)?.labs || []) : []
  const onRoute = labs.find((l) => practice.includes(l.id))
  return onRoute ? { lab: onRoute, reason: 'route' } : null
}
