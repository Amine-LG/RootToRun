// What the academy may do on the connected cluster, what it found, and what is left after cleanup.
// Everything here states facts from the backend: unknown stays "unknown", and nothing is called clean until the
// API server confirmed it.
import { useEffect, useRef, useState } from 'react'
import { cluster, type Capabilities, type CleanupReport, type Environment, type Preflight } from '../lib/data'
import { t } from '../lib/i18n'
import { MdInline } from '../lib/md'
import { Icon, Spinner } from './ui'

const yesNo = (v: boolean | null | undefined) => (v === true ? <span className="cap yes">{t('cap.yes')}</span> : v === false ? <span className="cap no">{t('cap.no')}</span> : <span className="cap unk">{t('cap.unknown')}</span>)

/** Step 2 of My cluster → Connections: whether the academy may change this cluster. It reloads whenever `version`
 * changes (an identity was connected or logged out), so connecting the learner shows the approval at once, and it
 * reports the state to the page (`onEnv`), which keeps the cluster-admin step closed until the cluster is approved. */
export function EnvironmentPanel({ onChange, onEnv, version = 0 }: { onChange?: () => void; onEnv?: (env: Environment) => void; version?: number }) {
  const [env, setEnv] = useState<Environment | null>(null)
  const [caps, setCaps] = useState<Capabilities | null>(null)
  const [ids, setIds] = useState<Record<string, { api: string; same_cluster: boolean }>>({})
  const [host, setHost] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  // only the newest answer counts: a slower, older request (from before a connect, log-out, approval or withdrawal)
  // must never put back a state that is no longer true
  const gen = useRef(0)
  const show = (next: Environment) => {
    setEnv(next)
    onEnv?.(next)
  }
  const load = (probe = false) => {
    const mine = ++gen.current
    return cluster.environment(probe).then(
      (r) => {
        if (mine !== gen.current) return
        show(r.env)
        setIds(r.identities)
        setCaps(r.capabilities ?? null) // a disconnected learner has no capabilities to show
      },
      (e) => {
        if (mine === gen.current) setMsg(String(e.message || e))
      },
    )
  }
  useEffect(() => {
    load(true)
  }, [version]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!env) return <Spinner />
  const approve = async () => {
    setBusy(true)
    setMsg('')
    try {
      const mine = ++gen.current // an answer still on its way describes the cluster before the approval
      const next = (await cluster.approve(host)).env
      if (mine !== gen.current) return // something newer happened meanwhile (a log-out, a reload)
      show(next)
      onChange?.()
      load(true)
    } catch (e) {
      setMsg(String((e as Error).message))
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className={`env-panel class-${env.class}`} data-testid="env-panel">
      <div className="env-panel-h">
        <Icon name={env.class === 'training' ? 'flask' : env.class === 'read-only' ? 'eye' : 'play'} size={18} />
        <strong>{t(`envclass.${env.class}` as 'envclass.training')}</strong>
        {env.api && <code>{env.api}</code>}
      </div>
      <p className="muted">{env.class === 'read-only' && !env.connected ? t('envclass.notConnectedText') : t(`envclass.${env.class}Text` as 'envclass.trainingText')}</p>
      {Object.entries(ids)
        .filter(([, v]) => !v.same_cluster)
        .map(([k, v]) => (
          <p key={k} className="banner bad">
            {t('env.mismatch', { identity: k, api: v.api })}
          </p>
        ))}
      {env.class === 'read-only' && (
        <div className="approve" data-testid="approve-block">
          {env.connected ? (
            <p>
              {env.crc ? t('env.crcDetected') : t('env.notCrc')} <MdInline text={t('env.approveHow', { host: env.host || '' })} />
            </p>
          ) : (
            <p className="small" data-testid="approve-needs-learner">{t('env.approveNeedsLearner')}</p>
          )}
          <div className="row">
            <input value={host} onChange={(e) => setHost(e.target.value)} placeholder={env.host || t('env.typeHost')} aria-label={t('env.typeHostLabel', { host: env.host || t('env.typeHost') })}
              disabled={!env.connected} data-testid="approve-host" />
            <button className="btn primary" disabled={!env.connected || busy || !host.trim()} onClick={approve} data-testid="approve">
              {t('env.approve')}
            </button>
          </div>
          {env.connected && !env.tls_verified && <p className="small warn-text">{t('env.noTls')}</p>}
        </div>
      )}
      {env.class === 'training' && (
        <p className="small">
          <button
            className="linkish"
            onClick={async () => {
              const mine = ++gen.current
              const next = (await cluster.revoke()).env
              if (mine !== gen.current) return
              show(next)
              onChange?.()
              load(true)
            }}
          >
            {t('env.revoke')}
          </button>
        </p>
      )}
      {msg && <p className="banner bad">{msg}</p>}
      {caps?.probed && (
        <details className="more">
          <summary>{t('cap.title')}</summary>
          <table className="cap-table">
            <tbody>
              <tr>
                <th>{t('cap.user')}</th>
                <td>{caps.user || t('cap.unknown')}</td>
              </tr>
              <tr>
                <th>{t('cap.kube')}</th>
                <td>{caps.kubernetes || t('cap.unknown')}</td>
              </tr>
              {Object.entries(caps.access || {}).map(([k, v]) => (
                <tr key={k}>
                  <th>{t(`cap.${k}` as 'cap.create-projects')}</th>
                  <td>{yesNo(v)}</td>
                </tr>
              ))}
              <tr>
                <th>{t('cap.storage')}</th>
                <td>
                  {caps.storage === null || caps.storage === undefined
                    ? t('cap.unknown')
                    : caps.storage.default
                      ? `${caps.storage.default.name} (reclaimPolicy ${caps.storage.default.reclaimPolicy})`
                      : t('cap.noDefault')}
                </td>
              </tr>
              <tr>
                <th>{t('cap.nodes')}</th>
                <td>{caps.nodes ?? t('cap.notVisible')}</td>
              </tr>
              {Object.entries(caps.apis || {}).map(([k, v]) => (
                <tr key={k}>
                  <th>
                    <code>{k}</code>
                  </th>
                  <td>{yesNo(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small muted">{t('cap.note')}</p>
        </details>
      )}
    </section>
  )
}

export function PreflightBox({ labId }: { labId: string }) {
  const [p, setP] = useState<Preflight | null>(null)
  useEffect(() => {
    cluster.preflight(labId).then(setP, () => setP(null))
  }, [labId])
  if (!p || p.class === 'practice') return null
  return (
    <div className={`preflight ${p.runnable ? 'ok' : 'no'}`} data-testid="preflight">
      <strong>{p.runnable ? t('pre.ok') : t('pre.no')}</strong>
      {(p.blockers.length > 0 || (p.unknown || []).length > 0) && (
        <ul>
          {p.blockers.map((b) => (
            <li key={b.req}>
              <Icon name="x" size={14} /> {b.why}
            </li>
          ))}
          {(p.unknown || []).map((b) => (
            <li key={b.req}>
              <Icon name="info" size={14} /> {b.why}
            </li>
          ))}
        </ul>
      )}
      {p.notes.map((n, i) => (
        <p key={i} className="small">
          {n}
        </p>
      ))}
      {!p.runnable && <p className="small muted">{t('pre.alternative')}</p>}
    </div>
  )
}

const PHASE_TONE: Record<string, string> = { gone: 'ok', failed: 'muted', reclaimed: 'ok', kept: 'muted', blocked: 'bad', replaced: 'bad', 'released-needs-admin': 'warn', 'not-visible': 'warn', deleting: 'info', unknown: 'warn', intent: 'warn', applied: 'info', bound: 'info' }

export function CleanupReportView({ rep, onRetry }: { rep: CleanupReport; onRetry?: () => void }) {
  return (
    <div className={`cleanup-rep state-${rep.state}`} data-testid="cleanup-report">
      <div className="row">
        <strong>{rep.run.lab_id}</strong>
        <span className={`pill ${rep.state === 'clean' ? 'ok' : rep.state === 'blocked' ? 'bad' : 'info'}`}>{t(`cleanup.${rep.state}` as 'cleanup.clean')}</span>
        {onRetry && rep.state !== 'clean' && (
          <button className="btn sm ghost" onClick={onRetry}>
            <Icon name="refresh" size={13} /> {t('cleanup.retry')}
          </button>
        )}
      </div>
      <ul className="cleanup-items">
        {rep.effects.map((e) => (
          <li key={e.id}>
            <span className={`pill ${PHASE_TONE[e.phase] || 'muted'}`}>{e.phase}</span> <code>{e.kind.toLowerCase()}/{e.name}</code> <span className="muted small">{e.detail}</span>
          </li>
        ))}
        {rep.volumes.map((v) => (
          <li key={v.pv}>
            <span className={`pill ${PHASE_TONE[v.phase] || 'muted'}`}>{v.phase}</span> <code>pv/{v.pv}</code> <span className="muted small">({v.namespace}/{v.claim}) {v.detail}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function CleanupPanel() {
  const [runs, setRuns] = useState<CleanupReport[] | null>(null)
  const [left, setLeft] = useState<{ name: string; phase: string; detail: string }[]>([])
  const [err, setErr] = useState('')
  const load = () =>
    cluster.cleanups().then(
      (r) => {
        setRuns(r.runs)
        setLeft(r.leftovers || [])
      },
      (e) => setErr(String(e.message || e)),
    )
  useEffect(() => {
    load()
  }, [])
  if (err) return <p className="banner bad">{err}</p>
  if (!runs) return <Spinner />
  return (
    <div className="cleanup-list">
      {!runs.length && <p className="muted">{t('cleanup.none')}</p>}
      {runs.map((r) => (
        <CleanupReportView key={r.run.id} rep={r} onRetry={() => cluster.retryCleanup(r.run.id).then(load)} />
      ))}
      {left.length > 0 && (
        <div className="cleanup-rep" data-testid="leftovers">
          <strong>{t('cleanup.leftovers')}</strong>
          <p className="small muted">{t('cleanup.leftoversText')}</p>
          <ul className="cleanup-items">
            {left.map((l) => (
              <li key={l.name}>
                <span className="pill warn">{l.phase}</span> <code>namespace/{l.name}</code> <span className="muted small">{l.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
