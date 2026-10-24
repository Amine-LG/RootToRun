"""scripts/ci_browser.sh installs a browser for the Linux CI jobs and its system libraries (apt, slow) only when the
browser does not start without them. Here a stand-in for .venv/bin/python records what the script asks of it."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from platforms import WINDOWS

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ci_browser.sh"
WORKFLOWS = ROOT / ".github" / "workflows"

STAND_IN = """#!/usr/bin/env bash
echo "$*" >> calls.log
if [ "$1" = - ]; then cat > /dev/null; exit "${LAUNCH_EXIT:-0}"; fi
"""


def ci_browser(tmp_path, launch_exit):
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text(STAND_IN, encoding="utf-8")
    (venv / "python").chmod(0o755)
    env = {**os.environ, "LAUNCH_EXIT": str(launch_exit)}
    done = subprocess.run(["bash", str(SCRIPT), "firefox"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return (tmp_path / "calls.log").read_text(encoding="utf-8").splitlines(), done.stdout


@pytest.mark.skipif(WINDOWS or not shutil.which("bash"), reason="a Linux CI script (bash)")
def test_a_browser_that_starts_needs_no_apt(tmp_path):
    calls, out = ci_browser(tmp_path, launch_exit=0)
    assert calls == ["-m playwright install firefox", "- firefox"]
    assert "nothing installed with apt" in out


@pytest.mark.skipif(WINDOWS or not shutil.which("bash"), reason="a Linux CI script (bash)")
def test_a_browser_that_does_not_start_gets_its_libraries(tmp_path):
    calls, out = ci_browser(tmp_path, launch_exit=1)
    assert calls == ["-m playwright install firefox", "- firefox", "-m playwright install-deps firefox"]
    assert "installing its libraries with apt" in out


def test_every_linux_browser_install_in_ci_goes_through_the_script():
    for workflow in ("ci.yml", "candidate.yml"):
        jobs = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))["jobs"]
        runs = [s.get("run", "") for job in jobs.values() if "windows" not in str(job.get("runs-on"))
                for s in job["steps"]]
        assert not [r for r in runs if "playwright install" in r], workflow
        assert [r for r in runs if r.startswith("scripts/ci_browser.sh ")], workflow
