// Learner progress stays in localStorage by default; optional account sync is an explicit opt-in.
//
// The store records facts, and every page derives conclusions with the same rules (lib/standing.ts, lib/evidence.ts):
//   - reading a lesson ("finished reading") is exposure, not understanding;
//   - a Check answer keeps its first and latest attempt; an ungraded guess (Predict) never counts as evidence;
//   - "Try again" on an exercise starts a new attempt on screen only: the next answer becomes the latest, the first
//     one stays the honest record, and nothing else is erased (resetProgress is the only thing that deletes facts);
//   - "replayed" (recorded outputs) and "verified" (state checks passed on a real cluster) are different achievements
//     and are never merged; a newer failed verdict stays visible after an older success.
// Version 2 is stored under a new key; version 1 data is migrated once and left in place untouched.
import { merge } from './sync' // type-only import back from sync, so no runtime cycle
import { useSyncExternalStore } from 'react'

export type Attempt = { ok: boolean; at: number; pick?: number; shown?: boolean; revealedAt?: number } // shown: answered after the answer was revealed (at revealedAt)
export type QuestionRecord = { first: Attempt; latest: Attempt; n: number }
export type Guess = { at: number; pick?: number; skipped?: boolean }
export type StepResult = { at: number; source: 'recording' | 'live' | 'legacy'; matched: boolean }
/** The current attempt at an incident (or a challenge: stage 1 = solution shown, hints = hints shown in this attempt).
 * restartAttempt() starts a new one; the lab-level facts (revealed, hints used, verdicts) are kept. `rev` is when the
 * attempt started (absent: the first attempt, as in every older record): when two copies are merged (import, sync)
 * the newer attempt wins as a whole, with its diagnosis and self-check, so an old export cannot bring back an
 * attempt the learner restarted. */
export type IncidentState = { stage?: number; hints?: number; draft?: string; replays?: string[]; nextHintAt?: number; rev?: number }
export type LabProgress = {
  started?: number
  steps?: Record<string, number> // step id → when completed (kept for compatibility; see stepResults)
  stepResults?: Record<string, StepResult>
  replayed?: number // every step worked through on recordings
  verified?: number // the latest time the final checks passed on a real cluster
  verdict?: string // latest live verdict
  verdictAt?: number
  hints?: number
  revealed?: number // incident: answer shown before repairing
  diagnosis?: string // incident: what the learner wrote before revealing
  incident?: IncidentState // where the learner is in an investigation, so a reload does not lose it
  selfCheck?: { root: boolean; evidence: boolean; fix: boolean; at: number } // incident debrief, self-assessed
  pos?: string // current step id
}
export type LessonRecord = {
  seen?: number
  done?: number // finished reading (exposure; never shown as "understood")
  skipped?: number // reading skipped after passing the lesson's checks
  pos?: string // current activity id
}
/** A track diagnostic: one answer per item (pick -1 = "I don't know yet"), with the learner's confidence. Suggests
 * where to start; it never marks a lesson as done. */
export type DiagAnswer = { pick: number; conf: 0 | 1 | 2; ok: boolean; at: number }
export type DiagnosticRecord = { started: number; finished?: number; answers: Record<string, DiagAnswer> }
export type CardState = { ef: number; interval: number; due: number; reps: number; lapses: number; reviewedAt?: number }
export type Progress = {
  v: 2
  lessons: Record<string, LessonRecord>
  predictions: Record<string, QuestionRecord> // graded Check questions, by stable question id
  guesses: Record<string, Guess> // ungraded predictions (lesson Predict items, "guess before you run" in labs)
  explains: Record<string, { score: number; of: number; at: number }> // self-assessed against a rubric
  labs: Record<string, LabProgress>
  cards: Record<string, CardState>
  confidence: Record<string, number>
  diagnostics: Record<string, DiagnosticRecord> // by track id
  days: string[]
  cmds: Record<string, number>
  xp: number
  last?: { href: string; title: string; at: number }
  route?: string // the journey the learner chose on the home page (a route id); never required
  syncNotes?: Record<string, string[]> // conflicting lab notes/drafts retained by sync, included in exports
  legacy?: { predictions?: Record<string, { ok: boolean; at: number }> } // v1 answers keyed by position, migrated lazily
}

