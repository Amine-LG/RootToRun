// Turns a track diagnostic's answers into study advice. Pure functions, so the rules are unit-tested.
//
// Each item belongs to its first target (a lesson, or a lab/incident/challenge in the practice track):
//   study      - at least one of its items was missed or answered "I don't know yet"
//   review     - every item right, but at least one was a guess
//   shown      - every item answered, all right, none guessed (still not "done": the lesson's own checks confirm it)
//   partial    - the answered items were right and sure, but some of its items were not answered
//   unassessed - none of its items answered yet
// "Confident but wrong" (certain, and wrong) is reported separately: it points at a misconception, which is worth
// fixing first because it feels like knowledge.
import type { Curriculum, Diagnostic } from './data'
import type { DiagnosticRecord } from './progress'

export type Verdict = 'study' | 'review' | 'shown' | 'partial' | 'unassessed'
export type TargetResult = { id: string; verdict: Verdict; items: string[]; missed: number; guessed: number; confidentWrong: number; right: number }
export type ModuleResult = { id: string; title: string; answered: number; right: number; total: number; targets: TargetResult[] }
export type DiagnosticResult = { answered: number; right: number; total: number; modules: ModuleResult[]; byTarget: Record<string, TargetResult>; practise: string[] }

export const CONF_GUESS = 0
export const CONF_SURE = 2

export function moduleOf(cur: Curriculum, trackId: string, target: string): string | undefined {
  const tr = cur.tracks.find((t) => t.id === trackId)
  return tr?.modules.find((mid) => {
    const m = cur.modules.find((x) => x.id === mid)
    return !!m && (m.lessons.includes(target) || !!m.labs?.includes(target))
  })
}

export function classify(cur: Curriculum, d: Diagnostic, rec: DiagnosticRecord | undefined): DiagnosticResult {
  const answers = rec?.answers || {}
  const byTarget: Record<string, TargetResult> = {}
  const practise: string[] = []
  let answered = 0
  let right = 0
  for (const it of d.items) {
    const id = it.targets[0]
    const r = (byTarget[id] ||= { id, verdict: 'unassessed', items: [], missed: 0, guessed: 0, confidentWrong: 0, right: 0 })
    r.items.push(it.id)
    const a = answers[it.id]
    if (!a) continue
    answered++
    if (a.ok) {
      right++
      r.right++
      if (a.conf === CONF_GUESS) r.guessed++
    } else {
      r.missed++
      if (a.pick >= 0 && a.conf === CONF_SURE) r.confidentWrong++
    }
    if (!a.ok || a.conf === CONF_GUESS) for (const extra of it.targets.slice(1)) if (!practise.includes(extra)) practise.push(extra)
  }
  for (const r of Object.values(byTarget)) {
    const seen = r.items.filter((i) => answers[i]).length
    r.verdict = seen === 0 ? 'unassessed' : r.missed > 0 ? 'study' : r.guessed > 0 ? 'review' : seen < r.items.length ? 'partial' : 'shown'
  }
  const tr = cur.tracks.find((t) => t.id === d.track)
  const modules: ModuleResult[] = (tr?.modules || [])
    .map((mid) => {
      const m = cur.modules.find((x) => x.id === mid)
      const order = [...(m?.lessons || []), ...(m?.labs || [])]
      const targets = order.map((x) => byTarget[x]).filter(Boolean) as TargetResult[]
      const items = d.items.filter((it) => order.includes(it.targets[0]))
      return {
        id: mid,
        title: m?.title || mid,
        total: items.length,
        answered: items.filter((it) => answers[it.id]).length,
        right: items.filter((it) => answers[it.id]?.ok).length,
        targets,
      }
    })
    .filter((m) => m.total > 0)
  return { answered, right, total: d.items.length, modules, byTarget, practise: practise.filter((p) => !byTarget[p]) }
}

/** Items in track order (by module, then by the module's own order of targets), so the diagnostic reads like the path. */
export function ordered(cur: Curriculum, d: Diagnostic) {
  const tr = cur.tracks.find((t) => t.id === d.track)
  const rank = new Map<string, number>()
  let k = 0
  for (const mid of tr?.modules || []) {
    const m = cur.modules.find((x) => x.id === mid)
    for (const x of [...(m?.lessons || []), ...(m?.labs || [])]) rank.set(x, k++)
  }
  return d.items.map((it, i) => ({ it, i })).sort((a, b) => (rank.get(a.it.targets[0]) ?? 1e6) - (rank.get(b.it.targets[0]) ?? 1e6) || a.i - b.i).map((x) => x.it)
}

/** The topics to study first, in the order the results page and the path both recommend: confident mistakes first,
 * then the most missed, then the path's own order. */
export function studyOrder(res: DiagnosticResult): TargetResult[] {
  return res.modules.flatMap((m) => m.targets).filter((r) => r.verdict === 'study').sort((a, b) => b.confidentWrong - a.confidentWrong || b.missed - a.missed)
}
