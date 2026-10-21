"""Live labs only on a cluster the operator approved; approval is bound to the cluster's identity."""
import pytest
from fastapi.testclient import TestClient

from academy import config, environment, kube

KC = """apiVersion: v1
kind: Config
clusters: [{name: c, cluster: {server: "%s", certificate-authority: ca.crt}}]
contexts: [{name: x, context: {cluster: c, user: u}}]
current-context: x
users: [{name: u, user: {token: t}}]
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    kd = tmp_path / "kube"
    kd.mkdir()
    (kd / "ca.crt").write_text("CA-ONE", encoding="utf-8")
    monkeypatch.setattr(config, "KUBE_DIR", kd)
    monkeypatch.setattr(environment, "APPROVALS", tmp_path / "cluster-approvals.json")
    monkeypatch.setattr(config, "cluster_enabled", lambda: True)
    monkeypatch.setattr(kube, "crc_status", lambda: {"openshiftStatus": "Running"})
    environment.invalidate()

    def connect(identity, server="https://api.crc.testing:6443"):
        (kd / f"{identity}.kubeconfig").write_text(KC % server, encoding="utf-8")

    return connect, kd


def test_connected_cluster_is_read_only_until_approved(env):
    connect, _ = env
    connect("learner")
    e = environment.current()
    assert e["class"] == "read-only" and e["crc"] is True  # detection is only a hint


def test_approval_needs_the_exact_host(env):
    connect, _ = env
    connect("learner")
    with pytest.raises(ValueError):
        environment.approve("")
    with pytest.raises(ValueError):
        environment.approve("api.other.example")
    assert environment.approve("api.crc.testing")["class"] == "training"


def test_approval_does_not_follow_a_changed_kubeconfig(env):
    connect, kd = env
    connect("learner")
    environment.approve("api.crc.testing")
    connect("learner", "https://api.prod.example.com:6443")  # same file, another cluster
    assert environment.current()["class"] == "read-only"
    connect("learner")
    (kd / "ca.crt").write_text("CA-TWO", encoding="utf-8")  # same URL, different CA: a different cluster as far as we can tell
    assert environment.current()["class"] == "read-only"


def test_admin_on_another_cluster_does_not_count(env):
    connect, _ = env
    connect("learner")
    connect("admin", "https://api.prod.example.com:6443")
    assert environment.same_cluster("admin") is False
    connect("admin")
    assert environment.same_cluster("admin") is True


def test_api_refuses_mutations_on_an_unapproved_cluster(env, monkeypatch):
    connect, _ = env
    connect("learner")
    from academy.main import app

    c = TestClient(app, headers={"X-Academy": "1", "Host": "127.0.0.1"})
    r = c.post("/api/labs/lab.groups/prepare", json={"confirm": True})
    assert r.status_code == 409 and "not approved" in r.json()["detail"]
    r = c.post("/api/workbench/run", json={"command": "oc create configmap x -n academy-groups", "identity": "learner", "namespace": "academy-groups", "confirm": True})
    assert r.status_code == 409
    r = c.post("/api/connect", json={"identity": "admin", "confirm": "anything"})
    assert r.status_code == 409


def test_approval_does_not_survive_turning_tls_verification_off(env):
    connect, kd = env
    connect("learner")
    environment.approve("api.crc.testing")
    (kd / "learner.kubeconfig").write_text((kd / "learner.kubeconfig").read_text(encoding="utf-8").replace("certificate-authority: ca.crt", "certificate-authority: ca.crt, insecure-skip-tls-verify: true"), encoding="utf-8")
    assert environment.current()["class"] == "read-only"


def test_approval_accepts_the_api_address_as_the_page_shows_it(env):
    connect, _ = env
    connect("learner")
    assert environment.current()["host"] == "api.crc.testing"  # the page shows the exact host to type
    for typed in ("  API.CRC.TESTING ", "https://api.crc.testing:6443", "https://api.crc.testing:6443/"):
        environment.revoke()
        assert environment.approve(typed)["class"] == "training", typed
    environment.revoke()
    for wrong in ("https://api.other.example:6443", "api.crc.testing.evil", "crc.testing"):
        with pytest.raises(ValueError):
            environment.approve(wrong)


def test_messages_name_the_real_blocker_and_the_step(env):
    connect, _ = env
    from academy.main import app

    c = TestClient(app, headers={"X-Academy": "1", "Host": "127.0.0.1"})
    nobody = environment.current()
    assert nobody["connected"] is False and "connect it first" in nobody["reason"] and "step 1" in nobody["reason"]
    r = c.post("/api/connect", json={"identity": "admin", "confirm": "use kubeadmin"})
    assert r.status_code == 409 and "connect the learner account first" in r.json()["detail"]
    connect("learner")
    unapproved = environment.current()
    assert "not approved" in unapproved["reason"] and "step 2" in unapproved["reason"]
    r = c.post("/api/connect", json={"identity": "admin", "confirm": "use kubeadmin"})
    assert r.status_code == 409 and "step 2" in r.json()["detail"]


def test_approval_input_is_strict(env):
    connect, _ = env
    connect("learner")
    for wrong in ("ftp://api.crc.testing", "https://user@api.crc.testing:6443", "https://api.crc.testing:6443/x",
                  "https://api.crc.testing:99999", "https://api.crc.tes\tting:6443", "api.crc.tes ting", "https://api.crc.testing"):
        with pytest.raises(ValueError):
            environment.approve(wrong)
    assert environment.current()["class"] == "read-only"


def test_kubeadmin_is_refused_when_it_would_reach_another_cluster(env, monkeypatch, tmp_path):
    connect, _ = env
    connect("learner")
    environment.approve("api.crc.testing")
    other = tmp_path / "admin-elsewhere.kubeconfig"
    other.write_text(KC % "https://api.prod.example.com:6443", encoding="utf-8")
    monkeypatch.setitem(config.EXTERNAL_KUBECONFIG, "admin", str(other))
    called = []
    monkeypatch.setattr(kube, "login_user", lambda identity: called.append(identity) or {"ok": True})
    from academy.main import app

    c = TestClient(app, headers={"X-Academy": "1", "Host": "127.0.0.1"})
    r = c.post("/api/connect", json={"identity": "admin", "confirm": "use kubeadmin"})
    assert r.status_code == 409 and "another cluster" in r.json()["detail"] and called == []  # nothing was sent


def test_a_certificate_problem_is_not_sent_to_approval(env):
    connect, kd = env
    connect("learner")
    environment.approve("api.crc.testing")
    (kd / "learner.kubeconfig").write_text((kd / "learner.kubeconfig").read_text(encoding="utf-8").replace("certificate-authority: ca.crt", "certificate-authority: ca.crt, insecure-skip-tls-verify: true"), encoding="utf-8")
    from academy.main import app

    c = TestClient(app, headers={"X-Academy": "1", "Host": "127.0.0.1"})
    r = c.post("/api/connect", json={"identity": "admin", "confirm": "use kubeadmin"})
    assert r.status_code == 409 and "certificate" in r.json()["detail"] and "step 1" in r.json()["detail"]


def test_an_imported_learner_kubeconfig_that_does_not_log_in_is_not_kept(env, monkeypatch, tmp_path):
    connect, kd = env
    src = tmp_path / "learner-import.kubeconfig"
    src.write_text(KC % "https://api.crc.testing:6443", encoding="utf-8")
    monkeypatch.setitem(config.EXTERNAL_KUBECONFIG, "learner", str(src))
    monkeypatch.setattr(kube, "whoami", lambda identity: {"connected": False, "reason": "Unauthorized"})
    r = kube.login_user("learner")
    assert r["ok"] is False and not kube.kubeconfig("learner").exists()
    assert environment.current()["connected"] is False  # so no approval is offered


def test_confirmation_round_cases(env, monkeypatch, tmp_path):
    connect, kd = env
    connect("learner")
    for wrong in ("https://api.crc.testing:6443//", "https://api.crc.testing:6443///"):
        with pytest.raises(ValueError):
            environment.approve(wrong)
    assert environment.approve("https://api.crc.testing:6443/")["class"] == "training"
    # an empty admin kubeconfig is "not the approved cluster", not a server error
    empty = tmp_path / "empty.kubeconfig"
    empty.write_text("# nothing\n", encoding="utf-8")
    monkeypatch.setitem(config.EXTERNAL_KUBECONFIG, "admin", str(empty))
    assert environment.admin_target_is_approved_cluster() is False
    # a path differing only in letter case is another API
    connect("learner", "https://api.example.com:6443/clusters/dev")
    other = tmp_path / "admin-case.kubeconfig"
    other.write_text(KC % "https://api.example.com:6443/clusters/DEV", encoding="utf-8")
    (tmp_path / "ca.crt").write_text("CA-ONE", encoding="utf-8")
    monkeypatch.setitem(config.EXTERNAL_KUBECONFIG, "admin", str(other))
    assert environment.admin_target_is_approved_cluster() is False
    # a learner whose kubeconfig trusts no CA is sent back to step 1, approved or not
    connect("learner")
    (kd / "learner.kubeconfig").write_text((kd / "learner.kubeconfig").read_text(encoding="utf-8").replace("certificate-authority: ca.crt", "insecure-skip-tls-verify: true"), encoding="utf-8")
    e = environment.current()
    assert e["needs"] == "tls" and "step 1" in e["reason"]
