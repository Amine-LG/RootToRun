"""Cleanup ledger under failure: no false "clean", no deletion of anything the ledger cannot prove it created.

A fake API server answers the way OpenShift does (verified on OpenShift Local 4.21):
  * a normal user asking for a project that does not exist (or that it lost access to) gets Forbidden, not NotFound;
  * a DELETE with a UID precondition that does not match returns 409 Conflict and deletes nothing;
  * a terminating namespace held by a finalizer reports NamespaceFinalizersRemaining.
"""
import json

import pytest

from academy import config, environment, kube, ledger

NS = "academy-test"
PPATH = f"/apis/project.openshift.io/v1/projects/{NS}"
GPATH = "/apis/user.openshift.io/v1/groups/academy-auditors"


class FakeAPI:
    def __init__(self):
        self.objects = {}  # path -> {"uid", "terminating", "finalizer"}
        self.connected = {"learner", "reader"}
        self.learner_lost_access = False
        self.calls = []
        self.description = config.MARKER

    def add(self, path, uid, **kw):
        self.objects[path] = {"uid": uid, "terminating": False, "finalizer": None, **kw}

    def oc(self, identity, args, stdin=None, timeout=None):
        self.calls.append((identity, list(args)))
        R = lambda code, out="", err="": kube.Result(["oc", *args], code, out, err, 0)  # noqa: E731
        if identity not in self.connected:
            return kube.Result(["oc", *args], 1, "", f"Not connected as {identity}.", 0, "not_connected")
        if args[:2] == ["delete", "--raw"]:
            path, body = args[2], json.load(open(args[4], encoding="utf-8"))
            o = self.objects.get(path)
            if not o:
                return R(1, err=f'Error from server (NotFound): "{path}" not found')
            if body["preconditions"]["uid"] != o["uid"]:
                return R(1, err="Error from server (Conflict): Operation cannot be fulfilled: the UID in the precondition does not match")
            if o["finalizer"]:
                o["terminating"] = True
                if path == PPATH:
                    self.learner_lost_access = True
            else:
                del self.objects[path]
            return R(0, '{"kind":"Status","status":"Success"}')
        if args[:2] == ["get", "--raw"]:
            path = args[2]
            o = self.objects.get(path)
            if path == PPATH and identity == "learner" and (not o or self.learner_lost_access):
                return R(1, err='Error from server (Forbidden): projects.project.openshift.io "academy-test" is forbidden')
            if not o:
                return R(1, err="Error from server (NotFound): not found")
            return R(0, json.dumps({"metadata": {"uid": o["uid"]}}))
        if args[:2] == ["get", "namespace"]:
            o = self.objects.get(PPATH)
            if identity != "reader":
                return R(1, err="Error from server (Forbidden): namespaces is forbidden")
            if not o:
                return R(1, err='Error from server (NotFound): namespaces "academy-test" not found')
            conds = [{"type": "NamespaceFinalizersRemaining", "status": "True", "message": f"Some content in the namespace has finalizers remaining: {o['finalizer']} in 1 resource instances"}] if o["finalizer"] else []
            return R(0, json.dumps({"metadata": {"uid": o["uid"]}, "status": {"phase": "Terminating" if o["terminating"] else "Active", "conditions": conds}}))
        if args[:2] == ["get", "project"]:
            o = self.objects.get(PPATH)
            if not o or self.learner_lost_access:
                return R(1, err='Error from server (Forbidden): projects.project.openshift.io "academy-test" is forbidden')
            return R(0, json.dumps({"metadata": {"uid": o["uid"], "annotations": {"openshift.io/description": self.description}}, "status": {"phase": "Active"}}))
        if args[:2] == ["get", "pvc"] or args[:2] == ["get", "pv"]:
            return R(0, json.dumps({"items": []}))
        return R(1, err="unexpected call")