const KEY = 'osa.progress.v2'
const KEY_V1 = 'osa.progress.v1'
const empty = (): Progress => ({ v: 2, lessons: {}, predictions: {}, guesses: {}, explains: {}, labs: {}, cards: {}, confidence: {}, diagnostics: {}, days: [], cmds: {}, xp: 0 })

// ---------------------------------------------------------------- validation and migration
const isObj = (x: unknown): x is Record<string, unknown> => !!x && typeof x === 'object' && !Array.isArray(x)
const num = (x: unknown) => (typeof x === 'number' && Number.isFinite(x) ? x : undefined)
function mapOf<T>(x: unknown, f: (v: unknown) => T | undefined): Record<string, T> {
  const out: Record<string, T> = Object.create(null)
  if (!isObj(x)) return out
  for (const [k, v] of Object.entries(x)) {
    const r = f(v)
    if (r !== undefined) out[k] = r
  }
  return out
}
const attempt = (x: unknown): Attempt | undefined => (isObj(x) && typeof x.ok === 'boolean' && num(x.at) !== undefined ? { ok: x.ok, at: x.at as number, pick: num(x.pick), ...(x.shown === true ? { shown: true, ...(num(x.revealedAt) ? { revealedAt: x.revealedAt as number } : {}) } : {}) } : undefined)
const legacyAnswer = (x: unknown) => (isObj(x) && typeof x.ok === 'boolean' && num(x.at) ? { ok: x.ok, at: x.at as number } : undefined)

// route ids renamed after learners could store them: a stored old id still selects the same route
const RENAMED_ROUTES: Record<string, string> = { exam: 'new-role' }

