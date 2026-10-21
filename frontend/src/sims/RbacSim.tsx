import { useMemo, useState } from 'react'
import {
  NAMESPACE_UID_RANGE,
  RBAC_BINDINGS,
  RBAC_IDENTITIES,
  RBAC_NAMESPACES,
  RBAC_RESOURCES,
  RBAC_ROLES,
  RBAC_VERBS,
  SCCS,
  admitPod,
  canI,
  ruleText,
  userInfo,
  validateBinding,
  type Binding,
  type PodSecuritySpec,
  type SccName,
  type Subject,
} from './models'
import { Btn, Chip, Code, Panel, Segmented, SelectField, SimIcon, SimShell, Toggle, useAnnounceChange, type Challenge, type ModelScope, type PredictSpec } from './ui'

const PREDICT: PredictSpec = {
  question: 'alice is admin of project team-a through a RoleBinding (in team-a) that references the ClusterRole admin. Can she delete pods in team-b?',
  choices: [
    { id: 'yes-cluster', label: 'Yes: admin is a ClusterRole, so it applies everywhere', feedback: 'The kind of the role decides what it can contain, not where it applies. The binding decides where.' },
    { id: 'no', label: 'No: a RoleBinding only grants inside its own namespace', correct: true, feedback: 'A RoleBinding that references a ClusterRole grants that ClusterRole\'s rules in the RoleBinding\'s namespace only. Only a ClusterRoleBinding grants cluster-wide.' },
    { id: 'deny', label: 'Only if team-b has no deny rule', feedback: 'RBAC has no deny rules at all: permissions are the union of what every matching binding grants.' },
    { id: 'auth', label: 'Yes, because she is in system:authenticated', feedback: 'Membership in system:authenticated (or OpenShift\'s system:authenticated:oauth) only grants what is bound to those groups. Here that is creating projects, through the self-provisioners binding to system:authenticated:oauth.' },
  ],
  explain: 'To answer "can X do Y?", list every binding whose subjects include X (directly, through a group or a ServiceAccount virtual group), keep those that apply in that namespace, and look for one rule that matches. One match is enough; nothing can take it away except removing every path.',
}

const SCOPE: ModelScope = {
  includes: [
    'Subjects: users, groups and ServiceAccounts, with the virtual groups system:authenticated, system:serviceaccounts and system:serviceaccounts:<namespace> (and OpenShift\'s system:authenticated:oauth).',
    'RoleBindings and ClusterRoleBindings, Roles and ClusterRoles; namespace scope of RoleBindings (also when they reference a ClusterRole); roleRef resolution (a RoleBinding can only use a Role of its own namespace).',
    'Rule matching: verbs, API groups, resources and subresources (pods does not cover pods/log), wildcards, resourceNames; listing across all namespaces needs a ClusterRoleBinding.',
    'Union of permissions with every granting path listed, and no deny rules.',
    'A simplified SCC admission: which SCCs a ServiceAccount may use, priority then restrictiveness ordering, first SCC that validates wins, the openshift.io/scc annotation and the denial message format.',
  ],
  leavesOut: [
    'Built-in roles are abbreviated: the real view/edit/admin are aggregated ClusterRoles with many more rules.',
    'Role aggregation, the escalate/bind/impersonate verbs, non-resource URLs, the Node and webhook authorizers, OpenShift scopes on OAuth tokens.',
    'SCC fields other than runAsUser, privileged, capabilities, hostNetwork, hostPath and hostUsers (no SELinux, fsGroup, supplemental groups, seccomp, volume lists). The real denial message lists every SCC in the cluster; only six are modelled.',
    'Pod Security Admission (the namespace-level pod-security.kubernetes.io labels) that OpenShift also enforces.',
  ],
  links: [
    { label: 'Kubernetes: RBAC authorization', url: 'https://kubernetes.io/docs/reference/access-authn-authz/rbac/' },
    { label: 'Kubernetes: RoleBinding and ClusterRoleBinding', url: 'https://kubernetes.io/docs/reference/access-authn-authz/rbac/#rolebinding-and-clusterrolebinding' },
    { label: 'Kubernetes: referring to subjects (virtual groups)', url: 'https://kubernetes.io/docs/reference/access-authn-authz/rbac/#referring-to-subjects' },
    { label: 'OpenShift 4.21: using RBAC to define and apply permissions', url: 'https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/authentication_and_authorization/using-rbac' },
    { label: 'OpenShift 4.21: managing security context constraints', url: 'https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/authentication_and_authorization/managing-pod-security-policies' },
    { label: 'OpenShift 4.21: service accounts', url: 'https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/authentication_and_authorization/understanding-and-creating-service-accounts' },
  ],
}

