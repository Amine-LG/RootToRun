"""A durable record of everything the academy creates on a cluster, and cleanup that proves what it removed.

Rules (the user-facing summary is in README.md, "Live labs, safely"):
  * Write-ahead: an `intent` row is stored before the academy creates anything; the object's UID is stored right
    after. A crash between the two is reconciled on the next pass by reading the object back.
  * Ownership is proven by the recorded UID (and, for projects, the academy marker), never by a name pattern.
  * Deletion sends the recorded UID as a server-side precondition: if the name now belongs to a different object
    (deleted and recreated by someone else), the API server refuses (409) and nothing is deleted.
  * Only an API NotFound proves that something is gone. A normal user loses sight of a project while it is still
    terminating (its RoleBindings are deleted first), so the learner's view alone is reported as "no longer
    visible", not as gone. The reader identity (cluster-reader) is used to confirm.
  * Finalizers are never removed. A namespace stuck on finalizers is reported with the conditions the API server
    gives (NamespaceFinalizersRemaining / NamespaceContentRemaining) and the authorised action needed.
  * Volumes left by a Retain StorageClass are recorded while the lab runs (claim UID → volume) and reported after
    cleanup; reclaiming them needs an administrator and is never implicit.
  * The ledger is SQLite (WAL) in the data directory. If it cannot be read, cleanup refuses to guess.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import config, kube

DB = config.DATA_DIR / "ledger.db"
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, lab_id TEXT NOT NULL, cluster TEXT NOT NULL, api TEXT, created_at REAL, updated_at REAL,
  state TEXT NOT NULL,              -- active | cleaning | clean | blocked
  cleanup_requested_at REAL, detail TEXT
);
CREATE TABLE IF NOT EXISTS effects (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
  kind TEXT NOT NULL, name TEXT NOT NULL, namespace TEXT, scope TEXT NOT NULL, path TEXT NOT NULL,
  uid TEXT, identity TEXT NOT NULL,  -- who may delete it
  phase TEXT NOT NULL,               -- intent | applied | failed | deleting | gone | not-visible | blocked | replaced | unknown
  detail TEXT, created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS volumes (
  pv TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(id), namespace TEXT, claim TEXT, claim_uid TEXT,
  phase TEXT NOT NULL,               -- bound | released-needs-admin | gone | kept | reclaimed | unknown
  detail TEXT, noted_at REAL, updated_at REAL, PRIMARY KEY (pv, run_id)
);
"""
TERMINAL_OK = {"gone", "failed"}


class LedgerUnavailable(RuntimeError):
    pass


# API answers that prove a request was refused and nothing was created (Kubernetes Status reasons). Timeouts,
# InternalError, ServiceUnavailable or a lost connection prove nothing: the object may exist.
REJECTED = ("(AlreadyExists)", "(Forbidden)", "(Invalid)", "(BadRequest)", "(Unauthorized)", "(NotFound)", "(MethodNotAllowed)")


def rejected(stderr: str) -> bool:
    return any(r in (stderr or "") for r in REJECTED)


def _db() -> sqlite3.Connection:
    try:
        DB.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=FULL")
        c.executescript(SCHEMA)
        problems = [r[0] for r in c.execute("PRAGMA integrity_check")]
        if problems != ["ok"]:
            c.close()
            raise sqlite3.DatabaseError("integrity check failed: " + "; ".join(problems[:3]))
        return c
    except sqlite3.DatabaseError as e:
        raise LedgerUnavailable(f"the cleanup ledger ({DB}) cannot be read: {e}. Destructive recovery is disabled until it is fixed.") from e


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------- recording effects
def begin_run(lab_id: str, cluster: str, api: str = "") -> str:
    """The active run of a lab on this cluster, or a new one."""
    with _lock, _db() as c:
        row = c.execute("SELECT id FROM runs WHERE lab_id=? AND cluster=? AND state='active' ORDER BY created_at DESC LIMIT 1", (lab_id, cluster)).fetchone()
        if row:
            return row["id"]
        rid = f"{lab_id}:{uuid.uuid4().hex[:10]}"
        c.execute("INSERT INTO runs (id, lab_id, cluster, api, created_at, updated_at, state) VALUES (?,?,?,?,?,?, 'active')", (rid, lab_id, cluster, api, _now(), _now()))
        return rid


