/** Deterministic fact union. Scalar ties use canonical order so device order cannot change the result. */
import type { Progress, LabProgress, StepResult } from './progress'

/** The attempt a copy of a lab is in (lib/progress.ts IncidentState.rev; older copies: 0, the first attempt). */
const rev = (l?: LabProgress) => l?.incident?.rev ?? 0

export function canonical(value: unknown): string {
  if (value === undefined) return ''
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  if (value && typeof value === 'object') return `{${Object.entries(value).filter(([, v]) => v !== undefined).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(',')}}`
  return JSON.stringify(value)
}
const stable = <T,>(a: T, b: T): T => canonical(a) >= canonical(b) ? a : b
const min = (a?: number, b?: number) => a === undefined ? b : b === undefined ? a : Math.min(a, b)
const max = (a?: number, b?: number) => a === undefined ? b : b === undefined ? a : Math.max(a, b)
const by = <T,>(a: T, b: T, time: (x: T) => number): T => time(a) === time(b) ? stable(a, b) : time(a) > time(b) ? a : b
const owns = (obj: object, key: string) => Object.prototype.hasOwnProperty.call(obj, key)
function maps<T>(a: Record<string, T> = {}, b: Record<string, T> = {}, combine: (a: T, b: T) => T = stable): Record<string, T> {
  return Object.fromEntries([...new Set([...Object.keys(a), ...Object.keys(b)])].sort().map(k => [k, owns(a, k) && owns(b, k) ? combine(a[k], b[k]) : owns(a, k) ? a[k] : b[k]]))
}
const recent = <T extends { at: number }>(a: T, b: T) => by(a, b, x => x.at)
const earliest = <T extends { at: number }>(a: T, b: T) => a.at === b.at ? stable(a, b) : a.at < b.at ? a : b
const union = (a: string[] = [], b: string[] = []) => [...new Set([...a, ...b])].sort()
const strength = (r: StepResult) => (r.matched ? 3 : 0) + ({ legacy: 0, recording: 1, live: 2 }[r.source])
function labs(a: LabProgress, b: LabProgress): LabProgress {
  const xVerdict = { verdict: a.verdict, verdictAt: a.verdictAt }
  const yVerdict = { verdict: b.verdict, verdictAt: b.verdictAt }
  const verdict = !a.verdict ? yVerdict : !b.verdict ? xVerdict : by(xVerdict, yVerdict, x => x.verdictAt || 0)
  const result: LabProgress = {
    started: min(a.started, b.started), steps: maps(a.steps, b.steps, (x, y) => Math.min(x, y)),
    stepResults: maps(a.stepResults, b.stepResults, (x, y) => strength(x) === strength(y) ? recent(x, y) : strength(x) > strength(y) ? x : y),
    replayed: max(a.replayed, b.replayed), verified: max(a.verified, b.verified),
    verdict: verdict.verdict, verdictAt: verdict.verdictAt, hints: max(a.hints, b.hints), revealed: min(a.revealed, b.revealed),
    diagnosis: stable(a.diagnosis, b.diagnosis), pos: stable(a.pos, b.pos),
    selfCheck: a.selfCheck && b.selfCheck ? recent(a.selfCheck, b.selfCheck) : a.selfCheck || b.selfCheck,
  }
  // The current attempt (incident state, its diagnosis and self-check) is not a cumulative fact: when the copies are in
  // different attempts, the newer attempt is taken as it is. Cumulative facts above (revealed, hints, verdicts) merge.
  if (rev(a) !== rev(b)) {
    const now = rev(a) > rev(b) ? a : b
    result.incident = now.incident
    result.diagnosis = now.diagnosis
    result.selfCheck = now.selfCheck
    return result
  }
  if (a.incident || b.incident) {
    const x = a.incident || {}, y = b.incident || {}
    result.incident = { stage: max(x.stage, y.stage), hints: max(x.hints, y.hints),
      draft: stable(x.draft, y.draft),
      replays: union(x.replays, y.replays), nextHintAt: max(x.nextHintAt, y.nextHintAt), rev: x.rev ?? y.rev }
  }
  return result
}
/** Old cards have no review timestamp: infer it from due minus the scheduled interval. */
const reviewTime = (c: Progress['cards'][string]) => c.reviewedAt ?? c.due - c.interval * 86400000
export function merge(local: Progress, remote: Progress): Progress {
  if (canonical(local) === canonical(remote)) return structuredClone(local)
  const out: Progress = {
    v: 2,
    lessons: maps(local.lessons, remote.lessons, (a, b) => ({ seen: min(a.seen, b.seen), done: min(a.done, b.done), skipped: min(a.skipped, b.skipped), pos: stable(a.pos, b.pos) })),
    predictions: maps(local.predictions, remote.predictions, (a, b) => ({ first: earliest(a.first, b.first), latest: recent(a.latest, b.latest), n: Math.max(a.n, b.n) })),
    guesses: maps(local.guesses, remote.guesses, earliest) /* only the first guess is a prediction */, explains: maps(local.explains, remote.explains, recent),
    labs: maps(local.labs, remote.labs, labs), cards: maps(local.cards, remote.cards, (a, b) => by(a, b, reviewTime)),
    confidence: maps(local.confidence, remote.confidence, (a, b) => Math.max(a, b)),
    diagnostics: maps(local.diagnostics, remote.diagnostics, (a, b) => a.started === b.started ? {
      started: a.started, finished: max(a.finished, b.finished), answers: maps(a.answers, b.answers, recent),
    } : a.started > b.started ? a : b),
    days: union(local.days, remote.days), cmds: maps(local.cmds, remote.cmds, (a, b) => Math.max(a, b)), xp: Math.max(local.xp, remote.xp),
  }
  if (local.last || remote.last) out.last = local.last && remote.last ? recent(local.last, remote.last) : local.last || remote.last
  if (local.route || remote.route) out.route = stable(local.route, remote.route)
  if (local.legacy || remote.legacy) out.legacy = { predictions: maps(local.legacy?.predictions, remote.legacy?.predictions, earliest) }
  // The existing workspace displays one note/draft. Preserve conflicting text in
  // the progress/export as well, so selecting a display value cannot erase it.
  const notes = maps(local.syncNotes, remote.syncNotes, union)
  for (const id of new Set([...Object.keys(local.labs), ...Object.keys(remote.labs)])) {
    const a = local.labs[id], b = remote.labs[id]
    if (a && b && rev(a) !== rev(b)) continue // the older attempt's texts were discarded by a restart: not a conflict
    for (const [field, x, y] of [
      ['diagnosis', a?.diagnosis, b?.diagnosis], ['draft', a?.incident?.draft, b?.incident?.draft],
    ]) {
      if (typeof x === 'string' && typeof y === 'string' && x !== y) {
        const key = JSON.stringify([id, field])
        notes[key] = union(notes[key], [x, y])
      }
    }
  }
  if (Object.keys(notes).length) out.syncNotes = notes
  // Clone all branches: callers can safely mutate their local store after merging.
  return structuredClone(out)
}
