import { describe, expect, it } from 'vitest'
import { SAMPLE_NODES, simulate, type SimNode, type SimPod } from '../lib/scheduler'
import {
  BACKOFF_MAX,
  DEFAULT_PROBE,
  DEFAULT_TRAFFIC,
  RBAC_BINDINGS,
  RBAC_IDENTITIES,
  RBAC_RESOURCES,
  RBAC_ROLES,
  ROLLOUT_BAD_IMAGE,
  ROLLOUT_GOOD_IMAGE,
  admitPod,
  appHealth,
  appSyncStatus,
  argoManualSync,
  argoReconcile,
  canI,
  driftRows,
  endpointSlice,
  gitRemove,
  gitSetField,
  initialDrift,
  initialReconcile,
  initialRollout,
  initialStorage,
  liveCreateUntracked,
  liveDelete,
  liveSetField,
  maxUnavailableFor,
  newRSNewReplicas,
  ocDiff,
  planOldScaleDown,
  rcDeletePodAction,
  rcDeleteRS,
  rcEditRS,
  rcRelabelPod,
  rcRunToSteady,
  rcScaleDeployment,
  rcSetImage,
  rcStep,
  rcSummary,
  setDriftPolicy,
  resolveFenceposts,
  rollbackRollout,
  rolloutCounts,
  rolloutStatusText,
  rolloutStep,
  ruleAllows,
  runRollout,
  sendRequest,
  simulateProbes,
  probeSnapshot,
  probeStatusAt,
  startRollout,
  stCreatePVC,
  stCreatePod,
  stDeletePod,
  stDeletePV,
  stDeletePVC,
  stPatchReclaim,
  stReservePV,
  templateHash,
  userInfo,
  validateBinding,
  validateProbes,
  validateRollingUpdate,
  type AppScript,
  type Binding,
  type ProbeConfig,
  type PodSecuritySpec,
  type RolloutConfig,
  type RolloutState,
  type StorageState,
  type TrafficConfig,
} from './models'

// =====================================================================================================
describe('scheduler (kube-scheduler 1.34 default profile model)', () => {
  const pod = (p: Partial<SimPod> = {}): SimPod => ({ cpu: 500, mem: 1024, image: 'registry.example/payments:1.4', nodeSelector: {}, required: [], preferred: [], tolerations: [], ...p })
  const byName = (r: ReturnType<typeof simulate>, n: string) => r.results.find((x) => x.node.name === n)!

  it('filters tainted nodes and scores the rest with the default weights', () => {
    const r = simulate(SAMPLE_NODES, pod())
    expect(r.results.filter((x) => x.feasible).map((x) => x.node.name)).toEqual(['worker-a1', 'worker-b1'])
    const a1 = byName(r, 'worker-a1')
    const b1 = byName(r, 'worker-b1')
    // LeastAllocated: a1 cpu (4000-3700)*100/4000=7, mem (16000-10024)*100/16000=37 → 22
    expect(a1.scores.NodeResourcesFit).toBe(22)
    expect(b1.scores.NodeResourcesFit).toBe(62)
    expect(a1.scores.NodeResourcesBalancedAllocation).toBe(85)
    expect(b1.scores.NodeResourcesBalancedAllocation).toBe(94)
    // ImageLocality: 350MB × 1/4 nodes ≈ 87.5MB → 100 × (87.5−23)/(1000−23) = 6
    expect(a1.scores.ImageLocality).toBe(6)
    expect(b1.scores.ImageLocality).toBe(0)
    // System default spreading (hostname maxSkew 3, zone maxSkew 5) favours the node without replicas
    expect(a1.scores.PodTopologySpread).toBe(66)
    expect(b1.scores.PodTopologySpread).toBe(100)
    expect(a1.total).toBe(22 * 1 + 85 * 1 + 100 * 3 + 6 * 1 + 66 * 2)
    expect(r.winners).toEqual(['worker-b1'])
    expect(r.skipped.map((s) => s.plugin)).toEqual(expect.arrayContaining(['NodeAffinity', 'InterPodAffinity']))
  })

  it('HighNodeUtilization uses MostAllocated with weight 5 and no BalancedAllocation', () => {
    const r = simulate(SAMPLE_NODES, pod(), 'HighNodeUtilization')
    expect(r.weights.NodeResourcesFit).toBe(5)
    expect(r.scorePlugins).not.toContain('NodeResourcesBalancedAllocation')
    expect(byName(r, 'worker-a1').scores.NodeResourcesFit).toBe(77)
    expect(r.winners).toEqual(['worker-a1'])
  })

  it('NoScoring leaves every feasible node tied', () => {
    const r = simulate(SAMPLE_NODES, pod(), 'NoScoring')
    expect(r.scorePlugins).toEqual([])
    expect(r.winners).toEqual(['worker-a1', 'worker-b1'])
  })

  it('reports only the first failing filter per node, in the real message format', () => {
    const r = simulate(SAMPLE_NODES, pod({ cpu: 7500 }))
    expect(r.winners).toEqual([])
    expect(r.message).toBe(
      '0/4 nodes are available: 2 Insufficient cpu, 2 node(s) had untolerated taint(s). no new claims to deallocate, preemption: 0/4 nodes are available: 4 Preemption is not helpful for scheduling.',
    )
    const c1 = byName(r, 'worker-c1')
    expect(c1.filters.find((f) => f.plugin === 'NodeResourcesFit')).toMatchObject({ pass: false, skippedByRealScheduler: true })
  })

  it('preemption tail: resolvable failures are dry-run (no victims here), unresolvable ones are not', () => {
    const r = simulate(SAMPLE_NODES, pod({ cpu: 3000 }))
    expect(r.message).toBe(
      '0/4 nodes are available: 2 Insufficient cpu, 2 node(s) had untolerated taint(s). no new claims to deallocate, preemption: 0/4 nodes are available: 2 No preemption victims found for incoming pod, 2 Preemption is not helpful for scheduling.',
    )
    // a request above allocatable can never fit, so it is unresolvable (as recorded on a real 4.21 cluster)
    expect(byName(simulate(SAMPLE_NODES, pod({ cpu: 7500 })), 'worker-a1').filters.find((f) => f.plugin === 'NodeResourcesFit')?.code).toBe('UnschedulableAndUnresolvable')
  })

  it('a toleration lets the pod onto the GPU node but does not attract it there', () => {
    const r = simulate(SAMPLE_NODES, pod({ tolerations: [{ key: 'gpu', operator: 'Equal', value: 'true', effect: 'NoSchedule' }] }))
    expect(byName(r, 'worker-c1').feasible).toBe(true)
    expect(r.winners).toEqual(['worker-c1']) // it wins because it is the emptiest node, not because of the toleration
    const exists = simulate(SAMPLE_NODES, pod({ tolerations: [{ operator: 'Exists' }] }))
    expect(exists.results.every((x) => x.feasible)).toBe(true)
  })

  it('topology spread DoNotSchedule is a filter, counted over nodes that match the pod node affinity', () => {
    const r = simulate(SAMPLE_NODES, pod({ spread: { topologyKey: 'zone', maxSkew: 1, when: 'DoNotSchedule' } }))
    expect(byName(r, 'worker-a1').filters.find((f) => f.plugin === 'PodTopologySpread')?.pass).toBe(false)
    expect(r.scorePlugins).not.toContain('PodTopologySpread')
    // only zone-a is eligible when the pod is pinned to worker-a1, so the global minimum is 1, not 0
    const pinned = simulate(SAMPLE_NODES, pod({ nodeSelector: { 'kubernetes.io/hostname': 'worker-a1' }, spread: { topologyKey: 'zone', maxSkew: 1, when: 'DoNotSchedule' } }))
    expect(pinned.winners).toEqual(['worker-a1'])
  })

  it('best-effort pods skip BalancedAllocation and are scored with non-zero default requests', () => {
    const r = simulate(SAMPLE_NODES, pod({ cpu: 0, mem: 0 }))
    expect(r.skipped.map((s) => s.plugin)).toContain('NodeResourcesBalancedAllocation')
    // a1: cpu (4000-3300)*100/4000 = 17, mem (16000-9200)*100/16000 = 42 → 29
    expect(byName(r, 'worker-a1').scores.NodeResourcesFit).toBe(29)
  })

  it('pod anti-affinity: required filters, preferred scores', () => {
    const req = simulate(SAMPLE_NODES, pod({ podAntiAffinity: 'required' }))
    expect(byName(req, 'worker-a1').filters.find((f) => f.plugin === 'InterPodAffinity')?.eventReasons).toEqual(["node(s) didn't match pod anti-affinity rules"])
    const pref = simulate(SAMPLE_NODES, pod({ podAntiAffinity: 'preferred' }))
    expect(byName(pref, 'worker-a1').scores.InterPodAffinity).toBe(0)
    expect(byName(pref, 'worker-b1').scores.InterPodAffinity).toBe(100)
  })

  it('a single feasible node is chosen without scoring, as schedulePod does', () => {
    // disktype=ssd: worker-a1 and worker-c1 carry it, but worker-c1 keeps its gpu taint, so only worker-a1 is left
    const r = simulate(SAMPLE_NODES, pod({ nodeSelector: { disktype: 'ssd' } }))
    expect(r.results.filter((x) => x.feasible).map((x) => x.node.name)).toEqual(['worker-a1'])
    expect(r.winners).toEqual(['worker-a1'])
    expect(r.scorePlugins).toEqual([])
    expect(byName(r, 'worker-a1').scores).toEqual({})
    expect(r.skipped).toEqual([{ plugin: 'all score plugins', why: expect.stringContaining('only one node passed the filters') }])
    // with two feasible nodes, scoring runs as usual
    expect(simulate(SAMPLE_NODES, pod()).scorePlugins.length).toBeGreaterThan(0)
  })

  it('PreferNoSchedule taints are scored in reverse, never filtered', () => {
    const nodes: SimNode[] = SAMPLE_NODES.map((n) => (n.name === 'worker-b1' ? { ...n, taints: [{ key: 'maintenance', value: 'soon', effect: 'PreferNoSchedule' }] } : n))
    const r = simulate(nodes, pod())
    expect(byName(r, 'worker-b1').feasible).toBe(true)
    expect(byName(r, 'worker-b1').scores.TaintToleration).toBe(0)
    expect(byName(r, 'worker-a1').scores.TaintToleration).toBe(100)
  })
})

