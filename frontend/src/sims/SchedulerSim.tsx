import { useMemo, useState } from 'react'
import { SAMPLE_NODES, SCORE_PLUGIN_ORDER, simulate, taintText, type NodeResult, type Profile, type SimNode, type SimPod } from '../lib/scheduler'
import { Btn, Chip, Code, Meter, NumField, Panel, Segmented, SelectField, SimIcon, SimShell, Toggle, useAnnounceChange, type Challenge, type ModelScope, type PredictSpec } from './ui'

const PREDICT: PredictSpec = {
  question:
    'A payments pod requests 500m CPU and 1Gi of memory. worker-a1 already caches its image and runs one payments replica; worker-b1 is mostly idle; worker-c1 is the biggest node but carries a gpu=true:NoSchedule taint. With the default profile, where does the pod go?',
  choices: [
    { id: 'a1', label: 'worker-a1: the image is already there', feedback: 'ImageLocality does favour worker-a1, but the bonus is small: the image is scaled by how few nodes have it and clamped to a 23MB–1GB range.' },
    { id: 'b1', label: 'worker-b1: the emptier node wins', correct: true, feedback: 'LeastAllocated, BalancedAllocation and the default topology spreading all prefer worker-b1, and they outweigh the small image bonus.' },
    { id: 'c1', label: 'worker-c1: it has the most free capacity', feedback: 'worker-c1 never reaches scoring: its NoSchedule taint filters it out because the pod has no toleration.' },
    { id: 'pending', label: 'Nowhere: the pod stays Pending', feedback: 'Two nodes pass every filter, so the pod is schedulable.' },
  ],
  explain: 'Filtering decides which nodes are possible; scoring only ranks those survivors. Open a node card to see every plugin, its 0–100 score and its weight.',
}

const SCOPE: ModelScope = {
  includes: [
    'Filter plugins NodeUnschedulable, TaintToleration, NodeAffinity (nodeSelector + one required term), NodeResourcesFit, PodTopologySpread (DoNotSchedule) and InterPodAffinity (anti-affinity on the hostname), in the real order.',
    'Score plugins with their upstream 1.34 formulas and default weights: TaintToleration ×3, NodeAffinity ×2, PodTopologySpread ×2, InterPodAffinity ×2, NodeResourcesFit ×1, NodeResourcesBalancedAllocation ×1, ImageLocality ×1.',
    'NodeResourcesFit LeastAllocated vs MostAllocated, the "non-zero" 100m/200Mi requests used when scoring pods without requests, and the BalancedAllocation skip for best-effort pods.',
    'System default topology spreading (hostname maxSkew 3, zone maxSkew 5, ScheduleAnyway) for pods owned by a controller.',
    'OpenShift profiles: LowNodeUtilization (the default), HighNodeUtilization (MostAllocated with weight 5, no BalancedAllocation), NoScoring (no score plugins).',
    'The FailedScheduling message format, counting only the first failing filter of each node.',
    'When only one node passes the filters, the scheduler picks it without scoring, as kube-scheduler does.',
  ],
  leavesOut: [
    'Other filters: NodeName, NodePorts, volume plugins (VolumeBinding, VolumeZone, VolumeRestrictions, NodeVolumeLimits), DynamicResources, scheduling gates.',
    'Preemption, pod priority, the scheduling queue and back-off, extenders and multiple profiles per cluster.',
    'Random tie-breaking: tied nodes are all shown; the real scheduler picks one at random.',
    'percentageOfNodesToScore (only matters above 100 nodes), pod overhead, init containers, extended resources.',
    'Pod affinity (attraction), several node affinity terms, matchLabelKeys, minDomains and the node inclusion policies other than the defaults.',
    'The real scheduler stops at the first failing filter of a node; the model evaluates all of them so you can see every reason.',
  ],
  links: [
    { label: 'Kubernetes: kube-scheduler', url: 'https://kubernetes.io/docs/concepts/scheduling-eviction/kube-scheduler/' },
    { label: 'Kubernetes: scheduling plugins and weights', url: 'https://kubernetes.io/docs/reference/scheduling/config/#scheduling-plugins' },
    { label: 'Kubernetes: resource bin packing (LeastAllocated / MostAllocated)', url: 'https://kubernetes.io/docs/concepts/scheduling-eviction/resource-bin-packing/' },
    { label: 'Kubernetes: taints and tolerations', url: 'https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/' },
    { label: 'Kubernetes: assigning pods to nodes (affinity)', url: 'https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/' },
    { label: 'Kubernetes: pod topology spread constraints', url: 'https://kubernetes.io/docs/concepts/scheduling-eviction/topology-spread-constraints/' },
    { label: 'OpenShift 4.21: scheduler profiles', url: 'https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/nodes/controlling-pod-placement-onto-nodes-scheduling#nodes-scheduler-profiles' },
  ],
}

