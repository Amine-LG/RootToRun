import { beforeEach, describe, expect, it, vi } from 'vitest'

const { create, tokenize } = vi.hoisted(() => ({ create: vi.fn(), tokenize: vi.fn() }))
vi.mock('shiki/core', () => ({ createHighlighterCoreSync: create }))

beforeEach(() => {
  vi.resetModules()
  create.mockReset()
  tokenize.mockReset()
})

const source = 'metadata:\n  name: web # comment\n\n'
const plain = source.split('\n').map((s) => s ? [{ c: '', s }] : [])

describe('grammar failure fallback', () => {
  it('keeps exact plain rows if the regex engine cannot initialise', async () => {
    create.mockImplementation(() => { throw new Error('engine unavailable') })
    const { highlight } = await import('./highlight')
    expect(highlight('yaml', source)).toEqual(plain)
    expect(highlight('json', source)).toEqual(plain)
  })

  it('keeps exact plain rows if tokenisation throws or loses characters', async () => {
    create.mockReturnValue({ codeToTokensBase: tokenize })
    tokenize.mockImplementationOnce(() => { throw new Error('grammar unavailable') })
    const { highlight } = await import('./highlight')
    expect(highlight('yaml', source)).toEqual(plain)
    tokenize.mockReturnValue([[{ content: 'incomplete' }]])
    expect(highlight('yaml', source)).toEqual(plain)
  })

  it('does not initialise grammars for shell, plain or oversized input', async () => {
    const { highlight } = await import('./highlight')
    expect(highlight('shell', 'oc get pods')[0][0]).toEqual({ c: 'bin', s: 'oc' })
    expect(highlight('plain', source)).toEqual(plain)
    const long = 'x'.repeat(2001)
    expect(highlight('yaml', long)).toEqual([[{ c: '', s: long }]])
    expect(create).not.toHaveBeenCalled()
  })
})