// =====================================================================================================
describe('rolling update (Deployment controller)', () => {
  const cfg = (c: Partial<RolloutConfig> = {}): RolloutConfig => ({ replicas: 4, maxSurge: '25%', maxUnavailable: '25%', readySeconds: 10, progressDeadlineSeconds: 600, strategy: 'RollingUpdate', ...c })
  const roll = (c: Partial<RolloutConfig>, image = ROLLOUT_GOOD_IMAGE, good = true) => runRollout(startRollout(initialRollout(cfg(c)), image, good))

  it('rounds maxSurge up and maxUnavailable down: 1 replica with 25%/25% → surge 1, unavailable 0', () => {
    expect(resolveFenceposts('25%', '25%', 1)).toEqual({ surge: 1, unavailable: 0, bumped: false })
    expect(resolveFenceposts('25%', '25%', 10)).toEqual({ surge: 3, unavailable: 2, bumped: false })
  })

  it('bumps maxUnavailable to 1 when both resolve to 0 through rounding', () => {
    expect(resolveFenceposts(0, '25%', 3)).toEqual({ surge: 0, unavailable: 1, bumped: true })
    expect(maxUnavailableFor(0, '25%', 3)).toBe(1)
    expect(maxUnavailableFor('25%', '100%', 0)).toBe(0)
  })

  it('rejects maxSurge=0 with maxUnavailable=0 (as int or %) and maxUnavailable > 100%', () => {
    expect(validateRollingUpdate(0, 0)).toEqual(['spec.strategy.rollingUpdate.maxUnavailable: Invalid value: 0: may not be 0 when `maxSurge` is 0'])
    expect(validateRollingUpdate('0%', 0)).toHaveLength(1)
    expect(validateRollingUpdate('0%', '0%')).toHaveLength(1)
    expect(validateRollingUpdate(1, 0)).toEqual([])
    expect(validateRollingUpdate(0, '120%')[0]).toMatch(/must not be greater than 100%/)
    expect(validateRollingUpdate(-1, 1)[0]).toMatch(/greater than or equal to 0/)
    // an invalid Deployment never starts a rollout
    const s = runRollout(startRollout(initialRollout(cfg({ maxSurge: 0, maxUnavailable: 0 })), ROLLOUT_GOOD_IMAGE, true))
    expect(rolloutCounts(s).updated).toBe(0)
  })

  it('NewRSNewReplicas never exceeds replicas + maxSurge', () => {
    expect(newRSNewReplicas(4, 1, 4, 0)).toBe(1)
    expect(newRSNewReplicas(4, 1, 5, 1)).toBe(1)
    expect(newRSNewReplicas(4, 4, 4, 0)).toBe(4)
  })

  it('cleans up unhealthy old pods before counting availability', () => {
    const p = planOldScaleDown(4, 1, { replicas: 0, available: 0 }, [{ replicas: 2, available: 0 }, { replicas: 4, available: 4 }])
    expect(p.cleaned).toBe(2)
    expect(p.next).toEqual([0, 3])
  })

  it('1 replica, 25%/25%: surges to 2 pods and never drops below 1 available', () => {
    const s = roll({ replicas: 1 })
    expect(s.complete).toBe(true)
    expect(s.maxPodsSeen).toBe(2)
    expect(s.minAvailableSeen).toBe(1)
    expect(rolloutStatusText(s)).toEqual({ text: 'deployment "web" successfully rolled out', exitCode: 0 })
  })

  it('maxUnavailable 0 keeps full availability; the surge bounds the total', () => {
    const s = roll({ replicas: 4, maxSurge: 1, maxUnavailable: 0 })
    expect(s.complete).toBe(true)
    expect(s.minAvailableSeen).toBe(4)
    expect(s.maxPodsSeen).toBe(5)
  })

  it('bad image with 4 replicas, 25%/25%: stops at 3 available, then ProgressDeadlineExceeded, then rollback recovers', () => {
    const stuck = roll({}, ROLLOUT_BAD_IMAGE, false)
    const c = rolloutCounts(stuck)
    expect(c.available).toBe(3)
    expect(c.updated).toBe(2)
    expect(c.updatedAvailable).toBe(0)
    expect(stuck.minAvailableSeen).toBe(3)
    expect(stuck.progressing.reason).toBe('ProgressDeadlineExceeded')
    expect(stuck.t).toBe(600)
    expect(rolloutStatusText(stuck)).toEqual({ text: 'error: deployment "web" exceeded its progress deadline', exitCode: 1 })
    const back = runRollout(rollbackRollout(stuck))
    expect(back.complete).toBe(true)
    expect(back.revision).toBe(3)
    const nc = rolloutCounts(back)
    expect(nc.newRS?.image).toBe('quay.io/acme/web:1.0')
    expect(nc.newRS?.revision).toBe(3)
    expect(nc.available).toBe(4)
    expect(nc.oldPods).toBe(0)
  })

  it('rolling forward from a stuck rollout cleans up the broken pods first', () => {
    const stuck = roll({}, ROLLOUT_BAD_IMAGE, false)
    const fixed = runRollout(startRollout(stuck, ROLLOUT_GOOD_IMAGE, true))
    const c = rolloutCounts(fixed)
    expect(fixed.complete).toBe(true)
    expect(c.newRS?.image).toBe(ROLLOUT_GOOD_IMAGE)
    expect(c.available).toBe(4)
    expect(fixed.minAvailableSeen).toBeGreaterThanOrEqual(3)
    expect(fixed.rss.find((r) => r.image === ROLLOUT_BAD_IMAGE)?.replicas).toBe(0)
  })

  it('the controller does not roll back by itself and never scales below minAvailable', () => {
    let s: RolloutState = startRollout(initialRollout(cfg({ replicas: 10 })), ROLLOUT_BAD_IMAGE, false)
    for (let i = 0; i < 50; i++) {
      const r = rolloutStep(s)
      if (!r.moved) break
      s = r.state
      expect(rolloutCounts(s).available).toBeGreaterThanOrEqual(8)
    }
    expect(s.image).toBe(ROLLOUT_BAD_IMAGE)
  })

  it('Recreate takes availability to zero before the new pods start', () => {
    const s = roll({ strategy: 'Recreate' })
    expect(s.complete).toBe(true)
    expect(s.minAvailableSeen).toBe(0)
    expect(s.maxPodsSeen).toBe(4)
  })
})

