"""Offline adversarial contracts from an independent review of the graders.

Written as strict expected failures against the graders it reviewed; the graders were then fixed, so the
markers were removed and every case must now pass.

Fixtures model API responses, not admission/defaulting or live network behavior.
Every real cluster and HTTP entry point is forbidden.
"""
import copy
import json
from pathlib import Path

import pytest
import yaml

from academy import checks, kube


ROOT = Path(__file__).resolve().parents[1]
BUG = pytest.mark.xfail(strict=True, reason="Current grader accepts/rejects the counterexample; see G4 review")


def challenge(slug):
    return yaml.safe_load((ROOT / f"content/en/challenges/ch-{slug}.yaml").read_text(encoding="utf-8"))


def result(stdout="", code=0):
    return kube.Result([], code, stdout, "", 0, "ok")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unmocked cluster/network access")
    for name in ("oc", "oc_json", "read", "helm", "whoami"):
        monkeypatch.setattr(kube, name, forbidden)
    monkeypatch.setattr(checks.urllib.request, "build_opener", forbidden)


def state(slug):
    lab = challenge(slug)
    objects = {(o["kind"].lower(), o["metadata"]["name"]): o
               for text in lab["setup"] for o in yaml.safe_load_all(text)}
    if slug == "production-ready":
        alt = next(t for t in lab["trials"] if t["id"] == "one-manifest")
        objects.update({(o["kind"].lower(), o["metadata"]["name"]): o
                        for o in yaml.safe_load_all(alt["commands"][0]["stdin"])})
    elif slug == "bounded-cleanup":
        objects["cronjob", "debug-cleaner"] = {
            "metadata": {"name": "debug-cleaner"}, "spec": {
                "schedule": "*/30 * * * *", "concurrencyPolicy": "Forbid",
                "jobTemplate": {"spec": {"template": {"spec": {
                    "serviceAccountName": "debug-cleaner", "containers": [{
                        "name": "cleaner", "command": ["oc", "delete", "pods", "-l", "debug=true"]}]}}}}}}
        objects["job", "cleanup-now"] = {
            "metadata": {"name": "cleanup-now", "ownerReferences": [{"name": "debug-cleaner"}]},
            "status": {"succeeded": 1}}
        objects = {k: v for k, v in objects.items() if k[0] != "pod"}
    elif slug == "right-size":
        for name, cpu, mem in (("report", "200m", "160Mi"), ("cache", "10m", "32Mi")):
            ct = objects["deployment", name]["spec"]["template"]["spec"]["containers"][0]
            ct["resources"] = {"requests": {"cpu": cpu, "memory": mem},
                               "limits": {"cpu": cpu, "memory": mem}}
    elif slug == "slow-start":
        d = objects["deployment", "shop"]
        d["spec"]["strategy"] = {"rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1}}
        ct = d["spec"]["template"]["spec"]["containers"][0]
        ct["startupProbe"] = {"httpGet": {"port": 8080}, "failureThreshold": 12}
        ct["readinessProbe"] = {"httpGet": {"port": 8080}}

    pods = []
    for (kind, name), obj in objects.items():
        if kind == "route":
            obj["spec"]["host"] = f"{name}.apps.review.example"
            obj["status"] = {"ingress": [{"routerCanonicalHostname": "router.apps.review.example",
                                          "conditions": [{"type": "Admitted", "status": "True"}]}]}
        if kind != "deployment":
            continue
        obj["metadata"]["generation"] = 1
        n = obj["spec"].get("replicas", 1)
        obj["status"] = {"observedGeneration": 1, "replicas": n, "readyReplicas": n, "updatedReplicas": n}
        for i in range(n):
            pods.append({"metadata": {"name": f"{name}-abc-{i}", "labels": {"app": name},
                                      "annotations": {"openshift.io/scc": "restricted-v2"},
                                      "ownerReferences": [{"kind": "ReplicaSet", "name": f"{name}-abc"}]},
                         "spec": copy.deepcopy(obj["spec"]["template"]["spec"]),
                         "status": {"phase": "Running", "qosClass": "Guaranteed",
                                    "conditions": [{"type": "Ready", "status": "True"}],  # as every running, ready pod reports
                                    "containerStatuses": [{"ready": True, "restartCount": 0}]}})
    return lab, objects, pods


def grade(monkeypatch, s, extra_rules=()):
    lab, objects, pods = s

    def get(ns, kind, name=None, selector=None, **kwargs):
        if kind in ("pod", "pods"):
            items = pods
            if selector:
                key, value = selector.split("=", 1)
                items = [p for p in items if p["metadata"].get("labels", {}).get(key) == value]
            return {"items": items}, result()
        if not name:
            return {"items": [o for (k, _), o in objects.items() if k == kind]}, result()
        return objects.get((kind, name)), result()

    def oc(identity, args, **kwargs):
        if args[:2] == ["auth", "can-i"]:
            return result("yes")
        if args[:3] == ["create", "-f", "-"]:
            return result(json.dumps({"status": {"resourceRules": [
                {"apiGroups": [""], "resources": ["pods"], "verbs": ["list", "delete"]},
                *extra_rules]}}))
        assert args[0] == "exec", args
        if any("healthz" in a for a in args):
            return result("ok")  # outbound access to the API server still works
        # Fixed outcome fixtures: in the egress trial, batch isolation comes from Egress.
        return result("", 28) if args[1].startswith("batch-") else result("store ok")

    class Response:
        def __init__(self, url):
            self.status = 302 if url.startswith("http:") and lab["id"] == "ch.production-ready" else 200
            self.headers = {"Location": "https://store.apps.review.example/"}
        def read(self, *args):
            return b"store ok shop ok"
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    class Opener:
        def open(self, request, **kwargs):
            return Response(request.full_url)

    monkeypatch.setattr(checks, "_get", get)
    monkeypatch.setattr(kube, "oc", oc)
    monkeypatch.setattr(checks.urllib.request, "build_opener", lambda *args: Opener())
    outcomes = [checks.run_check(lab["namespace"], c) for c in lab["checks"]]
    assert all(o["status"] != "error" for o in outcomes), outcomes
    return checks.verdict(outcomes), {o["id"]: o["status"] for o in outcomes}


@pytest.mark.parametrize("slug", ["right-size", "bounded-cleanup", "slow-start", "production-ready"])
def test_reference_fixture(monkeypatch, slug):
    assert grade(monkeypatch, state(slug))[0] == "verified"


def test_G4_01_resource_only(monkeypatch):
    s = state("right-size")
    s[1]["deployment", "report"]["spec"]["template"]["spec"]["containers"][0]["command"] = ["sleep", "infinity"]
    assert grade(monkeypatch, s)[0] != "verified"


def test_G4_02_report_ownership(monkeypatch):
    s = state("right-size")
    s[1]["deployment", "report"]["spec"]["replicas"] = 0
    for p in s[2]:
        if p["metadata"]["labels"]["app"] == "report":
            p["metadata"].pop("ownerReferences")
    assert grade(monkeypatch, s)[0] != "verified"


def test_G4_03_total_cpu(monkeypatch):
    s = state("right-size")
    for p in s[2]:
        if p["metadata"]["labels"]["app"] == "report":
            p["spec"]["containers"].append({"name": "helper", "resources": {
                "requests": {"cpu": "900m", "memory": "16Mi"},
                "limits": {"cpu": "900m", "memory": "16Mi"}}})
    assert grade(monkeypatch, s)[1]["report-cpu"] == "fail"


def test_G4_04_cache_defaulted_requests(monkeypatch):
    s = state("right-size")
    del s[1]["deployment", "cache"]["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"]
    assert grade(monkeypatch, s)[0] == "verified"


def test_G4_05_pending_is_not_ready(monkeypatch):
    s = state("right-size")
    for p in s[2]:
        if p["metadata"]["labels"]["app"] == "cache":
            p["status"] = {"phase": "Pending", "containerStatuses": []}
    assert grade(monkeypatch, s)[1]["cache-ready"] == "fail"


def test_G4_06_suspended(monkeypatch):
    s = state("bounded-cleanup")
    s[1]["cronjob", "debug-cleaner"]["spec"]["suspend"] = True
    assert grade(monkeypatch, s)[0] != "verified"


def test_G4_07_noop_cleanup(monkeypatch):
    s = state("bounded-cleanup")
    ct = s[1]["cronjob", "debug-cleaner"]["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    ct["command"] = ["/bin/true"]
    assert grade(monkeypatch, s)[0] != "verified"


@pytest.mark.parametrize("rule,check", [
    ({"apiGroups": ["apps"], "resources": ["deployments/scale"], "verbs": ["patch"]}, "no-deployments"),
    ({"apiGroups": ["rbac.authorization.k8s.io"], "resources": ["roles", "rolebindings"], "verbs": ["deletecollection"]}, "no-rbac"),
])
def test_G4_08_forbidden_permissions(monkeypatch, rule, check):
    assert grade(monkeypatch, state("bounded-cleanup"), [rule])[1][check] == "fail"


def test_G4_09_equivalent_schedule(monkeypatch):
    s = state("bounded-cleanup")
    s[1]["cronjob", "debug-cleaner"]["spec"]["schedule"] = "15,45 * * * *"
    assert grade(monkeypatch, s)[0] == "verified"


def test_G4_10_success_history_gc(monkeypatch):
    s = state("bounded-cleanup")
    assert grade(monkeypatch, s)[0] == "verified"
    del s[1]["job", "cleanup-now"]
    # after history cleanup the CronJob's own status keeps the evidence (the controller records the last success)
    s[1]["cronjob", "debug-cleaner"]["status"] = {"lastSuccessfulTime": "2026-10-14T15:00:00Z"}
    assert grade(monkeypatch, s)[0] == "verified"


def test_G4_11_ineffective_liveness(monkeypatch):
    s = state("slow-start")
    s[1]["deployment", "shop"]["spec"]["template"]["spec"]["containers"][0]["livenessProbe"] = {"exec": {"command": ["/bin/true"]}}
    assert grade(monkeypatch, s)[0] != "verified"


def test_G4_12_paused_template(monkeypatch):
    s = state("slow-start")
    s[1]["deployment", "shop"]["spec"]["paused"] = True
    for p in s[2]:
        p["spec"]["containers"][0].pop("readinessProbe")
        p["spec"]["containers"][0].pop("livenessProbe")
    assert grade(monkeypatch, s)[0] != "verified"


@pytest.mark.parametrize("slug", ["slow-start", "production-ready"])
def test_G4_13_zero_percent(monkeypatch, slug):
    s = state(slug)
    name = "shop" if slug == "slow-start" else "store"
    s[1]["deployment", name]["spec"]["strategy"]["rollingUpdate"]["maxUnavailable"] = "0%"
    assert grade(monkeypatch, s)[0] == "verified"


def test_G4_14_delayed_restart(monkeypatch):
    s = state("slow-start")
    ct = s[1]["deployment", "shop"]["spec"]["template"]["spec"]["containers"][0]
    ct["livenessProbe"] = {"httpGet": {"port": 8081}, "initialDelaySeconds": 120, "failureThreshold": 1}
    early = grade(monkeypatch, s)[0]
    assert early != "verified"  # a liveness probe on the wrong port is rejected before it ever fires


def test_G4_15_egress_substitute(monkeypatch):
    s = state("production-ready")
    for key in list(s[1]):
        if key[0] == "networkpolicy":
            del s[1][key]
    s[1]["networkpolicy", "batch-egress"] = {"spec": {
        "podSelector": {"matchLabels": {"app": "batch"}}, "policyTypes": ["Egress"],
        "egress": [{"ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]}]}}
    assert grade(monkeypatch, s)[0] != "verified"


def test_G4_16_router_rule(monkeypatch):
    s = state("production-ready")
    del s[1]["networkpolicy", "allow-store-clients"]["spec"]["ingress"][1]
    assert grade(monkeypatch, s)[0] != "verified"


def test_G4_17_projected_decoy(monkeypatch):
    s = state("production-ready")
    tpl = s[1]["deployment", "store"]["spec"]["template"]["spec"]
    tpl["volumes"] = [{"name": "page", "projected": {"sources": [
        {"configMap": {"name": "store-content", "items": [{"key": "index.html", "path": "unused.html"}]}},
        {"configMap": {"name": "shadow", "items": [{"key": "index.html", "path": "index.html"}]}}
    ]}}]
    assert grade(monkeypatch, s)[1]["content"] == "fail"


def test_G4_18_parent_mount(monkeypatch):
    s = state("production-ready")
    tpl = s[1]["deployment", "store"]["spec"]["template"]["spec"]
    tpl["containers"][0]["volumeMounts"][0]["mountPath"] = "/var/www"
    tpl["volumes"][0]["configMap"]["items"] = [{"key": "index.html", "path": "html/index.html"}]
    assert grade(monkeypatch, s)[0] == "verified"
