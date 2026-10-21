"""Cluster Explorer: read-only inspection with the `reader` identity (cluster-reader ServiceAccount).

Only allowlisted kinds can be listed or shown. Secrets are never read. managedFields are stripped.
If the reader is not set up, the learner can still explore its own academy-* projects.
"""
from __future__ import annotations

import re

import yaml

from . import environment, kube

# kind -> (oc resource name, namespaced)
KINDS: dict[str, tuple[str, bool]] = {
    "Namespace": ("namespaces", False),
    "Node": ("nodes", False),
    "ClusterVersion": ("clusterversions.config.openshift.io", False),
    "ClusterOperator": ("clusteroperators.config.openshift.io", False),
    "MachineConfigPool": ("machineconfigpools.machineconfiguration.openshift.io", False),
    "MachineConfig": ("machineconfigs.machineconfiguration.openshift.io", False),
    "Scheduler": ("schedulers.config.openshift.io", False),
    "Infrastructure": ("infrastructures.config.openshift.io", False),
    "Network": ("networks.config.openshift.io", False),
    "IngressConfig": ("ingresses.config.openshift.io", False),
    "OAuth": ("oauths.config.openshift.io", False),
    "StorageClass": ("storageclasses.storage.k8s.io", False),
    "PersistentVolume": ("persistentvolumes", False),
    "CSIDriver": ("csidrivers.storage.k8s.io", False),
    "SecurityContextConstraints": ("securitycontextconstraints.security.openshift.io", False),
    "ClusterRole": ("clusterroles.rbac.authorization.k8s.io", False),
    "ClusterRoleBinding": ("clusterrolebindings.rbac.authorization.k8s.io", False),
    "CustomResourceDefinition": ("customresourcedefinitions.apiextensions.k8s.io", False),
    "PriorityClass": ("priorityclasses.scheduling.k8s.io", False),
    "APIService": ("apiservices.apiregistration.k8s.io", False),
    "Pod": ("pods", True),
    "Deployment": ("deployments.apps", True),
    "ReplicaSet": ("replicasets.apps", True),
    "DaemonSet": ("daemonsets.apps", True),
    "StatefulSet": ("statefulsets.apps", True),
    "Job": ("jobs.batch", True),
    "CronJob": ("cronjobs.batch", True),
    "Service": ("services", True),
    "EndpointSlice": ("endpointslices.discovery.k8s.io", True),
    "Route": ("routes.route.openshift.io", True),
    "IngressController": ("ingresscontrollers.operator.openshift.io", True),
    "ConfigMap": ("configmaps", True),
    "Event": ("events", True),
    "NetworkPolicy": ("networkpolicies.networking.k8s.io", True),
    "PersistentVolumeClaim": ("persistentvolumeclaims", True),
    "ServiceAccount": ("serviceaccounts", True),
    "Role": ("roles.rbac.authorization.k8s.io", True),
    "RoleBinding": ("rolebindings.rbac.authorization.k8s.io", True),
    "ImageStream": ("imagestreams.image.openshift.io", True),
    "BuildConfig": ("buildconfigs.build.openshift.io", True),
    "ResourceQuota": ("resourcequotas", True),
    "LimitRange": ("limitranges", True),
    "PodDisruptionBudget": ("poddisruptionbudgets.policy", True),
    "Lease": ("leases.coordination.k8s.io", True),
    "Subscription": ("subscriptions.operators.coreos.com", True),
    "ClusterServiceVersion": ("clusterserviceversions.operators.coreos.com", True),
    "CatalogSource": ("catalogsources.operators.coreos.com", True),
    "InstallPlan": ("installplans.operators.coreos.com", True),
}
NAME_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9.:_-]{0,251}[a-zA-Z0-9])?$")
NS_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class Bad(ValueError):
    pass


def _reader() -> bool:
    """The reader counts only when it points at the learner's cluster: a reader kubeconfig left from another cluster
    would show that cluster's objects as this one's."""
    return bool(kube.whoami("reader").get("connected")) and environment.same_cluster("reader")