// =====================================================================================================
describe('reconciliation: Deployment → ReplicaSet → Pods', () => {
  it('a deleted pod is replaced by the ReplicaSet controller alone', () => {
    const s0 = initialReconcile()
    const s = rcRunToSteady(rcDeletePodAction(s0, s0.pods[0].name))
    expect(rcSummary(s).running).toBe(3)
    expect(s.pods.some((p) => p.name === s0.pods[0].name)).toBe(false)
    expect(s.log.filter((l) => l.who === 'deployment').every((l) => l.act.length === 0)).toBe(true)
    expect(s.markers).toContain('rs:replace-pod')
  })

  it('editing the ReplicaSet directly is reverted by its owner, the Deployment', () => {
    const s0 = initialReconcile()
    const s = rcRunToSteady(rcEditRS(s0, s0.rss[0].name, 5))
    expect(s.rss[0].replicas).toBe(3)
    expect(rcSummary(s).running).toBe(3)
    expect(s.markers).toContain('deploy:revert-rs')
  })

  it('scaling the Deployment flows down through the ReplicaSet', () => {
    const s = rcRunToSteady(rcScaleDeployment(initialReconcile(), 5))
    expect(s.rss[0].replicas).toBe(5)
    expect(rcSummary(s).running).toBe(5)
  })

  it('a template change creates a new ReplicaSet and rolls within maxSurge/maxUnavailable', () => {
    let s = rcSetImage(initialReconcile(), 'quay.io/acme/web:1.1')
    let maxPods = 0
    let minReady = 3
    for (let i = 0; i < 300 && s.queue.length; i++) {
      s = rcStep(s)
      const live = s.pods.filter((p) => !p.terminating)
      maxPods = Math.max(maxPods, live.length)
      minReady = Math.min(minReady, live.filter((p) => p.phase === 'Running').length)
    }
    const sum = rcSummary(s)
    expect(sum.steady).toBe(true)
    expect(s.pods.every((p) => p.hash === sum.newHash)).toBe(true)
    expect(s.rss.find((r) => r.hash !== sum.newHash)?.replicas).toBe(0)
    expect(maxPods).toBeLessThanOrEqual(4) // 3 + ceil(25% of 3)
    expect(minReady).toBeGreaterThanOrEqual(3) // maxUnavailable floor(25% of 3) = 0
  })

  it('relabelling a pod orphans it: it keeps running and is replaced', () => {
    const s0 = initialReconcile()
    const s = rcRunToSteady(rcRelabelPod(s0, s0.pods[1].name))
    const sum = rcSummary(s)
    expect(sum.orphans.map((p) => p.name)).toEqual([s0.pods[1].name])
    expect(sum.orphans[0].phase).toBe('Running')
    expect(sum.owned).toBe(3)
  })

  it('deleting the ReplicaSet: the garbage collector removes its pods and the Deployment recreates it', () => {
    const s0 = initialReconcile()
    const s = rcRunToSteady(rcDeleteRS(s0, s0.rss[0].name))
    expect(s.rss).toHaveLength(1)
    expect(s.rss[0].name).toBe(s0.rss[0].name) // same template → same pod-template-hash → same name
    expect(s.rss[0].uid).not.toBe(s0.rss[0].uid)
    expect(rcSummary(s).running).toBe(3)
    expect(s.pods.some((p) => s0.pods.some((o) => o.name === p.name))).toBe(false)
  })

  it('work queue keys are de-duplicated and the hash is stable', () => {
    const s0 = initialReconcile()
    const s = rcEditRS(rcScaleDeployment(s0, 4), s0.rss[0].name, 6)
    expect(s.queue.filter((w) => w.ctrl === 'deployment')).toHaveLength(1)
    expect(templateHash('web|x')).toBe(templateHash('web|x'))
    expect(templateHash('web|x')).toMatch(/^[bcdfghjklmnpqrstvwxz2456789]+$/)
  })
})

