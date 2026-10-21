// Progress semantics: facts in, honest statuses out.
import { describe, expect, it, vi } from 'vitest'
import { labStatus, normalize } from './progress'

describe('labStatus', () => {
  it('shows a later failure after an earlier success', () => {
    expect(labStatus({ verified: 100, verdict: 'failed', verdictAt: 200 })).toBe('failed')
    expect(labStatus({ verified: 100, verdict: 'partial', verdictAt: 200 })).toBe('partial')
  })
  it('shows a later success after an earlier failure, and repeated successes stay verified', () => {
    expect(labStatus({ verified: 300, verdict: 'verified', verdictAt: 300 })).toBe('verified')
    expect(labStatus({ verified: 300, verdict: 'verified', verdictAt: 301 })).toBe('verified')
  })
  it('never calls a self-assessed diagnosis verified, and needs all three points', () => {
    expect(labStatus({ revealed: 1, selfCheck: { root: true, evidence: true, fix: true, at: 2 } })).toBe('diagnosed')
    expect(labStatus({ revealed: 1, selfCheck: { root: true, evidence: false, fix: true, at: 2 } })).toBe('revealed')
  })
  it('does not count recorded replays of failed expectations as practised', () => {
    expect(labStatus({ stepResults: { a: { at: 1, source: 'legacy', matched: false } } })).toBe('started')
  })
})

describe('normalize (import and migration)', () => {
  it('migrates v1 without inventing evidence', () => {
    const p = normalize({ v: 1, lessons: { x: { done: 5 } }, predictions: { 'lesson:x:0': { ok: true, at: 3 } }, labs: { l: { steps: { s: 4 } } }, xp: 10 })
    expect(p.v).toBe(2)
    expect(p.predictions).toEqual({}) // v1 answers wait for their stable ids
    expect(p.legacy?.predictions).toEqual({ 'lesson:x:0': { ok: true, at: 3 } })
    expect(p.labs.l.stepResults).toEqual({ s: { at: 4, source: 'legacy', matched: false } })
    expect(p.labs.l.replayed).toBeUndefined()
  })
  it('drops malformed parts instead of crashing', () => {
    const p = normalize({ v: 2, lessons: null, predictions: { q: { first: 'x' } }, labs: { l: 'nope' }, days: ['2026-01-01', 'bad'], last: { href: 'https://evil.example' } })
    expect(p.lessons).toEqual({})
    expect(p.predictions).toEqual({})
    expect(p.labs).toEqual({})
    expect(p.days).toEqual(['2026-01-01'])
    expect(p.last).toBeUndefined()
  })
})

describe('resetProgress', () => {
  const store = (failWrites: boolean) => {
    const m = new Map<string, string>()
    return {
      getItem: (k: string) => m.get(k) ?? null,
      setItem: (k: string, v: string) => {
        if (failWrites) throw new Error('QuotaExceededError')
        m.set(k, v)
      },
      removeItem: (k: string) => void m.delete(k),
      seed: (k: string, v: string) => m.set(k, v),
    }
  }
  it('reports success only when the stored copy is really empty', async () => {
    const s = store(false)
    s.seed('osa.progress.v2', JSON.stringify({ v: 2, lessons: { x: { done: 1 } } }))
    vi.stubGlobal('localStorage', s)
    const { resetProgress } = await import('./progress')
    expect(resetProgress()).toEqual({ ok: true })
    expect(JSON.parse(s.getItem('osa.progress.v2')!).lessons).toEqual({})
    vi.unstubAllGlobals()
  })
  it('reports failure when the browser refuses to store the reset', async () => {
    const s = store(true)
    s.seed('osa.progress.v2', JSON.stringify({ v: 2, lessons: { x: { done: 1 } } }))
    vi.stubGlobal('localStorage', s)
    const { resetProgress } = await import('./progress')
    expect(resetProgress()).toEqual({ ok: false, reason: 'storage' })
    vi.unstubAllGlobals()
  })
})

