// Educational model of one kube-scheduler scheduling cycle (scheduling framework), Kubernetes 1.34 /
// OpenShift 4.21. It reproduces the real *structure* and, for the plugins it includes, the upstream
// formulas: Filter plugins remove infeasible nodes, Score plugins rate each feasible node 0-100,
// NormalizeScore rescales, each score is multiplied by the plugin weight and summed, the highest total wins
// (ties are broken at random by the real scheduler).
//
// Sources:
//  - Plugins and default weights: https://kubernetes.io/docs/reference/scheduling/config/#scheduling-plugins
//    and pkg/scheduler/apis/config/v1/default_plugins.go (TaintToleration 3, NodeAffinity 2,
//    PodTopologySpread 2, InterPodAffinity 2, NodeResourcesFit 1, NodeResourcesBalancedAllocation 1,
//    ImageLocality 1).
//  - NodeResourcesFit strategies: https://kubernetes.io/docs/concepts/scheduling-eviction/resource-bin-packing/
//  - Topology spread (incl. system default constraints):
//    https://kubernetes.io/docs/concepts/scheduling-eviction/topology-spread-constraints/
//  - OpenShift profiles: https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/nodes/controlling-pod-placement-onto-nodes-scheduling#nodes-scheduler-profiles
//    (operator config: HighNodeUtilization = NodeResourcesFit MostAllocated with weight 5 and
//    NodeResourcesBalancedAllocation disabled; NoScoring = every preScore/score plugin disabled).
//
// Simplifications (stated in the UI too): one container per pod; only cpu and memory; the pod belongs to
// one app ("app=payments") whose existing replicas are counted per node; required node affinity is one
// nodeSelectorTerm; no volumes, ports, DRA, extenders, priorities or preemption victims;
// percentageOfNodesToScore is irrelevant below 100 nodes. As in schedulePod, a single feasible node is chosen
// without running any score plugin. Every filter is evaluated for teaching, but the
// real scheduler stops at the first failing filter of a node and only that failure reaches the event.

export type Taint = { key: string; value?: string; effect: 'NoSchedule' | 'PreferNoSchedule' | 'NoExecute' }
export type Toleration = { key?: string; operator?: 'Equal' | 'Exists'; value?: string; effect?: string }
export type SimNode = {
  name: string
  zone: string
  cpu: number // millicores allocatable
  mem: number // MiB allocatable
  usedCpu: number // sum of requests of pods already bound to the node
  usedMem: number
  labels: Record<string, string>
  taints: Taint[]
  unschedulable?: boolean
  images?: string[]
  appPods?: number // pods of the same app (app=payments) already on the node
}
export type Term = { key: string; operator: 'In' | 'NotIn' | 'Exists' | 'DoesNotExist'; values?: string[] }
export type SpreadConstraint = { topologyKey: 'zone' | 'hostname'; maxSkew: number; when: 'DoNotSchedule' | 'ScheduleAnyway' }
export type SimPod = {
  cpu: number // millicores requested (0 = no request)
  mem: number // MiB requested (0 = no request)
  image: string
  nodeSelector: Record<string, string>
  required: Term[]
  preferred: { weight: number; term: Term }[]
  tolerations: Toleration[]
  spread?: SpreadConstraint
  /** @deprecated use podAntiAffinity: 'required' */
  antiAffinityHostname?: boolean
  /** pod anti-affinity against app=payments on kubernetes.io/hostname */
  podAntiAffinity?: 'none' | 'preferred' | 'required'
  /** owned by a ReplicaSet/Service: enables the system default topology spreading (default true) */
  ownedByController?: boolean
}
export type Profile = 'LowNodeUtilization' | 'HighNodeUtilization' | 'NoScoring'

