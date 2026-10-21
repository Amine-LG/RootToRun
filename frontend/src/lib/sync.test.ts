import { describe, expect, it } from 'vitest'
import { labStatus, normalize, type Progress } from './progress'
import { merge } from './sync'

const p = (partial: Partial<Progress> = {}) => normalize({ v: 2, ...partial })
const a = p({ lessons: { a: { seen: 20, done: 30, pos: 'learn' } },
  predictions: { q: { first: { at: 5, ok: false }, latest: { at: 30, ok: true }, n: 3 } },
  labs: { lab: { started: 4, verified: 20, verdict: 'verified', verdictAt: 20, stepResults: { s: { at: 50, source: 'recording', matched: true } }, diagnosis: 'note', incident: { stage: 1, draft: 'draft', replays: ['a'] } } },
  cards: { c: { reviewedAt: 20, ef: 2.5, interval: 20, due: 2000000, reps: 4, lapses: 0 } },
  diagnostics: { track: { started: 5, answers: { a: { pick: 1, ok: true, conf: 1, at: 6 } } } },
  days: ['2026-01-01'], cmds: { 'oc get': 3 }, xp: 100,
})
const b = p({ lessons: { a: { seen: 10, done: 40 }, b: { seen: 50 } },
  predictions: { q: { first: { at: 2, ok: true }, latest: { at: 40, ok: false }, n: 2 } },
  labs: { lab: { started: 8, replayed: 10, verdict: 'failed', verdictAt: 40, stepResults: { s: { at: 10, source: 'live', matched: true }, t: { at: 11, source: 'legacy', matched: false } }, incident: { stage: 2, replays: ['b'] } } },
  cards: { c: { reviewedAt: 30, ef: 2, interval: 0, due: 1000, reps: 0, lapses: 1 } },
  diagnostics: { track: { started: 10, answers: {} } }, days: ['2026-01-02'], cmds: { 'oc get': 2, 'oc logs': 1 }, xp: 80,
})
describe('progress merge', () => {
  it('unions lessons with earliest exposure and completion', () => {
    const m = merge(a, b)
    expect(m.lessons.a).toEqual({ seen: 10, done: 30, skipped: undefined, pos: 'learn' })
    expect(m.lessons.b.seen).toBe(50)
  })
  it('keeps first and latest attempts without inflating counts or rewards', () => {
    const m = merge(a, b)
    expect(m.predictions.q).toEqual({ first: b.predictions.q.first, latest: b.predictions.q.latest, n: 3 })
    expect(m.cmds).toEqual({ 'oc get': 3, 'oc logs': 1 }); expect(m.xp).toBe(100)
  })
  it('keeps strongest evidence and shows a later failed verdict', () => {
    const lab = merge(a, b).labs.lab
    expect(lab.verified).toBe(20); expect(lab.replayed).toBe(10)
    expect(lab.stepResults?.s).toEqual(b.labs.lab.stepResults?.s)
    expect(lab.stepResults?.t.source).toBe('legacy')
    expect(labStatus(lab)).toBe('failed')
    expect(lab.diagnosis).toBe('note'); expect(lab.incident?.draft).toBe('draft')
    expect(lab.incident?.replays).toEqual(['a', 'b'])
  })
  it('uses review time rather than due date; newer failed recall beats older long interval', () => {
    expect(merge(a, b).cards.c).toEqual(b.cards.c)
    const old = p({ cards: { c: { ef: 2, interval: 1, due: 86400100, reps: 1, lapses: 0 } } })
    expect(merge(old, a).cards.c).toEqual(old.cards.c)
  })
  it('keeps newest diagnostic run, unions answers within the same run', () => {
    expect(merge(a, b).diagnostics.track).toEqual(b.diagnostics.track)
    const same = p({ diagnostics: { track: { started: 5, finished: 20, answers: { b: { at: 10, pick: 0, conf: 2, ok: false } } } } })
    expect(Object.keys(merge(a, same).diagnostics.track.answers)).toEqual(['a', 'b'])
    expect(merge(a, same).diagnostics.track.finished).toBe(20)
  })
  it('unions days without dropping older history', () => {
    expect(merge(a, b).days).toEqual(['2026-01-01', '2026-01-02'])
    const dates = Array.from({ length: 500 }, (_, i) => new Date(Date.UTC(2020, 0, i + 1)).toISOString().slice(0, 10))
    expect(normalize(merge(p({ days: dates.slice(0, 300) }), p({ days: dates.slice(300) }))).days).toHaveLength(500)
  })
  it('preserves guesses, rubric scores, confidence, legacy answers, route and resume location', () => {
    const x = p({ guesses: { g: { at: 1, pick: 0 } }, explains: { e: { at: 1, score: 1, of: 2 } }, confidence: { c: 2 }, route: 'linux', last: { href: '/me', at: 1, title: 'Me' }, legacy: { predictions: { old: { ok: false, at: 2 } } } })
    const y = p({ guesses: { g: { at: 2, skipped: true } }, explains: { e: { at: 2, score: 2, of: 2 } }, confidence: { c: 3 }, route: 'containers', last: { href: '/review', at: 2, title: 'Review' }, legacy: { predictions: { other: { ok: true, at: 3 } } } })
    const m = merge(x, y)
    expect(m.guesses).toEqual(x.guesses) /* the earliest guess is the prediction (A: first guess kept) */; expect(m.explains).toEqual(y.explains); expect(m.confidence.c).toBe(3)
    expect(m.last).toEqual(y.last); expect(m.route).toBeTruthy(); expect(Object.keys(m.legacy!.predictions!)).toHaveLength(2)
    expect(merge(y, x)).toEqual(m)
  })
  it('is idempotent and commutative including timestamp ties, and never mutates inputs', () => {
    const before = structuredClone(a)
    for (const x of [a, b, p(), merge(a, b)]) {
      expect(merge(x, x)).toEqual(x)
      expect(merge(x, a)).toEqual(merge(a, x))
      expect(merge(merge(x, b), b)).toEqual(merge(x, b))
    }
    const tie = p({ predictions: { q: { first: { at: 5, ok: true }, latest: { at: 30, ok: false }, n: 3 } } })
    expect(merge(a, tie)).toEqual(merge(tie, a))
    const merged = merge(a, b); merged.labs.lab.incident!.draft = 'changed'
    expect(a).toEqual(before)
  })
})