const SUBJECTS: Subject[] = [
  { kind: 'User', name: 'alice' },
  { kind: 'User', name: 'bob' },
  { kind: 'Group', name: 'developers' },
  { kind: 'Group', name: 'auditors' },
  { kind: 'Group', name: 'system:authenticated' },
  { kind: 'Group', name: 'system:serviceaccounts' },
  { kind: 'Group', name: 'system:serviceaccounts:team-a' },
  { kind: 'Group', name: 'system:serviceaccounts:team-b' },
  { kind: 'ServiceAccount', name: 'ci', namespace: 'team-a' },
  { kind: 'ServiceAccount', name: 'deployer', namespace: 'team-a' },
  { kind: 'ServiceAccount', name: 'default', namespace: 'team-b' },
  { kind: 'ServiceAccount', name: 'builder', namespace: 'team-b' },
]
const subjText = (s: Subject) => (s.kind === 'ServiceAccount' ? `ServiceAccount ${s.namespace}/${s.name}` : `${s.kind} ${s.name}`)
const roleKey = (kind: string, name: string, ns?: string) => `${kind}|${ns || ''}|${name}`
const bindingText = (b: Binding) => `${b.kind} ${b.namespace ? `${b.namespace}/` : ''}${b.name} → ${b.roleRef.kind} ${b.roleRef.name} → ${b.subjects.map(subjText).join(', ')}`
const VIRTUAL = new Set(['system:authenticated', 'system:authenticated:oauth', 'system:serviceaccounts'])
const isVirtual = (g: string) => VIRTUAL.has(g) || g.startsWith('system:serviceaccounts:')

const DEFAULT_POD: PodSecuritySpec = { runAsUser: 0, privileged: false, addCapability: '', hostNetwork: false, hostPath: false, hostUsersFalse: false, imageUser: 'root' }

