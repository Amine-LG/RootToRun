import { describe, expect, it } from 'vitest'
import { splitRow } from './md'

describe('table rows', () => {
  it('splits on pipes outside code only', () => {
    expect(splitRow('| a | b |')).toEqual(['a', 'b'])
    expect(splitRow('| `a || b` | run b if a fails |')).toEqual(['`a || b`', 'run b if a fails'])
    expect(splitRow('| x \\| y | z |')).toEqual(['x | y', 'z'])
  })
})
