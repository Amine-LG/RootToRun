import { describe, expect, it } from 'vitest'
import { DIAGRAMS } from './diagrams'

// What the RBAC diagram teaches, as relations: any subject kind can be named in either binding; a RoleBinding can
// point at a Role or a ClusterRole and grants in its own project; a ClusterRoleBinding points only at a ClusterRole
// and grants everywhere. An earlier version drew groups as members of the subject and linked only to RoleBindings.
describe('rbac diagram', () => {
  const d = DIAGRAMS.find((x) => x.id === 'rbac')!
  const node = (id: string) => d.nodes.find((n) => n.id === id)!
  const to = (from: string) => d.edges.filter((e) => e.from === from).map((e) => e.to).sort()

  it('names all three kinds of subject, and the subject is named in both kinds of binding', () => {
    expect(node('subject').sub).toMatch(/User.*Group.*ServiceAccount/)
    for (const kind of ['**User**', '**Group**', '**ServiceAccount**']) expect(node('subject').detail).toContain(kind)
    expect(to('subject')).toEqual(['crb', 'rb'])
    expect(d.edges.some((e) => /member/i.test(e.label || ''))).toBe(false) // no subject is drawn as a group member
  })

  it('keeps Role and ClusterRole apart, with the references each binding may have', () => {
    expect(node('role').label).toBe('Role')
    expect(node('crole').label).toBe('ClusterRole')
    expect(to('rb')).toEqual(['crole', 'role'])
    expect(to('crb')).toEqual(['crole']) // a ClusterRoleBinding can never point at a Role
    expect(node('crb').detail).toMatch(/only at a ClusterRole, never at a Role/)
  })

  it('says that the binding sets the scope', () => {
    const rbToCrole = d.edges.find((e) => e.from === 'rb' && e.to === 'crole')!
    expect(rbToCrole.label).toMatch(/this project only/)
    expect(node('rb').detail).toMatch(/only in that project/)
    expect(node('crb').detail).toMatch(/everywhere/)
    expect(d.caption).toMatch(/binding sets the scope/i)
    expect(d.caption).toMatch(/no deny rule/)
  })

  it('ends in one decision reached from both roles', () => {
    expect(d.edges.filter((e) => e.to === 'decision').map((e) => e.from).sort()).toEqual(['crole', 'role'])
  })
})

// Request path: the request (blue) goes client → load balancer → router → pod IP; Route → Service → EndpointSlices
// is how the router finds the pods. The Route's details explain the three TLS terminations.
describe('request-path diagram', () => {
  const d = DIAGRAMS.find((x) => x.id === 'request-path')!
  const node = (id: string) => d.nodes.find((n) => n.id === id)!
  const flows = d.edges.filter((e) => e.kind === 'flow').map((e) => `${e.from}>${e.to}`).sort()

  it('draws the request as client → load balancer → router → pod, never through the Service', () => {
    expect(flows).toEqual(['client>lb', 'lb>router', 'router>pod'])
    expect(d.edges.some((e) => e.kind === 'flow' && (e.to === 'svc' || e.from === 'svc'))).toBe(false)
    expect(d.caption).toMatch(/blue arrows carry the request/)
    expect(node('router').detail).toMatch(/not through the Service ClusterIP/)
  })

  it('explains each TLS termination and the Route port', () => {
    const r = node('route').detail!
    expect(r).toMatch(/\*\*edge\*\*: the router decrypts and sends plain HTTP/)
    expect(r).toMatch(/\*\*passthrough\*\*: the router does not decrypt.*SNI/)
    expect(r).toMatch(/\*\*re-encrypt\*\*: the router decrypts, then opens a new TLS connection/)
    expect(r).toMatch(/spec\.port\.targetPort/)
    expect(node('eps').detail).toMatch(/not ready and receive no traffic/)
  })
})

