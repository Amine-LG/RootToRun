"""The recorder's rollback and cleanup when a run is interrupted or a deletion is refused.
Everything that would reach a cluster or a process is stubbed: these tests never run oc, bash or podman.
"""
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from academy import config, kube, ledger, recorder
from platforms import RECORDER

pytestmark = RECORDER


def _lesson():
    exp = SimpleNamespace(id="X-TEST-01", objective="test", changes=[], preflight=[], snapshot=[], settle=[], verify=[],
                          login_checks=[], rollback=["undo-the-change"])
    cmd = SimpleNamespace(cmd="make-the-change", cwd=None, as_="admin", expect="ok", timeout=10)
    return SimpleNamespace(id="t.rollback", record_on="cluster-admin", files={}, commands=[cmd], experiment=exp,
                           test_users=[], secret_vars=[], fingerprint=lambda: "fingerprint")


def _result(code=0, stderr="", status="ok"):
    return kube.Result(argv=["oc"], code=code, stdout="", stderr=stderr, seconds=0.0, status=status)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("recorder tests must not execute a process")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(shutil, "which", lambda *a, **k: None)  # no tool versions are read
    monkeypatch.setenv("ACADEMY_PRIVATE_DIR", str(tmp_path / "private"))
    monkeypatch.setattr(config, "RECORDINGS_DIR", tmp_path / "recordings")
    monkeypatch.setattr(recorder, "_private_values", lambda: [])
    session = {"info": {"namespace": "rec-ns", "_project_uid": "uid-1", "admin": "kubeadmin"},
               "ids": {"admin": {}, "recovery": {}, "developer": {}}, "secrets": {}}
    monkeypatch.setattr(recorder, "_admin_session", lambda lesson, work, env: (session, ""))
    monkeypatch.setattr(recorder, "_private_record", lambda lesson, data: tmp_path / "private-record.json")
    calls = SimpleNamespace(sh=[], deleted=[])
    monkeypatch.setattr(recorder, "_sh", lambda cmd, cwd, env, timeout=300: calls.sh.append(cmd) or
                        {"cmd": cmd, "code": 0, "stdout": "", "stderr": "", "combined": ""})
    clock = [0.0]
    monkeypatch.setattr(recorder, "time", SimpleNamespace(time=lambda: 0.0, monotonic=lambda: clock[0],
                                                          sleep=lambda s: clock.__setitem__(0, clock[0] + s)))
    return calls


def test_an_interrupted_first_command_is_still_rolled_back(fake, monkeypatch):
    def interrupted(*args):
        raise KeyboardInterrupt
    monkeypatch.setattr(recorder, "_run_ordered", interrupted)
    monkeypatch.setattr(ledger, "_delete_with_uid", lambda *a: fake.deleted.append(a) or "found")
    monkeypatch.setattr(kube, "oc", lambda *a, **k: _result(1, "Error from server (NotFound): projects.project.openshift.io \"rec-ns\" not found"))
    with pytest.raises(KeyboardInterrupt):
        recorder.record_lesson(_lesson(), log=lambda *a: None)
    assert "undo-the-change" in fake.sh
    assert fake.deleted and fake.deleted[0][2] == "uid-1"


@pytest.mark.parametrize("deleted, read, problem", [
    ("forbidden", _result(0), "could not be deleted (forbidden)"),
    ("found", _result(1, "Unable to connect to the server: i/o timeout"), "could not be confirmed (error)"),
    ("found", _result(0, status="timeout"), "could not be confirmed (error)"),
    ("found", _result(0), "still exists after its deletion"),
])
def test_a_temporary_project_counts_as_removed_only_on_notfound(fake, monkeypatch, deleted, read, problem):
    monkeypatch.setattr(recorder, "_run_ordered", lambda *a: (0, "", "", ""))
    monkeypatch.setattr(ledger, "_delete_with_uid", lambda *a: deleted)
    monkeypatch.setattr(kube, "oc", lambda *a, **k: read)
    out = recorder.record_lesson(_lesson(), log=lambda *a: None)
    assert not out["ok"]
    assert any(problem in p for p in out["problems"]), out["problems"]


def test_a_project_the_rollback_already_deleted_counts_as_removed_on_the_recovery_notfound(fake, monkeypatch):
    # the developer is refused (Forbidden) a project that no longer exists; the recovery administrator's NotFound proves it
    monkeypatch.setattr(recorder, "_run_ordered", lambda *a: (0, "", "", ""))
    monkeypatch.setattr(ledger, "_delete_with_uid", lambda *a: "forbidden")
    monkeypatch.setattr(kube, "oc", lambda *a, **k: _result(1, "Error from server (Forbidden): projects.project.openshift.io \"rec-ns\" is forbidden"))
    monkeypatch.setattr(recorder, "_sh", lambda cmd, cwd, env, timeout=300: fake.sh.append(cmd) or (
        {"cmd": cmd, "code": 1, "stdout": "", "stderr": 'Error from server (NotFound): namespaces "rec-ns" not found', "combined": ""}
        if cmd.startswith("oc get namespace") else {"cmd": cmd, "code": 0, "stdout": "", "stderr": "", "combined": ""}))
    out = recorder.record_lesson(_lesson(), log=lambda *a: None)
    assert out["ok"], out["problems"]
    assert "oc get namespace rec-ns" in fake.sh


def test_a_confirmed_removal_is_not_a_problem(fake, monkeypatch):
    monkeypatch.setattr(recorder, "_run_ordered", lambda *a: (0, "", "", ""))
    monkeypatch.setattr(ledger, "_delete_with_uid", lambda *a: "found")
    monkeypatch.setattr(kube, "oc", lambda *a, **k: _result(1, "Error from server (NotFound): projects.project.openshift.io \"rec-ns\" not found"))
    out = recorder.record_lesson(_lesson(), log=lambda *a: None)
    assert out["ok"], out["problems"]