/** Accepts v1 or v2 data of unknown quality; returns a well-formed v2 store (malformed parts are dropped). */
export function normalize(raw: unknown): Progress {
  const p = empty()
  if (!isObj(raw)) return p
  const v1 = raw.v === 1
  p.lessons = mapOf(raw.lessons, (x) => (isObj(x) ? { seen: num(x.seen), done: num(x.done), skipped: num(x.skipped), pos: typeof x.pos === 'string' ? x.pos : undefined } : undefined))
  if (v1) {
    // v1 answers were keyed lesson:<id>:<index>. They become real records only when the lesson's questions are known.
    p.legacy = { predictions: mapOf(raw.predictions, legacyAnswer) }
  } else {
    p.predictions = mapOf(raw.predictions, (x) => {
      if (!isObj(x)) return undefined
      const first = attempt(x.first)
      const latest = attempt(x.latest)
      return first && latest ? { first, latest, n: num(x.n) || 1 } : undefined
    })
    p.guesses = mapOf(raw.guesses, (x) => (isObj(x) && num(x.at) ? { at: x.at as number, pick: num(x.pick), skipped: x.skipped === true || undefined } : undefined))
    if (isObj(raw.legacy)) p.legacy = { predictions: mapOf(raw.legacy.predictions, legacyAnswer) }
  }
  p.explains = mapOf(raw.explains, (x) => (isObj(x) && num(x.score) !== undefined && num(x.of) ? { score: x.score as number, of: x.of as number, at: num(x.at) || 0 } : undefined))
  p.labs = mapOf(raw.labs, (x) => {
    if (!isObj(x)) return undefined
    const l: LabProgress = {
      started: num(x.started),
      steps: mapOf(x.steps, num),
      replayed: num(x.replayed),
      verified: num(x.verified),
      verdict: typeof x.verdict === 'string' ? x.verdict : undefined,
      verdictAt: num(x.verdictAt),
      hints: num(x.hints),
      revealed: num(x.revealed),
      diagnosis: typeof x.diagnosis === 'string' ? x.diagnosis.slice(0, 4000) : undefined,
      pos: typeof x.pos === 'string' ? x.pos : undefined,
    }
    if (isObj(x.stepResults)) {
      l.stepResults = mapOf(x.stepResults, (r) =>
        isObj(r) && num(r.at) && (r.source === 'recording' || r.source === 'live' || r.source === 'legacy') ? { at: r.at as number, source: r.source, matched: r.matched === true } : undefined,
      )
    } else if (v1 && l.steps) {
      // v1 marked a step done whether or not its command did what was expected: keep that as "legacy", not as a match
      l.stepResults = Object.fromEntries(Object.entries(l.steps).map(([k, at]) => [k, { at, source: 'legacy' as const, matched: false }]))
    }
    if (isObj(x.selfCheck) && num(x.selfCheck.at)) {
      const c = x.selfCheck
      l.selfCheck = { root: c.root === true, evidence: c.evidence === true, fix: c.fix === true, at: c.at as number }
    }
    if (isObj(x.incident)) {
      const i = x.incident
      l.incident = {
        stage: num(i.stage),
        hints: num(i.hints),
        draft: typeof i.draft === 'string' ? i.draft.slice(0, 4000) : undefined,
        replays: Array.isArray(i.replays) ? i.replays.filter((r): r is string => typeof r === 'string').slice(0, 200) : undefined,
        nextHintAt: num(i.nextHintAt),
        rev: num(i.rev),
      }
    }
    return l
  })
  p.cards = mapOf(raw.cards, (x) => (isObj(x) && num(x.ef) && num(x.due) !== undefined ? { ef: x.ef as number, interval: num(x.interval) || 0, due: x.due as number, reps: num(x.reps) || 0, lapses: num(x.lapses) || 0, reviewedAt: num(x.reviewedAt) } : undefined))
  p.confidence = mapOf(raw.confidence, (x) => (num(x) && (x as number) >= 1 && (x as number) <= 5 ? (x as number) : undefined))
  p.diagnostics = mapOf(raw.diagnostics, (x) =>
    isObj(x) && num(x.started)
      ? {
          started: x.started as number,
          finished: num(x.finished),
          answers: mapOf(x.answers, (a) =>
            isObj(a) && num(a.pick) !== undefined && (a.conf === 0 || a.conf === 1 || a.conf === 2) && typeof a.ok === 'boolean'
              ? { pick: a.pick as number, conf: a.conf, ok: a.ok, at: num(a.at) || 0 }
              : undefined,
          ),
        }
      : undefined,
  )
  p.days = Array.isArray(raw.days) ? raw.days.filter((d): d is string => typeof d === 'string' && /^\d{4}-\d\d-\d\d$/.test(d)) : []
  if (isObj(raw.syncNotes)) p.syncNotes = mapOf(raw.syncNotes, (x) =>
    Array.isArray(x) ? [...new Set(x.filter((v): v is string => typeof v === 'string'))].sort() : undefined)
  p.cmds = mapOf(raw.cmds, num)
  p.xp = num(raw.xp) || 0
  if (typeof raw.route === 'string' && /^[a-z0-9-]{1,40}$/.test(raw.route)) p.route = RENAMED_ROUTES[raw.route] || raw.route
  if (isObj(raw.last) && typeof raw.last.href === 'string' && raw.last.href.startsWith('/')) p.last = { href: raw.last.href, title: String(raw.last.title || ''), at: num(raw.last.at) || 0 }
  return p
}

function read(): Progress {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) return normalize(JSON.parse(raw))
    const old = localStorage.getItem(KEY_V1)
    if (old) return normalize(JSON.parse(old))
  } catch {
    /* unavailable or corrupt: start fresh */
  }
  return empty()
}

let state = read()
const subs = new Set<() => void>()
const today = () => new Date().toISOString().slice(0, 10)

/** Persist and notify. Returns false when the browser refused to store it (private mode, quota, disabled storage). */
let saveFailed = false
function save(): boolean {
  let ok = true
  try {
    localStorage.setItem(KEY, JSON.stringify(state))
  } catch {
    ok = false // progress stays in memory for this tab
  }
  saveFailed = !ok
  subs.forEach((f) => f())
  return ok
}
/** True while the browser refuses to store progress (storage full, blocked or private browsing): the shell says so,
 *  so that nothing is shown as kept that would vanish with the tab. */
