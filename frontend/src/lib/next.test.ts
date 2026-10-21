import { describe, expect, it } from 'vitest'
import type { Curriculum, Route } from './data'
import type { Progress } from './progress'
import { continueTarget, lessonBeside, nextLesson, nextUnread, resumeTarget } from './next'

const lesson = (id: string, module: string) => ({ id, title: id, module, mode: 'LOCAL_SIMULATION' as const, minutes: 10, level: 1, concepts: [], prerequisites: [], labs: [], objective: '' })
const cur = {
  tracks: [
    { id: 'linux', title: 'Linux', tagline: '', level: '', audience: '', summary: '', outcome: '', modules: ['m1'] },
    { id: 'k8s', title: 'K8s', tagline: '', level: '', audience: '', summary: '', outcome: '', modules: ['m2', 'm3', 'm4'] },
  ],
  modules: [
    { id: 'm1', title: '', summary: '', lessons: ['a', 'b'] },
    { id: 'm2', title: '', summary: '', lessons: ['c'] },
    { id: 'm3', title: '', summary: '', lessons: ['d'] },
    { id: 'm4', title: '', summary: '', lessons: ['e'] },
  ],
  lessons: { a: lesson('a', 'm1'), b: lesson('b', 'm1'), c: lesson('c', 'm2'), d: lesson('d', 'm3'), e: lesson('e', 'm4') },
  concepts: {},
  labs: { 'lab.x': { id: 'lab.x', kind: 'lab', title: 'X' } },
} as unknown as Curriculum
// a route that skips Linux and module m3
const route: Route = { id: 'r', title: '', who: '', promise: '', cluster: 'none', begin: { kind: 'lesson', id: 'c', label: '' }, steps: ['m2', 'm4'] }
const prog = (lessons: Record<string, object> = {}, last?: string) => ({ lessons, labs: {}, diagnostics: {}, last: last ? { href: last, title: last } : undefined }) as unknown as Progress

describe('one rule for every Continue', () => {
  it('resumes the last place only while it is unfinished', () => {
    expect(continueTarget(cur, prog({ b: { seen: 1 } }, '/lesson/b'))?.href).toBe('/lesson/b')
    expect(continueTarget(cur, prog({ b: { done: 1 } }, '/lesson/b'))?.href).toBe('/lesson/a') // finished: never "continue" it
    expect(continueTarget(cur, prog({ b: { done: 1 } }, '/lesson/b'))?.resume).toBe(false)
  })
  it('follows the chosen route, not the whole course, once the last place is finished', () => {
    expect(continueTarget(cur, prog({ c: { done: 1 } }, '/lesson/c'), route)?.href).toBe('/lesson/e')
    expect(continueTarget(cur, prog({}, undefined), route)?.href).toBe('/lesson/c') // nothing started: the route's begin
    expect(continueTarget(cur, prog({}, undefined), route)?.why).toBe('begin')
    expect(continueTarget(cur, prog({ a: { done: 1 } }), route)?.why).toBe('route')
    expect(continueTarget(cur, prog({ c: { done: 1 }, e: { done: 1 } }), route)).toBeNull() // route read: practice next, not Linux
    expect(continueTarget(cur, prog({}, undefined))?.why).toBe('course')
  })
  it('resumes a lab worked on, not one only opened', () => {
    const p = (labs: object) => ({ ...prog({ a: { done: 1 } }, '/lab/lab.x'), labs }) as unknown as Progress
    expect(continueTarget(cur, p({}))?.href).toBe('/lesson/b')
    expect(continueTarget(cur, p({ 'lab.x': { verdict: 'failed', verdictAt: 2 } }))?.href).toBe('/lab/lab.x')
    const inc = { ...prog({ a: { done: 1 } }, '/lab/lab.x?stage=investigate'), labs: {} } as unknown as Progress
    expect(continueTarget(cur, inc)?.href).toBe('/lab/lab.x?stage=investigate') // an investigation under way
  })
  it('resumes a restarted incident whose new attempt is being investigated', () => {
    const c = { ...cur, labs: { ...cur.labs, 'inc.y': { id: 'inc.y', kind: 'incident', title: 'Y' } } } as unknown as Curriculum
    const p = (incident: object) => ({ ...prog({ a: { done: 1 } }, '/lab/inc.y?stage=investigate'), labs: { 'inc.y': { revealed: 1, hints: 2, incident } } }) as unknown as Progress
    expect(continueTarget(c, p({ stage: 1, hints: 0, rev: 5 }))?.href).toBe('/lab/inc.y?stage=investigate')
    expect(continueTarget(c, p({ stage: 0, hints: 0, rev: 5 }))?.href).toBe('/lesson/b') // restarted, not begun again
  })
  it('sends the end-of-lesson button past lessons already read', () => {
    expect(nextUnread(cur, 'a', null, prog({ b: { skipped: 1 } }))?.id).toBe('c')
  })
  it('puts the diagnostic plan before the route', () => {
    expect(continueTarget(cur, prog({}), route, cur.lessons.d)?.href).toBe('/lesson/d')
  })
  it('resumes within one course only when the last lesson belongs to it', () => {
    expect(resumeTarget(cur, prog({ c: { seen: 1 } }, '/lesson/c'), 'k8s')?.href).toBe('/lesson/c')
    expect(resumeTarget(cur, prog({ c: { seen: 1 } }, '/lesson/c'), 'linux')).toBeNull()
    expect(nextLesson(cur, prog({ a: { done: 1 } }), 'linux')?.id).toBe('b')
  })
  it('gives previous and next along the route when the lesson is on it, else along the course', () => {
    expect(lessonBeside(cur, 'c', route, 1)?.id).toBe('e')
    expect(lessonBeside(cur, 'e', route, -1)?.id).toBe('c')
    expect(lessonBeside(cur, 'c', null, 1)?.id).toBe('d')
    expect(lessonBeside(cur, 'b', route, 1)?.id).toBe('c') // not on the route: course order
    expect(lessonBeside(cur, 'a', null, -1)).toBeNull()
  })
})
