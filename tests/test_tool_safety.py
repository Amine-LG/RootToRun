"""Safety of the maintainer's tools, checked without any real client or cluster: the grading oracle never runs a line
whose command or connection it cannot read reliably, and the recorder's wrappers, credential files and scrubbing
hold. (scripts/cluster_read.py has its own tests.)"""
import importlib.util
import os
import stat
import subprocess

import pytest

from academy import config, recorder
from platforms import RECORDER

spec = importlib.util.spec_from_file_location("grading_oracle", config.ROOT / "scripts" / "grading_oracle.py")
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


@pytest.mark.parametrize("cmd", ['oc get pods "$(touch /tmp/x)"', 'oc get pods "`id`"', 'oc get "$HOME"'])
def test_oracle_never_expands_inside_double_quotes(cmd):
    assert oracle.raw_words(cmd) is None and oracle.argv(cmd) is None


@pytest.mark.parametrize("words", [
    ["oc", "get", "pods", "--kubeconfig=/elsewhere"],
    ["oc", "config", "set", "current-context", "x", "--kubeconfig=/elsewhere"],
    ["oc", "--namespace=demo", "image", "info", "quay.io/x/y:z"],
    ["oc", "--cache-dir", "get", "delete", "pods", "--all"],
    ["oc", "get", "pods", "-sattacker.invalid"],
    ["oc", "version", "--client", "--profile=cpu", "--profile-output=/tmp/x"],
    ["oc", "project", "other"],
    ["oc", "get", "pods", "--as=system:admin"],
])
def test_oracle_skips_lines_it_cannot_run_safely(words, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not run")
    monkeypatch.setattr(oracle.subprocess, "run", boom)
    monkeypatch.setattr(oracle, "LEARNER_KUBECONFIG", config.ROOT / "README.md")  # "exists": only the checks decide
    assert oracle.client(words)[0] == "skipped"
    assert oracle.server(words) is None


@pytest.mark.parametrize("words", [["oc", "get", "pods", "-Aw"], ["oc", "get", "pods", "--watch_only=true"], ["oc", "logs", "web", "-f=true"]])
def test_oracle_never_watches(words, monkeypatch):
    monkeypatch.setattr(oracle.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    monkeypatch.setattr(oracle, "LEARNER_KUBECONFIG", config.ROOT / "README.md")
    assert oracle.server(words) is None


def _wrapper(tmp_path):
    fake = tmp_path / "fake-oc"
    fake.write_text("#!/bin/sh\necho ran \"$@\"\n", encoding="utf-8")
    fake.chmod(0o700)
    recorder._wrapper(tmp_path / "bin", str(fake), "/nonexistent/kubeconfig", "admin", "administrator")
    return tmp_path / "bin" / "oc"


@pytest.mark.parametrize("args", [["--cache-dir", "get", "config", "set", "current-context", "x"],
                                  ["get", "pods", "-shttps://elsewhere.invalid"], ["config", "view"],
                                  ["-n", "x", "project", "y"], ["--insecure-skip-tls-verify", "get", "pods"]])
@RECORDER
def test_recorder_wrapper_refuses(args, tmp_path):
    r = subprocess.run([str(_wrapper(tmp_path)), *args], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 97 and "ran" not in r.stdout, (r.stdout, r.stderr)


@RECORDER
def test_recorder_wrapper_runs_ordinary_commands(tmp_path):
    r = subprocess.run([str(_wrapper(tmp_path)), "-n", "team", "get", "pods"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and "--kubeconfig=/nonexistent/kubeconfig --context=admin -n team get pods" in r.stdout


@RECORDER
def test_credential_files_are_owner_only_and_never_follow_links(tmp_path):
    f = tmp_path / "x.kubeconfig"
    recorder._write_owner_only(f, "data")
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    link = tmp_path / "link.kubeconfig"
    os.symlink(tmp_path / "target", link)
    with pytest.raises(FileExistsError):
        recorder._write_owner_only(link, "data")
    assert not (tmp_path / "target").exists()


def test_scrub_removes_base64_forms_of_known_secrets():
    out = recorder.scrub("password: c3ludGhldGljLXBhc3N3b3Jk and synthetic-password", [], {"P": "synthetic-password"})
    assert "c3ludGhldGljLXBhc3N3b3Jk" not in out and "synthetic-password" not in out


@pytest.mark.parametrize("args", [["get", "pods", "-Ashttps://elsewhere.invalid"], ["get", "pods", "--client_certificate=/tmp/c"],
                                  ["get", "pods", "--tls_server_name=elsewhere"], ["--as=alice", "get", "pods"],
                                  ["get", "pods", "--insecure_skip_tls_verify=true"], ["get", "pods", "-s", "https://x"]])
@RECORDER
def test_recorder_wrapper_refuses_other_spellings(args, tmp_path):
    r = subprocess.run([str(_wrapper(tmp_path)), *args], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 97 and "ran" not in r.stdout, (args, r.stdout, r.stderr)


@pytest.mark.parametrize("args", [["apply", "--server-side", "-f", "x.yaml"], ["get", "pods", "--as=alice", "--as-group=team"],
                                  ["debug", "node/crc", "--", "chroot", "/host", "ps", "-eZ"], ["get", "pods", "-ojson"],
                                  ["--namespace=team", "get", "pods"]])
@RECORDER
def test_recorder_wrapper_keeps_what_lessons_use(args, tmp_path):
    r = subprocess.run([str(_wrapper(tmp_path)), *args], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and r.stdout.startswith("ran"), (args, r.stderr)


@RECORDER
def test_an_interrupted_command_is_stopped_before_anything_else(tmp_path, monkeypatch):
    import time

    pidfile = tmp_path / "pid"

    def interrupted(*a, **k):
        for _ in range(100):
            if pidfile.exists() and pidfile.read_text(encoding="utf-8").strip():
                break
            time.sleep(0.05)
        raise KeyboardInterrupt

    monkeypatch.setattr(recorder, "_collect", interrupted)
    with pytest.raises(KeyboardInterrupt):
        recorder._run_ordered(f"echo $$ > {pidfile}; exec sleep 30", tmp_path, {"PATH": "/usr/bin:/bin"}, 60)
    pid = int(pidfile.read_text(encoding="utf-8"))
    time.sleep(0.2)
    assert not os.path.exists(f"/proc/{pid}") or open(f"/proc/{pid}/stat", encoding="utf-8").read().split()[2] == "Z"


@pytest.mark.skipif(not oracle.BWRAP, reason="bubblewrap is not installed")
def test_oracle_sandbox_hides_host_paths_and_network(monkeypatch):
    monkeypatch.setattr(oracle, "OC", "/usr/bin/true")
    probe = ("for d in /run /var /home /root; do [ -e $d/. ] && echo visible:$d; done; "
             "echo x > /usr/probe 2>/dev/null && echo wrote; "
             "(exec 3<>/dev/tcp/1.1.1.1/53) 2>/dev/null && echo network; echo done")
    r = subprocess.run(oracle.jail(["/bin/bash", "-c", probe]), capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.stdout.strip() == "done", r.stdout + r.stderr


@pytest.mark.skipif(not oracle.BWRAP, reason="bubblewrap is not installed")
def test_oracle_keeps_kubectl_as_kubectl(monkeypatch):
    monkeypatch.setattr(oracle, "OC", "/usr/bin/true")
    argv = oracle.sandboxed(["kubectl", "get", "pods"], network=False)
    assert argv[argv.index("--") + 1].endswith("/kubectl")
