import { useEffect, useMemo, useRef, useState } from 'react'
import { DEFAULT_PROBE, probeSnapshot, probeStatusAt, simulateProbes, type AppScript, type PodEvent, type ProbeConfig, type ProbeKind, type ProbeSnapshot, type ProbeSpec, type ProbeTimeline } from './models'
import { Btn, Chip, NumField, Panel, Segmented, SelectField, SimShell, Stat, Toggle, useAnnouncer, useReducedMotion, type Challenge, type ModelScope, type PredictSpec } from './ui'

const PREDICT: PredictSpec = {
  question: 'The database the app needs goes down for 60 seconds. The readiness probe checks the database; the liveness probe only checks that the process answers. What happens to the pod during the outage?',
  choices: [
    { id: 'restart', label: 'The kubelet restarts the container after 3 failed probes', feedback: 'Only liveness and startup probe failures restart a container. Readiness failures never do.' },
    { id: 'endpoints', label: 'It gets no Service traffic until the database is back; no restart', correct: true, feedback: 'After failureThreshold failed readiness probes the pod is NotReady: its EndpointSlice entry turns ready: false and traffic goes elsewhere. It comes back after successThreshold successes.' },
    { id: 'crashloop', label: 'It goes into CrashLoopBackOff', feedback: 'CrashLoopBackOff needs a container that keeps stopping. Nothing stops it here.' },
    { id: 'nothing', label: 'Nothing visible: probes only matter at startup', feedback: 'Readiness and liveness probes run for the whole life of the container, every periodSeconds.' },
  ],
  explain: 'Readiness answers "should I get traffic now?", liveness answers "is this process beyond repair?". A liveness probe that checks dependencies turns every outage into a restart storm.',
}

const SCOPE: ModelScope = {
  includes: [
    'Startup, readiness and liveness probes with initialDelaySeconds, periodSeconds, timeoutSeconds, successThreshold and failureThreshold.',
    'Liveness and readiness wait until the startup probe has succeeded; failureThreshold consecutive liveness or startup failures kill the container; readiness failures only set Ready=False.',
    'A new container starts NotReady; Ready needs successThreshold consecutive readiness successes. Without a readiness probe a started container is Ready.',
    'Restart back-off as the kubelet computes it: first restart immediate (1s in this model), then 10s, 20s, 40s… capped at 300s, reset after 10 minutes without restarting.',
    'EndpointSlice membership: a NotReady pod stays listed with ready: false and receives no Service traffic.',
  ],
  leavesOut: [
    'Probe timing jitter: the kubelet aligns each probe ticker to when its worker started, so real probes can be up to one period later than shown. The extra readiness runs the kubelet makes to turn a container Ready sooner are not modelled.',
    'initialDelaySeconds is counted from container start, as the kubelet code does; the docs describe liveness/readiness delays as starting after the startup probe succeeds. Both agree that liveness and readiness do not run before that.',
    'terminationGracePeriodSeconds: a killed container stops at once here; a real one gets SIGTERM, then SIGKILL after the grace period.',
    'exec and gRPC probes, multiple containers, sidecars, init containers, restartPolicy other than Always.',
    'Kubelet sync delays (restarts after back-off can lag by a few seconds) and the feature gates that shorten back-off (ReduceDefaultCrashLoopBackOffDecay, KubeletCrashLoopBackOffMax).',
    'Event de-duplication details: real events are aggregated with a count and a time range, approximated here.',
  ],
  links: [
    { label: 'Kubernetes: liveness, readiness and startup probes', url: 'https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/' },
    { label: 'Kubernetes: probe configuration fields and defaults', url: 'https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/#configure-probes' },
    { label: 'Kubernetes: configure liveness, readiness and startup probes (task)', url: 'https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/' },
    { label: 'Kubernetes: container restarts and back-off', url: 'https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#container-restarts' },
    { label: 'Kubernetes: EndpointSlice conditions', url: 'https://kubernetes.io/docs/concepts/services-networking/endpoint-slices/#conditions' },
    { label: 'OpenShift 4.21: application health checks', url: 'https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/building_applications/application-health' },
  ],
}

