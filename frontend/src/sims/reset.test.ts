// "Reset model" (sims/ui.tsx withReset) mounts the model again: it is a real reset only if every model starts from a
// fresh initial state and no action changes that initial state or the shared defaults in place. These tests freeze the
// starting state and the defaults, play every kind of action on them (a mutation throws on frozen objects), then check
// that a new start is exactly the original one.
import { describe, expect, it } from 'vitest'
import {
  argoReconcile, DEFAULT_TRAFFIC, gitSetField, initialDrift, initialReconcile, initialRollout, initialStorage, liveCreateUntracked, liveDelete,
  liveSetField, RBAC_BINDINGS, rcDeletePodAction, rcEditRS, rcRelabelPod, rcRunToSteady, rcScaleDeployment, rcSetImage, rcStep, rollbackRollout,
  runRollout, sendRequest, setDriftPolicy, simulateProbes, stCreatePod, stCreatePVC, stDeletePod, stDeletePVC, startRollout, DEFAULT_PROBE,
  ROLLOUT_BAD_IMAGE, ROLLOUT_GOOD_IMAGE, type RolloutConfig, type ProbeConfig, canI, RBAC_RESOURCES, RBAC_IDENTITIES,
} from './models'
import { SAMPLE_NODES, simulate } from '../lib/scheduler'
import { evaluateAccess, permsPresets } from './perms'

function deepFreeze<T>(x: T): T {
  if (x && typeof x === 'object' && !Object.isFrozen(x)) {
    Object.freeze(x)
    for (const v of Object.values(x as object)) deepFreeze(v)
  }
  return x
}
const snap = <T,>(x: T): T => structuredClone(x)

describe('Reset model restores the starting state of every model', () => {
  it('controllers and reconciliation', () => {
    const before = snap(initialReconcile())
    let s = deepFreeze(initialReconcile())
    s = rcDeletePodAction(s, s.pods[0].name)
    s = rcStep(s)
    s = rcScaleDeployment(s, 5)
    s = rcEditRS(s, s.rss[0].name, 1)
    s = rcSetImage(s, 'quay.io/acme/web:1.1')
    s = rcRelabelPod(s, s.pods[0].name)
    s = rcRunToSteady(s)
    expect(s).not.toEqual(before) // the actions did change the model
    expect(initialReconcile()).toEqual(before)
  })

  it('rolling update', () => {
    const cfg: RolloutConfig = deepFreeze({ replicas: 4, maxSurge: '25%', maxUnavailable: '25%', readySeconds: 10, progressDeadlineSeconds: 600, strategy: 'RollingUpdate' })
    const before = snap(initialRollout(cfg))
    let s = deepFreeze(initialRollout(cfg))
    s = runRollout(startRollout(s, ROLLOUT_BAD_IMAGE, false))
    s = rollbackRollout(s)
    s = runRollout(startRollout(s, ROLLOUT_GOOD_IMAGE, true))
    expect(s).not.toEqual(before)
    expect(initialRollout(cfg)).toEqual(before)
  })

  it('storage', () => {
    const sc = deepFreeze({ bindingMode: 'WaitForFirstConsumer' as const, reclaimPolicy: 'Delete' as const })
    const before = snap(initialStorage(sc))
    let s = deepFreeze(initialStorage(sc))
    s = stCreatePVC(s)
    s = stCreatePod(s)
    s = stDeletePod(s, s.pods[0].name)
    s = stDeletePVC(s)
    expect(s).not.toEqual(before)
    expect(initialStorage(sc)).toEqual(before)
  })

  it('GitOps drift', () => {
    const policy = deepFreeze({ automated: true, selfHeal: false, prune: false })
    const before = snap(initialDrift(policy))
    let s = deepFreeze(initialDrift(policy))
    s = liveSetField(s, 'Deployment', 'web', 'spec.replicas', '5', 'oc scale deployment/web --replicas=5')
    s = gitSetField(s, 'ConfigMap', 'web-config', 'data.LOG_LEVEL', 'debug', 'more logs')
    s = liveCreateUntracked(s)
    s = liveDelete(s, 'CronJob', 'report')
    s = argoReconcile(setDriftPolicy(s, { automated: true, selfHeal: true, prune: true }))
    expect(s).not.toEqual(before)
    expect(initialDrift(policy)).toEqual(before)
  })

  it('the shared defaults of the stateless models are never changed by using them', () => {
    const traffic = snap(DEFAULT_TRAFFIC), nodes = snap(SAMPLE_NODES), bindings = snap(RBAC_BINDINGS), probe = snap(DEFAULT_PROBE)
    deepFreeze(DEFAULT_TRAFFIC); deepFreeze(SAMPLE_NODES); deepFreeze(RBAC_BINDINGS); deepFreeze(DEFAULT_PROBE)
    sendRequest(DEFAULT_TRAFFIC, 'router'); sendRequest(DEFAULT_TRAFFIC, 'client', 2)
    simulate(SAMPLE_NODES, { cpu: 500, mem: 1024, image: 'registry.example/payments:1.4', nodeSelector: {}, required: [], preferred: [], tolerations: [] }, 'HighNodeUtilization')
    canI({ identity: RBAC_IDENTITIES[0], verb: 'list', resource: RBAC_RESOURCES[0], namespace: 'team-a' }, RBAC_BINDINGS)
    const app = { startSeconds: 5, exitAfterSeconds: 3, hangAfterSeconds: null, dependencyDown: { from: 60, to: 120 }, livenessChecksDependency: false, healthLatencySeconds: 0 }
    const cfg: ProbeConfig = deepFreeze({ startup: DEFAULT_PROBE, readiness: { ...DEFAULT_PROBE, enabled: true }, liveness: { ...DEFAULT_PROBE, enabled: true }, app, horizon: 180 })
    simulateProbes(cfg)
    expect(DEFAULT_TRAFFIC).toEqual(traffic)
    expect(SAMPLE_NODES).toEqual(nodes)
    expect(RBAC_BINDINGS).toEqual(bindings)
    expect(DEFAULT_PROBE).toEqual(probe)
  })

  it('file permissions: presets are rebuilt for every start and evaluating them changes nothing', () => {
    const a = permsPresets()
    const before = snap(a)
    for (const p of deepFreeze(a)) evaluateAccess(p.nodes, p.process, p.operation, p.target)
    expect(permsPresets()).toEqual(before)
  })
})
