import './sims.css'
import DriftSim from './DriftSim'
import ProbesSim from './ProbesSim'
import PermsSim from './PermsSim'
import RbacSim from './RbacSim'
import ReconcileSim from './ReconcileSim'
import RolloutSim from './RolloutSim'
import SchedulerSim from './SchedulerSim'
import StorageSim from './StorageSim'
import TrafficSim from './TrafficSim'
import { withReset } from './ui'

export type SimDef = { id: string; title: string; summary: string; concepts: string[]; Component: () => JSX.Element }

const MODELS: SimDef[] = [
  {
    id: 'scheduler',
    title: 'Scheduler: filter and score',
    summary: 'Watch kube-scheduler filter four nodes and score the survivors with weighted plugins; switch OpenShift scheduler profiles.',
    concepts: ['k8s.scheduler', 'k8s.affinity', 'k8s.requests-limits'],
    Component: SchedulerSim,
  },
  {
    id: 'reconcile',
    title: 'Controllers and reconciliation',
    summary: 'Delete a pod, scale, edit a ReplicaSet behind the Deployment\'s back or change the template, then step through each control loop: observe, diff, act.',
    concepts: ['k8s.controllers', 'k8s.deployment', 'k8s.replicaset'],
    Component: ReconcileSim,
  },
  {
    id: 'rollout',
    title: 'Rolling update, step by step',
    summary: 'Step through the Deployment controller as it surges and scales down ReplicaSets; break the image, hit the progress deadline and roll back.',
    concepts: ['k8s.rollout', 'deploy.strategies'],
    Component: RolloutSim,
  },
  {
    id: 'probes',
    title: 'Probes, restarts and back-off',
    summary: 'Tune startup, readiness and liveness probes against an app script (slow start, deadlock, database outage, crash) and watch Ready, endpoints, restarts and CrashLoopBackOff on a timeline.',
    concepts: ['k8s.probes', 'k8s.pod-lifecycle'],
    Component: ProbesSim,
  },
  {
    id: 'traffic',
    title: 'Request path: Route → Service → Pod',
    summary: 'Edit a Route, Service, pods and a NetworkPolicy, send a request from the router or a client pod, and see exactly where it stops: router 503, refused, timeout or DNS failure.',
    concepts: ['net.services', 'net.endpointslices', 'net.routes', 'net.policy'],
    Component: TrafficSim,
  },
  {
    id: 'rbac',
    title: 'Who can do what: RBAC and SCCs',
    summary: 'Ask oc auth can-i for users, groups and ServiceAccounts and see every binding path that grants it (RBAC has no deny); then watch a simplified SCC admission choose restricted-v2 or anyuid.',
    concepts: ['sec.rbac', 'sec.serviceaccounts', 'sec.scc'],
    Component: RbacSim,
  },
  {
    id: 'storage',
    title: 'Claims, volumes and storage classes',
    summary: 'Create and delete PVCs, pods and PVs on a zonal StorageClass: Immediate vs WaitForFirstConsumer, Delete vs Retain, access modes, finalizers, and where the data really lives.',
    concepts: ['storage.pvc', 'storage.class'],
    Component: StorageSim,
  },
  {
    id: 'drift',
    title: 'GitOps drift and sync',
    summary: 'Change Git or the live cluster, then let Argo CD reconcile with or without self-heal and prune; compare its OutOfSync view with what oc diff reports.',
    concepts: ['gitops.drift', 'deploy.declarative'],
    Component: DriftSim,
  },
  {
    id: 'perms',
    title: 'Who may touch this file? Linux permissions and OpenShift’s arbitrary UID',
    summary: 'Predict file and directory access, trace every ancestor and permission bit, and fix an image for OpenShift’s arbitrary UID with group 0 permissions.',
    concepts: ['container.security', 'sec.scc'],
    Component: PermsSim,
  },
]

/** Every model offers the same "Reset model" (sims/ui.tsx withReset): it restores all of the model's state. */
export const SIMS: SimDef[] = MODELS.map((s) => ({ ...s, Component: withReset(s.id, s.Component) }))