export const MAX_NODE_SCORE = 100
/** Default weights of the upstream default profile (= OpenShift LowNodeUtilization). */
export const WEIGHTS: Record<string, number> = {
  TaintToleration: 3,
  NodeAffinity: 2,
  PodTopologySpread: 2,
  InterPodAffinity: 2,
  NodeResourcesFit: 1,
  NodeResourcesBalancedAllocation: 1,
  ImageLocality: 1,
}
export const PROFILE_WEIGHTS: Record<Profile, Record<string, number>> = {
  LowNodeUtilization: { ...WEIGHTS },
  HighNodeUtilization: {
    TaintToleration: 3,
    NodeAffinity: 2,
    PodTopologySpread: 2,
    InterPodAffinity: 2,
    NodeResourcesFit: 5,
    ImageLocality: 1,
  },
  NoScoring: {},
}
export const SCORE_PLUGIN_ORDER = ['TaintToleration', 'NodeAffinity', 'NodeResourcesFit', 'PodTopologySpread', 'InterPodAffinity', 'NodeResourcesBalancedAllocation', 'ImageLocality']
export const FILTER_PLUGIN_ORDER = ['NodeUnschedulable', 'TaintToleration', 'NodeAffinity', 'NodeResourcesFit', 'PodTopologySpread', 'InterPodAffinity']

/** Container image sizes (MB) used by ImageLocality. */
export const IMAGE_SIZES_MB: Record<string, number> = {
  'registry.example/payments:1.4': 350,
  'registry.example/payments:1.5': 350,
}
/** Requests the scorer assumes for containers that set none (schedutil.DefaultMilliCPURequest / DefaultMemoryRequest). */
export const NON_ZERO_CPU = 100
export const NON_ZERO_MEM = 200

export const nodeLabels = (n: SimNode): Record<string, string> => ({ ...n.labels, 'kubernetes.io/hostname': n.name, 'topology.kubernetes.io/zone': n.zone })

export const matchTerm = (labels: Record<string, string>, t: Term): boolean => {
  const v = labels[t.key]
  switch (t.operator) {
    case 'In':
      return v !== undefined && (t.values || []).includes(v)
    case 'NotIn':
      return v === undefined || !(t.values || []).includes(v)
    case 'Exists':
      return v !== undefined
    case 'DoesNotExist':
      return v === undefined
  }
}

/** Toleration matching as in k8s.io/api core/v1 Toleration.ToleratesTaint. */
export const tolerates = (tols: Toleration[], t: Taint): boolean =>
  tols.some(
    (o) =>
      (!o.effect || o.effect === t.effect) &&
      ((o.operator || 'Equal') === 'Exists' ? !o.key || o.key === t.key : o.key === t.key && (o.value || '') === (t.value || '')),
  )

export const taintText = (t: Taint) => `${t.key}${t.value ? '=' + t.value : ''}:${t.effect}`

export type FilterResult = {
  plugin: string
  pass: boolean
  /** short human explanation for this node */
  reason: string
  /** the exact reason string the real plugin reports (what lands in the FailedScheduling event) */
  eventReasons?: string[]
  code?: 'Unschedulable' | 'UnschedulableAndUnresolvable'
  /** true when an earlier filter already rejected the node: the real scheduler would not run this one */
  skippedByRealScheduler?: boolean
}
export type ScoreDetail = { plugin: string; raw: number; score: number; weight: number; explain: string }
export type NodeResult = {
  node: SimNode
  filters: FilterResult[]
  feasible: boolean
  /** normalized 0-100 score per plugin (only plugins that ran) */
  scores: Record<string, number>
  details: Record<string, ScoreDetail>
  total: number
}
export type SkippedPlugin = { plugin: string; why: string }
export type SimResult = {
  results: NodeResult[]
  winners: string[]
  message: string | null
  profile: Profile
  scorePlugins: string[]
  skipped: SkippedPlugin[]
  weights: Record<string, number>
}

const podAnti = (pod: SimPod): 'none' | 'preferred' | 'required' => pod.podAntiAffinity || (pod.antiAffinityHostname ? 'required' : 'none')
const affinityMatches = (n: SimNode, pod: SimPod) => {
  const labels = nodeLabels(n)
  return Object.entries(pod.nodeSelector).every(([k, v]) => labels[k] === v) && pod.required.every((t) => matchTerm(labels, t))
}
const domainOf = (n: SimNode, key: 'zone' | 'hostname') => (key === 'zone' ? n.zone : n.name)
const idiv = (a: number, b: number) => Math.trunc(a / b) // Go int64 division

