// Bridge for scripts/grading_oracle.py: grades a batch of typed commands with the same rule as the practice step
// (an accepted form as typed, or an equivalent command). Runs only when the oracle sets ORACLE_IN.
import { it } from 'vitest'
import { readFileSync, writeFileSync } from 'node:fs'
import { equivalentCommand, normCommand, shellWords } from '../src/lib/match'

const input = process.env.ORACLE_IN
it.skipIf(!input)('grades the oracle batch', () => {
  const batch = JSON.parse(readFileSync(input!, 'utf8')) as { typed: string; accept: string[] }[]
  const out = batch.map(({ typed, accept }) => {
    const n = normCommand(typed)
    const hit = accept.find((a) => normCommand(a) === n) ?? accept.find((a) => equivalentCommand(typed, a))
    const words = shellWords(typed)
    return { accepted: hit !== undefined, via: hit ?? null, words: words ? words.map((w) => w.v) : null }
  })
  writeFileSync(process.env.ORACLE_OUT!, JSON.stringify(out))
}, 600_000)