def _identity(ns: str | None) -> str:
    if _reader():
        return "reader"
    if ns and ns.startswith("academy-") and ns != "academy-system" and kube.whoami("learner").get("connected"):
        return "learner"
    raise Bad("Set up the read-only explorer identity (Connections) to inspect cluster objects.")


def _resolve(kind: str, ns: str | None) -> tuple[str, bool]:
    if kind not in KINDS:
        raise Bad(f"kind {kind} is not available in the explorer")
    res, namespaced = KINDS[kind]
    if namespaced and ns and not NS_RE.match(ns):
        raise Bad("invalid namespace")
    return res, namespaced


def strip(obj: dict) -> dict:
    md = obj.get("metadata", {})
    md.pop("managedFields", None)
    ann = md.get("annotations") or {}
    ann.pop("kubectl.kubernetes.io/last-applied-configuration", None)
    return obj


def list_kind(kind: str, ns: str | None) -> dict:
    res, namespaced = _resolve(kind, ns)
    ident = _identity(ns if namespaced else None)
    args = ["get", res] + (["-n", ns] if namespaced and ns else (["-A"] if namespaced else []))
    if ident == "learner" and not ns:
        raise Bad("choose an academy-* namespace")
    obj, r = kube.oc_json(ident, args, timeout=30)
    if obj is None:
        return {"ok": False, "identity": ident, "error": kube.redact(r.stderr.strip())[-400:]}
    items = []
    for o in obj.get("items", [])[:600]:
        md = o.get("metadata", {})
        items.append({"name": md.get("name"), "namespace": md.get("namespace"), "created": md.get("creationTimestamp"), "status": brief(kind, o)})
    return {"ok": True, "identity": ident, "kind": kind, "items": items, "truncated": len(obj.get("items", [])) > 600}


def get_one(kind: str, ns: str | None, name: str) -> dict:
    res, namespaced = _resolve(kind, ns)
    if not NAME_RE.match(name or ""):
        raise Bad("invalid name")
    ident = _identity(ns if namespaced else None)
    args = ["get", res, name] + (["-n", ns] if namespaced and ns else [])
    obj, r = kube.oc_json(ident, args, timeout=30)
    if obj is None:
        return {"ok": False, "identity": ident, "error": kube.redact(r.stderr.strip())[-400:]}
    obj = strip(obj)
    return {"ok": True, "identity": ident, "yaml": kube.redact(yaml.safe_dump(obj, sort_keys=False, width=140))[:200000], "summary": brief(kind, obj)}


def brief(kind: str, o: dict) -> str:
    st, sp = o.get("status") or {}, o.get("spec") or {}
    if kind == "ClusterOperator":
        cond = {c["type"]: c["status"] for c in st.get("conditions", [])}
        v = next((x.get("version") for x in st.get("versions", []) if x.get("name") == "operator"), "")
        return f"Available={cond.get('Available')} Progressing={cond.get('Progressing')} Degraded={cond.get('Degraded')} {v}"
    if kind == "Node":
        ready = next((c["status"] for c in st.get("conditions", []) if c["type"] == "Ready"), "?")
        roles = [k.split("/", 1)[1] for k in o["metadata"].get("labels", {}) if k.startswith("node-role.kubernetes.io/")]
        return f"Ready={ready} roles={','.join(roles)} cpu={st.get('allocatable', {}).get('cpu')} mem={st.get('allocatable', {}).get('memory')} kubelet={st.get('nodeInfo', {}).get('kubeletVersion')}"
    if kind == "ClusterVersion":
        return f"{st.get('desired', {}).get('version')} channel={sp.get('channel', '-')}"
    if kind == "MachineConfigPool":
        return f"machines={st.get('machineCount')} ready={st.get('readyMachineCount')} updated={st.get('updatedMachineCount')} degraded={st.get('degradedMachineCount')}"
    if kind == "Pod":
        cs = st.get("containerStatuses") or []
        return f"{st.get('phase')} ready={sum(1 for c in cs if c.get('ready'))}/{len(cs)} restarts={sum(c.get('restartCount', 0) for c in cs)} node={sp.get('nodeName', '-')}"
    if kind in ("Deployment", "StatefulSet"):
        return f"ready={st.get('readyReplicas', 0)}/{sp.get('replicas', 0)}"
    if kind == "DaemonSet":
        return f"ready={st.get('numberReady', 0)}/{st.get('desiredNumberScheduled', 0)}"
    if kind == "StorageClass":
        default = o["metadata"].get("annotations", {}).get("storageclass.kubernetes.io/is-default-class") == "true"
        return f"provisioner={o.get('provisioner')} binding={o.get('volumeBindingMode')} reclaim={o.get('reclaimPolicy')}{' (default)' if default else ''}"
    if kind == "SecurityContextConstraints":
        return f"priority={o.get('priority')} runAsUser={(o.get('runAsUser') or {}).get('type')} privileged={o.get('allowPrivilegedContainer')}"
    if kind == "Route":
        return f"{sp.get('host')} → {sp.get('to', {}).get('name')} tls={(sp.get('tls') or {}).get('termination', '-')}"
    if kind == "Service":
        return f"{sp.get('type')} {sp.get('clusterIP')} ports={[p.get('port') for p in sp.get('ports', [])]}"
    if kind == "PersistentVolumeClaim":
        return f"{st.get('phase')} {sp.get('storageClassName')}"
    if kind == "Event":
        return f"{o.get('type')} {o.get('reason')}: {(o.get('message') or '')[:120]}"
    if kind == "Lease":
        return f"holder={sp.get('holderIdentity')}"
    if kind == "ClusterServiceVersion":
        return f"{st.get('phase')} {sp.get('version', '')}"
    return ""