// Storage: ownership (project vs cluster vs storage system) is shown, the PV is an API object rather than part of the
// storage back-end, and the PVC details state what can change (size up only, with allowVolumeExpansion).
describe('storage diagram', () => {
  const d = DIAGRAMS.find((x) => x.id === 'storage')!
  const node = (id: string) => d.nodes.find((n) => n.id === id)!

  it('frames only the pod and its claim as the project, not the PV', () => {
    expect(d.zones).toEqual([{ label: 'Your project', col: 0, row: 0, cols: 2, rows: 1 }])
    const inZone = d.nodes.filter((n) => n.row === 0 && n.col < 2).map((n) => n.id).sort()
    expect(inZone).toEqual(['pod', 'pvc'])
    expect(node('pv').detail).toMatch(/cluster-scoped object, not part of any project/)
    expect(d.caption).toMatch(/belong to the cluster/)
  })

  it('states binding modes, reclaim policies, access modes and expansion correctly', () => {
    expect(d.caption).toMatch(/`Immediate`.*zone where the pod cannot run/)
    expect(node('pvc').detail).toMatch(/only grow, and only when the class sets `allowVolumeExpansion: true`/)
    expect(node('pvc').detail).toMatch(/ReadWriteOncePod: one pod/)
    expect(node('sc').detail).toMatch(/Delete by default/)
    expect(node('pv').detail).toMatch(/copied from the class/)
    expect(d.edges.find((e) => e.from === 'pvc' && e.to === 'pv')).toMatchObject({ label: 'bound', both: true })
  })
})

// NetworkPolicy: all callers are connections (blue), isolation is per direction, NetworkPolicy itself has no deny
// rule while AdminNetworkPolicy can deny, and DNS egress names the pods' port 5353 as the lesson records.
describe('networkpolicy diagram', () => {
  const d = DIAGRAMS.find((x) => x.id === 'networkpolicy')!
  const node = (id: string) => d.nodes.find((n) => n.id === id)!

  it('draws every caller, and DNS egress, as a connection; the policy only selects', () => {
    for (const from of ['router', 'same', 'other']) expect(d.edges.find((e) => e.from === from && e.to === 'target')).toMatchObject({ kind: 'flow' })
    expect(d.edges.find((e) => e.from === 'target' && e.to === 'dns')).toMatchObject({ kind: 'flow' })
    expect(d.edges.find((e) => e.from === 'policy' && e.to === 'target')?.kind).toBeUndefined()
    expect(d.edges.find((e) => e.from === 'router')?.caption).not.toBe('ingress') // not the only ingress
  })

  it('isolates per direction and adds rules; deny exists only in AdminNetworkPolicy', () => {
    expect(node('target').detail).toMatch(/per direction/)
    expect(node('target').detail).toMatch(/both the caller's egress and the destination's ingress/)
    expect(d.caption).toMatch(/a NetworkPolicy has no deny rule/)
    expect(d.caption).toMatch(/AdminNetworkPolicy can deny/)
    expect(node('other').detail).toMatch(/\*\*same\*\* entry, both must match.*\*\*separate\*\* entries, either one/)
  })

  it('matches the lesson on the router namespaces and the DNS port', () => {
    expect(node('router').detail).toMatch(/openshift-ingress.*openshift-host-network/)
    expect(node('router').detail).toMatch(/own node is never blocked/)
    expect(node('dns').detail).toMatch(/5353/)
    expect(node('dns').detail).not.toMatch(/allow both/)
  })
})

// Platform architecture diagrams (control loop, OpenShift, enterprise, OLM, configuration). Each test names the
// statement it guards; the earlier versions said otherwise.
const diagram = (id: string) => {
  const d = DIAGRAMS.find((x) => x.id === id)!
  return { d, node: (n: string) => d.nodes.find((x) => x.id === n)!, to: (from: string) => d.edges.filter((e) => e.from === from).map((e) => e.to).sort() }
}

