"""Which cluster is connected, may it be changed, and what can it do?

Classes:
  practice   no cluster (ACADEMY_CLUSTER=off, or `oc` missing): recorded outputs only.
  read-only  a cluster is connected but this installation's operator has not approved it for training labs.
             Reads are allowed; nothing is created, changed or deleted (except cleaning up what the ledger
             proves the academy created earlier).
  training   the operator approved this exact cluster for live labs. Approval is a local action, stored in
             data/cluster-approvals.json, and is bound to a fingerprint (API URL + the CA that the learner's
             kubeconfig trusts). If the kubeconfig later points elsewhere, the fingerprint changes and the
             cluster is read-only again. An object inside the cluster can never grant this (anyone with the
             right permissions could create it); approval is the operator's decision, not the cluster's.

OpenShift Local (CRC) is detected (API host api.crc.testing and `crc status` running) and the approval screen
says so, but detection is only a hint: approval is always explicit.

Capabilities are probed as the learner with SelfSubjectAccessReviews (`oc auth can-i`) and API discovery. A
probe that fails stays "unknown"; unknown never counts as available.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import yaml

from . import config, kube

APPROVALS = config.DATA_DIR / "cluster-approvals.json"
_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}


# ---------------------------------------------------------------- fingerprint and approval
def _cluster_entry(identity: kube.Identity = "learner") -> dict | None:
    return _cluster_entry_of(kube.kubeconfig(identity))


def _cluster_entry_of(p: Path) -> dict | None:
    """Server, CA digest and TLS setting of the current context of the kubeconfig at `p`."""
    try:
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(d, dict):  # empty or not a kubeconfig at all
        return None
    ctx_name = d.get("current-context")
    ctx = next((c["context"] for c in d.get("contexts", []) if c.get("name") == ctx_name), None)
    name = (ctx or {}).get("cluster")
    cl = next((c["cluster"] for c in d.get("clusters", []) if c.get("name") == name), None) or (d.get("clusters") or [{}])[0].get("cluster")
    if not cl:
        return None
    ca = b""
    if cl.get("certificate-authority-data"):
        import base64

        ca = base64.b64decode(cl["certificate-authority-data"])
    elif cl.get("certificate-authority"):
        f = Path(cl["certificate-authority"])
        f = f if f.is_absolute() else p.parent / f
        try:
            ca = f.read_bytes()
        except OSError:
            ca = b""
    return {"server": cl.get("server", ""), "ca_sha256": hashlib.sha256(ca).hexdigest() if ca else "", "insecure": bool(cl.get("insecure-skip-tls-verify"))}


def fingerprint(identity: kube.Identity = "learner") -> dict | None:
    """API URL + trusted CA of an identity's kubeconfig. None if not connected, and always None when cluster access is
    off: a practice server must not reveal which cluster the data directory's kubeconfigs point at."""
    if not config.cluster_enabled():
        return None
    e = _cluster_entry(identity)
    if not e or not e["server"]:
        return None
    fp = hashlib.sha256(f"{e['server']}|{e['ca_sha256']}".encode()).hexdigest()[:16]
    return {**e, "id": fp, "host": urlparse(e["server"]).hostname or ""}


