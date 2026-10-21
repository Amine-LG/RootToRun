import { useState } from 'react'
import {
  ACCESS_SHORT,
  ST_NODES,
  initialStorage,
  stCreatePVC,
  stCreatePod,
  stDeletePV,
  stDeletePVC,
  stDeletePod,
  stPatchReclaim,
  stReservePV,
  storageSummary,
  type AccessMode,
  type StBackend,
  type StPV,
  type StorageState,
} from './models'
import { Btn, Chip, Log, Panel, Segmented, SelectField, SimShell, useAnnouncer, type Challenge, type ModelScope, type PredictSpec, type Tone } from './ui'

const PREDICT: PredictSpec = {
  question: 'The StorageClass uses volumeBindingMode: WaitForFirstConsumer. You create a PersistentVolumeClaim, and no pod uses it yet. What does oc get pvc show?',
  choices: [
    { id: 'bound', label: 'Bound: a volume is provisioned right away', feedback: 'That is volumeBindingMode: Immediate. WaitForFirstConsumer deliberately waits.' },
    { id: 'pending', label: 'Pending, until a pod that uses it is scheduled', correct: true, feedback: 'The event says "waiting for first consumer to be created before binding". Once the scheduler picks a node for a pod, the volume is provisioned in that node\'s zone.' },
    { id: 'available', label: 'Available', feedback: 'Available is a PersistentVolume phase (a free volume), not a claim phase.' },
    { id: 'lost', label: 'Lost', feedback: 'Lost means the claim\'s volume disappeared. Nothing was bound yet.' },
  ],
  explain: 'Binding late lets the volume follow the pod. With Immediate binding a zonal disk can be created in a zone where the pod cannot run, and the pod stays Pending.',
}

const SCOPE: ModelScope = {
  includes: [
    'Dynamic provisioning with volumeBindingMode Immediate (bind at once, zone chosen without knowing the pod) and WaitForFirstConsumer (bind after scheduling, in the node\'s zone).',
    'reclaimPolicy Delete (claim deleted → PV and backend volume deleted) and Retain (PV Released, data kept, not reused until an admin clears the claimRef); patching one PV\'s reclaim policy: Retain protects it, Delete on a Released PV makes the provisioner delete it with its data.',
    'Deleting a PV object: a Retain volume stays on the storage system; a Delete volume is deleted with it (provisioner finalizer, Kubernetes 1.33 and later).',
    'Phases: claim Pending/Bound, volume Available/Bound/Released; the pvc-protection and pv-protection finalizers that keep in-use objects Terminating.',
    'Access modes on zonal block storage: ReadWriteOnce attaches to one node (Multi-Attach error elsewhere), ReadWriteOncePod allows one pod, ReadWriteMany cannot be provisioned.',
    'Scheduler messages: volume node affinity conflicts, unbound immediate claims, missing claims.',
  ],
  leavesOut: [
    'File storage (NFS, CephFS) where ReadWriteMany works and ReadWriteOnce is often not enforced across nodes.',
    'Static provisioning beyond re-using a released volume, volume expansion, snapshots and clones, storage capacity tracking, volume attach limits.',
    'Real provisioners choose a zone themselves for Immediate binding (here always zone-b) and take time to create, attach and mount volumes.',
    'Scheduler tails in messages (preemption details) are omitted.',
  ],
  links: [
    { label: 'Kubernetes: persistent volumes (lifecycle, reclaiming)', url: 'https://kubernetes.io/docs/concepts/storage/persistent-volumes/' },
    { label: 'Kubernetes: storage object in use protection', url: 'https://kubernetes.io/docs/concepts/storage/persistent-volumes/#storage-object-in-use-protection' },
    { label: 'Kubernetes: reserving a PersistentVolume', url: 'https://kubernetes.io/docs/concepts/storage/persistent-volumes/#reserving-a-persistentvolume' },
    { label: 'Kubernetes: access modes', url: 'https://kubernetes.io/docs/concepts/storage/persistent-volumes/#access-modes' },
    { label: 'Kubernetes: StorageClass volume binding mode', url: 'https://kubernetes.io/docs/concepts/storage/storage-classes/#volume-binding-mode' },
    { label: 'OpenShift 4.21: understanding persistent storage', url: 'https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/storage/understanding-persistent-storage' },
    { label: 'OpenShift 4.21: dynamic provisioning', url: 'https://docs.redhat.com/en/documentation/openshift_container_platform/4.21/html/storage/dynamic-provisioning' },
  ],
}