describe('importProgress', () => {
  it('merges an imported backup with newer progress instead of replacing it', async () => {
    const store: Record<string, string> = {}
    vi.stubGlobal('localStorage', { getItem: (k: string) => store[k] ?? null, setItem: (k: string, v: string) => void (store[k] = v), removeItem: (k: string) => void delete store[k] })
    const { importProgress, recordAnswer, getProgress } = await import('./progress')
    recordAnswer('qnewer', true, 0) // done in this browser after the backup was made
    const backup = { v: 2, lessons: { 'lx.first-steps': { seen: 1, done: 2 } }, predictions: { qolder: { first: { ok: false, at: 1 }, latest: { ok: true, at: 2 }, n: 2 } } }
    const r = importProgress(JSON.stringify(backup))
    const p = getProgress()
    expect(Object.keys(p.predictions).sort()).toEqual(['qnewer', 'qolder'])
    expect(p.lessons['lx.first-steps'].done).toBe(2)
    expect(r.answers).toBe(2)
    vi.unstubAllGlobals()
  })
  it('merges a v1 backup too: an old file never erases newer work (final review)', async () => {
    vi.resetModules()
    const store: Record<string, string> = {}
    vi.stubGlobal('localStorage', { getItem: (k: string) => store[k] ?? null, setItem: (k: string, v: string) => void (store[k] = v), removeItem: (k: string) => void delete store[k] })
    const { importProgress, recordAnswer, markLessonDone, getProgress } = await import('./progress')
    markLessonDone('lx.first-steps')
    recordAnswer('qnewer', true, 0)
    importProgress(JSON.stringify({ v: 1, lessons: { old: { seen: 1, done: 2 } }, predictions: { 'lesson:old:0': { ok: true, at: 3 } } }))
    const p = getProgress()
    expect(Object.keys(p.lessons).sort()).toEqual(['lx.first-steps', 'old'])
    expect(Object.keys(p.predictions)).toEqual(['qnewer'])
    expect(p.legacy?.predictions?.['lesson:old:0']).toBeTruthy() // kept aside, not credited
    expect(JSON.parse(store['osa.progress.v2']).lessons['lx.first-steps']).toBeTruthy() // and saved
    vi.unstubAllGlobals()
  })
})

describe('renamed route ids', () => {
  it('keeps the route of a learner who chose it under its old id', () => {
    expect(normalize({ version: 2, route: 'exam' }).route).toBe('new-role')
    expect(normalize({ version: 2, route: 'platform' }).route).toBe('platform')
  })
})

// Try again, Restart and Reset learning progress are three different things.
describe('repeating exercises keeps the honest record', () => {
  const browserStore = () => {
    const m = new Map<string, string>()
    return {
      m,
      get length() { return m.size },
      key: (i: number) => [...m.keys()][i] ?? null,
      getItem: (k: string) => m.get(k) ?? null,
      setItem: (k: string, v: string) => void m.set(k, v),
      removeItem: (k: string) => void m.delete(k),
    }
  }
  it('a retried answer becomes the latest; the first stays', async () => {
    vi.resetModules()
    vi.stubGlobal('localStorage', browserStore())
    const { recordAnswer, getProgress } = await import('./progress')
    recordAnswer('q1', false, 1)
    recordAnswer('q1', true, 0)
    recordAnswer('q1', false, 2)
    const r = getProgress().predictions.q1
    expect([r.first.ok, r.first.pick, r.latest.ok, r.latest.pick, r.n]).toEqual([false, 1, false, 2, 3])
    vi.unstubAllGlobals()
  })
  it('only the first guess is recorded: a guess after the answer was shown is not a prediction', async () => {
    vi.resetModules()
    vi.stubGlobal('localStorage', browserStore())
    const { recordGuess, getProgress } = await import('./progress')
    recordGuess('g', 2)
    recordGuess('g', 0)
    expect(getProgress().guesses.g.pick).toBe(2)
    vi.unstubAllGlobals()
  })
  it('restarting an incident clears its attempt only, and keeps what was revealed and every other fact', async () => {
    vi.resetModules()
    vi.stubGlobal('localStorage', browserStore())
    const { labUpdate, markLessonDone, recordAnswer, restartAttempt, getProgress, labStatus } = await import('./progress')
    markLessonDone('lesson-a')
    recordAnswer('q1', true, 0)
    labUpdate('inc.other', (l) => void (l.incident = { stage: 2, draft: 'other incident notes' }))
    labUpdate('inc.x', (l) => {
      l.incident = { stage: 3, hints: 2, draft: 'the image tag is wrong in the deployment', replays: ['0', '1'], nextHintAt: 5 }
      l.hints = 2
      l.revealed = 10
      l.diagnosis = 'the image tag is wrong in the deployment'
      l.selfCheck = { root: true, evidence: true, fix: true, at: 11 }
    })
    restartAttempt('inc.x')
    const p = getProgress()
    expect(p.labs['inc.x'].incident).toEqual({ stage: 0, hints: 0, rev: expect.any(Number) })
    expect(p.labs['inc.x'].selfCheck).toBeUndefined()
    expect(p.labs['inc.x'].diagnosis).toBeUndefined()
    expect([p.labs['inc.x'].revealed, p.labs['inc.x'].hints]).toEqual([10, 2]) // help received stays on record
    expect(labStatus(p.labs['inc.x'])).toBe('revealed')
    expect(p.labs['inc.other'].incident?.draft).toBe('other incident notes')
    expect(p.lessons['lesson-a'].done).toBeTruthy()
    expect(p.predictions.q1.latest.ok).toBe(true)
    vi.unstubAllGlobals()
  })
  it('Reset learning progress also clears the models\' predictions and challenges, and nothing else of the site', async () => {
    vi.resetModules()
    const s = browserStore()
    s.setItem('oa.sim.rollout.predict', 'b')
    s.setItem('oa.sim.rollout.challenges', 'c1')
    s.setItem('osa.theme', 'dark')
    vi.stubGlobal('localStorage', s)
    const { resetProgress, markLessonDone } = await import('./progress')
    markLessonDone('lesson-a')
    expect(resetProgress()).toEqual({ ok: true })
    expect([...s.m.keys()].filter((k) => k.startsWith('oa.sim.'))).toEqual([])
    expect(s.getItem('osa.theme')).toBe('dark')
    vi.unstubAllGlobals()
  })
})