// ---------------------------------------------------------------- filter phase
function runFilters(nodes: SimNode[], pod: SimPod): NodeResult[] {
  // PodTopologySpread PreFilter: count matching pods per domain over nodes that pass the pod's node
  // affinity/selector (nodeAffinityPolicy: Honor, the default); taints are ignored (nodeTaintsPolicy: Ignore).
  let spreadCounts: Record<string, number> | null = null
  let spreadMin = 0
  if (pod.spread && pod.spread.when === 'DoNotSchedule') {
    spreadCounts = {}
    for (const n of nodes) {
      if (!affinityMatches(n, pod)) continue
      const d = domainOf(n, pod.spread.topologyKey)
      spreadCounts[d] = (spreadCounts[d] || 0) + (n.appPods || 0)
    }
    const vals = Object.values(spreadCounts)
    spreadMin = vals.length ? Math.min(...vals) : 0
  }

  return nodes.map((n) => {
    const labels = nodeLabels(n)
    const f: FilterResult[] = []
    f.push(
      n.unschedulable
        ? { plugin: 'NodeUnschedulable', pass: false, reason: 'node is cordoned (spec.unschedulable: true)', eventReasons: ['node(s) were unschedulable'], code: 'UnschedulableAndUnresolvable' }
        : { plugin: 'NodeUnschedulable', pass: true, reason: 'schedulable' },
    )
    const hard = n.taints.filter((t) => t.effect !== 'PreferNoSchedule' && !tolerates(pod.tolerations, t))
    f.push(
      hard.length
        ? { plugin: 'TaintToleration', pass: false, reason: `untolerated taint ${hard.map(taintText).join(', ')}`, eventReasons: ['node(s) had untolerated taint(s)'], code: 'UnschedulableAndUnresolvable' }
        : { plugin: 'TaintToleration', pass: true, reason: n.taints.some((t) => t.effect !== 'PreferNoSchedule') ? 'NoSchedule/NoExecute taints tolerated' : 'no NoSchedule/NoExecute taints' },
    )
    const selOk = Object.entries(pod.nodeSelector).every(([k, v]) => labels[k] === v)
    const reqOk = pod.required.every((t) => matchTerm(labels, t))
    f.push(
      selOk && reqOk
        ? { plugin: 'NodeAffinity', pass: true, reason: Object.keys(pod.nodeSelector).length || pod.required.length ? 'nodeSelector / required affinity match' : 'no nodeSelector or required affinity' }
        : { plugin: 'NodeAffinity', pass: false, reason: !selOk ? "labels don't match nodeSelector" : "labels don't match required node affinity", eventReasons: ["node(s) didn't match Pod's node affinity/selector"], code: 'UnschedulableAndUnresolvable' },
    )
    // NodeResourcesFit filter uses the pod's actual requests (a pod with no requests always fits).
    const freeCpu = n.cpu - n.usedCpu
    const freeMem = n.mem - n.usedMem
    const insufficient: string[] = []
    if (pod.cpu > freeCpu) insufficient.push('Insufficient cpu')
    if (pod.mem > freeMem) insufficient.push('Insufficient memory')
    f.push(
      insufficient.length
        ? {
            plugin: 'NodeResourcesFit',
            pass: false,
            reason: [pod.cpu > freeCpu ? `needs ${pod.cpu}m CPU, ${freeCpu}m unrequested` : '', pod.mem > freeMem ? `needs ${pod.mem}Mi, ${freeMem}Mi unrequested` : ''].filter(Boolean).join('; '),
            eventReasons: insufficient,
            // a request above the node's allocatable can never fit, even by preempting every pod
            code: pod.cpu > n.cpu || pod.mem > n.mem ? 'UnschedulableAndUnresolvable' : 'Unschedulable',
          }
        : { plugin: 'NodeResourcesFit', pass: true, reason: `fits by requests: ${freeCpu}m CPU and ${freeMem}Mi not yet requested` },
    )
    if (pod.spread && pod.spread.when === 'DoNotSchedule' && spreadCounts) {
      const d = domainOf(n, pod.spread.topologyKey)
      const matchNum = spreadCounts[d] || 0
      const skew = matchNum + 1 - spreadMin
      const ok = skew <= pod.spread.maxSkew
      f.push(
        ok
          ? { plugin: 'PodTopologySpread', pass: true, reason: `${pod.spread.topologyKey} ${d}: ${matchNum} + 1 − min ${spreadMin} = ${skew} ≤ maxSkew ${pod.spread.maxSkew}` }
          : {
              plugin: 'PodTopologySpread',
              pass: false,
              reason: `${pod.spread.topologyKey} ${d}: ${matchNum} + 1 − min ${spreadMin} = ${skew} > maxSkew ${pod.spread.maxSkew}`,
              eventReasons: ["node(s) didn't match pod topology spread constraints"],
              code: 'Unschedulable',
            },
      )
    }
    if (podAnti(pod) === 'required') {
      const ok = (n.appPods || 0) === 0
      f.push(
        ok
          ? { plugin: 'InterPodAffinity', pass: true, reason: 'no app=payments pod on this node' }
          : { plugin: 'InterPodAffinity', pass: false, reason: `${n.appPods} app=payments pod(s) already on this host`, eventReasons: ["node(s) didn't match pod anti-affinity rules"], code: 'Unschedulable' },
      )
    }
    let failed = false
    for (const x of f) {
      if (failed) x.skippedByRealScheduler = true
      if (!x.pass) failed = true
    }
    return { node: n, filters: f, feasible: !failed, scores: {}, details: {}, total: 0 }
  })
}

