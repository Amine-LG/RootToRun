"""API behaviour in practice mode (no cluster): request guards, answer hiding, static export."""
import json
import pytest
import subprocess
import sys

from fastapi.testclient import TestClient

from academy import config, main

c = TestClient(main.app)
H = {"X-Academy": "1"}


def test_practice_mode():
    assert c.get("/api/meta").json()["mode"] == "practice"


def test_practice_mode_does_not_reveal_the_cluster_behind_stored_kubeconfigs(monkeypatch):
    """Even when the data directory holds kubeconfigs (a practice server started beside a cluster-mode one), the
    environment endpoint names no API server and no fingerprint."""
    from academy import environment
    monkeypatch.setattr(environment, "_cluster_entry", lambda identity: {"server": "https://api.private.example:6443", "ca_sha256": "x", "insecure": False})
    assert environment.fingerprint("learner") is None
    body = c.get("/api/environment").json()
    assert body["identities"] == {} and "private.example" not in json.dumps(body)


def test_foreign_host_is_refused():
    r = c.get("/api/meta", headers={"Host": "evil.example"})
    assert r.status_code == 403


def test_writes_need_the_custom_header_and_no_cors():
    assert c.post("/api/labs/lab.rbac/verify").status_code == 403
    assert c.options("/api/meta").status_code == 403


def test_cluster_endpoints_answer_409_in_practice_mode():
    for url, body in [
        ("/api/labs/lab.rbac/prepare", {"confirm": True}),
        ("/api/labs/lab.rbac/verify", {}),
        ("/api/labs/lab.rbac/exec", {"where": "commands", "index": 0}),
        ("/api/workbench/run", {"command": "oc get pods -n academy-x"}),
        ("/api/connect", {"identity": "learner"}),
    ]:
        assert c.post(url, json=body, headers=H).status_code == 409, url


def test_security_headers():
    r = c.get("/api/meta")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_incident_answers_are_hidden_until_revealed():
    d = c.get("/api/labs/inc.service-selector-503").json()
    lab, rec = d["lab"], d["recording"]
    assert lab["root_cause"] == "" and lab["fix"] == [] and lab["break"] == [] and lab["hints"] == []
    assert lab["hint_count"] >= 3
    assert all(e["step"] != "fix" for e in rec["entries"])
    assert "verify_after" not in rec
    r = c.post("/api/labs/inc.service-selector-503/reveal", headers=H).json()
    assert r["root_cause"] and r["fix"] and r["fix_recording"] and r["verify_after"]["verdict"] == "verified"


def test_hints_are_progressive():
    assert len(c.get("/api/labs/inc.service-selector-503/hints?n=1").json()["hints"]) == 1
    assert len(c.get("/api/labs/inc.service-selector-503/hints?n=99").json()["hints"]) == 3


def test_command_reference_excludes_incident_fixes():
    cmds = c.get("/api/commands").json()
    assert len(cmds) > 200
    assert not any(x["cmd"].startswith("oc set selector svc/web app=web -n academy-inc-selector") for x in cmds)


def test_review_cards():
    cards = c.get("/api/cards").json()
    assert len(cards) > 100 and all(x["q"] and x["a"] for x in cards)