describe('a restart before anything was saved', () => {
  it('records the new attempt, so an older copy imported later cannot bring the previous one back', async () => {
    vi.resetModules()
    const store: Record<string, string> = {}
    vi.stubGlobal('localStorage', { getItem: (k: string) => store[k] ?? null, setItem: (k: string, v: string) => void (store[k] = v), removeItem: (k: string) => void delete store[k] })
    const older = JSON.stringify({ v: 2, lessons: {}, predictions: {}, labs: { 'inc.y': { started: 5, steps: {}, incident: { stage: 3, hints: 1, draft: 'an old diagnosis from another device', replays: ['0'] } } } })
    const { restartAttempt, importProgress, getProgress } = await import('./progress')
    expect(getProgress().labs['inc.y']).toBeUndefined()
    restartAttempt('inc.y') // nothing of this incident was stored yet (a draft still waiting for its debounced save)
    expect(getProgress().labs['inc.y'].incident?.rev).toBeGreaterThan(0)
    importProgress(older)
    const l = getProgress().labs['inc.y']
    expect([l.incident?.stage, l.incident?.draft, l.incident?.replays]).toEqual([0, undefined, undefined])
    vi.unstubAllGlobals()
  })
})

describe('a restarted attempt survives merging an older copy', () => {
  it('importing an export made before the restart keeps the new attempt and the cumulative facts', async () => {
    vi.resetModules()
    const store: Record<string, string> = {}
    vi.stubGlobal('localStorage', { getItem: (k: string) => store[k] ?? null, setItem: (k: string, v: string) => void (store[k] = v), removeItem: (k: string) => void delete store[k] })
    const { labUpdate, restartAttempt, exportProgress, importProgress, getProgress } = await import('./progress')
    labUpdate('inc.x', (l) => {
      l.incident = { stage: 3, hints: 2, draft: 'the image tag is wrong in the deployment', replays: ['0', '1'] }
      l.hints = 2
      l.revealed = 10
      l.diagnosis = 'the image tag is wrong in the deployment'
      l.selfCheck = { root: true, evidence: true, fix: true, at: 11 }
    })
    const before = exportProgress() // an export from the first attempt, with no attempt revision (as every older export)
    expect(JSON.parse(before).labs['inc.x'].incident.rev).toBeUndefined()
    restartAttempt('inc.x')
    labUpdate('inc.x', (l) => void (l.incident = { ...l.incident, stage: 1, draft: 'second attempt' }))
    importProgress(before)
    const l = getProgress().labs['inc.x']
    expect([l.incident?.stage, l.incident?.hints, l.incident?.draft, l.incident?.replays]).toEqual([1, 0, 'second attempt', undefined])
    expect(l.selfCheck).toBeUndefined()
    expect(l.diagnosis).toBeUndefined()
    expect([l.revealed, l.hints]).toEqual([10, 2]) // cumulative facts still merge
    // and the other way round: a copy of the restarted attempt imported into the old one takes over
    const after = exportProgress()
    vi.resetModules()
    for (const k of Object.keys(store)) delete store[k]
    store['osa.progress.v2'] = before
    const fresh = await import('./progress')
    fresh.importProgress(after)
    expect(fresh.getProgress().labs['inc.x'].incident?.draft).toBe('second attempt')
    expect(fresh.getProgress().labs['inc.x'].selfCheck).toBeUndefined()
    vi.unstubAllGlobals()
  })
})

