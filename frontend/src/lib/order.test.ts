import { describe, expect, it } from 'vitest'
import { displayOrder } from './order'

describe('choice display order', () => {
  it('is a stable permutation', () => {
    const o = displayOrder('qabc', 4)
    expect([...o].sort()).toEqual([0, 1, 2, 3])
    expect(displayOrder('qabc', 4)).toEqual(o)
  })
  it('spreads an answer that authors always put second', () => {
    const where = [0, 0, 0]
    for (let k = 0; k < 3000; k++) where[displayOrder(`q${k.toString(16)}`, 3).indexOf(1)]++
    for (const n of where) expect(n).toBeGreaterThan(850)
  })
})