type SelectorOpt = '' | 'disktype=ssd' | 'disktype=nvme' | 'gpu=true'
type SpreadOpt = 'default' | 'DoNotSchedule' | 'ScheduleAnyway'
type AntiOpt = 'none' | 'preferred' | 'required'

const PLUGIN_SHORT: Record<string, string> = {
  TaintToleration: 'TaintToleration',
  NodeAffinity: 'NodeAffinity',
  NodeResourcesFit: 'NodeResourcesFit',
  PodTopologySpread: 'PodTopologySpread',
  InterPodAffinity: 'InterPodAffinity',
  NodeResourcesBalancedAllocation: 'BalancedAllocation',
  ImageLocality: 'ImageLocality',
}

export default function SchedulerSim() {
  const [nodes, setNodes] = useState<SimNode[]>(SAMPLE_NODES)
  const [profile, setProfile] = useState<Profile>('LowNodeUtilization')
  const [cpu, setCpu] = useState(500)
  const [mem, setMem] = useState(1024)
  const [sel, setSel] = useState<SelectorOpt>('')
  const [preferSsd, setPreferSsd] = useState(false)
  const [tolGpu, setTolGpu] = useState(false)
  const [spread, setSpread] = useState<SpreadOpt>('default')
  const [anti, setAnti] = useState<AntiOpt>('none')

  const pod: SimPod = useMemo(
    () => ({
      cpu,
      mem,
      image: 'registry.example/payments:1.4',
      nodeSelector: sel ? { [sel.split('=')[0]]: sel.split('=')[1] } : {},
      required: [],
      preferred: preferSsd ? [{ weight: 80, term: { key: 'disktype', operator: 'In', values: ['ssd'] } }] : [],
      tolerations: tolGpu ? [{ key: 'gpu', operator: 'Equal', value: 'true', effect: 'NoSchedule' }] : [],
      spread: spread === 'default' ? undefined : { topologyKey: 'zone', maxSkew: 1, when: spread },
      podAntiAffinity: anti,
    }),
    [cpu, mem, sel, preferSsd, tolGpu, spread, anti],
  )
  const res = useMemo(() => simulate(nodes, pod, profile), [nodes, pod, profile])
  const outcome = res.message ? `Pending: ${res.message}` : `Scheduled to ${res.winners.join(' or ')}${res.winners.length > 1 ? ' (tie)' : ''}`
  const msg = useAnnounceChange(outcome)

  const challenges: Challenge[] = [
    { id: 'pending', title: 'Make the pod Pending and read the FailedScheduling event: which nodes failed which filter?', hint: 'Ask for more CPU than any untainted node has left, or pick a nodeSelector no node matches.', done: !!res.message },
    {
      id: 'tolerate',
      title: 'A toleration allows, it does not attract: land the pod on worker-c1 with an empty nodeSelector.',
      hint: 'Add the toleration only. Then look at why worker-c1 wins the scoring phase.',
      done: res.winners.length === 1 && res.winners[0] === 'worker-c1' && sel === '',
    },
    { id: 'binpack', title: 'Bin-pack: choose the profile under which the busiest feasible node (worker-a1) wins.', hint: 'One OpenShift profile switches NodeResourcesFit to MostAllocated and multiplies it by 5.', done: profile === 'HighNodeUtilization' && res.winners.length === 1 && res.winners[0] === 'worker-a1' },
  ]

  const toggleNode = (name: string, patch: (n: SimNode) => SimNode) => setNodes((ns) => ns.map((n) => (n.name === name ? patch(n) : n)))

  return (
    <SimShell
      id="scheduler"
      title="Scheduler: filter and score"
      scenario={
        <>
          <p>
            A new <code>payments</code> pod is waiting for a node. kube-scheduler first <strong>filters</strong> out nodes that cannot run it, then <strong>scores</strong> the survivors with weighted plugins and binds the pod to the highest total.
          </p>
          <p>Change the pod spec, cordon or taint nodes, and switch the OpenShift scheduler profile to see each decision.</p>
        </>
      }
      predict={PREDICT}
      scope={SCOPE}
      challenges={challenges}
      announcement={msg}
    >
      <div className="sim-work">
        <div className="sim-col">
          <Panel title="Pod spec">
            <div className="sim-form">
              <div className="sim-row">
                <NumField label="CPU request" value={cpu} onChange={setCpu} min={0} max={16000} step={100} unit="m" />
                <NumField label="Memory request" value={mem} onChange={setMem} min={0} max={64000} step={256} unit="Mi" />
              </div>
              <SelectField<SelectorOpt>
                label="nodeSelector"
                value={sel}
                onChange={setSel}
                options={[
                  { value: '', label: 'none' },
                  { value: 'disktype=ssd', label: 'disktype=ssd' },
                  { value: 'disktype=nvme', label: 'disktype=nvme (no node has it)' },
                  { value: 'gpu=true', label: 'gpu=true' },
                ]}
              />
              <Toggle label="Prefer disktype=ssd (preferred affinity, weight 80)" checked={preferSsd} onChange={setPreferSsd} />
              <Toggle label="Tolerate gpu=true:NoSchedule" checked={tolGpu} onChange={setTolGpu} />
              <SelectField<SpreadOpt>
                label="Topology spread"
                value={spread}
                onChange={setSpread}
                options={[
                  { value: 'default', label: 'none set (system defaults apply)' },
                  { value: 'DoNotSchedule', label: 'zone, maxSkew 1, DoNotSchedule' },
                  { value: 'ScheduleAnyway', label: 'zone, maxSkew 1, ScheduleAnyway' },
                ]}
                hint="DoNotSchedule is a filter; ScheduleAnyway only changes scores."
              />
              <SelectField<AntiOpt>
                label="Pod anti-affinity (app=payments, per host)"
                value={anti}
                onChange={setAnti}
                options={[
                  { value: 'none', label: 'none' },
                  { value: 'preferred', label: 'preferred (weight 100)' },
                  { value: 'required', label: 'required' },
                ]}
              />
            </div>
          </Panel>
          <Panel title="Scheduler profile">
            <Segmented<Profile>
              label="KubeScheduler cluster profile"
              value={profile}
              onChange={setProfile}
              options={[
                { value: 'LowNodeUtilization', label: 'LowNode' },
                { value: 'HighNodeUtilization', label: 'HighNode' },
                { value: 'NoScoring', label: 'NoScoring' },
              ]}
              hint={
                profile === 'LowNodeUtilization'
                  ? 'Default: spread pods for low utilisation per node (LeastAllocated).'
                  : profile === 'HighNodeUtilization'
                    ? 'Pack pods onto as few nodes as possible: MostAllocated ×5, no BalancedAllocation.'
                    : 'Fastest: every score plugin disabled, any feasible node will do.'
              }
            />
          </Panel>
        </div>

        <div className="sim-col">
          <Outcome res={res} />
          <div className="sim-nodes">
            {res.results.map((r) => (
              <NodeCard key={r.node.name} r={r} pod={pod} winner={res.winners.includes(r.node.name)} tie={res.winners.length > 1} weights={res.weights} onCordon={() => toggleNode(r.node.name, (n) => ({ ...n, unschedulable: !n.unschedulable }))} onSoftTaint={() => toggleNode(r.node.name, (n) => (n.taints.some((t) => t.key === 'maintenance') ? { ...n, taints: n.taints.filter((t) => t.key !== 'maintenance') } : { ...n, taints: [...n.taints, { key: 'maintenance', value: 'soon', effect: 'PreferNoSchedule' }] }))} />
            ))}
          </div>
          {res.skipped.length > 0 && (
            <p className="sim-note">
              Not scoring: {res.skipped.map((s, i) => (
                <span key={s.plugin}>
                  {i > 0 && '; '}
                  <strong>{s.plugin}</strong> ({s.why})
                </span>
              ))}
              .
            </p>
          )}
        </div>
      </div>
    </SimShell>
  )
}