// ---------------------------------------------------------------- score plugins (upstream formulas)

/** NodeResourcesFit LeastAllocated / MostAllocated, cpu and memory weight 1 each, Go integer arithmetic. */
export function fitScore(n: SimNode, pod: SimPod, strategy: 'LeastAllocated' | 'MostAllocated') {
  // Scoring uses "non-zero" requests: a container without a request counts as 100m CPU / 200Mi.
  const reqCpu = n.usedCpu + (pod.cpu || NON_ZERO_CPU)
  const reqMem = n.usedMem + (pod.mem || NON_ZERO_MEM)
  const one = (req: number, cap: number) => {
    if (cap === 0) return 0
    if (strategy === 'LeastAllocated') return req > cap ? 0 : idiv((cap - req) * MAX_NODE_SCORE, cap)
    return idiv(Math.min(req, cap) * MAX_NODE_SCORE, cap)
  }
  const c = one(reqCpu, n.cpu)
  const m = one(reqMem, n.mem)
  return { score: idiv(c + m, 2), cpu: c, mem: m, reqCpu, reqMem }
}

/** NodeResourcesBalancedAllocation (1.34): (1 − |cpuFraction − memFraction| / 2) × 100, fractions capped at 1. */
export function balancedScore(n: SimNode, pod: SimPod) {
  const fc = Math.min(1, (n.usedCpu + pod.cpu) / n.cpu)
  const fm = Math.min(1, (n.usedMem + pod.mem) / n.mem)
  const std = Math.abs((fc - fm) / 2)
  return { score: Math.trunc((1 - std) * MAX_NODE_SCORE), fc, fm, std }
}

/** ImageLocality: image size scaled by the share of nodes that have it, clamped to [23MB, 1000MB × containers]. */
export function imageLocalityScore(n: SimNode, pod: SimPod, nodes: SimNode[]) {
  const mb = 1024 * 1024
  const minT = 23 * mb
  const maxT = 1000 * mb
  const has = (n.images || []).includes(pod.image)
  const sizeMb = IMAGE_SIZES_MB[pod.image] ?? 300
  const numNodes = nodes.filter((x) => (x.images || []).includes(pod.image)).length
  let sum = has ? Math.trunc(sizeMb * mb * (numNodes / nodes.length)) : 0
  const scaledMb = sum / mb
  sum = Math.min(maxT, Math.max(minT, sum))
  return { score: idiv(MAX_NODE_SCORE * (sum - minT), maxT - minT), has, sizeMb, numNodes, scaledMb }
}

