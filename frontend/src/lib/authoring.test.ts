import { describe, expect, it } from 'vitest'
import { filterEntries, formatApiError, tokenFromFragment, type AuthorEntry } from './authoring'

describe('author token fragment', () => {
  it('decodes a URL token and replaces the stored token', () => {
    expect(tokenFromFragment('#token=new%2Bsecret%3D', 'old')).toEqual({ token: 'new+secret=', consumed: true })
  })
  it('retains the session token on reload and handles a missing token', () => {
    expect(tokenFromFragment('', 'saved')).toEqual({ token: 'saved', consumed: false })
    expect(tokenFromFragment('', null)).toEqual({ token: '', consumed: false })
    expect(tokenFromFragment('#section', 'saved')).toEqual({ token: 'saved', consumed: false })
  })
})

it('filters items by every search word across kind, title, id and path', () => {
  const entries: AuthorEntry[] = [
    { kind: 'lesson', id: 'o1.cli', title: 'Command line', file: 'en/lessons/cli.yaml' },
    { kind: 'module', id: 'apps', title: 'Applications', file: 'en/modules.yaml' },
  ]
  expect(filterEntries(entries, ' LESSON command cli.yaml ')).toEqual([entries[0]])
  expect(filterEntries(entries, '')).toEqual(entries)
  expect(filterEntries(entries, 'lesson applications')).toEqual([])
})

it('formats validation errors and request errors', () => {
  expect(formatApiError({ errors: ['Unknown concept', 'Section removed'] })).toBe('Unknown concept\nSection removed')
  expect(formatApiError('file changed')).toBe('file changed')
  expect(formatApiError([{ msg: 'missing field' }])).toContain('missing field')
})