function Outcome({ res }: { res: ReturnType<typeof simulate> }) {
  if (res.message)
    return (
      <div className="sim-banner" data-tone="bad">
        <SimIcon name="alert" />
        <div className="sim-banner-body">
          <p>
            <strong>Pod stays Pending.</strong> <code>oc describe pod</code> shows:
          </p>
          <Code>{`Warning  FailedScheduling  default-scheduler  ${res.message}`}</Code>
        </div>
      </div>
    )
  return (
    <div className="sim-banner" data-tone="ok">
      <SimIcon name="check" />
      <div className="sim-banner-body">
        <p>
          <strong>Bound to {res.winners.join(' or ')}.</strong>{' '}
          {res.profile === 'NoScoring' ? 'No score plugin ran, so every feasible node ties; the scheduler picks one at random.' : res.scorePlugins.length === 0 ? 'It is the only node that passed every filter, so the scheduler binds the pod there without scoring.' : res.winners.length > 1 ? 'Tie: the real scheduler picks one of these at random.' : `Highest weighted total among ${res.results.filter((r) => r.feasible).length} feasible node(s).`}
        </p>
        <p className="sim-note">
          Event: <code>Normal Scheduled default-scheduler Successfully assigned shop/payments-7c9d to {res.winners[0]}</code>
        </p>
      </div>
    </div>
  )
}

