// @ts-nocheck: the last test uses node modules (child_process, path); the project has no @types/node
// Commands checked against the real oc client by scripts/grading_oracle.py: near misses of accepted answers that the
// client itself rejects must never be accepted, and those it treats identically must be.
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { venvPython } from './cmdfmt.equiv'
import { equivalentCommand, normCommand } from './match'
import fixtures from './oracle.fixtures.json'

const grade = (typed: string, accept: string[]) =>
  accept.some((a) => normCommand(a) === normCommand(typed) || equivalentCommand(typed, a))

describe(`commands checked against the real client (${fixtures.client})`, () => {
  it('rejects what the client rejects', () => {
    const wrong = fixtures.rejected.filter((f) => grade(f.typed, f.accept))
    expect(wrong.map((f) => `${f.step}: ${f.typed} (${f.client})`)).toEqual([])
    expect(fixtures.rejected.length).toBeGreaterThan(100)
  })
  it('accepts what the client treats the same', () => {
    const missed = fixtures.equivalent.filter((f) => !grade(f.typed, f.accept))
    expect(missed.map((f) => `${f.step}: ${f.typed}`)).toEqual([])
  })
  // The fixtures keep the accepted answers of the day they were recorded; lessons change after that. A command the
  // client rejected must not become accepted through a later edit of the step's current answers either.
  it('rejects what the client rejects, against the lessons as they are now', () => {
    const ROOT = resolve(import.meta.dirname, '../../..')
    const py = `
import glob, json, sys, yaml
out = {}
def walk(x):
    if isinstance(x, dict):
        if isinstance(x.get('id'), str) and isinstance(x.get('accept'), list):
            out.setdefault(x['id'], []).extend(a for a in x['accept'] if isinstance(a, str))
        for v in x.values(): walk(v)
    elif isinstance(x, list):
        for v in x: walk(v)
for f in sorted(glob.glob(sys.argv[1] + '/content/en/**/*.yaml', recursive=True)):
    walk(yaml.load(open(f, encoding='utf-8').read(), Loader=yaml.BaseLoader) or [])
print(json.dumps(out))
`
    const current: Record<string, string[]> = JSON.parse(execFileSync(venvPython(), ['-I', '-c', py, ROOT], { encoding: 'utf8', env: { ...process.env, KUBECONFIG: '/nonexistent' } }))
    const known = fixtures.rejected.filter((f) => current[f.step])
    expect(known.length).toBe(fixtures.rejected.length) // every fixture still names a step that exists
    const wrong = known.filter((f) => grade(f.typed, current[f.step]))
    expect(wrong.map((f) => `${f.step}: ${f.typed} (${f.client})`)).toEqual([])
  }, 120000) // reading every content file takes seconds
})
