// Pure, deterministic models behind the simulations. No React, no randomness, no clocks.
//
// Every model is a *teaching model*: it reproduces the documented behaviour (and, where noted, the upstream
// controller logic) of one mechanism, and says what it leaves out. Versions targeted: Kubernetes 1.34 /
// OpenShift 4.21, the versions the course's recordings come from.

export * as scheduler from '../lib/scheduler'

// =====================================================================================================
// Shared helpers
// =====================================================================================================

/** Alphabet Kubernetes uses for generated names and pod-template-hash (k8s.io/apimachinery/pkg/util/rand). */
const K8S_ALPHABET = 'bcdfghjklmnpqrstvwxz2456789'

/** Deterministic 5-character suffix, shaped like generateName suffixes ("web-6d4f8b7c9-x7k2p"). */
export function nameSuffix(n: number): string {
  let x = (Math.imul(n + 1, 2654435761) ^ 0x5bd1e995) >>> 0
  let s = ''
  for (let i = 0; i < 5; i++) {
    s += K8S_ALPHABET[x % K8S_ALPHABET.length]
    x = Math.floor(x / K8S_ALPHABET.length) ^ Math.imul(x, 31)
    x >>>= 0
  }
  return s
}

/** pod-template-hash: fnv32a of the template, then SafeEncodeString of its decimal form (as the Deployment controller does). */
export function templateHash(template: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < template.length; i++) {
    h ^= template.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return String(h)
    .split('')
    .map((c) => K8S_ALPHABET[c.charCodeAt(0) % K8S_ALPHABET.length])
    .join('')
}

// =====================================================================================================
// Rolling updates (Deployment controller)
// Docs: https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#rolling-update-deployment
//       https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#failed-deployment
//       https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#rolling-back-a-deployment
// Logic mirrors pkg/controller/deployment/rolling.go, recreate.go and util/deployment_util.go:
// NewRSNewReplicas, reconcileOldReplicaSets, cleanupUnhealthyReplicas, scaleDownOldReplicaSetsForRollingUpdate,
// ResolveFenceposts, MaxUnavailable and the ProgressDeadlineExceeded condition.
// Simplifications: a pod is Available as soon as it is Ready (minReadySeconds = 0); old pods are healthy;
// scaled-down pods disappear at once (graceful termination not modelled); one controller sync per step;
// the ReplicaSet controller creates and deletes pods instantly; no proportional scaling, pause or HPA. The real
// controller can create the new ReplicaSet and scale an old one down in the same sync; the model shows them as two
// steps (same outcome).
// =====================================================================================================

/** An int or a percentage string, as in IntOrString: 1, "1" or "25%". */
export type IntOrPercent = number | string

export function parseIntOrPercent(v: IntOrPercent): { kind: 'int' | 'percent'; value: number } | null {
  if (typeof v === 'number') return Number.isInteger(v) ? { kind: 'int', value: v } : null
  const s = v.trim()
  let m = /^(-?\d+)%$/.exec(s)
  if (m) return { kind: 'percent', value: Number(m[1]) }
  m = /^(-?\d+)$/.exec(s)
  if (m) return { kind: 'int', value: Number(m[1]) }
  return null
}

/** intstr.GetScaledValueFromIntOrPercent: percentages of `total`, rounded up (maxSurge) or down (maxUnavailable). */
export function scaledValue(v: IntOrPercent, total: number, roundUp: boolean): number {
  const p = parseIntOrPercent(v)
  if (!p) return 0
  if (p.kind === 'int') return p.value
  const raw = (p.value * total) / 100
  return roundUp ? Math.ceil(raw) : Math.floor(raw)
}

/**
 * ResolveFenceposts: absolute maxSurge (rounded up) and maxUnavailable (rounded down). If both resolve to 0
 * (possible through rounding, e.g. 1 replica with 0 / 25%), maxUnavailable becomes 1.
 */
export function resolveFenceposts(maxSurge: IntOrPercent, maxUnavailable: IntOrPercent, desired: number) {
  const surge = scaledValue(maxSurge, desired, true)
  let unavailable = scaledValue(maxUnavailable, desired, false)
  let bumped = false
  if (surge === 0 && unavailable === 0) {
    unavailable = 1
    bumped = true
  }
  return { surge, unavailable, bumped }
}

/** deploymentutil.MaxUnavailable: the resolved value, capped at the replica count (0 when replicas is 0). */
export function maxUnavailableFor(maxSurge: IntOrPercent, maxUnavailable: IntOrPercent, desired: number): number {
  if (desired === 0) return 0
  return Math.min(desired, resolveFenceposts(maxSurge, maxUnavailable, desired).unavailable)
}

/** ValidateRollingUpdateDeployment (pkg/apis/apps/validation), with the API server's wording. */
export function validateRollingUpdate(maxSurge: IntOrPercent, maxUnavailable: IntOrPercent): string[] {
  const errs: string[] = []
  const show = (v: IntOrPercent) => (typeof v === 'number' ? String(v) : `"${v}"`)
  const s = parseIntOrPercent(maxSurge)
  const u = parseIntOrPercent(maxUnavailable)
  if (!u) errs.push(`spec.strategy.rollingUpdate.maxUnavailable: Invalid value: ${show(maxUnavailable)}: a valid percent string must be a numeric string followed by an ending '%'`)
  if (!s) errs.push(`spec.strategy.rollingUpdate.maxSurge: Invalid value: ${show(maxSurge)}: a valid percent string must be a numeric string followed by an ending '%'`)
  if (u && u.value < 0) errs.push(`spec.strategy.rollingUpdate.maxUnavailable: Invalid value: ${show(maxUnavailable)}: must be greater than or equal to 0`)
  if (s && s.value < 0) errs.push(`spec.strategy.rollingUpdate.maxSurge: Invalid value: ${show(maxSurge)}: must be greater than or equal to 0`)
  if (u && s && u.value === 0 && s.value === 0) errs.push(`spec.strategy.rollingUpdate.maxUnavailable: Invalid value: ${show(maxUnavailable)}: may not be 0 when \`maxSurge\` is 0`)
  if (u && u.kind === 'percent' && u.value > 100) errs.push(`spec.strategy.rollingUpdate.maxUnavailable: Invalid value: ${show(maxUnavailable)}: must not be greater than 100%`)
  return errs
}

/** NewRSNewReplicas for RollingUpdate: scale the new ReplicaSet up as far as maxSurge allows. */
export function newRSNewReplicas(desired: number, surge: number, totalSpecReplicas: number, newRSReplicas: number): number {
  const maxTotal = desired + surge
  if (totalSpecReplicas >= maxTotal) return newRSReplicas
  const scaleUp = Math.min(maxTotal - totalSpecReplicas, desired - newRSReplicas)
  return newRSReplicas + Math.max(0, scaleUp)
}

export type RsCounts = { replicas: number; available: number }

/**
 * reconcileOldReplicaSets: how far old ReplicaSets (oldest first) may be scaled down this sync.
 * Returns the new spec.replicas of each old ReplicaSet and the arithmetic, for display.
 */
export function planOldScaleDown(desired: number, maxUnavailable: number, newRS: RsCounts, oldRSs: RsCounts[]) {
  const oldTotal = oldRSs.reduce((s, r) => s + r.replicas, 0)
  const next = oldRSs.map((r) => r.replicas)
  if (oldTotal === 0) return { next, cleaned: 0, scaled: 0, math: 'no old pods left', maxScaledDown: 0 }
  const allTotal = oldTotal + newRS.replicas
  const minAvailable = desired - maxUnavailable
  const newUnavailable = newRS.replicas - newRS.available
  const maxScaledDown = allTotal - minAvailable - newUnavailable
  let math = `maxScaledDown = all pods ${allTotal} − minAvailable ${minAvailable} − new unavailable ${newUnavailable} = ${maxScaledDown}`
  if (maxScaledDown <= 0) return { next, cleaned: 0, scaled: 0, math: math + ' → cannot scale down', maxScaledDown }
  // cleanupUnhealthyReplicas: remove old pods that are not available first; they do not reduce availability.
  let cleaned = 0
  oldRSs.forEach((r, i) => {
    if (cleaned >= maxScaledDown) return
    const unhealthy = next[i] - r.available
    if (unhealthy <= 0) return
    const c = Math.min(maxScaledDown - cleaned, unhealthy)
    next[i] -= c
    cleaned += c
  })
  // scaleDownOldReplicaSetsForRollingUpdate: keep at least minAvailable available pods.
  const available = newRS.available + oldRSs.reduce((s, r) => s + r.available, 0)
  let scaled = 0
  if (available > minAvailable) {
    const total = available - minAvailable
    oldRSs.forEach((_, i) => {
      if (scaled >= total || next[i] === 0) return
      const c = Math.min(next[i], total - scaled)
      next[i] -= c
      scaled += c
    })
    math += `; available ${available} − minAvailable ${minAvailable} = ${total} may go`
  } else math += `; available ${available} ≤ minAvailable ${minAvailable} → keep old pods`
  return { next, cleaned, scaled, math, maxScaledDown }
}

export type RolloutConfig = {
  replicas: number
  maxSurge: IntOrPercent
  maxUnavailable: IntOrPercent
  /** seconds from pod creation until Ready (image pull, start, readiness probe) */
  readySeconds: number
  progressDeadlineSeconds: number
  strategy: 'RollingUpdate' | 'Recreate'
}
export type RolloutPod = { name: string; createdAt: number; readyAt: number | null }
export type RolloutRS = { name: string; revision: number; image: string; good: boolean; replicas: number; pods: RolloutPod[]; created: number }
export type RolloutLog = { t: number; who: 'you' | 'deployment controller' | 'replicaset controller' | 'kubelet'; text: string; math?: string }
export type RolloutCondition = { status: 'True' | 'False'; reason: string; message: string }
export type RolloutState = {
  t: number
  cfg: RolloutConfig
  image: string
  imageGood: boolean
  revision: number
  rss: RolloutRS[]
  lastProgress: number
  progressing: RolloutCondition
  complete: boolean
  rolling: boolean
  log: RolloutLog[]
  seq: number
  /** lowest available count since the last rollout started */
  minAvailableSeen: number
  /** highest pod count since the last rollout started */
  maxPodsSeen: number
  markers: string[]
  /** why the controller is waiting, when it is */
  waiting: string
}

export const ROLLOUT_GOOD_IMAGE = 'quay.io/acme/web:2.0'
export const ROLLOUT_BAD_IMAGE = 'quay.io/acme/web:2.0-typo'
export const ROLLOUT_START_IMAGE = 'quay.io/acme/web:1.0'

const rsName = (image: string) => `web-${templateHash('web|' + image)}`

export function initialRollout(cfg: RolloutConfig): RolloutState {
  const name = rsName(ROLLOUT_START_IMAGE)
  const pods = Array.from({ length: cfg.replicas }, (_, i) => ({ name: `${name}-${nameSuffix(i)}`, createdAt: -600, readyAt: -590 }))
  return {
    t: 0,
    cfg,
    image: ROLLOUT_START_IMAGE,
    imageGood: true,
    revision: 1,
    rss: [{ name, revision: 1, image: ROLLOUT_START_IMAGE, good: true, replicas: cfg.replicas, pods, created: -600 }],
    lastProgress: 0,
    progressing: { status: 'True', reason: 'NewReplicaSetAvailable', message: `ReplicaSet "${name}" has successfully progressed.` },
    complete: true,
    rolling: false,
    log: [],
    seq: cfg.replicas,
    minAvailableSeen: cfg.replicas,
    maxPodsSeen: cfg.replicas,
    markers: [],
    waiting: '',
  }
}

const isAvail = (p: RolloutPod, t: number) => p.readyAt !== null && p.readyAt <= t
export const rsAvailable = (rs: RolloutRS, t: number) => rs.pods.filter((p) => isAvail(p, t)).length

export function rolloutCounts(s: RolloutState) {
  const newRS = s.rss.find((r) => r.image === s.image) || null
  const old = s.rss.filter((r) => r !== newRS)
  const total = s.rss.reduce((n, r) => n + r.pods.length, 0)
  const available = s.rss.reduce((n, r) => n + rsAvailable(r, s.t), 0)
  const updated = newRS ? newRS.pods.length : 0
  const updatedAvailable = newRS ? rsAvailable(newRS, s.t) : 0
  const oldPods = old.reduce((n, r) => n + r.pods.length, 0)
  const maxUnav = s.cfg.strategy === 'RollingUpdate' ? maxUnavailableFor(s.cfg.maxSurge, s.cfg.maxUnavailable, s.cfg.replicas) : s.cfg.replicas
  return { newRS, old, total, available, updated, updatedAvailable, oldPods, minAvailable: s.cfg.replicas - maxUnav, maxUnavailable: maxUnav }
}

/** `oc rollout status` text, as printed by kubectl's DeploymentStatusViewer. */
export function rolloutStatusText(s: RolloutState): { text: string; exitCode: number | null } {
  const c = rolloutCounts(s)
  if (s.progressing.reason === 'ProgressDeadlineExceeded') return { text: 'error: deployment "web" exceeded its progress deadline', exitCode: 1 }
  if (c.updated < s.cfg.replicas) return { text: `Waiting for deployment "web" rollout to finish: ${c.updated} out of ${s.cfg.replicas} new replicas have been updated...`, exitCode: null }
  if (c.total > c.updated) return { text: `Waiting for deployment "web" rollout to finish: ${c.total - c.updated} old replicas are pending termination...`, exitCode: null }
  if (c.updatedAvailable < c.updated) return { text: `Waiting for deployment "web" rollout to finish: ${c.updatedAvailable} of ${c.updated} updated replicas are available...`, exitCode: null }
  return { text: 'deployment "web" successfully rolled out', exitCode: 0 }
}

function cloneRollout(s: RolloutState): RolloutState {
  return { ...s, rss: s.rss.map((r) => ({ ...r, pods: r.pods.map((p) => ({ ...p })) })), log: [...s.log], markers: [...s.markers] }
}

function setReplicas(s: RolloutState, rs: RolloutRS, n: number) {
  while (rs.pods.length < n) {
    const name = `${rs.name}-${nameSuffix(s.seq++)}`
    rs.pods.push({ name, createdAt: s.t, readyAt: rs.good ? s.t + s.cfg.readySeconds : null })
    if (!rs.good) s.log.push({ t: s.t, who: 'kubelet', text: `${name}: Failed to pull image "${rs.image}": manifest unknown → ErrImagePull, then ImagePullBackOff` })
  }
  if (rs.pods.length > n) {
    // ReplicaSet controller deletes not-ready pods first, then the newest.
    const ranked = [...rs.pods].sort((a, b) => Number(isAvail(a, s.t)) - Number(isAvail(b, s.t)) || b.createdAt - a.createdAt)
    const doomed = new Set(ranked.slice(0, rs.pods.length - n).map((p) => p.name))
    rs.pods = rs.pods.filter((p) => !doomed.has(p.name))
  }
  rs.replicas = n
}

function track(s: RolloutState) {
  const c = rolloutCounts(s)
  s.minAvailableSeen = Math.min(s.minAvailableSeen, c.available)
  s.maxPodsSeen = Math.max(s.maxPodsSeen, c.total)
}

function progress(s: RolloutState, newRSName: string) {
  s.lastProgress = s.t
  s.progressing = { status: 'True', reason: 'ReplicaSetUpdated', message: `ReplicaSet "${newRSName}" is progressing.` }
}

