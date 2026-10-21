"""Declarative check helpers: field paths and comparisons decide verdicts, so they must be exact."""
from academy import checks

OBJ = {
    "metadata": {"annotations": {"openshift.io/scc": "restricted-v2"}},
    "spec": {"template": {"spec": {"containers": [{"env": [{"name": "A", "value": "1"}, {"name": "MODE", "value": "live"}]}]}}},
    "status": {"conditions": [{"type": "Available", "reason": "MinimumReplicasAvailable"}, {"type": "Progressing", "reason": "NewReplicaSetAvailable"}]},
}


def test_dig_escaped_dots_and_filters():
    assert checks.dig(OBJ, r"metadata.annotations.openshift\.io/scc") == "restricted-v2"
    assert checks.dig(OBJ, "spec.template.spec.containers[0].env[?name=MODE].value") == "live"
    assert checks.dig(OBJ, "status.conditions[?type=Progressing].reason") == "NewReplicaSetAvailable"
    assert checks.dig(OBJ, "status.conditions[?type=Missing].reason") is None


def test_compare():
    assert checks.compare(3, "gte", 1)
    assert not checks.compare(0, "gte", 1)
    assert checks.compare(None, "absent", None)
    assert checks.compare("abc", "contains", "b")
    assert checks.compare("abc", "matches", "^a")
    assert not checks.compare("abc", "eq", "abd")


def test_verdict_is_never_verified_unless_every_check_passes():
    ok = {"status": "pass"}
    assert checks.verdict([ok, ok]) == "verified"
    assert checks.verdict([ok, {"status": "fail"}]) == "partial"
    assert checks.verdict([{"status": "fail"}]) == "failed"
    assert checks.verdict([ok, {"status": "error"}]) != "verified"
    # a real failure next to a check that could not run is a failure, not "could not check"
    assert checks.verdict([{"status": "fail"}, {"status": "error"}]) == "failed"
    assert checks.verdict([{"status": "error"}, {"status": "error"}]) == "unavailable"


def test_rules_deny_survives_several_matching_rules(monkeypatch):
    """Found by a grader trial on the cluster: after one matching rule with resourceNames, the next rule crashed the
    check (a variable was reused), so a role with many rules (admin) graded as 'could not check' instead of 'fail'."""
    import json
    from types import SimpleNamespace

    from academy import checks, kube

    rules = [
        {"apiGroups": ["apps"], "resources": ["deployments"], "verbs": ["get"], "resourceNames": ["web"]},
        {"apiGroups": ["apps"], "resources": ["deployments"], "verbs": ["delete", "patch"]},
        {"apiGroups": [""], "resources": ["secrets"], "verbs": ["list"]},
    ]
    out = json.dumps({"status": {"incomplete": False, "resourceRules": rules}})
    monkeypatch.setattr(kube, "oc", lambda *a, **k: SimpleNamespace(stdout=out, stderr="", code=0, status="ok"))
    r = checks.c_rules_deny("ns", {"as": "bot", "forbid": [{"resource": "deployments.apps", "verbs": ["delete"]}, {"resource": "secrets", "verbs": ["get", "list"]}]})
    assert r["status"] == "fail" and "delete deployments.apps" in r["observed"] and "list secrets" in r["observed"], r


def test_quantities_compare_with_units():
    from academy.checks import compare, quantity

    assert quantity("500m") == 0.5 and quantity("128Mi") == 128 * 2**20 and quantity("2") == 2
    assert compare("250m", "qlte", "1") and not compare("1500m", "qlte", "1")
    assert compare("160Mi", "qgte", "96Mi") and not compare(None, "qlte", "1") and not compare("lots", "qgte", "1")


def test_helm_release_reads_effective_values_of_newest_revision(monkeypatch):
    import base64
    import gzip
    import json
    from types import SimpleNamespace

    from academy import checks

    def secret(version, status, config):
        rel = {"name": "shop", "version": version, "info": {"status": status}, "config": config,
               "chart": {"values": {"replicas": 1, "message": "hello"}}}
        inner = base64.b64encode(gzip.compress(json.dumps(rel).encode())).decode()
        return {"metadata": {"labels": {"owner": "helm", "name": "shop", "version": str(version)}},
                "data": {"release": base64.b64encode(inner.encode()).decode()}}

    items = [secret(1, "superseded", {}), secret(2, "deployed", {"replicas": 3, "message": "shop-v2"})]
    monkeypatch.setattr(checks, "_get", lambda *a, **k: ({"items": items}, SimpleNamespace(status="ok", stderr="")))
    ok = checks.c_helm_release("ns", {"release": "shop", "values": {"replicas": 3, "message": "shop-v2"}})
    assert ok["status"] == "pass", ok
    bad = checks.c_helm_release("ns", {"release": "shop", "values": {"replicas": 4}})
    assert bad["status"] == "fail" and "replicas = 3" in bad["observed"], bad
    items.append(secret(3, "failed", {"replicas": 3, "message": "shop-v2"}))
    assert checks.c_helm_release("ns", {"release": "shop", "values": {}})["status"] == "fail"
    monkeypatch.setattr(checks, "_get", lambda *a, **k: ({"items": []}, SimpleNamespace(status="ok", stderr="")))
    assert checks.c_helm_release("ns", {"release": "shop"})["status"] == "fail"