export function useSaveFailed(): boolean {
  return useSyncExternalStore(
    (f) => {
      subs.add(f)
      return () => subs.delete(f)
    },
    () => saveFailed,
  )
}

export function update(f: (p: Progress) => void, xp = 0) {
  const next: Progress = structuredClone(state)
  f(next)
  if (xp) next.xp += xp
  const d = today()
  if (!next.days.includes(d)) next.days = [...next.days, d]
  state = next
  save()
}

export const getProgress = () => state
/** Sync replaces facts without awarding XP or recording a new study day. */
export function replaceProgress(p: Progress): boolean {
  state = normalize(p)
  return save()
}
export function subscribeProgress(f: () => void) {
  subs.add(f)
  return () => { subs.delete(f) }
}

export function useProgress(): Progress {
  return useSyncExternalStore(
    (f) => {
      subs.add(f)
      return () => subs.delete(f)
    },
    () => state,
  )
}

if (typeof window !== 'undefined')
  window.addEventListener('storage', (e) => {
    if (e.key === KEY) {
      state = read()
      subs.forEach((f) => f())
    }
  })

// ---------------------------------------------------------------- rewards (motivation only; never drives recommendations)
export const XP = { lesson: 20, predictRight: 5, predictTried: 1, explain: 15, labReplay: 30, labVerified: 60, incidentSolved: 80, incidentRevealed: 20, card: 2 }
export const LEVELS = [0, 100, 250, 500, 900, 1400, 2000, 2800, 3800, 5000]
export function level(xp: number) {
  let i = LEVELS.findIndex((x) => xp < x)
  if (i === -1) i = LEVELS.length
  const lo = LEVELS[i - 1] ?? 0
  const hi = LEVELS[i] ?? lo + 1500
  return { level: i, into: xp - lo, span: hi - lo }
}

export function streak(days: string[]) {
  const set = new Set(days)
  let n = 0
  const d = new Date()
  if (!set.has(d.toISOString().slice(0, 10))) d.setDate(d.getDate() - 1) // today not yet counted
  while (set.has(d.toISOString().slice(0, 10))) {
    n++
    d.setDate(d.getDate() - 1)
  }
  return n
}

// ---------------------------------------------------------------- lessons
export const markLessonSeen = (id: string) => {
  if (!state.lessons[id]?.seen) update((p) => void (p.lessons[id] = { ...p.lessons[id], seen: Date.now() }))
}
/** Finished reading: exposure only. */
export const markLessonDone = (id: string) => {
  if (!state.lessons[id]?.done) update((p) => void (p.lessons[id] = { ...p.lessons[id], done: Date.now() }), XP.lesson)
}
/** The learner passed the lesson's checks and chose to skip the reading (recorded as exactly that). */
export const markReadingSkipped = (id: string) => {
  if (!state.lessons[id]?.skipped) update((p) => void (p.lessons[id] = { ...p.lessons[id], skipped: Date.now() }))
}
export const setLessonPos = (id: string, pos: string) => {
  if (state.lessons[id]?.pos !== pos) update((p) => void (p.lessons[id] = { ...p.lessons[id], pos }))
}

/** A graded answer to a Check question (stable question id). Keeps the first and the latest attempt. */
export function recordAnswer(qid: string, ok: boolean, pick?: number, shown = false, revealedAt?: number) {
  const prior = state.predictions[qid]
  const a: Attempt = { ok, at: Date.now(), pick, ...(shown ? { shown: true, ...(revealedAt ? { revealedAt } : {}) } : {}) }
  update((p) => void (p.predictions[qid] = prior ? { first: prior.first, latest: a, n: prior.n + 1 } : { first: a, latest: a, n: 1 }), prior ? 0 : ok ? XP.predictRight : XP.predictTried)
}
/** An ungraded guess (or an explicit skip). Never evidence of understanding. Only the first one is kept: a guess
 * made again after "Try again" comes after the answer was shown, so it is no longer a prediction. */
