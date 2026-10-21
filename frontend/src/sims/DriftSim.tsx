import { useState } from 'react'
import {
  appHealth,
  appSyncStatus,
  argoManualSync,
  argoReconcile,
  driftRows,
  gitRemove,
  gitSetField,
  initialDrift,
  liveCreateUntracked,
  liveDelete,
  liveSetField,
  ocDiff,
  setDriftPolicy,
  type DriftRow,
  type DriftState,
} from './models'
import { Btn, Chip, Code, Log, Panel, SimShell, Toggle, useAnnouncer, type Challenge, type ModelScope, type PredictSpec } from './ui'

const PREDICT: PredictSpec = {
  question: 'An Argo CD Application has automated sync on and self-heal off. Git says replicas: 3. Someone runs oc scale deployment/web --replicas=5. After Argo CD\'s next reconciliation, how many replicas run?',
  choices: [
    { id: '3', label: '3: automated sync puts Git back', feedback: 'Automated sync only syncs when the Git revision changes. Reverting changes made in the cluster is what selfHeal adds.' },
    { id: '5', label: '5, and the Application shows OutOfSync', correct: true, feedback: 'Argo CD detects the drift (OutOfSync) but skips auto-sync: the most recent sync was already to this revision. The next Git commit, a manual sync or self-heal would bring 3 back.' },
    { id: 'delete', label: 'Argo CD deletes and recreates the Deployment', feedback: 'Sync applies the desired fields; it does not delete live objects that are still in Git.' },
    { id: 'error', label: 'The Application goes Degraded', feedback: 'Health and sync status are separate: 5 healthy replicas are Healthy, just OutOfSync.' },
  ],
  explain: 'Drift detection (OutOfSync) and drift correction (sync) are separate. Self-heal turns detection into correction; prune extends it to objects removed from Git. oc diff answers the same question from your terminal, for the files you give it.',
}

const SCOPE: ModelScope = {
  includes: [
    'Comparison of the manifests at the Git revision with the live objects the Application tracks, per field, giving Synced / OutOfSync and Missing.',
    'Automated sync once per new Git revision; selfHeal also reverting changes made in the cluster; prune (automatic or on a manual sync) deleting tracked objects removed from Git.',
    'Objects without Argo CD\'s tracking metadata (the argocd.argoproj.io/tracking-id annotation by default in Argo CD 3.x, or a label, depending on the tracking method) are not part of the Application: never OutOfSync, never pruned.',
    'A prune-only change is not auto-synced while automated.prune is off ("need to prune extra resources only"); enabling prune later syncs that revision.',
    'Application health, reported separately from sync status: drift makes an Application OutOfSync, not Degraded. A resource missing from the cluster shows as Missing on its row but does not lower the Application\'s health.',
    'oc diff -f: compares only the objects in the files with the live ones, exit code 1 when they differ, 0 otherwise.',
  ],
  leavesOut: [
    'Timing: real Argo CD watches the cluster continuously, polls Git about every 3 minutes (or uses webhooks) and waits a short self-heal timeout; here reconciliation happens when you press the button.',
    'Server-side apply and defaulted fields, ignoreDifferences, sync waves and hooks, retries, health checks beyond "exists", multiple sources, Helm/Kustomize rendering.',
    'The diff is abridged: real oc diff output has full objects, line numbers and metadata changes such as generation (managedFields are hidden by default).',
  ],
  links: [
    { label: 'Argo CD: automated sync policy (prune, self-heal)', url: 'https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/' },
    { label: 'Argo CD: sync options', url: 'https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/' },
    { label: 'Argo CD: resource tracking', url: 'https://argo-cd.readthedocs.io/en/stable/user-guide/resource_tracking/' },
    { label: 'Kubernetes: kubectl diff', url: 'https://kubernetes.io/docs/reference/kubectl/generated/kubectl_diff/' },
    { label: 'Kubernetes: declarative management with kubectl', url: 'https://kubernetes.io/docs/tasks/manage-kubernetes-objects/declarative-config/' },
    { label: 'Red Hat OpenShift GitOps documentation', url: 'https://docs.redhat.com/en/documentation/red_hat_openshift_gitops/1.18' },
  ],
}

const REPLICAS = 'spec.replicas'
const IMAGE = 'spec.template.spec.containers[0].image'
const HOTFIX = 'quay.io/acme/web:1.4.2-hotfix'

