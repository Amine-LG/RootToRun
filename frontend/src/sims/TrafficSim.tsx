import { useEffect, useMemo, useRef, useState } from 'react'
import { CLUSTER_IP, DEFAULT_TRAFFIC, NAMESPACE, POLICY_TEXT, endpointSlice, sendRequest, type Hop, type NetPolicyMode, type TrafficConfig, type TrafficPod, type TrafficResult } from './models'
import { Btn, Chip, Code, NumField, Panel, SelectField, SimIcon, SimShell, TextField, Toggle, useAnnouncer, useReducedMotion, type Challenge, type ModelScope, type PredictSpec } from './ui'

const PREDICT: PredictSpec = {
  question: 'The Service selector says app=payments-web, but the pods are labelled app=web. The Route points to the Service by name. What does a browser get through the Route?',
  choices: [
    { id: '503', label: 'HTTP 503 from the router', correct: true, feedback: 'The selector matches no pod, so the EndpointSlice is empty and the router has no backend server: it answers 503 "Application is not available" itself.' },
    { id: 'refused', label: 'Connection refused', feedback: 'The browser only talks to the router, which is up. Connection refused is what a pod inside the cluster sees when it calls the Service ClusterIP.' },
    { id: 'timeout', label: 'A timeout', feedback: 'Timeouts come from dropped packets (for example a NetworkPolicy), not from an empty Service.' },
    { id: '200', label: '200: the Route finds the pods through the Service name', feedback: 'The Route names the Service, but the Service finds pods only through its selector.' },
  ],
  explain: 'Labels are the glue: Route → Service by name, Service → pods by label selector, and only Ready endpoints get traffic. Each broken link has its own symptom, but through the router most of them look the same: 503.',
}

const SCOPE: ModelScope = {
  includes: [
    'Route host matching, the Route → Service reference and spec.port.targetPort matched against the endpoint port name or number (the router reads EndpointSlices and connects to pod IPs directly).',
    'Service label selector, port and targetPort (number, or a container port name resolved per pod); EndpointSlice endpoints with their ready condition.',
    'The pod side: labels, readiness, the port the process really listens on (containerPort is only documentation unless a named targetPort refers to it).',
    'NetworkPolicy ingress rules for the web pods (allow from the router namespace, from the same namespace, or nothing).',
    'Symptoms: router 503, curl exit 7 (connection refused), exit 28 (timeout), exit 6 (DNS failure), with the messages curl prints.',
  ],
  leavesOut: [
    'TLS (edge, passthrough, re-encrypt), route sharding, wildcard routes, path-based routes, HAProxy timeouts and health checks.',
    'Several Service ports, UDP, session affinity, externalTrafficPolicy, headless Services, DNS search-path details.',
    'Which endpoint answers: real load balancing is random (client) or by the router\'s balance algorithm; the model rotates deterministically.',
    'Timing: a dropped connection makes the router wait for its connect timeout before the 503; the model only reports the outcome.',
    'Calling an undeclared Service port: dropped in this model (exact behaviour depends on the network plugin).',
    'Routers on the host network: in the model, router traffic always comes from pods in openshift-ingress. A host-network router\'s traffic is matched through the namespace openshift-host-network, which carries the same policy-group label, and NetworkPolicy never blocks traffic from the pod\'s own node, so a one-node cluster hides a missing router rule.',
  ],
  links: [
    { label: 'Kubernetes: Services', url: 'https://kubernetes.io/docs/concepts/services-networking/service/' },
    { label: 'Kubernetes: EndpointSlices', url: 'https://kubernetes.io/docs/concepts/services-networking/endpoint-slices/' },
    { label: 'Kubernetes: Network Policies', url: 'https://kubernetes.io/docs/concepts/services-networking/network-policies/' },
    { label: 'Kubernetes: DNS for Services and Pods', url: 'https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/' },
    { label: 'OpenShift 4.21: Routes', url: 'https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/ingress_and_load_balancing/routes' },
    { label: 'OpenShift 4.21: network policy', url: 'https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/network_security/network-policy' },
  ],
}

type Sent = { key: string; res: TrafficResult; n: number }