describe('control-loop diagram', () => {
  const { d, node, to } = diagram('control-loop')

  it('lets only the API server reach etcd, and every controller and the kubelet talk to the API server', () => {
    expect(d.edges.filter((e) => e.from === 'etcd' || e.to === 'etcd').map((e) => e.from)).toEqual(['api'])
    for (const c of ['dc', 'rsc', 'sched', 'kubelet']) expect(to(c)).toContain('api')
    expect(d.edges.find((e) => e.from === 'kubelet' && e.to === 'crio')?.label).toBe('CRI')
  })

  it('says the scheduler records its choice through a Binding', () => {
    expect(node('sched').detail).toMatch(/posting a Binding, which sets the pod's spec\.nodeName/)
  })
})

describe('openshift diagram', () => {
  const { d, node, to } = diagram('openshift')

  it('has the Cluster Version Operator deploy the cluster operators, which report in ClusterOperators', () => {
    expect(d.caption).toMatch(/deploys the cluster operators of the release/)
    expect(d.caption).not.toMatch(/keeps every ClusterOperator at the release version/)
    expect(node('cvo').detail).toMatch(/reads every ClusterOperator/)
    expect(to('cvo')).toEqual(['ingress', 'mco', 'olm'])
  })

  it('names the three networking operators and what each deploys', () => {
    expect(to('ingress')).toEqual(['ovn', 'router']) // OVN-Kubernetes was drawn with no operator behind it
    for (const op of ['Ingress Operator', 'DNS Operator', 'Cluster Network Operator']) expect(node('ingress').detail).toContain(op)
  })

  it('uses the 4.21 console name for the operator catalog', () => {
    expect(node('olm').detail).toContain('Ecosystem > Software Catalog')
  })
})

describe('enterprise diagram', () => {
  const { d, node } = diagram('enterprise')

  it('frames infrastructure and worker nodes as compute nodes, not as workloads', () => {
    expect(d.zones!.map((z) => z.label)).toEqual(['Compute nodes', 'Shared services'])
    expect(node('infra').sub).toBe('routers, registry, monitoring')
    expect(node('infra').detail).toMatch(/label or a taint alone moves nothing/)
  })

  it('does not promise automatic sync or built-in log forwarding', () => {
    expect(node('gitops').detail).not.toMatch(/Continuously applies/)
    expect(node('gitops').detail).toMatch(/automatically or on demand/)
    expect(node('obs').detail).toMatch(/Logging operator/)
  })
})

describe('olm diagram', () => {
  const { d, node, to } = diagram('olm')

  it('is about OLM Classic and says what OLM v1 uses instead', () => {
    expect(d.title).toBe('Installing an operator with OLM Classic')
    expect(d.caption).toMatch(/ClusterCatalog and a ClusterExtension/)
  })

  it('lists the four install modes an OperatorGroup scope can match', () => {
    for (const mode of ['its own namespace', 'one other namespace', 'several namespaces', 'all namespaces']) expect(node('og').detail).toContain(mode)
    expect(node('og').detail).toMatch(/Exactly one OperatorGroup per namespace/)
  })

  it('splits OLM into the Catalog Operator and the OLM Operator, and keeps the object chain', () => {
    expect(node('olm').detail).toMatch(/Catalog Operator.*InstallPlan.*OLM Operator.*ClusterServiceVersion/s)
    expect(to('sub')).toEqual(['olm'])
    expect(to('olm')).toEqual(['ip'])
    expect(to('ip')).toEqual(['csv'])
    expect(to('og')).toEqual(['csv'])
  })
})

describe('config-injection diagram', () => {
  const { d, node } = diagram('config-injection')

  it('separates variables (copied at start) from volume files (refreshed, except subPath)', () => {
    expect(d.edges.find((e) => e.to === 'env')?.label).toMatch(/once, at start/)
    expect(d.edges.find((e) => e.to === 'files')?.label).toMatch(/refresh/)
    expect(node('files').detail).toMatch(/subPath mounts, which never update/)
    expect(node('env').detail).toMatch(/never sees a later change: restart the pods/)
    expect(node('restart').detail).toMatch(/does not change the pod template/)
  })

  it('says a pod waiting for a missing object starts once it exists', () => {
    expect(node('kubelet').detail).toMatch(/keeps retrying/)
  })
})

// The login diagram: authentication happens at login (OAuth server + identity provider) AND on every request (the API
// server turns the token into a user name and groups); only then does RBAC decide. An earlier version put the API
// server in the Authorization zone and linked Groups straight to the RBAC decision, as if RBAC looked groups up.
describe('auth-flow diagram', () => {
  const d = DIAGRAMS.find((x) => x.id === 'auth-flow')!
  const node = (id: string) => d.nodes.find((n) => n.id === id)!
  const inZone = (label: string, id: string) => {
    const z = d.zones!.find((x) => x.label === label)!, n = node(id)
    return n.col >= z.col && n.col < z.col + z.cols && n.row >= z.row && n.row < z.row + z.rows
  }
  const edge = (from: string, to: string) => d.edges.find((e) => e.from === from && e.to === to)

  it('puts the API server, which authenticates each request, in Authentication, and only RBAC in Authorization', () => {
    for (const id of ['you', 'oauth', 'idp', 'identity', 'token', 'groups', 'api']) expect(inZone('Authentication', id)).toBe(true)
    expect(inZone('Authorization', 'rbac')).toBe(true)
    expect(inZone('Authorization', 'api')).toBe(false)
    expect(d.nodes.filter((n) => inZone('Authorization', n.id)).map((n) => n.id)).toEqual(['rbac'])
  })

  it('adds the groups at authentication and hands user name and groups to RBAC', () => {
    expect(edge('groups', 'api')).toBeTruthy()
    expect(edge('groups', 'rbac')).toBeUndefined()
    expect(edge('api', 'rbac')!.label).toMatch(/user name \+ groups/)
    expect(node('groups').detail).toMatch(/system:authenticated:oauth/)
    expect(node('api').detail).toMatch(/401 Unauthorized/)
    expect(node('rbac').detail).toMatch(/403 Forbidden/)
  })

  it('names the three mapping methods of OpenShift 4.21', () => {
    for (const m of ['**claim**', '**lookup**', '**add**']) expect(node('identity').detail).toContain(m)
    expect(node('identity').detail).toMatch(/<provider name>:<provider user ID>/)
  })
})

// SCC admission on OpenShift 4.21: restricted-v3 is available beside restricted-v2, access comes from RBAC or the SCC's
// own users/groups fields, order is priority, restrictiveness, name, required-scc pins one SCC, and Pod Security
// admission is a separate check. An earlier version named only restricted-v2 and left Pod Security admission out.
describe('scc-admission diagram', () => {
  const d = DIAGRAMS.find((x) => x.id === 'scc-admission')!
  const node = (id: string) => d.nodes.find((n) => n.id === id)!

  it('lists what authenticated users may use on 4.21, and both ways an SCC is granted', () => {
    expect(node('avail').detail).toMatch(/restricted-v2/)
    expect(node('avail').detail).toMatch(/restricted-v3.*hostUsers: false/)
    expect(node('avail').detail).toMatch(/`users` and `groups` fields/)
    expect(node('sa').detail).toMatch(/system:openshift:scc:<scc>/)
  })

  it('sorts by priority, then restrictiveness, then name, and mentions the required-scc pin', () => {
    expect(node('order').sub).toBe('priority, restrictiveness, name')
    expect(node('order').detail).toMatch(/Highest priority first.*most restrictive first.*by name/)
    expect(node('order').detail).toMatch(/openshift\.io\/required-scc/)
  })

  it('takes defaults from all three namespace annotations', () => {
    for (const a of ['sa.scc.uid-range', 'sa.scc.supplemental-groups', 'sa.scc.mcs']) expect(node('ranges').detail).toContain(a)
  })

  it('says that Pod Security admission is a separate check', () => {
    expect(d.caption).toMatch(/Pod Security admission checks the same pod separately/)
    expect(node('admitted').detail).toMatch(/enforces only `privileged` by default/)
    expect(node('rejected').detail).toMatch(/not usable by user or serviceaccount/)
  })
})

// OpenShift 4.21 network security docs: "Using the namespaceSelector field without the podSelector field set to {}
// will not include hostNetwork pods." An earlier text implied the label alone matched host-network routers.
describe('networkpolicy diagram: host-network routers', () => {
  it('says a host-network router needs podSelector {} beside the namespaceSelector', () => {
    const d = DIAGRAMS.find((x) => x.id === 'networkpolicy')!
    expect(d.nodes.find((n) => n.id === 'router')!.detail).toMatch(/podSelector: \{\}` in the same entry/)
  })
})
