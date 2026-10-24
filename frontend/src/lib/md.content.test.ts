// @ts-nocheck: test helper; uses node modules (child_process, fs) and the project has no @types/node
// Every string of the course content goes through the Markdown renderer without throwing: the text of every page,
// including what a page shows only after a click (a diagnostic's questions, a lesson's "Go deeper" panel), which the
// browser check of every page (tests/e2e/test_mobile_overflow.py) does not open. A string that is not Markdown renders
// as text, so checking every string checks every Markdown field.
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ROOT, venvPython } from './cmdfmt.equiv'
import { Md } from './md'

function contentStrings(): string[] {
  const py = `
import sys, json, glob, yaml
out = set()
def walk(x):
    if isinstance(x, dict):
        for v in x.values(): walk(v)
    elif isinstance(x, list):
        for v in x: walk(v)
    elif isinstance(x, str) and x.strip():
        out.add(x)
for f in sorted(glob.glob(sys.argv[1] + '/content/en/**/*.yaml', recursive=True)):
    walk(yaml.load(open(f, encoding='utf-8').read(), Loader=yaml.BaseLoader) or [])
print(json.dumps(sorted(out)))
`
  const venv = venvPython()
  const py3 = process.env.ACADEMY_PYTHON || (existsSync(venv) ? venv : 'python3')
  return JSON.parse(execFileSync(py3, ['-I', '-c', py, ROOT], { encoding: 'utf8', maxBuffer: 256 << 20 }))
}

describe('the course content', () => {
  it('every string renders through Md without throwing', () => {
    const strings = contentStrings()
    expect(strings.length).toBeGreaterThan(5000)
    const failures: string[] = []
    for (const text of strings) {
      try {
        renderToStaticMarkup(createElement(Md, { text }))
      } catch (e) {
        failures.push(`${String(e).slice(0, 120)} <- ${text.slice(0, 160)}`)
      }
    }
    expect(failures).toEqual([])
  }, 120_000)
})