def active_run(lab_id: str, cluster: str) -> str | None:
    with _lock, _db() as c:
        row = c.execute("SELECT id FROM runs WHERE lab_id=? AND cluster=? AND state IN ('active','cleaning','blocked') ORDER BY created_at DESC LIMIT 1", (lab_id, cluster)).fetchone()
        return row["id"] if row else None


def intent(run_id: str, kind: str, name: str, path: str, *, namespace: str | None = None, scope: str = "namespaced", identity: str = "learner") -> int:
    with _lock, _db() as c:
        cur = c.execute(
            "INSERT INTO effects (run_id, kind, name, namespace, scope, path, identity, phase, created_at, updated_at) VALUES (?,?,?,?,?,?,?, 'intent', ?, ?)",
            (run_id, kind, name, namespace, scope, path, identity, _now(), _now()),
        )
        return int(cur.lastrowid)


def _set(eid: int, phase: str, detail: str = "", uid: str | None = None) -> None:
    with _lock, _db() as c:
        if uid:
            c.execute("UPDATE effects SET phase=?, detail=?, uid=?, updated_at=? WHERE id=?", (phase, detail, uid, _now(), eid))
        else:
            c.execute("UPDATE effects SET phase=?, detail=?, updated_at=? WHERE id=?", (phase, detail, _now(), eid))


def applied(eid: int, uid: str, detail: str = "") -> None:
    _set(eid, "applied", detail, uid)


def failed(eid: int, reason: str) -> None:
    _set(eid, "failed", reason[:500])


def effects(run_id: str) -> list[dict]:
    with _lock, _db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM effects WHERE run_id=? ORDER BY id", (run_id,))]


def find_effect(run_id: str, kind: str, name: str) -> dict | None:
    with _lock, _db() as c:
        r = c.execute("SELECT * FROM effects WHERE run_id=? AND kind=? AND name=? ORDER BY id DESC LIMIT 1", (run_id, kind, name)).fetchone()
        return dict(r) if r else None


def uid_of(identity: str, path: str) -> tuple[str, str | None]:
    """Read an object by REST path: ('found', uid) | ('not_found', None) | (reason, None)."""
    r = kube.oc(identity, ["get", "--raw", path], timeout=30)  # type: ignore[arg-type]
    state = kube.classify(r)
    if state != "found":
        return state, None
    try:
        return "found", json.loads(r.stdout).get("metadata", {}).get("uid")
    except ValueError:
        return "error", None


def note_volumes(run_id: str, namespace: str) -> list[str]:
    """Record which volumes the lab's claims are bound to, while the lab is still running (claim UID → volume)."""
    state, obj, _r = kube.read("learner", ["get", "pvc", "-n", namespace])
    if state != "found" or obj is None:
        return []
    out = []
    with _lock, _db() as c:
        for pvc in obj.get("items", []):
            pv = pvc.get("spec", {}).get("volumeName")
            if not pv:
                continue
            c.execute(
                "INSERT INTO volumes (pv, run_id, namespace, claim, claim_uid, phase, noted_at, updated_at) VALUES (?,?,?,?,?, 'bound', ?, ?) "
                "ON CONFLICT(pv, run_id) DO UPDATE SET claim_uid=excluded.claim_uid, updated_at=excluded.updated_at",
                (pv, run_id, namespace, pvc["metadata"]["name"], pvc["metadata"].get("uid"), _now(), _now()),
            )
            out.append(pv)
    return out


def volumes(run_id: str) -> list[dict]:
    with _lock, _db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM volumes WHERE run_id=? ORDER BY pv", (run_id,))]


# ---------------------------------------------------------------- cleanup
def request_cleanup(run_id: str) -> None:
    with _lock, _db() as c:
        c.execute("UPDATE runs SET state='cleaning', cleanup_requested_at=COALESCE(cleanup_requested_at, ?), updated_at=? WHERE id=?", (_now(), _now(), run_id))
    _wake.set()