export function recordGuess(key: string, pick: number | null) {
  if (state.guesses[key]) return
  update((p) => void (p.guesses[key] = pick === null ? { at: Date.now(), skipped: true } : { at: Date.now(), pick }))
}
/** v1 stored answers by position; once a lesson's questions are known, carry them over to stable ids. */
export function migrateLegacyAnswers(lessonId: string, qids: string[]) {
  const legacy = state.legacy?.predictions
  if (!legacy) return
  const found = qids.map((q, k) => ({ q, key: `lesson:${lessonId}:${k}` })).filter(({ q, key }) => legacy[key] && !state.predictions[q])
  if (!found.length) return
  update((p) => {
    for (const { q, key } of found) {
      const a = p.legacy!.predictions![key]
      const at: Attempt = { ok: a.ok, at: a.at }
      p.predictions[q] = { first: at, latest: at, n: 1 }
      delete p.legacy!.predictions![key]
    }
  })
}

export const recordExplain = (key: string, score: number, of: number) =>
  update((p) => void (p.explains[key] = { score, of, at: Date.now() }), state.explains[key] ? 0 : XP.explain)
export const setConfidence = (concept: string, n: number) => update((p) => void (p.confidence[concept] = n))
export const diagStart = (track: string) => update((p) => void (p.diagnostics[track] = { started: Date.now(), answers: {} }))
export const diagAnswer = (track: string, item: string, a: Omit<DiagAnswer, 'at'>) =>
  update((p) => {
    const d = (p.diagnostics[track] ||= { started: Date.now(), answers: {} })
    d.answers[item] = { ...a, at: Date.now() }
  })
export const diagFinish = (track: string) => update((p) => void (p.diagnostics[track] && (p.diagnostics[track].finished = Date.now())))
export const diagClear = (track: string) => update((p) => void delete p.diagnostics[track])
export const setLast = (href: string, title: string) => {
  if (state.last?.href !== href) update((p) => void (p.last = { href, title, at: Date.now() }))
}
export const setRoute = (id: string | null) => update((p) => void (id ? (p.route = id) : delete p.route))
export const noteCommand = (cmd: string) => update((p) => void (p.cmds[cmd] = (p.cmds[cmd] || 0) + 1))

// ---------------------------------------------------------------- labs and incidents
export function labUpdate(id: string, f: (l: LabProgress) => void, xp = 0) {
  update((p) => {
    const l = { started: Date.now(), ...(p.labs[id] || {}) }
    f(l)
    p.labs[id] = l
  }, xp)
}

/** Starts a new attempt at an incident or a challenge: back to the first stage, with no draft, replays, hints on
 * screen, diagnosis or self-check. What happened before stays recorded (the answer was revealed, hints used, live
 * verdicts, step results), so a restart never turns help into "solved alone" and never touches other activities. */
export function restartAttempt(id: string) {
  update((p) => {
    // a restart before anything was saved (a draft not yet stored) still records the new attempt, so an older copy
    // imported later cannot bring the previous attempt back
    const l = (p.labs[id] = { started: Date.now(), ...(p.labs[id] || {}) })
    l.incident = { stage: 0, hints: 0, rev: Math.max(Date.now(), (l.incident?.rev ?? 0) + 1) }
    delete l.selfCheck
    delete l.diagnosis
  })
}

/** Which attempt is current: the start time of the latest restart (0 = the first attempt). */
export const attemptRev = (l?: LabProgress) => l?.incident?.rev ?? 0

export type LabStatus = 'new' | 'started' | 'replayed' | 'diagnosed' | 'revealed' | 'partial' | 'failed' | 'verified'
/** The latest live verdict wins over an older success, so a later failure is never hidden. */
export function labStatus(l?: LabProgress): LabStatus {
  if (!l) return 'new'
  // a live verdict that is not "verified" and is newer than the last success hides nothing: it is what is true now
  if (l.verdict && l.verdict !== 'verified' && l.verdictAt && (!l.verified || l.verdictAt > l.verified)) return l.verdict === 'partial' ? 'partial' : 'failed'
  if (l.verified) return 'verified'
  if (l.verdict === 'partial') return 'partial'
  if (l.replayed) return 'replayed'
  if (l.selfCheck && l.selfCheck.root && l.selfCheck.evidence && l.selfCheck.fix) return 'diagnosed'
  if (l.revealed) return 'revealed'
  return (l.stepResults && Object.keys(l.stepResults).length) || (l.steps && Object.keys(l.steps).length) ? 'started' : 'new'
}