/** One Deployment controller sync. Returns whether it changed anything. */
export function rolloutSync(s0: RolloutState): { state: RolloutState; changed: boolean } {
  const s = cloneRollout(s0)
  const { replicas, maxSurge, maxUnavailable } = s.cfg
  if (s.cfg.strategy === 'RollingUpdate' && validateRollingUpdate(maxSurge, maxUnavailable).length) return { state: s0, changed: false }
  let newRS = s.rss.find((r) => r.image === s.image)
  const old = s.rss.filter((r) => r !== newRS).sort((a, b) => a.created - b.created)
  const say = (text: string, math?: string) => s.log.push({ t: s.t, who: 'deployment controller', text, math })

  if (s.cfg.strategy === 'Recreate') {
    const live = old.filter((r) => r.replicas > 0)
    if (live.length) {
      for (const r of live) {
        say(`Scaled down replica set ${r.name} from ${r.replicas} to 0`, 'Recreate: every old pod goes first')
        setReplicas(s, r, 0)
      }
      progress(s, newRS?.name || rsName(s.image))
      track(s)
      return { state: s, changed: true }
    }
    if (!newRS) {
      newRS = { name: rsName(s.image), revision: s.revision, image: s.image, good: s.imageGood, replicas: 0, pods: [], created: s.t }
      s.rss.push(newRS)
      say(`Scaled up replica set ${newRS.name} from 0 to ${replicas} (new ReplicaSet, revision ${s.revision})`, 'Recreate: all new pods at once, after the old ones are gone')
      setReplicas(s, newRS, replicas)
      progress(s, newRS.name)
      track(s)
      return { state: s, changed: true }
    }
    if (newRS.replicas !== replicas) {
      say(`Scaled up replica set ${newRS.name} from ${newRS.replicas} to ${replicas}`)
      setReplicas(s, newRS, replicas)
      progress(s, newRS.name)
      track(s)
      return { state: s, changed: true }
    }
  } else {
    const { surge } = resolveFenceposts(maxSurge, maxUnavailable, replicas)
    const maxUnav = maxUnavailableFor(maxSurge, maxUnavailable, replicas)
    const specTotal = () => s.rss.reduce((n, r) => n + r.replicas, 0)
    if (!newRS) {
      const total = specTotal()
      const n = newRSNewReplicas(replicas, surge, total, 0)
      newRS = { name: rsName(s.image), revision: s.revision, image: s.image, good: s.imageGood, replicas: 0, pods: [], created: s.t }
      s.rss.push(newRS)
      say(`Scaled up replica set ${newRS.name} from 0 to ${n} (new ReplicaSet, revision ${s.revision})`, `maxTotal = replicas ${replicas} + maxSurge ${surge} = ${replicas + surge}; pods (spec) now ${total} → room for ${n}`)
      setReplicas(s, newRS, n)
      s.progressing = { status: 'True', reason: 'NewReplicaSetCreated', message: `Created new replica set "${newRS.name}"` }
      s.lastProgress = s.t
      track(s)
      return { state: s, changed: true }
    }
    // reconcileNewReplicaSet
    if (newRS.replicas > replicas) {
      say(`Scaled down replica set ${newRS.name} from ${newRS.replicas} to ${replicas}`, 'new ReplicaSet is above the desired count')
      setReplicas(s, newRS, replicas)
      progress(s, newRS.name)
      track(s)
      return { state: s, changed: true }
    }
    const total = specTotal()
    const want = newRSNewReplicas(replicas, surge, total, newRS.replicas)
    if (want !== newRS.replicas) {
      say(`Scaled up replica set ${newRS.name} from ${newRS.replicas} to ${want}`, `maxTotal = ${replicas} + ${surge} = ${replicas + surge}; pods (spec) ${total} → +${want - newRS.replicas}`)
      setReplicas(s, newRS, want)
      progress(s, newRS.name)
      track(s)
      return { state: s, changed: true }
    }
    // reconcileOldReplicaSets
    const plan = planOldScaleDown(replicas, maxUnav, { replicas: newRS.replicas, available: rsAvailable(newRS, s.t) }, old.map((r) => ({ replicas: r.replicas, available: rsAvailable(r, s.t) })))
    if (plan.cleaned + plan.scaled > 0) {
      old.forEach((r, i) => {
        if (plan.next[i] !== r.replicas) {
          say(`Scaled down replica set ${r.name} from ${r.replicas} to ${plan.next[i]}`, plan.math + (plan.cleaned ? ` (${plan.cleaned} unhealthy old pod(s) cleaned up first)` : ''))
          setReplicas(s, r, plan.next[i])
        }
      })
      progress(s, newRS.name)
      track(s)
      return { state: s, changed: true }
    }
    s.waiting = plan.math
  }
  // nothing to scale: is the rollout complete?
  const c = rolloutCounts(s)
  if (newRS && newRS.replicas === replicas && c.updatedAvailable === replicas && c.oldPods === 0) {
    if (!s.complete) {
      s.complete = true
      s.rolling = false
      s.progressing = { status: 'True', reason: 'NewReplicaSetAvailable', message: `ReplicaSet "${newRS.name}" has successfully progressed.` }
      say('Rollout complete: all replicas updated and available', 'Progressing=True, reason NewReplicaSetAvailable')
      s.markers.push('complete')
      return { state: s, changed: true }
    }
    s.waiting = ''
  }
  return { state: s0.waiting === s.waiting ? s0 : { ...s0, waiting: s.waiting }, changed: false }
}

/** The next moment something happens on its own: a pod becomes Ready or the progress deadline passes. */
export function nextRolloutEvent(s: RolloutState): { t: number; kind: 'ready' | 'deadline' } | null {
  const readies = s.rss.flatMap((r) => r.pods).filter((p) => p.readyAt !== null && p.readyAt > s.t).map((p) => p.readyAt as number)
  const nextReady = readies.length ? Math.min(...readies) : null
  const deadline = !s.complete && s.progressing.reason !== 'ProgressDeadlineExceeded' ? s.lastProgress + s.cfg.progressDeadlineSeconds : null
  if (nextReady !== null && (deadline === null || nextReady <= deadline)) return { t: nextReady, kind: 'ready' }
  if (deadline !== null && deadline > s.t) return { t: deadline, kind: 'deadline' }
  if (deadline !== null && deadline <= s.t) return { t: s.t, kind: 'deadline' }
  return null
}

/** One step: a controller sync if it has work, otherwise advance the clock to the next event. */
export function rolloutStep(s0: RolloutState): { state: RolloutState; moved: boolean } {
  const sync = rolloutSync(s0)
  if (sync.changed) return { state: sync.state, moved: true }
  const ev = nextRolloutEvent(sync.state)
  if (!ev) return { state: sync.state, moved: false }
  const s = cloneRollout(sync.state)
  s.t = ev.t
  if (ev.kind === 'ready') {
    for (const r of s.rss)
      for (const p of r.pods)
        if (p.readyAt === s.t) {
          s.log.push({ t: s.t, who: 'kubelet', text: `${p.name} is Ready (readiness probe passed) → counts as available` })
          if (r.image === s.image) progress(s, r.name)
        }
  } else {
    const newRS = s.rss.find((r) => r.image === s.image)
    s.progressing = { status: 'False', reason: 'ProgressDeadlineExceeded', message: `ReplicaSet "${newRS?.name || rsName(s.image)}" has timed out progressing.` }
    s.log.push({ t: s.t, who: 'deployment controller', text: 'Progressing=False, reason ProgressDeadlineExceeded. The controller does not roll back by itself.', math: `no progress for progressDeadlineSeconds ${s.cfg.progressDeadlineSeconds}s` })
    s.markers.push('deadline')
  }
  track(s)
  return { state: s, moved: true }
}

/** `oc set image deployment/web web=<image>`: changes the pod template, which starts a rollout. */
export function startRollout(s0: RolloutState, image: string, good: boolean): RolloutState {
  const s = cloneRollout(s0)
  if (image === s.image) return s0
  const existing = s.rss.find((r) => r.image === image)
  s.revision += 1
  if (existing) existing.revision = s.revision
  s.image = image
  s.imageGood = good
  s.complete = false
  s.rolling = true
  s.lastProgress = s.t
  // the Progressing condition is left as it was: the controller updates it on its next sync
  s.minAvailableSeen = rolloutCounts(s).available
  s.maxPodsSeen = rolloutCounts(s).total
  s.log.push({ t: s.t, who: 'you', text: `oc set image deployment/web web=${image}` })
  s.markers.push('start')
  return s
}

/** `oc rollout undo deployment/web`: put the previous revision's template back. The old ReplicaSet is reused and gets the next revision number. */
export function rollbackRollout(s0: RolloutState): RolloutState {
  const prev = s0.rss.filter((r) => r.image !== s0.image).sort((a, b) => b.revision - a.revision)[0]
  if (!prev) return s0
  const s = startRollout(s0, prev.image, prev.good)
  s.log[s.log.length - 1] = { t: s.t, who: 'you', text: `oc rollout undo deployment/web → template back to ${prev.image} (ReplicaSet ${prev.name} becomes revision ${s.revision})` }
  s.markers.push('rollback')
  return s
}

/** Run until nothing moves (bounded); used by "Run to end" and the tests. */
export function runRollout(s: RolloutState, maxSteps = 500): RolloutState {
  let cur = s
  for (let i = 0; i < maxSteps; i++) {
    const r = rolloutStep(cur)
    if (!r.moved) return r.state
    cur = r.state
  }
  return cur
}

// =====================================================================================================
// Controllers and reconciliation: Deployment → ReplicaSet → Pods
// Docs: https://kubernetes.io/docs/concepts/architecture/controller/
//       https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/#how-a-replicaset-works
//       https://kubernetes.io/docs/concepts/overview/working-with-objects/owners-dependents/
//       https://kubernetes.io/docs/concepts/architecture/garbage-collection/
// Each controller is a loop: it is woken by watch events (queued, de-duplicated keys), observes the
// current state, computes the difference with the desired state and acts through the API.
// Simplifications: one work queue for all controllers processed in order; the scheduler picks the least
// loaded node; the kubelet starts a pod in one step and finishes termination in one step; controllers are
// not re-woken by events their own expectations already account for (the real ones wake and find nothing
// to do); no resync period, rate limiting, proportional scaling or leader election.
// =====================================================================================================

export type RcCtrl = 'deployment' | 'replicaset' | 'scheduler' | 'kubelet' | 'garbage-collector'
export type RcPod = { name: string; uid: number; owner: string | null; ownerUid: number | null; hash: string; app: string; image: string; phase: 'Pending' | 'Running'; node: string | null; terminating: boolean }
export type RcRS = { name: string; uid: number; hash: string; image: string; replicas: number; revision: number; readyReplicas: number }
export type RcWork = { ctrl: RcCtrl; key: string; why: string }
export type RcLog = { n: number; who: RcCtrl | 'you'; key: string; observe: string; diff: string; act: string[] }
export type RcState = {
  deploy: { name: string; replicas: number; image: string; revision: number }
  rss: RcRS[]
  pods: RcPod[]
  queue: RcWork[]
  log: RcLog[]
  seq: number
  n: number
  markers: string[]
}
export const RC_NODES = ['worker-1', 'worker-2', 'worker-3']
export const RC_MAX_SURGE = '25%'
export const RC_MAX_UNAVAILABLE = '25%'

const rcHash = (image: string) => templateHash('web|' + image)

export function initialReconcile(): RcState {
  const image = 'quay.io/acme/web:1.0'
  const hash = rcHash(image)
  const rs: RcRS = { name: `web-${hash}`, uid: 1001, hash, image, replicas: 3, revision: 1, readyReplicas: 3 }
  const pods: RcPod[] = [0, 1, 2].map((i) => ({ name: `${rs.name}-${nameSuffix(100 + i)}`, uid: i + 1, owner: rs.name, ownerUid: rs.uid, hash, app: 'web', image, phase: 'Running', node: RC_NODES[i], terminating: false }))
  return { deploy: { name: 'web', replicas: 3, image, revision: 1 }, rss: [rs], pods, queue: [], log: [], seq: 3, n: 0, markers: [] }
}

function cloneRc(s: RcState): RcState {
  return { ...s, deploy: { ...s.deploy }, rss: s.rss.map((r) => ({ ...r })), pods: s.pods.map((p) => ({ ...p })), queue: [...s.queue], log: [...s.log], markers: [...s.markers] }
}
function enqueue(s: RcState, ctrl: RcCtrl, key: string, why: string) {
  if (!s.queue.some((w) => w.ctrl === ctrl && w.key === key)) s.queue.push({ ctrl, key, why })
}
const podMatches = (p: RcPod, rs: RcRS) => p.app === 'web' && p.hash === rs.hash
const activePods = (s: RcState, rs: RcRS) => s.pods.filter((p) => p.ownerUid === rs.uid && !p.terminating)

function rcNewPod(s: RcState, rs: RcRS): RcPod {
  const pod: RcPod = { name: `${rs.name}-${nameSuffix(100 + s.seq)}`, uid: s.seq + 1, owner: rs.name, ownerUid: rs.uid, hash: rs.hash, app: 'web', image: rs.image, phase: 'Pending', node: null, terminating: false }
  s.seq++
  s.pods.push(pod)
  enqueue(s, 'scheduler', pod.name, `pod ${pod.name} created without a node`)
  return pod
}

function rcDeletePod(s: RcState, p: RcPod, why: string) {
  p.terminating = true
  enqueue(s, 'kubelet', p.name, why)
}

/** Ranking used when a ReplicaSet scales down: unscheduled, then not running, then newest first. */
function deletionOrder(pods: RcPod[]) {
  return [...pods].sort((a, b) => Number(a.node !== null) - Number(b.node !== null) || Number(a.phase === 'Running') - Number(b.phase === 'Running') || b.uid - a.uid)
}

function rcScaleRS(s: RcState, rs: RcRS, to: number) {
  rs.replicas = to
  enqueue(s, 'replicaset', rs.name, `spec.replicas of ${rs.name} changed`)
}

// ---- user actions (they change objects through the API; watches enqueue the controllers that care)
export function rcDeletePodAction(s0: RcState, name: string): RcState {
  const s = cloneRc(s0)
  const p = s.pods.find((x) => x.name === name)
  if (!p || p.terminating) return s0
  p.terminating = true
  s.log.push({ n: ++s.n, who: 'you', key: name, observe: '', diff: '', act: [`oc delete pod ${name}`] })
  const owner = s.rss.find((r) => r.uid === p.ownerUid)
  if (owner) enqueue(s, 'replicaset', owner.name, `pod ${name} got a deletionTimestamp`)
  enqueue(s, 'kubelet', name, `pod ${name} is terminating`)
  s.markers.push('user:delete-pod')
  return s
}
export function rcScaleDeployment(s0: RcState, replicas: number): RcState {
  const s = cloneRc(s0)
  if (replicas === s.deploy.replicas || replicas < 0) return s0
  s.log.push({ n: ++s.n, who: 'you', key: 'web', observe: '', diff: '', act: [`oc scale deployment/web --replicas=${replicas}`] })
  s.deploy.replicas = replicas
  enqueue(s, 'deployment', 'web', 'Deployment spec.replicas changed')
  s.markers.push('user:scale-deploy')
  return s
}
export function rcEditRS(s0: RcState, name: string, replicas: number): RcState {
  const s = cloneRc(s0)
  const rs = s.rss.find((r) => r.name === name)
  if (!rs || rs.replicas === replicas || replicas < 0) return s0
  s.log.push({ n: ++s.n, who: 'you', key: name, observe: '', diff: '', act: [`oc scale replicaset/${name} --replicas=${replicas}`] })
  rs.replicas = replicas
  enqueue(s, 'replicaset', name, `spec.replicas of ${name} changed`)
  enqueue(s, 'deployment', 'web', `owned ReplicaSet ${name} changed`)
  s.markers.push('user:edit-rs')
  return s
}
export function rcSetImage(s0: RcState, image: string): RcState {
  const s = cloneRc(s0)
  if (image === s.deploy.image) return s0
  s.log.push({ n: ++s.n, who: 'you', key: 'web', observe: '', diff: '', act: [`oc set image deployment/web web=${image}`] })
  s.deploy.image = image
  s.deploy.revision += 1
  enqueue(s, 'deployment', 'web', 'Deployment pod template changed')
  s.markers.push('user:set-image')
  return s
}
export function rcRelabelPod(s0: RcState, name: string): RcState {
  const s = cloneRc(s0)
  const p = s.pods.find((x) => x.name === name)
  if (!p || p.app !== 'web') return s0
  s.log.push({ n: ++s.n, who: 'you', key: name, observe: '', diff: '', act: [`oc label pod ${name} app=web-debug --overwrite`] })
  p.app = 'web-debug'
  const owner = s.rss.find((r) => r.uid === p.ownerUid)
  if (owner) enqueue(s, 'replicaset', owner.name, `labels of pod ${name} changed`)
  s.markers.push('user:relabel')
  return s
}
export function rcDeleteRS(s0: RcState, name: string): RcState {
  const s = cloneRc(s0)
  if (!s.rss.some((r) => r.name === name)) return s0
  s.log.push({ n: ++s.n, who: 'you', key: name, observe: '', diff: '', act: [`oc delete replicaset ${name}  (propagationPolicy: Background)`] })
  s.rss = s.rss.filter((r) => r.name !== name)
  enqueue(s, 'garbage-collector', name, `owner ${name} was deleted`)
  enqueue(s, 'deployment', 'web', `owned ReplicaSet ${name} was deleted`)
  s.markers.push('user:delete-rs')
  return s
}