export default function TrafficSim() {
  const [cfg, setCfg] = useState<TrafficConfig>(DEFAULT_TRAFFIC)
  const [current, setCurrent] = useState<Sent | null>(null)
  const [lastRouter, setLastRouter] = useState<Sent | null>(null)
  const [lastClient, setLastClient] = useState<Sent | null>(null)
  const [history, setHistory] = useState<Sent[]>([])
  const [revealed, setRevealed] = useState(0)
  const attempts = useRef(0)
  const seq = useRef(0)
  const reduced = useReducedMotion()
  const [msg, announce] = useAnnouncer()
  const key = useMemo(() => JSON.stringify(cfg), [cfg])
  const slice = useMemo(() => endpointSlice(cfg), [cfg])

  const set = (patch: Partial<TrafficConfig>) => setCfg((c) => ({ ...c, ...patch }))
  const setPod = (i: number, patch: Partial<TrafficPod>) => setCfg((c) => ({ ...c, pods: c.pods.map((p, j) => (j === i ? { ...p, ...patch } : p)) }))

  const send = (from: 'router' | 'client') => {
    const res = sendRequest(cfg, from, from === 'client' ? attempts.current++ : 0)
    const sent = { key, res, n: ++seq.current }
    setCurrent(sent)
    setHistory((h) => [...h.slice(-5), sent])
    if (from === 'router') setLastRouter(sent)
    else setLastClient(sent)
    setRevealed(reduced ? res.hops.length : 1)
    if (reduced) announce(`${res.symptom}. ${res.failedAt ? `Fails at ${res.hops.find((h) => h.id === res.failedAt)?.label}.` : ''}`)
  }

  // walk the packet hop by hop; stop where it fails
  const stopAt = current ? (current.res.failedAt ? current.res.hops.findIndex((h) => h.id === current.res.failedAt) + 1 : current.res.hops.filter((h) => h.status !== 'skip').length) : 0
  useEffect(() => {
    if (!current || revealed >= stopAt) return
    const id = window.setTimeout(() => setRevealed((r) => r + 1), 380)
    return () => window.clearTimeout(id)
  }, [current, revealed, stopAt])
  const done = !!current && revealed >= stopAt
  useEffect(() => {
    if (done && current && !reduced) announce(`${current.res.symptom}. ${current.res.failedAt ? `Fails at ${current.res.hops.find((h) => h.id === current.res.failedAt)?.label}.` : 'Every hop worked.'}`)
  }, [done]) // eslint-disable-line react-hooks/exhaustive-deps

  const podsUntouched = JSON.stringify(cfg.pods) === JSON.stringify(DEFAULT_TRAFFIC.pods)
  const allHealthy = cfg.pods.every((p) => p.ready && p.listenPort === 8080)
  const challenges: Challenge[] = [
    {
      id: 'router-503',
      title: 'Make the router return 503 without touching the pods, and send the request.',
      hint: 'Break any link between the Route and the pods: the selector, the Service targetPort, the Route targetPort, or a NetworkPolicy.',
      done: !!lastRouter && lastRouter.key === key && lastRouter.res.httpStatus === 503 && podsUntouched,
    },
    {
      id: 'split',
      title: 'The client pod times out (curl exit 28) while the router still gets 200: send both requests with the same configuration.',
      hint: 'NetworkPolicies are allow-lists: allow one source and not the other.',
      done: !!lastRouter && !!lastClient && lastRouter.key === key && lastClient.key === key && lastRouter.res.httpStatus === 200 && lastClient.res.exitCode === 28,
    },
    {
      id: 'refused',
      title: 'Get "connection refused" (exit 7) from the client pod while every pod is Ready and listening on 8080.',
      hint: 'Refused can come from the Service (no endpoints) or from the pod (wrong port). Here the pods are fine, so look at the Service.',
      done: !!lastClient && lastClient.key === key && lastClient.res.exitCode === 7 && allHealthy,
    },
  ]

  return (
    <SimShell
      id="traffic"
      title="Request path: Route → Service → Pod"
      scenario={
        <>
          <p>
            The <code>web</code> app in project <code>{NAMESPACE}</code> is exposed by a Route and a Service (port 80 → targetPort 8080). Edit any field, then send a request from a browser through the router, or with curl from a <code>toolbox</code> pod in the same project.
          </p>
          <p>Watch where the request stops and which symptom the client sees.</p>
        </>
      }
      predict={PREDICT}
      scope={SCOPE}
      challenges={challenges}
      announcement={msg}
    >
      <div className="sim-work">
        <div className="sim-col">
          <Panel title="Route">
            <div className="sim-form">
              <TextField label="spec.host" value={cfg.routeHost} onChange={(v) => set({ routeHost: v })} />
              <div className="sim-row">
                <TextField label="spec.to.name" value={cfg.routeService} onChange={(v) => set({ routeService: v })} />
                <TextField label="spec.port.targetPort" value={cfg.routeTargetPort} onChange={(v) => set({ routeTargetPort: v })} hint="port name or number; empty = any" />
              </div>
            </div>
          </Panel>
          <Panel title="Service">
            <div className="sim-form">
              <div className="sim-row">
                <TextField label="metadata.name" value={cfg.serviceName} onChange={(v) => set({ serviceName: v })} />
                <TextField label="selector app=" value={cfg.selectorApp} onChange={(v) => set({ selectorApp: v })} />
              </div>
              <div className="sim-row">
                <NumField label={`port (name ${cfg.servicePortName})`} value={cfg.servicePort} onChange={(v) => set({ servicePort: v })} min={1} max={65535} />
                <TextField label="targetPort" value={cfg.targetPort} onChange={(v) => set({ targetPort: v })} hint="number or container port name" />
              </div>
            </div>
          </Panel>
          <Panel title="Pods (Deployment web)">
            <div className="sim-form">
              <NumField label={`containerPort named "${cfg.containerPortName}" (declared)`} value={cfg.containerPort} onChange={(v) => set({ containerPort: v })} min={1} max={65535} hint="Only used when targetPort is the name; it does not open any port." />
              {cfg.pods.map((p, i) => (
                <fieldset key={p.name} className="sim-podcfg">
                  <legend className="sim-mono">{p.name}</legend>
                  <div className="sim-row">
                    <TextField label="label app=" value={p.app} onChange={(v) => setPod(i, { app: v })} />
                    <NumField label="process listens on" value={p.listenPort} onChange={(v) => setPod(i, { listenPort: v })} min={1} max={65535} />
                  </div>
                  <Toggle label="Ready (readiness probe passing)" checked={p.ready} onChange={(v) => setPod(i, { ready: v })} />
                </fieldset>
              ))}
            </div>
          </Panel>
          <Panel title="NetworkPolicy on the web pods">
            <SelectField<NetPolicyMode>
              label="Ingress"
              value={cfg.policy}
              onChange={(v) => set({ policy: v })}
              options={[
                { value: 'none', label: 'no policy' },
                { value: 'deny-all', label: 'deny all ingress' },
                { value: 'allow-same-namespace', label: `allow from namespace ${NAMESPACE} only` },
                { value: 'allow-from-router', label: 'allow from the router only' },
                { value: 'allow-router-and-namespace', label: `allow router + namespace ${NAMESPACE}` },
              ]}
              hint={POLICY_TEXT[cfg.policy]}
            />
          </Panel>
        </div>

        <div className="sim-col">
          <Panel title="Send a request">
            <div className="sim-form">
              <div className="sim-send">
                <div className="sim-form">
                  <TextField label="Browser asks for host" value={cfg.requestHost} onChange={(v) => set({ requestHost: v })} />
                  <Btn variant="primary" icon="arrow" onClick={() => send('router')}>
                    Browser → Route
                  </Btn>
                </div>
                <div className="sim-form">
                  <div className="sim-row">
                    <TextField label="toolbox curls host" value={cfg.clientHost} onChange={(v) => set({ clientHost: v })} />
                    <NumField label="port" value={cfg.clientPort} onChange={(v) => set({ clientPort: v })} min={1} max={65535} />
                  </div>
                  <Btn variant="primary" icon="arrow" onClick={() => send('client')}>
                    curl from toolbox pod
                  </Btn>
                </div>
              </div>
            </div>
          </Panel>

          <Panel title={current ? (current.res.from === 'router' ? 'Path through the router' : 'Path from the client pod') : 'Path'} aside={current && current.key !== key ? <Chip tone="warn">config changed since this request</Chip> : undefined}>
            {current ? <PathView res={current.res} revealed={revealed} done={done} /> : <p className="sim-empty">Send a request to trace it hop by hop.</p>}
          </Panel>

          {current && <ResultCard res={current.res} pending={!done} />}

          <Panel title="EndpointSlice web-xxxxx (live)">
            {slice.endpoints.length === 0 ? (
              <p className="sim-empty">
                No endpoints: no pod has label <code>app={cfg.selectorApp}</code>.
              </p>
            ) : (
              <ul className="sim-eps">
                {slice.endpoints.map((e) => (
                  <li key={e.pod} data-ready={e.ready && e.port !== null}>
                    <span className="sim-mono sim-strong">
                      {e.ip}:{e.port ?? '?'}
                    </span>
                    <span className="sim-mono sim-muted">{e.pod}</span>
                    <Chip tone={e.ready ? 'ok' : 'warn'}>ready: {String(e.ready)}</Chip>
                    {e.port === null && <Chip tone="bad">port {cfg.targetPort} not found on pod</Chip>}
                  </li>
                ))}
              </ul>
            )}
            <p className="sim-note">
              Service ClusterIP {CLUSTER_IP}:{cfg.servicePort} → targetPort {cfg.targetPort}. Endpoint port name: {cfg.servicePortName}.
            </p>
          </Panel>

          {history.length > 1 && (
            <Panel title="Recent requests">
              <ol className="sim-history">
                {[...history].reverse().map((h) => (
                  <li key={h.n}>
                    <Chip tone={h.res.ok ? 'ok' : 'bad'}>{h.res.from === 'router' ? 'browser' : 'toolbox'}</Chip> <span>{h.res.symptom}</span>
                    {h.key !== key && <span className="sim-muted"> (older config)</span>}
                  </li>
                ))}
              </ol>
            </Panel>
          )}
        </div>
      </div>
    </SimShell>
  )
}