// =====================================================================================================
describe('probes and restarts (kubelet)', () => {
  const app = (a: Partial<AppScript> = {}): AppScript => ({ startSeconds: 5, exitAfterSeconds: null, hangAfterSeconds: null, dependencyDown: null, livenessChecksDependency: false, healthLatencySeconds: 0, ...a })
  const conf = (c: Partial<ProbeConfig> = {}): ProbeConfig => ({ startup: { ...DEFAULT_PROBE }, readiness: { ...DEFAULT_PROBE }, liveness: { ...DEFAULT_PROBE }, app: app(), horizon: 300, ...c })

  it('readiness failures remove the pod from endpoints but never restart it', () => {
    const tl = simulateProbes(conf({ readiness: { ...DEFAULT_PROBE, enabled: true }, app: app({ dependencyDown: { from: 60, to: 120 } }) }))
    expect(tl.restarts).toBe(0)
    // probes every 10s: Ready at 10 (first probe at 0 is refused), failures at 60, 70, 80 → NotReady at 80, back at 120
    expect(tl.ready).toEqual([
      { from: 10, to: 80 },
      { from: 120, to: 300 },
    ])
  })

  it('the snapshot shows the cause and effect of a readiness failure: NotReady, no traffic, no restart, then recovery', () => {
    const c = conf({ readiness: { ...DEFAULT_PROBE, enabled: true }, liveness: { ...DEFAULT_PROBE, enabled: true, initialDelaySeconds: 10 }, app: app({ dependencyDown: { from: 60, to: 120 } }), horizon: 180 })
    const tl = simulateProbes(c)
    const before = probeSnapshot(tl, c, 50)
    expect(before).toMatchObject({ database: 'up', ready: true, traffic: 'serving', container: { state: 'running', run: 0 } })
    const first = probeSnapshot(tl, c, 65) // one failed /ready: still Ready
    expect(first.probes.find((p) => p.kind === 'readiness')).toMatchObject({ fails: 1, threshold: 3, cause: 'database down' })
    expect(first.ready).toBe(true)
    const out = probeSnapshot(tl, c, 85) // three in a row: NotReady
    expect(out).toMatchObject({ database: 'down', ready: false, traffic: 'blocked', container: { state: 'running', run: 0 } })
    expect(out.probes.find((p) => p.kind === 'liveness')).toMatchObject({ fails: 0 }) // /healthz does not check the database
    expect(out.story).toMatch(/NotReady.*no traffic.*never restarts/)
    expect(tl.restarts).toBe(0)
    const back = probeSnapshot(tl, c, 125)
    expect(back).toMatchObject({ database: 'up', ready: true, traffic: 'serving' })
    expect(back.story).toMatch(/passes again.*database is back.*traffic/)
  })

  it('the snapshot shows a liveness check on the database killing and restarting the container', () => {
    const c = conf({ readiness: { ...DEFAULT_PROBE, enabled: true }, liveness: { ...DEFAULT_PROBE, enabled: true, initialDelaySeconds: 10 }, app: app({ dependencyDown: { from: 60, to: 120 }, livenessChecksDependency: true }), horizon: 180 })
    const tl = simulateProbes(c)
    expect(tl.restarts).toBeGreaterThan(0)
    const kill = tl.runs[0].end as number
    expect(tl.runs[0].endReason).toBe('liveness')
    expect(kill).toBeGreaterThanOrEqual(80)
    expect(kill).toBeLessThan(120)
    const failing = probeSnapshot(tl, c, kill - 5)
    expect(failing.probes.find((p) => p.kind === 'liveness')).toMatchObject({ cause: 'database down' })
    const restarted = probeSnapshot(tl, c, kill + 1)
    expect(restarted.container.run).toBe(1)
    expect(restarted.ready).toBe(false) // a new container starts NotReady
    expect(restarted.story).toMatch(/liveness probe.*killed and restarted/)
    expect(tl.events.filter((e) => e.reason === 'Started').map((e) => e.message)).toEqual(tl.runs.map(() => 'Started container app')) // the kubelet's own wording
  })

  it('a pod waiting in CrashLoopBackOff stays in the EndpointSlice as not ready, with no running container', () => {
    const c = conf({ readiness: { ...DEFAULT_PROBE, enabled: true }, app: app({ exitAfterSeconds: 3 }), horizon: 120 })
    const tl = simulateProbes(c)
    const w = tl.waits[0]
    const snap = probeSnapshot(tl, c, w.from + 1)
    expect(snap).toMatchObject({ ready: false, traffic: 'none', container: { state: 'backoff', run: null } })
    expect(probeStatusAt(tl, w.from + 1)).toMatchObject({ status: 'CrashLoopBackOff', ready: false, inEndpoints: 'not ready' })
  })

  it('liveness kills after failureThreshold consecutive failures, period apart', () => {
    const tl = simulateProbes(conf({ liveness: { ...DEFAULT_PROBE, enabled: true, initialDelaySeconds: 15, periodSeconds: 10, failureThreshold: 3 }, app: app({ hangAfterSeconds: 60 }), horizon: 120 }))
    // probes at 15, 25, ..., first failure at 65, kill at 65 + (3 − 1) × 10 = 85
    expect(tl.runs[0].end).toBe(85)
    expect(tl.runs[0].endReason).toBe('liveness')
    expect(tl.runs[1].start).toBe(86) // first restart is immediate
    expect(tl.restarts).toBe(1)
  })

  it('a slow starter without a startup probe is killed by liveness repeatedly, then backs off', () => {
    const tl = simulateProbes(conf({ liveness: { ...DEFAULT_PROBE, enabled: true }, app: app({ startSeconds: 90 }) }))
    // killed at uptime 20 (probes at 0, 10, 20 all refused), restarted at once; restarts are immediate while the
    // container ran longer than the current back-off, then the kubelet starts waiting (40s, 80s, 160s)
    expect(tl.runs.map((r) => [r.start, r.end])).toEqual([
      [0, 20],
      [21, 41],
      [42, 62],
      [63, 83],
      [84, 104],
      [144, 164],
      [244, 264],
    ])
    expect(tl.waits.map((w) => w.backoff)).toEqual([40, 80, 160])
    expect(tl.runs.every((r) => r.endReason === 'liveness')).toBe(true)
  })

  it('a startup probe protects the slow start; liveness takes over afterwards', () => {
    const tl = simulateProbes(
      conf({
        startup: { ...DEFAULT_PROBE, enabled: true, periodSeconds: 10, failureThreshold: 12 },
        liveness: { ...DEFAULT_PROBE, enabled: true },
        readiness: { ...DEFAULT_PROBE, enabled: true },
        app: app({ startSeconds: 90 }),
      }),
    )
    expect(tl.restarts).toBe(0)
    expect(tl.runs[0].startedAt).toBe(90)
    expect(tl.ready[0].from).toBe(90) // readiness starts counting once the startup probe succeeded
    expect(tl.marks.filter((m) => m.probe === 'liveness' && m.t < 90)).toEqual([])
  })

  it('CrashLoopBackOff: immediate first restart, then 10s, 20s, 40s… capped at 300s', () => {
    const tl = simulateProbes(conf({ app: app({ exitAfterSeconds: 2 }), horizon: 700 }))
    expect(tl.waits.map((w) => w.backoff)).toEqual([10, 20, 40, 80, 160, 300, 300])
    expect(tl.runs[1].start).toBe(3)
    expect(tl.maxBackoff).toBe(BACKOFF_MAX)
  })

  it('the back-off resets after 10 minutes of running', () => {
    const tl = simulateProbes(conf({ app: app({ exitAfterSeconds: 700 }), horizon: 1500 }))
    expect(tl.restarts).toBe(2)
    expect(tl.waits).toEqual([])
  })

  it('a probe that answers no faster than timeoutSeconds fails', () => {
    const tl = simulateProbes(conf({ readiness: { ...DEFAULT_PROBE, enabled: true, timeoutSeconds: 1 }, app: app({ healthLatencySeconds: 2 }), horizon: 60 }))
    expect(tl.ready).toEqual([])
    expect(tl.marks.every((m) => !m.ok)).toBe(true)
  })

  it('defaults zero fields like the API server and rejects negatives', () => {
    expect(validateProbes({ startup: DEFAULT_PROBE, readiness: { ...DEFAULT_PROBE, enabled: true, periodSeconds: 0, failureThreshold: 0 }, liveness: DEFAULT_PROBE })).toEqual([])
    expect(validateProbes({ startup: DEFAULT_PROBE, readiness: { ...DEFAULT_PROBE, enabled: true, timeoutSeconds: -1 }, liveness: DEFAULT_PROBE })).toEqual([
      'spec.containers[0].readinessProbe.timeoutSeconds: Invalid value: -1: must be greater than or equal to 0',
    ])
    const tl = simulateProbes(conf({ readiness: { ...DEFAULT_PROBE, enabled: true, periodSeconds: 0 }, horizon: 30 }))
    expect(tl.marks.filter((m) => m.probe === 'readiness').map((m) => m.t)).toEqual([0, 10, 20, 30])
  })

  it('validates successThreshold: liveness and startup must be 1', () => {
    expect(validateProbes({ startup: DEFAULT_PROBE, readiness: DEFAULT_PROBE, liveness: { ...DEFAULT_PROBE, enabled: true, successThreshold: 2 } })).toEqual([
      'spec.containers[0].livenessProbe.successThreshold: Invalid value: 2: must be 1',
    ])
    expect(validateProbes({ startup: DEFAULT_PROBE, readiness: { ...DEFAULT_PROBE, enabled: true, successThreshold: 2 }, liveness: DEFAULT_PROBE })).toEqual([])
  })
})

