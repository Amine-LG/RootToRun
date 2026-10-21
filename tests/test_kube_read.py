"""Reads are tri-state: only an explicit NotFound proves absence (texts below are real `oc` 4.21 messages)."""
from pathlib import Path

from academy import kube

R = kube.Result


def test_only_notfound_proves_absence():
    assert kube.classify(R(["oc"], 0, "{}", "", 0)) == "found"
    assert kube.classify(R(["oc"], 1, "", 'Error from server (NotFound): namespaces "academy-x" not found', 0)) == "not_found"
    forbidden = 'Error from server (Forbidden): projects.project.openshift.io "academy-x" is forbidden: User "developer" cannot get resource "projects"'
    assert kube.classify(R(["oc"], 1, "", forbidden, 0)) == "forbidden"
    assert kube.classify(R(["oc"], 1, "", "error: You must be logged in to the server (Unauthorized)", 0)) == "unauthorized"
    assert kube.classify(R(["oc"], 124, "", "Timed out after 30s", 0, "timeout")) == "error"
    assert kube.classify(R(["oc"], 1, "", "Unable to connect to the server: dial tcp: i/o timeout", 0)) == "error"
    assert kube.classify(R([], 127, "", "", 0, "oc_missing")) == "error"


def test_malformed_json_is_unknown(monkeypatch):
    monkeypatch.setattr(kube, "oc", lambda *a, **k: R(["oc"], 0, "not json", "", 0))
    state, obj, _ = kube.read("learner", ["get", "pv", "x"])
    assert state == "error" and obj is None


def test_imported_kubeconfig_keeps_relative_files_working(tmp_path, monkeypatch):
    """A kubeconfig given with ACADEMY_KUBECONFIG_<ID> may name its CA, certificate and key relative to itself; the
    private copy elsewhere must still point at the same files."""
    from academy import kube

    src = tmp_path / "given" / "config"
    src.parent.mkdir()
    key = (tmp_path / "elsewhere" / "u.key").as_posix()  # absolute on every platform (C:/... on Windows)
    src.write_text("apiVersion: v1\nkind: Config\nclusters:\n- name: c\n  cluster: {server: 'https://example.invalid:6443', certificate-authority: ca.crt}\n"
                   f"users:\n- name: u\n  user: {{client-certificate: certs/u.crt, client-key: '{key}'}}\n", encoding="utf-8")
    out = kube._absolute_paths(src)
    assert str(src.parent / "ca.crt") in out and str(src.parent / "certs" / "u.crt") in out and str(Path(key)) in out
    src.write_text("apiVersion: v1\nkind: Config\nusers:\n- name: u\n  user:\n    client-key: ~/k.key\n"
                   "    exec: {apiVersion: client.authentication.k8s.io/v1, command: ./bin/login}\n- name: v\n  user:\n"
                   "    exec: {apiVersion: client.authentication.k8s.io/v1, command: kubelogin}\n", encoding="utf-8")
    out = kube._absolute_paths(src)
    assert "~/" not in out and str(src.parent / "bin" / "login") in out and "command: kubelogin" in out
    plain = tmp_path / "plain"
    plain.write_text("apiVersion: v1\nkind: Config\nclusters: []\n# a comment kept as written\n", encoding="utf-8")
    assert kube._absolute_paths(plain) == plain.read_text(encoding="utf-8")