def _delete_with_uid(identity: str, path: str, uid: str) -> str:
    """DELETE <path> with a UID precondition. Returns found|not_found|conflict|forbidden|unauthorized|error."""
    body = {"kind": "DeleteOptions", "apiVersion": "v1", "preconditions": {"uid": uid}, "propagationPolicy": "Background"}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=config.DATA_DIR, encoding="utf-8", newline="\n") as f:
        json.dump(body, f)
    try:
        r = kube.oc(identity, ["delete", "--raw", path, "-f", f.name], timeout=60)  # type: ignore[arg-type]
    finally:
        Path(f.name).unlink(missing_ok=True)
    if "(Conflict)" in r.stderr:
        return "conflict"
    return kube.classify(r)


STUCK_AFTER_S = 180  # a namespace waiting on finalizers for longer than this is reported as stuck


def _namespace_report(ns: str) -> tuple[str, str]:
    """As the reader: ('gone'|'terminating'|'stuck'|'present'|'unknown', detail)."""
    if not _usable("reader"):
        return "unknown", "the reader identity is not connected to this cluster, so the namespace cannot be checked directly"
    state, obj, r = kube.read("reader", ["get", "namespace", ns])
    if state == "not_found":
        return "gone", "confirmed by the API server (NotFound)"
    if state != "found":
        return "unknown", f"the namespace could not be read ({state})"
    if obj.get("status", {}).get("phase") != "Terminating":
        return "present", "the namespace still exists and is not being deleted"
    conds = {c["type"]: c for c in obj.get("status", {}).get("conditions", [])}
    fin = conds.get("NamespaceFinalizersRemaining", {})
    if fin.get("status") == "True":
        # Kubernetes sets this transiently too (pvc-protection waits for pods to stop, for example a StatefulSet's):
        # only a deletion that has been waiting for longer than a grace period is reported as stuck.
        since = obj.get("metadata", {}).get("deletionTimestamp")
        try:
            age = time.time() - datetime.fromisoformat(str(since).replace("Z", "+00:00")).timestamp()
        except ValueError:
            age = STUCK_AFTER_S
        if age < STUCK_AFTER_S:
            return "terminating", f"waiting for finalizers ({fin.get('message', '')}); normal for a short while"
        return "stuck", fin.get("message", "finalizers remaining")
    content = conds.get("NamespaceContentRemaining", {})
    return "terminating", content.get("message", "deletion in progress")