def overview() -> dict:
    """Health overview from real objects: version, operators, nodes, scheduler profile, platform."""
    ident = "reader" if _reader() else None
    if not ident:
        return {"ok": False, "error": "Set up the read-only explorer identity to see cluster health."}
    out: dict = {"ok": True}
    cv, r = kube.oc_json(ident, ["get", "clusterversion", "version"])
    if cv is None:
        return {"ok": False, "error": kube.redact(r.stderr.strip())[-300:]}
    out["version"] = cv.get("status", {}).get("desired", {}).get("version")
    out["history"] = [h.get("version") + " " + h.get("state", "") for h in cv.get("status", {}).get("history", [])[:3]]
    co, _ = kube.oc_json(ident, ["get", "clusteroperators"])
    ops = []
    for o in (co or {}).get("items", []):
        cond = {c["type"]: c for c in o.get("status", {}).get("conditions", [])}
        ops.append({
            "name": o["metadata"]["name"],
            "available": cond.get("Available", {}).get("status"),
            "progressing": cond.get("Progressing", {}).get("status"),
            "degraded": cond.get("Degraded", {}).get("status"),
            "message": (cond.get("Degraded", {}).get("message") if cond.get("Degraded", {}).get("status") == "True" else cond.get("Progressing", {}).get("message") if cond.get("Progressing", {}).get("status") == "True" else "") or "",
        })
    out["operators"] = ops
    nodes, _ = kube.oc_json(ident, ["get", "nodes"])
    out["nodes"] = [{"name": n["metadata"]["name"], "status": brief("Node", n), "taints": n.get("spec", {}).get("taints", []),
                     "capacity": n.get("status", {}).get("capacity", {}), "allocatable": n.get("status", {}).get("allocatable", {})} for n in (nodes or {}).get("items", [])]
    sch, _ = kube.oc_json(ident, ["get", "schedulers.config.openshift.io", "cluster"])
    out["scheduler"] = (sch or {}).get("spec", {})
    infra, _ = kube.oc_json(ident, ["get", "infrastructures.config.openshift.io", "cluster"])
    ist = (infra or {}).get("status", {})
    out["platform"] = {"type": (ist.get("platformStatus") or {}).get("type"), "controlPlaneTopology": ist.get("controlPlaneTopology"), "infrastructureTopology": ist.get("infrastructureTopology")}
    net, _ = kube.oc_json(ident, ["get", "networks.config.openshift.io", "cluster"])
    out["network"] = {"type": (net or {}).get("status", {}).get("networkType"), "clusterNetwork": (net or {}).get("status", {}).get("clusterNetwork"), "serviceNetwork": (net or {}).get("status", {}).get("serviceNetwork")}
    return out