// ---- controllers
function reconcileDeployment(s: RcState): RcLog {
  const d = s.deploy
  const hash = rcHash(d.image)
  let newRS = s.rss.find((r) => r.hash === hash)
  const old = s.rss.filter((r) => r !== newRS)
  const observe = `Deployment web wants ${d.replicas} × ${d.image} (pod-template-hash ${hash}). Owned ReplicaSets: ${s.rss.map((r) => `${r.name} spec ${r.replicas}/ready ${r.readyReplicas}`).join(', ') || 'none'}.`
  const log: RcLog = { n: 0, who: 'deployment', key: 'web', observe, diff: '', act: [] }
  const { surge } = resolveFenceposts(RC_MAX_SURGE, RC_MAX_UNAVAILABLE, d.replicas)
  const maxUnav = maxUnavailableFor(RC_MAX_SURGE, RC_MAX_UNAVAILABLE, d.replicas)
  const total = () => s.rss.reduce((n, r) => n + r.replicas, 0)
  if (!newRS) {
    const oldActive = old.filter((r) => r.replicas > 0)
    const n = oldActive.length ? newRSNewReplicas(d.replicas, surge, total(), 0) : d.replicas
    newRS = { name: `web-${hash}`, uid: 1001 + s.seq * 7, hash, image: d.image, replicas: 0, revision: d.revision, readyReplicas: 0 }
    s.seq++
    s.rss.push(newRS)
    log.diff = `no ReplicaSet matches the current pod template (hash ${hash})`
    log.act.push(`POST replicasets ${newRS.name} (revision ${d.revision}, replicas ${n})`)
    rcScaleRS(s, newRS, n)
    if (oldActive.length) s.markers.push('deploy:create-new-rs')
    else s.markers.push('deploy:recreate-rs')
    return log
  }
  const oldActive = old.filter((r) => r.replicas > 0)
  if (oldActive.length === 0) {
    if (newRS.replicas !== d.replicas) {
      log.diff = `ReplicaSet ${newRS.name} spec.replicas ${newRS.replicas} ≠ Deployment replicas ${d.replicas}`
      log.act.push(`PATCH replicasets/${newRS.name} spec.replicas: ${newRS.replicas} → ${d.replicas}`)
      if (s.markers.includes('user:edit-rs') && !s.markers.includes('deploy:revert-rs')) s.markers.push('deploy:revert-rs')
      rcScaleRS(s, newRS, d.replicas)
      return log
    }
    log.diff = 'none: the only active ReplicaSet already has the desired replicas'
    if (newRS.readyReplicas === d.replicas && s.rss.length > 1) s.markers.push('deploy:rollout-complete')
    return log
  }
  // rolling update in progress
  if (newRS.replicas > d.replicas) {
    log.diff = `new ReplicaSet above the desired count (${newRS.replicas} > ${d.replicas})`
    log.act.push(`PATCH replicasets/${newRS.name} spec.replicas: ${newRS.replicas} → ${d.replicas}`)
    rcScaleRS(s, newRS, d.replicas)
    return log
  }
  const want = newRSNewReplicas(d.replicas, surge, total(), newRS.replicas)
  if (want !== newRS.replicas) {
    log.diff = `rolling update: new ReplicaSet ${newRS.replicas}/${d.replicas}; maxSurge ${RC_MAX_SURGE} → ${surge}, total pods may reach ${d.replicas + surge}`
    log.act.push(`PATCH replicasets/${newRS.name} spec.replicas: ${newRS.replicas} → ${want}`)
    rcScaleRS(s, newRS, want)
    return log
  }
  const plan = planOldScaleDown(d.replicas, maxUnav, { replicas: newRS.replicas, available: newRS.readyReplicas }, old.map((r) => ({ replicas: r.replicas, available: r.readyReplicas })))
  if (plan.cleaned + plan.scaled > 0) {
    log.diff = `rolling update: ${plan.math}`
    old.forEach((r, i) => {
      if (plan.next[i] !== r.replicas) {
        log.act.push(`PATCH replicasets/${r.name} spec.replicas: ${r.replicas} → ${plan.next[i]}`)
        rcScaleRS(s, r, plan.next[i])
      }
    })
    return log
  }
  log.diff = `rolling update: waiting for new pods to become available (${plan.math})`
  return log
}

function reconcileReplicaSet(s: RcState, name: string): RcLog {
  const rs = s.rss.find((r) => r.name === name)
  if (!rs) return { n: 0, who: 'replicaset', key: name, observe: `ReplicaSet ${name} no longer exists`, diff: 'none', act: [] }
  const log: RcLog = { n: 0, who: 'replicaset', key: name, observe: '', diff: '', act: [] }
  // release owned pods that no longer match the selector; adopt matching orphans
  for (const p of s.pods.filter((x) => x.ownerUid === rs.uid && !podMatches(x, rs))) {
    p.owner = null
    p.ownerUid = null
    log.act.push(`PATCH pods/${p.name}: remove ownerReference (labels no longer match selector app=web,pod-template-hash=${rs.hash})`)
    s.markers.push('rs:release')
  }
  for (const p of s.pods.filter((x) => x.ownerUid === null && !x.terminating && podMatches(x, rs))) {
    p.owner = rs.name
    p.ownerUid = rs.uid
    log.act.push(`PATCH pods/${p.name}: add ownerReference (adopt orphan that matches the selector)`)
  }
  const active = activePods(s, rs)
  const terminating = s.pods.filter((p) => p.ownerUid === rs.uid && p.terminating).length
  log.observe = `ReplicaSet ${rs.name} wants ${rs.replicas}; pods matching app=web,pod-template-hash=${rs.hash}: ${active.length} active${terminating ? `, ${terminating} terminating (not counted)` : ''}.`
  const diff = rs.replicas - active.length
  if (diff > 0) {
    log.diff = `${active.length} < ${rs.replicas}: create ${diff}`
    for (let i = 0; i < diff; i++) {
      const p = rcNewPod(s, rs)
      log.act.push(`POST pods ${p.name}`)
    }
    if (s.markers.includes('user:delete-pod')) s.markers.push('rs:replace-pod')
  } else if (diff < 0) {
    log.diff = `${active.length} > ${rs.replicas}: delete ${-diff}`
    for (const p of deletionOrder(active).slice(0, -diff)) {
      rcDeletePod(s, p, `ReplicaSet ${rs.name} scaled down`)
      log.act.push(`DELETE pods/${p.name}`)
    }
  } else log.diff = `${active.length} = ${rs.replicas}: pod count matches`
  const ready = activePods(s, rs).filter((p) => p.phase === 'Running').length
  if (ready !== rs.readyReplicas) {
    log.act.push(`PUT replicasets/${rs.name}/status readyReplicas: ${rs.readyReplicas} → ${ready}`)
    rs.readyReplicas = ready
    enqueue(s, 'deployment', 'web', `status of ReplicaSet ${rs.name} changed`)
  }
  return log
}

function reconcileScheduler(s: RcState, name: string): RcLog {
  const p = s.pods.find((x) => x.name === name)
  if (!p || p.node || p.terminating) return { n: 0, who: 'scheduler', key: name, observe: `pod ${name} is gone or already bound`, diff: 'none', act: [] }
  const load = (node: string) => s.pods.filter((x) => x.node === node && !x.terminating).length
  const node = [...RC_NODES].sort((a, b) => load(a) - load(b) || a.localeCompare(b))[0]
  p.node = node
  enqueue(s, 'kubelet', name, `pod ${name} bound to ${node}`)
  return { n: 0, who: 'scheduler', key: name, observe: `pod ${name} has no spec.nodeName; nodes run ${RC_NODES.map((x) => `${x}: ${load(x)}`).join(', ')} pods`, diff: 'unscheduled pod', act: [`POST pods/${name}/binding → ${node}`] }
}

function reconcileKubelet(s: RcState, name: string): RcLog {
  const p = s.pods.find((x) => x.name === name)
  if (!p) return { n: 0, who: 'kubelet', key: name, observe: `pod ${name} is gone`, diff: 'none', act: [] }
  if (p.terminating) {
    s.pods = s.pods.filter((x) => x !== p)
    return { n: 0, who: 'kubelet', key: name, observe: `pod ${name} has a deletionTimestamp${p.node ? ` on ${p.node}` : ''}`, diff: 'containers must stop', act: [`SIGTERM, containers exit; DELETE pods/${name} (grace period over)`] }
  }
  if (p.node && p.phase === 'Pending') {
    p.phase = 'Running'
    const rs = s.rss.find((r) => r.uid === p.ownerUid)
    if (rs) enqueue(s, 'replicaset', rs.name, `pod ${name} became Ready`)
    return { n: 0, who: 'kubelet', key: name, observe: `pod ${name} is bound to ${p.node} but has no running containers`, diff: 'containers not running', act: [`pull ${p.image}, create and start containers; PATCH pods/${name}/status phase Running, Ready=True`] }
  }
  return { n: 0, who: 'kubelet', key: name, observe: `pod ${name} is ${p.phase}`, diff: 'none', act: [] }
}

function reconcileGC(s: RcState, owner: string): RcLog {
  const deps = s.pods.filter((p) => p.ownerUid !== null && !p.terminating && !s.rss.some((r) => r.uid === p.ownerUid))
  for (const p of deps) rcDeletePod(s, p, `owner ${owner} no longer exists`)
  return { n: 0, who: 'garbage-collector', key: owner, observe: `${deps.length} pod(s) have an ownerReference to ${owner}, which no longer exists`, diff: deps.length ? 'dependents without an owner' : 'none', act: deps.map((p) => `DELETE pods/${p.name}`) }
}

/** Process the next queued work item. */
export function rcStep(s0: RcState): RcState {
  if (s0.queue.length === 0) return s0
  const s = cloneRc(s0)
  const work = s.queue.shift() as RcWork
  let log: RcLog
  switch (work.ctrl) {
    case 'deployment':
      log = reconcileDeployment(s)
      break
    case 'replicaset':
      log = reconcileReplicaSet(s, work.key)
      break
    case 'scheduler':
      log = reconcileScheduler(s, work.key)
      break
    case 'kubelet':
      log = reconcileKubelet(s, work.key)
      break
    case 'garbage-collector':
      log = reconcileGC(s, work.key)
      break
  }
  log.n = ++s.n
  log.observe = `woken because ${work.why}. ${log.observe}`
  s.log.push(log)
  return s
}

export function rcRunToSteady(s: RcState, max = 300): RcState {
  let cur = s
  for (let i = 0; i < max && cur.queue.length; i++) cur = rcStep(cur)
  return cur
}

export function rcSummary(s: RcState) {
  const live = s.pods.filter((p) => !p.terminating)
  return {
    steady: s.queue.length === 0,
    running: live.filter((p) => p.phase === 'Running').length,
    owned: live.filter((p) => p.ownerUid !== null).length,
    orphans: s.pods.filter((p) => p.ownerUid === null && !p.terminating),
    newHash: rcHash(s.deploy.image),
  }
}

// =====================================================================================================
// Probes, restarts and CrashLoopBackOff (kubelet)
// Docs: https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/
//       https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/#configure-probes
//       https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
//       https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#container-restarts
// Behaviour modelled: liveness/readiness wait until the startup probe succeeds; failureThreshold
// consecutive failures make a liveness/startup probe kill the container, and make readiness report
// NotReady (no restart); successThreshold consecutive successes are needed to become Ready again; a new
// container starts NotReady. Restart back-off follows the kubelet (doBackOff + flowcontrol.Backoff): first
// restart immediate (1s in this model), then 10s, 20s, 40s… capped at 300s, reset after 10 minutes without a restart.
// Simplifications: one container; whole seconds; probes run at start + initialDelaySeconds + k·periodSeconds
// (the kubelet's ticker is aligned to when its probe worker started, so real probes can be up to one period
// later); initialDelaySeconds is counted from container start, as kubelet prober/worker.go does (the docs
// describe liveness/readiness delays as beginning after the startup probe succeeds; the code only holds those
// probes until then); the extra readiness runs the kubelet triggers to become Ready faster are not modelled; a
// killed container stops at once (terminationGracePeriodSeconds not modelled); a probe fails when
// the endpoint answers slower than or equal to timeoutSeconds; no exec/gRPC probes; feature gates that
// change back-off (ReduceDefaultCrashLoopBackOffDecay, KubeletCrashLoopBackOffMax) are off.
// =====================================================================================================

export type ProbeKind = 'startup' | 'readiness' | 'liveness'
export type ProbeSpec = { enabled: boolean; initialDelaySeconds: number; periodSeconds: number; timeoutSeconds: number; successThreshold: number; failureThreshold: number }
export type AppScript = {
  /** seconds after a container starts before the app listens */
  startSeconds: number
  /** the process exits with code 1 this long after starting (null = never) */
  exitAfterSeconds: number | null
  /** uptime after which the app deadlocks: health endpoints stop answering (null = never) */
  hangAfterSeconds: number | null
  /** the database the app needs is down during [from, to) (absolute seconds) */
  dependencyDown: { from: number; to: number } | null
  /** /healthz also checks the database (an anti-pattern for liveness) */
  livenessChecksDependency: boolean
  /** seconds the health endpoints take to answer */
  healthLatencySeconds: number
}
export type ProbeConfig = { startup: ProbeSpec; readiness: ProbeSpec; liveness: ProbeSpec; app: AppScript; horizon: number }
export type ProbeMark = { t: number; probe: ProbeKind; ok: boolean; detail: string; container: number }
export type ContainerRun = { index: number; start: number; end: number | null; endReason: 'Error' | 'liveness' | 'startup' | null; startedAt: number | null }
export type BackoffWait = { from: number; to: number; backoff: number }
/** type 'Status' marks container status changes that are not Kubernetes Events. */
export type PodEvent = { t: number; type: 'Normal' | 'Warning' | 'Status'; reason: string; message: string }
export type ProbeTimeline = {
  horizon: number
  runs: ContainerRun[]
  waits: BackoffWait[]
  marks: ProbeMark[]
  ready: { from: number; to: number }[]
  events: PodEvent[]
  restarts: number
  maxBackoff: number
  errors: string[]
}

export const DEFAULT_PROBE: ProbeSpec = { enabled: false, initialDelaySeconds: 0, periodSeconds: 10, timeoutSeconds: 1, successThreshold: 1, failureThreshold: 3 }
export const BACKOFF_INITIAL = 10
export const BACKOFF_MAX = 300

/** API defaulting (pkg/apis/core/v1/defaults.go): 0 means "use the default" for these fields. */
export function defaultProbe(p: ProbeSpec): ProbeSpec {
  return {
    ...p,
    periodSeconds: p.periodSeconds === 0 ? 10 : p.periodSeconds,
    timeoutSeconds: p.timeoutSeconds === 0 ? 1 : p.timeoutSeconds,
    successThreshold: p.successThreshold === 0 ? 1 : p.successThreshold,
    failureThreshold: p.failureThreshold === 0 ? 3 : p.failureThreshold,
  }
}

/** Probe validation (pkg/apis/core/validation): negatives are rejected; liveness/startup successThreshold must be 1. */
export function validateProbes(cfg: Pick<ProbeConfig, 'startup' | 'readiness' | 'liveness'>): string[] {
  const errs: string[] = []
  ;(['startup', 'readiness', 'liveness'] as ProbeKind[]).forEach((k) => {
    if (!cfg[k].enabled) return
    const p = defaultProbe(cfg[k])
    const f = `spec.containers[0].${k}Probe`
    for (const field of ['initialDelaySeconds', 'periodSeconds', 'timeoutSeconds', 'successThreshold', 'failureThreshold'] as const)
      if (p[field] < 0) errs.push(`${f}.${field}: Invalid value: ${p[field]}: must be greater than or equal to 0`)
    if (k !== 'readiness' && p.successThreshold !== 1 && p.successThreshold >= 0) errs.push(`${f}.successThreshold: Invalid value: ${p.successThreshold}: must be 1`)
  })
  return errs
}

/** flowcontrol.Backoff as the kubelet uses it (initial 10s, max 300s, no jitter). */
class KubeletBackoff {
  entry: { backoff: number; lastUpdate: number } | null = null
  private expired(eventTime: number) {
    return this.entry !== null && eventTime - this.entry.lastUpdate > 2 * BACKOFF_MAX
  }
  inBackOffSince(eventTime: number, now: number) {
    if (!this.entry || this.expired(eventTime)) return false
    return now - eventTime < this.entry.backoff
  }
  next(eventTime: number, now: number) {
    if (!this.entry || this.expired(eventTime)) this.entry = { backoff: BACKOFF_INITIAL, lastUpdate: now }
    else this.entry = { backoff: Math.min(this.entry.backoff * 2, BACKOFF_MAX), lastUpdate: now }
  }
}

const POD_IP = '10.217.0.42'

