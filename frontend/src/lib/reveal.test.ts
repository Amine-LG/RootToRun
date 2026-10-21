import { describe, expect, it } from 'vitest'
import { revealDelta } from './reveal'

// viewport: sticky header ends at 76px, window 900px tall; usable area 88..888 (12px breathing room)
const at = (top: number, height: number) => ({ top, bottom: top + height, height })

describe('revealDelta', () => {
  it('does not move when the content is fully visible', () => {
    expect(revealDelta(at(200, 300), 76, 900)).toBe(0)
  })
  it('scrolls the smallest distance that shows content that fits, keeping its start visible', () => {
    expect(revealDelta(at(700, 300), 76, 900)).toBe(112) // bottom 1000 -> 888
    expect(revealDelta(at(20, 300), 76, 900)).toBe(-68) // top 20 -> 88
  })
  it('never aligns tall content by its bottom edge: its start goes under the header', () => {
    expect(revealDelta(at(850, 2000), 76, 900)).toBe(762) // start 850 -> 88
    expect(revealDelta(at(-500, 2000), 76, 900)).toBe(-588)
  })
  it('leaves tall content alone when its start is already in the upper part of the screen', () => {
    expect(revealDelta(at(150, 2000), 76, 900)).toBe(0)
  })
})
