"""ci-ok is the one check a ruleset can require: it passes only when every other job of ci.yml passed, and the
browser tests were either run and passed or not needed. Here its own shell runs against each result GitHub can give."""
import itertools
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from platforms import WINDOWS

JOBS = yaml.safe_load((Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml")
                      .read_text(encoding="utf-8"))["jobs"]
NOT_SUCCESS = ["failure", "cancelled", "skipped", ""]  # "" when the job is missing from `needs`
needs_bash = pytest.mark.skipif(WINDOWS or not shutil.which("bash"), reason="the gates run on ubuntu-latest (bash)")


def gate(job, env):
    (step,) = JOBS[job]["steps"]
    return subprocess.run([shutil.which("bash"), "-e", "-c", step["run"]], env=env, capture_output=True).returncode


def test_the_gates_always_report_and_cover_every_job():
    for job in ("ci-ok", "browser-tests"):
        assert JOBS[job]["if"] == "always()", job
    covered = set(JOBS["ci-ok"]["needs"]) | set(JOBS["browser-tests"]["needs"])
    assert covered == set(JOBS) - {"ci-ok"}
    # each job ci-ok waits for is one of the results its step checks
    assert {v.split(".")[1] for v in JOBS["ci-ok"]["steps"][0]["env"].values()} == set(JOBS["ci-ok"]["needs"])


@needs_bash
def test_ci_ok_passes_only_when_every_job_passed():
    names = list(JOBS["ci-ok"]["steps"][0]["env"])
    assert gate("ci-ok", dict.fromkeys(names, "success")) == 0
    for name, result in itertools.product(names, NOT_SUCCESS):
        assert gate("ci-ok", {**dict.fromkeys(names, "success"), name: result}) != 0, (name, result)


@needs_bash
@pytest.mark.parametrize("changes, site, parts, passes", [
    ("success", "true", "success", True),
    ("success", "false", "skipped", True),  # documentation only: the browser tests were not needed
    ("success", "true", "skipped", False),
    ("success", "true", "failure", False),
    ("success", "true", "cancelled", False),
    ("success", "false", "failure", False),
    ("success", "", "skipped", False),
    ("failure", "", "skipped", False),
    ("cancelled", "false", "skipped", False),
    ("skipped", "false", "skipped", False),
])
def test_browser_tests_reject_an_unexpected_skip(changes, site, parts, passes):
    assert (gate("browser-tests", {"CHANGES": changes, "SITE": site, "PARTS": parts}) == 0) is passes
