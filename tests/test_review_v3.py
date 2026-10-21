"""Remaining v2 defects; deterministic responses, no cluster or network access."""
import copy
import json
import sys

import pytest
import yaml

from academy import checks, config, curriculum, kube, labs, recorder
from scripts import coverage
from test_review_v2 import (
    forbid_cluster, install_web_responses, result, web_state,
)


@pytest.mark.parametrize("mount", ["/var/www/html-unused", "/var/www/html/unused"])
def test_content_mount_must_supply_the_served_index(monkeypatch, mount):
    """An unused required ConfigMap must not certify a root page supplied by shadow."""
    objects = web_state()
    tpl = objects["deployment", "shop"]["spec"]["template"]["spec"]
    objects["configmap", "shadow"] = copy.deepcopy(objects["configmap", "shop-content"])
    objects["configmap", "shadow"]["metadata"]["name"] = "shadow"
    tpl["volumes"][0]["configMap"]["name"] = "shadow"
    tpl["volumes"].append({"name": "unused", "configMap": {"name": "shop-content"}})
    tpl["containers"][0]["volumeMounts"].append({"name": "unused", "mountPath": mount})
    install_web_responses(monkeypatch, objects)
    observed = labs.verify(labs.load()["ch.ship-web-app"])
    assert observed["verdict"] != "verified", observed


def test_rules_deny_matches_wildcard_subresource(monkeypatch):
    """Kubernetes grants pods/log through */log; a denial check must see that grant.

    Semantics: https://github.com/kubernetes/kubernetes/blob/master/pkg/apis/rbac/v1/evaluation_helpers.go
    This does not affect the bot's current parent-resource prohibitions.
    """
    rule = {"apiGroups": [""], "resources": ["*/log"], "verbs": ["get"]}
    monkeypatch.setattr(kube, "oc", lambda *a, **k: result(json.dumps({
        "status": {"incomplete": False, "resourceRules": [rule]}})))
    observed = checks.c_rules_deny("review", {"as": "ci-bot", "forbid": [
        {"resource": "pods/log", "verbs": ["get"]}]})
    assert observed["status"] == "fail", observed


def test_trusted_exec_rejects_another_deployments_fake_image(monkeypatch):
    """A Deployment named batch-forged must not supply the lab batch's curl evidence."""
    pod = {"metadata": {"name": "aaa-fake-batch", "labels": {"app": "batch"},
                        "ownerReferences": [{"kind": "ReplicaSet", "name": "batch-forged-5d9f"}]},
           "spec": {"containers": [{"name": "curl", "image": "example.invalid/forged-curl:latest",
                                    "command": ["sleep", "infinity"]}]},
           "status": {"phase": "Running"}}
    monkeypatch.setattr(checks, "_pods", lambda *a: ([pod], result()))
    # A custom image's absolute /usr/bin/curl returns these bytes without connecting.
    monkeypatch.setattr(kube, "oc", lambda i, args, **kw:
                        result("ok") if "healthz" in args[-1] else result(code=28))
    lab = labs.load()["ch.protect-traffic"]
    observed = [checks.run_check(lab.namespace, c.model_dump()) for c in lab.checks
                if c.id in ("batch-blocked", "batch-egress")]
    assert not all(r["status"] == "pass" for r in observed), observed


def test_route_cannot_borrow_response_outside_its_path(monkeypatch):
    """Two admitted Routes may share a host at different paths; only working serves /."""
    objects = web_state()
    route = objects["route", "shop"]
    route["spec"]["path"] = "/other"
    route["status"]["ingress"][0]["conditions"] = [{"type": "Admitted", "status": "True"}]
    working = copy.deepcopy(route)
    working["metadata"]["name"] = "working"
    working["spec"]["path"] = "/"
    objects["route", "working"] = working
    install_web_responses(monkeypatch, objects)
    lab = labs.load()["ch.ship-web-app"]
    c = next(c for c in lab.checks if c.id == "outside")
    observed = checks.run_check(lab.namespace, c.model_dump())
    assert observed["status"] != "pass", observed