def test_env_source_and_secret_mount():
    from academy.checks import _env_source, _file_source

    by_ref = {"env": [{"name": "GREETING", "valueFrom": {"configMapKeyRef": {"name": "app-settings", "key": "GREETING"}}}]}
    whole = {"envFrom": [{"configMapRef": {"name": "app-settings"}}]}
    prefixed = {"envFrom": [{"configMapRef": {"name": "app-settings"}, "prefix": "APP_"}]}
    literal = {"env": [{"name": "GREETING", "value": "Bonjour"}], "envFrom": [{"configMapRef": {"name": "app-settings"}}]}
    want = {"var": "GREETING", "configmap": "app-settings"}
    assert _env_source(by_ref, want) is None and _env_source(whole, want) is None
    assert _env_source(prefixed, want) and _env_source(literal, want), "a prefix renames it; a literal entry wins over envFrom"
    vols = {"db": {"name": "db", "secret": {"secretName": "db-credentials"}}, "other": {"name": "other", "secret": {"secretName": "x", "items": [{"key": "p", "path": "password"}]}}}
    want = {"name": "db-credentials", "path": "/etc/db", "file": "password"}
    assert _file_source({"volumeMounts": [{"name": "db", "mountPath": "/etc/db"}]}, vols, want, "Secret") is None
    assert _file_source({"volumeMounts": [{"name": "db", "mountPath": "/etc/db"}, {"name": "other", "mountPath": "/etc/db/password", "subPath": "password"}]}, vols, want, "Secret")


def test_lesson_recordings_redact_machine_identity():
    from academy.recorder import redact

    pairs = [("/home/alice", "/home/learner"), ("alice", "learner"), ("box1.lan", "workstation")]
    out = redact("uid=1000(alice) gid=1000(alice) /home/alice/x box1.lan:22 malice alice-x", pairs)
    assert out == "uid=1000(learner) gid=1000(learner) /home/learner/x workstation:22 malice alice-x"


from types import SimpleNamespace  # noqa: E402


def _netpols(monkeypatch, *pols):
    items = [{"metadata": {"name": f"p{i}"}, "spec": spec} for i, spec in enumerate(pols)]
    monkeypatch.setattr(checks, "_get", lambda *a, **k: ({"items": items}, SimpleNamespace(status="ok", stderr="")))


ROUTER = {"policy-group.network.openshift.io/ingress": ""}
FROM_ROUTER = [{"namespaceSelector": {"matchLabels": ROUTER}}]


def test_a_router_rule_on_the_wrong_port_does_not_admit_the_application(monkeypatch):
    c = {"type": "netpol_ingress", "labels": {"app": "store"}, "isolated": True, "peer_ns_labels": ROUTER, "allows": True, "port": 8080, "port_name": "http"}
    _netpols(monkeypatch, {"podSelector": {"matchLabels": {"app": "store"}}, "ingress": [{"from": FROM_ROUTER, "ports": [{"protocol": "TCP", "port": 9999}]}]})
    assert checks.run_check("ns", c)["status"] == "fail"
    for ports in ([{"port": 8080}], [{"protocol": "TCP", "port": "http"}], [{"port": 8000, "endPort": 8100}], None):
        rule = {"from": FROM_ROUTER, **({"ports": ports} if ports else {})}
        _netpols(monkeypatch, {"podSelector": {"matchLabels": {"app": "store"}}, "ingress": [rule]})
        assert checks.run_check("ns", c)["status"] == "pass", ports


def test_egress_isolation_evaluates_the_whole_selector(monkeypatch):
    c = {"type": "netpol_ingress", "direction": "Egress", "labels": {"app": "client"}, "isolated": True}
    # app=client plus a label the client does not carry selects no client pod
    _netpols(monkeypatch, {"podSelector": {"matchLabels": {"app": "client", "tier": "x"}}, "policyTypes": ["Egress"]})
    assert checks.run_check("ns", c)["status"] == "fail"
    # an equivalent matchExpressions selector, and a policy with egress rules but no policyTypes, both count
    _netpols(monkeypatch, {"podSelector": {"matchExpressions": [{"key": "app", "operator": "In", "values": ["client"]}]}, "policyTypes": ["Egress"]})
    assert checks.run_check("ns", c)["status"] == "pass"
    _netpols(monkeypatch, {"podSelector": {"matchLabels": {"app": "client"}}, "egress": [{"to": []}]})
    assert checks.run_check("ns", c)["status"] == "pass"
    # an ingress-only policy does not isolate egress
    _netpols(monkeypatch, {"podSelector": {"matchLabels": {"app": "client"}}, "policyTypes": ["Ingress"]})
    assert checks.run_check("ns", c)["status"] == "fail"


def test_field_ref_compares_two_objects(monkeypatch):
    objs = {("deployment", "hello"): {"spec": {"template": {"spec": {"containers": [{"image": "reg/p/hello@sha256:bbb"}]}}}},
            ("build", "hello-2"): {"status": {"output": {"to": {"imageDigest": "sha256:bbb"}}}}}
    monkeypatch.setattr(checks, "_get", lambda ns, kind, name=None, **k: (objs.get((kind, name)), SimpleNamespace(status="ok", stderr="")))
    c = {"type": "field_ref", "kind": "deployment", "name": "hello", "path": "spec.template.spec.containers[0].image", "op": "contains",
         "ref": {"kind": "build", "name": "hello-2", "path": "status.output.to.imageDigest"}}
    assert checks.run_check("ns", c)["status"] == "pass"
    objs[("deployment", "hello")]["spec"]["template"]["spec"]["containers"][0]["image"] = "reg/p/hello@sha256:aaa"
    assert checks.run_check("ns", c)["status"] == "fail"
    objs[("build", "hello-2")]["status"] = {}  # no digest yet: never a pass
    assert checks.run_check("ns", c)["status"] == "fail"