@pytest.fixture
def api(tmp_path, monkeypatch):
    fake = FakeAPI()
    monkeypatch.setattr(ledger, "DB", tmp_path / "ledger.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(kube, "oc", fake.oc)
    monkeypatch.setattr(kube, "whoami", lambda i: {"connected": i in fake.connected})
    monkeypatch.setattr(environment, "current", lambda: {"connected": True, "fingerprint": "fp1", "api": "https://api.test:6443", "tls_verified": True})
    monkeypatch.setattr(environment, "same_cluster", lambda i: True)
    return fake


def run_with_project(fake):
    rid = ledger.begin_run("lab.test", "fp1")
    fake.add(PPATH, "uid-p")
    ledger.applied(ledger.intent(rid, "Project", NS, PPATH), "uid-p")
    return rid


def test_project_deleted_and_confirmed_gone_by_reader(api):
    rid = run_with_project(api)
    ledger.request_cleanup(rid)
    rep = ledger.cleanup_pass(rid)
    assert rep["state"] == "clean"
    assert rep["effects"][0]["phase"] == "gone" and "NotFound" in rep["effects"][0]["detail"]


def test_learner_losing_sight_is_never_reported_as_gone(api):
    """The CRC behaviour: the learner sees Forbidden while the namespace is still terminating."""
    rid = run_with_project(api)
    api.objects[PPATH]["finalizer"] = "academy.test/hold"
    api.connected = {"learner"}  # no reader to confirm
    ledger.request_cleanup(rid)
    rep = ledger.cleanup_pass(rid)
    e = rep["effects"][0]
    assert e["phase"] == "not-visible" and rep["state"] == "cleaning"
    assert rep["state"] != "clean"


def test_finalizer_is_reported_never_removed(api):
    rid = run_with_project(api)
    api.objects[PPATH]["finalizer"] = "academy.test/hold"
    ledger.request_cleanup(rid)
    rep = ledger.cleanup_pass(rid)
    e = rep["effects"][0]
    assert rep["state"] == "blocked" and e["phase"] == "blocked"
    assert "academy.test/hold" in e["detail"] and "never removes finalizers" in e["detail"]
    assert not any(a[:2] == ["patch"] or "finalizers" in " ".join(a) for _i, a in api.calls if a[0] != "get")
    # an administrator resolves it outside the academy; the next pass confirms
    del api.objects[PPATH]
    assert ledger.cleanup_pass(rid)["state"] == "clean"


def test_replaced_object_is_not_deleted(api):
    rid = run_with_project(api)
    api.objects[PPATH]["uid"] = "someone-elses-uid"  # deleted and recreated by someone else, same name
    ledger.request_cleanup(rid)
    rep = ledger.cleanup_pass(rid)
    assert rep["effects"][0]["phase"] == "replaced" and PPATH in api.objects and rep["state"] == "blocked"


def test_crash_between_intent_and_uid_is_reconciled(api):
    rid = ledger.begin_run("lab.test", "fp1")
    ledger.intent(rid, "Project", NS, PPATH)  # the process died here; the project was created with this run's marker
    api.add(PPATH, "uid-p")
    api.description = f"{config.MARKER} {ledger.run_marker(rid)}"
    ledger.request_cleanup(rid)
    rep = ledger.cleanup_pass(rid)
    assert rep["effects"][0]["uid"] == "uid-p" and rep["state"] == "clean"


def test_intent_never_created_is_not_an_error(api):
    rid = ledger.begin_run("lab.test", "fp1")
    ledger.intent(rid, "Group", "academy-auditors", GPATH, scope="cluster", identity="admin")
    api.connected.add("admin")
    ledger.request_cleanup(rid)
    rep = ledger.cleanup_pass(rid)
    assert rep["effects"][0]["phase"] == "failed" and rep["state"] == "clean"


def test_cluster_object_needs_admin_and_says_so(api):
    rid = ledger.begin_run("lab.test", "fp1")
    api.add(GPATH, "uid-g")
    ledger.applied(ledger.intent(rid, "Group", "academy-auditors", GPATH, scope="cluster", identity="admin"), "uid-g")
    ledger.request_cleanup(rid)
    rep = ledger.cleanup_pass(rid)
    assert rep["state"] == "blocked" and "administrator" in rep["effects"][0]["detail"] and GPATH in api.objects
    api.connected.add("admin")
    assert ledger.cleanup_pass(rid)["state"] == "clean" and GPATH not in api.objects


def test_state_survives_a_restart(api):
    rid = run_with_project(api)
    api.objects[PPATH]["finalizer"] = "x/y"
    ledger.request_cleanup(rid)
    ledger.cleanup_pass(rid)
    # a new process: nothing in memory, everything from the database
    assert [r["id"] for r in ledger.runs(("blocked",))] == [rid]
    assert ledger.report(rid)["remaining"] == 1


def test_corrupt_ledger_blocks_destructive_recovery(api):
    ledger.DB.write_bytes(b"this is not a sqlite database" * 100)
    with pytest.raises(ledger.LedgerUnavailable):
        ledger.runs()
    assert not any(a[:1] == ["delete"] for _i, a in api.calls)


def test_no_uid_no_delete(api):
    rid = ledger.begin_run("lab.test", "fp1")
    eid = ledger.intent(rid, "Project", NS, PPATH)
    ledger._set(eid, "applied", "")  # applied without a UID (should never happen): ownership unproven
    api.add(PPATH, "uid-p")
    ledger.request_cleanup(rid)
    ledger.cleanup_pass(rid)
    assert PPATH in api.objects


class FakeStorage(FakeAPI):
    """Adds one claim in the lab project and its volume, which survives the claim (reclaimPolicy Retain)."""

    def __init__(self):
        super().__init__()
        self.pv = {"name": "pvc-1", "phase": "Bound", "claim_uid": "uid-claim", "policy": "Retain"}

    def oc(self, identity, args, stdin=None, timeout=None):
        R = lambda code, out="", err="": kube.Result(["oc", *args], code, out, err, 0)  # noqa: E731
        if identity not in self.connected:
            return kube.Result(["oc", *args], 1, "", "Not connected", 0, "not_connected")
        if args[:2] == ["get", "pvc"]:
            items = [] if PPATH not in self.objects else [{"metadata": {"name": "data", "uid": "uid-claim"}, "spec": {"volumeName": "pvc-1"}}]
            return R(0, json.dumps({"items": items}))
        if args[:2] == ["get", "pv"]:
            if not self.pv:
                return R(1, err='Error from server (NotFound): persistentvolumes "pvc-1" not found')
            return R(0, json.dumps({"metadata": {"uid": "pv-uid", "resourceVersion": "5"}, "spec": {"claimRef": {"uid": self.pv["claim_uid"]}, "persistentVolumeReclaimPolicy": self.pv["policy"]}, "status": {"phase": self.pv["phase"]}}))
        if args[:2] == ["patch", "pv"]:
            self.calls.append((identity, list(args)))
            self.pv = None  # the provisioner deletes it once the policy is Delete
            return R(0, "persistentvolume/pvc-1 patched")
        out = super().oc(identity, args, stdin, timeout)
        if args[:2] == ["delete", "--raw"] and PPATH not in self.objects and self.pv:
            self.pv["phase"] = "Released"
        return out


@pytest.fixture
def storage(tmp_path, monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr(ledger, "DB", tmp_path / "ledger.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(kube, "oc", fake.oc)
    monkeypatch.setattr(kube, "whoami", lambda i: {"connected": i in fake.connected})
    monkeypatch.setattr(environment, "current", lambda: {"connected": True, "fingerprint": "fp1", "api": "https://api.test:6443", "tls_verified": True})
    monkeypatch.setattr(environment, "same_cluster", lambda i: True)
    return fake


def test_retained_volume_is_reported_then_reclaimed_by_an_admin(storage):
    rid = run_with_project(storage)
    assert ledger.note_volumes(rid, NS) == ["pvc-1"]
    ledger.request_cleanup(rid)
    rep = ledger.cleanup_pass(rid)
    v = rep["volumes"][0]
    assert rep["state"] == "blocked" and v["phase"] == "released-needs-admin" and "administrator" in v["detail"]
    with pytest.raises(PermissionError):
        ledger.reclaim_volumes(rid)  # no admin connected: nothing happens
    storage.connected.add("admin")
    out = ledger.reclaim_volumes(rid, wait_s=1)
    assert out == [{"pv": "pvc-1", "ok": True, "reason": "", "deleted": True}]
    assert ledger.report(rid)["state"] == "clean"


def test_a_volume_claimed_by_someone_else_is_never_reclaimed(storage):
    rid = run_with_project(storage)
    ledger.note_volumes(rid, NS)
    ledger.request_cleanup(rid)
    ledger.cleanup_pass(rid)
    storage.pv["claim_uid"] = "another-claim"  # rebound to a different claim after our cleanup
    storage.connected.add("admin")
    out = ledger.reclaim_volumes(rid, wait_s=1)
    assert not any(a[:2] == ["patch", "pv"] for _i, a in storage.calls)
    assert out == [] or not out[0]["ok"]


def test_an_interrupted_intent_never_adopts_a_project_without_this_runs_marker(api):
    rid = ledger.begin_run("lab.test", "fp1")
    ledger.intent(rid, "Project", NS, PPATH)
    api.add(PPATH, "someone-elses")  # a project with that name exists, but this run did not create it
    ledger.request_cleanup(rid)
    rep = ledger.cleanup_pass(rid)
    assert rep["effects"][0]["phase"] == "unknown" and PPATH in api.objects


def test_a_run_from_another_cluster_is_never_touched(api, monkeypatch):
    rid = run_with_project(api)
    monkeypatch.setattr(environment, "current", lambda: {"connected": True, "fingerprint": "another", "api": "https://api.prod:6443", "tls_verified": True})
    ledger.request_cleanup(rid)
    rep = ledger.cleanup_pass(rid)
    assert rep["state"] == "blocked" and PPATH in api.objects and "another cluster" in rep["reason"]


def test_transient_finalizers_are_not_reported_as_stuck(monkeypatch):
    """pvc-protection briefly holds a namespace while a StatefulSet's pods stop; that is terminating, not stuck."""
    from datetime import datetime, timezone
    from academy import ledger
    now = datetime.now(timezone.utc).isoformat()
    ns = {"metadata": {"deletionTimestamp": now}, "status": {"phase": "Terminating", "conditions": [
        {"type": "NamespaceFinalizersRemaining", "status": "True", "message": "kubernetes.io/pvc-protection in 2 resource instances"}]}}
    monkeypatch.setattr(ledger, "_usable", lambda i: True)
    monkeypatch.setattr(ledger.kube, "read", lambda *a, **k: ("found", ns, None))
    assert ledger._namespace_report("academy-x")[0] == "terminating"
    ns["metadata"]["deletionTimestamp"] = "2020-01-01T00:00:00Z"
    assert ledger._namespace_report("academy-x")[0] == "stuck"


def test_owns_project_needs_an_open_run_and_the_same_uid(api):
    """Workbench writes are allowed only in a project an open run created: a name or a description proves nothing."""
    assert ledger.owns_project(NS) is False  # no run knows it, even though nothing contradicts the name
    run_with_project(api)
    assert ledger.owns_project(NS) is True
    api.objects[PPATH]["uid"] = "uid-replacement"  # deleted and recreated by someone else under the same name
    assert ledger.owns_project(NS) is False


def test_projects_with_the_current_or_the_earlier_marker_are_the_academys(api):
    """Projects created before the project took its final name carry the earlier description and stay the academy's;
    any other description, or text added after the marker, is not."""
    api.add(PPATH, "uid-project")
    for description, owned in ((config.MARKER, True), ("Managed by OpenShift Engineering Academy", True),
                               ("Managed by someone else", False), (f"{config.MARKER} and more", False), ("", False)):
        api.description = description
        assert ledger._project_owned(NS) is owned, description


def test_a_lab_project_with_either_marker_is_reported_as_owned(monkeypatch):
    from academy import labs

    for description, owned in ((f"{config.MARKER} [run 1]", True), ("Managed by OpenShift Engineering Academy [run 1]", True),
                               ("Managed by someone else", False)):
        obj = {"metadata": {"annotations": {"openshift.io/description": description}}, "status": {"phase": "Active"}}
        monkeypatch.setattr(kube, "read", lambda *a, **kw: ("found", obj, None))
        assert labs.project_state(NS)["owned"] is owned, description