def test_static_export(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    r = subprocess.run([sys.executable, str(config.ROOT / "scripts" / "export_static.py"), "--out", str(tmp_path)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    data = tmp_path / "data"
    assert json.loads((data / "meta.json").read_text(encoding="utf-8"))["mode"] == "static"
    inc = json.loads((data / "en" / "labs" / "inc.dns-typo.json").read_text(encoding="utf-8"))
    assert inc["lab"]["root_cause"] == "" and inc["lab"]["fix"] == []
    assert json.loads((data / "en" / "labs" / "inc.dns-typo.reveal.json").read_text(encoding="utf-8"))["root_cause"]
    assert (data / "en" / "lessons" / "o1.cli.json").exists()


def test_health_endpoints_ignore_the_host_header():
    assert c.get("/healthz", headers={"Host": "10.0.0.7:8080"}).json() == {"ok": True}
    r = c.get("/readyz", headers={"Host": "10.0.0.7:8080"})
    assert r.status_code in (200, 503) and "ready" in r.json()
    assert c.get("/api/meta", headers={"Host": "10.0.0.7:8080"}).status_code == 403


def test_unknown_api_paths_answer_json_404_not_the_app_shell():
    """A mistyped API path is an API error (JSON 404), never index.html with 200; app routes still get the shell."""
    for url in ["/api/does-not-exist", "/api/labs/nope/extra/deep", "/api"]:
        r = c.get(url)
        assert r.status_code == 404 and r.headers["content-type"].startswith("application/json"), url
        assert "detail" in r.json()
    if (config.DIST_DIR / "index.html").exists():
        r = c.get("/lesson/does-not-exist")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")


def test_any_host_is_refused_when_a_cluster_is_reachable():
    import subprocess

    code = "import os; os.environ['ACADEMY_ALLOWED_HOSTS']='*'; os.environ['ACADEMY_CLUSTER']='auto'; import academy.main"
    r = subprocess.run([sys.executable, "-c", code], cwd=config.ROOT / "backend", capture_output=True, text=True, encoding="utf-8", env={**__import__('os').environ, "ACADEMY_CLUSTER": "auto", "PATH": "/usr/bin:/bin:" + str(config.ROOT / "tests" / "fake-oc")})
    if "oc" not in r.stderr and r.returncode == 0:
        pytest.skip("no oc binary found, cluster mode cannot be enabled here")
    assert r.returncode != 0 and "only allowed with ACADEMY_CLUSTER=off" in r.stderr


def test_workbench_changes_only_projects_the_academy_prepared(monkeypatch):
    """A learner command that changes the cluster runs only in a project an open ledger run created (same UID);
    an academy-* name alone is not enough."""
    from academy import ledger, runner
    monkeypatch.setattr(main, "need_cluster", lambda: None)
    monkeypatch.setattr(main, "need_training", lambda what="": None)
    monkeypatch.setattr(ledger, "owns_project", lambda ns: False)
    monkeypatch.setattr(runner, "execute", lambda *a, **k: pytest.fail("a command ran in a project the academy does not own"))
    r = c.post("/api/workbench/run", headers=H, json={"command": "oc delete deployment important -n academy-unowned", "identity": "learner", "confirm": True})
    assert r.status_code == 200 and r.json()["refused"] and "not prepared by the academy" in r.json()["reason"]


def test_lesson_recording_never_deletes_a_project_it_did_not_create(monkeypatch, tmp_path):
    from academy import environment, kube, labs, recorder
    calls = []
    def oc(identity, args, **kw):
        calls.append(args)
        return kube.Result(["oc", *args], 1, "", 'Error from server (AlreadyExists): project.project.openshift.io "x" already exists', 0)
    monkeypatch.setattr(kube, "oc", oc)
    monkeypatch.setattr(kube, "whoami", lambda i: {"connected": True})
    lesson = type("L", (), {"id": "o1.cli"})()
    monkeypatch.setattr(environment, "current", lambda: {"class": "read-only"})
    ns, _info, problem = recorder._cluster_session(lesson, tmp_path / "w", {})
    assert ns is None and "not approved" in problem and calls == []
    monkeypatch.setattr(environment, "current", lambda: {"class": "training"})
    monkeypatch.setattr(recorder.time, "sleep", lambda s: None)
    # even a project that carries the academy's description is never deleted: a description can be copied
    monkeypatch.setattr(labs, "project_state", lambda ns: {"exists": True, "owned": True})
    ns, _info, problem = recorder._cluster_session(lesson, tmp_path / "w", {})
    assert ns is None and "already exists; it was not touched" in problem
    assert not any(a[:1] == ["delete"] for a in calls)


def test_explorer_ignores_a_reader_connected_to_another_cluster(monkeypatch):
    from academy import environment, explorer, kube
    monkeypatch.setattr(kube, "whoami", lambda i: {"connected": True})
    monkeypatch.setattr(environment, "same_cluster", lambda i: False)
    monkeypatch.setattr(kube, "oc_json", lambda *a, **k: pytest.fail("the explorer read another cluster"))
    with pytest.raises(explorer.Bad):
        explorer._identity("production")
    assert explorer.overview()["ok"] is False


def test_workbench_checks_the_namespace_the_command_will_run_in(monkeypatch):
    """With a lab and no -n, the runner uses the lab's namespace; ownership is checked for that same namespace."""
    from academy import labs, ledger, runner
    seen = []
    monkeypatch.setattr(main, "need_cluster", lambda: None)
    monkeypatch.setattr(main, "need_training", lambda what="": None)
    monkeypatch.setattr(ledger, "owns_project", lambda ns: seen.append(ns) or False)
    monkeypatch.setattr(runner, "execute", lambda *a, **k: pytest.fail("ran without an ownership check"))
    lab = labs.load(None)["lab.rbac"]
    r = c.post("/api/workbench/run", headers=H, json={"command": "oc create configmap x", "identity": "learner", "lab_id": "lab.rbac", "confirm": True})
    assert r.json()["refused"] and seen == [lab.namespace]