function NodeCard({ r, pod, winner, tie, weights, onCordon, onSoftTaint }: { r: NodeResult; pod: SimPod; winner: boolean; tie: boolean; weights: Record<string, number>; onCordon: () => void; onSoftTaint: () => void }) {
  const n = r.node
  const state = !r.feasible ? 'filtered' : winner ? 'winner' : 'feasible'
  const plugins = SCORE_PLUGIN_ORDER.filter((p) => r.scores[p] !== undefined)
  const soft = n.taints.some((t) => t.key === 'maintenance')
  return (
    <article className="sim-node" data-state={state} aria-label={`${n.name}: ${state === 'filtered' ? 'filtered out' : winner ? (tie ? 'tied for first' : 'selected') : 'feasible'}`}>
      <header className="sim-node-head">
        <h4 className="sim-node-name">{n.name}</h4>
        <Chip tone="muted">{n.zone}</Chip>
        {state === 'winner' && <Chip tone="ok">{tie ? 'tie' : 'selected'}</Chip>}
        {state === 'filtered' && <Chip tone="bad">filtered out</Chip>}
        {n.unschedulable && <Chip tone="warn">cordoned</Chip>}
      </header>
      <div className="sim-node-res">
        <ResourceLine label="CPU" used={n.usedCpu} req={pod.cpu} cap={n.cpu} unit="m" />
        <ResourceLine label="Memory" used={n.usedMem} req={pod.mem} cap={n.mem} unit="Mi" />
      </div>
      <div className="sim-chips">
        {Object.entries(n.labels)
          .filter(([k]) => !k.startsWith('node-role'))
          .map(([k, v]) => (
            <Chip key={k}>{`${k}=${v}`}</Chip>
          ))}
        {Object.keys(n.labels)
          .filter((k) => k.startsWith('node-role'))
          .map((k) => (
            <Chip key={k}>{k.replace('node-role.kubernetes.io/', 'role: ')}</Chip>
          ))}
        {n.taints.map((t) => (
          <Chip key={t.key} tone="warn" title="taint">
            {taintText(t)}
          </Chip>
        ))}
        {(n.appPods || 0) > 0 && <Chip tone="info">{n.appPods} payments pod</Chip>}
        {(n.images || []).length > 0 && <Chip tone="accent">image cached</Chip>}
      </div>

      <h5 className="sim-sub">Filter</h5>
      <ul className="sim-filters">
        {r.filters.map((f) => (
          <li key={f.plugin} data-pass={f.pass} data-skipped={f.skippedByRealScheduler || undefined}>
            <span className="sim-filter-mark" aria-hidden="true">
              <SimIcon name={f.pass ? 'check' : 'x'} size={14} />
            </span>
            <span className="sim-sr">{f.pass ? 'passes' : 'fails'}: </span>
            <span>
              <strong>{f.plugin}</strong> <span className="sim-muted">{f.reason}</span>
              {f.skippedByRealScheduler && <span className="sim-muted"> (not run by the real scheduler: an earlier filter already failed)</span>}
            </span>
          </li>
        ))}
      </ul>

      {r.feasible && plugins.length > 0 && (
        <>
          <h5 className="sim-sub">Score</h5>
          <ul className="sim-scores">
            {plugins.map((p) => {
              const d = r.details[p]
              const w = weights[p] ?? 1
              return (
                <li key={p}>
                  <div className="sim-score-row">
                    <span className="sim-score-name" title={p}>
                      {PLUGIN_SHORT[p] || p}
                    </span>
                    <span className="sim-score-val">
                      {d.score} × {w} = <strong>{d.score * w}</strong>
                    </span>
                  </div>
                  <Meter value={d.score} max={100} label={`${p} score ${d.score} of 100`} tone={d.score >= 70 ? 'ok' : d.score >= 35 ? 'accent' : 'muted'} />
                  <p className="sim-score-why">{d.explain}</p>
                </li>
              )
            })}
          </ul>
          <p className="sim-total">
            Total <strong>{r.total}</strong>
          </p>
        </>
      )}
      {r.feasible && plugins.length === 0 && <p className="sim-note">Feasible. No score plugin ran.</p>}

      <div className="sim-actions sim-node-actions">
        <Btn onClick={onCordon} icon={n.unschedulable ? 'play' : 'x'}>
          {n.unschedulable ? `Uncordon ${n.name}` : `Cordon ${n.name}`}
        </Btn>
        <Btn onClick={onSoftTaint} variant="quiet">
          {soft ? 'Remove PreferNoSchedule taint' : 'Add maintenance=soon:PreferNoSchedule'}
        </Btn>
      </div>
    </article>
  )
}

function ResourceLine({ label, used, req, cap, unit }: { label: string; used: number; req: number; cap: number; unit: string }) {
  return (
    <div className="sim-resline">
      <div className="sim-resline-text">
        <span>{label}</span>
        <span className="sim-muted">
          {used}
          {unit} requested + {req}
          {unit} of {cap}
          {unit}
        </span>
      </div>
      <Meter value={used} extra={req} max={cap} label={`${label}: ${used}${unit} already requested, this pod asks ${req}${unit}, ${cap}${unit} allocatable`} tone="muted" />
    </div>
  )
}