def _pass_effect(e: dict, age: float) -> tuple[str, str]:
    """One cleanup attempt for one effect. Returns (phase, detail)."""
    phase, kind = e["phase"], e["kind"]
    if phase in TERMINAL_OK or phase == "replaced":
        return phase, e["detail"] or ""
    if phase == "intent":  # interrupted between intent and UID: recover only with proof that this run created it
        if kind != "Project":
            if not _usable(e["identity"]):
                return "intent", f"cannot check whether it was created: the {e['identity']} identity is not connected to this run's cluster"
            state, _uid = uid_of(e["identity"], e["path"])
            if state == "not_found":
                return "failed", "never created (the run stopped before the API server accepted it)"
            if state == "found":
                return "unknown", ("an object with this name exists, but the run stopped before its UID was recorded, so the academy "
                                   "cannot prove it created it; it is not deleted. Check it and delete it yourself if it is the lab's.")
            return "intent", f"could not confirm whether it was created ({state}); will retry"
        state, obj, _r = kube.read("learner", ["get", "project", e["name"]])
        desc = ((obj or {}).get("metadata", {}).get("annotations") or {}).get("openshift.io/description", "")
        if state == "found" and run_marker(e["run_id"]) in desc:
            uid = obj["metadata"].get("uid")
            _set(e["id"], "applied", "UID recovered after an interruption (the project carries this run's marker)", uid)
            e = {**e, "phase": "applied", "uid": uid, "detail": "UID recovered after an interruption"}
            phase = "applied"
        elif state == "found":
            return "unknown", "a project with this name exists but does not carry this run's marker; it is not deleted"
        else:
            # a normal user cannot tell "never created" from "not mine" for projects (both answer Forbidden)
            return "intent", f"could not confirm whether the project was created ({state}); connect the reader identity, or check it yourself"
    if not e.get("uid"):
        # nothing is ever deleted without a recorded UID; but once the name is gone, there is nothing left to report
        if kind != "Project" and _usable(e["identity"]):
            state, _u = uid_of(e["identity"], e["path"])
            if state == "not_found":
                return "gone", "no object with this name exists any more (NotFound); nothing was deleted by the academy"
        return "unknown", "no UID was recorded, so ownership cannot be proven; nothing is deleted"
    who = e["identity"]
    if who == "admin" and not _usable("admin"):
        return "blocked", f"needs an administrator on this cluster: connect the admin identity, or delete {kind.lower()}/{e['name']} (UID {e['uid']}) yourself"
    if phase in ("applied", "blocked", "unknown") and not (e["detail"] or "").startswith("delete requested"):
        res = _delete_with_uid(who, e["path"], e["uid"])
        if res == "conflict":
            return "replaced", "the name now belongs to a different object (UID changed); it was not deleted"
        if res == "not_found":
            return "gone", "already gone (NotFound)"
        if res in ("forbidden", "unauthorized"):
            return "blocked", f"the {who} identity is not allowed to delete it ({res})"
        if res != "found":
            return "unknown", f"the delete request failed ({res}); will retry"
        phase = "deleting"
    # verify
    if kind == "Project":
        st, detail = _namespace_report(e["name"])
        if st == "gone":
            return "gone", detail
        if st == "stuck":
            return "blocked", f"the namespace is waiting for finalizers: {detail}. The academy never removes finalizers; an administrator must resolve the objects that hold them."
        if st == "unknown":
            vis, _o, _r = kube.read("learner", ["get", "project", e["name"]])
            if vis == "found":
                return "deleting", "delete requested: still terminating"
            return "not-visible", "delete requested: the learner can no longer see the project, but only the reader can confirm it is gone"
        return "deleting", f"delete requested: {detail}"
    state, _uid = uid_of("reader" if _usable("reader") else who, e["path"])
    if state == "not_found":
        return "gone", "confirmed by the API server (NotFound)"
    return "deleting", "delete requested: still present" if state == "found" else f"delete requested: could not confirm ({state})"


def owns_project(ns: str) -> bool:
    """True when an open run of this ledger created project `ns` and the project on the cluster is still that one
    (same UID). A name, a prefix or a description can be copied; a UID recorded at creation cannot."""
    with _lock, _db() as c:
        uids = {r["uid"] for r in c.execute("SELECT e.uid FROM effects e JOIN runs r ON r.id=e.run_id WHERE e.kind='Project' AND e.name=? "
                                            "AND r.state IN ('active','cleaning','blocked') AND e.phase NOT IN ('gone','failed') AND e.uid IS NOT NULL", (ns,))}
    if not uids:
        return False
    state, uid = uid_of("learner", f"/apis/project.openshift.io/v1/projects/{ns}")
    return state == "found" and uid in uids


def run_marker(run_id: str) -> str:
    """Written into a project's description at creation, so an interrupted run can prove the project is its own."""
    return f"[run {run_id}]"


def _project_owned(ns: str) -> bool:
    state, obj, _r = kube.read("learner", ["get", "project", ns])
    if state != "found":
        return False
    return ns.startswith(config.NS_PREFIX) and (obj.get("metadata", {}).get("annotations") or {}).get("openshift.io/description") in config.MARKERS