export function simulateProbes(cfg: ProbeConfig): ProbeTimeline {
  const out: ProbeTimeline = { horizon: cfg.horizon, runs: [], waits: [], marks: [], ready: [], events: [], restarts: 0, maxBackoff: 0, errors: validateProbes(cfg) }
  if (out.errors.length) return out
  cfg = { ...cfg, startup: defaultProbe(cfg.startup), readiness: defaultProbe(cfg.readiness), liveness: defaultProbe(cfg.liveness) }
  const { app } = cfg
  const backoff = new KubeletBackoff()
  const probes = (['startup', 'liveness', 'readiness'] as ProbeKind[]).filter((k) => cfg[k].enabled)

  let run = null as ContainerRun | null
  let restartAt = 0 as number | null
  let started = false
  let ready = false
  let readySince = null as number | null
  const streak: Record<ProbeKind, { ok: number; fail: number }> = { startup: { ok: 0, fail: 0 }, liveness: { ok: 0, fail: 0 }, readiness: { ok: 0, fail: 0 } }
  const ev = (t: number, type: PodEvent['type'], reason: string, message: string) => out.events.push({ t, type, reason, message })
  const setReady = (t: number, v: boolean) => {
    if (v === ready) return
    ready = v
    if (v) readySince = t
    else if (readySince !== null) {
      out.ready.push({ from: readySince, to: t })
      readySince = null
    }
  }
  const finish = (t: number, reason: ContainerRun['endReason']) => {
    if (!run) return
    const prevEnd = out.runs.length ? out.runs[out.runs.length - 1].end : null
    run.end = t
    run.endReason = reason
    out.runs.push(run)
    run = null
    setReady(t, false)
    // kubelet doBackOff: a crash is checked against its own finish time; a probe kill is decided in the same
    // sync, against the previous exited container (the killed one still shows as running in that snapshot).
    // "Immediate" restarts take one second in this model (stop, then start on the next tick).
    const firstTs = reason === 'Error' ? t : prevEnd
    if (firstTs === null) restartAt = t + 1
    else if (!backoff.inBackOffSince(firstTs, t)) {
      backoff.next(firstTs, t)
      restartAt = t + 1
    } else {
      const wait = backoff.entry ? backoff.entry.backoff : BACKOFF_INITIAL
      restartAt = t + wait
      backoff.next(t, restartAt)
      out.waits.push({ from: t, to: restartAt, backoff: wait })
      out.maxBackoff = Math.max(out.maxBackoff, wait)
      ev(t, 'Warning', 'BackOff', 'Back-off restarting failed container app in pod web-7f9c_shop(5f0c…)')
      ev(t, 'Status', 'CrashLoopBackOff', `back-off ${wait}s restarting failed container=app pod=web-7f9c_shop(5f0c…)`)
    }
  }

  const outcome = (k: ProbeKind, t: number, uptime: number): { ok: boolean; detail: string } => {
    const path = k === 'readiness' ? '/ready' : '/healthz'
    const url = `http://${POD_IP}:8080${path}`
    if (uptime < app.startSeconds) return { ok: false, detail: `Get "${url}": dial tcp ${POD_IP}:8080: connect: connection refused` }
    if (app.hangAfterSeconds !== null && uptime >= app.hangAfterSeconds) return { ok: false, detail: `Get "${url}": context deadline exceeded (Client.Timeout exceeded while awaiting headers)` }
    if (app.healthLatencySeconds >= cfg[k].timeoutSeconds) return { ok: false, detail: `Get "${url}": context deadline exceeded (Client.Timeout exceeded while awaiting headers)` }
    const depDown = app.dependencyDown !== null && t >= app.dependencyDown.from && t < app.dependencyDown.to
    if (depDown && (k === 'readiness' || app.livenessChecksDependency)) return { ok: false, detail: 'HTTP probe failed with statuscode: 503' }
    return { ok: true, detail: '200 OK' }
  }

  // Starts the next container when its restart time has come.
  const startIfDue = (t: number) => {
    if (run || restartAt === null || t < restartAt) return
    const index = out.runs.length
    run = { index, start: t, end: null, endReason: null, startedAt: null }
    if (index > 0) out.restarts++
    started = !cfg.startup.enabled
    if (started) run.startedAt = t
    for (const k of probes) streak[k] = { ok: 0, fail: 0 }
    restartAt = null
    ev(t, 'Normal', 'Started', 'Started container app')
    if (!cfg.readiness.enabled && started) setReady(t, true)
  }

  for (let t = 0; t <= cfg.horizon; t++) {
    startIfDue(t)
    if (!run) continue
    const uptime = t - (run as ContainerRun).start
    if (app.exitAfterSeconds !== null && uptime >= app.exitAfterSeconds) {
      ev(t, 'Status', 'Terminated', 'container app exited: exit code 1, reason Error')
      finish(t, 'Error')
      continue
    }
    for (const k of probes) {
      const p = cfg[k]
      if (uptime < p.initialDelaySeconds || (uptime - p.initialDelaySeconds) % p.periodSeconds !== 0) continue
      if (k !== 'startup' && !started) continue
      if (k === 'startup' && started) continue
      const r = outcome(k, t, uptime)
      const cur = run as ContainerRun
      out.marks.push({ t, probe: k, ok: r.ok, detail: r.detail, container: cur.index })
      const st = streak[k]
      if (r.ok) {
        st.ok++
        st.fail = 0
      } else {
        st.fail++
        st.ok = 0
        ev(t, 'Warning', 'Unhealthy', `${k[0].toUpperCase() + k.slice(1)} probe failed: ${r.detail}`)
      }
      if (k === 'startup') {
        if (r.ok) {
          started = true
          cur.startedAt = t
          if (!cfg.readiness.enabled) setReady(t, true)
        } else if (st.fail >= p.failureThreshold) {
          ev(t, 'Normal', 'Killing', 'Container app failed startup probe, will be restarted')
          finish(t, 'startup')
          break
        }
      } else if (k === 'liveness') {
        if (!r.ok && st.fail >= p.failureThreshold) {
          ev(t, 'Normal', 'Killing', 'Container app failed liveness probe, will be restarted')
          finish(t, 'liveness')
          break
        }
      } else {
        if (!ready && st.ok >= p.successThreshold) setReady(t, true)
        else if (ready && st.fail >= p.failureThreshold) setReady(t, false)
      }
    }
  }
  if (readySince !== null) out.ready.push({ from: readySince, to: cfg.horizon })
  if (run) out.runs.push(run)
  return out
}

/** Pod status column at time t (what `oc get pods` would print). */
export function probeStatusAt(tl: ProbeTimeline, t: number): { status: string; ready: boolean; restarts: number; inEndpoints: 'serving' | 'not ready' } {
  const within = (from: number, to: number) => from <= t && (t < to || (to === tl.horizon && t <= to))
  const run = tl.runs.find((r) => r.start <= t && (r.end === null || t < r.end))
  const wait = tl.waits.find((w) => w.from <= t && t < w.to)
  const ready = tl.ready.some((r) => within(r.from, r.to))
  const restarts = tl.runs.filter((r) => r.index > 0 && r.start <= t).length
  const status = run ? 'Running' : wait ? 'CrashLoopBackOff' : tl.runs.some((r) => r.end !== null && r.end <= t && r.endReason === 'Error') ? 'Error' : 'Running'
  return { status, ready, restarts, inEndpoints: ready ? 'serving' : 'not ready' }
}

/** What one probe looked like at time t: its last answer, and how many in a row it has failed or passed. */
export type ProbeNow = { kind: ProbeKind; path: '/ready' | '/healthz'; last: ProbeMark | null; fails: number; oks: number; threshold: number; cause: string | null }
/** The pod at time t, cause and effect: the database, each probe, the container, readiness and Service traffic. */
export type ProbeSnapshot = {
  t: number
  database: 'up' | 'down' | null
  probes: ProbeNow[]
  container: { state: 'running' | 'backoff' | 'stopped' | 'none'; run: number | null; uptime: number | null; backoffLeft: number | null; lastStop: ContainerRun['endReason'] }
  ready: boolean
  traffic: 'serving' | 'blocked' | 'none'
  story: string
}

/** Why a probe failed, in a learner's words, from the kubelet's message (and the database at that moment). */
export function probeCause(m: ProbeMark, cfg: ProbeConfig): string | null {
  if (m.ok) return null
  if (m.detail.includes('503')) return cfg.app.dependencyDown && m.t >= cfg.app.dependencyDown.from && m.t < cfg.app.dependencyDown.to ? 'database down' : 'HTTP 503'
  if (m.detail.includes('connection refused')) return 'not listening yet'
  if (m.detail.includes('deadline exceeded')) return `no answer within ${cfg[m.probe].timeoutSeconds}s`
  return 'failed'
}

export function probeSnapshot(tl: ProbeTimeline, cfg: ProbeConfig, t: number): ProbeSnapshot {
  const st = probeStatusAt(tl, t)
  const run = tl.runs.find((r) => r.start <= t && (r.end === null || t < r.end)) || null
  const wait = tl.waits.find((w) => w.from <= t && t < w.to) || null
  const stopped = [...tl.runs].reverse().find((r) => r.end !== null && r.end <= t) || null
  const kinds = (['startup', 'readiness', 'liveness'] as ProbeKind[]).filter((k) => cfg[k].enabled)
  const probes: ProbeNow[] = kinds.map((k) => {
    // the streak counts only the current container's answers (a restart starts every probe afresh)
    const marks = tl.marks.filter((m) => m.probe === k && m.t <= t && (run ? m.container === run.index : true))
    const last = marks.length ? marks[marks.length - 1] : null
    let fails = 0
    let oks = 0
    for (let i = marks.length - 1; i >= 0 && !marks[i].ok; i--) fails++
    for (let i = marks.length - 1; i >= 0 && marks[i].ok; i--) oks++
    return { kind: k, path: k === 'readiness' ? '/ready' : '/healthz', last: run || !last ? last : null, fails: run ? fails : 0, oks: run ? oks : 0, threshold: cfg[k].failureThreshold, cause: last && run ? probeCause(last, cfg) : null }
  })
  const db = cfg.app.dependencyDown ? (t >= cfg.app.dependencyDown.from && t < cfg.app.dependencyDown.to ? 'down' : 'up') : null
  const state: ProbeSnapshot['container']['state'] = run ? 'running' : wait ? 'backoff' : stopped ? 'stopped' : 'none'
  const ready = st.ready
  const traffic = !run ? 'none' : ready ? 'serving' : 'blocked'
  const p = (k: ProbeKind) => probes.find((x) => x.kind === k)
  const r = p('readiness')
  const l = p('liveness')
  const s = p('startup')
  const killer = (x: ContainerRun['endReason']) => (x === 'liveness' ? 'liveness probe (/healthz)' : x === 'startup' ? 'startup probe (/healthz)' : 'process')
  let story: string
  if (wait && stopped) {
    const left = wait.to - t
    story =
      stopped.endReason === 'Error'
        ? `The process exited with code 1. The kubelet waits ${left}s (CrashLoopBackOff, back-off ${wait.backoff}s) before restarting it. No container: no traffic.`
        : `The ${killer(stopped.endReason)} failed ${cfg[stopped.endReason as ProbeKind].failureThreshold} times in a row, so the kubelet killed the container. It restarts it in ${left}s (CrashLoopBackOff, back-off ${wait.backoff}s). No container: no traffic.`
  } else if (!run) {
    story = stopped ? `The container stopped (${killer(stopped.endReason)}); the kubelet restarts it at once.` : 'Waiting for the container to start.'
  } else if (stopped && !ready && stopped.end !== null && run.start - stopped.end <= 1 && (!r || !r.last || r.oks === 0) && (!l || l.fails === 0)) {
    // just restarted (no back-off): say why, until the new container is Ready or fails again
    story = `${stopped.endReason === 'Error' ? 'The process exited with code 1' : `The ${killer(stopped.endReason)} failed ${cfg[stopped.endReason as ProbeKind].failureThreshold} times in a row${stopped.endReason === 'liveness' && cfg.app.livenessChecksDependency && cfg.app.dependencyDown && stopped.end >= cfg.app.dependencyDown.from && stopped.end < cfg.app.dependencyDown.to ? ' (database down)' : ''}`}, so the kubelet killed and restarted the container (restart ${st.restarts}). The new container starts NotReady: no traffic until /ready passes.`
  } else if (s && run.startedAt === null) {
    story = `Startup probe: ${s.last ? (s.last.ok ? 'passed' : `failing (${s.cause}), ${s.fails} of ${s.threshold}`) : 'not run yet'}. Liveness and readiness wait until it passes; the pod gets no traffic yet.`
  } else if (!ready) {
    if (r && r.last && !r.last.ok)
      story =
        `/ready answers ${r.last.detail.includes('503') ? '503' : 'nothing'} (${r.cause}), ${Math.min(r.fails, r.threshold)} of ${r.threshold} failures${r.fails >= r.threshold ? ': the pod is NotReady and the Service sends it no traffic.' : ': not Ready yet, so no traffic.'}` +
        (l && l.fails > 0 ? ` /healthz fails too (${l.cause}), ${l.fails} of ${l.threshold}: at ${l.threshold} the kubelet kills the container.` : r.fails >= r.threshold ? ' The container keeps running: a readiness failure never restarts it.' : '')
    else story = 'The container is running but not Ready yet: no Service traffic until /ready passes.'
  } else if (l && l.fails > 0) {
    story = `/healthz is failing (${l.cause}), ${l.fails} of ${l.threshold}: at ${l.threshold} the kubelet kills and restarts the container.`
  } else if (r && r.fails > 0) {
    story = `/ready failed (${r.cause}), ${r.fails} of ${r.threshold}: still Ready until ${r.threshold} failures in a row.`
  } else {
    const back = tl.ready.filter((x) => x.from <= t).slice(-1)[0]
    const recovered = back && tl.ready.some((x) => x.to <= back.from) && t - back.from < 30
    story = recovered
      ? `/ready passes again${db === 'up' && cfg.app.dependencyDown ? ' now the database is back' : ''}: Ready since ${back.from}s, and the Service sends traffic to the pod again.`
      : 'Probes pass: the pod is Ready, listed in the EndpointSlice as ready, and receives Service traffic.'
  }
  return { t, database: db, probes, container: { state, run: run ? run.index : null, uptime: run ? t - run.start : null, backoffLeft: wait ? wait.to - t : null, lastStop: stopped ? stopped.endReason : null }, ready, traffic, story }
}

// =====================================================================================================
// Request path: Route → Service → EndpointSlice → Pod, with NetworkPolicy
// Docs: https://kubernetes.io/docs/concepts/services-networking/service/
//       https://kubernetes.io/docs/concepts/services-networking/endpoint-slices/
//       https://kubernetes.io/docs/concepts/services-networking/network-policies/
//       https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/ingress_and_load_balancing/routes
// Behaviour modelled: a Service selects pods by labels; the EndpointSlice lists every selected pod with its
// ready condition and the resolved targetPort (a named targetPort is looked up in each pod's container
// ports); only ready endpoints receive traffic; the OpenShift router (HAProxy) sends traffic straight to
// endpoint IPs, filtered by the Route's spec.port.targetPort (matched against the endpoint port *name or
// number*), and answers 503 itself when no endpoint works; a client pod goes through the Service ClusterIP,
// which rejects when there is no ready endpoint (connection refused) and load-balances otherwise; a pod not
// listening on the port resets the connection (refused); NetworkPolicy drops disallowed packets (timeout).
// Simplifications: one namespace ("shop"), one Service port, TCP/HTTP only, HTTP route (no TLS),
// deterministic endpoint choice (real choice is random), timing of retries and timeouts not modelled.
// =====================================================================================================

export type TrafficPod = { name: string; app: string; ready: boolean; listenPort: number }
export type NetPolicyMode = 'none' | 'deny-all' | 'allow-same-namespace' | 'allow-from-router' | 'allow-router-and-namespace'
export type TrafficConfig = {
  routeHost: string
  routeService: string
  /** Route spec.port.targetPort: '' (unset), a port name or a number */
  routeTargetPort: string
  serviceName: string
  selectorApp: string
  servicePort: number
  servicePortName: string
  /** Service targetPort: a number or a container port name */
  targetPort: string
  /** named container port every pod declares (documentation unless referenced by name) */
  containerPortName: string
  containerPort: number
  pods: TrafficPod[]
  policy: NetPolicyMode
  /** host the external client asks for */
  requestHost: string
  /** host and port in the client pod's curl URL */
  clientHost: string
  clientPort: number
}
export type HopStatus = 'ok' | 'fail' | 'warn' | 'skip'
export type Hop = { id: 'client' | 'dns' | 'router' | 'route' | 'service' | 'endpoints' | 'policy' | 'pod'; label: string; status: HopStatus; detail: string }
export type TrafficResult = {
  from: 'router' | 'client'
  hops: Hop[]
  ok: boolean
  failedAt: Hop['id'] | null
  command: string
  output: string
  exitCode: number
  httpStatus: number | null
  symptom: string
  explanation: string
  endpoint: string | null
}
export type Endpoint = { pod: string; ip: string; ready: boolean; port: number | null; portName: string }

export const NAMESPACE = 'shop'
export const APPS_DOMAIN = 'apps-crc.testing'
export const CLUSTER_IP = '10.217.4.92'
const podIp = (i: number) => `10.217.0.${21 + i}`

export const DEFAULT_TRAFFIC: TrafficConfig = {
  routeHost: `web-${NAMESPACE}.${APPS_DOMAIN}`,
  routeService: 'web',
  routeTargetPort: 'http',
  serviceName: 'web',
  selectorApp: 'web',
  servicePort: 80,
  servicePortName: 'http',
  targetPort: '8080',
  containerPortName: 'http',
  containerPort: 8080,
  pods: [
    { name: 'web-5d59d67564-k2x7p', app: 'web', ready: true, listenPort: 8080 },
    { name: 'web-5d59d67564-q9z4m', app: 'web', ready: true, listenPort: 8080 },
  ],
  policy: 'none',
  requestHost: `web-${NAMESPACE}.${APPS_DOMAIN}`,
  clientHost: 'web',
  clientPort: 80,
}

/** What the EndpointSlice controller publishes for the Service. */
export function endpointSlice(cfg: TrafficConfig): { endpoints: Endpoint[]; portLabel: string } {
  const numeric = /^\d+$/.test(cfg.targetPort.trim())
  const endpoints = cfg.pods
    .map((p, i) => ({ p, i }))
    .filter(({ p }) => p.app === cfg.selectorApp)
    .map(({ p, i }) => {
      let port: number | null = null
      if (numeric) port = Number(cfg.targetPort)
      else if (cfg.targetPort.trim() === cfg.containerPortName) port = cfg.containerPort
      return { pod: p.name, ip: podIp(i), ready: p.ready, port, portName: cfg.servicePortName }
    })
  return { endpoints, portLabel: numeric ? cfg.targetPort : `${cfg.targetPort} → ${endpoints.find((e) => e.port !== null)?.port ?? 'unresolved'}` }
}

const routerAllowed = (m: NetPolicyMode) => m === 'none' || m === 'allow-from-router' || m === 'allow-router-and-namespace'
const namespaceAllowed = (m: NetPolicyMode) => m === 'none' || m === 'allow-same-namespace' || m === 'allow-router-and-namespace'

