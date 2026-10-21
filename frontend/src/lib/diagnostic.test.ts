import { describe, expect, it } from 'vitest'
import type { Curriculum, Diagnostic } from './data'
import { classify, ordered } from './diagnostic'

const cur = {
  tracks: [{ id: 't', title: 'T', modules: ['m1', 'm2'] }],
  modules: [
    { id: 'm1', title: 'One', summary: '', lessons: ['a', 'b'] },
    { id: 'm2', title: 'Two', summary: '', lessons: [], labs: ['inc.x'] },
  ],
  lessons: {},
  labs: {},
} as unknown as Curriculum

const item = (id: string, targets: string[]) => ({ id, targets, prompt: id, evidence: '', choices: ['x', 'y'], answer: 1, feedback: ['', ''], explain: '' })
const d: Diagnostic = { track: 't', title: '', intro: '', minutes: 5, items: [item('q3', ['inc.x', 'b']), item('q1', ['a']), item('q2', ['a', 'inc.x']), item('q4', ['b'])] }
const ans = (pick: number, conf: 0 | 1 | 2) => ({ pick, conf, ok: pick === 1, at: 1 })

describe('diagnostic classification', () => {
  it('orders items by the path, not by the file', () => {
    expect(ordered(cur, d).map((i) => i.id)).toEqual(['q1', 'q2', 'q4', 'q3'])
  })

  it('a miss means study, a guess means review, sure answers mean shown', () => {
    const r = classify(cur, d, { started: 1, answers: { q1: ans(1, 2), q2: ans(0, 1), q4: ans(1, 0), q3: ans(1, 1) } })
    expect(r.byTarget.a.verdict).toBe('study')
    expect(r.byTarget.b.verdict).toBe('review')
    expect(r.byTarget['inc.x'].verdict).toBe('shown')
    expect(r.right).toBe(3)
    expect(r.answered).toBe(4)
  })

  it('flags confident mistakes, counts "I don\'t know" as a miss but not as confident', () => {
    const r = classify(cur, d, { started: 1, answers: { q1: ans(0, 2), q4: { pick: -1, conf: 0, ok: false, at: 1 } } })
    expect(r.byTarget.a.confidentWrong).toBe(1)
    expect(r.byTarget.b.verdict).toBe('study')
    expect(r.byTarget.b.confidentWrong).toBe(0)
  })

  it('a topic with unanswered items is only partly assessed, never shown', () => {
    const r = classify(cur, d, { started: 1, answers: { q1: ans(1, 2) } })
    expect(r.byTarget.a.verdict).toBe('partial')
  })

  it('unanswered targets stay unassessed, and modules count only their own items', () => {
    const r = classify(cur, d, { started: 1, answers: { q1: ans(1, 1) } })
    expect(r.byTarget['inc.x'].verdict).toBe('unassessed')
    expect(r.modules.map((m) => [m.id, m.total, m.answered, m.right])).toEqual([
      ['m1', 3, 1, 1],
      ['m2', 1, 0, 0],
    ])
  })

  it('suggests secondary targets for missed or guessed items, never ones already listed as primary', () => {
    const r = classify(cur, d, { started: 1, answers: { q2: ans(0, 1), q3: ans(1, 0) } })
    expect(r.practise).toEqual([]) // inc.x and b are primary targets themselves
  })
})