def _pass_volumes(run_id: str, project_gone: bool) -> None:
    if not project_gone:
        return
    who = "admin" if _usable("admin") else "reader" if _usable("reader") else None
    for v in volumes(run_id):
        if v["phase"] in ("gone", "reclaimed", "kept"):
            continue
        if not v["claim_uid"]:  # found by the safety-net scan: only its existence is re-checked
            if who and kube.read(who, ["get", "pv", v["pv"]])[0] == "not_found":  # type: ignore[arg-type]
                with _lock, _db() as c:
                    c.execute("UPDATE volumes SET phase='gone', detail=?, updated_at=? WHERE pv=? AND run_id=?", ("no longer exists (NotFound)", _now(), v["pv"], run_id))
            continue
        if not who:
            phase, detail = "unknown", "connect the reader identity to check volumes left by this lab"
        else:
            state, pv, _r = kube.read(who, ["get", "pv", v["pv"]])  # type: ignore[arg-type]
            if state == "not_found":
                phase, detail = "gone", "deleted with its claim (reclaimPolicy Delete) or reclaimed"
            elif state != "found":
                phase, detail = "unknown", f"could not read the volume ({state})"
            else:
                ref = pv.get("spec", {}).get("claimRef") or {}
                if ref.get("uid") != v["claim_uid"]:
                    phase, detail = "kept", "this volume is now claimed by something else; it is not the academy's to reclaim"
                elif pv.get("status", {}).get("phase") == "Released":
                    phase = "released-needs-admin"
                    detail = (f"Released, reclaimPolicy {pv['spec'].get('persistentVolumeReclaimPolicy')}: the data and the space are kept until an "
                              f"administrator reclaims it (Connections → volumes, or `oc patch pv {v['pv']} -p '{{\"spec\":{{\"persistentVolumeReclaimPolicy\":\"Delete\"}}}}'`)")
                else:
                    phase, detail = "unknown", f"volume phase {pv.get('status', {}).get('phase')}"
        with _lock, _db() as c:
            c.execute("UPDATE volumes SET phase=?, detail=?, updated_at=? WHERE pv=? AND run_id=?", (phase, detail, _now(), v["pv"], run_id))


def _target_mismatch(run) -> str:
    """Why this process must not act on the run's cluster right now ("" if it may)."""
    from . import environment

    env = environment.current()
    if not env.get("connected"):
        return "no learner identity is connected, so the run's cluster cannot be checked"
    if env.get("fingerprint") != run["cluster"]:
        return (f"this run was recorded on another cluster ({run['api'] or run['cluster']}); the academy is now connected to "
                f"{env.get('api', 'a different cluster')}. Nothing is deleted or marked gone until it is connected to the original cluster again.")
    if env.get("tls_verified") is False:
        return "the connection does not verify the API server's certificate; cleanup waits for a verified connection"
    return ""


def _usable(identity: str) -> bool:
    """An identity may act for cleanup only if it is connected to the learner's cluster."""
    from . import environment

    return bool(kube.whoami(identity).get("connected")) and (identity == "learner" or environment.same_cluster(identity))  # type: ignore[arg-type]


def _scan_unrecorded_volumes(run_id: str, namespaces: list[str]) -> None:
    """Safety net: volumes whose claim lived in this run's projects but whose binding was never recorded (for example
    a claim bound and deleted between two observations). They are reported, never reclaimed: without the binding
    recorded during the run, the academy cannot prove the claim was its own."""
    who = "reader" if _usable("reader") else "admin" if _usable("admin") else None
    if not who or not namespaces:
        return
    state, obj, _r = kube.read(who, ["get", "pv"])  # type: ignore[arg-type]
    if state != "found":
        return
    known = {v["pv"] for v in volumes(run_id)}
    with _lock, _db() as c:
        for pv in (obj or {}).get("items", []):
            ref = pv.get("spec", {}).get("claimRef") or {}
            name = pv.get("metadata", {}).get("name")
            if ref.get("namespace") in namespaces and name not in known and pv.get("status", {}).get("phase") != "Bound":
                c.execute("INSERT OR IGNORE INTO volumes (pv, run_id, namespace, claim, claim_uid, phase, detail, noted_at, updated_at) VALUES (?,?,?,?,?, 'unknown', ?, ?, ?)",
                          (name, run_id, ref.get("namespace"), ref.get("name"), None,
                           f"{pv.get('status', {}).get('phase')} volume of a claim in this lab's project, found at cleanup; its binding was not recorded during the run, so it is reported, not reclaimed. An administrator should check it.",
                           _now(), _now()))


