import { describe, expect, it } from 'vitest'
import { duration } from './studytime'

describe('duration', () => {
  it('writes minutes below an hour to the nearest 5', () => {
    expect(duration(12)).toBe('10 min')
    expect(duration(44)).toBe('45 min')
    expect(duration(2)).toBe('5 min')
  })
  it('writes hours as plain decimals to the nearest half, never as fractions', () => {
    expect(duration(210)).toBe('about 3.5 h')
    expect(duration(450)).toBe('about 7.5 h')
    expect(duration(720)).toBe('about 12 h')
    expect(duration(60)).toBe('about 1 h')
    expect(duration(210, false)).toBe('3.5 h')
    for (let m = 55; m < 4000; m += 7) expect(duration(m)).toMatch(/^about \d+(\.5)? h$/)
  })
})