export const POLICY_TEXT: Record<NetPolicyMode, string> = {
  none: 'no NetworkPolicy selects the web pods: all ingress allowed',
  'deny-all': 'deny-by-default: podSelector {} with no ingress rules',
  'allow-same-namespace': 'allow ingress from pods in namespace shop only',
  'allow-from-router': 'allow ingress only from namespaces labelled policy-group.network.openshift.io/ingress (the router)',
  'allow-router-and-namespace': 'allow ingress from the router and from pods in namespace shop',
}

const ROUTER_503 = '503 (HAProxy page "Application is not available")'

export function sendRequest(cfg: TrafficConfig, from: 'router' | 'client', attempt = 0): TrafficResult {
  return from === 'router' ? viaRouter(cfg) : viaClient(cfg, attempt)
}

function viaRouter(cfg: TrafficConfig): TrafficResult {
  const hops: Hop[] = []
  const command = `curl -sS -o /dev/null -w '%{http_code}\\n' http://${cfg.requestHost}/`
  const done = (failedAt: Hop['id'] | null, httpStatus: number | null, exitCode: number, output: string, symptom: string, explanation: string, endpoint: string | null = null): TrafficResult => {
    const ids: Hop['id'][] = ['client', 'dns', 'router', 'route', 'service', 'endpoints', 'policy', 'pod']
    const labels: Record<string, string> = { client: 'Browser / curl', dns: 'DNS', router: 'Router (HAProxy)', route: 'Route', service: 'Service', endpoints: 'EndpointSlice', policy: 'NetworkPolicy', pod: 'Pod' }
    for (const id of ids) if (!hops.some((h) => h.id === id)) hops.push({ id, label: labels[id], status: 'skip', detail: 'not reached' })
    hops.sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id))
    return { from: 'router', hops, ok: failedAt === null && httpStatus === 200, failedAt, command, output, exitCode, httpStatus, symptom, explanation, endpoint }
  }
  hops.push({ id: 'client', label: 'Browser / curl', status: 'ok', detail: `GET http://${cfg.requestHost}/` })
  if (!cfg.requestHost.endsWith('.' + APPS_DOMAIN)) {
    hops.push({ id: 'dns', label: 'DNS', status: 'fail', detail: `${cfg.requestHost} is not under the wildcard *.${APPS_DOMAIN}` })
    return done('dns', null, 6, `000\ncurl: (6) Could not resolve host: ${cfg.requestHost}`, 'DNS failure (curl exit 6)', 'The name never resolves, so no packet reaches the cluster. Route hosts must sit under the apps domain (or have their own DNS record).')
  }
  hops.push({ id: 'dns', label: 'DNS', status: 'ok', detail: `*.${APPS_DOMAIN} → router` })
  hops.push({ id: 'router', label: 'Router (HAProxy)', status: 'ok', detail: `looks up a Route for host ${cfg.requestHost}` })
  if (cfg.routeHost !== cfg.requestHost) {
    hops.push({ id: 'route', label: 'Route', status: 'fail', detail: `no Route has host ${cfg.requestHost} (Route host is ${cfg.routeHost})` })
    return done('route', 503, 0, '503', `Router ${ROUTER_503}`, 'DNS sent the request to the router, but no Route claims this host, so the router answers from its default backend.')
  }
  hops.push({ id: 'route', label: 'Route', status: 'ok', detail: `host ${cfg.routeHost} → service ${cfg.routeService}${cfg.routeTargetPort ? `, targetPort ${cfg.routeTargetPort}` : ''}` })
  if (cfg.routeService !== cfg.serviceName) {
    hops.push({ id: 'service', label: 'Service', status: 'fail', detail: `service "${cfg.routeService}" does not exist (the Service is "${cfg.serviceName}")` })
    return done('service', 503, 0, '503', `Router ${ROUTER_503}`, 'The Route points to a Service that does not exist, so the router has no endpoints for this backend.')
  }
  const slice = endpointSlice(cfg)
  hops.push({ id: 'service', label: 'Service', status: 'ok', detail: `selector app=${cfg.selectorApp}; the router reads its EndpointSlice (it does not use the ClusterIP)` })
  if (slice.endpoints.length === 0) {
    hops.push({ id: 'endpoints', label: 'EndpointSlice', status: 'fail', detail: `no pod has label app=${cfg.selectorApp}: the slice is empty` })
    return done('endpoints', 503, 0, '503', `Router ${ROUTER_503}`, 'The Service selector matches no pod, so its EndpointSlice is empty and the router has nowhere to send the request.')
  }
  const usable = slice.endpoints.filter((e) => e.ready && e.port !== null)
  if (usable.length === 0) {
    const why = slice.endpoints.every((e) => !e.ready) ? 'every selected pod is NotReady (listed with ready: false)' : `targetPort "${cfg.targetPort}" does not resolve on the selected pods`
    hops.push({ id: 'endpoints', label: 'EndpointSlice', status: 'fail', detail: why })
    return done('endpoints', 503, 0, '503', `Router ${ROUTER_503}`, 'Pods are selected but none can serve: only ready endpoints with a resolved port receive traffic.')
  }
  const byRoute = cfg.routeTargetPort.trim() === '' ? usable : usable.filter((e) => e.portName === cfg.routeTargetPort.trim() || String(e.port) === cfg.routeTargetPort.trim())
  if (byRoute.length === 0) {
    hops.push({ id: 'endpoints', label: 'EndpointSlice', status: 'fail', detail: `Route targetPort "${cfg.routeTargetPort}" matches no endpoint port (endpoints expose name "${cfg.servicePortName}", port ${usable[0].port})` })
    return done('endpoints', 503, 0, '503', `Router ${ROUTER_503}`, "The Route's targetPort is compared with the endpoint port name or the endpoint (target) port number, not the Service port. Nothing matches, so the router has no server for this route.")
  }
  hops.push({ id: 'endpoints', label: 'EndpointSlice', status: 'ok', detail: `${byRoute.length} ready endpoint(s): ${byRoute.map((e) => `${e.ip}:${e.port}`).join(', ')}` })
  if (!routerAllowed(cfg.policy)) {
    hops.push({ id: 'policy', label: 'NetworkPolicy', status: 'fail', detail: `${POLICY_TEXT[cfg.policy]} → packets from the router are dropped` })
    return done('policy', 503, 0, '503', `Router ${ROUTER_503}, after its connect timeout`, 'The router cannot connect to any endpoint because a NetworkPolicy drops its packets. HAProxy gives up after its connect timeout and answers 503, which hides the real cause.')
  }
  hops.push({ id: 'policy', label: 'NetworkPolicy', status: 'ok', detail: POLICY_TEXT[cfg.policy] })
  const pods = byRoute.map((e) => ({ e, p: cfg.pods.find((p) => p.name === e.pod) as TrafficPod }))
  const listening = pods.filter(({ e, p }) => p.listenPort === e.port)
  if (listening.length === 0) {
    hops.push({ id: 'pod', label: 'Pod', status: 'fail', detail: `the process listens on ${pods[0].p.listenPort}, the endpoint port is ${pods[0].e.port}: connection refused` })
    return done('pod', 503, 0, '503', `Router ${ROUTER_503}`, 'Every endpoint refuses the connection because nothing listens on the endpoint port. The router reports it as 503.')
  }
  if (listening.length < pods.length) {
    hops.push({ id: 'pod', label: 'Pod', status: 'warn', detail: `${pods.length - listening.length} endpoint(s) refuse connections; HAProxy retries another server, so users see slow or occasional failures` })
    return done(null, 200, 0, '200', '200 OK (some endpoints are broken)', 'The router redispatches failed connections to another endpoint, so this works, but part of the backend is broken.', listening[0].p.name)
  }
  hops.push({ id: 'pod', label: 'Pod', status: 'ok', detail: `${listening[0].p.name} answers on ${listening[0].e.port}` })
  return done(null, 200, 0, '200', '200 OK', 'Every hop works: DNS → router → Route → ready endpoint → listening pod.', listening[0].p.name)
}

function viaClient(cfg: TrafficConfig, attempt: number): TrafficResult {
  const hops: Hop[] = []
  const command = `oc exec deploy/toolbox -n ${NAMESPACE} -- curl -sS -m 3 http://${cfg.clientHost}:${cfg.clientPort}/`
  const ids: Hop['id'][] = ['client', 'dns', 'service', 'endpoints', 'policy', 'pod']
  const labels: Record<string, string> = { client: 'Client pod (toolbox)', dns: 'Cluster DNS', service: 'Service ClusterIP', endpoints: 'EndpointSlice', policy: 'NetworkPolicy', pod: 'Pod' }
  const done = (failedAt: Hop['id'] | null, exitCode: number, output: string, symptom: string, explanation: string, endpoint: string | null = null): TrafficResult => {
    for (const id of ids) if (!hops.some((h) => h.id === id)) hops.push({ id, label: labels[id], status: 'skip', detail: 'not reached' })
    hops.sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id))
    return { from: 'client', hops, ok: failedAt === null, failedAt, command, output: output + (exitCode ? `\ncommand terminated with exit code ${exitCode}` : ''), exitCode, httpStatus: failedAt === null ? 200 : null, symptom, explanation, endpoint }
  }
  hops.push({ id: 'client', label: labels.client, status: 'ok', detail: `pod toolbox in namespace ${NAMESPACE}` })
  const names = [cfg.serviceName, `${cfg.serviceName}.${NAMESPACE}`, `${cfg.serviceName}.${NAMESPACE}.svc`, `${cfg.serviceName}.${NAMESPACE}.svc.cluster.local`]
  if (!names.includes(cfg.clientHost)) {
    hops.push({ id: 'dns', label: labels.dns, status: 'fail', detail: `no Service named after "${cfg.clientHost}" in the search path → NXDOMAIN` })
    return done('dns', 6, `curl: (6) Could not resolve host: ${cfg.clientHost}`, 'DNS failure (curl exit 6)', 'Cluster DNS only knows Service names (<service>.<namespace>.svc.cluster.local). A typo in the host never reaches the network.')
  }
  hops.push({ id: 'dns', label: labels.dns, status: 'ok', detail: `${cfg.clientHost} → ${CLUSTER_IP}` })
  if (cfg.clientPort !== cfg.servicePort) {
    hops.push({ id: 'service', label: labels.service, status: 'fail', detail: `the Service only exposes port ${cfg.servicePort}; nothing load-balances ${CLUSTER_IP}:${cfg.clientPort}` })
    return done('service', 28, 'curl: (28) Connection timed out after 3000 milliseconds', 'Timeout (curl exit 28)', 'The ClusterIP is virtual: only the ports the Service declares are load-balanced. Packets to any other port are typically dropped, so the client times out (exact behaviour depends on the network plugin).')
  }
  const slice = endpointSlice(cfg)
  const usable = slice.endpoints.filter((e) => e.ready && e.port !== null)
  hops.push({ id: 'service', label: labels.service, status: 'ok', detail: `${CLUSTER_IP}:${cfg.servicePort} → targetPort ${cfg.targetPort}` })
  if (usable.length === 0) {
    const why = slice.endpoints.length === 0 ? `selector app=${cfg.selectorApp} matches no pod` : slice.endpoints.every((e) => !e.ready) ? 'all selected pods are NotReady' : `targetPort "${cfg.targetPort}" does not resolve on the pods`
    hops.push({ id: 'endpoints', label: labels.endpoints, status: 'fail', detail: `${why}: no ready endpoint, so the ClusterIP rejects the connection` })
    return done('endpoints', 7, `curl: (7) Failed to connect to ${cfg.clientHost} port ${cfg.clientPort}: Connection refused`, 'Connection refused (curl exit 7)', 'A Service with no ready endpoints rejects connections (OVN-Kubernetes and kube-proxy both answer with a reject), so the client sees "connection refused" immediately.')
  }
  const e = usable[attempt % usable.length]
  hops.push({ id: 'endpoints', label: labels.endpoints, status: 'ok', detail: `picked ${e.ip}:${e.port} of ${usable.length} ready endpoint(s) (the real choice is random; this model rotates)` })
  if (!namespaceAllowed(cfg.policy)) {
    hops.push({ id: 'policy', label: labels.policy, status: 'fail', detail: `${POLICY_TEXT[cfg.policy]} → packets from toolbox are dropped` })
    return done('policy', 28, 'curl: (28) Connection timed out after 3000 milliseconds', 'Timeout (curl exit 28)', 'NetworkPolicy drops packets silently: no reset, no ICMP. The TCP handshake never completes and curl gives up after -m 3.')
  }
  hops.push({ id: 'policy', label: labels.policy, status: 'ok', detail: POLICY_TEXT[cfg.policy] })
  const pod = cfg.pods.find((p) => p.name === e.pod) as TrafficPod
  if (pod.listenPort !== e.port) {
    hops.push({ id: 'pod', label: labels.pod, status: 'fail', detail: `${pod.name} listens on ${pod.listenPort}, not ${e.port}: the kernel answers with a TCP reset` })
    return done('pod', 7, `curl: (7) Failed to connect to ${cfg.clientHost} port ${cfg.clientPort}: Connection refused`, 'Connection refused (curl exit 7)', 'The packet reached the pod, but nothing listens on the targetPort, so the connection is reset. Note the message names the Service port, not the port that is wrong.', pod.name)
  }
  hops.push({ id: 'pod', label: labels.pod, status: 'ok', detail: `${pod.name} answers on ${e.port}` })
  return done(null, 0, '<h1>payments portal</h1>', '200 OK', 'Every hop works: DNS → ClusterIP → ready endpoint → listening pod.', pod.name)
}

// =====================================================================================================
// RBAC authorization
// Docs: https://kubernetes.io/docs/reference/access-authn-authz/rbac/
//       https://kubernetes.io/docs/reference/access-authn-authz/authentication/#users-in-kubernetes (virtual groups)
//       https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/authentication_and_authorization/using-rbac
// Behaviour modelled: permissions are purely additive (the union of every rule reachable through a binding
// whose subjects include the user, one of its groups or its ServiceAccount); there are no deny rules; a
// RoleBinding grants only inside its own namespace, even when it references a ClusterRole; a ClusterRoleBinding
// grants in every namespace and on cluster-scoped resources; a RoleBinding can only reference a Role in its
// own namespace, and a ClusterRoleBinding only a ClusterRole (the API server rejects anything else); listing
// a namespaced resource across all namespaces needs a ClusterRoleBinding; rule matching
// follows rbac/v1 helpers ('*' wildcards, "pods" does not cover "pods/log", "*/log" does, resourceNames).
// Simplifications: built-in roles are abbreviated (the real ones are aggregated and much longer); no
// aggregation, escalation/bind checks, non-resource URLs, impersonation or webhook/Node authorizers.
// =====================================================================================================

export type Rule = { apiGroups: string[]; resources: string[]; verbs: string[]; resourceNames?: string[] }
export type Role = { kind: 'Role' | 'ClusterRole'; name: string; namespace?: string; rules: Rule[]; note?: string }
export type Subject = { kind: 'User' | 'Group' | 'ServiceAccount'; name: string; namespace?: string }
export type Binding = { kind: 'RoleBinding' | 'ClusterRoleBinding'; name: string; namespace?: string; roleRef: { kind: 'Role' | 'ClusterRole'; name: string }; subjects: Subject[]; enabled: boolean; builtin?: boolean }
export type Identity = { id: string; kind: 'User' | 'ServiceAccount'; name: string; namespace?: string; extraGroups: string[] }
export type ResourceDef = { resource: string; group: string; namespaced: boolean; label: string }
export type AccessQuery = { identity: Identity; verb: string; resource: ResourceDef; namespace: string | null; name?: string }
export type GrantPath = { binding: Binding; role: Role; ruleIndex: number; via: string; scope: string }
export type NearMiss = { binding: Binding; why: string }
export type AccessResult = { allowed: boolean; paths: GrantPath[]; nearMisses: NearMiss[]; username: string; groups: string[]; command: string; invalid?: string }

export const RBAC_RESOURCES: ResourceDef[] = [
  { resource: 'pods', group: '', namespaced: true, label: 'pods' },
  { resource: 'pods/log', group: '', namespaced: true, label: 'pods/log' },
  { resource: 'pods/exec', group: '', namespaced: true, label: 'pods/exec' },
  { resource: 'deployments', group: 'apps', namespaced: true, label: 'deployments.apps' },
  { resource: 'secrets', group: '', namespaced: true, label: 'secrets' },
  { resource: 'configmaps', group: '', namespaced: true, label: 'configmaps' },
  { resource: 'rolebindings', group: 'rbac.authorization.k8s.io', namespaced: true, label: 'rolebindings.rbac.authorization.k8s.io' },
  { resource: 'imagestreams/layers', group: 'image.openshift.io', namespaced: true, label: 'imagestreams/layers (image pull)' },
  { resource: 'nodes', group: '', namespaced: false, label: 'nodes (cluster-scoped)' },
  { resource: 'projectrequests', group: 'project.openshift.io', namespaced: false, label: 'projectrequests (new project)' },
]
export const RBAC_VERBS = ['get', 'list', 'watch', 'create', 'update', 'patch', 'delete']
export const RBAC_NAMESPACES = ['team-a', 'team-b']