export default function RbacSim() {
  const [view, setView] = useState<'rbac' | 'scc'>('rbac')
  const [bindings, setBindings] = useState<Binding[]>(() => RBAC_BINDINGS.map((b) => ({ ...b })))
  const [custom, setCustom] = useState<string[]>([])
  const [who, setWho] = useState('sa-ci')
  const [verb, setVerb] = useState('list')
  const [resource, setResource] = useState('pods')
  const [ns, setNs] = useState('team-a')
  const [resName, setResName] = useState('')
  // new binding form
  const [nbKind, setNbKind] = useState<'RoleBinding' | 'ClusterRoleBinding'>('RoleBinding')
  const [nbNs, setNbNs] = useState('team-a')
  const [nbRole, setNbRole] = useState(roleKey('ClusterRole', 'view'))
  const [nbSubject, setNbSubject] = useState(subjText(SUBJECTS[1]))
  const [nbError, setNbError] = useState<string | null>(null)
  // SCC
  const [pod, setPod] = useState<PodSecuritySpec>(DEFAULT_POD)
  const [grants, setGrants] = useState<SccName[]>([])

  const identity = RBAC_IDENTITIES.find((i) => i.id === who) || RBAC_IDENTITIES[0]
  const res = RBAC_RESOURCES.find((r) => r.resource === resource) || RBAC_RESOURCES[0]
  const result = useMemo(() => canI({ identity, verb, resource: res, namespace: res.namespaced ? (ns === '*' ? null : ns) : null, name: resName || undefined }, bindings), [identity, verb, res, ns, resName, bindings])
  const scc = useMemo(() => admitPod(pod, grants), [pod, grants])
  const info = userInfo(identity)

  const announcement = useAnnounceChange(view === 'rbac' ? `${result.command}: ${result.allowed ? `yes, through ${result.paths.length} path(s)` : 'no'}` : scc.admitted ? `Pod admitted with SCC ${scc.admitted}` : 'Pod rejected: unable to validate against any security context constraint')

  const addBinding = () => {
    const [rk, , rname] = nbRole.split('|')
    const subject = SUBJECTS.find((s) => subjText(s) === nbSubject) as Subject
    const base = `${rname.replace(/[^a-z0-9-]/gi, '-')}-${subject.name.replace(/[^a-z0-9-]/gi, '-')}`.toLowerCase()
    let name = base
    for (let i = 2; bindings.some((b) => b.name === name && (b.namespace || '') === (nbKind === 'RoleBinding' ? nbNs : '')); i++) name = `${base}-${i}`
    const b: Binding = { kind: nbKind, name, namespace: nbKind === 'RoleBinding' ? nbNs : undefined, roleRef: { kind: rk as 'Role' | 'ClusterRole', name: rname }, subjects: [subject], enabled: true }
    const refused = validateBinding(b)
    setNbError(refused)
    if (refused) return
    setBindings((bs) => [...bs, b])
    setCustom((c) => [...c, `${b.namespace || ''}/${b.name}`])
  }
  const bkey = (b: Binding) => `${b.kind}/${b.namespace || ''}/${b.name}`
  const granting = new Set(result.paths.map((p) => bkey(p.binding)))
  const missing = new Set(result.nearMisses.map((m) => bkey(m.binding)))

  const sa = (id: string) => RBAC_IDENTITIES.find((i) => i.id === id) as (typeof RBAC_IDENTITIES)[number]
  const challenges: Challenge[] = [
    {
      id: 'union',
      title: 'Revoke: make "oc auth can-i list pods -n team-a --as=system:serviceaccount:team-a:ci" answer no.',
      hint: 'There is no deny rule. Find every path that grants it, including the one through a virtual group, and remove them all.',
      done: !canI({ identity: sa('sa-ci'), verb: 'list', resource: RBAC_RESOURCES[0], namespace: 'team-a' }, bindings).allowed,
    },
    {
      id: 'virtual-group',
      title: 'With one new RoleBinding in team-a, let every ServiceAccount of team-b pull images from team-a.',
      hint: 'Bind system:image-puller to the group that every team-b ServiceAccount belongs to automatically.',
      done:
        canI({ identity: sa('sa-b-default'), verb: 'get', resource: RBAC_RESOURCES.find((r) => r.resource === 'imagestreams/layers') as (typeof RBAC_RESOURCES)[number], namespace: 'team-a' }, bindings).allowed &&
        bindings.some((b) => b.enabled && b.kind === 'RoleBinding' && b.namespace === 'team-a' && b.subjects.some((s) => s.kind === 'Group' && s.name === 'system:serviceaccounts:team-b')),
    },
    {
      id: 'scc',
      title: 'SCC: the pod asks for runAsUser 0 and is rejected. Get it admitted under restricted-v2 without granting any SCC.',
      hint: 'Change the pod, not the permissions: let restricted-v2 pick a UID from the project range.',
      done: scc.admitted === 'restricted-v2' && grants.length === 0,
    },
  ]

  return (
    <SimShell
      id="rbac"
      title="Who can do what: RBAC and SCCs"
      scenario={
        <>
          <p>
            Two projects (<code>team-a</code>, <code>team-b</code>), two users, a few ServiceAccounts and a handful of bindings. Ask <code>oc auth can-i</code> questions and see every path that grants the permission, or why none does. Then see how SCC admission picks a security context constraint for a pod.
          </p>
        </>
      }
      predict={PREDICT}
      scope={SCOPE}
      challenges={challenges}
      announcement={announcement}
    >
      <Segmented<'rbac' | 'scc'>
        label="Part"
        value={view}
        onChange={setView}
        options={[
          { value: 'rbac', label: 'RBAC: can I…?' },
          { value: 'scc', label: 'SCC admission (simplified)' },
        ]}
      />
      {view === 'rbac' ? (
        <div className="sim-work">
          <div className="sim-col">
            <Panel title="Ask">
              <div className="sim-form">
                <SelectField label="as" value={who} onChange={setWho} options={RBAC_IDENTITIES.map((i) => ({ value: i.id, label: i.kind === 'User' ? `user ${i.name}` : `ServiceAccount ${i.namespace}/${i.name}` }))} />
                <div className="sim-row">
                  <SelectField label="verb" value={verb} onChange={setVerb} options={RBAC_VERBS.map((v) => ({ value: v, label: v }))} />
                  <SelectField label="resource" value={resource} onChange={setResource} options={RBAC_RESOURCES.map((r) => ({ value: r.resource, label: r.label }))} />
                </div>
                {res.namespaced ? (
                  <SelectField label="namespace" value={ns} onChange={setNs} options={[...RBAC_NAMESPACES.map((n) => ({ value: n, label: n })), { value: '*', label: 'all namespaces (-A)' }]} />
                ) : (
                  <p className="sim-note">{res.resource} is cluster-scoped: no namespace.</p>
                )}
                {resource === 'configmaps' && <SelectField label="resource name" value={resName} onChange={setResName} options={[{ value: '', label: '(any / list)' }, { value: 'app-settings', label: 'app-settings' }, { value: 'other', label: 'other' }]} />}
                <div>
                  <p className="sim-sub">The request carries</p>
                  <div className="sim-chips">
                    <Chip tone="accent">user {info.username}</Chip>
                    {info.groups.map((g) => (
                      <Chip key={g} tone={isVirtual(g) ? 'violet' : 'info'} title={isVirtual(g) ? 'virtual group added by the API server' : 'group from the identity provider'}>
                        {isVirtual(g) ? 'virtual ' : 'group '}
                        {g}
                      </Chip>
                    ))}
                  </div>
                </div>
              </div>
            </Panel>
            <Panel title="Add a binding">
              <div className="sim-form">
                <Segmented<'RoleBinding' | 'ClusterRoleBinding'>
                  label="kind"
                  value={nbKind}
                  onChange={(v) => {
                    setNbKind(v)
                    setNbError(null)
                  }}
                  options={[
                    { value: 'RoleBinding', label: 'RoleBinding' },
                    { value: 'ClusterRoleBinding', label: 'ClusterRoleBinding' },
                  ]}
                />
                {nbKind === 'RoleBinding' && <SelectField label="in namespace" value={nbNs} onChange={setNbNs} options={RBAC_NAMESPACES.map((n) => ({ value: n, label: n }))} />}
                <SelectField
                  label="roleRef"
                  value={nbRole}
                  onChange={(v) => {
                    setNbRole(v)
                    setNbError(null)
                  }}
                  options={RBAC_ROLES.map((r) => ({ value: roleKey(r.kind, r.name, r.namespace), label: `${r.kind} ${r.namespace ? `${r.namespace}/` : ''}${r.name}` }))}
                  hint={nbKind === 'RoleBinding' ? 'A Role of this namespace, or any ClusterRole (its rules then apply in this namespace only).' : 'Only a ClusterRole: a ClusterRoleBinding cannot reference a Role.'}
                />
                <SelectField label="subject" value={nbSubject} onChange={setNbSubject} options={SUBJECTS.map((s) => ({ value: subjText(s), label: subjText(s) }))} hint="A User, a Group or a ServiceAccount: either kind of binding can name any of them." />
                <Btn variant="primary" onClick={addBinding}>
                  Create binding
                </Btn>
                {nbError && (
                  <div className="sim-banner" data-tone="bad" data-testid="rbac-binding-refused">
                    <SimIcon name="x" />
                    <div className="sim-banner-body">
                      <p>The API server refuses it; nothing is created.</p>
                      <Code>{nbError}</Code>
                    </div>
                  </div>
                )}
              </div>
            </Panel>
          </div>
          <div className="sim-col">
            <div className="sim-banner" data-tone={result.allowed ? 'ok' : 'bad'}>
              <SimIcon name={result.allowed ? 'check' : 'x'} />
              <div className="sim-banner-body">
                <Code>{`$ ${result.command}\n${result.allowed ? 'yes' : 'no'}`}</Code>
                <p>{result.allowed ? `Allowed through ${result.paths.length} independent path${result.paths.length > 1 ? 's' : ''}. To revoke, every one must go.` : 'Denied: no binding grants it. RBAC denies by default; there is nothing to "unblock", only something to grant.'}</p>
              </div>
            </div>
            {result.paths.length > 0 && (
              <Panel title="Paths that grant it">
                <ol className="sim-grants">
                  {result.paths.map((p) => (
                    <li key={bkey(p.binding)}>
                      <span className="sim-grant-step">
                        <Chip tone="info">{p.via}</Chip>
                      </span>
                      <span className="sim-grant-step">
                        {p.binding.kind} <code>{p.binding.namespace ? `${p.binding.namespace}/` : ''}{p.binding.name}</code>
                      </span>
                      <span className="sim-grant-step">
                        {p.role.kind} <code>{p.role.name}</code>
                      </span>
                      <span className="sim-grant-step">
                        rule: <code>{ruleText(p.role.rules[p.ruleIndex])}</code>
                      </span>
                      <span className="sim-grant-step">
                        <Chip tone={p.scope === 'cluster-wide' ? 'warn' : 'ok'}>{p.scope}</Chip>
                      </span>
                    </li>
                  ))}
                </ol>
              </Panel>
            )}
            {result.nearMisses.length > 0 && (
              <Panel title="Bindings that match the subject but do not help">
                <ul className="sim-misses">
                  {result.nearMisses.map((m) => (
                    <li key={bkey(m.binding)}>
                      <code>{m.binding.namespace ? `${m.binding.namespace}/` : ''}{m.binding.name}</code>: {m.why}
                    </li>
                  ))}
                </ul>
              </Panel>
            )}
            <Panel title={`Bindings (${bindings.filter((b) => b.enabled).length} active)`}>
              <ul className="sim-bindings">
                {bindings.map((b, i) => {
                  const k = bkey(b)
                  const isCustom = custom.includes(`${b.namespace || ''}/${b.name}`)
                  return (
                    <li key={k} data-grants={granting.has(k) || undefined} data-miss={missing.has(k) || undefined}>
                      <Toggle label={<span className="sim-binding-text">{bindingText(b)}</span>} checked={b.enabled} onChange={(v) => setBindings((bs) => bs.map((x, j) => (j === i ? { ...x, enabled: v } : x)))} hint={granting.has(k) ? 'grants this request' : b.builtin ? 'created by OpenShift' : undefined} />
                      {isCustom && (
                        <Btn variant="quiet" onClick={() => setBindings((bs) => bs.filter((_, j) => j !== i))}>
                          Delete
                        </Btn>
                      )}
                    </li>
                  )
                })}
              </ul>
            </Panel>
            <details className="sim-roles">
              <summary>Roles and their rules</summary>
              <ul>
                {RBAC_ROLES.map((r) => (
                  <li key={roleKey(r.kind, r.name, r.namespace)}>
                    <strong>
                      {r.kind} {r.namespace ? `${r.namespace}/` : ''}
                      {r.name}
                    </strong>
                    {r.note && <span className="sim-muted"> ({r.note})</span>}
                    <ul>
                      {r.rules.map((rule) => (
                        <li key={ruleText(rule)}>
                          <code>{ruleText(rule)}</code>
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            </details>
          </div>
        </div>
      ) : (
        <SccPart pod={pod} setPod={setPod} grants={grants} setGrants={setGrants} result={scc} />
      )}
    </SimShell>
  )
}

function SccPart({ pod, setPod, grants, setGrants, result }: { pod: PodSecuritySpec; setPod: (p: PodSecuritySpec) => void; grants: SccName[]; setGrants: (g: SccName[]) => void; result: ReturnType<typeof admitPod> }) {
  const set = (patch: Partial<PodSecuritySpec>) => setPod({ ...pod, ...patch })
  const uidValue = pod.runAsUser === null ? 'unset' : String(pod.runAsUser)
  return (
    <div className="sim-work">
      <div className="sim-col">
        <Panel title="Pod spec (Deployment web, ServiceAccount app)">
          <div className="sim-form">
            <Segmented<string>
              label="securityContext.runAsUser"
              value={uidValue}
              onChange={(v) => set({ runAsUser: v === 'unset' ? null : Number(v) })}
              options={[
                { value: 'unset', label: 'unset' },
                { value: '0', label: '0 (root)' },
                { value: '1001', label: '1001' },
                { value: String(NAMESPACE_UID_RANGE[0] + 5), label: String(NAMESPACE_UID_RANGE[0] + 5) },
              ]}
              hint={`Project UID range (openshift.io/sa.scc.uid-range): ${NAMESPACE_UID_RANGE[0]}/10000`}
            />
            <Segmented<'root' | '1001'>
              label="Image USER"
              value={pod.imageUser}
              onChange={(v) => set({ imageUser: v })}
              options={[
                { value: 'root', label: 'none (root)' },
                { value: '1001', label: 'USER 1001' },
              ]}
            />
            <SelectField<PodSecuritySpec['addCapability']>
              label="capabilities.add"
              value={pod.addCapability}
              onChange={(v) => set({ addCapability: v })}
              options={[
                { value: '', label: 'none' },
                { value: 'NET_BIND_SERVICE', label: 'NET_BIND_SERVICE' },
                { value: 'NET_ADMIN', label: 'NET_ADMIN' },
              ]}
            />
            <Toggle label="privileged: true" checked={pod.privileged} onChange={(v) => set({ privileged: v })} />
            <Toggle label="hostNetwork: true" checked={pod.hostNetwork} onChange={(v) => set({ hostNetwork: v })} />
            <Toggle label="a hostPath volume" checked={pod.hostPath} onChange={(v) => set({ hostPath: v })} />
            <Toggle label="hostUsers: false (user namespace)" checked={pod.hostUsersFalse} onChange={(v) => set({ hostUsersFalse: v })} />
          </div>
        </Panel>
        <Panel title="SCCs the ServiceAccount may use">
          <div className="sim-form">
            <p className="sim-note">Every authenticated user and ServiceAccount may use restricted-v2 and restricted-v3. Others need a grant:</p>
            {(['anyuid', 'nonroot-v2', 'hostnetwork-v2', 'privileged'] as SccName[]).map((n) => (
              <Toggle key={n} label={<code>oc adm policy add-scc-to-user {n} -z app</code>} checked={grants.includes(n)} onChange={(v) => setGrants(v ? [...grants, n] : grants.filter((g) => g !== n))} />
            ))}
          </div>
        </Panel>
      </div>
      <div className="sim-col">
        <div className="sim-banner" data-tone={result.admitted ? (result.runtimeError ? 'warn' : 'ok') : 'bad'}>
          <SimIcon name={result.admitted ? 'check' : 'x'} />
          <div className="sim-banner-body">
            {result.admitted ? (
              <>
                <p>
                  <strong>Admitted with SCC {result.admitted}.</strong> The container runs as UID {result.effectiveUid}.
                </p>
                <Code>{`$ oc get pod -l app=web -o jsonpath='{.items[0].metadata.annotations.openshift\\.io/scc}'\n${result.admitted}`}</Code>
                {result.runtimeError && <p>But the kubelet refuses to start it: <code>{result.runtimeError}</code></p>}
              </>
            ) : (
              <>
                <p>
                  <strong>No pod is created.</strong> The ReplicaSet reports:
                </p>
                <Code>{`Warning  FailedCreate  replicaset/web-6c966884bf  ${result.message}`}</Code>
              </>
            )}
          </div>
        </div>
        <Panel title="Admission, in order">
          <ol className="sim-scc-list">
            {SCCS.map((s) => {
              const v = result.verdicts.find((x) => x.scc === s.name)
              const state = !v ? 'not-tried' : !v.usable ? 'unusable' : v.accepted ? 'accepted' : 'rejected'
              return (
                <li key={s.name} data-state={state}>
                  <div className="sim-scc-head">
                    <code className="sim-strong">{s.name}</code>
                    {s.priority > 0 && <Chip tone="warn">priority {s.priority}</Chip>}
                    <Chip tone={state === 'accepted' ? 'ok' : state === 'rejected' ? 'bad' : 'muted'}>{state === 'accepted' ? 'admits the pod' : state === 'rejected' ? 'rejects' : state === 'unusable' ? 'not usable' : 'not tried (an earlier SCC won)'}</Chip>
                  </div>
                  {v && v.usable && v.errors.length > 0 && (
                    <ul className="sim-scc-errors">
                      {v.errors.map((e) => (
                        <li key={e}>
                          <code>{e}</code>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              )
            })}
          </ol>
          <p className="sim-note">Order as observed on OpenShift 4.21: highest priority first, then most restrictive. A simplified model: only these six SCCs and a few fields.</p>
        </Panel>
      </div>
    </div>
  )
}
