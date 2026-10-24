import { afterEach, describe, expect, it, vi } from 'vitest'
import { ChunkError, entryIn, failedFile, mayReload, probe, reloadHelps, reloadOnce, retrying } from './chunks'

const here = 'https://roottorun.example/learn/a'

describe('failedFile', () => {
  it('reads the file Chromium, Firefox and Vite name, and only the site\'s own', () => {
    expect(failedFile(new TypeError('Failed to fetch dynamically imported module: https://roottorun.example/assets/Lesson-C5x.js'), 'js', here)).toBe('/assets/Lesson-C5x.js')
    expect(failedFile(new TypeError('error loading dynamically imported module: https://roottorun.example/assets/Lab-1.js?retry=1'), 'js', here)).toBe('/assets/Lab-1.js')
    expect(failedFile(new Error('Unable to preload CSS for https://roottorun.example/assets/sims-B.css'), 'css', here)).toBe('/assets/sims-B.css')
    expect(failedFile(new TypeError('Importing a module script failed.'), 'js', here)).toBeNull() // Safari: no name
    expect(failedFile(new TypeError('Failed to fetch dynamically imported module: https://elsewhere.example/assets/x.js'), 'js', here)).toBeNull()
    expect(failedFile(new Error('Unable to preload CSS for https://roottorun.example/assets/sims-B.css'), 'js', here)).toBeNull()
  })
})

function browser({ online = true, path = '/learn/a', storage = true } = {}) {
  const store: Record<string, string> = {}
  const reload = vi.fn()
  vi.stubGlobal('navigator', { onLine: online })
  vi.stubGlobal('location', { pathname: path, href: `https://roottorun.example${path}`, reload })
  vi.stubGlobal('sessionStorage', storage
    ? { getItem: (k: string) => store[k] ?? null, setItem: (k: string, v: string) => void (store[k] = v) }
    : { getItem: () => { throw new Error('denied') }, setItem: () => { throw new Error('denied') } })
  return { store, reload }
}
afterEach(() => vi.unstubAllGlobals())

describe('one automatic reload', () => {
  it('reloads once per address, then never within a minute', async () => {
    const { reload } = browser()
    expect(mayReload()).toBe(true)
    expect(await reloadOnce()).toBe(true)
    expect(reload).toHaveBeenCalledTimes(1)
    expect(mayReload()).toBe(false) // the same address again: the recovery panel instead
    vi.stubGlobal('location', { pathname: '/learn/a/', reload }) // the same page after a host's trailing-slash redirect
    expect(mayReload()).toBe(false)
    vi.stubGlobal('location', { pathname: '/labs/b', reload })
    expect(mayReload()).toBe(true) // another address may be reloaded for
  })
  it('does not reload a page the learner moved to while the failed files were refreshed', async () => {
    const { reload } = browser()
    const moved = () => (vi.stubGlobal('location', { pathname: '/me', href: 'https://roottorun.example/me', reload }), true)
    expect(await reloadOnce(moved)).toBe(false) // another address by the time the reload would happen
    expect(await reloadOnce(() => false)).toBe(false) // the page that failed has gone (navigation, Try again)
    expect(reload).not.toHaveBeenCalled()
  })
  it('allows a reload again after a minute', () => {
    const { store } = browser()
    store['osa.reloadedFor'] = JSON.stringify({ path: '/learn/a', at: Date.now() - 61_000 })
    expect(mayReload()).toBe(true)
  })
  it('never reloads offline or without sessionStorage', async () => {
    browser({ online: false })
    expect(mayReload()).toBe(false)
    const { reload } = browser({ storage: false })
    expect(mayReload()).toBe(false)
    expect(await reloadOnce()).toBe(false)
    expect(reload).not.toHaveBeenCalled()
  })
})

describe('retrying', () => {
  it('rejects with a ChunkError naming the attempt and the file, and still asks while the browser says offline', async () => {
    browser({ online: false }) // some systems report offline while the network works: the import is attempted
    const load = vi.fn(() => Promise.reject(new TypeError('Failed to fetch dynamically imported module: https://roottorun.example/assets/X-1.js')))
    const again = retrying(load)
    const first = await again().catch((e) => e)
    expect(first).toBeInstanceOf(ChunkError)
    expect([first.attempt, first.file]).toEqual([0, '/assets/X-1.js'])
    expect(load).toHaveBeenCalledTimes(1)
    load.mockImplementationOnce(() => Promise.resolve({ ok: 1 }) as never)
    await expect(again()).resolves.toEqual({ ok: 1 })
    expect(load).toHaveBeenCalledTimes(2)
  })
})

describe('probe and reloadHelps', () => {
  const answer = (status: number, type = 'text/javascript') => vi.fn(() => Promise.resolve(new Response(null, { status, headers: { 'content-type': type } })))
  it('reads a deployment, a file still served, a site that answers and no answer', async () => {
    browser()
    vi.stubGlobal('fetch', answer(404, 'text/html'))
    expect(await probe('/assets/X-1.js')).toBe('replaced')
    vi.stubGlobal('fetch', answer(200, 'text/html')) // a host that answers every address with its index page
    expect(await probe('/assets/X-1.js')).toBe('replaced')
    vi.stubGlobal('fetch', answer(200))
    expect(await probe('/assets/X-1.js')).toBe('served')
    vi.stubGlobal('document', { querySelector: () => null })
    expect(await probe(null)).toBe('answers') // the site answers without naming an entry script
    vi.stubGlobal('fetch', answer(503))
    expect(await probe('/assets/X-1.js')).toBe('unreachable')
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))))
    expect(await probe('/assets/X-1.js')).toBe('unreachable')
  })
  it('without a file name (Safari), compares the entry script the site\'s index names with the one running', async () => {
    browser()
    vi.stubGlobal('document', { querySelector: () => ({ src: 'https://roottorun.example/assets/index-Old1.js' }) })
    const index = (entry: string) => vi.fn(() => Promise.resolve(new Response(`<script src="/theme.js"></script><script type="module" crossorigin src="${entry}"></script>`, { status: 200, headers: { 'content-type': 'text/html' } })))
    vi.stubGlobal('fetch', index('/assets/index-Old1.js'))
    expect(await probe(null)).toBe('served') // the same deployment: the network failed, no reload for that
    vi.stubGlobal('fetch', index('/assets/index-New2.js'))
    expect(await probe(null)).toBe('replaced') // a new deployment
    expect(entryIn('<script src=x.js></script><script crossorigin type="module" src=\'/assets/index-A.js\'>', 'https://r.example/a')).toBe('/assets/index-A.js')
    expect(entryIn('<p>no script</p>', 'https://r.example/')).toBeNull()
  })
  it('reloads only when the server says it helps', () => {
    const first = new ChunkError(new Error('x'), 0, '/assets/X-1.js')
    const retried = new ChunkError(new Error('x'), 1, '/assets/X-1.js')
    expect(reloadHelps(first, 'replaced')).toBe(true)
    expect(reloadHelps(first, 'answers')).toBe(true)
    expect(reloadHelps(first, 'served')).toBe(false) // the network dropped once: Try again is enough
    expect(reloadHelps(retried, 'served')).toBe(true) // the browser remembers the failure: only a reload helps
    expect(reloadHelps(retried, 'unreachable')).toBe(false)
  })
})