def cleanup_pass(run_id: str) -> dict:
    """One idempotent pass over a run: delete what is still there (UID-checked), verify, and summarise."""
    with _lock, _db() as c:
        run = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not run:
        raise KeyError(run_id)
    why = _target_mismatch(run)
    if why:
        with _lock, _db() as c:
            c.execute("UPDATE runs SET state=CASE WHEN state='active' THEN 'active' ELSE 'blocked' END, detail=?, updated_at=? WHERE id=?", (why, _now(), run_id))
        out = report(run_id)
        out["reason"] = why
        return out
    age = _now() - (run["cleanup_requested_at"] or _now())
    # cluster-scoped objects first (they may refer to the namespaces), then namespaces
    order = sorted(effects(run_id), key=lambda e: 0 if e["scope"] == "cluster" else 1)
    for e in order:
        phase, detail = _pass_effect(e, age)
        if phase == "deleting" and not detail.startswith("delete requested"):
            detail = "delete requested: " + detail
        if (phase, detail) != (e["phase"], e["detail"] or ""):
            _set(e["id"], phase, detail)
    effs = effects(run_id)
    projects_gone = all(e["phase"] in TERMINAL_OK for e in effs if e["kind"] == "Project")
    if projects_gone:
        _scan_unrecorded_volumes(run_id, [e["name"] for e in effs if e["kind"] == "Project"])
    _pass_volumes(run_id, projects_gone)
    vols = volumes(run_id)
    if all(e["phase"] in TERMINAL_OK for e in effs) and all(v["phase"] in ("gone", "reclaimed", "kept") for v in vols):
        state = "clean"
    elif any(e["phase"] in ("blocked", "replaced") for e in effs) or any(v["phase"] == "released-needs-admin" for v in vols):
        state = "blocked"
    else:
        state = "cleaning"
    with _lock, _db() as c:
        c.execute("UPDATE runs SET state=?, updated_at=? WHERE id=?", (state, _now(), run_id))
    return report(run_id)