const READ = ['get', 'list', 'watch']
const WRITE = ['create', 'update', 'patch', 'delete', 'deletecollection']
export const RBAC_ROLES: Role[] = [
  {
    kind: 'ClusterRole',
    name: 'view',
    note: 'abbreviated: the real role is aggregated from many rules',
    rules: [
      { apiGroups: [''], resources: ['pods', 'pods/log', 'services', 'endpoints', 'configmaps', 'persistentvolumeclaims'], verbs: READ },
      { apiGroups: ['apps'], resources: ['deployments', 'replicasets', 'statefulsets'], verbs: READ },
      // OpenShift aggregates the registry rules into view: anyone who can view a project can pull its images
      { apiGroups: ['image.openshift.io', ''], resources: ['imagestreams/layers'], verbs: ['get'] },
    ],
  },
  {
    kind: 'ClusterRole',
    name: 'edit',
    note: 'abbreviated; no access to Roles or RoleBindings',
    rules: [
      { apiGroups: [''], resources: ['pods', 'pods/log', 'services', 'endpoints', 'configmaps', 'secrets', 'persistentvolumeclaims'], verbs: [...READ, ...WRITE] },
      { apiGroups: [''], resources: ['pods/exec'], verbs: [...READ, ...WRITE] },
      { apiGroups: ['apps'], resources: ['deployments', 'replicasets', 'statefulsets'], verbs: [...READ, ...WRITE] },
      // OpenShift: pull (get) and push (update) the project's images
      { apiGroups: ['image.openshift.io', ''], resources: ['imagestreams/layers'], verbs: ['get', 'update'] },
    ],
  },
  {
    kind: 'ClusterRole',
    name: 'admin',
    note: 'abbreviated: edit plus Roles and RoleBindings in the namespace',
    rules: [
      { apiGroups: [''], resources: ['pods', 'pods/log', 'services', 'endpoints', 'configmaps', 'secrets', 'persistentvolumeclaims'], verbs: [...READ, ...WRITE] },
      { apiGroups: [''], resources: ['pods/exec'], verbs: [...READ, ...WRITE] },
      { apiGroups: ['apps'], resources: ['deployments', 'replicasets', 'statefulsets'], verbs: [...READ, ...WRITE] },
      // OpenShift: pull (get) and push (update) the project's images
      { apiGroups: ['image.openshift.io', ''], resources: ['imagestreams/layers'], verbs: ['get', 'update'] },
      { apiGroups: ['rbac.authorization.k8s.io'], resources: ['roles', 'rolebindings'], verbs: [...READ, ...WRITE] },
    ],
  },
  { kind: 'ClusterRole', name: 'secret-reader', rules: [{ apiGroups: [''], resources: ['secrets'], verbs: ['get', 'list'] }] },
  { kind: 'ClusterRole', name: 'node-reader', rules: [{ apiGroups: [''], resources: ['nodes'], verbs: READ }] },
  { kind: 'ClusterRole', name: 'system:image-puller', note: 'OpenShift: pull images from a project', rules: [{ apiGroups: ['image.openshift.io', ''], resources: ['imagestreams/layers'], verbs: ['get'] }] },
  { kind: 'ClusterRole', name: 'self-provisioner', note: 'OpenShift: create projects', rules: [{ apiGroups: ['project.openshift.io', ''], resources: ['projectrequests'], verbs: ['create'] }] },
  { kind: 'Role', name: 'pod-reader', namespace: 'team-a', rules: [{ apiGroups: [''], resources: ['pods'], verbs: READ }] },
  { kind: 'Role', name: 'config-editor', namespace: 'team-b', rules: [{ apiGroups: [''], resources: ['configmaps'], verbs: ['get', 'update', 'patch'], resourceNames: ['app-settings'] }] },
]

export const RBAC_IDENTITIES: Identity[] = [
  { id: 'alice', kind: 'User', name: 'alice', extraGroups: ['developers', 'system:authenticated:oauth'] },
  { id: 'bob', kind: 'User', name: 'bob', extraGroups: ['auditors', 'system:authenticated:oauth'] },
  { id: 'sa-ci', kind: 'ServiceAccount', name: 'ci', namespace: 'team-a', extraGroups: [] },
  { id: 'sa-deployer', kind: 'ServiceAccount', name: 'deployer', namespace: 'team-a', extraGroups: [] },
  { id: 'sa-b-default', kind: 'ServiceAccount', name: 'default', namespace: 'team-b', extraGroups: [] },
  { id: 'sa-b-builder', kind: 'ServiceAccount', name: 'builder', namespace: 'team-b', extraGroups: [] },
]

export const RBAC_BINDINGS: Binding[] = [
  { kind: 'RoleBinding', name: 'admin', namespace: 'team-a', roleRef: { kind: 'ClusterRole', name: 'admin' }, subjects: [{ kind: 'User', name: 'alice' }], enabled: true, builtin: true },
  { kind: 'RoleBinding', name: 'view-developers', namespace: 'team-b', roleRef: { kind: 'ClusterRole', name: 'view' }, subjects: [{ kind: 'Group', name: 'developers' }], enabled: true },
  { kind: 'RoleBinding', name: 'ci-pod-reader', namespace: 'team-a', roleRef: { kind: 'Role', name: 'pod-reader' }, subjects: [{ kind: 'ServiceAccount', name: 'ci', namespace: 'team-a' }], enabled: true },
  { kind: 'RoleBinding', name: 'view-team-a-sas', namespace: 'team-a', roleRef: { kind: 'ClusterRole', name: 'view' }, subjects: [{ kind: 'Group', name: 'system:serviceaccounts:team-a' }], enabled: true },
  { kind: 'RoleBinding', name: 'deployer-edit', namespace: 'team-b', roleRef: { kind: 'ClusterRole', name: 'edit' }, subjects: [{ kind: 'ServiceAccount', name: 'deployer', namespace: 'team-a' }], enabled: true },
  { kind: 'RoleBinding', name: 'system:image-pullers', namespace: 'team-a', roleRef: { kind: 'ClusterRole', name: 'system:image-puller' }, subjects: [{ kind: 'Group', name: 'system:serviceaccounts:team-a' }], enabled: true, builtin: true },
  { kind: 'ClusterRoleBinding', name: 'auditors-secrets', roleRef: { kind: 'ClusterRole', name: 'secret-reader' }, subjects: [{ kind: 'Group', name: 'auditors' }], enabled: false },
  { kind: 'ClusterRoleBinding', name: 'self-provisioners', roleRef: { kind: 'ClusterRole', name: 'self-provisioner' }, subjects: [{ kind: 'Group', name: 'system:authenticated:oauth' }], enabled: true, builtin: true },
]

/** Username and groups the API server attaches to a request (including the virtual groups). */
export function userInfo(id: Identity): { username: string; groups: string[] } {
  if (id.kind === 'ServiceAccount') {
    return { username: `system:serviceaccount:${id.namespace}:${id.name}`, groups: ['system:serviceaccounts', `system:serviceaccounts:${id.namespace}`, 'system:authenticated'] }
  }
  return { username: id.name, groups: [...id.extraGroups, 'system:authenticated'] }
}

/** rbac/v1 VerbMatches / APIGroupMatches / ResourceMatches / ResourceNameMatches. */
export function ruleAllows(rule: Rule, verb: string, group: string, resource: string, name?: string): boolean {
  if (!rule.verbs.includes('*') && !rule.verbs.includes(verb)) return false
  if (!rule.apiGroups.includes('*') && !rule.apiGroups.includes(group)) return false
  const sub = resource.includes('/') ? resource.split('/')[1] : ''
  const resOk = rule.resources.some((r) => r === '*' || r === resource || (sub !== '' && r === `*/${sub}`))
  if (!resOk) return false
  if (rule.resourceNames && rule.resourceNames.length) return name !== undefined && rule.resourceNames.includes(name)
  return true
}

function subjectMatch(sub: Subject, username: string, groups: string[]): string | null {
  if (sub.kind === 'User' && sub.name === username) return `user ${username}`
  if (sub.kind === 'Group' && groups.includes(sub.name)) return `group ${sub.name}`
  if (sub.kind === 'ServiceAccount' && `system:serviceaccount:${sub.namespace}:${sub.name}` === username) return `ServiceAccount ${sub.namespace}/${sub.name}`
  return null
}

/** ValidateClusterRoleBinding (pkg/apis/rbac/validation): a ClusterRoleBinding may reference only a ClusterRole.
 * Returns the API server's refusal, or null when the binding is accepted. */
export function validateBinding(b: Pick<Binding, 'kind' | 'name' | 'roleRef'>): string | null {
  if (b.kind === 'ClusterRoleBinding' && b.roleRef.kind !== 'ClusterRole')
    return `The ClusterRoleBinding "${b.name}" is invalid: roleRef.kind: Unsupported value: "${b.roleRef.kind}": supported values: "ClusterRole"`
  return null
}

export function resolveRole(b: Binding, roles: Role[]): Role | null {
  if (b.roleRef.kind === 'ClusterRole') return roles.find((r) => r.kind === 'ClusterRole' && r.name === b.roleRef.name) || null
  return roles.find((r) => r.kind === 'Role' && r.name === b.roleRef.name && r.namespace === b.namespace) || null
}

export function canI(q: AccessQuery, bindings: Binding[], roles: Role[] = RBAC_ROLES): AccessResult {
  const { username, groups } = userInfo(q.identity)
  const ns = q.resource.namespaced ? q.namespace : null
  const scopeFlag = !q.resource.namespaced ? '' : ns ? ` -n ${ns}` : ' -A'
  const [base, sub] = q.resource.resource.split('/')
  const command = `oc auth can-i ${q.verb} ${base}${q.resource.group ? '.' + q.resource.group : ''}${q.name ? '/' + q.name : ''}${sub ? ` --subresource=${sub}` : ''}${scopeFlag} --as=${username}`
  const paths: GrantPath[] = []
  const nearMisses: NearMiss[] = []
  for (const b of bindings) {
    if (!b.enabled || validateBinding(b)) continue // the API server never stores an invalid binding
    const via = b.subjects.map((s) => subjectMatch(s, username, groups)).find((x) => x !== null) || null
    if (!via) continue
    const role = resolveRole(b, roles)
    if (!role) {
      nearMisses.push({ binding: b, why: `roleRef ${b.roleRef.kind} "${b.roleRef.name}" not found${b.roleRef.kind === 'Role' ? ` in namespace ${b.namespace}` : ''}: the binding grants nothing` })
      continue
    }
    if (b.kind === 'RoleBinding') {
      if (!q.resource.namespaced) {
        nearMisses.push({ binding: b, why: `a RoleBinding can never grant cluster-scoped resources like ${q.resource.resource}` })
        continue
      }
      if (ns === null) {
        nearMisses.push({ binding: b, why: `it only grants inside ${b.namespace}; listing across all namespaces needs a ClusterRoleBinding` })
        continue
      }
      if (b.namespace !== ns) {
        nearMisses.push({ binding: b, why: `it grants only in namespace ${b.namespace}${b.roleRef.kind === 'ClusterRole' ? ' (even though it references a ClusterRole)' : ''}` })
        continue
      }
    }
    const idx = role.rules.findIndex((r) => ruleAllows(r, q.verb, q.resource.group, q.resource.resource, q.name))
    if (idx < 0) {
      nearMisses.push({ binding: b, why: `${role.kind} ${role.name} has no rule for ${q.verb} on ${q.resource.resource}` })
      continue
    }
    paths.push({ binding: b, role, ruleIndex: idx, via, scope: b.kind === 'ClusterRoleBinding' ? 'cluster-wide' : `namespace ${b.namespace}` })
  }
  return { allowed: paths.length > 0, paths, nearMisses, username, groups, command }
}

export const ruleText = (r: Rule) =>
  `${r.verbs.join(',')} on ${r.resources.join(',')}${r.apiGroups.some((g) => g !== '') ? ` (${r.apiGroups.map((g) => g || 'core').join(',')})` : ''}${r.resourceNames ? ` named ${r.resourceNames.join(',')}` : ''}`

// ---- SCC admission (simplified)
// Docs: https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/authentication_and_authorization/managing-pod-security-policies
// Behaviour modelled: admission collects the SCCs the pod's ServiceAccount (for workload-created pods) may
// `use`, orders them by priority, then restrictiveness, then name (order below as observed on OpenShift
// 4.21), defaults unset fields from the SCC strategy, and admits the pod with the *first* SCC that validates
// every field; the choice is recorded in the openshift.io/scc annotation. Simplified: six SCCs with a few
// fields each (runAsUser, privileged, capabilities, hostNetwork, hostPath, hostUsers); no SELinux, fsGroup,
// supplemental groups, seccomp or volume types beyond hostPath; the real denial lists every SCC in the cluster.

export type SccName = 'anyuid' | 'restricted-v2' | 'restricted-v3' | 'nonroot-v2' | 'hostnetwork-v2' | 'privileged'
export type Scc = { name: SccName; priority: number; runAsUser: 'MustRunAsRange' | 'MustRunAsNonRoot' | 'RunAsAny'; range?: [number, number]; allowPrivileged: boolean; allowedCaps: string[] | '*'; hostNetwork: boolean; hostPath: boolean; requireHostUsersFalse?: boolean; defaultAccess: boolean }
export type PodSecuritySpec = { runAsUser: number | null; privileged: boolean; addCapability: '' | 'NET_BIND_SERVICE' | 'NET_ADMIN'; hostNetwork: boolean; hostPath: boolean; hostUsersFalse: boolean; imageUser: 'root' | '1001' }
export type SccVerdict = { scc: SccName; usable: boolean; errors: string[]; accepted: boolean }
export type SccResult = { admitted: SccName | null; verdicts: SccVerdict[]; message: string; effectiveUid: string; runtimeError: string | null }

export const NAMESPACE_UID_RANGE: [number, number] = [1000660000, 1000669999]
export const SCCS: Scc[] = [
  { name: 'anyuid', priority: 10, runAsUser: 'RunAsAny', allowPrivileged: false, allowedCaps: [], hostNetwork: false, hostPath: false, defaultAccess: false },
  { name: 'restricted-v2', priority: 0, runAsUser: 'MustRunAsRange', range: NAMESPACE_UID_RANGE, allowPrivileged: false, allowedCaps: ['NET_BIND_SERVICE'], hostNetwork: false, hostPath: false, defaultAccess: true },
  { name: 'restricted-v3', priority: 0, runAsUser: 'MustRunAsRange', range: [1000, 65534], allowPrivileged: false, allowedCaps: ['NET_BIND_SERVICE'], hostNetwork: false, hostPath: false, requireHostUsersFalse: true, defaultAccess: true },
  { name: 'nonroot-v2', priority: 0, runAsUser: 'MustRunAsNonRoot', allowPrivileged: false, allowedCaps: ['NET_BIND_SERVICE'], hostNetwork: false, hostPath: false, defaultAccess: false },
  { name: 'hostnetwork-v2', priority: 0, runAsUser: 'MustRunAsRange', range: NAMESPACE_UID_RANGE, allowPrivileged: false, allowedCaps: ['NET_BIND_SERVICE'], hostNetwork: true, hostPath: false, defaultAccess: false },
  { name: 'privileged', priority: 0, runAsUser: 'RunAsAny', allowPrivileged: true, allowedCaps: '*', hostNetwork: true, hostPath: true, defaultAccess: false },
]

export function admitPod(pod: PodSecuritySpec, granted: SccName[]): SccResult {
  const verdicts: SccVerdict[] = []
  let admitted: SccName | null = null
  for (const scc of SCCS) {
    const usable = scc.defaultAccess || granted.includes(scc.name)
    if (!usable) {
      verdicts.push({ scc: scc.name, usable, errors: ['Forbidden: not usable by user or serviceaccount'], accepted: false })
      continue
    }
    // pod-level checks first, then container-level ones (sccmatching/provider.go order)
    const errors: string[] = []
    if (pod.hostNetwork && !scc.hostNetwork) errors.push('.spec.securityContext.hostNetwork: Invalid value: true: Host network is not allowed to be used')
    if (scc.requireHostUsersFalse && !pod.hostUsersFalse) errors.push('.spec.securityContext.hostUsers: Invalid value: null: Host Users must be set to false')
    if (pod.hostPath && !scc.hostPath) errors.push('spec.volumes[0]: Invalid value: "hostPath": hostPath volumes are not allowed to be used')
    if (pod.runAsUser !== null) {
      if (scc.runAsUser === 'MustRunAsRange' && scc.range && (pod.runAsUser < scc.range[0] || pod.runAsUser > scc.range[1])) errors.push(`.containers[0].runAsUser: Invalid value: ${pod.runAsUser}: must be in the ranges: [${scc.range[0]}, ${scc.range[1]}]`)
      if (scc.runAsUser === 'MustRunAsNonRoot' && pod.runAsUser === 0) errors.push('.containers[0].runAsUser: Invalid value: 0: running with the root UID is forbidden')
    }
    if (pod.privileged && !scc.allowPrivileged) errors.push('.containers[0].privileged: Invalid value: true: Privileged containers are not allowed')
    if (pod.addCapability && scc.allowedCaps !== '*' && !scc.allowedCaps.includes(pod.addCapability)) errors.push(`.containers[0].capabilities.add: Invalid value: "${pod.addCapability}": capability may not be added`)
    if (pod.hostNetwork && !scc.hostNetwork) errors.push('.containers[0].hostNetwork: Invalid value: true: Host network is not allowed to be used')
    const accepted = errors.length === 0 && admitted === null
    verdicts.push({ scc: scc.name, usable, errors, accepted })
    if (errors.length === 0 && admitted === null) {
      admitted = scc.name
      break
    }
  }
  const scc = SCCS.find((x) => x.name === admitted)
  let effectiveUid = '-'
  let runtimeError: string | null = null
  if (scc) {
    if (pod.runAsUser !== null) effectiveUid = String(pod.runAsUser)
    else if (scc.runAsUser === 'MustRunAsRange' && scc.range) effectiveUid = `${scc.range[0]} (first UID of the range, set by admission)`
    else {
      effectiveUid = pod.imageUser === 'root' ? '0 (the image has no USER, so root)' : '1001 (the image USER)'
      if (scc.runAsUser === 'MustRunAsNonRoot' && pod.imageUser === 'root') runtimeError = 'Error: container has runAsNonRoot and image will run as root'
    }
  }
  const message = admitted
    ? `pod admitted; annotation openshift.io/scc: ${admitted}`
    : `Error creating: pods "web-6c966884bf-" is forbidden: unable to validate against any security context constraint: [${verdicts
        // volume errors are reported with a root field path, so they carry no "provider X:" prefix
        .map((v) => v.errors.map((e) => (e.startsWith('spec.volumes') ? e : `provider ${v.usable ? v.scc : `"${v.scc}"`}: ${e}`)).join(', '))
        .join(', ')}]`
  return { admitted, verdicts, message, effectiveUid, runtimeError }
}

