import { createContext, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { AccountSync } from '../lib/account-sync'
import { useApp } from '../lib/app'
import { t } from '../lib/i18n'
import { normalize, useProgress, type Progress } from '../lib/progress'
import { merge } from '../lib/sync'

const SyncContext = createContext<AccountSync | null>(null)
const consentKey = (sync: AccountSync) => `osa.sync.${sync.account?.sync_key}`
export function AccountSyncProvider({ children }: { children: ReactNode }) {
  const { meta } = useApp()
  const [sync, setSync] = useState<AccountSync | null>(null)
  useEffect(() => {
    if (!meta?.accounts || meta.mode === 'static') return
    const engine = new AccountSync()
    setSync(engine)
    let alive = true
    const start = async () => {
      await engine.start()
      if (!alive || !engine.account?.sync_key) return
      try { if (sessionStorage.getItem(consentKey(engine)) === 'yes') engine.activate() } catch { /* confirmation remains available */ }
    }
    void start()
    const resume = () => { if (engine.active) void engine.sync(); else if (engine.status === 'offline') void start() }
    window.addEventListener('online', resume)
    window.addEventListener('focus', resume)
    return () => { alive = false; engine.stop(); window.removeEventListener('online', resume); window.removeEventListener('focus', resume) }
  }, [meta?.accounts, meta?.mode])
  return <SyncContext.Provider value={sync}>{children}</SyncContext.Provider>
}
const counts = (p: Progress) => t('sync.counts', { lessons: Object.keys(p.lessons).length, questions: Object.keys(p.predictions).length, labs: Object.keys(p.labs).length, cards: Object.keys(p.cards).length, days: p.days.length })
function Panel({ sync }: { sync: AccountSync }) {
  useSyncExternalStore(sync.subscribe, sync.snapshot)
  const local = useProgress()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [acting, setActing] = useState(false)
  const combined = sync.remote ? merge(local, normalize(sync.remote.progress)) : null
  const act = async (path: string, method: 'POST' | 'DELETE') => {
    setActing(true)
    try {
      try { sessionStorage.removeItem(consentKey(sync)) } catch { /* optional */ }
      await sync.action(path, method)
      setConfirmDelete(false)
    } catch { /* engine exposes the failure; local progress is retained */ }
    finally { setActing(false) }
  }
  return <section aria-labelledby="sync-title">
    <h2 id="sync-title">{t('sync.title')}</h2>
    <p>{t('sync.privacy')}</p>
    <p role="status" aria-live="polite">{t(`sync.${sync.status}`)}</p>
    {sync.account?.signed_in ? <>
      <p>{t('sync.signedIn', { provider: sync.account.provider })}</p>
      {!sync.active && sync.remote && combined && <>
        <p>{t('sync.previewHelp')}</p>
        <table><thead><tr><th>{t('sync.copy')}</th><th>{t('sync.contains')}</th></tr></thead><tbody>
          <tr><th scope="row">{t('sync.local')}</th><td>{counts(local)}</td></tr>
          <tr><th scope="row">{t('sync.server')}</th><td>{counts(normalize(sync.remote.progress))}</td></tr>
          <tr><th scope="row">{t('sync.combined')}</th><td>{counts(combined)}</td></tr>
        </tbody></table>
        <button className="btn primary" onClick={() => {
          try { sessionStorage.setItem(consentKey(sync), 'yes') } catch { /* this page can still sync */ }
          sync.activate()
        }}>{t('sync.approve')}</button>
      </>}
      <div className="row">
        <a className="btn" href="/api/me/export" download>{t('sync.export')}</a>
        <button className="btn" disabled={acting} onClick={() => void act('/api/auth/logout', 'POST')}>{t('sync.logout')}</button>
        {!confirmDelete ? <button className="btn danger" disabled={acting} onClick={() => setConfirmDelete(true)}>{t('sync.delete')}</button> : <>
          <span>{t('sync.deleteHelp')}</span>
          <button className="btn danger" disabled={acting} onClick={() => void act('/api/me', 'DELETE')}>{t('sync.deleteConfirm')}</button>
          <button className="btn" onClick={() => setConfirmDelete(false)}>{t('ui.cancel')}</button>
        </>}
      </div>
    </> : <a className="btn" href="/api/auth/login">{t('sync.login')}</a>}
    {(sync.status === 'error' || sync.status === 'offline') && <button className="btn" onClick={() => sync.active ? void sync.sync() : void sync.start()}>{t('sync.retry')}</button>}
  </section>
}
export function SyncPanel() {
  const sync = useContext(SyncContext)
  return sync ? <Panel sync={sync} /> : null
}