def report(run_id: str) -> dict:
    with _lock, _db() as c:
        run = dict(c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
    effs, vols = effects(run_id), volumes(run_id)
    remaining = [e for e in effs if e["phase"] not in TERMINAL_OK] + [v for v in vols if v["phase"] not in ("gone", "reclaimed", "kept")]
    return {"run": run, "state": run["state"], "effects": effs, "volumes": vols, "remaining": len(remaining)}


def runs(states: tuple[str, ...] = ("active", "cleaning", "blocked")) -> list[dict]:
    with _lock, _db() as c:
        q = f"SELECT * FROM runs WHERE state IN ({','.join('?' * len(states))}) ORDER BY created_at DESC"
        return [dict(r) for r in c.execute(q, states)]


# ---------------------------------------------------------------- background sweeper (survives restarts: state is in the DB)
_wake = threading.Event()
_started = False


def _sweep_forever() -> None:
    while True:
        _wake.wait(timeout=20)
        _wake.clear()
        try:
            for r in runs(("cleaning", "blocked")):
                # blocked runs are re-checked less often: something outside the academy has to change first
                if r["state"] == "blocked" and _now() - (r["updated_at"] or 0) < 120:
                    continue
                cleanup_pass(r["id"])
        except LedgerUnavailable:
            time.sleep(60)
        except Exception:  # never let the sweeper die; the next pass retries
            time.sleep(10)


def start_sweeper() -> None:
    global _started
    if _started or not config.cluster_enabled():
        return
    _started = True
    threading.Thread(target=_sweep_forever, name="ledger-sweeper", daemon=True).start()
    _wake.set()


def leftovers() -> list[dict]:
    """academy-* namespaces that the reader can see but no open ledger run owns. Reported, never touched: a name
    pattern is not proof of ownership. (academy-system holds the reader identity and is excluded.)"""
    if not kube.whoami("reader").get("connected"):
        return []
    state, obj, _r = kube.read("reader", ["get", "namespaces"])
    if state != "found":
        return []
    with _lock, _db() as c:
        owned = {r["name"] for r in c.execute("SELECT e.name FROM effects e JOIN runs r ON r.id=e.run_id WHERE e.kind='Project' AND e.phase NOT IN ('gone','failed')")}
    out = []
    for ns in obj.get("items", []):
        name = ns["metadata"]["name"]
        if not name.startswith(config.NS_PREFIX) or name == "academy-system" or name in owned:
            continue
        conds = {c["type"]: c for c in ns.get("status", {}).get("conditions", [])}
        fin = conds.get("NamespaceFinalizersRemaining", {})
        out.append({"name": name, "phase": ns.get("status", {}).get("phase"), "uid": ns["metadata"].get("uid"),
                    "created": ns["metadata"].get("creationTimestamp"),
                    "detail": fin.get("message") if fin.get("status") == "True" else ""})
    return out


def reclaim_volumes(run_id: str, wait_s: float = 60) -> list[dict]:
    """With an administrator connected: reclaim the Released volumes this run's claims left behind (Retain).

    Only volumes recorded for this run qualify, and only while the volume is Released and its claimRef still names the
    claim UID recorded during the run. Reclaiming switches the volume's reclaimPolicy to Delete, so the provisioner
    removes the storage and the PersistentVolume, exactly as if the StorageClass had used Delete."""
    with _lock, _db() as c:
        run = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not run:
        raise KeyError(run_id)
    why = _target_mismatch(run)
    if why:
        raise PermissionError(why)
    if not _usable("admin"):
        raise PermissionError("connect the admin identity (on this run's cluster) to reclaim volumes")
    out = []
    for v in volumes(run_id):
        if v["phase"] != "released-needs-admin":
            continue
        state, pv, _r = kube.read("admin", ["get", "pv", v["pv"]])
        ref = (pv or {}).get("spec", {}).get("claimRef") or {}
        meta = (pv or {}).get("metadata") or {}
        if state != "found" or pv.get("status", {}).get("phase") != "Released" or ref.get("uid") != v["claim_uid"]:
            out.append({"pv": v["pv"], "ok": False, "reason": "no longer a Released volume of this lab's claim; not touched"})
            continue
        if not meta.get("uid") or not meta.get("resourceVersion"):
            out.append({"pv": v["pv"], "ok": False, "reason": "the volume's identity could not be read; not touched"})
            continue
        # One atomic, conditional request: the API server applies it only if the volume is still the same object, in the
        # same version, still claimed by the recorded claim UID. Anything that changed in between makes it fail (422/409).
        body = [
            {"op": "test", "path": "/metadata/uid", "value": meta["uid"]},
            {"op": "test", "path": "/metadata/resourceVersion", "value": meta["resourceVersion"]},
            {"op": "test", "path": "/spec/claimRef/uid", "value": v["claim_uid"]},
            {"op": "replace", "path": "/spec/persistentVolumeReclaimPolicy", "value": "Delete"},
        ]
        r = kube.oc("admin", ["patch", "pv", v["pv"], "--type=json", "-p", json.dumps(body)])
        out.append({"pv": v["pv"], "ok": r.ok, "reason": "" if r.ok else kube.redact(r.stderr)[-200:]})
    t0 = time.monotonic()
    while any(o["ok"] for o in out) and time.monotonic() - t0 < wait_s:
        if all(kube.read("admin", ["get", "pv", o["pv"]])[0] == "not_found" for o in out if o["ok"]):
            break
        time.sleep(2)
    for o in out:
        if o["ok"]:
            gone = kube.read("admin", ["get", "pv", o["pv"]])[0] == "not_found"
            o["deleted"] = gone
            with _lock, _db() as c:
                c.execute("UPDATE volumes SET phase=?, detail=?, updated_at=? WHERE pv=? AND run_id=?",
                          ("reclaimed" if gone else "released-needs-admin", "reclaimed by an administrator (reclaimPolicy Delete); confirmed NotFound" if gone else "reclaim requested; not deleted yet", _now(), o["pv"], run_id))
    cleanup_pass(run_id)
    return out
