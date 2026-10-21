import { describe, expect, it } from 'vitest'
import { parseOutput, parseTable, shortCell, visibleColumns } from './parse'
import { commandResult } from './result'

describe('retained output parsing', () => {
  it('preserves empty aligned cells and removes only wholly empty columns in wrap mode', () => {
    const tb = parseTable(['NAME  READY  STATUS   PORTS    AGE  EXTRA', 'web   2/2    Running  8080/TCP  3m', 'api   1/1    Pending  443/TCP   4s'])!
    expect(tb.head).toEqual(['NAME', 'READY', 'STATUS', 'PORTS', 'AGE', 'EXTRA'])
    expect(tb.rows[0]).toEqual(['web', '2/2', 'Running', '8080/TCP', '3m', ''])
    expect(visibleColumns(tb).head).not.toContain('EXTRA')
    expect(visibleColumns(tb, false).head).toContain('EXTRA')
  })
  it('refuses grid-spilling rows and does not mistake YAML/traces for tables', () => {
    expect(parseTable(['NAME  AGE', 'a-name-over-boundaries  2m'])).toBeNull()
    expect(parseTable(['apiVersion: v1', 'kind: Service'])).toBeNull()
    expect(parseTable(['Traceback (most recent call last):', '  File "example.py", line 7'])).toBeNull()
  })
  it('mixed multi-table blocks retain line offsets for a single preview budget', () => {
    const raw = 'Header\n\nNAME  AGE\nweb   2m\n\napiVersion: v1\n  data: value\n\nNODE  CPU\ncrc   4\n'
    const blocks = parseOutput(raw)
    expect(blocks.filter(b => b.table).map(b => b.start)).toEqual([2, 8])
    expect(blocks.find(b => b.start === 5)?.lines).toEqual(['apiVersion: v1', '  data: value'])
    expect(raw.endsWith('\n')).toBe(true)
  })
  it('statuses, ports, ages and ready values never split, unlike long resource identifiers', () => {
    for (const [header, value] of [['READY','2/2'], ['PORTS','8080/TCP'], ['STATUS','CrashLoopBackOff'], ['AGE','31m']]) expect(shortCell(header, value)).toBe(true)
    expect(shortCell('NAME', 'a-very-long-generated-pod-name')).toBe(false)
    expect(shortCell('PORTS', '80/TCP,443/TCP,8080/TCP')).toBe(false)
    expect(shortCell('STATUS', 'a long diagnostic explanation')).toBe(false)
  })
})
describe('CommandBlock result contract', () => {
  it('keeps expected failure distinct from execution error and unexpected failures', () => {
    expect(commandResult('recording', 'fail', 7)).toEqual({ source: 'recording', expected: 'fail', status: 'fail', matched: true })
    expect(commandResult('live', 'ok', 1).matched).toBe(false)
    expect(commandResult('simulation', 'any', 1).matched).toBe(true)
    for (const code of [undefined, -1, 124]) expect(commandResult('live', 'any', code)).toMatchObject({ status: 'error', matched: false })
    expect(commandResult('live', 'fail', 1, 'not_connected').matched).toBe(false)
  })
})