/** DefaultNormalizeScore (framework/plugins/helper): scale to 0..100 by the max; reverse if asked. */
function defaultNormalize(raw: number[], reverse: boolean) {
  const max = Math.max(0, ...raw)
  if (max === 0) return raw.map(() => (reverse ? MAX_NODE_SCORE : 0))
  return raw.map((s) => {
    const v = idiv(MAX_NODE_SCORE * s, max)
    return reverse ? MAX_NODE_SCORE - v : v
  })
}

type SpreadSoft = { topologyKey: 'zone' | 'hostname'; maxSkew: number; system: boolean }

function softSpreadConstraints(pod: SimPod): SpreadSoft[] {
  if (pod.spread) return pod.spread.when === 'ScheduleAnyway' ? [{ topologyKey: pod.spread.topologyKey, maxSkew: pod.spread.maxSkew, system: false }] : []
  if (pod.ownedByController === false) return []
  // System default constraints (applied when the pod sets none and belongs to a Service/ReplicaSet/StatefulSet).
  return [
    { topologyKey: 'hostname', maxSkew: 3, system: true },
    { topologyKey: 'zone', maxSkew: 5, system: true },
  ]
}

function scorePodTopologySpread(all: SimNode[], feasible: NodeResult[], pod: SimPod, cons: SpreadSoft[]) {
  const weights = cons.map((c) => {
    const size = c.topologyKey === 'hostname' ? feasible.length : new Set(feasible.map((r) => r.node.zone)).size
    return Math.log(size + 2)
  })
  // pod counts per zone over all nodes that honour the pod's node affinity, for zones present among feasible nodes
  const zoneCounts: Record<string, number> = {}
  const feasibleZones = new Set(feasible.map((r) => r.node.zone))
  for (const n of all) {
    if (!affinityMatches(n, pod) || !feasibleZones.has(n.zone)) continue
    zoneCounts[n.zone] = (zoneCounts[n.zone] || 0) + (n.appPods || 0)
  }
  const raws = feasible.map((r) => {
    let s = 0
    const parts: string[] = []
    cons.forEach((c, i) => {
      const cnt = c.topologyKey === 'hostname' ? r.node.appPods || 0 : zoneCounts[r.node.zone] || 0
      s += cnt * weights[i] + (c.maxSkew - 1)
      parts.push(`${c.topologyKey}: ${cnt}×${weights[i].toFixed(2)}+${c.maxSkew - 1}`)
    })
    return { raw: Math.round(s), parts }
  })
  const vals = raws.map((x) => x.raw)
  const max = Math.max(0, ...vals)
  const min = vals.length ? Math.min(...vals) : 0
  return raws.map((x) => ({
    raw: x.raw,
    score: max === 0 ? MAX_NODE_SCORE : idiv(MAX_NODE_SCORE * (max + min - x.raw), max),
    explain: `${x.parts.join(' + ')} ≈ ${x.raw} (fewer matching pods → higher score)`,
  }))
}