// =====================================================================================================
describe('request path: Route → Service → EndpointSlice → Pod', () => {
  const t = (c: Partial<TrafficConfig>): TrafficConfig => ({ ...DEFAULT_TRAFFIC, ...c })

  it('works end to end by default (Service port 80 → targetPort 8080)', () => {
    expect(sendRequest(DEFAULT_TRAFFIC, 'router')).toMatchObject({ ok: true, httpStatus: 200 })
    expect(sendRequest(DEFAULT_TRAFFIC, 'client')).toMatchObject({ ok: true, exitCode: 0 })
  })

  it('selector mismatch → empty EndpointSlice → router 503, client connection refused', () => {
    const c = t({ selectorApp: 'payments-web' })
    expect(endpointSlice(c).endpoints).toEqual([])
    expect(sendRequest(c, 'router')).toMatchObject({ httpStatus: 503, failedAt: 'endpoints', exitCode: 0 })
    expect(sendRequest(c, 'client')).toMatchObject({ exitCode: 7 })
  })

  it('wrong targetPort → connection refused at the pod (exit 7), router 503', () => {
    const c = t({ targetPort: '80' })
    const r = sendRequest(c, 'client')
    expect(r).toMatchObject({ exitCode: 7, failedAt: 'pod' })
    expect(r.output).toContain('curl: (7) Failed to connect to web port 80: Connection refused')
    expect(sendRequest(c, 'router')).toMatchObject({ httpStatus: 503, failedAt: 'pod' })
  })

  it('NetworkPolicy drop → timeout (exit 28); the router gets 503 after its connect timeout', () => {
    const c = t({ policy: 'deny-all' })
    expect(sendRequest(c, 'client')).toMatchObject({ exitCode: 28, failedAt: 'policy' })
    expect(sendRequest(c, 'router')).toMatchObject({ httpStatus: 503, failedAt: 'policy' })
    const routerOnly = t({ policy: 'allow-from-router' })
    expect(sendRequest(routerOnly, 'router').httpStatus).toBe(200)
    expect(sendRequest(routerOnly, 'client').exitCode).toBe(28)
  })

  it('DNS failure → curl exit 6', () => {
    expect(sendRequest(t({ clientHost: 'payments-web' }), 'client')).toMatchObject({ exitCode: 6, failedAt: 'dns' })
    expect(sendRequest(t({ clientHost: 'web.shop.svc.cluster.local' }), 'client').exitCode).toBe(0)
    expect(sendRequest(t({ requestHost: 'web.example.org' }), 'router')).toMatchObject({ exitCode: 6, failedAt: 'dns' })
  })

  it('unknown host under the apps domain → router 503 from its default backend', () => {
    expect(sendRequest(t({ requestHost: `shop.${'apps-crc.testing'}` }), 'router')).toMatchObject({ httpStatus: 503, failedAt: 'route' })
  })

  it('Route targetPort is matched against the endpoint port name or number, not the Service port', () => {
    expect(sendRequest(t({ routeTargetPort: '8080' }), 'router').httpStatus).toBe(200)
    expect(sendRequest(t({ routeTargetPort: '' }), 'router').httpStatus).toBe(200)
    expect(sendRequest(t({ routeTargetPort: '80' }), 'router')).toMatchObject({ httpStatus: 503, failedAt: 'endpoints' })
  })

  it('named targetPort resolves through the declared container port', () => {
    expect(sendRequest(t({ targetPort: 'http' }), 'client').exitCode).toBe(0)
    expect(sendRequest(t({ targetPort: 'http', containerPort: 8081 }), 'client').exitCode).toBe(7)
    expect(sendRequest(t({ targetPort: 'web' }), 'router')).toMatchObject({ httpStatus: 503, failedAt: 'endpoints' })
  })

  it('NotReady pods stay in the slice but receive no traffic', () => {
    const c = t({ pods: DEFAULT_TRAFFIC.pods.map((p) => ({ ...p, ready: false })) })
    expect(endpointSlice(c).endpoints.map((e) => e.ready)).toEqual([false, false])
    expect(sendRequest(c, 'router').httpStatus).toBe(503)
    expect(sendRequest(c, 'client').exitCode).toBe(7)
  })

  it('one broken endpoint: the router redispatches, client requests alternate', () => {
    const c = t({ pods: [DEFAULT_TRAFFIC.pods[0], { ...DEFAULT_TRAFFIC.pods[1], listenPort: 9090 }] })
    const r = sendRequest(c, 'router')
    expect(r.httpStatus).toBe(200)
    expect(r.hops.find((h) => h.id === 'pod')?.status).toBe('warn')
    expect([0, 1].map((n) => sendRequest(c, 'client', n).exitCode)).toEqual([0, 7])
  })

  it('a client port the Service does not expose times out', () => {
    expect(sendRequest(t({ clientPort: 8080 }), 'client')).toMatchObject({ exitCode: 28, failedAt: 'service' })
  })
})