export default function DriftSim() {
  const [s, setS] = useState<DriftState>(() => initialDrift({ automated: true, selfHeal: false, prune: false }))
  const [manualPrune, setManualPrune] = useState(false)
  const [msg, announce] = useAnnouncer()
  const rows = driftRows(s)
  const status = appSyncStatus(s)
  const health = appHealth(s)
  const diff = ocDiff(s)

  const apply = (next: DriftState) => {
    setS(next)
    const last = next.log[next.log.length - 1]
    announce(next === s ? 'No change.' : `${last ? last.text : 'Done'}. Application ${appSyncStatus(next)}.`)
  }
  const live = (name: string) => s.live.find((r) => r.name === name)
  const git = (name: string) => s.git.find((r) => r.name === name)

  const lastArgo = [...s.log].reverse().find((l) => l.who === 'Argo CD')
  const lastLog = s.log[s.log.length - 1]
  const challenges: Challenge[] = [
    {
      id: 'self-heal',
      title: 'Hotfix gets reverted: with self-heal on, change the live image and let Argo CD put Git back.',
      hint: 'Turn on self-heal, run the oc set image hotfix, then reconcile.',
      done: s.markers.lastIndexOf(`live:edit:${IMAGE}`) >= 0 && s.markers.lastIndexOf('self-healed') > s.markers.lastIndexOf(`live:edit:${IMAGE}`) && live('web')?.fields[IMAGE] === git('web')?.fields[IMAGE],
    },
    {
      id: 'drift-sticks',
      title: 'Drift that sticks: with automated sync still on, scale the live Deployment to 5 and keep it at 5 after a reconciliation.',
      hint: 'Which automation setting is the one that reverts live changes?',
      done: s.policy.automated && !s.policy.selfHeal && lastLog?.who === 'Argo CD' && !!lastArgo && /Skipping auto-sync/.test(lastArgo.text) && live('web')?.fields[REPLICAS] === '5' && git('web')?.fields[REPLICAS] !== '5',
    },
    {
      id: 'prune',
      title: 'Prune: remove the CronJob from Git and get it deleted from the cluster.',
      hint: 'Without prune, Argo CD only marks it "requires pruning". Enable prune, or sync manually with prune.',
      done: s.markers.includes('git:remove:CronJob/report') && !s.live.some((r) => r.kind === 'CronJob' && r.name === 'report'),
    },
  ]

  return (
    <SimShell
      id="drift"
      title="GitOps drift and sync"
      scenario={
        <>
          <p>
            An Argo CD Application keeps project <code>shop</code> in line with a Git repository: a Deployment <code>web</code>, a ConfigMap <code>web-config</code> and a CronJob <code>report</code>. People also change things directly in the cluster.
          </p>
          <p>Make changes on either side, reconcile, and compare what Argo CD and oc diff report.</p>
        </>
      }
      predict={PREDICT}
      scope={SCOPE}
      challenges={challenges}
      announcement={msg}
    >
      <div className="sim-work">
        <div className="sim-col">
          <Panel title="Application syncPolicy">
            <div className="sim-form">
              <Toggle label="automated" checked={s.policy.automated} onChange={(v) => setS(setDriftPolicy(s, { ...s.policy, automated: v }))} hint="sync when the Git revision changes" />
              <Toggle label="automated.selfHeal" checked={s.policy.selfHeal} onChange={(v) => setS(setDriftPolicy(s, { ...s.policy, selfHeal: v }))} hint="also sync when the cluster drifts" disabled={!s.policy.automated} />
              <Toggle label="automated.prune" checked={s.policy.prune} onChange={(v) => setS(setDriftPolicy(s, { ...s.policy, prune: v }))} hint="delete tracked objects removed from Git" disabled={!s.policy.automated} />
            </div>
          </Panel>
          <Panel title="Change the cluster (oc)">
            <div className="sim-actions sim-actions-stack">
              <Btn onClick={() => apply(liveSetField(s, 'Deployment', 'web', REPLICAS, '5', 'oc scale deployment/web --replicas=5'))}>oc scale deployment/web --replicas=5</Btn>
              <Btn onClick={() => apply(liveSetField(s, 'Deployment', 'web', IMAGE, HOTFIX, `oc set image deployment/web web=${HOTFIX}`))}>oc set image … web:1.4.2-hotfix</Btn>
              <Btn onClick={() => apply(liveSetField(s, 'ConfigMap', 'web-config', 'data.LOG_LEVEL', 'debug', 'oc patch configmap web-config -p \'{"data":{"LOG_LEVEL":"debug"}}\''))}>set LOG_LEVEL=debug in web-config</Btn>
              <Btn variant="danger" onClick={() => apply(liveDelete(s, 'ConfigMap', 'web-config'))}>
                oc delete configmap web-config
              </Btn>
              <Btn onClick={() => apply(liveCreateUntracked(s))}>oc create configmap scratch</Btn>
            </div>
          </Panel>
          <Panel title="Change Git (commit and push)">
            <div className="sim-actions sim-actions-stack">
              <Btn onClick={() => apply(gitSetField(s, 'Deployment', 'web', REPLICAS, '4', 'web: 4 replicas'))}>replicas: 4</Btn>
              <Btn onClick={() => apply(gitSetField(s, 'Deployment', 'web', IMAGE, 'quay.io/acme/web:1.5.0', 'web: image 1.5.0'))}>image web:1.5.0</Btn>
              <Btn variant="danger" onClick={() => apply(gitRemove(s, 'CronJob', 'report'))}>
                remove cronjob report
              </Btn>
            </div>
          </Panel>
        </div>

        <div className="sim-col">
          <Panel title="Argo CD" aside={<Chip tone={status === 'Synced' ? 'ok' : 'warn'}>{status}</Chip>}>
            <div className="sim-form">
              <p className="sim-note">
                Git revision <code>{s.gitSha}</code> · last sync to <code>{s.syncedSha ?? '—'}</code>
              </p>
              <p className="sim-note" data-testid="drift-app-status">
                Sync status <strong>{status}</strong> · health <strong>{health}</strong>. Separate answers: sync compares the live objects with Git, health asks whether they work.
              </p>
              <div className="sim-actions">
                <Btn variant="primary" icon="reset" onClick={() => apply(argoReconcile(s))}>
                  Let Argo CD reconcile
                </Btn>
                <Btn onClick={() => apply(argoManualSync(s, manualPrune))}>Sync now{manualPrune ? ' (prune)' : ''}</Btn>
                <Toggle label="prune on manual sync" checked={manualPrune} onChange={setManualPrune} />
              </div>
              <ul className="sim-drift-rows">
                {rows.map((r) => (
                  <DriftRowView key={`${r.kind}/${r.name}`} r={r} />
                ))}
              </ul>
            </div>
          </Panel>

          <Panel title="oc diff -f manifests/" aside={<Chip tone={diff.exitCode ? 'warn' : 'ok'}>exit {diff.exitCode}</Chip>}>
            <Code>{`$ oc diff -f manifests/\n${diff.text || '(no output: the live objects match the files)'}`}</Code>
            <p className="sim-note">oc diff compares only the objects in the files: it cannot report objects removed from Git or created by hand. Output abridged.</p>
          </Panel>

          <Panel title="History">
            <Log
              items={s.log}
              keyOf={(l) => l.n}
              empty="Nothing yet."
              render={(l) => (
                <>
                  <div className="sim-log-meta">
                    <Chip tone={l.who === 'Argo CD' ? 'violet' : l.who === 'you (Git)' ? 'info' : 'accent'}>{l.who}</Chip>
                  </div>
                  <span className={l.who === 'Argo CD' ? undefined : 'sim-mono'}>{l.text}</span>
                </>
              )}
            />
          </Panel>
        </div>
      </div>
    </SimShell>
  )
}

