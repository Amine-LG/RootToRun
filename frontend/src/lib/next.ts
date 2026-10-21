// Where to go next. One rule for every "Continue" on the site (home, learn, a course, progress): the last place
// visited while it is unfinished, else the first unread lesson of the diagnostic plan, else the chosen route (its
// starting point while nothing is started, then its next unread lesson, and nothing once it is all read: practice
// comes next), else the next unread lesson of the course.
import type { Curriculum, LessonSummary, Route } from './data'
import { labStatus, type Progress } from './progress'
import { beginHref, nextOnRoute, routeLessons } from './routes'
import { canonical, lessonHref, refOf } from './urls'

const finished = (prog: Progress, id: string) => !!(prog.lessons[id]?.done || prog.lessons[id]?.skipped)

/** The next lesson to study: first lesson in course order that is neither read nor skipped (optionally within one path). */
export function nextLesson(cur: Curriculum, prog: Progress, trackId?: string) {
  for (const tr of cur.tracks)
    if (!trackId || tr.id === trackId)
      for (const m of tr.modules)
        for (const l of cur.modules.find((x) => x.id === m)?.lessons || []) if (cur.lessons[l] && !finished(prog, l)) return cur.lessons[l]
  return null
}

/** The order "previous" and "next" follow for lesson `id`: the chosen route when the lesson is on it, else the course. */
function readingOrder(cur: Curriculum, id: string, route: Route | null): string[] {
  const onRoute = route ? routeLessons(cur, route) : []
  if (onRoute.includes(id)) return onRoute
  return cur.tracks.flatMap((tr) => tr.modules.flatMap((m) => cur.modules.find((x) => x.id === m)?.lessons || [])).filter((l) => cur.lessons[l])
}
/** The lesson after (+1) or before (-1) `id` for this learner, or null at either end. */
export function lessonBeside(cur: Curriculum, id: string, route: Route | null, step: 1 | -1): LessonSummary | null {
  const order = readingOrder(cur, id, route)
  const i = order.indexOf(id)
  return i >= 0 ? cur.lessons[order[i + step]] || null : null
}

export type Target = { href: string; title: string; kind: 'lesson' | 'lab' | 'incident' | 'diagnostic' | 'course'; resume: boolean; why: 'last' | 'plan' | 'begin' | 'route' | 'course' }

/** The last place visited, while it is unfinished (optionally only within one course). */
export function resumeTarget(cur: Curriculum, prog: Progress, trackId?: string): Target | null {
  const last = prog.last
  // the saved place may be an address from before readable URLs (/lesson/<id>): it still names the same page
  const m = last && refOf(last.href)
  if (!last || !m || (m.kind !== 'lesson' && m.kind !== 'lab')) return null
  const href = canonical(last.href)
  if (m.kind === 'lesson') {
    const l = cur.lessons[m.id]
    const inTrack = !trackId || cur.tracks.find((t) => t.id === trackId)?.modules.includes(l?.module || '')
    return l && inTrack && !finished(prog, m.id) ? { href, title: last.title, kind: 'lesson', resume: true, why: 'last' } : null
  }
  if (trackId) return null
  const lab = cur.labs[m.id]
  const st = labStatus(prog.labs[m.id])
  // a lab worked on and not finished: steps done, a failed or partial verdict, or an incident whose investigation began
  // (its stage is in the address); only opened is not "started"
  // a restarted incident keeps its old reveal on record: what counts is that its current attempt is being investigated
  const stage = prog.labs[m.id]?.incident?.stage
  const investigating = lab?.kind === 'incident' && (stage === 1 || stage === 2)
  const begun = investigating || st === 'started' || st === 'partial' || st === 'failed' || (st === 'new' && /[?&]stage=/.test(last.href))
  return lab && begun ? { href, title: last.title, kind: lab.kind === 'incident' ? 'incident' : 'lab', resume: true, why: 'last' } : null
}

/** The one thing to continue (see the rule at the top of this file); `planned` is usePlannedLesson's result (lib/planned.ts). */
export function continueTarget(cur: Curriculum, prog: Progress, route: Route | null = null, planned: LessonSummary | null = null): Target | null {
  const back = resumeTarget(cur, prog)
  if (back) return back
  const lesson = (n: LessonSummary, why: Target['why']): Target => ({ href: lessonHref(n.id), title: n.title, kind: 'lesson', resume: false, why })
  if (planned) return lesson(planned, 'plan')
  if (route) {
    const begun = Object.keys(prog.lessons).length + Object.keys(prog.labs).length + Object.keys(prog.diagnostics).length > 0
    if (!begun) {
      const b = route.begin
      return { href: beginHref(route), title: b.label, kind: b.kind === 'track' ? 'course' : b.kind, resume: false, why: 'begin' }
    }
    const n = nextOnRoute(cur, prog, route)
    return n ? lesson(n, 'route') : null // the route is read: practice is next
  }
  const n = nextLesson(cur, prog)
  return n ? lesson(n, 'course') : null
}

/** The first lesson after `id`, in the order of lessonBeside, that is neither read nor skipped. */
export function nextUnread(cur: Curriculum, id: string, route: Route | null, prog: Progress): LessonSummary | null {
  const order = readingOrder(cur, id, route)
  const rest = order.slice(order.indexOf(id) + 1)
  const n = rest.find((l) => !finished(prog, l))
  return n ? cur.lessons[n] : null
}