// ---------------------------------------------------------------- one scheduling cycle
export function simulate(nodes: SimNode[], pod: SimPod, profile: Profile = 'LowNodeUtilization'): SimResult {
  const results = runFilters(nodes, pod)
  const feasible = results.filter((r) => r.feasible)
  const weights = PROFILE_WEIGHTS[profile]
  const skipped: SkippedPlugin[] = []
  const scorePlugins: string[] = []

  const put = (plugin: string, vals: { raw: number; score: number; explain: string }[]) => {
    scorePlugins.push(plugin)
    feasible.forEach((r, i) => {
      r.scores[plugin] = vals[i].score
      r.details[plugin] = { plugin, raw: vals[i].raw, score: vals[i].score, weight: weights[plugin] ?? 1, explain: vals[i].explain }
    })
  }

  if (profile === 'NoScoring') {
    skipped.push({ plugin: 'all score plugins', why: 'the NoScoring profile disables every preScore and score plugin' })
  } else if (feasible.length === 1) {
    // schedulePod: "When only one node after predicate, just use it." Scoring is skipped entirely.
    skipped.push({ plugin: 'all score plugins', why: 'only one node passed the filters, so the scheduler binds the pod there without scoring' })
  } else if (feasible.length > 1) {
    // TaintToleration: count intolerable PreferNoSchedule taints, normalized in reverse.
    const soft = feasible.map((r) => r.node.taints.filter((t) => t.effect === 'PreferNoSchedule' && !tolerates(pod.tolerations, t)))
    const tt = defaultNormalize(soft.map((s) => s.length), true)
    put('TaintToleration', soft.map((s, i) => ({ raw: s.length, score: tt[i], explain: s.length ? `${s.length} untolerated PreferNoSchedule taint(s): ${s.map(taintText).join(', ')}` : 'no untolerated PreferNoSchedule taint' })))

    // NodeAffinity: sum of weights of matching preferred terms; skipped when the pod has none.
    if (pod.preferred.length === 0) skipped.push({ plugin: 'NodeAffinity', why: 'no preferred node affinity terms (PreScore returns Skip)' })
    else {
      const raw = feasible.map((r) => pod.preferred.reduce((s, p) => s + (matchTerm(nodeLabels(r.node), p.term) ? p.weight : 0), 0))
      const na = defaultNormalize(raw, false)
      put('NodeAffinity', raw.map((v, i) => ({ raw: v, score: na[i], explain: v ? `matching preferred terms weigh ${v}` : 'no preferred term matches' })))
    }

    // NodeResourcesFit
    const strategy = profile === 'HighNodeUtilization' ? 'MostAllocated' : 'LeastAllocated'
    put(
      'NodeResourcesFit',
      feasible.map((r) => {
        const s = fitScore(r.node, pod, strategy)
        const how = strategy === 'LeastAllocated' ? 'unrequested share' : 'requested share'
        return { raw: s.score, score: s.score, explain: `${strategy}: ${how} after placement, cpu ${s.cpu} and memory ${s.mem}, averaged` + (!pod.cpu || !pod.mem ? ' (missing requests count as 100m / 200Mi here)' : '') }
      }),
    )

    // PodTopologySpread (only ScheduleAnyway constraints are scored)
    const cons = softSpreadConstraints(pod)
    if (cons.length === 0) skipped.push({ plugin: 'PodTopologySpread', why: pod.spread ? 'the pod only has a DoNotSchedule constraint, which is a filter; scoring uses ScheduleAnyway constraints' : 'the pod is not owned by a controller, so no system default constraints apply' })
    else {
      const ps = scorePodTopologySpread(nodes, feasible, pod, cons)
      put('PodTopologySpread', ps.map((x) => ({ ...x, explain: (cons[0].system ? 'system default constraints (hostname maxSkew 3, zone maxSkew 5, ScheduleAnyway): ' : '') + x.explain })))
    }

    // InterPodAffinity: preferred anti-affinity (weight 100) against app=payments on the hostname.
    if (podAnti(pod) !== 'preferred') skipped.push({ plugin: 'InterPodAffinity', why: 'no preferred pod (anti-)affinity terms to score' })
    else {
      // Each matching pod counts −100 for the incoming pod's term and −100 for the identical term the existing replica carries.
      const raw = feasible.map((r) => -200 * (r.node.appPods || 0))
      const min = Math.min(...raw)
      const max = Math.max(...raw)
      put(
        'InterPodAffinity',
        raw.map((v, i) => ({
          raw: v,
          score: max - min > 0 ? Math.trunc(MAX_NODE_SCORE * ((v - min) / (max - min))) : 0,
          explain: `${feasible[i].node.appPods || 0} app=payments pod(s) here; −100 per pod for each side's preferred anti-affinity term`,
        })),
      )
    }

    // NodeResourcesBalancedAllocation (disabled in HighNodeUtilization; skipped for best-effort pods)
    if (profile === 'HighNodeUtilization') skipped.push({ plugin: 'NodeResourcesBalancedAllocation', why: 'disabled by the HighNodeUtilization profile' })
    else if (!pod.cpu && !pod.mem) skipped.push({ plugin: 'NodeResourcesBalancedAllocation', why: 'best-effort pod (no requests): skipped since Kubernetes 1.33' })
    else
      put(
        'NodeResourcesBalancedAllocation',
        feasible.map((r) => {
          const b = balancedScore(r.node, pod)
          return { raw: b.score, score: b.score, explain: `cpu ${(b.fc * 100).toFixed(0)}% vs memory ${(b.fm * 100).toFixed(0)}% requested after placement; closer is better` }
        }),
      )

    // ImageLocality
    put(
      'ImageLocality',
      feasible.map((r) => {
        const s = imageLocalityScore(r.node, pod, nodes)
        return { raw: s.score, score: s.score, explain: s.has ? `image cached (${s.sizeMb}MB × ${s.numNodes}/${nodes.length} nodes ≈ ${s.scaledMb.toFixed(0)}MB, clamped to 23–1000MB)` : 'image not cached on this node' }
      }),
    )
    for (const r of feasible) r.total = Object.entries(r.scores).reduce((s, [k, v]) => s + v * (weights[k] ?? 1), 0)
  }

  const best = feasible.length ? Math.max(...feasible.map((r) => r.total)) : null
  const winners = feasible.filter((r) => r.total === best).map((r) => r.node.name)
  return { results, winners, message: feasible.length ? null : failedSchedulingMessage(results), profile, scorePlugins, skipped, weights }
}

