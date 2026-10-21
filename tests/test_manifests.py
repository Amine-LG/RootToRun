"""Shared manifest and execution validation tests: no processes or cluster calls."""
from copy import deepcopy
from types import SimpleNamespace
import subprocess

import pytest
import yaml

from academy import kube, manifests, policy, runner

NS = "academy-x"


@pytest.fixture(autouse=True)
def no_subprocess(monkeypatch):
    def refused(*args, **kwargs):
        pytest.fail(f"unexpected subprocess.run call: {args[0]!r}")
    monkeypatch.setattr(subprocess, "run", refused)


def obj(kind="ConfigMap", namespace=None, **fields):
    group = manifests.KIND_GROUPS.get(kind, "")
    result = {"apiVersion": f"{group}/v1" if group else "v1", "kind": kind, "metadata": {"name": "test"}, **fields}
    if namespace is not None:
        result["metadata"]["namespace"] = namespace
    return result


def wrapper(children, kind="List"):
    return obj(kind, **{manifests.WRAPPERS[kind]: children}, apiVersion="template.openshift.io/v1" if kind == "Template" else "v1")


def test_namespace_forced_without_mutating_input():
    source = [wrapper([obj(), wrapper([obj("Secret")], "Template")])]
    original = deepcopy(source)
    validated = manifests.validate_manifests(source, NS)
    assert source == original
    assert validated[0]["items"][0]["metadata"]["namespace"] == NS
    assert validated[0]["items"][1]["objects"][0]["metadata"]["namespace"] == NS


@pytest.mark.parametrize("depth", [0, 1, 3, 8])
@pytest.mark.parametrize("bad", [obj("Group"), obj("ValidatingAdmissionPolicy"), obj("NeverHeardOfThis"), obj(namespace="default"), obj("Secret", type="kubernetes.io/service-account-token")])
def test_nested_objects_share_the_boundary(depth, bad):
    source = bad
    for i in range(depth):
        source = wrapper([obj(), source], "List" if i % 2 else "Template")
    with pytest.raises(manifests.ManifestRefused):
        manifests.validate_manifests([source], NS)


@pytest.mark.parametrize("kind", sorted(manifests.WRITE_KINDS))
def test_known_write_kinds(kind):
    assert manifests.validate_manifests([obj(kind)], NS)[0]["metadata"]["namespace"] == NS


@pytest.mark.parametrize("source", [False, 0, "scalar", [], {}, {"kind": "ConfigMap"}, obj(metadata=[]), obj(metadata=None), obj(metadata={"namespace": 1}), obj(metadata={"namespace": ""}), obj(apiVersion=[]), obj(apiVersion="apps/v1/extra"), wrapper(False), wrapper(None), obj("ConfigMapList"), obj(items="bad"), obj("Secret", metadata={"annotations": []})])
def test_malformed_documents_are_learner_facing(source):
    with pytest.raises(manifests.ManifestRefused):
        manifests.validate_manifests([source], NS)


def test_empty_yaml_documents_ignored_but_false_is_not():
    assert manifests.validate_manifests("---\n---\n", NS) == []
    with pytest.raises(manifests.ManifestRefused):
        manifests.validate_manifests("false", NS)


def test_recursive_alias_refused():
    source = "&self\napiVersion: v1\nkind: List\nitems: [*self]"
    with pytest.raises(manifests.ManifestRefused, match="recursive"):
        manifests.validate_manifests(source, NS)


def test_depth_limit():
    source = obj()
    for _ in range(22):
        source = wrapper([source])
    with pytest.raises(manifests.ManifestRefused, match="deeply"):
        manifests.validate_manifests([source], NS)


@pytest.mark.parametrize("kind", ["Deployment", "Secret", "Route"])
def test_familiar_kind_in_unapproved_api_group_is_refused(kind):
    with pytest.raises(manifests.ManifestRefused, match="API group"):
        manifests.validate_manifests([obj(kind, apiVersion="evil.example/v1")], NS)


@pytest.mark.parametrize("source", [obj("List", items=[obj()], apiVersion="evil.example/v1"), obj("Template", objects=[obj()], apiVersion="v1")])
def test_wrapper_api_groups_checked(source):
    with pytest.raises(manifests.ManifestRefused):
        manifests.validate_manifests([source], NS)


def test_elevated_allowance_is_explicit_and_recursive():
    source = wrapper([obj("Group"), obj()])
    validated = manifests.validate_manifests([source], NS, elevated_kinds={"Group"})
    assert "namespace" not in validated[0]["items"][0]["metadata"]
    with pytest.raises(manifests.ManifestRefused):
        manifests.validate_manifests([source], NS, elevated_kinds={"ClusterRole"})
    with pytest.raises(manifests.ManifestRefused):
        manifests.validate_manifests([obj("Group", NS)], NS, elevated_kinds={"Group"})


