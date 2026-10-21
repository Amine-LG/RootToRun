import { useEffect, useState } from 'react'
import {
  RC_MAX_SURGE,
  RC_MAX_UNAVAILABLE,
  initialReconcile,
  rcDeletePodAction,
  rcDeleteRS,
  rcEditRS,
  rcRelabelPod,
  rcRunToSteady,
  rcScaleDeployment,
  rcSetImage,
  rcStep,
  rcSummary,
  type RcCtrl,
  type RcLog,
  type RcPod,
  type RcState,
} from './models'
import { Btn, Chip, Log, NumField, Panel, SelectField, SimIcon, SimShell, useAnnouncer, useReducedMotion, type Challenge, type ModelScope, type PredictSpec, type Tone } from './ui'

const PREDICT: PredictSpec = {
  question: 'A Deployment keeps 3 replicas of web. You run oc delete pod on one of them. Which control loop creates the replacement pod?',
  choices: [
    { id: 'deploy', label: 'The Deployment controller', feedback: 'The Deployment controller never creates pods. It only manages ReplicaSets (their template and replica count).' },
    { id: 'rs', label: 'The ReplicaSet controller', correct: true, feedback: 'It counts the active pods that match its selector, sees 2 instead of 3, and creates one.' },
    { id: 'kubelet', label: 'The kubelet on the node', feedback: 'The kubelet restarts containers inside an existing pod; it never recreates a deleted pod object.' },
    { id: 'none', label: 'Nobody: you have to re-apply the YAML', feedback: 'Reconciliation exists precisely so that nobody has to: the desired state (3 replicas) is still stored in the API.' },
  ],
  explain: 'Each controller owns one level: Deployment → ReplicaSets, ReplicaSet → Pods, scheduler → node binding, kubelet → containers. Each one only compares its own desired and observed state.',
}

const SCOPE: ModelScope = {
  includes: [
    'Watch events enqueue controller keys; a key already queued is not queued twice (work-queue de-duplication).',
    'The ReplicaSet controller: counts active pods matching its selector (terminating pods do not count), creates or deletes the difference, releases pods whose labels no longer match, adopts matching orphans, updates status.',
    'The Deployment controller: creates a ReplicaSet per pod template (named by pod-template-hash), keeps its replicas equal to the Deployment, and rolls out template changes with maxSurge 25% / maxUnavailable 25%.',
    'Owner references by UID and the garbage collector deleting pods whose owner is gone.',
    'The scheduler binding pods and the kubelet starting and stopping them, as separate loops.',
  ],
  leavesOut: [
    'Real concurrency: controllers run in parallel, here one work item runs per step.',
    'Expectations, resync periods, rate-limited requeues and informer caches. Controllers are only woken when the change matters to them (the real ones also wake and find nothing to do).',
    'Real scheduling (the model picks the least loaded node), image pulls, probes and readiness delays (a started pod is Ready at once).',
    'Graceful termination time, foreground deletion, proportional scaling during a rollout, revisionHistoryLimit cleanup.',
  ],
  links: [
    { label: 'Kubernetes: controllers', url: 'https://kubernetes.io/docs/concepts/architecture/controller/' },
    { label: 'Kubernetes: how a ReplicaSet works', url: 'https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/#how-a-replicaset-works' },
    { label: 'Kubernetes: Deployments', url: 'https://kubernetes.io/docs/concepts/workloads/controllers/deployment/' },
    { label: 'Kubernetes: owners and dependents', url: 'https://kubernetes.io/docs/concepts/overview/working-with-objects/owners-dependents/' },
    { label: 'Kubernetes: garbage collection', url: 'https://kubernetes.io/docs/concepts/architecture/garbage-collection/' },
  ],
}

const IMAGES = ['quay.io/acme/web:1.0', 'quay.io/acme/web:1.1', 'quay.io/acme/web:1.2']
const CTRL_LABEL: Record<RcCtrl | 'you', string> = {
  deployment: 'Deployment controller',
  replicaset: 'ReplicaSet controller',
  scheduler: 'Scheduler',
  kubelet: 'Kubelet',
  'garbage-collector': 'Garbage collector',
  you: 'You',
}
const CTRL_TONE: Record<RcCtrl | 'you', Tone> = { deployment: 'violet', replicaset: 'accent', scheduler: 'info', kubelet: 'warn', 'garbage-collector': 'bad', you: 'ok' }