def _read_approvals() -> dict:
    try:
        d = json.loads(APPROVALS.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def crc_detected(fp: dict | None) -> bool:
    if not fp or fp["host"] != "api.crc.testing":
        return False
    st = kube.crc_status()
    return st.get("openshiftStatus") == "Running"


def current() -> dict:
    """The environment class and why."""
    if not config.cluster_enabled():
        return {"class": "practice", "reason": "practice mode: no cluster is used"}
    fp = fingerprint("learner")
    if not fp:
        return {"class": "read-only", "connected": False, "needs": "learner", "reason": "no learner account is connected: connect it first (My cluster → Connections, step 1)"}
    approved = _read_approvals().get(fp["id"])
    out = {"connected": True, "api": fp["server"], "host": fp["host"], "fingerprint": fp["id"], "crc": crc_detected(fp), "tls_verified": not fp["insecure"] and bool(fp["ca_sha256"])}
    if not out["tls_verified"]:
        # approval needs a verified connection, and a kubeconfig that stopped verifying TLS is not the approved one
        return {**out, "class": "read-only", "needs": "tls", "reason": "the learner's kubeconfig no longer verifies the API server's certificate, so the approval does not apply: log out and connect the learner account again (My cluster → Connections, step 1)"}
    if approved:
        return {**out, "class": "training", "approved": approved, "reason": "approved for training labs by the operator of this installation"}
    return {**out, "class": "read-only", "needs": "approval", "reason": "not approved for training labs yet: the academy only reads from this cluster (approve it in My cluster → Connections, step 2)"}


def _typed_matches(typed: str, fp: dict) -> bool:
    """The operator typed this cluster: its API host exactly, or its API address exactly as the page shows it (an ending
    slash allowed). Nothing else: no other scheme, port, path or user part, and no whitespace inside."""
    t = typed.strip().lower()
    if not t or any(ch.isspace() for ch in t):
        return False
    server = fp["server"].lower()
    return t == fp["host"].lower() or t in (server, server + "/")


def approve(typed_host: str, scope_note: str = "") -> dict:
    """Approve the learner's current cluster for training labs. The operator must type the API host (no default)."""
    fp = fingerprint("learner")
    if not fp:
        raise ValueError("connect the learner identity first")
    if not _typed_matches(typed_host, fp):
        raise ValueError(f"type the API host {fp['host']} to approve this cluster")
    if fp["insecure"] or not fp["ca_sha256"]:
        raise ValueError("the learner's kubeconfig does not verify the API server certificate; approval needs a trusted CA")
    with _lock:
        d = _read_approvals()
        d[fp["id"]] = {"api": fp["server"], "ca_sha256": fp["ca_sha256"], "approved_at": int(time.time()), "crc": crc_detected(fp), "note": scope_note[:200]}
        _write_atomic(APPROVALS, d)
    _cache.clear()
    return current()


def admin_target_is_approved_cluster() -> bool:
    """Would connecting kubeadmin reach the cluster the learner is on (the approved one)? Checked before any login: the
    operator's admin kubeconfig (ACADEMY_KUBECONFIG_ADMIN), or the CRC login to the configured API with CRC's CA."""
    learner = _cluster_entry("learner")
    if not learner:
        return False
    ext = config.EXTERNAL_KUBECONFIG.get("admin")
    if ext:
        target = _cluster_entry_of(Path(ext).expanduser())
    else:
        ca = kube._ca_file()
        try:
            digest = hashlib.sha256(Path(ca).read_bytes()).hexdigest() if ca else ""
        except OSError:
            digest = ""
        target = {"server": config.API_SERVER, "ca_sha256": digest, "insecure": False}
    if not target:
        return False
    def same(a: str, b: str) -> bool:  # scheme and host compare without case; port and path exactly
        ua, ub = urlparse(a), urlparse(b)
        return (ua.scheme.lower(), (ua.hostname or ""), ua.port, ua.path.rstrip("/")) == (ub.scheme.lower(), (ub.hostname or ""), ub.port, ub.path.rstrip("/"))

    return same(target["server"], learner["server"]) and bool(target["ca_sha256"]) and target["ca_sha256"] == learner["ca_sha256"] and not target["insecure"]


def revoke() -> dict:
    fp = fingerprint("learner")
    with _lock:
        d = _read_approvals()
        if fp:
            d.pop(fp["id"], None)
        _write_atomic(APPROVALS, d)
    _cache.clear()
    return current()


def training() -> bool:
    return current()["class"] == "training"


# ---------------------------------------------------------------- capabilities
# SelfSubjectAccessReviews asked as the learner: (key, verb, resource, namespace or None)
ACCESS = [
    ("create-projects", "create", "projectrequests.project.openshift.io", None),
    ("list-nodes", "list", "nodes", None),
    ("list-storageclasses", "list", "storageclasses.storage.k8s.io", None),
    ("list-pvs", "list", "persistentvolumes", None),
    ("read-clusterversion", "get", "clusterversions.config.openshift.io", None),
    ("create-groups", "create", "groups.user.openshift.io", None),
]
OPTIONAL_APIS = {
    "route.openshift.io": "Routes",
    "project.openshift.io": "Projects",
    "build.openshift.io": "Builds",
    "image.openshift.io": "ImageStreams",
    "operators.coreos.com": "Operator Lifecycle Manager (OLM v0)",
    "monitoring.coreos.com": "Prometheus monitoring APIs (present does not mean user workload monitoring is enabled)",
    "argoproj.io": "Argo CD / OpenShift GitOps",
    "snapshot.storage.k8s.io": "Volume snapshots",
}


def _can_i(identity: kube.Identity, verb: str, resource: str, ns: str | None) -> bool | None:
    args = ["auth", "can-i", verb, resource] + (["-n", ns] if ns else [])
    r = kube.oc(identity, args, timeout=20)
    if r.status != "ok":
        return None
    out = r.stdout.strip().splitlines()[-1:] or [""]
    if r.code == 0 and out[0] == "yes":
        return True
    if r.code == 1 and out[0] == "no":
        return False
    return None  # anything else (errors, odd output) is unknown


def probe(force: bool = False) -> dict:
    """What the connected learner can do and which APIs exist. Cached per cluster fingerprint for 5 minutes."""
    env = current()
    if env["class"] == "practice" or not env.get("connected"):
        return {"env": env, "probed": False}
    who = kube.whoami("learner")
    try:
        stamp = kube.kubeconfig("learner").stat().st_mtime_ns
    except OSError:
        stamp = 0
    # permissions belong to a user, not to a cluster: a different user (or new credentials) is a different answer
    key = f"{env['fingerprint']}|{who.get('user')}|{stamp}"
    hit = _cache.get(key)
    if hit and not force and time.time() - hit[0] < 300:
        return hit[1]
    out: dict = {"env": env, "probed": True, "at": int(time.time())}
    out["user"] = who.get("user")
    r = kube.oc("learner", ["get", "--raw", "/version"], timeout=20)
    try:
        out["kubernetes"] = json.loads(r.stdout).get("gitVersion") if r.ok else None
    except ValueError:
        out["kubernetes"] = None
    r = kube.oc("learner", ["api-versions"], timeout=30)
    groups = {line.split("/")[0] for line in r.stdout.split()} if r.ok else None
    out["apis"] = {g: (g in groups) if groups is not None else None for g in OPTIONAL_APIS}
    out["access"] = {k: _can_i("learner", verb, res, ns) for k, verb, res, ns in ACCESS}
    out["storage"] = None
    if out["access"].get("list-storageclasses"):
        obj, _r = kube.oc_json("learner", ["get", "storageclasses"])
        if obj is not None:
            classes = []
            for sc in obj.get("items", []):
                ann = sc["metadata"].get("annotations") or {}
                classes.append({
                    "name": sc["metadata"]["name"],
                    "default": ann.get("storageclass.kubernetes.io/is-default-class") == "true",
                    "provisioner": sc.get("provisioner"),
                    "reclaimPolicy": sc.get("reclaimPolicy", "Delete"),
                    "bindingMode": sc.get("volumeBindingMode", "Immediate"),
                })
            out["storage"] = {"classes": classes, "default": next((c for c in classes if c["default"]), None)}
    out["nodes"] = None
    if out["access"].get("list-nodes"):
        obj, _r = kube.oc_json("learner", ["get", "nodes"])
        out["nodes"] = len(obj.get("items", [])) if obj is not None else None
    out["identities"] = {i: bool(kube.whoami(i).get("connected")) and same_cluster(i) for i in ("reader", "admin")}
    _cache[key] = (time.time(), out)
    return out


def invalidate() -> None:
    _cache.clear()


# ---------------------------------------------------------------- lab requirements and preflight
REQUIREMENTS = {
    "project-create": "create its own projects",
    "admin": "an administrator identity for a few clearly marked steps",
    "reader": "the read-only reader identity (cluster-wide read access) for some steps",
    "dynamic-storage": "a default StorageClass that provisions volumes on demand",
    "routes": "OpenShift Routes",
    "crc": "OpenShift Local (CRC): the steps refer to its single node, named crc",
    "olm": "the Operator Lifecycle Manager APIs",
    "cluster-objects": "creating cluster-scoped objects (needs an administrator, tracked and cleaned up by the ledger)",
}


def lab_requirements(lab) -> list[str]:
    """Explicit `requires` plus what the lab's own content shows it needs."""
    req = {"project-create", *getattr(lab, "requires", [])}
    cmds = [c for _w, c in lab.all_commands()]
    if lab.elevated_setup or any(c.as_ == "admin" and not c.skip for c in cmds):
        req.add("admin")
    if any(c.as_ == "reader" and not c.skip for c in cmds):
        req.add("reader")
    text = "\n".join([*lab.setup, *lab.break_, *lab.files.values(), *[c.stdin or "" for c in cmds]])
    if "kind: PersistentVolumeClaim" in text or "volumeClaimTemplates" in text:
        req.add("dynamic-storage")
    if "kind: Route" in text or any(c.cmd.startswith(("oc expose", "oc create route")) for c in cmds):
        req.add("routes")
    if getattr(lab, "cluster_objects", None):
        req.add("cluster-objects")
    return sorted(req)


def preflight(lab) -> dict:
    """Can this lab run here, safely and accurately? Never guesses: unknown is reported as unknown."""
    caps = probe()
    env = caps["env"]
    reqs = lab_requirements(lab)
    if env["class"] == "practice":
        return {"class": "practice", "runnable": False, "requirements": reqs, "blockers": [{"req": "cluster", "why": "practice mode: replay the recorded outputs instead"}], "notes": []}
    blockers, unknown, notes = [], [], []
    if env["class"] != "training":
        blockers.append({"req": "training", "why": env.get("reason") or "this cluster is not approved for training labs"})
    acc, apis = caps.get("access", {}), caps.get("apis", {})
    ids = caps.get("identities", {})
    checks = {
        "project-create": acc.get("create-projects"),
        "admin": ids.get("admin"),
        "reader": ids.get("reader"),
        "routes": apis.get("route.openshift.io"),
        "olm": apis.get("operators.coreos.com"),
        "crc": env.get("crc"),
        "cluster-objects": ids.get("admin"),
        "dynamic-storage": None if caps.get("storage") is None else bool((caps["storage"] or {}).get("default")),
    }
    for r in reqs:
        v = checks.get(r)
        if v is True:
            continue
        (unknown if v is None else blockers).append({"req": r, "why": REQUIREMENTS.get(r, r) + (" (could not be checked)" if v is None else " (not available)")})
    sc = (caps.get("storage") or {}).get("default")
    if "dynamic-storage" in reqs and sc and sc["reclaimPolicy"] == "Retain":
        notes.append(f"The default StorageClass `{sc['name']}` keeps volumes after their claim is deleted (reclaimPolicy Retain). "
                     "Cleanup will leave Released PersistentVolumes that only an administrator can reclaim; the academy lists them.")
    if "crc" not in reqs and env.get("crc") is False and "reader" in reqs:
        notes.append("Recorded outputs come from a single-node CRC cluster; node names and counts will differ here.")
    return {"class": env["class"], "runnable": not blockers and not unknown, "requirements": reqs, "blockers": blockers, "unknown": unknown, "notes": notes}


# ---------------------------------------------------------------- every identity must point at the same cluster
def identity_clusters() -> dict:
    """For each connected identity: its cluster fingerprint and whether it matches the learner's."""
    base = fingerprint("learner")
    out = {}
    for i in ("learner", "reader", "admin"):
        fp = fingerprint(i)  # type: ignore[arg-type]
        if fp:
            out[i] = {"api": fp["server"], "fingerprint": fp["id"], "same_cluster": bool(base) and fp["server"] == base["server"]}
    return out


def same_cluster(identity: kube.Identity) -> bool:
    """The reader and admin kubeconfigs must target the learner's API server (their CA bundles may legitimately
    differ: the reader uses a ServiceAccount token, the admin may have been imported)."""
    a, b = fingerprint(identity), fingerprint("learner")
    # same API server, and this identity's own connection verifies the server certificate
    return bool(a and b and a["server"] == b["server"] and not a["insecure"] and a["ca_sha256"])
