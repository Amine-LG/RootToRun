import { describe, expect, it } from 'vitest'
import type { Curriculum, Route } from './data'
import type { Progress } from './progress'
import { beginHref, buildsOn, daysAway, nextOnRoute, routeLessons, routeModules, territoryOnRoute } from './routes'

const lesson = (id: string, module: string) => ({ id, title: id, module, mode: 'LOCAL_SIMULATION' as const, minutes: 10, level: 1, concepts: [], prerequisites: [], labs: [], objective: '' })
const cur = {
  tracks: [
    { id: 'linux', title: 'Linux', tagline: '', level: '', audience: '', summary: '', outcome: '', modules: ['m1', 'm2'] },
    { id: 'k8s', title: 'K8s', tagline: '', level: '', audience: '', summary: '', outcome: '', modules: ['m3', 'm4'] },
  ],
  modules: [
    { id: 'm1', title: '', summary: '', lessons: ['a', 'b'] },
    { id: 'm2', title: '', summary: '', lessons: ['c'] },
    { id: 'm3', title: '', summary: '', lessons: ['d'] },
    { id: 'm4', title: '', summary: '', lessons: ['e', 'gone'] },
  ],
  lessons: { a: lesson('a', 'm1'), b: lesson('b', 'm1'), c: lesson('c', 'm2'), d: lesson('d', 'm3'), e: lesson('e', 'm4') },
  concepts: {},
  labs: {},
  cases: [],
  runbooks: [],
} as unknown as Curriculum
const route = (steps: string[]): Route => ({ id: 'r', title: '', who: '', promise: '', cluster: 'none', begin: { kind: 'lesson', id: 'a', label: '' }, steps })
const prog = (lessons: Record<string, object> = {}, days: string[] = []) => ({ lessons, days }) as unknown as Progress

describe('routes', () => {
  it('expands track steps into their modules, in order, without duplicates', () => {
    expect(routeModules(cur, route(['linux', 'm3', 'm1']))).toEqual(['m1', 'm2', 'm3'])
    expect(routeLessons(cur, route(['m4', 'linux']))).toEqual(['e', 'a', 'b', 'c'])
  })
  it('classifies territories as on, partly on or off a route', () => {
    expect(territoryOnRoute(cur, route(['linux']), 'linux')).toBe('on')
    expect(territoryOnRoute(cur, route(['m3']), 'k8s')).toBe('part')
    expect(territoryOnRoute(cur, route(['m3']), 'linux')).toBe('off')
    expect(territoryOnRoute(cur, null, 'linux')).toBeNull()
  })
  it('finds the next unfinished lesson on the route, counting skipped reading as finished', () => {
    const r = route(['linux', 'k8s'])
    expect(nextOnRoute(cur, prog(), r)?.id).toBe('a')
    expect(nextOnRoute(cur, prog({ a: { done: 1 }, b: { skipped: 1 } }), r)?.id).toBe('c')
    expect(nextOnRoute(cur, prog({ a: { done: 1 }, b: { done: 1 }, c: { done: 1 }, d: { done: 1 }, e: { done: 1 } }), r)).toBeNull()
  })
  it('says which courses a course builds on, falling back to the one before it', () => {
    expect(buildsOn(cur, 'linux')).toEqual([])
    expect(buildsOn(cur, 'k8s')).toEqual(['linux'])
    expect(buildsOn(cur, 'start')).toEqual([]) // known, but its prerequisite is not in this curriculum
  })
  it('measures the time away from the last study day', () => {
    expect(daysAway(prog({}, []))).toBeNull()
    expect(daysAway(prog({}, ['2026-01-01', '2026-01-10']), new Date(2026, 0, 31))).toBe(21)
  })
  it('links the first step of a route', () => {
    expect(beginHref({ ...route([]), begin: { kind: 'diagnostic', id: 'admin1', label: '' } })).toBe('/diagnostic/admin1')
    expect(beginHref({ ...route([]), begin: { kind: 'track', id: 'platform', label: '' } })).toBe('/learn/platform')
  })
})
