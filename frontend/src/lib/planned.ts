// The diagnostic plan's next lesson, for lib/next.ts (a hook: it loads the finished diagnostics' plans).
import { useEffect, useState } from 'react'
import { api, type Curriculum, type Diagnostic, type LessonSummary, type Route } from './data'
import { classify, studyOrder } from './diagnostic'
import { useApp } from './app'
import type { Progress } from './progress'

const finished = (prog: Progress, id: string) => !!(prog.lessons[id]?.done || prog.lessons[id]?.skipped)

/** The first unread lesson of a finished diagnostic's ranked plan for this route (the same plan the results and
 * territory pages show), or null. */
export function usePlannedLesson(cur: Curriculum | null, prog: Progress, route: Route | null): LessonSummary | null {
  const { lang } = useApp()
  const tracks = !cur ? [] : route ? cur.tracks.filter((x) => route.steps.includes(x.id) || x.modules.some((m) => route.steps.includes(m))) : cur.tracks
  const dks = [...new Set(tracks.map((x) => cur?.diagnostics?.[x.id]?.track).filter((k): k is string => !!k && !!prog.diagnostics[k]?.finished))]
  const [plans, setPlans] = useState<Record<string, Diagnostic>>({})
  useEffect(() => {
    dks.forEach((k) => api.diagnostic(k, lang).then((d) => setPlans((p) => ({ ...p, [k]: d })), () => undefined))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dks.join(','), lang])
  if (!cur) return null
  for (const k of dks) {
    const d = plans[k]
    if (!d) continue
    const id = studyOrder(classify(cur, d, prog.diagnostics[k])).map((r) => r.id).find((x) => cur.lessons[x] && !finished(prog, x))
    if (id) return cur.lessons[id]
  }
  return null
}
