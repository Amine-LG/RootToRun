import { describe, expect, it } from 'vitest'
import type { Curriculum } from './data'
import { conceptEvidence, courseOrder, evidenceLevel } from './evidence'
import type { Attempt, LabProgress, Progress, QuestionRecord } from './progress'
import { activityDone, cardQueue, checksOf, questionState, tallyActivities, tallyChecks, verifiedNow } from './standing'
import type { ReviewCard } from './data'

const at = (ok: boolean, more: Partial<Attempt> = {}): Attempt => ({ ok, at: 1000, pick: 0, ...more })
const rec = (first: Attempt, latest: Attempt = first, n = first === latest ? 1 : 2): QuestionRecord => ({ first, latest, n })
const RIGHT = rec(at(true))
const WRONG = rec(at(false))
const CORRECTED = rec(at(false), at(true, { at: 2000, shown: true, revealedAt: 1500 }))
const LATER = rec(at(false), at(true, { at: 9e9 })) // right again long after, without having just seen the answer
const BROKE = rec(at(true), at(false, { at: 2000 }))
const prog = (predictions: Record<string, QuestionRecord> = {}, labs: Record<string, LabProgress> = {}, lessons: Progress['lessons'] = {}) =>
  ({ predictions, labs, lessons }) as unknown as Progress

describe('a question is read the same way everywhere', () => {
  it('by its latest answer, saying when it was corrected after the answer was shown', () => {
    expect(questionState(undefined)).toBe('unanswered')
    expect(questionState(RIGHT)).toBe('right')
    expect(questionState(WRONG)).toBe('wrong')
    expect(questionState(CORRECTED)).toBe('corrected')
    expect(questionState(LATER)).toBe('right')
    expect(questionState(BROKE)).toBe('wrong') // a later wrong answer is what is true now
  })
  it('scores count corrected answers, keep the first try apart, and only wrong answers are outstanding', () => {
    const p = prog({ a: RIGHT, b: CORRECTED, c: WRONG, d: LATER, e: BROKE })
    const t = tallyChecks(['a', 'b', 'c', 'd', 'e', 'f'], p)
    expect(t).toEqual({ total: 6, answered: 5, right: 3, corrected: 1, firstTry: 2, wrong: ['c', 'e'], unanswered: ['f'] })
  })
})

describe('an activity is completed by what its kind allows', () => {
  const full = { root: true, evidence: true, fix: true, at: 1 }
  it('a lab on the recordings, an incident by its debrief, a challenge only on a cluster', () => {
    expect(activityDone('lab', { replayed: 1 })).toBe(true)
    expect(activityDone('lab', { stepResults: { s: { at: 1, source: 'recording', matched: true } } })).toBe(false)
    expect(activityDone('incident', { replayed: 1 })).toBe(false)
    expect(activityDone('incident', { selfCheck: full })).toBe(true)
    expect(activityDone('incident', { selfCheck: { ...full, fix: false } })).toBe(false) // an unfinished self-check
    expect(activityDone('incident', { revealed: 1 })).toBe(false)
    expect(activityDone('challenge', { revealed: 1, hints: 3 })).toBe(false)
    expect(activityDone('challenge', { verified: 5, verdict: 'verified', verdictAt: 5 })).toBe(true)
    expect(activityDone('lab', undefined)).toBe(false)
  })
  it('completion stays a fact; the verdict shown is the latest one', () => {
    const l: LabProgress = { replayed: 1, verified: 5, verdict: 'failed', verdictAt: 9 }
    expect(activityDone('lab', l)).toBe(true)
    expect(verifiedNow(l)).toBe(false)
  })
})

const lesson = (id: string, module: string, concepts: string[], checks: string[]) => ({ id, title: id, module, concepts, checks, labs: [] })
const lab = (id: string, kind: 'lab' | 'incident' | 'challenge', module: string, concepts: string[]) => ({ id, kind, title: id, module, concepts, level: 1 })
const cur = {
  tracks: [{ id: 't2', modules: ['m2'] }, { id: 't1', modules: ['m1'] }], // the course order is the tracks' order
  modules: [{ id: 'm1', lessons: ['l1', 'l2'] }, { id: 'm2', lessons: ['l3'] }],
  lessons: { l3: lesson('l3', 'm2', ['x'], ['q3']), l1: lesson('l1', 'm1', ['x'], ['q1', 'q2']), l2: lesson('l2', 'm1', ['y'], []) },
  labs: { inc: lab('inc', 'incident', 'm2', ['x']), lb: lab('lb', 'lab', 'm1', ['x']), ch: lab('ch', 'challenge', 'm2', ['y']) },
  concepts: {},
} as unknown as Curriculum

describe('concept evidence uses the same rules, and says where to go', () => {
  it('lists lessons in course order and activities by module, and counts them by the shared rules', () => {
    expect(courseOrder(cur)).toEqual(['l3', 'l1', 'l2'])
    expect(checksOf(cur, ['l3', 'l1'])).toEqual(['q3', 'q1', 'q2'])
    const p = prog({ q1: CORRECTED, q2: WRONG }, { inc: { selfCheck: { root: true, evidence: true, fix: true, at: 1 } }, lb: { stepResults: {} } }, { l1: { done: 1 } })
    const e = conceptEvidence(cur, p, 'x')
    expect(e).toMatchObject({ lessonIds: ['l3', 'l1'], labIds: ['inc', 'lb'], read: 1, checks: 3, checksAnswered: 2, checksCorrect: 1, checksCorrected: 1, practised: 1, labs: 2, verified: 0, begun: 1 })
    expect(evidenceLevel(e)).toBe('practised')
    expect(tallyActivities(cur, ['inc', 'lb', 'ch', 'gone'], p)).toEqual({ total: 3, done: 1, verified: 0 })
  })
})

describe('recall cards are counted the same way on every page', () => {
  it("a finished lesson's cards are ready at once, as new; a graded card comes back when it is due again", () => {
    const card = (id: string, ref: string) => ({ id, source: 'lesson', ref }) as ReviewCard
    const cards = [card('a1', 'l1'), card('a2', 'l1'), card('a3', 'l1'), card('b1', 'l2')]
    const p = { lessons: { l1: { done: 1 } }, labs: {}, predictions: { q: RIGHT }, cards: { a2: { ef: 2.5, interval: 1, due: 500, reps: 1, lapses: 0 }, a3: { ef: 2.5, interval: 3, due: 5000, reps: 2, lapses: 0 } } } as unknown as Progress
    const q = cardQueue(cards, p, 1000)
    expect(q.deck.map((c) => c.id)).toEqual(['a1', 'a2', 'a3']) // l2 is not finished: its card is not in the deck
    expect(q.fresh.map((c) => c.id)).toEqual(['a1'])
    expect(q.again.map((c) => c.id)).toEqual(['a2'])
    expect(q.ready.map((c) => c.id)).toEqual(['a1', 'a2']) // in deck order; a3 is due later
  })
})
