"""Validating a Helm upgrade must never change what the learner's command does."""
from academy import kube, policy, runner


def _fake_helm(calls):
    def helm(identity, args, timeout=None):
        calls.append(list(args))
        if args[:2] == ["get", "values"]:
            return kube.Result(["helm", *args], 0, "replicas: 3\n", "", 0)
        if args[:1] == ["get"]:
            return kube.Result(["helm", *args], 0, "", "", 0)
        if args[:1] == ["template"]:
            return kube.Result(["helm", *args], 0, "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: x\n", "", 0)
        return kube.Result(["helm", *args], 0, "ok", "", 0)
    return helm


def test_upgrade_without_values_is_not_rewritten(monkeypatch, tmp_path):
    (tmp_path / "chart").mkdir()
    calls = []
    monkeypatch.setattr(kube, "helm", _fake_helm(calls))
    p = policy.plan("helm upgrade demo lab/chart -n academy-declarative", labdir=str(tmp_path))
    before = list(p.argv)
    runner._validate_helm(p, 30)
    assert p.argv == before, "the learner's argv was modified"
    render = next(c for c in calls if c[0] == "template")
    assert "-f" in render, "rendering must use the release's previous values, as `helm upgrade` would"


def test_upgrade_with_values_renders_those_values(monkeypatch, tmp_path):
    (tmp_path / "chart").mkdir()
    calls = []
    monkeypatch.setattr(kube, "helm", _fake_helm(calls))
    p = policy.plan("helm upgrade demo lab/chart --set replicas=2 -n academy-declarative", labdir=str(tmp_path))
    runner._validate_helm(p, 30)
    render = next(c for c in calls if c[0] == "template")
    assert "--set=replicas=2" in render and not any(c[:2] == ["get", "values"] for c in calls)


def test_an_empty_values_file_still_renders_with_the_previous_values(monkeypatch, tmp_path):
    (tmp_path / "chart").mkdir()
    (tmp_path / "empty.yaml").write_text("# nothing\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(kube, "helm", _fake_helm(calls))
    p = policy.plan("helm upgrade demo lab/chart -f lab/empty.yaml -n academy-declarative", labdir=str(tmp_path))
    runner._validate_helm(p, 30)
    assert any(c[:2] == ["get", "values"] for c in calls), "Helm reuses stored values when the supplied file is empty"


def test_validation_never_deletes_the_learners_values_file(monkeypatch, tmp_path):
    (tmp_path / "chart").mkdir()
    values = tmp_path / "values.yaml"
    values.write_text("replicas: 2\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(kube, "helm", _fake_helm(calls))
    monkeypatch.setattr(runner.tempfile, "gettempdir", lambda: str(tmp_path))  # lab files living under the temp dir
    p = policy.plan("helm upgrade demo lab/chart -f lab/values.yaml -n academy-declarative", labdir=str(tmp_path))
    runner._validate_helm(p, 30)
    assert values.exists()
