import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ROLLOUT_BAD_IMAGE,
  ROLLOUT_GOOD_IMAGE,
  ROLLOUT_START_IMAGE,
  initialRollout,
  maxUnavailableFor,
  resolveFenceposts,
  rollbackRollout,
  rolloutCounts,
  rolloutStatusText,
  rolloutStep,
  rsAvailable,
  runRollout,
  startRollout,
  validateRollingUpdate,
  type RolloutConfig,
  type RolloutRS,
  type RolloutState,
} from './models'
import { Btn, Chip, Code, Log, NumField, Panel, Segmented, SimIcon, SimShell, Stat, TextField, Toggle, useAnnouncer, type Challenge, type ModelScope, type PredictSpec } from './ui'

const PREDICT: PredictSpec = {
  question:
    'A Deployment runs 4 replicas with maxSurge 25% and maxUnavailable 25%. You roll out an image whose tag has a typo, so it can never be pulled. When the controller has done everything it is allowed to do, how many pods still serve traffic?',
  choices: [
    { id: '4', label: '4: old pods are kept until new ones are ready', feedback: 'maxUnavailable 25% of 4 is 1, so the controller is allowed to remove one old pod before any new pod is available.' },
    { id: '3', label: '3', correct: true, feedback: 'It surges one new pod, removes one old pod (allowed by maxUnavailable), adds a second new pod, then stops: 3 old pods serve, 2 new pods are stuck in ImagePullBackOff.' },
    { id: '2', label: '2', feedback: 'The controller never goes below replicas − maxUnavailable = 3 available pods.' },
    { id: '0', label: '0: the rollout replaces everything', feedback: 'That is what the Recreate strategy would do. RollingUpdate keeps at least replicas − maxUnavailable pods available.' },
  ],
  explain: 'A stuck rollout is not rolled back automatically: after progressDeadlineSeconds the Deployment reports Progressing=False (ProgressDeadlineExceeded) and waits for you to fix it or run oc rollout undo.',
}

const SCOPE: ModelScope = {
  includes: [
    'The Deployment controller decisions of a RollingUpdate: NewRSNewReplicas (scale up within replicas + maxSurge), cleanup of unhealthy old pods, then scale down while keeping replicas − maxUnavailable available.',
    'Rounding: maxSurge percentages round up, maxUnavailable round down; if both resolve to 0, maxUnavailable becomes 1. API validation (0/0 rejected, maxUnavailable ≤ 100%).',
    'Recreate: scale every old pod to zero, then create the new ReplicaSet at full size.',
    'Progressing condition (NewReplicaSetCreated, ReplicaSetUpdated, NewReplicaSetAvailable, ProgressDeadlineExceeded) and the oc rollout status messages.',
    'oc rollout undo: the previous ReplicaSet is reused and gets the next revision number.',
  ],
  leavesOut: [
    'minReadySeconds (a pod counts as available as soon as it is Ready), readiness flapping and pod crashes after Ready.',
    'Graceful termination: scaled-down pods disappear at once (real ones stay Terminating for terminationGracePeriodSeconds and are not counted).',
    'The ReplicaSet controller\'s slow-start batches, API latency, several syncs per second and the informer cache.',
    'Proportional scaling when you scale during a rollout, paused rollouts, revisionHistoryLimit cleanup, HPA.',
    'One decision per step: the real controller can create the new ReplicaSet and scale an old one down in the same sync (same outcome, fewer steps).',
    'Scheduling: new pods are assumed to fit on a node immediately.',
  ],
  links: [
    { label: 'Kubernetes: Deployments, rolling update', url: 'https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#rolling-update-deployment' },
    { label: 'Kubernetes: max surge and max unavailable', url: 'https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#max-surge' },
    { label: 'Kubernetes: failed deployment (progress deadline)', url: 'https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#failed-deployment' },
    { label: 'Kubernetes: rolling back a Deployment', url: 'https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#rolling-back-a-deployment' },
    { label: 'OpenShift 4.21: Deployments and strategies', url: 'https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/building_applications/deployments' },
  ],
}

const DEFAULT_CFG: RolloutConfig = { replicas: 4, maxSurge: '25%', maxUnavailable: '25%', readySeconds: 10, progressDeadlineSeconds: 600, strategy: 'RollingUpdate' }