// ---------------------------------------------------------------- spaced review
// A simple expanding-interval scheduler in the spirit of SM-2 (not a full implementation): a failed recall comes back
// in 10 minutes, successes after 1 day, 3 days, then intervals multiplied by an ease factor.
export function grade(cardId: string, q: 0 | 3 | 4 | 5) {
  update((p) => {
    const c = p.cards[cardId] || { ef: 2.5, interval: 0, due: 0, reps: 0, lapses: 0 }
    if (q < 3) {
      c.reps = 0
      c.lapses++
      c.interval = 0
      c.ef = Math.max(1.3, c.ef - 0.2)
    } else {
      c.reps++
      c.interval = c.reps === 1 ? 1 : c.reps === 2 ? 3 : Math.round(c.interval * c.ef)
      c.ef = Math.max(1.3, c.ef + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))
    }
    c.reviewedAt = Date.now()
    c.due = q < 3 ? Date.now() + 10 * 60 * 1000 : Date.now() + c.interval * 86400 * 1000
    p.cards[cardId] = c
  }, XP.card)
}

/** A card is in the deck once its lesson was read (or its reading skipped) or its lab/incident worked through. */
export function unlocked(card: { source: string; ref: string }, p: Progress) {
  if (card.source === 'lesson') return !!(p.lessons[card.ref]?.done || p.lessons[card.ref]?.skipped)
  const l = p.labs[card.ref]
  return !!(l && (l.replayed || l.verified || l.revealed || l.selfCheck))
}

export function exportProgress(): string {
  return JSON.stringify(state, null, 1)
}
/** Imports a progress file (v1 or v2) and merges it with the progress already in this browser, fact by fact, so
 * that importing an older backup never erases newer work. Malformed parts are dropped; returns the result. */
export function importProgress(text: string): { lessons: number; answers: number; labs: number; saved: boolean } {
  const raw = JSON.parse(text)
  if (!isObj(raw) || (raw.v !== 1 && raw.v !== 2)) throw new Error('not an academy progress file')
  const incoming = normalize(raw)
  state = merge(state, incoming) // a v1 file too: its positional answers stay under `legacy` (merged by sync.ts)
  const saved = save()
  return { lessons: Object.keys(state.lessons).length, answers: Object.keys(state.predictions).length + Object.keys(state.legacy?.predictions || {}).length, labs: Object.keys(state.labs).length, saved }
}
/** Where the models (sims/ui.tsx) keep their prediction and challenges in this browser: learner state too. */
export const SIM_KEY_PREFIX = 'oa.sim.'
/** Deletes all progress in this browser (including the v1 copy kept for migration and the models' predictions and
 * challenges). Says whether it really worked. */
export function resetProgress(): { ok: boolean; reason?: string } {
  state = empty()
  const saved = save()
  try {
    localStorage.removeItem(KEY_V1)
    const sims: string[] = []
    for (let i = 0; i < (localStorage.length || 0); i++) {
      const k = localStorage.key(i)
      if (k?.startsWith(SIM_KEY_PREFIX)) sims.push(k)
    }
    sims.forEach((k) => localStorage.removeItem(k))
  } catch {
    /* nothing more can be done */
  }
  // Read back what the browser kept: success means the stored copy is empty, not only that no error was thrown.
  let clean = false
  try {
    const stored = localStorage.getItem(KEY)
    const p = stored === null ? null : normalize(JSON.parse(stored))
    clean = !p || (Object.keys(p.lessons).length === 0 && Object.keys(p.labs).length === 0 && Object.keys(p.predictions).length === 0 && Object.keys(p.diagnostics).length === 0)
  } catch {
    clean = false
  }
  if (!saved || !clean) return { ok: false, reason: 'storage' }
  return { ok: true }
}