type Preset = 'db-down' | 'healthy' | 'slow-start' | 'hang' | 'crash' | 'slow-health'
const PRESETS: Record<Preset, { label: string; app: AppScript }> = {
  'db-down': { label: 'Database down from 60s to 120s', app: { startSeconds: 5, exitAfterSeconds: null, hangAfterSeconds: null, dependencyDown: { from: 60, to: 120 }, livenessChecksDependency: false, healthLatencySeconds: 0 } },
  healthy: { label: 'Healthy app (listens after 5s)', app: { startSeconds: 5, exitAfterSeconds: null, hangAfterSeconds: null, dependencyDown: null, livenessChecksDependency: false, healthLatencySeconds: 0 } },
  'slow-start': { label: 'Slow start: listens after 90s', app: { startSeconds: 90, exitAfterSeconds: null, hangAfterSeconds: null, dependencyDown: null, livenessChecksDependency: false, healthLatencySeconds: 0 } },
  hang: { label: 'Deadlocks after 60s of uptime', app: { startSeconds: 5, exitAfterSeconds: null, hangAfterSeconds: 60, dependencyDown: null, livenessChecksDependency: false, healthLatencySeconds: 0 } },
  crash: { label: 'Exits with code 1 after 3s (missing config)', app: { startSeconds: 5, exitAfterSeconds: 3, hangAfterSeconds: null, dependencyDown: null, livenessChecksDependency: false, healthLatencySeconds: 0 } },
  'slow-health': { label: 'Health endpoint answers in 2s', app: { startSeconds: 5, exitAfterSeconds: null, hangAfterSeconds: null, dependencyDown: null, livenessChecksDependency: false, healthLatencySeconds: 2 } },
}

const DEFAULT_CFG: ProbeConfig = {
  startup: { ...DEFAULT_PROBE, failureThreshold: 30 },
  readiness: { ...DEFAULT_PROBE, enabled: true },
  liveness: { ...DEFAULT_PROBE, enabled: true, initialDelaySeconds: 10 },
  app: PRESETS['db-down'].app,
  horizon: 180,
}
const KINDS: ProbeKind[] = ['startup', 'readiness', 'liveness']
const KIND_LABEL: Record<ProbeKind, string> = { startup: 'Startup', readiness: 'Readiness', liveness: 'Liveness' }