export default function RolloutSim() {
  const [cfg, setCfg] = useState<RolloutConfig>(DEFAULT_CFG)
  const [bad, setBad] = useState(true)
  const [s, setS] = useState<RolloutState>(() => initialRollout(DEFAULT_CFG))
  const [playing, setPlaying] = useState(false)
  const [msg, announce] = useAnnouncer()
  const timer = useRef<number | null>(null)

  const errors = cfg.strategy === 'RollingUpdate' ? validateRollingUpdate(cfg.maxSurge, cfg.maxUnavailable) : []
  const c = rolloutCounts(s)
  const status = rolloutStatusText(s)
  const stuck = s.progressing.reason === 'ProgressDeadlineExceeded'
  const canRollback = s.rss.some((r) => r.image !== s.image)
  const started = s.markers.includes('start')

  const update = (patch: Partial<RolloutConfig>) => {
    const next = { ...cfg, ...patch }
    setCfg(next)
    setS(initialRollout(next))
    setPlaying(false)
  }

  const say = (st: RolloutState, fallback: string) => {
    const last = st.log[st.log.length - 1]
    announce(last ? `t=${st.t}s, ${last.who}: ${last.text}` : fallback)
  }
  const step = () => {
    const r = rolloutStep(s)
    setS(r.state)
    if (!r.moved) {
      setPlaying(false)
      announce(r.state.complete ? 'Rollout complete. Nothing left to do.' : `Nothing else happens on its own. ${r.state.waiting}`)
    } else say(r.state, '')
    return r.moved
  }

  useEffect(() => {
    if (!playing) return
    timer.current = window.setTimeout(() => {
      const r = rolloutStep(s)
      setS(r.state)
      if (!r.moved) setPlaying(false)
      else say(r.state, '')
    }, 850)
    return () => {
      if (timer.current) window.clearTimeout(timer.current)
    }
  }, [playing, s]) // eslint-disable-line react-hooks/exhaustive-deps

  const start = () => {
    const image = bad ? ROLLOUT_BAD_IMAGE : ROLLOUT_GOOD_IMAGE
    if (image === s.image) {
      announce(`The Deployment already runs ${image}: changing nothing starts no rollout. Toggle the image, or use Reset model.`)
      return
    }
    setS(startRollout(s, image, !bad))
    announce(`Started rollout to ${image}. Step to watch the controller.`)
  }
  const undo = () => {
    const next = rollbackRollout(s)
    setS(next)
    announce('oc rollout undo: the previous template is back; step to watch the rollback roll out.')
  }
  const toEnd = () => {
    setPlaying(false)
    const next = runRollout(s)
    setS(next)
    say(next, 'Nothing to run.')
  }

  const fence = useMemo(() => (cfg.strategy === 'RollingUpdate' && !errors.length ? resolveFenceposts(cfg.maxSurge, cfg.maxUnavailable, cfg.replicas) : null), [cfg, errors.length])
  const maxUnav = cfg.strategy === 'RollingUpdate' && !errors.length ? maxUnavailableFor(cfg.maxSurge, cfg.maxUnavailable, cfg.replicas) : cfg.replicas

  const challenges: Challenge[] = [
    {
      id: 'zero-downtime',
      title: 'Zero downtime: complete a rollout to the good image without availability ever dropping below the replica count.',
      hint: 'Availability can only drop when maxUnavailable lets the controller remove old pods before new ones are ready.',
      done: cfg.strategy === 'RollingUpdate' && s.complete && started && s.image === ROLLOUT_GOOD_IMAGE && s.minAvailableSeen >= cfg.replicas,
    },
    {
      id: 'deadline-rollback',
      title: 'Fail, then recover: let the broken image hit ProgressDeadlineExceeded, then roll back until the Deployment is healthy again.',
      hint: 'Lower progressDeadlineSeconds if you do not want to wait for 600 simulated seconds, then use "Roll back" and step to the end.',
      done: s.markers.includes('deadline') && s.markers.includes('rollback') && s.complete && s.image === ROLLOUT_START_IMAGE,
    },
    {
      id: 'one-replica',
      title: 'Rounding edge case: with 1 replica and 25% / 25%, show that the controller surges to 2 pods and never drops to 0 available.',
      hint: '25% of 1 rounds up to 1 for maxSurge and down to 0 for maxUnavailable.',
      done: cfg.replicas === 1 && String(cfg.maxSurge) === '25%' && String(cfg.maxUnavailable) === '25%' && cfg.strategy === 'RollingUpdate' && started && s.complete && s.maxPodsSeen === 2 && s.minAvailableSeen === 1,
    },
  ]

  const lastDecision = [...s.log].reverse().find((l) => l.who === 'deployment controller')
  const rss = [...s.rss].sort((a, b) => b.created - a.created)

  return (
    <SimShell
      id="rollout"
      title="Rolling update, step by step"
      scenario={
        <>
          <p>
            Deployment <code>web</code> runs <code>{ROLLOUT_START_IMAGE}</code>. You change the image and the Deployment controller replaces pods in batches bounded by <code>maxSurge</code> and <code>maxUnavailable</code>.
          </p>
          <p>Step through each controller decision, watch availability, then try a broken image and a rollback.</p>
        </>
      }
      predict={PREDICT}
      scope={SCOPE}
      challenges={challenges}
      announcement={msg}
    >
      <div className="sim-work">
        <div className="sim-col">
          <Panel title="Deployment spec">
            <div className="sim-form">
              <Segmented<RolloutConfig['strategy']>
                label="strategy.type"
                value={cfg.strategy}
                onChange={(v) => update({ strategy: v })}
                options={[
                  { value: 'RollingUpdate', label: 'RollingUpdate' },
                  { value: 'Recreate', label: 'Recreate' },
                ]}
              />
              <NumField label="replicas" value={cfg.replicas} onChange={(v) => update({ replicas: v })} min={1} max={10} />
              {cfg.strategy === 'RollingUpdate' && (
                <div className="sim-row">
                  <TextField label="maxSurge" value={String(cfg.maxSurge)} onChange={(v) => update({ maxSurge: v })} hint="number or %" />
                  <TextField label="maxUnavailable" value={String(cfg.maxUnavailable)} onChange={(v) => update({ maxUnavailable: v })} hint="number or %" />
                </div>
              )}
              <div className="sim-row">
                <NumField label="Time to Ready" value={cfg.readySeconds} onChange={(v) => update({ readySeconds: v })} min={1} max={300} unit="s" />
                <NumField label="progressDeadlineSeconds" value={cfg.progressDeadlineSeconds} onChange={(v) => update({ progressDeadlineSeconds: v })} min={10} max={3600} step={10} unit="s" />
              </div>
              <Toggle label="The new image is broken (tag typo)" checked={bad} onChange={setBad} hint={bad ? `${ROLLOUT_BAD_IMAGE}: ErrImagePull, then ImagePullBackOff` : `${ROLLOUT_GOOD_IMAGE}: Ready after ${cfg.readySeconds}s`} />
              <p className="sim-note">Changing the spec resets the Deployment to 1.0.</p>
            </div>
          </Panel>
          {errors.length > 0 ? (
            <div className="sim-banner" data-tone="bad">
              <SimIcon name="alert" />
              <div className="sim-banner-body">
                <p>
                  <strong>The API server rejects this Deployment.</strong>
                </p>
                <Code>{`The Deployment "web" is invalid: ${errors.join('; ')}`}</Code>
              </div>
            </div>
          ) : (
            <Panel title="What the controller may do">
              {fence ? (
                <ul className="sim-fence">
                  <li>
                    maxSurge <code>{String(cfg.maxSurge)}</code> of {cfg.replicas} → <strong>{fence.surge}</strong> <span className="sim-muted">(rounded up)</span>
                  </li>
                  <li>
                    maxUnavailable <code>{String(cfg.maxUnavailable)}</code> of {cfg.replicas} → <strong>{maxUnav}</strong> <span className="sim-muted">(rounded down{fence.bumped ? '; both were 0, so it becomes 1' : ''})</span>
                  </li>
                  <li>
                    At most <strong>{cfg.replicas + fence.surge}</strong> pods; at least <strong>{cfg.replicas - maxUnav}</strong> available.
                  </li>
                </ul>
              ) : (
                <p className="sim-note">Recreate: every old pod is removed first, then all new pods are created. Availability drops to 0 in between.</p>
              )}
            </Panel>
          )}
        </div>

        <div className="sim-col">
          <Panel
            title="Run it"
            aside={
              <span className="sim-clock" aria-label={`Simulated time ${s.t} seconds`}>
                t = {s.t}s
              </span>
            }
          >
            <div className="sim-actions">
              <Btn variant="primary" icon="play" onClick={start} disabled={errors.length > 0 || (s.rolling && !stuck)} title={stuck ? 'Roll forward: set a different image while the rollout is stuck' : undefined}>
                {`oc set image … web:${bad ? '2.0-typo' : '2.0'}`}
              </Btn>
              <Btn icon="step" onClick={step} disabled={!s.rolling || playing}>
                Step
              </Btn>
              <Btn icon={playing ? 'x' : 'play'} onClick={() => setPlaying(!playing)} disabled={!s.rolling}>
                {playing ? 'Pause' : 'Play'}
              </Btn>
              <Btn onClick={toEnd} disabled={!s.rolling}>
                Run to the end
              </Btn>
              <Btn icon="undo" onClick={undo} disabled={!canRollback}>
                oc rollout undo
              </Btn>
            </div>
          </Panel>

          <div className="sim-stats">
            <Stat label="pods (all ReplicaSets)" value={c.total} tone={fence && c.total > cfg.replicas + fence.surge ? 'bad' : undefined} />
            <Stat label="available" value={`${c.available}/${cfg.replicas}`} tone={c.available >= cfg.replicas ? 'ok' : c.available >= c.minAvailable ? 'warn' : 'bad'} />
            <Stat label="updated (new RS)" value={c.updated} />
            <Stat label="lowest availability so far" value={s.minAvailableSeen} tone={s.minAvailableSeen >= cfg.replicas ? 'ok' : s.minAvailableSeen === 0 ? 'bad' : 'warn'} />
          </div>

          <Panel title="ReplicaSets and pods">
            <div className="sim-rs-list">
              {rss.map((rs) => (
                <RSLane key={rs.name} rs={rs} t={s.t} current={rs.image === s.image} />
              ))}
            </div>
            <ul className="sim-legend" aria-label="Legend">
              <li>
                <span className="sim-pod-dot" data-state="ready" /> Ready (available)
              </li>
              <li>
                <span className="sim-pod-dot" data-state="starting" /> starting
              </li>
              <li>
                <span className="sim-pod-dot" data-state="pull" /> ImagePullBackOff
              </li>
            </ul>
          </Panel>

          <Panel title="Status">
            <div className="sim-form">
              <div className="sim-chips">
                <Chip tone={stuck ? 'bad' : s.complete ? 'ok' : 'info'}>
                  Progressing={s.progressing.status} · {s.progressing.reason}
                </Chip>
                <Chip tone={c.available >= c.minAvailable ? 'ok' : 'bad'}>Available={c.available >= c.minAvailable ? 'True' : 'False'}</Chip>
              </div>
              <p className="sim-note">{s.progressing.message}</p>
              <Code label="oc rollout status deployment/web">{`$ oc rollout status deployment/web\n${status.text}`}</Code>
              {lastDecision && (
                <div className="sim-decision">
                  <p className="sim-sub">Last controller decision (t={lastDecision.t}s)</p>
                  <p>{lastDecision.text}</p>
                  {lastDecision.math && <p className="sim-math">{lastDecision.math}</p>}
                </div>
              )}
              {s.rolling && s.waiting && <p className="sim-note">Waiting: {s.waiting}</p>}
            </div>
          </Panel>

          <Panel title="Events">
            <Log
              items={s.log}
              keyOf={(_, i) => i}
              empty="Nothing yet. Start the rollout."
              render={(l) => (
                <>
                  <div className="sim-log-meta">
                    <span className="sim-mono">t={l.t}s</span>
                    <Chip tone={l.who === 'you' ? 'accent' : l.who === 'kubelet' ? 'info' : 'violet'}>{l.who}</Chip>
                  </div>
                  <span>{l.text}</span>
                  {l.math && <span className="sim-math"> · {l.math}</span>}
                </>
              )}
            />
          </Panel>
        </div>
      </div>
    </SimShell>
  )
}

