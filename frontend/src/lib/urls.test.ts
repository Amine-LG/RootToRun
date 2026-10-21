import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type { Curriculum } from './data'
import { Md } from './md'
import { continueTarget, resumeTarget } from './next'
import type { Progress } from './progress'
import { beginHref } from './routes'
import { canonical, detailKind, diagnosticHref, itemHref, labHref, lessonHref, refOf, resolve, setAddresses, trackHref } from './urls'

// A small curriculum with the addresses the server gives (backend/academy/urls.py)
const lesson = (id: string, module: string, path: string) => ({ id, title: id, module, mode: 'REAL_LAB' as const, minutes: 10, level: 1, concepts: [], prerequisites: [], labs: [], objective: '', path })
const cur = {
  tracks: [
    { id: 'linux', title: 'Linux', modules: ['m1'], path: '/learn/linux' },
    { id: 'admin2', title: 'OpenShift administration', modules: ['m2'], path: '/learn/platform-administration' },
    { id: 'practice', title: 'Practice arena', modules: ['m3'], path: '/learn/practice' },
  ],
  modules: [
    { id: 'm1', title: '', summary: '', lessons: ['lx.first-steps'] },
    { id: 'm2', title: '', summary: '', lessons: ['n.htpasswd-users'] },
    { id: 'm3', title: '', summary: '', lessons: [], labs: ['ch.ship-web-app'] },
  ],
  lessons: {
    'lx.first-steps': lesson('lx.first-steps', 'm1', '/learn/linux/your-first-minutes-in-a-shell'),
    'n.htpasswd-users': lesson('n.htpasswd-users', 'm2', '/learn/platform-administration/manage-local-users'),
  },
  concepts: {},
  labs: {
    'lab.rbac': { id: 'lab.rbac', kind: 'lab', title: 'Least privilege', path: '/labs/least-privilege-for-two-serviceaccounts' },
    'inc.dns-typo': { id: 'inc.dns-typo', kind: 'incident', title: 'Could not resolve host', path: '/incidents/could-not-resolve-host' },
    'ch.ship-web-app': { id: 'ch.ship-web-app', kind: 'challenge', title: 'Ship a web app', path: '/challenges/ship-a-web-app' },
  },
  diagnostics: {
    admin2: { track: 'admin2', title: 'Administration check', minutes: 30, count: 20, path: '/diagnostic/platform-administration' },
    practice: { track: 'admin2', title: 'Administration check', minutes: 30, count: 20, path: '/diagnostic/platform-administration' },
  },
} as unknown as Curriculum
const prog = (last?: string, lessons: Record<string, object> = {}, labs: Record<string, object> = {}) =>
  ({ lessons, labs, diagnostics: {}, last: last ? { href: last, title: 'T', at: 1 } : undefined }) as unknown as Progress

beforeAll(() => setAddresses(cur))
afterAll(() => setAddresses(null))

describe('readable addresses', () => {
  it('links use the address the server gives, never an id', () => {
    expect(lessonHref('n.htpasswd-users')).toBe('/learn/platform-administration/manage-local-users')
    expect(labHref('lab.rbac')).toBe('/labs/least-privilege-for-two-serviceaccounts')
    expect(labHref('inc.dns-typo')).toBe('/incidents/could-not-resolve-host')
    expect(labHref('ch.ship-web-app')).toBe('/challenges/ship-a-web-app')
    expect(trackHref('admin2')).toBe('/learn/platform-administration')
    expect(diagnosticHref('admin2')).toBe('/diagnostic/platform-administration')
    expect(itemHref('lx.first-steps')).toBe('/learn/linux/your-first-minutes-in-a-shell')
    expect(itemHref('inc.dns-typo')).toBe('/incidents/could-not-resolve-host')
    expect(beginHref({ id: 'r', title: '', who: '', promise: '', cluster: 'none', begin: { kind: 'diagnostic', id: 'admin2', label: '' }, steps: [] })).toBe('/diagnostic/platform-administration')
  })
  it('an address names what is there; a trailing slash (static hosts add one) changes nothing', () => {
    expect(resolve('/learn/platform-administration/manage-local-users')).toEqual({ kind: 'lesson', id: 'n.htpasswd-users' })
    expect(resolve('/learn/platform-administration/manage-local-users/')).toEqual({ kind: 'lesson', id: 'n.htpasswd-users' })
    expect(resolve('/learn/platform-administration')).toEqual({ kind: 'track', id: 'admin2' })
    expect(resolve('/incidents/could-not-resolve-host')).toEqual({ kind: 'lab', id: 'inc.dns-typo' })
    expect(resolve('/diagnostic/platform-administration')).toEqual({ kind: 'diagnostic', id: 'admin2' })
    expect(resolve('/labs/could-not-resolve-host')).toBeNull() // an incident is not a lab address
    expect(resolve('/lesson/n.htpasswd-users')).toBeNull() // old addresses are redirected, not served
    expect(resolve('/learn/admin2')).toBeNull()
  })
})

