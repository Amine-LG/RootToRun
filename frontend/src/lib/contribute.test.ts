import { describe, expect, it } from 'vitest'
import { SIMS } from '../sims'
import index from '../sims/index.ts?raw'
import { DIAGRAMS } from './diagrams'
import { editTargets, editUrl, formsFor, hasRepo, MODEL_SOURCES, reportUrl, sectionOf, type PageContext } from './contribute'

const m = { repo: 'https://github.com/example/example', branch: 'main', version: '1.0.0 (abc1234)' }
const params = (u: string) => Object.fromEntries(new URL(u).searchParams)

describe('contribution links', () => {
  it('need a repository on github.com, without credentials, query or fragment', () => {
    expect(hasRepo({})).toBe(false)
    expect(hasRepo(m)).toBe(true)
    expect(hasRepo({ repo: 'https://github.com@evil.example/o/r' })).toBe(false)
    expect(hasRepo({ repo: 'https://github.com/o/r?x=1' })).toBe(false)
    expect(hasRepo({ repo: 'https://github.com/o/r#x' })).toBe(false)
    expect(hasRepo({ repo: 'javascript:alert(1)' })).toBe(false)
  })
  it('edit a file of the repository and nothing outside it', () => {
    expect(editUrl(m, 'content/en/lessons/o1-flow.yaml')).toBe('https://github.com/example/example/edit/main/content/en/lessons/o1-flow.yaml')
    expect(editUrl(m, '../secret/x.yaml')).toBeNull()
    expect(editUrl(m, 'content//x.yaml')).toBeNull()
  })
  it('report with the page facts, a relative address and nothing else', () => {
    const c: PageContext = { type: 'lab', id: 'lab.x', title: 'A & B', area: 'Run apps', source: 'content/en/labs/x.yaml' }
    const u = reportUrl(m, 'content', c, '/labs/x?token=secret#frag', 'step s2')
    expect(u.startsWith('https://github.com/example/example/issues/new?')).toBe(true)
    expect(params(u)).toEqual({
      template: 'content-problem.yml', title: '[Guided lab] A & B: ', 'content-type': 'Guided lab', 'content-id': 'lab.x', 'content-title': 'A & B',
      area: 'Run apps', section: 'step s2', 'page-url': '/labs/x', 'site-version': '1.0.0 (abc1234)',
    })
    expect(params(reportUrl(m, 'website', c, 'https://evil.example/x'))['page-url']).toBeUndefined() // only a relative path
    expect(params(reportUrl(m, 'website', null, '/labs/x/'))['page-url']).toBe('/labs/x')
    expect(params(reportUrl(m, 'website', null, '/me'))).toEqual({ template: 'ui-bug.yml', title: '[Website] ', 'page-url': '/me', 'site-version': '1.0.0 (abc1234)' })
  })
  it('read the section from the anchor or a step, never free text', () => {
    expect(sectionOf('#where-am-i', '')).toBe('where-am-i')
    expect(sectionOf('', '?step=s3&from=x')).toBe('step s3')
    expect(sectionOf('', '?stage=fix')).toBe('stage fix')
    expect(sectionOf('#a b<script>', '?step=<x>')).toBe('')
    expect(sectionOf('#%E0%A4%A', '')).toBe('')
  })
  it('offer the command form where there are commands', () => {
    expect(formsFor('lesson')).toEqual(['content', 'command', 'website'])
    expect(formsFor('model')).toEqual(['content', 'website'])
    expect(formsFor(null)).toEqual(['website'])
  })
})

describe('edit targets', () => {
  // The model code is the file each SIMS entry's component is imported from (sims/index.ts), read here from that file's
  // import lines rather than from MODEL_SOURCES.
  // either quote, an optional semicolon: a formatting choice is not a different import (as tests/sources_oracle.py)
  const fileOf = Object.fromEntries([...index.matchAll(/^\s*import\s+(\w+)\s+from\s+(['"])\.\/([\w-]+)\2\s*;?\s*$/gm)].map((x) => [x[1], `${x[3]}.tsx`]))
  const componentOf = Object.fromEntries([...index.matchAll(/\bid:\s*(['"])([\w-]+)\1\s*,[\s\S]*?\bComponent:\s*(\w+)\b/g)].map((x) => [x[2], x[3]]))
  it('every model edits the file of its own component, then the catalogue', () => {
    expect(SIMS.length).toBeGreaterThan(0)
    for (const s of SIMS) {
      const want = `frontend/src/sims/${fileOf[componentOf[s.id]]}`
      expect(editTargets({ type: 'model', id: s.id, title: s.title }).map((e) => e.path), s.id).toEqual([want, 'frontend/src/sims/index.ts'])
    }
    expect(Object.keys(MODEL_SOURCES).sort()).toEqual(SIMS.map((s) => s.id).sort()) // no stale entry
  })
  it('a diagram edits the diagram data; a model that does not exist edits nothing', () => {
    expect(DIAGRAMS.length).toBeGreaterThan(0)
    expect(editTargets({ type: 'diagram', id: DIAGRAMS[0].id, title: '' }).map((e) => e.path)).toEqual(['frontend/src/lib/diagrams.ts'])
    expect(editTargets({ type: 'model', id: 'nope', title: '' })).toEqual([])
  })
  it('content edits its source; without one there is nothing to edit', () => {
    expect(editTargets({ type: 'lesson', id: 'n.x', title: '', source: 'content/en/lessons/x.yaml' })).toEqual([{ key: 'lesson', path: 'content/en/lessons/x.yaml' }])
    expect(editTargets({ type: 'incident', id: 'inc.x', title: '', source: 'content/en/incidents/x.yaml' })[0].spoiler).toBe(true)
    expect(editTargets({ type: 'lesson', id: 'n.x', title: '', source: null })).toEqual([])
    expect(editTargets({ type: 'commands', id: 'commands', title: '' })).toEqual([])
    expect(editTargets({ type: 'path', id: 'k', title: '', sources: { tracks: 'content/en/tracks.yaml', modules: 'content/en/modules.yaml' } }).map((e) => e.path))
      .toEqual(['content/en/tracks.yaml', 'content/en/modules.yaml'])
  })
})