export default function ReconcileSim() {
  const [s, setS] = useState<RcState>(initialReconcile)
  const [running, setRunning] = useState(false)
  const [msg, announce] = useAnnouncer()
  const reduced = useReducedMotion()
  const [podSel, setPodSel] = useState('')
  const [rsSel, setRsSel] = useState('')
  const [depReplicas, setDepReplicas] = useState(3)
  const [rsReplicas, setRsReplicas] = useState(5)
  const [image, setImage] = useState(IMAGES[1])

  const live = s.pods.filter((p) => !p.terminating)
  const pod = live.find((p) => p.name === podSel) || live[0]
  const rs = s.rss.find((r) => r.name === rsSel) || s.rss[s.rss.length - 1]
  const sum = rcSummary(s)
  const last = s.log[s.log.length - 1]

  const describe = (l: RcLog | undefined) => (l ? `${CTRL_LABEL[l.who]}: ${l.act.length ? l.act.join('; ') : `nothing to do (${l.diff})`}` : '')
  const step = () => {
    const next = rcStep(s)
    setS(next)
    announce(next.queue.length ? describe(next.log[next.log.length - 1]) : `${describe(next.log[next.log.length - 1])}. Queue empty: steady state.`)
  }
  useEffect(() => {
    if (!running) return
    if (!s.queue.length) {
      setRunning(false)
      announce('Steady state: every controller agrees with what it observes.')
      return
    }
    const id = window.setTimeout(() => setS(rcStep(s)), 700)
    return () => window.clearTimeout(id)
  }, [running, s]) // eslint-disable-line react-hooks/exhaustive-deps
  const runAll = () => {
    if (reduced) {
      const next = rcRunToSteady(s)
      setS(next)
      announce(`Ran ${next.n - s.n} reconciliations. Steady state.`)
    } else setRunning(true)
  }
  const act = (next: RcState, text: string) => {
    setRunning(false)
    setS(next)
    announce(next === s ? 'No change.' : `${text}. ${next.queue.length} work item(s) queued.`)
  }

  const challenges: Challenge[] = [
    {
      id: 'self-heal',
      title: 'Self-healing: delete a pod and step until its replacement runs. Which controllers acted?',
      hint: 'Only the ReplicaSet controller, the scheduler and the kubelet should do anything.',
      done: s.markers.includes('user:delete-pod') && s.markers.includes('rs:replace-pod') && sum.steady && sum.running >= s.deploy.replicas,
    },
    {
      id: 'owner-wins',
      title: 'The owner wins: scale the ReplicaSet directly and watch the Deployment controller put it back.',
      hint: 'oc scale replicaset changes the ReplicaSet, but the Deployment still says 3.',
      done: s.markers.includes('deploy:revert-rs') && sum.steady,
    },
    {
      id: 'rollout',
      title: 'Change the template: roll out a new image and reach steady state with only the new ReplicaSet holding pods.',
      hint: 'oc set image creates a new ReplicaSet (new pod-template-hash); keep stepping until the queue is empty.',
      done: s.markers.includes('user:set-image') && sum.steady && s.pods.length > 0 && s.pods.every((p) => p.hash === sum.newHash || p.ownerUid === null) && sum.running >= s.deploy.replicas,
    },
  ]

  const active = last && last.who !== 'you' ? last.key : null
  const orphans = s.pods.filter((p) => p.ownerUid === null)
  const dangling = s.pods.filter((p) => p.ownerUid !== null && !s.rss.some((r) => r.uid === p.ownerUid))

  return (
    <SimShell
      id="reconcile"
      title="Controllers and reconciliation"
      scenario={
        <>
          <p>
            Deployment <code>web</code> wants 3 replicas. Behind it, separate control loops each watch one kind of object and repeat the same cycle: <strong>observe</strong> the current state, <strong>diff</strong> it with the desired state, <strong>act</strong> through the API.
          </p>
          <p>Change something, then step through the loops one work item at a time.</p>
        </>
      }
      predict={PREDICT}
      scope={SCOPE}
      challenges={challenges}
      announcement={msg}
    >
      <div className="sim-work">
        <div className="sim-col">
          <Panel title="Change something (as a user)">
            <div className="sim-form">
              <p className="sim-sub">Deployment web</p>
              <div className="sim-inline">
                <NumField label="replicas" value={depReplicas} onChange={setDepReplicas} min={0} max={6} />
                <Btn onClick={() => act(rcScaleDeployment(s, depReplicas), `oc scale deployment/web --replicas=${depReplicas}`)}>oc scale deployment</Btn>
              </div>
              <div className="sim-inline">
                <SelectField label="image" value={image} onChange={setImage} options={IMAGES.map((i) => ({ value: i, label: i.split('/').pop() as string }))} />
                <Btn onClick={() => act(rcSetImage(s, image), `oc set image deployment/web web=${image}`)}>oc set image</Btn>
              </div>
              <hr className="sim-divider" />
              <p className="sim-sub">ReplicaSet</p>
              {rs ? (
                <>
                  <SelectField label="ReplicaSet" value={rs.name} onChange={setRsSel} options={s.rss.map((r) => ({ value: r.name, label: `${r.name} (rev ${r.revision})` }))} />
                  <div className="sim-inline">
                    <NumField label="replicas" value={rsReplicas} onChange={setRsReplicas} min={0} max={8} />
                    <Btn onClick={() => act(rcEditRS(s, rs.name, rsReplicas), `oc scale replicaset/${rs.name} --replicas=${rsReplicas}`)}>oc scale replicaset</Btn>
                  </div>
                  <Btn variant="danger" onClick={() => act(rcDeleteRS(s, rs.name), `oc delete replicaset ${rs.name}`)}>
                    oc delete replicaset
                  </Btn>
                </>
              ) : (
                <p className="sim-note">No ReplicaSet exists right now.</p>
              )}
              <hr className="sim-divider" />
              <p className="sim-sub">Pod</p>
              {pod ? (
                <>
                  <SelectField label="pod" value={pod.name} onChange={setPodSel} options={live.map((p) => ({ value: p.name, label: `${p.name}${p.ownerUid === null ? ' (orphan)' : ''}` }))} />
                  <div className="sim-actions">
                    <Btn variant="danger" onClick={() => act(rcDeletePodAction(s, pod.name), `oc delete pod ${pod.name}`)}>
                      oc delete pod
                    </Btn>
                    <Btn onClick={() => act(rcRelabelPod(s, pod.name), `oc label pod ${pod.name} app=web-debug`)} disabled={pod.app !== 'web'}>
                      relabel app=web-debug
                    </Btn>
                  </div>
                </>
              ) : (
                <p className="sim-note">No pods.</p>
              )}
            </div>
          </Panel>
        </div>

        <div className="sim-col">
          <Panel
            title="Control loops"
            aside={
              <Chip tone={sum.steady ? 'ok' : 'warn'}>
                {sum.steady ? 'steady state' : `${s.queue.length} queued`}
              </Chip>
            }
          >
            <div className="sim-form">
              <div className="sim-actions">
                <Btn variant="primary" icon="step" onClick={step} disabled={!s.queue.length || running}>
                  Step: next work item
                </Btn>
                <Btn icon={running ? 'x' : 'play'} onClick={() => (running ? setRunning(false) : runAll())} disabled={!s.queue.length}>
                  {running ? 'Pause' : 'Run until steady'}
                </Btn>
              </div>
              <p className="sim-note sim-next">
                {s.queue.length ? (
                  <>
                    Next: <Chip tone={CTRL_TONE[s.queue[0].ctrl]}>{CTRL_LABEL[s.queue[0].ctrl]}</Chip> <span className="sim-mono">{s.queue[0].key}</span>
                  </>
                ) : (
                  'Nothing queued: change something on the left.'
                )}
              </p>
            </div>
          </Panel>

          <Panel title="Objects">
            <div className="sim-tree">
              <div className="sim-obj" data-kind="deployment" data-active={active === 'web' && last?.who === 'deployment'}>
                <div className="sim-obj-head">
                  <Chip tone="violet">Deployment</Chip>
                  <span className="sim-mono sim-strong">web</span>
                </div>
                <p className="sim-obj-spec">
                  replicas <strong>{s.deploy.replicas}</strong> · image <code>{s.deploy.image.split('/').pop()}</code> · strategy RollingUpdate {RC_MAX_SURGE}/{RC_MAX_UNAVAILABLE}
                </p>
              </div>
              <div className="sim-tree-rs">
                {s.rss.map((r) => {
                  const pods = s.pods.filter((p) => p.ownerUid === r.uid)
                  return (
                    <div key={r.uid} className="sim-obj" data-kind="rs" data-active={active === r.name && (last?.who === 'replicaset' || last?.who === 'garbage-collector')} data-current={r.hash === sum.newHash}>
                      <div className="sim-obj-head">
                        <Chip tone="accent">ReplicaSet</Chip>
                        <span className="sim-mono sim-strong">{r.name}</span>
                        <span className="sim-muted">rev {r.revision}</span>
                      </div>
                      <p className="sim-obj-spec">
                        spec <strong>{r.replicas}</strong> · ready {r.readyReplicas} · <code>{r.image.split('/').pop()}</code>
                      </p>
                      <PodChips pods={pods} active={active} />
                    </div>
                  )
                })}
                {s.rss.length === 0 && <p className="sim-empty">No ReplicaSet.</p>}
              </div>
              {dangling.length > 0 && (
                <div className="sim-obj" data-kind="orphans">
                  <div className="sim-obj-head">
                    <Chip tone="bad">owner deleted</Chip>
                    <span className="sim-muted">their ownerReference points to a ReplicaSet UID that no longer exists: garbage for the garbage collector</span>
                  </div>
                  <PodChips pods={dangling} active={active} />
                </div>
              )}
              {orphans.length > 0 && (
                <div className="sim-obj" data-kind="orphans">
                  <div className="sim-obj-head">
                    <Chip tone="warn">no owner</Chip>
                    <span className="sim-muted">pods without a controller ownerReference</span>
                  </div>
                  <PodChips pods={orphans} active={active} />
                </div>
              )}
            </div>
          </Panel>

          <Panel title="Last reconcile">
            {last && last.who !== 'you' ? (
              <div className="sim-ooda" aria-live="off">
                <p className="sim-ooda-who">
                  <Chip tone={CTRL_TONE[last.who]}>{CTRL_LABEL[last.who]}</Chip> <span className="sim-mono">{last.key}</span> <span className="sim-muted">step {last.n}</span>
                </p>
                <ol className="sim-ooda-steps">
                  <li>
                    <span className="sim-ooda-tag">observe</span>
                    <span>{last.observe}</span>
                  </li>
                  <li>
                    <span className="sim-ooda-tag">diff</span>
                    <span>{last.diff}</span>
                  </li>
                  <li>
                    <span className="sim-ooda-tag">act</span>
                    <span>
                      {last.act.length ? (
                        last.act.map((a) => (
                          <code key={a} className="sim-ooda-act">
                            {a}
                          </code>
                        ))
                      ) : (
                        <span className="sim-muted">nothing</span>
                      )}
                    </span>
                  </li>
                </ol>
              </div>
            ) : (
              <p className="sim-empty">{last ? 'You changed something: step to let the controllers react.' : 'Change something on the left, then step.'}</p>
            )}
          </Panel>

          <Panel title="Work queue" aside={<span className="sim-muted sim-mono">{s.queue.length} item(s)</span>}>
                {s.queue.length ? (
                  <ol className="sim-queue">
                    {s.queue.map((w, i) => (
                      <li key={`${w.ctrl}-${w.key}`} data-next={i === 0}>
                        <Chip tone={CTRL_TONE[w.ctrl]}>{CTRL_LABEL[w.ctrl]}</Chip> <span className="sim-mono">{w.key}</span> <span className="sim-muted">· {w.why}</span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="sim-empty">Empty. Every controller agrees with what it observes, so nothing runs.</p>
                )}
          </Panel>

          <Panel title="History">
            <Log
              items={s.log}
              keyOf={(l) => l.n}
              empty="Nothing has happened yet."
              initial={8}
              render={(l) => (
                <>
                  <div className="sim-log-meta">
                    <span className="sim-mono">#{l.n}</span>
                    <Chip tone={CTRL_TONE[l.who]}>{CTRL_LABEL[l.who]}</Chip>
                    {l.who !== 'you' && <span className="sim-mono">{l.key}</span>}
                  </div>
                  {l.who === 'you' ? <code>{l.act[0]}</code> : <span>{l.act.length ? l.act.join(' · ') : <span className="sim-muted">no action: {l.diff}</span>}</span>}
                </>
              )}
            />
          </Panel>
        </div>
      </div>
    </SimShell>
  )
}

function PodChips({ pods, active }: { pods: RcPod[]; active: string | null }) {
  if (!pods.length) return <p className="sim-empty">no pods</p>
  return (
    <ul className="sim-podchips">
      {pods.map((p) => {
        const state = p.terminating ? 'terminating' : p.phase === 'Running' ? 'running' : p.node ? 'creating' : 'pending'
        const label = state === 'terminating' ? 'Terminating' : state === 'running' ? 'Running' : state === 'creating' ? 'ContainerCreating' : 'Pending (unscheduled)'
        return (
          <li key={p.name} className="sim-podchip" data-state={state} data-active={active === p.name}>
            <span className="sim-podchip-dot" aria-hidden="true">
              {state === 'terminating' ? <SimIcon name="x" size={12} /> : state === 'running' ? <SimIcon name="check" size={12} /> : null}
            </span>
            <span className="sim-podchip-text">
              <span className="sim-mono">{p.name.split('-').pop()}</span>
              <span className="sim-muted">
                {label}
                {p.node ? ` · ${p.node}` : ''}
                {p.app !== 'web' ? ` · app=${p.app}` : ''}
              </span>
            </span>
          </li>
        )
      })}
    </ul>
  )
}