def test_unknown_elevated_kind_requires_discovery_and_explicit_allowance():
    source = [obj("CustomGuardrail", apiVersion="example.io/v1")]
    with pytest.raises(manifests.ManifestRefused, match="unknown scope"):
        manifests.validate_manifests(source, NS, elevated_kinds={"CustomGuardrail"})
    assert manifests.validate_manifests(source, NS, elevated_kinds={"CustomGuardrail"}, kind_scopes={"CustomGuardrail": False})
    with pytest.raises(manifests.ManifestRefused):
        manifests.validate_manifests(source, NS, kind_scopes={"CustomGuardrail": True})


def test_allowed_kinds_narrows_elevated_setup():
    allowed = {"ResourceQuota", "LimitRange", "RoleBinding"}
    assert manifests.validate_manifests([obj("ResourceQuota")], NS, allowed_kinds=allowed)
    with pytest.raises(manifests.ManifestRefused, match="allowed writable"):
        manifests.validate_manifests([wrapper([obj()])], NS, allowed_kinds=allowed)


def test_setup_unset_mode_can_validate_before_namespace_is_available():
    validated = manifests.validate_manifests([obj()], None, namespace_mode="unset")
    assert "namespace" not in validated[0]["metadata"]
    with pytest.raises(manifests.ManifestRefused, match="leave metadata.namespace unset"):
        manifests.validate_manifests([wrapper([obj(namespace=NS)])], NS, namespace_mode="unset")


def test_check_mode_and_missing_namespace():
    assert "namespace" not in manifests.validate_manifests([obj()], NS, namespace_mode="check")[0]["metadata"]
    assert manifests.validate_manifests([obj(namespace=NS)], NS)
    with pytest.raises(manifests.ManifestRefused, match="needs a lab namespace"):
        manifests.validate_manifests([obj()], None)


@pytest.mark.parametrize("secret_type", ["Opaque", "kubernetes.io/tls", "kubernetes.io/dockerconfigjson", "kubernetes.io/dockercfg"])
def test_ordinary_lab_secrets_preserved(secret_type):
    assert manifests.validate_manifests([obj("Secret", type=secret_type, stringData={"password": "lab-only"})], NS)


def test_serviceaccounts_preserved_but_token_secret_provisioning_refused():
    assert manifests.validate_manifests([obj("ServiceAccount", automountServiceAccountToken=True)], NS)
    secret = obj("Secret", metadata={"annotations": {"kubernetes.io/service-account.name": "reporter"}})
    with pytest.raises(manifests.ManifestRefused, match="token Secrets"):
        manifests.validate_manifests([secret], NS)


def test_nested_items_on_ordinary_kind_cannot_hide_objects():
    with pytest.raises(manifests.ManifestRefused):
        manifests.validate_manifests([obj(items=[obj("ClusterRole")])], NS)


def test_reason_facade_uses_shared_validator():
    assert runner.check_manifests is manifests.check_manifests
    assert manifests.check_manifests([obj()], NS) is None
    assert "unknown" in manifests.check_manifests([obj("Unknown")], NS)


@pytest.mark.parametrize("command", ["oc adm upgrade --to-image=unsafe --allow-explicit-upgrade", "oc debug deploy/web --to-namespace default -- id", "oc exec deploy/web -- id"])
def test_refused_commands_never_reach_cluster(monkeypatch, command):
    calls = []
    monkeypatch.setattr(kube, "oc", lambda *a, **kw: calls.append(a))
    result = runner.execute(command, "reader", NS)
    assert result["refused"] is True and calls == []


@pytest.mark.parametrize("stdin", [yaml.safe_dump(wrapper([obj("Group")])), yaml.safe_dump(obj(namespace="default")), "kind: [", yaml.safe_dump(obj("Secret", type="kubernetes.io/service-account-token")), yaml.safe_dump(obj("Unknown"))])
def test_editor_refusals_never_reach_cluster(monkeypatch, stdin):
    calls = []
    monkeypatch.setattr(kube, "oc", lambda *a, **kw: calls.append(a))
    result = runner.execute("oc apply -f - -n academy-x", stdin=stdin)
    assert result["refused"] is True and calls == []


def test_runner_sends_validated_namespaces_to_oc(monkeypatch):
    calls = []
    def fake_oc(identity, argv, **kwargs):
        calls.append((identity, argv, kwargs))
        return kube.Result(["oc", *argv], 0, "created", "", 0)
    monkeypatch.setattr(kube, "oc", fake_oc)
    result = runner.execute("oc apply --filename=- -n academy-x", stdin=yaml.safe_dump(wrapper([obj()])))
    assert result["write"] is True
    assert len(calls) == 1
    sent = yaml.safe_load(calls[0][2]["stdin"])
    assert sent["items"][0]["metadata"]["namespace"] == NS


def test_lab_file_validation_prevents_cluster_write(monkeypatch, tmp_path):
    lab = SimpleNamespace(id="test-lab", files={"bad.yaml": ""}, namespace=NS)
    monkeypatch.setattr(runner.labs, "labfiles_dir", lambda _: tmp_path)
    (tmp_path / "bad.yaml").write_text(yaml.safe_dump(wrapper([obj("Group")])), encoding="utf-8")
    calls = []
    monkeypatch.setattr(kube, "oc", lambda *a, **kw: calls.append(a))
    result = runner.execute("oc apply -f lab/bad.yaml", lab=lab)
    assert result["refused"] and calls == []