// =====================================================================================================
// Persistent storage: PVC / PV / StorageClass
// Docs: https://kubernetes.io/docs/concepts/storage/persistent-volumes/
//       https://kubernetes.io/docs/concepts/storage/storage-classes/#volume-binding-mode
//       https://kubernetes.io/docs/concepts/storage/persistent-volumes/#storage-object-in-use-protection
//       https://kubernetes.io/docs/concepts/storage/persistent-volumes/#reserving-a-persistentvolume
// Behaviour modelled: Immediate provisions and binds as soon as the PVC exists, with no knowledge of where
// pods will run; WaitForFirstConsumer waits until a pod using the claim is scheduled and provisions in that
// node's zone; reclaimPolicy Delete removes the PV and the backend volume when the claim is deleted, Retain
// leaves the PV Released (claimRef kept, data kept, not reusable until an admin clears it); pvc-protection
// and pv-protection finalizers keep in-use objects Terminating; a pre-bound (reserved) PV binds to the claim
// it names; RWO volumes attach to one node, RWOP to one pod; block storage cannot provide RWX; a Released PV
// whose policy is patched to Delete is reclaimed (backend and PV deleted) by the provisioner; deleting a PV object
// whose policy is Delete also deletes its backend once it is no longer bound (external-provisioner finalizer,
// HonorPVReclaimPolicy, stable since Kubernetes 1.33), while a Retain volume's backend stays.
//       https://kubernetes.io/docs/concepts/storage/persistent-volumes/#persistentvolume-deletion-protection-finalizer
// Simplifications: one claim "data" of 10Gi on one zonal block StorageClass; two zones with two nodes each;
// the provisioner picks zone-b when it has no hint; attach/mount are instant; no expansion, snapshots,
// capacity tracking or static provisioning beyond re-using a released volume.
// =====================================================================================================

export type AccessMode = 'ReadWriteOnce' | 'ReadWriteOncePod' | 'ReadWriteMany'
export const ACCESS_SHORT: Record<AccessMode, string> = { ReadWriteOnce: 'RWO', ReadWriteOncePod: 'RWOP', ReadWriteMany: 'RWX' }
export type StorageClassCfg = { bindingMode: 'Immediate' | 'WaitForFirstConsumer'; reclaimPolicy: 'Delete' | 'Retain' }
export type StPVC = { name: string; uid: string; phase: 'Pending' | 'Bound'; volume: string | null; mode: AccessMode; terminating: boolean; reason: string }
export type StPV = { name: string; phase: 'Available' | 'Bound' | 'Released'; claimName: string | null; claimUid: string | null; reclaim: 'Delete' | 'Retain'; zone: string; backend: string; mode: AccessMode; terminating: boolean }
export type StBackend = { id: string; zone: string; files: string[]; deleted: boolean; attachedTo: string | null }
export type StPod = { name: string; node: string | null; phase: 'Pending' | 'ContainerCreating' | 'Running'; reason: string }
export type StLog = { n: number; who: 'you' | 'admin' | 'pv-controller' | 'external-provisioner' | 'scheduler' | 'kubelet' | 'attach-detach'; text: string }
export type StorageState = { sc: StorageClassCfg; mode: AccessMode; podZone: 'any' | 'zone-a' | 'zone-b'; pod2Node: 'same' | 'other'; pvc: StPVC | null; pvs: StPV[]; backends: StBackend[]; pods: StPod[]; log: StLog[]; seq: number; markers: string[] }

export const ST_NODES: { name: string; zone: string }[] = [
  { name: 'worker-a1', zone: 'zone-a' },
  { name: 'worker-a2', zone: 'zone-a' },
  { name: 'worker-b1', zone: 'zone-b' },
  { name: 'worker-b2', zone: 'zone-b' },
]
const zoneOf = (node: string) => ST_NODES.find((n) => n.name === node)?.zone || 'zone-a'

export function initialStorage(sc: StorageClassCfg, mode: AccessMode = 'ReadWriteOnce', podZone: StorageState['podZone'] = 'zone-a'): StorageState {
  return { sc, mode, podZone, pod2Node: 'other', pvc: null, pvs: [], backends: [], pods: [], log: [], seq: 0, markers: [] }
}

function cloneSt(s: StorageState): StorageState {
  return {
    ...s,
    sc: { ...s.sc },
    pvc: s.pvc ? { ...s.pvc } : null,
    pvs: s.pvs.map((p) => ({ ...p })),
    backends: s.backends.map((b) => ({ ...b, files: [...b.files] })),
    pods: s.pods.map((p) => ({ ...p })),
    log: [...s.log],
    markers: [...s.markers],
  }
}
const stLog = (s: StorageState, who: StLog['who'], text: string) => {
  const last = s.log[s.log.length - 1]
  if (last && last.who === who && last.text === text) return
  s.log.push({ n: s.log.length + 1, who, text })
}
const uid = (n: number) => `${(0x3f2a91c0 + n * 7919).toString(16)}-6c1d-4b8e-9a51-${(0x1a2b3c4d5e6f + n * 104729).toString(16).slice(0, 12)}`

function stProvision(s: StorageState, zone: string, why: string): StPV | null {
  const pvc = s.pvc as StPVC
  if (pvc.mode === 'ReadWriteMany') {
    pvc.reason = 'ProvisioningFailed'
    stLog(s, 'external-provisioner', `Warning ProvisioningFailed: failed to provision volume with StorageClass "zonal-block": rpc error: code = InvalidArgument desc = Volume capabilities not supported (block storage cannot be ReadWriteMany)`)
    return null
  }
  const name = `pvc-${pvc.uid}`
  const backend = `vol-0${(0xa3f19 + s.seq * 977).toString(16)}`
  s.seq++
  s.backends.push({ id: backend, zone, files: [], deleted: false, attachedTo: null })
  const pv: StPV = { name, phase: 'Bound', claimName: pvc.name, claimUid: pvc.uid, reclaim: s.sc.reclaimPolicy, zone, backend, mode: pvc.mode, terminating: false }
  s.pvs.push(pv)
  pvc.phase = 'Bound'
  pvc.volume = name
  pvc.reason = ''
  stLog(s, 'external-provisioner', `Normal ProvisioningSucceeded: Successfully provisioned volume ${name} (backend ${backend} in ${zone}; ${why})`)
  stLog(s, 'pv-controller', `PVC data Bound to ${name}; PV ${name} Bound`)
  return pv
}

/** Bind to a reserved or available matching PV before provisioning, as the PV controller does. */
function stBindExisting(s: StorageState, zoneHint: string | null): StPV | null {
  const pvc = s.pvc as StPVC
  const reserved = s.pvs.find((p) => p.phase === 'Available' && p.claimName === pvc.name && !p.terminating)
  const free = reserved || s.pvs.find((p) => p.phase === 'Available' && p.claimName === null && p.mode === pvc.mode && !p.terminating && (zoneHint === null || p.zone === zoneHint))
  if (!free) return null
  free.phase = 'Bound'
  free.claimName = pvc.name
  free.claimUid = pvc.uid
  pvc.phase = 'Bound'
  pvc.volume = free.name
  pvc.reason = ''
  stLog(s, 'pv-controller', `PVC data Bound to existing PV ${free.name}${reserved ? ' (it was reserved for this claim)' : ''}`)
  s.markers.push('bound-existing')
  return free
}

export function stCreatePVC(s0: StorageState): StorageState {
  if (s0.pvc) return s0
  const s = cloneSt(s0)
  s.pvc = { name: 'data', uid: uid(s.seq + 1), phase: 'Pending', volume: null, mode: s.mode, terminating: false, reason: '' }
  s.seq++
  stLog(s, 'you', `oc apply -f pvc.yaml → persistentvolumeclaim/data created (${ACCESS_SHORT[s.mode]}, 10Gi, storageClassName zonal-block)`)
  const reserved = s.pvs.find((p) => p.phase === 'Available' && p.claimName === 'data')
  if (reserved) stBindExisting(s, null)
  else if (s.sc.bindingMode === 'Immediate') {
    if (!stBindExisting(s, null)) stProvision(s, 'zone-b', 'Immediate: zone chosen without knowing where pods will run')
  } else {
    s.pvc.reason = 'WaitForFirstConsumer'
    stLog(s, 'pv-controller', 'Normal WaitForFirstConsumer: waiting for first consumer to be created before binding')
    s.markers.push('wffc-wait')
  }
  return stReconcilePods(s)
}

export function stCreatePod(s0: StorageState): StorageState {
  if (s0.pods.length >= 2) return s0
  const s = cloneSt(s0)
  const name = s.pods.length === 0 || s.pods[0].name !== 'app-1' ? 'app-1' : 'app-2'
  s.pods.push({ name, node: null, phase: 'Pending', reason: '' })
  stLog(s, 'you', `oc apply -f ${name}.yaml → pod/${name} created (volume from claim data${s.podZone !== 'any' ? `, nodeSelector zone=${s.podZone}` : ''})`)
  return stReconcilePods(s)
}

export function stDeletePod(s0: StorageState, name: string): StorageState {
  const s = cloneSt(s0)
  const pod = s.pods.find((p) => p.name === name)
  if (!pod) return s0
  s.pods = s.pods.filter((p) => p !== pod)
  stLog(s, 'you', `oc delete pod ${name}`)
  if (pod.node) {
    const stillUsed = s.pods.some((p) => p.node === pod.node && p.phase === 'Running')
    const pv = s.pvs.find((p) => p.name === s.pvc?.volume)
    const be = pv ? s.backends.find((b) => b.id === pv.backend) : undefined
    if (be && !stillUsed && be.attachedTo === pod.node) {
      be.attachedTo = null
      stLog(s, 'attach-detach', `volume ${pv?.name} unmounted and detached from ${pod.node}; data stays on ${be.id}`)
    }
  }
  return stSettle(s)
}

export function stDeletePVC(s0: StorageState): StorageState {
  if (!s0.pvc || s0.pvc.terminating) return s0
  const s = cloneSt(s0)
  const pvc = s.pvc as StPVC
  stLog(s, 'you', 'oc delete pvc data → persistentvolumeclaim "data" deleted')
  pvc.terminating = true
  s.markers.push('pvc-deleted')
  return stSettle(s)
}

export function stDeletePV(s0: StorageState, name: string): StorageState {
  const s = cloneSt(s0)
  const pv = s.pvs.find((p) => p.name === name)
  if (!pv || pv.terminating) return s0
  stLog(s, 'you', `oc delete pv ${name}`)
  pv.terminating = true
  return stSettle(s)
}

/** Admin: `oc patch pv <name> -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'`. Only this PV changes; the StorageClass keeps its policy. */
export function stPatchReclaim(s0: StorageState, name: string, policy: 'Delete' | 'Retain'): StorageState {
  const s = cloneSt(s0)
  const pv = s.pvs.find((p) => p.name === name)
  if (!pv || pv.reclaim === policy) return s0
  pv.reclaim = policy
  stLog(s, 'admin', `oc patch pv ${name} -p '{"spec":{"persistentVolumeReclaimPolicy":"${policy}"}}'`)
  s.markers.push(`pv-reclaim-${policy}`)
  // the PV controller acts on a Released volume's policy at its next sync: Delete hands it to the provisioner
  if (pv.phase === 'Released' && policy === 'Delete' && !pv.terminating) stReclaimDelete(s, pv, 'reclaimPolicy is now Delete on a Released volume')
  return s
}

/** The provisioner deletes the backend volume, then the PV object. The data is gone. */
function stReclaimDelete(s: StorageState, pv: StPV, why: string) {
  const be = s.backends.find((b) => b.id === pv.backend)
  if (be) {
    be.deleted = true
    be.files = []
    be.attachedTo = null
  }
  s.pvs = s.pvs.filter((p) => p !== pv)
  stLog(s, 'external-provisioner', `${why}: backend volume ${pv.backend} deleted, then PV ${pv.name}. The data is gone.`)
  s.markers.push('data-deleted')
}

/** Admin: remove claimRef.uid from a Released PV; it becomes Available, reserved for a claim named "data". */
export function stReservePV(s0: StorageState, name: string): StorageState {
  const s = cloneSt(s0)
  const pv = s.pvs.find((p) => p.name === name)
  if (!pv || pv.phase !== 'Released' || pv.terminating) return s0
  pv.phase = 'Available'
  pv.claimUid = null
  stLog(s, 'admin', `oc patch pv ${name} --type=json -p '[{"op":"remove","path":"/spec/claimRef/uid"}]' → Available, reserved for claim shop/data`)
  s.markers.push('pv-reserved')
  return s
}

const stSettle = (s: StorageState) => stReconcilePods(stFinalize(s))

/** Remove finalizer-protected objects once nothing protects them, and apply the reclaim policy. */
function stFinalize(s: StorageState): StorageState {
  const pvc = s.pvc
  if (pvc && pvc.terminating) {
    const users = s.pods.filter((p) => p.node !== null || p.phase !== 'Pending')
    if (users.length) {
      if (!pvc.reason.startsWith('Terminating')) stLog(s, 'pv-controller', `PVC data stays Terminating: finalizer kubernetes.io/pvc-protection, still used by pod(s) ${users.map((p) => p.name).join(', ')}`)
      pvc.reason = 'Terminating (in use)'
      return s
    }
    s.pvc = null
    stLog(s, 'pv-controller', 'PVC data removed (no pod uses it any more)')
    const pv = s.pvs.find((p) => p.name === pvc.volume)
    if (pv) {
      if (pv.reclaim === 'Delete') stReclaimDelete(s, pv, 'reclaimPolicy Delete')
      else {
        pv.phase = 'Released'
        stLog(s, 'pv-controller', `reclaimPolicy Retain: PV ${pv.name} is Released (claimRef still points to the deleted claim, data kept on ${pv.backend})`)
        s.markers.push('pv-released')
      }
    }
  }
  for (const pv of [...s.pvs]) {
    if (!pv.terminating) continue
    const boundToLiveClaim = pv.phase === 'Bound' && s.pvc !== null && s.pvc.volume === pv.name
    if (boundToLiveClaim) {
      stLog(s, 'pv-controller', `PV ${pv.name} stays Terminating: finalizer kubernetes.io/pv-protection while it is Bound`)
      continue
    }
    if (pv.reclaim === 'Delete') {
      // finalizer external-provisioner.volume.kubernetes.io/finalizer: the backend goes first, whatever the deletion order
      stReclaimDelete(s, pv, `PV ${pv.name} deleted with reclaimPolicy Delete (finalizer external-provisioner.volume.kubernetes.io/finalizer)`)
      continue
    }
    s.pvs = s.pvs.filter((p) => p !== pv)
    const be = s.backends.find((b) => b.id === pv.backend)
    stLog(s, 'pv-controller', `PV ${pv.name} deleted. Backend volume ${pv.backend} still exists on the storage system${be && be.files.length ? ' with its data' : ''}: deleting the PV object of a Retain volume never deletes the volume; an admin must clean it up.`)
    s.markers.push('pv-object-deleted')
  }
  return s
}

const failedSched = (reasons: string) => `Warning FailedScheduling: 0/${ST_NODES.length} nodes are available: ${reasons}`