function DriftRowView({ r }: { r: DriftRow }) {
  const tone = r.status === 'Synced' ? 'ok' : r.status === 'Ignored' ? 'muted' : 'warn'
  const note = r.status === 'Ignored' ? 'not tracked by Argo CD (no tracking annotation)' : r.requiresPruning ? 'not in Git: requires pruning' : r.health === 'Missing' ? 'Missing in the cluster' : r.diffs.length ? 'live differs from Git' : 'live matches Git'
  return (
    <li className="sim-drift-row" data-status={r.status}>
      <div className="sim-obj-head">
        <span className="sim-mono sim-strong">
          {r.kind}/{r.name}
        </span>
        <Chip tone={tone}>{r.status}</Chip>
        {r.health === 'Missing' && <Chip tone="bad">Missing</Chip>}
        <span className="sim-muted sim-drift-note">{note}</span>
      </div>
      {r.diffs.length > 0 && r.live && (
        <dl className="sim-drift-diff">
          {r.diffs.map((d) => (
            <div key={d.field}>
              <dt className="sim-mono">{d.field.split('.').pop()}</dt>
              <dd>
                <span className="sim-drift-git">
                  Git <code>{d.git}</code>
                </span>
                <span className="sim-drift-live">
                  live <code>{d.live ?? '—'}</code>
                </span>
              </dd>
            </div>
          ))}
        </dl>
      )}
    </li>
  )
}