// =====================================================================================================
describe('RBAC', () => {
  const id = (k: string) => RBAC_IDENTITIES.find((i) => i.id === k)!
  const res = (r: string) => RBAC_RESOURCES.find((x) => x.resource === r)!
  const ask = (who: string, verb: string, r: string, ns: string | null, bindings: Binding[] = RBAC_BINDINGS, name?: string) => canI({ identity: id(who), verb, resource: res(r), namespace: ns, name }, bindings)

  it('ServiceAccounts carry virtual groups', () => {
    expect(userInfo(id('sa-ci'))).toEqual({ username: 'system:serviceaccount:team-a:ci', groups: ['system:serviceaccounts', 'system:serviceaccounts:team-a', 'system:authenticated'] })
    expect(userInfo(id('alice')).groups).toContain('system:authenticated')
  })

  it('permissions are a union: every granting path is listed, removing one is not enough', () => {
    const r = ask('sa-ci', 'list', 'pods', 'team-a')
    expect(r.allowed).toBe(true)
    expect(r.paths.map((p) => p.binding.name).sort()).toEqual(['ci-pod-reader', 'view-team-a-sas'])
    const without = RBAC_BINDINGS.map((b) => (b.name === 'ci-pod-reader' ? { ...b, enabled: false } : b))
    expect(ask('sa-ci', 'list', 'pods', 'team-a', without).allowed).toBe(true)
    const neither = without.map((b) => (b.name === 'view-team-a-sas' ? { ...b, enabled: false } : b))
    expect(ask('sa-ci', 'list', 'pods', 'team-a', neither).allowed).toBe(false)
  })

  it('there are no deny rules: adding bindings never removes access', () => {
    const all = RBAC_BINDINGS.map((b) => ({ ...b, enabled: true }))
    for (const who of RBAC_IDENTITIES)
      for (const r of RBAC_RESOURCES)
        for (const ns of ['team-a', 'team-b', null])
          for (const verb of ['get', 'list', 'delete', 'create'])
            if (canI({ identity: who, verb, resource: r, namespace: ns }, RBAC_BINDINGS).allowed) expect(canI({ identity: who, verb, resource: r, namespace: ns }, all).allowed).toBe(true)
  })

  it('a RoleBinding to a ClusterRole only grants in the RoleBinding namespace', () => {
    expect(ask('alice', 'delete', 'pods', 'team-a').allowed).toBe(true)
    const r = ask('alice', 'delete', 'pods', 'team-b')
    expect(r.allowed).toBe(false)
    expect(r.nearMisses.find((m) => m.binding.name === 'admin')?.why).toMatch(/only in namespace team-a/)
    expect(ask('alice', 'list', 'pods', null).allowed).toBe(false) // -A needs a ClusterRoleBinding
  })

  it('a RoleBinding cannot grant cluster-scoped resources; a ClusterRoleBinding can', () => {
    const rb: Binding = { kind: 'RoleBinding', name: 'nodes', namespace: 'team-a', roleRef: { kind: 'ClusterRole', name: 'node-reader' }, subjects: [{ kind: 'User', name: 'bob' }], enabled: true }
    expect(ask('bob', 'list', 'nodes', null, [rb]).allowed).toBe(false)
    expect(ask('bob', 'list', 'nodes', null, [{ ...rb, kind: 'ClusterRoleBinding', namespace: undefined }]).allowed).toBe(true)
  })

  it('a RoleBinding cannot reference a Role from another namespace', () => {
    const rb: Binding = { kind: 'RoleBinding', name: 'x', namespace: 'team-b', roleRef: { kind: 'Role', name: 'pod-reader' }, subjects: [{ kind: 'User', name: 'bob' }], enabled: true }
    const r = ask('bob', 'get', 'pods', 'team-b', [rb])
    expect(r.allowed).toBe(false)
    expect(r.nearMisses[0].why).toMatch(/not found in namespace team-b/)
  })

  it('virtual group system:serviceaccounts:<ns> grants every ServiceAccount of a namespace', () => {
    expect(ask('sa-b-default', 'get', 'imagestreams/layers', 'team-a').allowed).toBe(false)
    const rb: Binding = { kind: 'RoleBinding', name: 'pull-from-b', namespace: 'team-a', roleRef: { kind: 'ClusterRole', name: 'system:image-puller' }, subjects: [{ kind: 'Group', name: 'system:serviceaccounts:team-b' }], enabled: true }
    expect(ask('sa-b-default', 'get', 'imagestreams/layers', 'team-a', [...RBAC_BINDINGS, rb]).allowed).toBe(true)
  })

  it('rule matching: subresources, wildcards and resourceNames', () => {
    expect(ruleAllows({ apiGroups: [''], resources: ['pods'], verbs: ['get'] }, 'get', '', 'pods/log')).toBe(false)
    expect(ruleAllows({ apiGroups: [''], resources: ['*/log'], verbs: ['get'] }, 'get', '', 'pods/log')).toBe(true)
    expect(ruleAllows({ apiGroups: ['*'], resources: ['*'], verbs: ['*'] }, 'delete', 'apps', 'deployments')).toBe(true)
    expect(ask('bob', 'get', 'configmaps', 'team-b', [{ kind: 'RoleBinding', name: 'c', namespace: 'team-b', roleRef: { kind: 'Role', name: 'config-editor' }, subjects: [{ kind: 'User', name: 'bob' }], enabled: true }], 'app-settings').allowed).toBe(true)
    expect(ask('bob', 'list', 'configmaps', 'team-b', [{ kind: 'RoleBinding', name: 'c', namespace: 'team-b', roleRef: { kind: 'Role', name: 'config-editor' }, subjects: [{ kind: 'User', name: 'bob' }], enabled: true }]).allowed).toBe(false)
    expect(RBAC_ROLES.find((r) => r.name === 'view')?.rules.some((r) => r.resources.includes('secrets'))).toBe(false)
  })

  it('a ClusterRoleBinding can reference only a ClusterRole: the API server refuses a Role, so it never grants', () => {
    const crb: Binding = { kind: 'ClusterRoleBinding', name: 'pod-reader-alice', roleRef: { kind: 'Role', name: 'pod-reader' }, subjects: [{ kind: 'User', name: 'alice' }], enabled: true }
    expect(validateBinding(crb)).toBe('The ClusterRoleBinding "pod-reader-alice" is invalid: roleRef.kind: Unsupported value: "Role": supported values: "ClusterRole"')
    expect(validateBinding({ ...crb, roleRef: { kind: 'ClusterRole', name: 'view' } })).toBeNull()
    expect(validateBinding({ ...crb, kind: 'RoleBinding' })).toBeNull() // a RoleBinding may reference a Role
    const r = ask('alice', 'list', 'pods', 'team-a', [crb])
    expect(r.allowed).toBe(false)
    expect(r.nearMisses).toEqual([]) // it does not exist, so it is not even a near miss
  })

  it('OpenShift: view pulls a project\'s images, edit and admin also push; matching the image-puller lessons', () => {
    expect(ask('alice', 'get', 'imagestreams/layers', 'team-a').paths.map((p) => p.role.name)).toEqual(['admin']) // her own project
    expect(ask('alice', 'update', 'imagestreams/layers', 'team-a').allowed).toBe(true)
    expect(ask('alice', 'get', 'imagestreams/layers', 'team-b').paths.map((p) => p.role.name)).toEqual(['view']) // developers: view in team-b
    expect(ask('alice', 'update', 'imagestreams/layers', 'team-b').allowed).toBe(false)
    expect(ask('sa-deployer', 'update', 'imagestreams/layers', 'team-b').paths.map((p) => p.role.name)).toEqual(['edit'])
    expect(ask('sa-deployer', 'get', 'pods/exec', 'team-b').allowed).toBe(true)
  })

  it('a group grant reaches every ServiceAccount of the namespace; naming one account leaves the others out', () => {
    const group: Binding = { kind: 'RoleBinding', name: 'pull', namespace: 'team-a', roleRef: { kind: 'ClusterRole', name: 'system:image-puller' }, subjects: [{ kind: 'Group', name: 'system:serviceaccounts:team-b' }], enabled: true }
    const one: Binding = { ...group, subjects: [{ kind: 'ServiceAccount', name: 'default', namespace: 'team-b' }] }
    for (const who of ['sa-b-default', 'sa-b-builder']) expect(ask(who, 'get', 'imagestreams/layers', 'team-a', [group]).allowed).toBe(true)
    expect(ask('sa-b-default', 'get', 'imagestreams/layers', 'team-a', [one]).allowed).toBe(true)
    expect(ask('sa-b-builder', 'get', 'imagestreams/layers', 'team-a', [one]).allowed).toBe(false)
  })

  it('OpenShift: OAuth users may create projects, ServiceAccounts may not', () => {
    expect(ask('alice', 'create', 'projectrequests', null).allowed).toBe(true)
    expect(ask('sa-ci', 'create', 'projectrequests', null).allowed).toBe(false)
  })

  it('prints the equivalent oc auth can-i command', () => {
    expect(ask('sa-ci', 'get', 'pods/log', 'team-a').command).toBe('oc auth can-i get pods --subresource=log -n team-a --as=system:serviceaccount:team-a:ci')
  })
})

