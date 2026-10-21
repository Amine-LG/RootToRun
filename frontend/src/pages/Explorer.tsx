import { useEffect, useState } from 'react'
import { PageHead } from '../components/PageHead'
import { Empty, Panel } from '../components/ui'
import { t } from '../lib/i18n'
import { get } from '../lib/data'
import { go, useApp, usePoll } from '../lib/app'

export default function Explorer({ kind, ns, name }: { kind?: string; ns?: string; name?: string }) {
  const { status } = useApp()
  const reader = status?.identities?.reader?.connected
  const overview = usePoll(() => get('/api/explore/overview'), 0, [reader])
  const [kinds, setKinds] = useState<{ kind: string; namespaced: boolean }[]>([])
  const [list, setList] = useState<any>(null)
  const [obj, setObj] = useState<any>(null)
  const [filter, setFilter] = useState('')
  const [nsInput, setNsInput] = useState(ns || '')
  useEffect(() => {
    get('/api/explore/kinds').then(setKinds)
  }, [])
  useEffect(() => {
    setList(null)
    if (kind) get(`/api/explore/list?kind=${kind}${ns ? `&ns=${encodeURIComponent(ns)}` : ''}`).then(setList, (e) => setList({ ok: false, error: e.message }))
  }, [kind, ns])
  useEffect(() => {
    setObj(null)
    if (kind && name) get(`/api/explore/get?kind=${kind}&name=${encodeURIComponent(name)}${ns ? `&ns=${encodeURIComponent(ns)}` : ''}`).then(setObj)
  }, [kind, name, ns])
  const nav = (k?: string, n?: string, nm?: string) => go(`/explorer?${new URLSearchParams({ ...(k ? { kind: k } : {}), ...(n ? { ns: n } : {}), ...(nm ? { name: nm } : {}) })}`)
  const namespaced = kinds.find((k) => k.kind === kind)?.namespaced

  const ov = overview.data
  return (
    <div className="page explorer xp">
      <PageHead eyebrow={t('nav.cluster')} title="Cluster Explorer" lede={t('xp.explorerLede')} />
      {!reader && (
        <div className="banner warn">
          The explorer identity is not set up. <a href="/connections">Connections</a> explains what it creates and why.
        </div>
      )}
      {ov?.ok && !kind && (
        <div className="grid2">
          <Panel title={`Cluster ${ov.version}`} testid="overview">
            <dl className="kv">
              <dt>Platform</dt>
              <dd>
                {ov.platform.type} · control plane {ov.platform.controlPlaneTopology} · infra {ov.platform.infrastructureTopology}
              </dd>
              <dt>Network</dt>
              <dd>
                {ov.network.type} · pods {ov.network.clusterNetwork?.map((c: any) => c.cidr).join(', ')} · services {ov.network.serviceNetwork?.join(', ')}
              </dd>
              <dt>Scheduler</dt>
              <dd>
                profile {ov.scheduler.profile || 'LowNodeUtilization (default)'} · mastersSchedulable {String(ov.scheduler.mastersSchedulable)}
              </dd>
              <dt>Update history</dt>
              <dd>{ov.history.join(' · ')}</dd>
            </dl>
            {ov.nodes.map((n: any) => (
              <div key={n.name} className="node-card">
                <strong>
                  <a href="#" onClick={(e) => (e.preventDefault(), nav('Node', undefined, n.name))}>
                    node/{n.name}
                  </a>
                </strong>
                <div className="small">{n.status}</div>
                <div className="small muted">taints: {n.taints?.length ? n.taints.map((t: any) => `${t.key}:${t.effect}`).join(', ') : 'none'}</div>
              </div>
            ))}
          </Panel>
          <Panel title={`ClusterOperators (${ov.operators.length})`}>
            <table className="ops">
              <thead>
                <tr>
                  <th>Operator</th>
                  <th>Avail.</th>
                  <th>Prog.</th>
                  <th>Degr.</th>
                </tr>
              </thead>
              <tbody>
                {ov.operators.map((o: any) => (
                  <tr key={o.name} className={o.degraded === 'True' || o.available !== 'True' ? 'bad' : o.progressing === 'True' ? 'warn' : ''} title={o.message}>
                    <td>
                      <a href="#" onClick={(e) => (e.preventDefault(), nav('ClusterOperator', undefined, o.name))}>
                        {o.name}
                      </a>
                    </td>
                    <td>{o.available}</td>
                    <td>{o.progressing}</td>
                    <td>{o.degraded}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="small muted">Healthy: Available=True, Progressing=False, Degraded=False. Hover a row for the condition message.</p>
          </Panel>
        </div>
      )}
      {ov && !ov.ok && reader && <div className="banner bad">{ov.error}</div>}

      <Panel title="Browse objects">
        <div className="explore-bar">
          <select value={kind || ''} onChange={(e) => nav(e.target.value || undefined, kinds.find((k) => k.kind === e.target.value)?.namespaced ? nsInput || undefined : undefined)} aria-label="Kind" data-testid="kind">
            <option value="">kind…</option>
            {kinds.map((k) => (
              <option key={k.kind} value={k.kind}>
                {k.kind}
                {k.namespaced ? '' : ' (cluster)'}
              </option>
            ))}
          </select>
          {namespaced && (
            <form
              onSubmit={(e) => {
                e.preventDefault()
                nav(kind, nsInput || undefined)
              }}
            >
              <input value={nsInput} onChange={(e) => setNsInput(e.target.value)} placeholder="namespace (empty = all)" aria-label="Namespace" />
            </form>
          )}
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="filter names" aria-label="Filter" />
        </div>
        {!kind && <Empty>Pick a kind. Good starting points: ClusterOperator, Node, SecurityContextConstraints, Scheduler, StorageClass, Lease (namespace kube-system or openshift-kube-scheduler).</Empty>}
        {list && !list.ok && <div className="bad small">{list.error}</div>}
        {list?.ok && (
          <div className="obj-list" data-testid="obj-list">
            {list.items
              .filter((i: any) => !filter || i.name.includes(filter) || (i.namespace || '').includes(filter))
              .slice(0, 300)
              .map((i: any) => (
                <a key={(i.namespace || '') + i.name} href="#" className={name === i.name ? 'on' : ''} onClick={(e) => (e.preventDefault(), nav(kind, i.namespace || ns, i.name))}>
                  <span>
                    {i.namespace && <span className="muted">{i.namespace}/</span>}
                    {i.name}
                  </span>
                  <span className="small muted">{i.status}</span>
                </a>
              ))}
          </div>
        )}
      </Panel>
      {obj && (
        <Panel title={`${kind}/${name}`} testid="yaml">
          {obj.ok ? <pre className="yaml">{obj.yaml}</pre> : <div className="bad small">{obj.error}</div>}
        </Panel>
      )}
    </div>
  )
}