function PathView({ res, revealed, done }: { res: TrafficResult; revealed: number; done: boolean }) {
  return (
    <ol className="sim-path" aria-label="Hops">
      {res.hops.map((h, i) => {
        const shown = i < revealed
        const state: Hop['status'] | 'pending' = shown ? h.status : done ? 'skip' : 'pending'
        const isCurrent = i === revealed - 1
        return (
          <li key={h.id} className="sim-hop" data-state={state} data-current={isCurrent || undefined}>
            <span className="sim-hop-dot" aria-hidden="true">
              {state === 'ok' ? <SimIcon name="check" size={13} /> : state === 'fail' ? <SimIcon name="x" size={13} /> : state === 'warn' ? <SimIcon name="alert" size={13} /> : null}
            </span>
            <div className="sim-hop-body">
              <p className="sim-hop-label">
                {h.label}
                <span className="sim-sr"> — {state === 'pending' ? 'not reached yet' : state === 'skip' ? 'not reached' : state}</span>
              </p>
              {/* details are laid out from the start (hidden until reached) so the trace never changes height while it animates */}
              <p className="sim-hop-detail" data-hidden={state === 'pending' || undefined} aria-hidden={state === 'pending' || undefined}>
                {h.detail}
              </p>
            </div>
          </li>
        )
      })}
    </ol>
  )
}

function ResultCard({ res, pending }: { res: TrafficResult; pending: boolean }) {
  // rendered (invisible) while the trace animates, so nothing below it moves when the result appears
  return (
    <div className="sim-banner sim-reqresult" data-pending={pending || undefined} aria-hidden={pending || undefined} data-tone={res.ok ? (res.hops.some((h) => h.status === 'warn') ? 'warn' : 'ok') : 'bad'}>
      <SimIcon name={res.ok ? 'check' : 'alert'} />
      <div className="sim-banner-body">
        <p>
          <strong>{res.symptom}</strong>
          {res.httpStatus !== null && res.from === 'router' ? ` · curl exit code ${res.exitCode} (an HTTP error is still a completed request; add -f to make curl fail)` : res.exitCode ? ` · curl exit code ${res.exitCode}` : ''}
        </p>
        <Code>{`$ ${res.command}\n${res.output}`}</Code>
        <p className="sim-note">{res.explanation}</p>
      </div>
    </div>
  )
}