def test_lab_files_replaced_with_normalized_editor_input(monkeypatch, tmp_path):
    lab = SimpleNamespace(id="test-lab", files={"good.yaml": ""}, namespace=NS)
    monkeypatch.setattr(runner.labs, "labfiles_dir", lambda _: tmp_path)
    (tmp_path / "good.yaml").write_text(yaml.safe_dump(obj()), encoding="utf-8")
    calls = []
    def fake_oc(identity, argv, **kwargs):
        calls.append((argv, kwargs))
        return kube.Result(["oc", *argv], 0, "ok", "", 0)
    monkeypatch.setattr(kube, "oc", fake_oc)
    assert runner.execute("oc apply -f lab/good.yaml", lab=lab)["write"]
    argv, kwargs = calls[0]
    assert "-f" in argv and str(tmp_path / "good.yaml") not in argv
    assert yaml.safe_load(kwargs["stdin"])["metadata"]["namespace"] == NS


@pytest.mark.parametrize("verb", ["install", "upgrade", "rollback", "uninstall"])
def test_helm_cluster_scope_refused_before_mutation(monkeypatch, verb):
    calls = []
    def fake_helm(identity, argv, **kwargs):
        calls.append(argv)
        return kube.Result(["helm", *argv], 0, yaml.safe_dump(obj("ClusterRole")), "", 0)
    monkeypatch.setattr(kube, "helm", fake_helm)
    lab = SimpleNamespace(id="test-lab", files={"chart/Chart.yaml": ""}, namespace=NS)
    suffix = " lab/chart" if verb in ("install", "upgrade") else " 1" if verb == "rollback" else ""
    result = runner.execute(f"helm {verb} demo{suffix}", lab=lab)
    assert result["refused"]
    assert calls and all(argv[0] != verb for argv in calls)


def test_helm_template_options_match_upgrade_options(monkeypatch):
    calls = []
    def fake_helm(identity, argv, **kwargs):
        calls.append(argv.copy())
        return kube.Result(["helm", *argv], 0, yaml.safe_dump(obj()), "", 0)
    monkeypatch.setattr(kube, "helm", fake_helm)
    lab = SimpleNamespace(id="test-lab", files={"chart/Chart.yaml": "", "values.yaml": ""}, namespace=NS)
    result = runner.execute("helm upgrade demo lab/chart --set replicas=2 --set-string message=hello -f lab/values.yaml", lab=lab)
    assert result["write"]
    template = next(argv for argv in calls if argv[0] == "template")
    assert "--include-crds" in template and "--is-upgrade" in template
    assert "--set=replicas=2" in template and "--set-string=message=hello" in template
    # The executed command is exactly the learner's: validation never adds options such as --reset-values.
    executed = calls[-1]
    assert executed[0] == "upgrade" and "--reset-values" not in executed


def test_helm_hooks_and_historical_revision_checked(monkeypatch):
    calls = []
    def fake_helm(identity, argv, **kwargs):
        calls.append(argv)
        unsafe = "--revision" in argv and argv[1] == "hooks"
        return kube.Result(["helm", *argv], 0, yaml.safe_dump(obj("Group") if unsafe else obj()), "", 0)
    monkeypatch.setattr(kube, "helm", fake_helm)
    result = runner.execute("helm rollback demo 1 -n academy-x")
    assert result["refused"]
    assert calls[-1] == ["get", "hooks", "demo", "--revision", "1", "-n", NS]
    assert not any(argv[0] == "rollback" for argv in calls)


def test_rendered_kustomize_checked_before_apply(monkeypatch):
    calls = []
    def fake_oc(identity, argv, **kwargs):
        calls.append(argv)
        return kube.Result(["oc", *argv], 0, yaml.safe_dump(obj("Group")), "", 0)
    monkeypatch.setattr(kube, "oc", fake_oc)
    lab = SimpleNamespace(id="test-lab", files={"kustomize/kustomization.yaml": ""}, namespace=NS)
    result = runner.execute("oc apply -k lab/kustomize", lab=lab)
    assert result["refused"] and len(calls) == 1 and calls[0][0] == "kustomize"


def test_all_shipped_setup_and_editor_manifests_use_allowlisted_kinds():
    from academy import labs
    failures = []
    checked = 0
    for lab in labs.load("en").values():
        for field in ("setup", "break_", "elevated_setup"):
            for text in getattr(lab, field):
                try:
                    manifests.validate_manifests(text, lab.namespace, namespace_mode="unset", allowed_kinds=labs.ELEVATED_KINDS if field == "elevated_setup" else None)
                except manifests.ManifestRefused as exc:
                    failures.append(f"{lab.id} {field}: {exc}")
                checked += 1
        for where, command in lab.all_commands():
            if command.stdin and command.as_ != "admin" and not command.skip:
                try:
                    manifests.validate_manifests(command.stdin, lab.namespace)
                except manifests.ManifestRefused as exc:
                    failures.append(f"{lab.id} {where}: {exc}")
                checked += 1
    assert checked > 60
    assert not failures, "\n".join(failures)