def test_trial_single_match_at_deadline_is_not_stable(monkeypatch):
    """An expected grade first seen at the deadline must not bypass the two-sample rule."""
    lab = labs.load()["ch.protect-traffic"].model_copy(deep=True)
    lab.trials = [next(t for t in lab.trials if t.id == "tier-label")]
    clock = [0]
    monkeypatch.setattr(recorder.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(recorder.time, "sleep", lambda n: clock.__setitem__(0, clock[0] + n))
    monkeypatch.setattr(labs, "cleanup", lambda *a, **k: {"state": "clean"})
    monkeypatch.setattr(labs, "prepare", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(recorder, "settle", lambda *a, **k: None)
    monkeypatch.setattr(labs, "run_tracked", lambda l, c, f: f())
    monkeypatch.setattr(recorder, "run_cmd", lambda l, c: {"cmd": c.cmd, "ok": True, "code": 0})
    def verify(lab, only=None):
        outcomes = [{"id": c.id, "status": "fail" if c.id == "batch-blocked" and clock[0] >= 150 else "pass"}
                    for c in lab.checks]
        return {"verdict": checks.verdict(outcomes), "results": outcomes}
    monkeypatch.setattr(labs, "verify", verify)
    problems = []
    observed = recorder.run_trials(lab, problems, log=lambda *a: None)
    assert not observed[0]["ok"], (clock, observed, problems)


def test_allow_all_egress_does_not_count_as_restricting_clients(monkeypatch):
    """An allow-all egress policy leaves clients unrestricted and must not lose ingress credit."""
    policies = {"items": [{"metadata": {"name": "allow-egress"}, "spec": {
        "podSelector": {"matchLabels": {"app": "batch"}}, "policyTypes": ["Egress"], "egress": [{}]}}]}
    monkeypatch.setattr(checks, "_get", lambda *a, **k: (policies, result()))
    lab = labs.load()["ch.protect-traffic"]
    c = next(c for c in lab.checks if c.id == "no-egress")
    observed = checks.run_check(lab.namespace, c.model_dump())
    assert observed["status"] == "pass", observed


def test_coverage_rejects_partially_uncheckable_baseline(monkeypatch, tmp_path):
    """A timeout waiting for batch evidence must not turn infrastructure errors into live verification."""
    lab = labs.load()["ch.protect-traffic"]
    rec = copy.deepcopy(labs.recording(lab.id))
    assert rec["ok"]
    # Isolate baseline validation from the shipped recording's independent stale-hash failure.
    rec["lab_hash"] = labs.lab_hash(lab)
    for r in rec["verify_before"]["results"]:
        if r["id"] == "batch-blocked":
            r["status"] = "error"
            r["observed"] = "no running pod for app=batch to test from"
    rec["verify_before"]["verdict"] = checks.verdict(rec["verify_before"]["results"])
    (tmp_path / "docs").mkdir()
    (tmp_path / "coverage.yaml").write_text(yaml.safe_dump([{"track": "Review", "topics": [
        {"title": "Audit", "items": [lab.id]}]}]), encoding="utf-8")
    monkeypatch.setattr(coverage, "ROOT", tmp_path)
    monkeypatch.setattr(config, "content_dir", lambda lang: tmp_path)
    monkeypatch.setattr(curriculum, "load", lambda lang: {"lessons": {}})
    monkeypatch.setattr(labs, "load", lambda lang: {lab.id: lab})
    monkeypatch.setattr(labs, "recording", lambda lid: rec)
    monkeypatch.setattr(coverage, "write_lab_table", lambda labs: None)
    monkeypatch.setattr(sys, "argv", ["coverage.py"])
    assert coverage.main() == 0
    rendered = (tmp_path / "docs/COVERAGE.md").read_text(encoding="utf-8")
    assert "| **implemented** |" in rendered, rendered
