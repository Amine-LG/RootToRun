import { useEffect, useState } from 'react'
import { CleanupPanel, EnvironmentPanel } from '../components/ClusterSafety'
import { cluster, get, post, type CleanupReport, type Environment } from '../lib/data'
import { useApp } from '../lib/app'
import { t } from '../lib/i18n'
import { MdInline } from '../lib/md'
import '../pages.css'

const gb = (b?: number) => (b ? `${(b / 1e9).toFixed(1)} GB` : '-')

export default function Connections() {
  const { status, refreshStatus } = useApp()
  const [plan, setPlan] = useState<any[]>([])
  const [phrase, setPhrase] = useState('')
  const [readerPhrase, setReaderPhrase] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState('')
  const [runs, setRuns] = useState<CleanupReport[] | null>(null)
  const [leftovers, setLeftovers] = useState(0)
  const [env, setEnv] = useState<Environment | null>(null)
  const [envVersion, setEnvVersion] = useState(0) // bumped after every connect or log-out: step 2 reloads
  useEffect(() => {
    get('/api/reader/plan').then((r) => setPlan(r.plan))
    cluster.cleanups().then(
      (r) => {
        setRuns(r.runs)
        setLeftovers((r.leftovers || []).length)
      },
      () => setRuns(null),
    )
  }, [])
  const ids = status?.identities
  const crc = status?.crc
  const attention = (runs || []).filter((r) => r.state !== 'clean').length + leftovers
  async function act(name: string, fn: () => Promise<any>) {
    setBusy(name)
    setMsg('')
    try {
      const r = await fn()
      if (r && r.ok === false) setMsg(r.reason || t('conn.failed'))
    } catch (e) {
      setMsg(String((e as Error).message))
    }
    setBusy('')
    refreshStatus()
    setEnvVersion((v) => v + 1)
  }
  const approved = env?.class === 'training'
  return (
    <div className="page pg pg-conn">
      <header className="pg-head">
        <div className="eyebrow">{t('conn.eyebrow')}</div>
        <h1>{t('conn.title')}</h1>
        <p className="pg-purpose">
          <MdInline text={t('conn.purpose')} />
        </p>
      </header>
      {msg && (
        <div className="banner bad" role="alert">
          {msg}
        </div>
      )}
      <section className="pg-sec" aria-labelledby="conn-ids">
        <h2 id="conn-ids">{t('conn.idsTitle')}</h2>
        <p className="pg-sub">{t('conn.idsSub')}</p>
        <div className="cn-steps">
          <section className="cn-id" data-testid="id-learner" aria-labelledby="conn-learner">
            <h3 id="conn-learner">
              <span className="cn-step-n">1</span> {t('conn.learnerTitle')}
            </h3>
            <p className="cn-state">{ids?.learner?.connected ? <span className="pill ok">{t('conn.connectedAs', { user: ids.learner.user || '' })}</span> : <span className="pill muted">{ids?.learner?.reason || t('conn.notConnected')}</span>}</p>
            <p className="cn-text">{t('conn.learnerText')}</p>
            <div className="cn-act">
              {ids?.learner?.connected ? (
                <button className="btn" onClick={() => act('l-out', () => post('/api/disconnect', { identity: 'learner' }))}>
                  {t('conn.logout')}
                </button>
              ) : (
                <button className="btn primary" disabled={!!busy} onClick={() => act('l-in', () => post('/api/connect', { identity: 'learner' }))} data-testid="connect-learner">
                  {busy === 'l-in' ? t('conn.connecting') : t('conn.connectLearner')}
                </button>
              )}
            </div>
          </section>

          <section className="cn-step" data-testid="step-approve" aria-labelledby="conn-approve">
            <h3 id="conn-approve">
              <span className="cn-step-n">2</span> {t('conn.approveTitle')}
            </h3>
            <EnvironmentPanel onChange={refreshStatus} onEnv={setEnv} version={envVersion} />
          </section>
          <section className="cn-id cn-elevated" data-testid="id-admin" aria-labelledby="conn-admin">
            <h3 id="conn-admin">
              <span className="cn-step-n">3</span> {t('conn.adminTitle')}
            </h3>
            <p className="cn-state">{ids?.admin?.connected ? <span className="pill warn">{t('conn.adminActive')}</span> : <span className="pill muted">{t('conn.notConnected')}</span>}</p>
            <p className="cn-text">{t('conn.adminText')}</p>
            <div className="cn-act">
              {ids?.admin?.connected ? (
                <button className="btn" onClick={() => act('a-out', () => post('/api/disconnect', { identity: 'admin' }))} data-testid="admin-logout">
                  {t('conn.logoutAdmin')}
                </button>
              ) : (
                <>
                  {!approved && <p className="small muted" data-testid="admin-needs-approval">{t('conn.adminNeedsApproval')}</p>}
                  <div className="row">
                    <input value={phrase} onChange={(e) => setPhrase(e.target.value)} placeholder="type: use kubeadmin" aria-label={t('conn.adminConfirm')} disabled={!approved} data-testid="admin-phrase" />
                    <button className="btn danger" disabled={!approved || phrase !== 'use kubeadmin' || !!busy} onClick={() => act('a-in', () => post('/api/connect', { identity: 'admin', confirm: phrase }))} data-testid="connect-admin">
                      {t('conn.connectAdmin')}
                    </button>
                  </div>
                </>
              )}
            </div>
          </section>
          <section className="cn-id" data-testid="id-reader" aria-labelledby="conn-reader">
            <h3 id="conn-reader">
              <span className="cn-step-n">4</span> {t('conn.readerTitle')}
            </h3>
            <p className="cn-state">{ids?.reader?.connected ? <span className="pill ok">{t('conn.connected')}</span> : <span className="pill muted">{ids?.reader?.reason || t('conn.notSetUp')}</span>}</p>
            <p className="cn-text">
              <MdInline text={t('conn.readerText')} />
            </p>
            <details className="cn-plan">
              <summary>{t('conn.planSummary')}</summary>
              <ul className="small">
                {plan.map((p, i) => (
                  <li key={i}>
                    <strong>{p.action}</strong> <code>{p.target}</code>: {p.why}
                  </li>
                ))}
              </ul>
              <p className="small muted">
                <MdInline text={t('conn.planRemove')} />
              </p>
            </details>
            <div className="cn-act">
              {ids?.admin?.connected ? (
                <div className="row">
                  <input value={readerPhrase} onChange={(e) => setReaderPhrase(e.target.value)} placeholder="type: create reader" aria-label={t('conn.readerConfirm')} />
                  <button className="btn" disabled={readerPhrase !== 'create reader' || !!busy} onClick={() => act('r', () => post('/api/reader/setup', { identity: 'admin', confirm: readerPhrase }))}>
                    {ids?.reader?.connected ? t('conn.readerRecreate') : t('conn.readerSetup')}
                  </button>
                </div>
              ) : (
                <p className="small muted">{t('conn.readerNeedsAdmin')}</p>
              )}
            </div>
          </section>

        </div>
      </section>

      <section className="pg-sec" aria-labelledby="conn-crc">
        <h2 id="conn-crc">{t('conn.crcTitle')}</h2>
        <div className="pg-card">
          <dl className="kv">
            <dt>{t('conn.crcVm')}</dt>
            <dd data-testid="crc-status">
              {crc?.crcStatus || t('conn.unknown')} / {crc?.openshiftStatus || t('conn.unknown')} {crc?.openshiftVersion}
            </dd>
            <dt>{t('conn.crcMemory')}</dt>
            <dd>{t('conn.crcOf', { used: gb(crc?.ramUsage), total: gb(crc?.ramSize) })}</dd>
            <dt>{t('conn.crcDisk')}</dt>
            <dd>{t('conn.crcOf', { used: gb(crc?.diskUsage), total: gb(crc?.diskSize) })}</dd>
            <dt>{t('conn.crcApi')}</dt>
            <dd>
              {status?.api ? <code>{status.api}</code> : '-'}
            </dd>
          </dl>
          <p className="small muted">
            <MdInline text={t('conn.crcNote')} />
          </p>
        </div>
      </section>

      <section className="pg-sec" aria-labelledby="conn-term">
        <h2 id="conn-term">{t('conn.termTitle')}</h2>
        <p className="pg-sub">{t('conn.termText')}</p>
        <pre className="code">{`eval $(crc oc-env)
oc login -u developer https://api.crc.testing:6443   # password: crc console --credentials
oc project academy-deploy`}</pre>
        <p className="small muted">{t('conn.termNote')}</p>
      </section>

      <details className="pg-fold cn-cleanup">
        <summary>
          <span>{t('conn.cleanupTitle')}</span>
          {runs && (attention > 0 ? <span className="pill warn">{t('conn.cleanupAttention', { n: attention })}</span> : runs.length > 0 && <span className="pill muted">{t('conn.cleanupRuns', { n: runs.length })}</span>)}
        </summary>
        <p className="small muted">{t('conn.cleanupText')}</p>
        <CleanupPanel />
      </details>
    </div>
  )
}