const PHASE_TONE: Record<string, Tone> = { Bound: 'ok', Pending: 'warn', Available: 'info', Released: 'violet', Terminating: 'bad', Running: 'ok', ContainerCreating: 'warn' }

export default function StorageSim() {
  const [s, setS] = useState<StorageState>(() => initialStorage({ bindingMode: 'WaitForFirstConsumer', reclaimPolicy: 'Delete' }))
  const [msg, announce] = useAnnouncer()
  const sum = storageSummary(s)

  const apply = (next: StorageState) => {
    setS(next)
    if (next === s) {
      announce('No change.')
      return
    }
    const fresh = next.log.slice(s.log.length)
    announce(fresh.map((l) => l.text).join(' ') || 'Done.')
  }
  const setSc = (patch: Partial<StorageState['sc']>) => setS((cur) => ({ ...cur, sc: { ...cur.sc, ...patch } }))

  const challenges: Challenge[] = [
    {
      id: 'wffc',
      title: 'Wait for the consumer: get a claim that stays Pending until a pod uses it, then binds in that pod\'s zone.',
      hint: 'WaitForFirstConsumer, create the claim first, then a pod.',
      done: s.markers.includes('wffc-wait') && s.markers.includes('wffc-bound') && s.pvc?.phase === 'Bound',
    },
    {
      id: 'zone',
      title: 'Make a pod Pending because its volume was created in another zone.',
      hint: 'Immediate binding picks a zone before any pod exists. Pin the pod to the other zone.',
      done: s.markers.includes('zone-conflict') && s.pods.some((p) => p.phase === 'Pending'),
    },
    {
      id: 'recover',
      title: 'Recover deleted data: delete the claim, then get a new claim "data" bound to the old volume with orders.db intact.',
      hint: 'Only a retained volume survives its claim. Released volumes are not reused automatically: an admin has to make the PV Available for the claim.',
      done: s.markers.includes('data-recovered'),
    },
  ]

  const unscheduled = s.pods.filter((p) => !p.node)
  return (
    <SimShell
      id="storage"
      title="Claims, volumes and storage classes"
      scenario={
        <>
          <p>
            An app in project <code>shop</code> needs a 10Gi volume called <code>data</code> from the <code>zonal-block</code> StorageClass (a CSI block driver: each disk lives in one zone). The cluster has two zones with two workers each.
          </p>
          <p>Create the claim and pods, delete things, and follow where the data actually lives.</p>
        </>
      }
      predict={PREDICT}
      scope={SCOPE}
      challenges={challenges}
      announcement={msg}
    >
      <div className="sim-work">
        <div className="sim-col">
          <Panel title="StorageClass zonal-block" aside={<Chip tone="muted">provisioner: block.csi.example.com</Chip>}>
            <div className="sim-form">
              <Segmented<StorageState['sc']['bindingMode']>
                label="volumeBindingMode"
                value={s.sc.bindingMode}
                onChange={(v) => setSc({ bindingMode: v })}
                options={[
                  { value: 'WaitForFirstConsumer', label: 'WaitForFirstConsumer' },
                  { value: 'Immediate', label: 'Immediate' },
                ]}
              />
              <Segmented<StorageState['sc']['reclaimPolicy']>
                label="reclaimPolicy"
                value={s.sc.reclaimPolicy}
                onChange={(v) => setSc({ reclaimPolicy: v })}
                options={[
                  { value: 'Delete', label: 'Delete' },
                  { value: 'Retain', label: 'Retain' },
                ]}
                hint="Copied into each PV when it is provisioned: changing it later does not change existing PVs."
              />
            </div>
          </Panel>
          <Panel title="Claim and pods">
            <div className="sim-form">
              <SelectField<AccessMode>
                label="PVC accessModes (next claim)"
                value={s.mode}
                onChange={(v) => setS((cur) => ({ ...cur, mode: v }))}
                options={[
                  { value: 'ReadWriteOnce', label: 'ReadWriteOnce (RWO)' },
                  { value: 'ReadWriteOncePod', label: 'ReadWriteOncePod (RWOP)' },
                  { value: 'ReadWriteMany', label: 'ReadWriteMany (RWX)' },
                ]}
              />
              <SelectField<StorageState['podZone']>
                label="Pod nodeSelector"
                value={s.podZone}
                onChange={(v) => setS((cur) => ({ ...cur, podZone: v }))}
                options={[
                  { value: 'zone-a', label: 'topology.kubernetes.io/zone=zone-a' },
                  { value: 'zone-b', label: 'topology.kubernetes.io/zone=zone-b' },
                  { value: 'any', label: 'none (any zone)' },
                ]}
              />
              <Segmented<StorageState['pod2Node']>
                label="Second pod lands on"
                value={s.pod2Node}
                onChange={(v) => setS((cur) => ({ ...cur, pod2Node: v }))}
                options={[
                  { value: 'other', label: 'another node' },
                  { value: 'same', label: 'the same node' },
                ]}
              />
              <div className="sim-actions">
                <Btn variant="primary" onClick={() => apply(stCreatePVC(s))} disabled={!!s.pvc}>
                  Create PVC data
                </Btn>
                <Btn variant="primary" onClick={() => apply(stCreatePod(s))} disabled={s.pods.length >= 2}>
                  Create pod {s.pods.some((p) => p.name === 'app-1') ? 'app-2' : 'app-1'}
                </Btn>
                <Btn variant="danger" onClick={() => apply(stDeletePVC(s))} disabled={!s.pvc || s.pvc.terminating}>
                  oc delete pvc data
                </Btn>
              </div>
            </div>
          </Panel>
        </div>

        <div className="sim-col">
          <Panel title="API objects">
            <div className="sim-objs">
              <div className="sim-obj" data-kind="pvc">
                <div className="sim-obj-head">
                  <Chip tone="accent">PersistentVolumeClaim</Chip>
                  <span className="sim-mono sim-strong">data</span>
                  <Chip tone={PHASE_TONE[sum.pvcPhase] || 'muted'}>{sum.pvcPhase}</Chip>
                </div>
                {s.pvc ? (
                  <p className="sim-obj-spec">
                    {ACCESS_SHORT[s.pvc.mode]} · 10Gi · volume <code>{s.pvc.volume ?? '—'}</code>
                    {s.pvc.reason && ` · ${s.pvc.reason}`}
                  </p>
                ) : (
                  <p className="sim-obj-spec">not created</p>
                )}
              </div>
              {s.pvs.map((pv) => (
                <PVCard key={pv.name} pv={pv} onDelete={() => apply(stDeletePV(s, pv.name))} onReserve={() => apply(stReservePV(s, pv.name))} onPatch={() => apply(stPatchReclaim(s, pv.name, pv.reclaim === 'Delete' ? 'Retain' : 'Delete'))} />
              ))}
              {s.pods.map((p) => (
                <div className="sim-obj" key={p.name} data-kind="pod">
                  <div className="sim-obj-head">
                    <Chip tone="info">Pod</Chip>
                    <span className="sim-mono sim-strong">{p.name}</span>
                    <Chip tone={PHASE_TONE[p.phase] || 'muted'}>{p.phase}</Chip>
                  </div>
                  <p className="sim-obj-spec">
                    {p.node ? `on ${p.node}` : 'not scheduled'}
                    {p.reason && ` · ${p.reason}`}
                  </p>
                  <div className="sim-actions">
                    <Btn variant="danger" onClick={() => apply(stDeletePod(s, p.name))}>
                      oc delete pod {p.name}
                    </Btn>
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Where the data lives">
            <div className="sim-zones">
              {['zone-a', 'zone-b'].map((z) => (
                <section key={z} className="sim-zone" aria-label={z}>
                  <p className="sim-sub">{z}</p>
                  <ul className="sim-zone-nodes">
                    {ST_NODES.filter((n) => n.zone === z).map((n) => {
                      const pods = s.pods.filter((p) => p.node === n.name)
                      return (
                        <li key={n.name} className="sim-zone-node">
                          <span className="sim-mono">{n.name}</span>
                          <span className="sim-chips">
                            {pods.map((p) => (
                              <Chip key={p.name} tone={p.phase === 'Running' ? 'ok' : 'warn'}>
                                {p.name}
                              </Chip>
                            ))}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                  {s.backends
                    .filter((b) => b.zone === z)
                    .map((b) => (
                      <Disk key={b.id} b={b} pv={s.pvs.find((p) => p.backend === b.id)} />
                    ))}
                </section>
              ))}
            </div>
            {unscheduled.length > 0 && (
              <p className="sim-note">
                Not scheduled: {unscheduled.map((p) => p.name).join(', ')} ({unscheduled[0].reason || 'Pending'}).
              </p>
            )}
            {sum.orphanedBackends.length > 0 && <p className="sim-note">A disk with no PV object is invisible to Kubernetes but still exists (and is still billed) on the storage system.</p>}
          </Panel>

          <Panel title="Events and controller actions">
            <Log
              items={s.log}
              keyOf={(l) => l.n}
              initial={7}
              empty="Nothing yet. Create the claim or a pod."
              render={(l) => (
                <>
                  <div className="sim-log-meta">
                    <Chip tone={l.who === 'you' ? 'accent' : l.who === 'admin' ? 'violet' : l.who === 'scheduler' ? 'info' : l.who === 'kubelet' ? 'ok' : 'muted'}>{l.who}</Chip>
                  </div>
                  <span className={l.who === 'you' || l.who === 'admin' ? 'sim-mono' : undefined}>{l.text}</span>
                </>
              )}
            />
          </Panel>
        </div>
      </div>
    </SimShell>
  )
}

function PVCard({ pv, onDelete, onReserve, onPatch }: { pv: StPV; onDelete: () => void; onReserve: () => void; onPatch: () => void }) {
  return (
    <div className="sim-obj" data-kind="pv">
      <div className="sim-obj-head">
        <Chip tone="violet">PersistentVolume</Chip>
        <span className="sim-mono sim-strong">{pv.name.slice(0, 16)}…</span>
        <Chip tone={PHASE_TONE[pv.terminating ? 'Terminating' : pv.phase]}>{pv.terminating ? `Terminating (${pv.phase})` : pv.phase}</Chip>
      </div>
      <p className="sim-obj-spec">
        {ACCESS_SHORT[pv.mode]} · reclaim <strong>{pv.reclaim}</strong> · {pv.zone} · claimRef {pv.claimName ? `shop/${pv.claimName}${pv.claimUid ? '' : ' (no uid: reserved)'}` : '—'} · backend <code>{pv.backend}</code>
      </p>
      <div className="sim-actions">
        <Btn variant="danger" onClick={onDelete} disabled={pv.terminating}>
          oc delete pv
        </Btn>
        <Btn onClick={onPatch}>set reclaim {pv.reclaim === 'Delete' ? 'Retain' : 'Delete'}</Btn>
        {pv.phase === 'Released' && (
          <Btn variant="primary" onClick={onReserve}>
            admin: make Available for claim data
          </Btn>
        )}
      </div>
    </div>
  )
}

function Disk({ b, pv }: { b: StBackend; pv: StPV | undefined }) {
  const state = b.deleted ? 'deleted' : !pv ? 'orphaned' : b.attachedTo ? 'attached' : 'detached'
  return (
    <div className="sim-disk" data-state={state}>
      <span className="sim-disk-icon" aria-hidden="true" />
      <span className="sim-disk-text">
        <span className="sim-mono sim-strong">{b.id}</span>
        <span className="sim-muted">
          {state === 'deleted' ? 'deleted with its data' : state === 'orphaned' ? 'no PV points to it any more' : state === 'attached' ? `attached to ${b.attachedTo}` : 'detached'}
          {!b.deleted && ` · files: ${b.files.length ? b.files.join(', ') : 'empty'}`}
        </span>
      </span>
    </div>
  )
}
