import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, cluster, loadMeta, type Curriculum, type Meta, type Status } from './data'
import { useLang } from './i18n'
import { relocate } from './router'
import { setAddresses } from './urls'

type Ctx = {
  meta: Meta | null
  cur: Curriculum | null
  status: Status | null
  lang: string
  live: boolean // a cluster is available and the learner identity is connected
  refreshStatus: () => Promise<void>
  error: string
}
const AppCtx = createContext<Ctx | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const lang = useLang()
  const [meta, setMeta] = useState<Meta | null>(null)
  const [cur, setCur] = useState<Curriculum | null>(null)
  const [status, setStatus] = useState<Status | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    loadMeta().then(setMeta, (e) => setError(String(e.message || e)))
  }, [])
  useEffect(() => {
    if (meta)
      api.curriculum(lang).then((c) => {
        // the addresses first: an old address (/lesson/<id>) is replaced before any page renders it
        setAddresses(c)
        relocate()
        setCur(c)
      }, (e) => setError(String(e.message || e)))
  }, [meta, lang])

  const refreshStatus = useCallback(async () => {
    if (meta?.mode !== 'cluster') return
    try {
      setStatus(await cluster.status(lang))
    } catch {
      setStatus(null)
    }
  }, [meta, lang])
  useEffect(() => {
    refreshStatus()
    if (meta?.mode !== 'cluster') return
    const t = window.setInterval(() => !document.hidden && refreshStatus(), 30000)
    return () => window.clearInterval(t)
  }, [refreshStatus, meta])

  const live = meta?.mode === 'cluster' && !!status?.identities?.learner?.connected
  return <AppCtx.Provider value={{ meta, cur, status, lang, live, refreshStatus, error }}>{children}</AppCtx.Provider>
}

export function useApp() {
  const c = useContext(AppCtx)
  if (!c) throw new Error('no app context')
  return c
}

export { navigate as go } from './router'

/** Load once per dependency change; returns data, error and a reload function. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [err, setErr] = useState('')
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let alive = true
    setErr('')
    load().then(
      (d) => alive && setData(d),
      (e) => alive && setErr(String(e?.message || e)),
    )
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])
  return { data, err, reload: () => setTick((x) => x + 1) }
}

/** Poll an async loader while mounted and the tab is visible (ms = 0: load once). */
export function usePoll<T>(load: () => Promise<T>, ms: number, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [err, setErr] = useState<string>('')
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let alive = true
    const run = async () => {
      if (document.hidden) return
      try {
        const d = await load()
        if (alive) {
          setData(d)
          setErr('')
        }
      } catch (e) {
        if (alive) setErr(String((e as Error).message || e))
      }
    }
    run()
    const id = ms > 0 ? window.setInterval(run, ms) : 0
    return () => {
      alive = false
      if (id) window.clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])
  return { data, err, reload: () => setTick((x) => x + 1) }
}