it('resolves equal lab timestamps independently of other merged fields', () => {
  const x = p({ labs: { l: { started: 3, verdict: 'failed', verdictAt: 10, diagnosis: 'z', incident: { draft: 'x' } } } })
  const y = p({ labs: { l: { started: 1, verdict: 'verified', verdictAt: 10, verified: 10, diagnosis: 'a', incident: { draft: 'y' } } } })
  const m = merge(x, y)
  expect(merge(y, x)).toEqual(m)
  expect(merge(m, x)).toEqual(m)
  expect(merge(m, y)).toEqual(m)
})

it('handles map keys named like object prototype properties', () => {
  const x = p(JSON.parse('{"lessons":{"__proto__":{"seen":1},"toString":{"done":2}}}'))
  const m = merge(x, p())
  expect(Object.keys(m.lessons)).toEqual(['__proto__', 'toString'])
  expect(m.lessons.__proto__.seen).toBe(1)
  expect(merge(p(), x)).toEqual(m)
})

it('retains every conflicting note and draft in normalized progress and exports', () => {
  const x = p({ labs: { lab: { diagnosis: 'first diagnosis', incident: { draft: 'first draft' } } } })
  const y = p({ labs: { lab: { diagnosis: 'second diagnosis', incident: { draft: 'second draft' } } } })
  const m = normalize(merge(x, y))
  expect(m.syncNotes?.['["lab","diagnosis"]']).toEqual(['first diagnosis', 'second diagnosis'])
  expect(m.syncNotes?.['["lab","draft"]']).toEqual(['first draft', 'second draft'])
  const z = p({ labs: { lab: { diagnosis: 'third diagnosis' } } })
  const next = merge(m, z)
  expect(next.syncNotes?.['["lab","diagnosis"]']).toHaveLength(3)
  expect(normalize(merge(y, x))).toEqual(m)
  expect(normalize(merge(m, x))).toEqual(m)
  expect(JSON.stringify(next)).toContain('first draft')
})