/**
 * The FailedScheduling message as formatted by framework.FitError.Error() in 1.34: only the first failing
 * filter of each node counts, "count reason" strings are sorted, then the PostFilter part.
 * "no new claims to deallocate" comes from the DynamicResources PostFilter (enabled in OpenShift 4.21).
 * DefaultPreemption then dry-runs the nodes whose failure is Unschedulable (resolvable): this model has no
 * lower-priority pods, so each reports "No preemption victims found for incoming pod"; nodes that failed with
 * UnschedulableAndUnresolvable (taints, affinity, cordon, a request above allocatable) get "Preemption is not
 * helpful for scheduling". Sources: pkg/scheduler/framework/types.go, framework/preemption/preemption.go,
 * plugins/defaultpreemption/default_preemption.go.
 */
export function failedSchedulingMessage(results: NodeResult[]): string {
  const counts: Record<string, number> = {}
  const post: Record<string, number> = {}
  for (const r of results) {
    const first = r.filters.find((x) => !x.pass)
    for (const reason of first?.eventReasons || []) counts[reason] = (counts[reason] || 0) + 1
    const p = first?.code === 'Unschedulable' ? 'No preemption victims found for incoming pod' : 'Preemption is not helpful for scheduling'
    post[p] = (post[p] || 0) + 1
  }
  const fmt = (m: Record<string, number>) =>
    Object.entries(m)
      .map(([k, v]) => `${v} ${k}`)
      .sort()
      .join(', ')
  const n = results.length
  return `0/${n} nodes are available: ${fmt(counts)}. no new claims to deallocate, preemption: 0/${n} nodes are available: ${fmt(post)}.`
}

export const SAMPLE_NODES: SimNode[] = [
  { name: 'worker-a1', zone: 'zone-a', cpu: 4000, mem: 16000, usedCpu: 3200, usedMem: 9000, labels: { 'node-role.kubernetes.io/worker': '', disktype: 'ssd' }, taints: [], images: ['registry.example/payments:1.4'], appPods: 1 },
  { name: 'worker-b1', zone: 'zone-b', cpu: 4000, mem: 16000, usedCpu: 1200, usedMem: 4000, labels: { 'node-role.kubernetes.io/worker': '', disktype: 'hdd' }, taints: [], appPods: 0 },
  { name: 'worker-c1', zone: 'zone-c', cpu: 8000, mem: 32000, usedCpu: 1000, usedMem: 2000, labels: { 'node-role.kubernetes.io/worker': '', disktype: 'ssd', gpu: 'true' }, taints: [{ key: 'gpu', value: 'true', effect: 'NoSchedule' }], appPods: 0 },
  { name: 'infra-a1', zone: 'zone-a', cpu: 4000, mem: 16000, usedCpu: 500, usedMem: 2000, labels: { 'node-role.kubernetes.io/infra': '' }, taints: [{ key: 'node-role.kubernetes.io/infra', effect: 'NoSchedule' }], appPods: 0 },
]
