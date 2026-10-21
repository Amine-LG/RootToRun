"""scripts/check_content.py names the file that does not load, first, and as a GitHub annotation on that file."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_content.py"
sys.path.insert(0, str(ROOT / "scripts"))
import check_content  # noqa: E402


def run(content, **env):
    base = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}  # these tests run in GitHub Actions too
    return subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          timeout=300, env={**base, "ACADEMY_CONTENT_DIR": str(content), **env})


def test_the_content_loads_and_a_problem_points_at_its_file():
    assert check_content.problems() == []
    assert check_content.source("b2-images-storage.yaml: 1 validation error") == "content/en/lessons/b2-images-storage.yaml"
    assert check_content.source("tracks.yaml: x") == "content/en/tracks.yaml"
    assert check_content.source("something else: x") is None
    line = check_content.annotation("a.yaml: 1 error\n  50% wrong", "content/en/lessons/a.yaml")
    assert line == "::error file=content/en/lessons/a.yaml,title=Course content does not load::a.yaml: 1 error%0A  50%25 wrong"


def test_a_changed_command_is_reported_on_its_lesson(tmp_path):
    # the pull request a contributor might open: a show step's command edited by hand, no longer one of the lesson's
    content = tmp_path / "content"
    shutil.copytree(ROOT / "content", content)
    lesson = content / "en" / "lessons" / "b2-images-storage.yaml"
    text = lesson.read_text(encoding="utf-8")
    old = "    run: oc get pods -l app=web -o custom-columns=NAME:.metadata.name,STARTED:.status.startTime\n"
    assert text.count(old) == 1
    lesson.write_text(text.replace(old, "    run: oc get pods -l app=web -o wide\n"), encoding="utf-8", newline="\n")
    r = run(content, GITHUB_ACTIONS="true")
    assert r.returncode == 1
    assert "b2-images-storage.yaml: 1 validation error for Lesson" in r.stdout and "run must be the exact cmd" in r.stdout
    assert "::error title=Course content does not load::b2-images-storage.yaml" in r.stdout  # outside the repository: no file
    assert "fix these first" in r.stdout.splitlines()[-1]
    assert "::error" not in run(content).stdout  # annotations only in GitHub Actions
