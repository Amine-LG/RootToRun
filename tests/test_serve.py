"""scripts/serve.py, the cross-platform way to run the site locally (the commands docs/WINDOWS.md gives): it serves
the app in practice mode on 127.0.0.1 and stops cleanly, on Linux and on the Windows CI runner."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVE = ROOT / "scripts" / "serve.py"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read()


@pytest.fixture
def server():
    port = free_port()
    env = {**os.environ, "KUBECONFIG": os.devnull}
    env.pop("ACADEMY_CLUSTER", None)
    proc = subprocess.Popen([sys.executable, str(SERVE), "--practice", "--no-build", "--port", str(port)], cwd=ROOT,
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    for _ in range(360):  # 90 s: a busy machine or runner starts the app slowly
        try:
            get(url + "/healthz")
            break
        except OSError:
            if proc.poll() is not None:
                pytest.fail("serve.py exited: " + proc.stdout.read().decode(errors="replace"))
            time.sleep(0.25)
    yield proc, url, port
    proc.terminate()
    proc.wait(15)


def test_serves_the_app_in_practice_mode_and_stops(server):
    proc, url, port = server
    status, body = get(url + "/api/status")
    assert status == 200
    assert json.loads(body)["mode"] == "practice"  # --practice: no cluster access at all
    proc.terminate()
    assert proc.wait(15) is not None
    out = proc.stdout.read().decode(errors="replace")
    assert f"http://127.0.0.1:{port}" in out and "practice mode" in out
    with pytest.raises(OSError):  # nothing is left listening: the server ran in this one process
        get(url + "/healthz")


def test_refuses_a_busy_port_with_a_clear_message():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        r = subprocess.run([sys.executable, str(SERVE), "--practice", "--no-build", "--port", str(port)], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode != 0 and f"port {port} is busy" in r.stderr


def test_says_how_to_run_it_without_the_project_environment(tmp_path):
    # a Python without uvicorn (the isolated mode ignores the project's environment variables, not its packages:
    # run the check with no site packages at all)
    r = subprocess.run([sys.executable, "-I", "-S", str(SERVE), "--no-build"], cwd=tmp_path, capture_output=True,
                       text=True, encoding="utf-8", timeout=60)
    assert r.returncode != 0 and "project's environment" in r.stderr


def test_a_changed_lock_file_or_configuration_rebuilds(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("serve_script", SERVE)
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)
    built, lock, config = tmp_path / "dist" / "index.html", tmp_path / "package-lock.json", tmp_path / "vite.config.ts"
    built.parent.mkdir()
    for f in (lock, config, built):  # in this order: the build is the newest
        f.write_text("x", encoding="utf-8")
        os.utime(f, (1_000 + len(str(f)), 1_000 + len(str(f))))
    os.utime(built, (5_000, 5_000))
    monkeypatch.setattr(serve, "BUILT", built)
    monkeypatch.setattr(serve, "SOURCES", [lock, config])
    assert not serve.stale()
    os.utime(lock, (6_000, 6_000))  # new dependencies: rebuild (and build() reinstalls them first)
    assert serve.stale()