function RSLane({ rs, t, current }: { rs: RolloutRS; t: number; current: boolean }) {
  const avail = rsAvailable(rs, t)
  return (
    <section className="sim-rs" data-current={current} aria-label={`ReplicaSet ${rs.name}, revision ${rs.revision}, ${rs.pods.length} pods, ${avail} available`}>
      <header className="sim-rs-head">
        <span className="sim-mono sim-strong">{rs.name}</span>
        <Chip tone={current ? 'accent' : 'muted'}>rev {rs.revision}{current ? ' · current template' : ''}</Chip>
        <Chip tone={rs.good ? 'ok' : 'bad'}>{rs.image.split('/').pop()}</Chip>
        <span className="sim-muted sim-rs-count">
          spec {rs.replicas} · available {avail}
        </span>
      </header>
      <ul className="sim-pods" aria-label={`Pods of ${rs.name}`}>
        {rs.pods.length === 0 && <li className="sim-muted sim-pods-empty">no pods</li>}
        {rs.pods.map((p) => {
          const state = p.readyAt === null ? 'pull' : p.readyAt <= t ? 'ready' : 'starting'
          return (
            <li key={p.name} className="sim-pod" data-state={state} title={p.name}>
              <span className="sim-pod-box" aria-hidden="true" />
              <span className="sim-pod-name">{p.name.slice(-5)}</span>
              <span className="sim-sr">
                {p.name}: {state === 'ready' ? 'Ready' : state === 'starting' ? `starting, Ready in ${(p.readyAt as number) - t}s` : 'ImagePullBackOff'}
              </span>
              {state === 'starting' && (
                <span className="sim-pod-eta" aria-hidden="true">
                  {(p.readyAt as number) - t}s
                </span>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