// An export made by an earlier version of the site, with real progress:
// a wrong check, a typed command with a hint then its solution shown, an order shown, a guess, a finished lesson, an
// incident in progress (two evidence commands replayed, a hint, a draft, at Diagnose), an incident revealed with a
// self-check, a challenge with a hint and its solution. It is imported over newer work in this browser that touches
// the same records; the expected values are written out here from the rule "facts are merged: the first answer is
// the earliest, the latest the most recent, a stage the furthest, replays and days the union; nothing newer is lost".
import baseline from './progress.baseline-export.json'

describe('importing an export made by the baseline site over newer local work', () => {
  const T = 1792369800000 // later than everything in the export
  const local = {
    v: 2,
    lessons: { 'd.services-dns': { seen: T }, 'lx.first-steps': { seen: T, done: T + 1 } },
    predictions: {
      q4bbc722ea3: { first: { ok: true, at: T, pick: 0 }, latest: { ok: true, at: T, pick: 0 }, n: 1 },
      'try:b.reconciliation:try-scale': { first: { ok: true, at: T, pick: 0 }, latest: { ok: true, at: T + 5, pick: 0 }, n: 1 },
    },
    labs: {
      'inc.dns-typo': { started: T, steps: {}, incident: { stage: 1, hints: 0, replays: ['1'] } },
      'ch.bounded-cleanup': { started: T, steps: {}, incident: { stage: 0, hints: 0 } }, // restarted here, after the export
    },
    days: ['2026-10-20'],
    xp: 50,
  }
  it('keeps every fact of both, with the literal values expected', async () => {
    vi.resetModules()
    const m = new Map<string, string>([['osa.progress.v2', JSON.stringify(local)]])
    vi.stubGlobal('localStorage', { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) })
    const { importProgress } = await import('./progress')
    expect(importProgress(JSON.stringify(baseline))).toEqual({ lessons: 4, answers: 3, labs: 3, saved: true })
    const p = JSON.parse(m.get('osa.progress.v2')!) // what a reload reads
    expect(p.lessons).toEqual({
      'b.reconciliation': { seen: 1792369715033, pos: 'check:recall-chain' },
      'f0.objects-api': { seen: 1792369716063, pos: 'check:recall-deployment' },
      'd.services-dns': { seen: 1792369717073, done: 1792369718229, pos: 'summary' },
      'lx.first-steps': { seen: T, done: T + 1 },
    })
    expect(p.predictions).toEqual({
      q4bbc722ea3: { first: { ok: false, at: 1792369715326, pick: 2 }, latest: { ok: true, at: T, pick: 0 }, n: 1 },
      // help on record: the first attempt asked for a hint (-2), then the solution was shown (-1)
      'try:b.reconciliation:try-scale': { first: { ok: false, at: 1792369715570, pick: -2 }, latest: { ok: true, at: T + 5, pick: 0 }, n: 2 },
      'order:f0.objects-api:order-owners': { first: { ok: false, at: 1792369716385, pick: 1 }, latest: { ok: false, at: 1792369716674, pick: -1, shown: true }, n: 2 },
    })
    expect(p.guesses).toEqual({ 'guess:q9bf21a3d0f': { at: 1792369715413, pick: 1 } })
    expect(p.labs['inc.dns-typo']).toEqual({
      started: 1792369718863, steps: {}, stepResults: {}, hints: 1,
      incident: { stage: 2, hints: 1, draft: 'The client asks for payments-web, but the Service is called web.', replays: ['0', '1', '2'], nextHintAt: 1792369735087 },
    })
    expect(p.labs['inc.broken-rollout']).toEqual({
      started: 1792369721430, steps: {}, revealed: 1792369721430,
      diagnosis: 'The new image tag does not exist, so the new pods never become ready.',
      selfCheck: { root: true, evidence: false, fix: false, at: 1792369721845 },
      incident: { stage: 3, draft: 'The new image tag does not exist, so the new pods never become ready.' },
    })
    // the newer restart stays a fresh attempt (stage 0, no hint shown in it); the help used before stays on record
    expect(p.labs['ch.bounded-cleanup']).toEqual({ started: 1792369722188, steps: {}, stepResults: {}, hints: 1, revealed: 1792369722321, incident: { stage: 0, hints: 0, replays: [] } })
    expect(p.cmds).toEqual(baseline.cmds)
    expect(p.days).toEqual(['2026-10-19', '2026-10-20'])
    expect(p.xp).toBe(50)
    expect(p.last).toEqual(baseline.last)
    vi.unstubAllGlobals()
  })
})