describe('SCC admission (simplified)', () => {
  const pod = (p: Partial<PodSecuritySpec> = {}): PodSecuritySpec => ({ runAsUser: null, privileged: false, addCapability: '', hostNetwork: false, hostPath: false, hostUsersFalse: false, imageUser: 'root', ...p })

  it('restricted-v2 assigns a UID from the namespace range when none is set', () => {
    const r = admitPod(pod(), [])
    expect(r.admitted).toBe('restricted-v2')
    expect(r.effectiveUid).toMatch(/^1000660000/)
  })

  it('runAsUser 0 is rejected without anyuid, with the real message shape', () => {
    const r = admitPod(pod({ runAsUser: 0 }), [])
    expect(r.admitted).toBeNull()
    expect(r.message).toContain('unable to validate against any security context constraint')
    expect(r.message).toContain('provider "anyuid": Forbidden: not usable by user or serviceaccount')
    expect(r.message).toContain('provider restricted-v2: .containers[0].runAsUser: Invalid value: 0: must be in the ranges: [1000660000, 1000669999]')
  })

  it('anyuid wins first because of its priority, even for pods that did not ask for root', () => {
    expect(admitPod(pod({ runAsUser: 0 }), ['anyuid']).admitted).toBe('anyuid')
    const r = admitPod(pod(), ['anyuid'])
    expect(r.admitted).toBe('anyuid')
    expect(r.effectiveUid).toMatch(/^0/)
  })

  it('pod-level errors come first; volume errors carry no provider prefix', () => {
    const r = admitPod(pod({ hostNetwork: true, hostPath: true }), [])
    expect(r.admitted).toBeNull()
    expect(r.message).toContain('provider restricted-v2: .spec.securityContext.hostNetwork: Invalid value: true: Host network is not allowed to be used, spec.volumes[0]: Invalid value: "hostPath": hostPath volumes are not allowed to be used')
    expect(r.message).toContain('provider restricted-v2: .containers[0].hostNetwork: Invalid value: true')
  })

  it('capabilities and host access need the matching SCC', () => {
    expect(admitPod(pod({ addCapability: 'NET_BIND_SERVICE' }), []).admitted).toBe('restricted-v2')
    expect(admitPod(pod({ addCapability: 'NET_ADMIN' }), ['anyuid']).admitted).toBeNull()
    expect(admitPod(pod({ addCapability: 'NET_ADMIN' }), ['privileged']).admitted).toBe('privileged')
    expect(admitPod(pod({ hostNetwork: true }), ['hostnetwork-v2']).admitted).toBe('hostnetwork-v2')
  })

  it('nonroot-v2 admits a non-root UID outside the range; MustRunAsNonRoot fails at runtime for a root image', () => {
    expect(admitPod(pod({ runAsUser: 1001 }), ['nonroot-v2']).admitted).toBe('nonroot-v2')
    expect(admitPod(pod({ runAsUser: 1001, hostUsersFalse: true }), []).admitted).toBe('restricted-v3')
  })
})

// =====================================================================================================
describe('storage: PVC, PV, StorageClass', () => {
  const st = (bindingMode: 'Immediate' | 'WaitForFirstConsumer', reclaimPolicy: 'Delete' | 'Retain', patch: Partial<StorageState> = {}): StorageState => ({ ...initialStorage({ bindingMode, reclaimPolicy }), ...patch })

  it('WaitForFirstConsumer: Pending until a pod is scheduled, then provisioned in that node zone', () => {
    const a = stCreatePVC(st('WaitForFirstConsumer', 'Delete'))
    expect(a.pvc?.phase).toBe('Pending')
    expect(a.pvs).toEqual([])
    const b = stCreatePod(a)
    expect(b.pvc?.phase).toBe('Bound')
    expect(b.pvs[0].zone).toBe('zone-a')
    expect(b.pods[0].phase).toBe('Running')
  })

  it('Immediate: bound at once, possibly in the wrong zone for the pod', () => {
    const a = stCreatePVC(st('Immediate', 'Delete'))
    expect(a.pvc?.phase).toBe('Bound')
    expect(a.pvs[0].zone).toBe('zone-b')
    const b = stCreatePod(a)
    expect(b.pods[0].phase).toBe('Pending')
    expect(b.log.some((l) => l.text.includes("2 node(s) didn't match PersistentVolume's node affinity, 2 node(s) didn't match Pod's node affinity/selector"))).toBe(true)
    const anyZone = stCreatePod(stCreatePVC(st('Immediate', 'Delete', { podZone: 'any' })))
    expect(anyZone.pods[0].node).toBe('worker-b1')
  })

  it('Delete: deleting the claim deletes the PV and the data', () => {
    let s = stCreatePod(stCreatePVC(st('WaitForFirstConsumer', 'Delete')))
    s = stDeletePVC(stDeletePod(s, 'app-1'))
    expect(s.pvc).toBeNull()
    expect(s.pvs).toEqual([])
    expect(s.backends[0]).toMatchObject({ deleted: true, files: [] })
  })

  it('Retain: the PV becomes Released, keeps the data, and is not reused by a new claim', () => {
    let s = stCreatePod(stCreatePVC(st('WaitForFirstConsumer', 'Retain')))
    const oldPv = s.pvs[0].name
    s = stDeletePVC(stDeletePod(s, 'app-1'))
    expect(s.pvs[0]).toMatchObject({ name: oldPv, phase: 'Released', claimName: 'data' })
    expect(s.backends[0].files).toEqual(['orders.db'])
    s = stCreatePod(stCreatePVC(s))
    expect(s.pvc?.volume).not.toBe(oldPv) // a fresh, empty volume
    expect(s.markers).not.toContain('data-recovered')
  })

  it('Retain + reserving the released PV brings the data back', () => {
    let s = stCreatePod(stCreatePVC(st('WaitForFirstConsumer', 'Retain')))
    const oldPv = s.pvs[0].name
    s = stReservePV(stDeletePVC(stDeletePod(s, 'app-1')), oldPv)
    expect(s.pvs[0].phase).toBe('Available')
    s = stCreatePVC(s)
    expect(s.pvc?.volume).toBe(oldPv) // a reserved PV binds even with WaitForFirstConsumer
    s = stCreatePod(s)
    expect(s.markers).toContain('data-recovered')
  })

  it('patching one PV to Retain protects its data even when the StorageClass says Delete', () => {
    let s = stCreatePod(stCreatePVC(st('WaitForFirstConsumer', 'Delete')))
    s = stPatchReclaim(s, s.pvs[0].name, 'Retain')
    s = stDeletePVC(stDeletePod(s, 'app-1'))
    expect(s.pvs[0].phase).toBe('Released')
    expect(s.backends[0].files).toEqual(['orders.db'])
    expect(s.sc.reclaimPolicy).toBe('Delete')
  })

  it('patching a Released PV to Delete makes the provisioner delete the volume and its data (as recorded in e.storage)', () => {
    let s = stCreatePod(stCreatePVC(st('WaitForFirstConsumer', 'Retain')))
    const pv = s.pvs[0].name
    s = stDeletePVC(stDeletePod(s, 'app-1'))
    expect(s.pvs[0]).toMatchObject({ name: pv, phase: 'Released' })
    s = stPatchReclaim(s, pv, 'Delete')
    expect(s.pvs).toEqual([])
    expect(s.backends[0]).toMatchObject({ deleted: true, files: [] })
    expect(s.log[s.log.length - 1].who).toBe('external-provisioner')
    expect(s.sc.reclaimPolicy).toBe('Retain') // only that one PV changed
    // a bound PV patched to Delete is not reclaimed until its claim goes
    let b = stCreatePod(stCreatePVC(st('WaitForFirstConsumer', 'Retain')))
    b = stPatchReclaim(b, b.pvs[0].name, 'Delete')
    expect(b.pvs[0]).toMatchObject({ phase: 'Bound', reclaim: 'Delete' })
    expect(b.backends[0].deleted).toBe(false)
  })

  it('deleting the PV object of a Delete volume deletes its backend once it is unbound (HonorPVReclaimPolicy)', () => {
    let s = stCreatePod(stCreatePVC(st('WaitForFirstConsumer', 'Delete')))
    s = stDeletePV(s, s.pvs[0].name)
    expect(s.pvs[0].terminating).toBe(true) // pv-protection while Bound
    s = stDeletePVC(stDeletePod(s, 'app-1'))
    expect(s.pvs).toEqual([])
    expect(s.backends[0].deleted).toBe(true)
    // a reserved (Available) PV switched to Delete, then deleted: the backend goes too
    let r = stCreatePod(stCreatePVC(st('WaitForFirstConsumer', 'Retain')))
    const name = r.pvs[0].name
    r = stReservePV(stDeletePVC(stDeletePod(r, 'app-1')), name)
    r = stDeletePV(stPatchReclaim(r, name, 'Delete'), name)
    expect(r.pvs).toEqual([])
    expect(r.backends[0].deleted).toBe(true)
    expect(r.markers).not.toContain('pv-object-deleted')
  })

  it('pvc-protection keeps an in-use claim Terminating until its pod is gone', () => {
    let s = stDeletePVC(stCreatePod(stCreatePVC(st('WaitForFirstConsumer', 'Delete'))))
    expect(s.pvc?.terminating).toBe(true)
    expect(s.pvs).toHaveLength(1)
    s = stDeletePod(s, 'app-1')
    expect(s.pvc).toBeNull()
  })

  it('pv-protection keeps a bound PV; deleting a Retain PV object leaves the volume behind', () => {
    let s = stCreatePod(stCreatePVC(st('WaitForFirstConsumer', 'Retain')))
    s = stDeletePV(s, s.pvs[0].name)
    expect(s.pvs[0].terminating).toBe(true)
    expect(s.pvc?.phase).toBe('Bound')
    s = stDeletePVC(stDeletePod(s, 'app-1'))
    expect(s.pvs).toEqual([])
    expect(s.backends[0]).toMatchObject({ deleted: false, files: ['orders.db'] })
  })

  it('access modes: RWO attaches to one node, RWOP to one pod, RWX is impossible on block storage', () => {
    const base = (mode: 'ReadWriteOnce' | 'ReadWriteOncePod' | 'ReadWriteMany', pod2Node: 'same' | 'other') => stCreatePod(stCreatePod(stCreatePVC({ ...st('WaitForFirstConsumer', 'Delete'), mode, pod2Node })))
    const other = base('ReadWriteOnce', 'other')
    expect(other.pods[1]).toMatchObject({ phase: 'ContainerCreating', reason: 'Multi-Attach error' })
    expect(base('ReadWriteOnce', 'same').pods[1].phase).toBe('Running')
    expect(base('ReadWriteOncePod', 'same').pods[1]).toMatchObject({ phase: 'Pending', node: null })
    const rwx = base('ReadWriteMany', 'other')
    expect(rwx.pvc?.phase).toBe('Pending')
    expect(rwx.log.some((l) => l.text.includes('ProvisioningFailed'))).toBe(true)
    // the second pod starts once the first one releases the RWO attachment
    expect(stDeletePod(other, 'app-1').pods[0]).toMatchObject({ name: 'app-2', phase: 'Running' })
  })
})