/** Scheduler, binder and kubelet decisions for every pod (idempotent). */
function stReconcilePods(s: StorageState): StorageState {
  for (const pod of s.pods) {
    if (pod.phase === 'Running') continue
    const pvc = s.pvc
    if (!pod.node) {
      if (!pvc) {
        pod.reason = 'persistentvolumeclaim "data" not found'
        stLog(s, 'scheduler', failedSched('persistentvolumeclaim "data" not found.'))
        continue
      }
      if (pvc.terminating) {
        pod.reason = 'persistentvolumeclaim "data" is being deleted'
        stLog(s, 'scheduler', failedSched('persistentvolumeclaim "data" is being deleted.'))
        continue
      }
      const candidates = ST_NODES.filter((n) => s.podZone === 'any' || n.zone === s.podZone)
      if (pvc.phase === 'Pending' && s.sc.bindingMode === 'Immediate') {
        pod.reason = 'pod has unbound immediate PersistentVolumeClaims'
        stLog(s, 'scheduler', failedSched('pod has unbound immediate PersistentVolumeClaims.'))
        continue
      }
      let node: string | null = null
      if (pvc.phase === 'Bound') {
        const pv = s.pvs.find((p) => p.name === pvc.volume) as StPV
        const others = s.pods.filter((p) => p !== pod && p.node)
        if (pvc.mode === 'ReadWriteOncePod' && others.length) {
          pod.reason = 'ReadWriteOncePod claim already in use'
          stLog(s, 'scheduler', failedSched(`${ST_NODES.length} node(s) unavailable due to PersistentVolumeClaim with ReadWriteOncePod access mode already in-use by another pod.`))
          continue
        }
        const fit = candidates.filter((n) => n.zone === pv.zone)
        if (!fit.length) {
          const nAff = ST_NODES.length - candidates.length
          const parts = [nAff ? `${nAff} node(s) didn't match Pod's node affinity/selector` : '', `${candidates.length} node(s) didn't match PersistentVolume's node affinity`].filter(Boolean).sort()
          pod.reason = `volume node affinity conflict: the volume lives in ${pv.zone}`
          stLog(s, 'scheduler', failedSched(parts.join(', ') + '.'))
          s.markers.push('zone-conflict')
          continue
        }
        const first = others[0]
        if (pod.name === 'app-2' && first?.node) {
          const sameZone = fit.filter((n) => n.name !== first.node)
          node = s.pod2Node === 'same' || !sameZone.length ? first.node : sameZone[0].name
        } else node = fit[0].name
      } else {
        // WaitForFirstConsumer: the scheduler picks a node, then the claim is provisioned for that node's zone.
        node = candidates[0].name
        if (!stBindExisting(s, zoneOf(node))) {
          stLog(s, 'scheduler', `pod ${pod.name}: node ${node} selected; annotating claim with volume.kubernetes.io/selected-node=${node}`)
          if (!stProvision(s, zoneOf(node), `WaitForFirstConsumer: zone of node ${node}`)) {
            pod.reason = 'waiting for the claim to be provisioned'
            continue
          }
          s.markers.push('wffc-bound')
        }
      }
      pod.node = node
      stLog(s, 'scheduler', `Normal Scheduled: Successfully assigned shop/${pod.name} to ${node}`)
    }
    // kubelet + attach/detach controller
    const pv = s.pvs.find((p) => p.name === s.pvc?.volume)
    const be = pv ? s.backends.find((b) => b.id === pv.backend) : undefined
    if (!pv || !be) continue
    if (be.attachedTo && be.attachedTo !== pod.node && pv.mode !== 'ReadWriteMany') {
      pod.phase = 'ContainerCreating'
      const holder = s.pods.find((p) => p.node === be.attachedTo && p !== pod)
      pod.reason = 'Multi-Attach error'
      stLog(s, 'attach-detach', `Warning FailedAttachVolume: Multi-Attach error for volume "${pv.name}" Volume is already used by pod(s) ${holder?.name || 'another pod'}`)
      s.markers.push('multi-attach')
      continue
    }
    if (!be.attachedTo) stLog(s, 'attach-detach', `Normal SuccessfulAttachVolume: AttachVolume.Attach succeeded for volume "${pv.name}" (${be.id} → ${pod.node})`)
    be.attachedTo = pod.node
    pod.phase = 'Running'
    pod.reason = ''
    const fresh = !be.files.includes('orders.db')
    if (fresh) be.files.push('orders.db')
    stLog(s, 'kubelet', `${pod.name} Running on ${pod.node}; /data/orders.db ${fresh ? 'created (empty volume)' : 'found: the data survived'}`)
    if (!fresh) s.markers.push('data-survived')
    if (s.markers.includes('pvc-deleted') && !fresh) s.markers.push('data-recovered')
  }
  return s
}

export function storageSummary(s: StorageState) {
  const pv = s.pvc?.volume ? s.pvs.find((p) => p.name === s.pvc?.volume) || null : null
  return {
    pvcPhase: s.pvc ? (s.pvc.terminating ? 'Terminating' : s.pvc.phase) : 'absent',
    pv,
    orphanedBackends: s.backends.filter((b) => !b.deleted && !s.pvs.some((p) => p.backend === b.id)),
  }
}

// =====================================================================================================
// GitOps drift (Argo CD / OpenShift GitOps)
// Docs: https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/
//       https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/
//       https://kubernetes.io/docs/reference/kubectl/generated/kubectl_diff/
//       https://docs.redhat.com/en/documentation/red_hat_openshift_gitops/1.18
// Behaviour modelled: an Application compares the manifests at the Git revision with the live objects it
// tracks; a difference makes it OutOfSync; automated sync syncs once per new Git revision, and only with
// selfHeal does it also revert changes made directly in the cluster; resources removed from Git are deleted
// only when pruning is enabled (auto-prune, or prune on a manual sync), and a prune-only change is not
// auto-synced while auto-prune is off; objects without Argo CD's tracking annotation (or label, depending on
// the configured tracking method) are ignored; `oc diff -f` compares the files with the live objects and exits 1 when they differ.
// Application health is reported separately from sync status (a drifted but running app is OutOfSync and Healthy).
// Simplifications: three resources and a few fields; reconciliation happens when you press the button (real
// Argo CD watches the cluster continuously and polls Git every ~3 minutes); self-heal timeouts, retries,
// sync waves, hooks, health assessment details and ignoreDifferences are not modelled; the diff is abridged.
// =====================================================================================================

export type DriftKind = 'Deployment' | 'ConfigMap' | 'CronJob'
export type DriftRes = { kind: DriftKind; name: string; fields: Record<string, string> }
export type LiveRes = DriftRes & { tracked: boolean }
export type DriftPolicy = { automated: boolean; selfHeal: boolean; prune: boolean }
export type DriftLog = { n: number; who: 'you (Git)' | 'you (cluster)' | 'Argo CD'; text: string }
export type DriftState = { gitSha: string; git: DriftRes[]; commits: { sha: string; message: string }[]; live: LiveRes[]; policy: DriftPolicy; syncedSha: string | null; log: DriftLog[]; markers: string[] }
export type DriftRow = { kind: DriftKind; name: string; inGit: boolean; live: boolean; tracked: boolean; status: 'Synced' | 'OutOfSync' | 'Ignored'; health: 'Healthy' | 'Missing' | '-'; requiresPruning: boolean; diffs: { field: string; git: string | null; live: string | null }[] }

const SHAS = ['3f9a1c2', '8b41d07', 'c27e5fa', '51d9b3e', 'e06a7c4', '9d2f418', '47bc0e9', 'a8e3f61']
export const DRIFT_IMAGE = 'quay.io/acme/web:1.4.2'

export function initialDrift(policy: DriftPolicy): DriftState {
  const git: DriftRes[] = [
    { kind: 'Deployment', name: 'web', fields: { 'spec.replicas': '3', 'spec.template.spec.containers[0].image': DRIFT_IMAGE } },
    { kind: 'ConfigMap', name: 'web-config', fields: { 'data.LOG_LEVEL': 'info' } },
    { kind: 'CronJob', name: 'report', fields: { 'spec.schedule': '0 2 * * *' } },
  ]
  return {
    gitSha: SHAS[0],
    git,
    commits: [{ sha: SHAS[0], message: 'initial manifests' }],
    live: git.map((r) => ({ ...r, fields: { ...r.fields }, tracked: true })),
    policy,
    syncedSha: SHAS[0],
    log: [],
    markers: [],
  }
}

function cloneDrift(s: DriftState): DriftState {
  return { ...s, git: s.git.map((r) => ({ ...r, fields: { ...r.fields } })), commits: [...s.commits], live: s.live.map((r) => ({ ...r, fields: { ...r.fields } })), policy: { ...s.policy }, log: [...s.log], markers: [...s.markers] }
}
const dLog = (s: DriftState, who: DriftLog['who'], text: string) => s.log.push({ n: s.log.length + 1, who, text })
const key = (r: { kind: string; name: string }) => `${r.kind}/${r.name}`

export function driftRows(s: DriftState): DriftRow[] {
  const rows: DriftRow[] = []
  for (const g of s.git) {
    const l = s.live.find((x) => key(x) === key(g))
    const diffs = Object.keys(g.fields)
      .filter((f) => !l || l.fields[f] !== g.fields[f])
      .map((f) => ({ field: f, git: g.fields[f], live: l ? l.fields[f] ?? null : null }))
    rows.push({ kind: g.kind, name: g.name, inGit: true, live: !!l, tracked: true, status: diffs.length ? 'OutOfSync' : 'Synced', health: l ? 'Healthy' : 'Missing', requiresPruning: false, diffs })
  }
  for (const l of s.live) {
    if (s.git.some((g) => key(g) === key(l))) continue
    rows.push({ kind: l.kind, name: l.name, inGit: false, live: true, tracked: l.tracked, status: l.tracked ? 'OutOfSync' : 'Ignored', health: l.tracked ? 'Healthy' : '-', requiresPruning: l.tracked, diffs: [] })
  }
  return rows
}

export function appSyncStatus(s: DriftState): 'Synced' | 'OutOfSync' {
  return driftRows(s).some((r) => r.status === 'OutOfSync') ? 'OutOfSync' : 'Synced'
}

/** Application health, separate from sync status (controller/health.go): the worst health of the live objects the
 * Application tracks. A resource that is Missing from the cluster does not lower it (OutOfSync already reports
 * that); only when none of its objects exist is the Application Missing. Every live object here is Healthy, so a
 * drifted Application is OutOfSync and still Healthy. */
export function appHealth(s: DriftState): 'Healthy' | 'Missing' {
  return driftRows(s).some((r) => r.live && r.tracked) ? 'Healthy' : 'Missing'
}

/** `oc diff -f manifests/` against the live cluster: only the objects in the files are compared. */
export function ocDiff(s: DriftState): { exitCode: number; text: string } {
  const chunks: string[] = []
  for (const g of s.git) {
    const l = s.live.find((x) => key(x) === key(g))
    const file = `${g.kind === 'Deployment' ? 'apps.v1' : g.kind === 'CronJob' ? 'batch.v1' : 'v1'}.${g.kind}.shop.${g.name}`
    const lines: string[] = []
    for (const f of Object.keys(g.fields)) {
      const leaf = f.split('.').pop() as string
      if (!l) lines.push(`+  ${leaf}: ${g.fields[f]}`)
      else if (l.fields[f] !== g.fields[f]) lines.push(`-  ${leaf}: ${l.fields[f]}`, `+  ${leaf}: ${g.fields[f]}`)
    }
    if (lines.length) chunks.push([`diff -u -N /tmp/LIVE-1093/${file} /tmp/MERGED-2207/${file}`, `--- /tmp/LIVE-1093/${file}`, `+++ /tmp/MERGED-2207/${file}`, `@@ ${l ? f2path(Object.keys(g.fields)[0]) : 'new object'} @@`, ...lines].join('\n'))
  }
  return chunks.length ? { exitCode: 1, text: chunks.join('\n') } : { exitCode: 0, text: '' }
}
const f2path = (f: string) => f.split('.').slice(0, -1).join('.') || f

function commit(s: DriftState, message: string) {
  const sha = SHAS[s.commits.length % SHAS.length]
  s.gitSha = sha
  s.commits.push({ sha, message })
  dLog(s, 'you (Git)', `git commit -m "${message}" && git push → ${sha}`)
}

export function gitSetField(s0: DriftState, k: DriftKind, name: string, field: string, value: string, message: string): DriftState {
  const s = cloneDrift(s0)
  const r = s.git.find((x) => x.kind === k && x.name === name)
  if (!r || r.fields[field] === value) return s0
  r.fields[field] = value
  commit(s, message)
  s.markers.push('git:edit')
  return s
}
export function gitRemove(s0: DriftState, k: DriftKind, name: string): DriftState {
  const s = cloneDrift(s0)
  if (!s.git.some((x) => x.kind === k && x.name === name)) return s0
  s.git = s.git.filter((x) => !(x.kind === k && x.name === name))
  commit(s, `remove ${k.toLowerCase()} ${name}`)
  s.markers.push(`git:remove:${key({ kind: k, name })}`)
  return s
}
export function liveSetField(s0: DriftState, k: DriftKind, name: string, field: string, value: string, command: string): DriftState {
  const s = cloneDrift(s0)
  const r = s.live.find((x) => x.kind === k && x.name === name)
  if (!r || r.fields[field] === value) return s0
  r.fields[field] = value
  dLog(s, 'you (cluster)', command)
  s.markers.push(`live:edit:${field}`)
  return s
}
export function liveDelete(s0: DriftState, k: DriftKind, name: string): DriftState {
  const s = cloneDrift(s0)
  if (!s.live.some((x) => x.kind === k && x.name === name)) return s0
  s.live = s.live.filter((x) => !(x.kind === k && x.name === name))
  dLog(s, 'you (cluster)', `oc delete ${k.toLowerCase()} ${name}`)
  s.markers.push('live:delete')
  return s
}
export function liveCreateUntracked(s0: DriftState): DriftState {
  if (s0.live.some((x) => x.name === 'scratch')) return s0
  const s = cloneDrift(s0)
  s.live.push({ kind: 'ConfigMap', name: 'scratch', fields: { 'data.NOTE': 'temporary' }, tracked: false })
  dLog(s, 'you (cluster)', 'oc create configmap scratch --from-literal=NOTE=temporary (no Argo CD tracking annotation)')
  return s
}

function applySync(s: DriftState, prune: boolean, why: string) {
  const changes: string[] = []
  for (const g of s.git) {
    const l = s.live.find((x) => key(x) === key(g))
    if (!l) {
      s.live.push({ ...g, fields: { ...g.fields }, tracked: true })
      changes.push(`created ${key(g)}`)
    } else {
      const fixed = Object.keys(g.fields).filter((f) => l.fields[f] !== g.fields[f])
      for (const f of fixed) l.fields[f] = g.fields[f]
      if (fixed.length) changes.push(`${key(g)}: ${fixed.map((f) => f.split('.').pop()).join(', ')} set back to Git`)
    }
  }
  const extra = s.live.filter((l) => l.tracked && !s.git.some((g) => key(g) === key(l)))
  if (prune) {
    for (const e of extra) changes.push(`pruned ${key(e)}`)
    s.live = s.live.filter((l) => !extra.includes(l))
    if (extra.length) s.markers.push('pruned')
  } else if (extra.length) changes.push(`kept ${extra.map(key).join(', ')} (not in Git, prune disabled → still OutOfSync)`)
  s.syncedSha = s.gitSha
  dLog(s, 'Argo CD', `sync to ${s.gitSha} (${why}): ${changes.join('; ') || 'nothing to change'}`)
}

/** One reconciliation by the application controller (refresh + automated sync decision). */
export function argoReconcile(s0: DriftState): DriftState {
  const s = cloneDrift(s0)
  const rows = driftRows(s)
  const out = rows.filter((r) => r.status === 'OutOfSync')
  if (!out.length) {
    dLog(s, 'Argo CD', `refresh: Synced to ${s.gitSha}`)
    return s
  }
  const summary = out.map((r) => `${r.kind}/${r.name}${r.requiresPruning ? ' (requires pruning)' : r.health === 'Missing' ? ' (Missing)' : ''}`).join(', ')
  if (!s.policy.automated) {
    dLog(s, 'Argo CD', `refresh: OutOfSync (${summary}). Automated sync is off: waiting for a manual sync.`)
    return s
  }
  const newRevision = s.syncedSha !== s.gitSha
  const liveDrift = out.some((r) => r.inGit)
  if (!s.policy.prune && out.every((r) => r.requiresPruning)) {
    // controller/appcontroller.go autoSync: nothing but pruning to do and auto-prune is off → no sync, the
    // revision is not recorded as synced, so enabling prune later still syncs it
    dLog(s, 'Argo CD', `refresh: OutOfSync (${summary}). Skipping auto-sync: need to prune extra resources only but automated prune is disabled.`)
    s.markers.push('auto-sync-skipped')
    return s
  }
  if (newRevision) {
    applySync(s, s.policy.prune, `automated: new revision ${s.gitSha}`)
    if (s.markers.some((m) => m.startsWith('live:'))) s.markers.push('auto-sync-new-revision')
    return s
  }
  if (s.policy.selfHeal && (liveDrift || (s.policy.prune && out.some((r) => r.requiresPruning)))) {
    applySync(s, s.policy.prune, 'automated: self-heal, the cluster drifted from Git')
    s.markers.push('self-healed')
    return s
  }
  dLog(s, 'Argo CD', `refresh: OutOfSync (${summary}). Skipping auto-sync: most recent sync already to ${s.gitSha}${s.policy.selfHeal ? ' and nothing self-heal or prune may fix' : '; self-heal is off, so live changes stay'}.`)
  s.markers.push('auto-sync-skipped')
  return s
}

export function argoManualSync(s0: DriftState, prune: boolean): DriftState {
  const s = cloneDrift(s0)
  applySync(s, prune, prune ? 'manual, with prune' : 'manual')
  return s
}

export function setDriftPolicy(s0: DriftState, policy: DriftPolicy): DriftState {
  const s = cloneDrift(s0)
  s.policy = policy
  return s
}
