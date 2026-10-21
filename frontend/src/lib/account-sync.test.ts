import { afterEach, describe, expect, it, vi } from 'vitest'
import { AccountSync } from './account-sync'
import { getProgress, normalize, replaceProgress } from './progress'

const copy = (version: number, lessons = {}) => ({ version, progress: normalize({ v: 2, lessons }) })
function api() {
  let remote = copy(0)
  let fail = false
  let conflicts = 0
  const writes: { version: string; body: unknown }[] = []
  const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (fail) throw new TypeError('Failed to fetch')
    if (url === '/api/me') return Response.json({ signed_in: true, provider: 'Fake', sync_key: 'key' })
    if (init?.method === 'PUT') {
      writes.push({ version: (init.headers as Record<string, string>)['If-Match'], body: JSON.parse(init.body as string) })
      if (conflicts-- > 0) { remote = copy(remote.version + 1, { remote: { done: 2 } }); return Response.json(remote, { status: 409 }) }
      remote = { version: remote.version + 1, progress: JSON.parse(init.body as string) }
    }
    return Response.json(remote)
  }) as unknown as typeof fetch
  return { fetcher, writes, setFail: (v: boolean) => { fail = v }, conflict: () => { conflicts = 1 } }
}
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })
describe('account sync lifecycle', () => {
  const setup = () => {
    vi.stubGlobal('localStorage', { getItem: () => null, setItem: vi.fn() })
    replaceProgress(normalize({ v: 2, lessons: { local: { seen: 1 } } }))
    const server = api()
    return { server, engine: new AccountSync(server.fetcher, 5) }
  }
  it('reads a preview without uploading or changing progress before consent', async () => {
    const { server, engine } = setup()
    await engine.start()
    expect(engine.status).toBe('preview'); expect(server.writes).toHaveLength(0)
    expect(getProgress().lessons.local.seen).toBe(1)
    engine.stop()
  })
  it('merges a 409 server copy and retries with its version', async () => {
    const { server, engine } = setup()
    await engine.start(); server.conflict(); engine.activate()
    await vi.waitFor(() => expect(engine.status).toBe('merged'))
    expect(server.writes.map(w => w.version)).toEqual(['"0"', '"1"'])
    expect(getProgress().lessons).toEqual({ local: { seen: 1, done: undefined, skipped: undefined, pos: undefined }, remote: { seen: undefined, done: 2, skipped: undefined, pos: undefined } })
    engine.stop()
  })
  it('debounces changes and recovers from a disconnected network', async () => {
    const { server, engine } = setup()
    await engine.start(); engine.activate()
    await vi.waitFor(() => expect(engine.status).toBe('synced'))
    server.setFail(true)
    replaceProgress(normalize({ v: 2, lessons: { a: { seen: 3 } } }))
    await vi.waitFor(() => expect(engine.status).toBe('offline'))
    expect(getProgress().lessons.a.seen).toBe(3)
    server.setFail(false); await engine.sync()
    expect(engine.status).toBe('synced'); expect(getProgress().lessons.local.seen).toBe(1)
    const n = server.writes.length
    replaceProgress(normalize({ ...getProgress(), xp: 1 })); replaceProgress(normalize({ ...getProgress(), xp: 2 }))
    await vi.waitFor(() => expect(server.writes.length).toBe(n + 1))
    engine.stop()
  })
  it('preserves changes made during an in-flight upload', async () => {
    const { server } = setup()
    let edited = false
    const fetcher: typeof fetch = async (url, init) => {
      if (init?.method === 'PUT' && !edited) {
        edited = true
        replaceProgress(normalize({ ...getProgress(), lessons: { ...getProgress().lessons, during: { seen: 99 } } }))
      }
      return server.fetcher(url, init)
    }
    const engine = new AccountSync(fetcher, 5)
    await engine.start(); engine.activate()
    await vi.waitFor(() => expect(server.writes.length).toBe(2))
    expect((server.writes[1].body as { lessons: object }).lessons).toHaveProperty('during')
    engine.stop()
  })
  it('cancels pending writes when signed out or deleted and keeps local progress', async () => {
    const { server, engine } = setup()
    await engine.start(); engine.activate()
    await vi.waitFor(() => expect(engine.status).toBe('synced'))
    const n = server.writes.length
    engine.schedule(); await engine.action('/api/auth/logout', 'POST')
    expect(engine.active).toBe(false); expect(engine.status).toBe('signedOut')
    await new Promise(r => setTimeout(r, 20))
    expect(server.writes).toHaveLength(n); expect(getProgress().lessons.local).toBeDefined()
  })
})

it('requires a new preview if another tab changes the account cookie', async () => {
  vi.stubGlobal('localStorage', { setItem: vi.fn() })
  replaceProgress(normalize({ v: 2, lessons: { local: { done: 1 } } }))
  let key = 'first-account'
  let writes = 0
  const fetcher: typeof fetch = async (url, init) => {
    if (url === '/api/me') return Response.json({ signed_in: true, provider: 'Fake', sync_key: key })
    if (init?.method === 'PUT') writes++
    return Response.json(copy(0))
  }
  const engine = new AccountSync(fetcher)
  await engine.start(); engine.activate()
  await vi.waitFor(() => expect(engine.status).toBe('synced'))
  const previous = writes
  key = 'second-account'
  await engine.sync()
  expect(engine.active).toBe(false); expect(engine.status).toBe('preview')
  expect(writes).toBe(previous)
  engine.stop()
})