// =====================================================================================================
describe('GitOps drift', () => {
  const pol = (automated: boolean, selfHeal: boolean, prune: boolean) => initialDrift({ automated, selfHeal, prune })
  const REPLICAS = 'spec.replicas'

  it('automated sync without self-heal leaves a live change in place (OutOfSync)', () => {
    let s = liveSetField(pol(true, false, false), 'Deployment', 'web', REPLICAS, '5', 'oc scale deployment/web --replicas=5')
    expect(appSyncStatus(s)).toBe('OutOfSync')
    s = argoReconcile(s)
    expect(s.live.find((r) => r.name === 'web')?.fields[REPLICAS]).toBe('5')
    expect(s.log[s.log.length - 1].text).toMatch(/Skipping auto-sync: most recent sync already to/)
  })

  it('self-heal reverts the live change', () => {
    const s = argoReconcile(liveSetField(pol(true, true, false), 'Deployment', 'web', REPLICAS, '5', 'oc scale'))
    expect(s.live.find((r) => r.name === 'web')?.fields[REPLICAS]).toBe('3')
    expect(appSyncStatus(s)).toBe('Synced')
  })

  it('a new Git revision is synced automatically; without automation it waits', () => {
    const changed = gitSetField(pol(true, false, false), 'Deployment', 'web', REPLICAS, '4', 'scale to 4')
    expect(argoReconcile(changed).live.find((r) => r.name === 'web')?.fields[REPLICAS]).toBe('4')
    const manual = gitSetField(pol(false, false, false), 'Deployment', 'web', REPLICAS, '4', 'scale to 4')
    expect(argoReconcile(manual).live.find((r) => r.name === 'web')?.fields[REPLICAS]).toBe('3')
  })

  it('resources removed from Git are only deleted with prune', () => {
    const removed = gitRemove(pol(true, false, false), 'CronJob', 'report')
    const kept = argoReconcile(removed)
    expect(kept.live.some((r) => r.kind === 'CronJob')).toBe(true)
    expect(driftRows(kept).find((r) => r.kind === 'CronJob')).toMatchObject({ status: 'OutOfSync', requiresPruning: true })
    expect(appSyncStatus(kept)).toBe('OutOfSync')
    expect(kept.syncedSha).not.toBe(kept.gitSha) // a prune-only change is not auto-synced while auto-prune is off
    expect(kept.log[kept.log.length - 1].text).toMatch(/need to prune extra resources only but automated prune is disabled/)
    expect(argoReconcile(setDriftPolicy(kept, { automated: true, selfHeal: false, prune: true })).live.some((r) => r.kind === 'CronJob')).toBe(false)
    expect(argoManualSync(kept, true).live.some((r) => r.kind === 'CronJob')).toBe(false)
    expect(argoReconcile(gitRemove(pol(true, false, true), 'CronJob', 'report')).live.some((r) => r.kind === 'CronJob')).toBe(false)
  })

  it('health is separate from sync status: drift is OutOfSync and Healthy; a missing ConfigMap does not lower health', () => {
    const scaled = liveSetField(pol(true, false, false), 'Deployment', 'web', REPLICAS, '5', 'oc scale')
    expect([appSyncStatus(scaled), appHealth(scaled)]).toEqual(['OutOfSync', 'Healthy'])
    const deleted = liveDelete(pol(false, false, false), 'ConfigMap', 'web-config')
    expect(driftRows(deleted).find((r) => r.name === 'web-config')?.health).toBe('Missing')
    expect([appSyncStatus(deleted), appHealth(deleted)]).toEqual(['OutOfSync', 'Healthy'])
    const none = { ...deleted, live: [] }
    expect(appHealth(none)).toBe('Missing')
  })

  it('untracked objects are ignored by Argo CD and by oc diff', () => {
    const s = argoManualSync(liveCreateUntracked(pol(true, true, true)), true)
    expect(s.live.some((r) => r.name === 'scratch')).toBe(true)
    expect(driftRows(s).find((r) => r.name === 'scratch')?.status).toBe('Ignored')
    expect(appSyncStatus(s)).toBe('Synced')
    expect(ocDiff(s)).toEqual({ exitCode: 0, text: '' })
  })

  it('oc diff shows live → Git changes and exits 1; it does not report objects removed from Git', () => {
    const s = liveSetField(pol(false, false, false), 'Deployment', 'web', REPLICAS, '5', 'oc scale')
    const d = ocDiff(s)
    expect(d.exitCode).toBe(1)
    expect(d.text).toContain('-  replicas: 5\n+  replicas: 3')
    expect(ocDiff(gitRemove(pol(false, false, false), 'CronJob', 'report')).exitCode).toBe(0)
    const missing = ocDiff(liveDelete(pol(false, false, false), 'ConfigMap', 'web-config'))
    expect(missing.text).toContain('+  LOG_LEVEL: info')
  })
})
