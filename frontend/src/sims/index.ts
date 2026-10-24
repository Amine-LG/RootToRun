import { SIM_CATALOG } from './catalog'
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
    ...SIM_CATALOG.scheduler,
    Component: SchedulerSim,
  },
  {
    id: 'reconcile',
    ...SIM_CATALOG.reconcile,
    Component: ReconcileSim,
  },
  {
    id: 'rollout',
    ...SIM_CATALOG.rollout,
    Component: RolloutSim,
  },
  {
    id: 'probes',
    ...SIM_CATALOG.probes,
    Component: ProbesSim,
  },
  {
    id: 'traffic',
    ...SIM_CATALOG.traffic,
    Component: TrafficSim,
  },
  {
    id: 'rbac',
    ...SIM_CATALOG.rbac,
    Component: RbacSim,
  },
  {
    id: 'storage',
    ...SIM_CATALOG.storage,
    Component: StorageSim,
  },
  {
    id: 'drift',
    ...SIM_CATALOG.drift,
    Component: DriftSim,
  },
  {
    id: 'perms',
    ...SIM_CATALOG.perms,
    Component: PermsSim,
  },
]

/** Every model offers the same "Reset model" (sims/ui.tsx withReset): it restores all of the model's state. */
export const SIMS: SimDef[] = MODELS.map((s) => ({ ...s, Component: withReset(s.id, s.Component) }))