export default function ProbesSim() {
  const [cfg, setCfg] = useState<ProbeConfig>(DEFAULT_CFG)
  const [preset, setPreset] = useState<Preset>('db-down')
  const [editing, setEditing] = useState<ProbeKind>('readiness')
  const [cursor, setCursor] = useState(DEFAULT_CFG.horizon)
  const [playing, setPlaying] = useState(false)
  const reduced = useReducedMotion()
  const [msg, announce] = useAnnouncer()
  const tl = useMemo(() => simulateProbes(cfg), [cfg])

  const setApp = (patch: Partial<AppScript>) => setCfg((c) => ({ ...c, app: { ...c.app, ...patch } }))
  const setProbe = (k: ProbeKind, patch: Partial<ProbeSpec>) => setCfg((c) => ({ ...c, [k]: { ...c[k], ...patch } }))

  // replaying the timeline (the result is computed at once; the cursor only reveals it)
  const raf = useRef<number | null>(null)
  useEffect(() => {
    if (!playing) return
    let last = performance.now()
    const tick = (now: number) => {
      const dt = (now - last) / 1000
      last = now
      setCursor((c) => {
        const next = Math.min(cfg.horizon, c + (dt * cfg.horizon) / 9)
        if (next >= cfg.horizon) setPlaying(false)
        return next
      })
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current)
    }
  }, [playing, cfg.horizon])
  useEffect(() => {
    setPlaying(false)
    setCursor(cfg.horizon)
  }, [cfg.horizon])

  const t = Math.round(cursor)
  const st = probeStatusAt(tl, t)
  const firstReady = tl.ready.length ? tl.ready[0].from : null
  const summary = tl.errors.length ? 'The pod spec is invalid.' : `${tl.restarts} restart(s) in ${cfg.horizon}s; ${firstReady === null ? 'never Ready' : `first Ready at ${firstReady}s`}${tl.maxBackoff ? `; longest back-off ${tl.maxBackoff}s` : ''}.`
  const prevSummary = useRef(summary)
  useEffect(() => {
    if (prevSummary.current !== summary) announce(summary)
    prevSummary.current = summary
  }, [summary]) // eslint-disable-line react-hooks/exhaustive-deps

  const play = () => {
    if (reduced) {
      setCursor(cfg.horizon)
      announce(`At ${cfg.horizon}s: ${summary}`)
      return
    }
    if (cursor >= cfg.horizon) setCursor(0)
    setPlaying(!playing)
  }

  const challenges: Challenge[] = [
    {
      id: 'antipattern',
      title: 'Reproduce the anti-pattern: make a database outage restart the container.',
      hint: 'Keep the database outage, make /healthz check the database too, and keep the liveness probe on.',
      done: !!cfg.app.dependencyDown && cfg.liveness.enabled && cfg.app.livenessChecksDependency && tl.restarts > 0 && cfg.app.hangAfterSeconds === null && cfg.app.exitAfterSeconds === null,
    },
    {
      id: 'slow-start',
      title: 'Slow starter: the app needs 90s to listen. Use a startup probe so it starts without a single restart, while liveness stays strict (initialDelaySeconds ≤ 10, periodSeconds ≤ 10, failureThreshold ≤ 3).',
      hint: 'The startup probe must allow failureThreshold × periodSeconds of at least ~90s. Liveness only starts once the startup probe succeeds.',
      done: cfg.app.startSeconds >= 90 && cfg.startup.enabled && cfg.liveness.enabled && cfg.liveness.initialDelaySeconds <= 10 && cfg.liveness.periodSeconds <= 10 && cfg.liveness.failureThreshold <= 3 && tl.restarts === 0 && tl.ready.length > 0 && cfg.app.exitAfterSeconds === null && cfg.app.hangAfterSeconds === null && !tl.errors.length,
    },
    {
      id: 'cap',
      title: 'Find the cap: let a crashing container reach the maximum back-off of 5 minutes.',
      hint: 'Pick the crashing app and a 600s window.',
      done: tl.maxBackoff === 300,
    },
  ]

  return (
    <SimShell
      id="probes"
      title="Probes, restarts and back-off"
      scenario={
        <>
          <p>
            One container, three probes, and an app with a behaviour script. The model runs the kubelet second by second: which probe fires when, when the pod is <strong>Ready</strong> (in the Service endpoints), when the container is <strong>restarted</strong>, and how the restart back-off grows.
          </p>
          <p>Pick a behaviour, tune the probes, and drag the time cursor or press Play.</p>
        </>
      }
      predict={PREDICT}
      scope={SCOPE}
      challenges={challenges}
      announcement={msg}
    >
      <div className="sim-work">
        <div className="sim-col">
          <Panel title="App behaviour">
            <div className="sim-form">
              <SelectField<Preset>
                label="Scenario"
                value={preset}
                onChange={(p) => {
                  setPreset(p)
                  setApp(PRESETS[p].app)
                  if (p === 'crash') setCfg((c) => ({ ...c, horizon: Math.max(c.horizon, 300) }))
                }}
                options={(Object.keys(PRESETS) as Preset[]).map((k) => ({ value: k, label: PRESETS[k].label }))}
              />
              <div className="sim-row">
                <NumField label="Listens after" value={cfg.app.startSeconds} onChange={(v) => setApp({ startSeconds: v })} min={0} max={600} unit="s" />
                <NumField label="Health answers in" value={cfg.app.healthLatencySeconds} onChange={(v) => setApp({ healthLatencySeconds: v })} min={0} max={10} unit="s" />
                <NumField label="Deadlocks after" value={cfg.app.hangAfterSeconds ?? 0} onChange={(v) => setApp({ hangAfterSeconds: v > 0 ? v : null })} min={0} max={900} unit="s" hint="uptime; 0 = never" />
                <NumField label="Exits after" value={cfg.app.exitAfterSeconds ?? 0} onChange={(v) => setApp({ exitAfterSeconds: v > 0 ? v : null })} min={0} max={900} unit="s" hint="uptime; 0 = never" />
              </div>
              <Toggle label="Database outage" checked={!!cfg.app.dependencyDown} onChange={(v) => setApp({ dependencyDown: v ? { from: 60, to: 120 } : null })} />
              {cfg.app.dependencyDown && (
                <div className="sim-row">
                  <NumField label="from" value={cfg.app.dependencyDown.from} onChange={(v) => setApp({ dependencyDown: { from: v, to: Math.max(v + 1, cfg.app.dependencyDown?.to ?? v + 1) } })} min={0} max={1200} unit="s" />
                  <NumField label="to" value={cfg.app.dependencyDown.to} onChange={(v) => setApp({ dependencyDown: { from: cfg.app.dependencyDown?.from ?? 0, to: v } })} min={1} max={1200} unit="s" />
                </div>
              )}
              <Toggle label="/healthz (liveness) also checks the database" checked={cfg.app.livenessChecksDependency} onChange={(v) => setApp({ livenessChecksDependency: v })} hint="/ready always checks it." />
            </div>
          </Panel>
          <Panel title="Probes">
            <div className="sim-form">
              <Segmented<ProbeKind> label="Edit" value={editing} onChange={setEditing} options={KINDS.map((k) => ({ value: k, label: `${KIND_LABEL[k]}${cfg[k].enabled ? '' : ' (off)'}` }))} />
              <ProbeEditor kind={editing} spec={cfg[editing]} onChange={(p) => setProbe(editing, p)} />
              <ul className="sim-probe-summary">
                {KINDS.map((k) => (
                  <li key={k}>
                    <strong>{KIND_LABEL[k]}</strong>{' '}
                    {cfg[k].enabled ? (
                      <span className="sim-mono">
                        delay {cfg[k].initialDelaySeconds}s · every {cfg[k].periodSeconds}s · timeout {cfg[k].timeoutSeconds}s · success {cfg[k].successThreshold} · failure {cfg[k].failureThreshold}
                      </span>
                    ) : (
                      <span className="sim-muted">off</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          </Panel>
        </div>

        <div className="sim-col">
          {tl.errors.length > 0 ? (
            <div className="sim-banner" data-tone="bad">
              <div className="sim-banner-body">
                <p>
                  <strong>The API server rejects this pod spec.</strong>
                </p>
                <pre className="sim-code">{`The Deployment "web" is invalid: ${tl.errors.join('; ')}`}</pre>
              </div>
            </div>
          ) : (
            <>
              <Panel
                title="Timeline"
                aside={
                  <Segmented<string>
                    label={<span className="sim-sr">Window</span>}
                    value={String(cfg.horizon)}
                    onChange={(v) => setCfg((c) => ({ ...c, horizon: Number(v) }))}
                    options={[
                      { value: '120', label: '120s' },
                      { value: '180', label: '180s' },
                      { value: '300', label: '300s' },
                      { value: '600', label: '600s' },
                    ]}
                  />
                }
              >
                <Timeline tl={tl} cfg={cfg} cursor={cursor} />
                <div className="sim-scrub">
                  <Btn icon={playing ? 'x' : 'play'} onClick={play}>
                    {playing ? 'Pause' : 'Play'}
                  </Btn>
                  <label className="sim-field sim-scrub-field">
                    <span className="sim-label">Inspect time: t = {t}s</span>
                    <input type="range" min={0} max={cfg.horizon} step={1} value={t} onChange={(e) => setCursor(Number(e.target.value))} aria-valuetext={`${t} seconds: ${st.status}, ${st.ready ? 'Ready' : 'not Ready'}, ${st.restarts} restarts`} />
                  </label>
                </div>
              </Panel>
              <PodNow snap={probeSnapshot(tl, cfg, t)} cfg={cfg} />
              <div className="sim-stats" aria-label={`Pod at ${t} seconds`}>
                <Stat label={`STATUS at ${t}s`} value={st.status} tone={st.status === 'Running' ? 'ok' : 'bad'} />
                <Stat label="READY" value={st.ready ? '1/1' : '0/1'} tone={st.ready ? 'ok' : 'warn'} />
                <Stat label="RESTARTS" value={st.restarts} tone={st.restarts ? 'warn' : undefined} />
                <Stat label="EndpointSlice" value={st.ready ? 'ready' : 'not ready'} tone={st.ready ? 'ok' : 'warn'} />
              </div>
              <Panel title={`Events up to ${t}s`}>
                <EventList events={tl.events.filter((e) => e.t <= t)} />
              </Panel>
            </>
          )}
        </div>
      </div>
    </SimShell>
  )
}

function ProbeEditor({ kind, spec, onChange }: { kind: ProbeKind; spec: ProbeSpec; onChange: (p: Partial<ProbeSpec>) => void }) {
  return (
    <div className="sim-form">
      <Toggle label={`${KIND_LABEL[kind]} probe enabled (httpGet ${kind === 'readiness' ? '/ready' : '/healthz'})`} checked={spec.enabled} onChange={(v) => onChange({ enabled: v })} />
      <div className="sim-row">
        <NumField label="initialDelaySeconds" value={spec.initialDelaySeconds} onChange={(v) => onChange({ initialDelaySeconds: v })} min={0} max={600} disabled={!spec.enabled} />
        <NumField label="periodSeconds" value={spec.periodSeconds} onChange={(v) => onChange({ periodSeconds: v })} min={1} max={300} disabled={!spec.enabled} />
        <NumField label="timeoutSeconds" value={spec.timeoutSeconds} onChange={(v) => onChange({ timeoutSeconds: v })} min={1} max={60} disabled={!spec.enabled} />
        <NumField label="successThreshold" value={spec.successThreshold} onChange={(v) => onChange({ successThreshold: v })} min={1} max={10} disabled={!spec.enabled} hint={kind === 'readiness' ? undefined : 'must be 1'} />
        <NumField label="failureThreshold" value={spec.failureThreshold} onChange={(v) => onChange({ failureThreshold: v })} min={1} max={60} disabled={!spec.enabled} />
      </div>
    </div>
  )
}

const PROBE_EFFECT: Record<ProbeKind, string> = { startup: 'kills the container', readiness: 'NotReady: no traffic', liveness: 'kills the container' }

/** The pod at the cursor: what each probe got, the container, and where Service traffic goes. Cause and effect, at a glance. */
function PodNow({ snap, cfg }: { snap: ProbeSnapshot; cfg: ProbeConfig }) {
  const { container: c } = snap
  return (
    <Panel title={`At t = ${snap.t}s`}>
      <div className="pn-wrap">
      <div className="pn" data-testid="probes-now">
        <div className="pn-col">
          <div className="pn-h">kubelet probes</div>
          {snap.probes.map((p) => (
            <div key={p.kind} className="pn-probe" data-state={!p.last ? 'idle' : p.last.ok ? 'ok' : 'fail'} data-testid={`now-${p.kind}`}>
              <div className="pn-probe-line">
                <span className="sim-mono">GET {p.path}</span>
                <span className="pn-res">{!p.last ? 'not run yet' : p.last.ok ? '200 OK' : p.last.detail.includes('503') ? `503 · ${p.cause}` : p.cause}</span>
              </div>
              <div className="pn-probe-line pn-sub">
                <span>{KIND_LABEL[p.kind]}</span>
                <span className="pn-meter" aria-label={`${p.fails} of ${p.threshold} failures in a row`}>
                  {Array.from({ length: Math.min(p.threshold, 10) }, (_, i) => (
                    <i key={i} data-on={i < p.fails || undefined} />
                  ))}
                  <span className="pn-meter-txt">{p.fails >= p.threshold ? PROBE_EFFECT[p.kind] : `${p.fails}/${p.threshold} → ${PROBE_EFFECT[p.kind]}`}</span>
                </span>
              </div>
            </div>
          ))}
        </div>
        <div className="pn-col pn-mid">
          {snap.database && (
            <div className="pn-box pn-db" data-state={snap.database}>
              <span className="pn-box-h">database</span>
              <strong>{snap.database === 'up' ? 'up' : 'down'}</strong>
              <span className="pn-box-sub">{snap.database === 'down' ? cfg.app.livenessChecksDependency ? '/ready and /healthz answer 503' : '/ready answers 503' : `checked by /ready${cfg.app.livenessChecksDependency ? ' and /healthz' : ''}`}</span>
            </div>
          )}
          <div className="pn-box pn-pod" data-state={c.state === 'running' ? (snap.ready ? 'ok' : 'warn') : 'bad'}>
            <span className="pn-box-h">pod web · container app</span>
            <strong>{c.state === 'running' ? (snap.ready ? 'Running · Ready' : 'Running · NotReady') : c.state === 'backoff' ? `CrashLoopBackOff · ${c.backoffLeft}s` : c.state === 'stopped' ? 'Restarting' : 'Pending'}</strong>
            <span className="pn-box-sub">{c.run === null ? (c.lastStop === 'liveness' ? 'killed by the liveness probe' : c.lastStop === 'startup' ? 'killed by the startup probe' : c.lastStop === 'Error' ? 'exited with code 1' : 'no container') : `${c.run ? `restart ${c.run} · ` : ''}up ${c.uptime}s`}</span>
          </div>
        </div>
        <div className="pn-col">
          <div className="pn-h">Service traffic</div>
          <div className="pn-route" data-traffic={snap.traffic}>
            <span className="pn-node">Service web</span>
            <span className="pn-link" aria-hidden="true">
              <i />
            </span>
            <span className="pn-node">EndpointSlice<span className="sim-mono pn-ep">10.217.0.42 · ready: {String(snap.ready)}</span></span>
          </div>
          <div className="pn-traffic">{snap.traffic === 'serving' ? 'requests reach the pod' : snap.traffic === 'blocked' ? 'no traffic: the pod is not Ready' : 'no traffic: no running container'}</div>
        </div>
      </div>
      </div>
      <p className="pn-story" data-testid="probes-story">{snap.story}</p>
    </Panel>
  )
}

function niceStep(h: number) {
  return h <= 120 ? 20 : h <= 180 ? 30 : h <= 300 ? 60 : 100
}

function Timeline({ tl, cfg, cursor }: { tl: ProbeTimeline; cfg: ProbeConfig; cursor: number }) {
  const h = cfg.horizon
  const pct = (t: number) => `${(Math.min(h, Math.max(0, t)) / h) * 100}%`
  const ticks: number[] = []
  for (let t = 0; t <= h; t += niceStep(h)) ticks.push(t)
  const cursorEl = (
    <>
      {cursor < h && <span className="sim-tl-future" style={{ left: pct(cursor) }} aria-hidden="true" />}
      <span className="sim-tl-cursor" style={{ left: pct(cursor) }} aria-hidden="true" />
    </>
  )
  const reveal = (t: number) => t <= cursor
  const probeRow = (k: ProbeKind) => {
    const marks = tl.marks.filter((m) => m.probe === k)
    const ok = marks.filter((m) => m.ok && reveal(m.t)).length
    const bad = marks.filter((m) => !m.ok && reveal(m.t)).length
    return (
      <div className="sim-tl-row" key={k}>
        <span className="sim-tl-label">
          {KIND_LABEL[k]} probe
          <span className="sim-tl-sub">{cfg[k].enabled ? `${ok} ok · ${bad} failed` : 'off'}</span>
        </span>
        <div className="sim-tl-track" role="img" aria-label={`${KIND_LABEL[k]} probe: ${cfg[k].enabled ? `${ok} successes and ${bad} failures up to ${Math.round(cursor)} seconds` : 'disabled'}`}>
          {cfg.app.dependencyDown && (k === 'readiness' || cfg.app.livenessChecksDependency) && <span className="sim-tl-outage" style={{ left: pct(cfg.app.dependencyDown.from), width: pct(cfg.app.dependencyDown.to - cfg.app.dependencyDown.from) }} title={`database outage: ${k === 'readiness' ? '/ready' : '/healthz'} checks it`} />}
          {marks.map((m) => (
            <span key={`${m.t}`} className="sim-tl-dot" data-ok={m.ok} data-hidden={!reveal(m.t) || undefined} style={{ left: pct(m.t) }} title={`${m.t}s: ${m.ok ? '200 OK' : m.detail}`} />
          ))}
          {cursorEl}
        </div>
      </div>
    )
  }
  return (
    <div className="sim-tl">
      <div className="sim-tl-row">
        <span className="sim-tl-label">
          Container
          <span className="sim-tl-sub">{tl.runs.filter((r) => r.start <= cursor).length} start(s)</span>
        </span>
        <div className="sim-tl-track" role="img" aria-label={`Container runs: ${tl.runs.map((r) => `${r.start} to ${r.end ?? h} seconds${r.endReason ? `, stopped by ${r.endReason === 'Error' ? 'a crash' : `the ${r.endReason} probe`}` : ''}`).join('; ')}. Back-off waits: ${tl.waits.map((w) => `${w.backoff} seconds at ${w.from}`).join(', ') || 'none'}.`}>
          {tl.runs.map((r) => (
            <span key={r.index} className="sim-tl-seg" data-kind="run" data-end={r.endReason || undefined} style={{ left: pct(r.start), width: `calc(${pct((r.end ?? h) - r.start)} - 1px)` }} />
          ))}
          {tl.waits.map((w) => (
            <span key={w.from} className="sim-tl-seg" data-kind="wait" style={{ left: pct(w.from), width: pct(w.to - w.from) }}>
              {w.to - w.from >= h / 10 && <span className="sim-tl-seg-label">back-off {w.backoff}s</span>}
            </span>
          ))}
          {tl.runs
            .filter((r) => r.end !== null)
            .map((r) => (
              <span key={`x${r.index}`} className="sim-tl-kill" style={{ left: pct(r.end as number) }} title={r.endReason === 'Error' ? 'exited with code 1' : `killed: ${r.endReason} probe failed`} />
            ))}
          {cursorEl}
        </div>
      </div>
      {KINDS.filter((k) => cfg[k].enabled).map(probeRow)}
      <div className="sim-tl-row">
        <span className="sim-tl-label">
          Ready (endpoints)
          <span className="sim-tl-sub">serving / not ready</span>
        </span>
        <div className="sim-tl-track" data-kind="ready" role="img" aria-label={`Ready intervals: ${tl.ready.map((r) => `${r.from} to ${r.to} seconds`).join(', ') || 'never Ready'}`}>
          {tl.ready.map((r) => (
            <span key={r.from} className="sim-tl-seg" data-kind="ready" style={{ left: pct(r.from), width: pct(r.to - r.from) }} />
          ))}
          {cfg.app.dependencyDown && <span className="sim-tl-outage" style={{ left: pct(cfg.app.dependencyDown.from), width: pct(cfg.app.dependencyDown.to - cfg.app.dependencyDown.from) }} title="database outage" />}
          {cursorEl}
        </div>
      </div>
      <div className="sim-tl-row" aria-hidden="true">
        <span className="sim-tl-label" />
        <div className="sim-tl-axis">
          {ticks.map((t) => (
            <span key={t} style={{ left: pct(t) }} data-edge={t === 0 ? 'start' : t === h ? 'end' : undefined}>
              {t}s
            </span>
          ))}
        </div>
      </div>
      <ul className="sim-legend" aria-label="Legend">
        <li>
          <span className="sim-tl-key" data-kind="run" /> running
        </li>
        <li>
          <span className="sim-tl-key" data-kind="wait" /> CrashLoopBackOff wait
        </li>
        <li>
          <span className="sim-tl-key" data-kind="ok" /> probe ok
        </li>
        <li>
          <span className="sim-tl-key" data-kind="fail" /> probe failed
        </li>
        <li>
          <span className="sim-tl-key" data-kind="ready" /> Ready
        </li>
        {cfg.app.dependencyDown && (
          <li>
            <span className="sim-tl-key" data-kind="outage" /> database down
          </li>
        )}
      </ul>
    </div>
  )
}

/** kubectl-describe-like list: consecutive identical events are folded into one line with a count. */
function EventList({ events }: { events: PodEvent[] }) {
  const folded: { first: number; last: number; count: number; e: PodEvent }[] = []
  for (const e of events) {
    const prev = folded[folded.length - 1]
    if (prev && prev.e.reason === e.reason && prev.e.message === e.message) {
      prev.count++
      prev.last = e.t
    } else folded.push({ first: e.t, last: e.t, count: 1, e })
  }
  const shown = folded.slice(-10)
  if (!shown.length) return <p className="sim-empty">No events yet.</p>
  return (
    <ol className="sim-events">
      {folded.length > shown.length && <li className="sim-muted">… {folded.length - shown.length} earlier line(s)</li>}
      {shown.map((f) => (
        <li key={`${f.first}-${f.e.reason}-${f.e.message}`}>
          <span className="sim-mono sim-muted">{f.count > 1 ? `${f.first}–${f.last}s (x${f.count})` : `${f.first}s`}</span>
          <Chip tone={f.e.type === 'Warning' ? 'warn' : f.e.type === 'Status' ? 'muted' : 'info'}>
            {f.e.type === 'Status' ? 'status' : f.e.type} {f.e.reason}
          </Chip>
          <span className="sim-events-msg">{f.e.message}</span>
        </li>
      ))}
    </ol>
  )
}
