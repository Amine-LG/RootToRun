import { getProgress, normalize, replaceProgress, subscribeProgress, type Progress } from './progress'
import { canonical, merge } from './sync'

export type Account = { signed_in: boolean; provider: string; display_name?: string; sync_key?: string }
export type Copy = { progress: Progress | null; version: number; updated?: number }
export type SyncStatus = 'loading' | 'signedOut' | 'preview' | 'syncing' | 'synced' | 'offline' | 'merged' | 'error' | 'storage'
export class AccountSync {
  account: Account | null = null
  remote: Copy | null = null
  status: SyncStatus = 'loading'
  active = false
  private listeners = new Set<() => void>()
  private revision = 0
  private timer: ReturnType<typeof setTimeout> | undefined
  private busy = false
  private dirty = false
  private applying = false
  private generation = 0
  private abort = new AbortController()
  private unsubscribe: (() => void) | undefined
  constructor(private fetcher: typeof fetch = fetch, private delay = 700) {}
  subscribe = (f: () => void) => { this.listeners.add(f); return () => { this.listeners.delete(f) } }
  snapshot = () => this.revision
  private notify() { this.revision++; this.listeners.forEach(f => f()) }
  private setStatus(status: SyncStatus) { this.status = status; this.notify() }
  private async request(path: string, init?: RequestInit) {
    const response = await this.fetcher(path, { cache: 'no-store', credentials: 'same-origin', signal: this.abort.signal, ...init })
    if (response.status === 401) { this.account = null; this.active = false; this.setStatus('signedOut') }
    if (!response.ok && response.status !== 409) throw new Error(`HTTP ${response.status}`)
    return response
  }
  async start() {
    const generation = this.generation
    try {
      const account: Account = await (await this.request('/api/me')).json()
      if (generation !== this.generation) return
      this.account = account
      if (!account.signed_in) { this.setStatus('signedOut'); return }
      const remote: Copy = await (await this.request('/api/me/progress')).json()
      if (generation !== this.generation) return
      this.remote = remote
      this.setStatus('preview')
    } catch (e) { if (generation === this.generation) this.failed(e) }
  }
  activate() {
    if (!this.account?.signed_in || !this.remote || this.active) return
    this.active = true
    this.unsubscribe = subscribeProgress(() => { if (!this.applying) this.schedule() })
    void this.sync()
  }
  schedule = () => {
    if (!this.active) return
    this.dirty = true
    clearTimeout(this.timer)
    this.timer = setTimeout(() => void this.sync(), this.delay)
  }
  private failed(e: unknown) {
    if (this.status === 'signedOut') return
    this.setStatus(e instanceof TypeError || (typeof navigator !== 'undefined' && !navigator.onLine) ? 'offline' : 'error')
  }
  async sync() {
    if (!this.active) return
    if (this.busy) { this.dirty = true; return }
    const generation = this.generation
    this.busy = true
    this.dirty = false
    this.setStatus('syncing')
    let conflict = false
    let saved = true
    try {
      const account: Account = await (await this.request('/api/me')).json()
      if (generation !== this.generation || !this.active) return
      if (!account.signed_in || account.sync_key !== this.account?.sync_key) {
        this.stop(); this.abort = new AbortController(); this.remote = null
        await this.start()
        return
      }
      const scope = { 'X-Academy-Account': this.account!.sync_key! }
      let remote: Copy = await (await this.request('/api/me/progress', { headers: scope })).json()
      for (let attempt = 0; attempt < 5; attempt++) {
        if (generation !== this.generation || !this.active) return
        const combined = merge(getProgress(), normalize(remote.progress))
        this.applying = true
        try { saved = replaceProgress(combined) && saved } finally { this.applying = false }
        const sent = canonical(getProgress())
        const response = await this.request('/api/me/progress', { method: 'PUT',
          headers: { ...scope, 'Content-Type': 'application/json', 'X-Academy': '1', 'If-Match': `"${remote.version}"` }, body: JSON.stringify(getProgress()) })
        const copy: Copy = await response.json()
        if (generation !== this.generation || !this.active) return
        this.remote = copy
        if (response.status === 409) { conflict = true; remote = copy; continue }
        this.setStatus(!saved ? 'storage' : conflict ? 'merged' : 'synced')
        // Changes made while the upload was in flight must be uploaded next.
        if (canonical(getProgress()) !== sent) this.dirty = true
        return
      }
      this.setStatus('error')
    } catch (e) { if (generation === this.generation) this.failed(e) }
    finally {
      this.busy = false
      if (this.active && this.dirty) this.schedule()
    }
  }
  stop() {
    this.active = false; this.generation++; clearTimeout(this.timer)
    this.unsubscribe?.(); this.unsubscribe = undefined; this.abort.abort()
  }
  async action(path: string, method: 'POST' | 'DELETE') {
    this.stop()
    this.abort = new AbortController()
    try {
      await this.request(path, { method, headers: { 'X-Academy': '1', ...(this.account?.sync_key ? { 'X-Academy-Account': this.account.sync_key } : {}) } })
      this.account = null; this.remote = null; this.setStatus('signedOut')
    } catch (e) { this.failed(e); throw e }
  }
}