describe('old addresses keep working', () => {
  it('lead to the current address with the same query and #anchor', () => {
    expect(canonical('/lesson/n.htpasswd-users')).toBe('/learn/platform-administration/manage-local-users')
    expect(canonical('/lesson/n.htpasswd-users#idp')).toBe('/learn/platform-administration/manage-local-users#idp')
    expect(canonical('/lesson/n.htpasswd-users/?a=checks#idp')).toBe('/learn/platform-administration/manage-local-users?a=checks#idp')
    expect(canonical('/lab/inc.dns-typo?stage=investigate')).toBe('/incidents/could-not-resolve-host?stage=investigate')
    expect(canonical('/lab/lab.rbac?step=finish')).toBe('/labs/least-privilege-for-two-serviceaccounts?step=finish')
    expect(canonical('/lab/ch.ship-web-app')).toBe('/challenges/ship-a-web-app')
    expect(canonical('/learn/admin2')).toBe('/learn/platform-administration')
    expect(canonical('/course/admin2')).toBe('/learn/platform-administration')
    expect(canonical('/course')).toBe('/learn')
    expect(canonical('/diagnostic/admin2')).toBe('/diagnostic/platform-administration')
    expect(canonical('/challenges')).toBe('/challenges') // Practice's own list of challenges, not a redirect
  })
  it('a lesson that moved to another track is found by its slug', () => {
    expect(canonical('/learn/linux/manage-local-users#x')).toBe('/learn/platform-administration/manage-local-users#x')
  })
  it('leaves current, unknown and external addresses alone', () => {
    for (const h of ['/learn/linux', '/learn/linux/your-first-minutes-in-a-shell?a=checks', '/lesson/nope', '/handbook', 'https://example.org/lesson/n.htpasswd-users', '//evil.example/lesson/n.htpasswd-users', '#part'])
      expect(canonical(h)).toBe(h)
  })
  it('a saved "continue" place from before readable addresses still resumes, at the new address', () => {
    expect(refOf('/lesson/lx.first-steps?a=x')).toEqual({ kind: 'lesson', id: 'lx.first-steps' })
    expect(refOf('/learn/linux/your-first-minutes-in-a-shell')).toEqual({ kind: 'lesson', id: 'lx.first-steps' })
    expect(resumeTarget(cur, prog('/lesson/lx.first-steps', { 'lx.first-steps': { seen: 1 } }))?.href).toBe('/learn/linux/your-first-minutes-in-a-shell')
    const lab = resumeTarget(cur, prog('/lab/inc.dns-typo?stage=investigate'))
    expect(lab?.href).toBe('/incidents/could-not-resolve-host?stage=investigate')
    expect(lab?.kind).toBe('incident')
    expect(continueTarget(cur, prog())?.href).toBe('/learn/linux/your-first-minutes-in-a-shell')
  })
  it('links written in content with ids are rendered with readable addresses', () => {
    const html = renderToStaticMarkup(createElement(Md, { text: 'See [users](/lesson/n.htpasswd-users#idp), [the incident](/lab/inc.dns-typo) and [docs](https://docs.example/x).' }))
    expect(html).toContain('href="/learn/platform-administration/manage-local-users#idp"')
    expect(html).toContain('href="/incidents/could-not-resolve-host"')
    expect(html).toContain('href="https://docs.example/x"')
    expect(renderToStaticMarkup(createElement(Md, { text: '[x](javascript:alert(1))' }))).toContain('href="#"')
  })
})

describe('page chrome by address shape', () => {
  it('knows a detail page before content loads', () => {
    expect(detailKind('/learn/linux/anything')).toBe('lesson')
    expect(detailKind('/learn/linux')).toBeNull()
    expect(detailKind('/incidents/x')).toBe('lab')
    expect(detailKind('/incidents')).toBeNull()
    expect(detailKind('/lesson/a.b')).toBe('lesson')
  })
})