def test_an_interrupted_rollback_still_runs_the_other_steps_and_the_cleanup(fake, monkeypatch):
    lesson = _lesson()
    lesson.experiment.rollback = ["undo-one", "undo-two"]
    lesson.experiment.verify = [SimpleNamespace(cmd="check-it", expect="ok", timeout=10)]
    monkeypatch.setattr(recorder, "_run_ordered", lambda *a: (0, "", "", ""))

    def sh(cmd, cwd, env, timeout=300):
        fake.sh.append(cmd)
        if cmd == "undo-one":
            raise KeyboardInterrupt
        if cmd == "check-it":
            raise RuntimeError("the verification broke")
        return {"cmd": cmd, "code": 0, "stdout": "", "stderr": "", "combined": ""}
    monkeypatch.setattr(recorder, "_sh", sh)
    monkeypatch.setattr(ledger, "_delete_with_uid", lambda *a: fake.deleted.append(a) or "found")
    monkeypatch.setattr(kube, "oc", lambda *a, **k: _result(1, "Error from server (NotFound): projects.project.openshift.io \"rec-ns\" not found"))
    with pytest.raises(KeyboardInterrupt):
        recorder.record_lesson(lesson, log=lambda *a: None)
    assert fake.sh.index("undo-two") > fake.sh.index("undo-one")  # the second step ran after the interrupted one
    assert fake.deleted and fake.deleted[0][2] == "uid-1"         # and the temporary project was still removed


def test_session_files_are_removed_even_when_reporting_and_project_removal_fail(fake, monkeypatch, tmp_path):
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(recorder, "_run_ordered", lambda *a: (0, "", "", ""))
    monkeypatch.setattr(recorder, "_private_record", lambda *a: (_ for _ in ()).throw(OSError("disk full")))

    def broken(*a):
        raise RuntimeError("API unreachable")
    monkeypatch.setattr(ledger, "_delete_with_uid", broken)
    out = recorder.record_lesson(_lesson(), log=lambda *a: None)
    assert not out["ok"] and any("cleanup: RuntimeError" in p for p in out["problems"]), out["problems"]
    assert list((tmp_path / "tmp").iterdir()) == []  # the private session directory (credentials) is gone


def test_session_files_are_removed_even_if_teardown_itself_is_interrupted(fake, monkeypatch, tmp_path):
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(recorder, "_run_ordered", lambda *a: (0, "", "", ""))

    def log(message):
        if "rollback" in message:
            raise KeyboardInterrupt  # interrupted while the rollback is being reported
    monkeypatch.setattr(ledger, "_delete_with_uid", lambda *a: fake.deleted.append(a) or "found")
    monkeypatch.setattr(kube, "oc", lambda *a, **k: _result(1, "Error from server (NotFound): projects.project.openshift.io \"rec-ns\" not found"))
    with pytest.raises(KeyboardInterrupt):
        recorder.record_lesson(_lesson(), log=log)
    assert list((tmp_path / "tmp").iterdir()) == []
    assert fake.deleted  # the temporary project was still removed


def test_a_real_ctrl_c_during_rollback_is_held_until_cleanup_is_done(fake, monkeypatch):
    import os
    import signal

    lesson = _lesson()
    lesson.experiment.rollback = ["undo-one", "undo-two"]
    monkeypatch.setattr(recorder, "_run_ordered", lambda *a: (0, "", "", ""))

    def sh(cmd, cwd, env, timeout=300):
        fake.sh.append(cmd)
        if cmd == "undo-one":
            os.kill(os.getpid(), signal.SIGINT)  # the operator presses Ctrl-C during the rollback
        return {"cmd": cmd, "code": 0, "stdout": "", "stderr": "", "combined": ""}
    monkeypatch.setattr(recorder, "_sh", sh)
    monkeypatch.setattr(ledger, "_delete_with_uid", lambda *a: fake.deleted.append(a) or "found")
    monkeypatch.setattr(kube, "oc", lambda *a, **k: _result(1, "Error from server (NotFound): projects.project.openshift.io \"rec-ns\" not found"))
    with pytest.raises(KeyboardInterrupt):
        recorder.record_lesson(lesson, log=lambda *a: None)
    assert "undo-two" in fake.sh and fake.deleted  # the rest of the rollback and the project removal still ran
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler  # and Ctrl-C works normally again


def test_ctrl_c_while_the_session_directory_is_removed_is_reported_after_removal(fake, monkeypatch, tmp_path):
    import os
    import signal
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(recorder, "_run_ordered", lambda *a: (0, "", "", ""))
    monkeypatch.setattr(ledger, "_delete_with_uid", lambda *a: "found")
    monkeypatch.setattr(kube, "oc", lambda *a, **k: _result(1, "Error from server (NotFound): projects.project.openshift.io \"rec-ns\" not found"))
    real_rmtree = shutil.rmtree

    def rmtree(path, *a, **k):
        if str(path).startswith(str(tmp_path / "tmp")) and "academy-lesson-" in os.path.basename(str(path)):
            os.kill(os.getpid(), signal.SIGINT)
        return real_rmtree(path, *a, **k)
    monkeypatch.setattr(shutil, "rmtree", rmtree)
    with pytest.raises(KeyboardInterrupt):
        recorder.record_lesson(_lesson(), log=lambda *a: None)
    assert list((tmp_path / "tmp").iterdir()) == []
