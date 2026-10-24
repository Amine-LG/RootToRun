"""A lab command that changes the cluster asks the learner first. The confirmation shows what will run: the command's
`run` form when it differs from the displayed `cmd`, and the YAML it sends with `-f -`; for an admin command, before
anything runs as cluster-admin. No cluster or process is used."""
import pytest
from fastapi.testclient import TestClient

from academy import environment, kube, labs, main, recorder

c = TestClient(main.app)
H = {"X-Academy": "1"}


@pytest.fixture
def lab(monkeypatch):
    base = labs.load("en")["lab.quotas-limits"].model_dump(by_alias=True)
    yaml_doc = "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: settings}\ndata: {mode: demo}\n"
    base["commands"] = [
        {"cmd": "oc get pods", "run": "oc delete configmap settings -n {ns}", "as": "admin"},
        {"cmd": "oc apply -f -", "stdin": yaml_doc, "as": "admin"},
        {"cmd": "oc get pods", "run": "oc delete configmap settings", "as": "learner"},
    ]
    probe = labs.Lab.model_validate(base)
    monkeypatch.setattr(main, "_lab", lambda *a: probe)
    monkeypatch.setattr(main, "need_cluster", lambda: None)
    monkeypatch.setattr(main, "need_training", lambda what="": None)
    monkeypatch.setattr(kube, "whoami", lambda identity: {"connected": True})
    monkeypatch.setattr(environment, "same_cluster", lambda identity: True)
    monkeypatch.setattr(recorder, "run_cmd", lambda *a: pytest.fail("ran without the learner's confirmation"))
    return probe


def ask(index):
    r = c.post("/api/labs/lab.quotas-limits/exec", headers=H, json={"where": "commands", "index": index, "confirm": False})
    assert r.status_code == 200, r.text
    return r.json()


def test_an_admin_command_is_confirmed_as_it_will_run(lab):
    r = ask(0)
    assert r["needs_confirm"] and r["admin"]
    assert r["display"] == "oc delete configmap settings -n {ns}"  # not the displayed "oc get pods"


def test_the_yaml_an_admin_command_sends_is_shown(lab):
    r = ask(1)
    assert r["needs_confirm"] and r["display"].startswith("oc apply -f -\n") and "kind: ConfigMap" in r["display"]


def test_a_learner_command_that_writes_is_confirmed_as_it_will_run(lab):
    r = ask(2)
    assert r["needs_confirm"] and r["display"] == "oc delete configmap settings"
