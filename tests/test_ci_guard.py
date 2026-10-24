"""ci-guard (.github/workflows/ci-guard.yml): the check a pull request cannot rewrite. It runs from the default branch
for pull requests into it, checks out and runs nothing from the pull request, and posts the commit status ci-guard:
success when the owner opened the pull request, when every changed file is Markdown documentation or a screenshot (an
ordinary file), or when the owner approved this exact commit. Its own shell runs here against an offline gh."""
import json
import os
import re
import subprocess
import sys

import pytest
import yaml

from academy import config
from platforms import WINDOWS

WF = config.ROOT / ".github" / "workflows" / "ci-guard.yml"
GUARD = yaml.safe_load(WF.read_text(encoding="utf-8"))
ON = GUARD.pop(True, GUARD.get("on"))  # YAML 1.1 reads the key `on` as True
JOB = GUARD["jobs"]["guard"]
# the guard's shell runs on ubuntu-latest (bash, python3); the Windows job checks the rest of this file
linux_shell = pytest.mark.skipif(WINDOWS, reason="the guard runs on ubuntu-latest: bash and python3")


def test_runs_from_the_default_branch_for_pull_requests_into_it_and_runs_nothing_of_theirs():
    assert set(ON) == {"pull_request_target"} and ON["pull_request_target"]["branches"] == ["main"]
    assert {"synchronize", "labeled", "unlabeled"} <= set(ON["pull_request_target"]["types"])
    assert GUARD["permissions"] == {}
    assert JOB["permissions"] == {"contents": "read", "pull-requests": "read", "statuses": "write"}
    assert all("uses" not in s for s in JOB["steps"])
    run = JOB["steps"][0]["run"]
    assert "${{" not in run  # values come in through env: only
    shell = run.replace(guard_program(), "")
    assert not re.search(r"checkout|\bgit |\.venv|\bnpm |pytest|\bsource |(python3?|bash|sh) (-\w+ )*[\w./]+\.(py|sh)|\./", shell)
    assert '[ "$BASE_REF" = "$DEFAULT_BRANCH" ]' in run


def guard_program():
    run = JOB["steps"][0]["run"]
    return run.split("verdict=$(python3", 1)[1].split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]


GH_STUB = '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if "POST" in args:
    with open(os.environ["STATUS_LOG"], "a", encoding="utf-8") as f: f.write(json.dumps(args) + "\\n")
elif any("/compare/" in a for a in args):
    assert args[1] == "repos/owner/repo/compare/" + os.environ["BASE"] + "..." + os.environ["HEAD"]
    print(json.dumps([os.environ["FILE"], None]))
elif any("/git/trees/" in a for a in args):
    side = "HEAD" if os.environ["HEAD"] in " ".join(args) else "BASE"
    if side == "HEAD" or os.environ.get("IN_BASE") == "1":
        print(json.dumps([os.environ["FILE"], os.environ.get("MODE", "100644")]))
elif any("/reviews?" in a for a in args):
    for row in json.loads(os.environ["REVIEWS"]): print(json.dumps(row))
else:
    count = Path(os.environ["HEAD_CALLS"])
    n = int(count.read_text(encoding="utf-8")) if count.exists() else 0
    heads = json.loads(os.environ["API_HEADS"])
    print(heads[min(n, len(heads)-1)])
    count.write_text(str(n+1), encoding="utf-8")
'''


@linux_shell
def test_guard_uses_the_latest_owner_review_and_binds_the_diff_to_the_event_head(tmp_path):
    """Execute the trusted shell with an offline gh stub: historical approvals and a stale event cannot grant access."""
    stub = tmp_path / "gh-stub.py"
    stub.write_text(GH_STUB, encoding="utf-8")
    script = tmp_path / "guard.sh"
    script.write_text('gh() { "$GUARD_PYTHON" "$GUARD_STUB" "$@"; }\n' +
                      JOB["steps"][0]["run"], encoding="utf-8")
    head, other = "a" * 40, "b" * 40
    approval = [1, "APPROVED", "owner", head]
    lesson = "content/en/lessons/lx0.yaml"
    cases = [
        ("CONTRIBUTOR", [], [head], "docs/é\n$(id).md", "100644", "success"),
        ("CONTRIBUTOR", [], [head], "content/media/lesson/screen.png", "100644", "success"),
        ("CONTRIBUTOR", [], [head], "docs/link.md", "120000", "failure"),  # a symbolic link is never exempt
        ("CONTRIBUTOR", [], [head], "docs/run.md", "100755", "failure"),  # nor an executable
        ("CONTRIBUTOR", [], [head], lesson, "100644", "failure"),  # lessons carry commands: the owner reviews them
        ("CONTRIBUTOR", [], [head], "content/en/labs/b5-quotas-limits.yaml", "100644", "failure"),
        ("CONTRIBUTOR", [], [head], "content/recordings/lab.x.json", "100644", "failure"),
        ("CONTRIBUTOR", [approval], [head], lesson, "100644", "success"),
        ("OWNER", [], [head], "pytest.py", "100644", "success"),
        ("CONTRIBUTOR", [], [head], "pytest.py", "100644", "failure"),
        ("MEMBER", [], [head], "pytest.py", "100644", "failure"),
        ("COLLABORATOR", [], [head], "pytest.py", "100644", "failure"),
        ("CONTRIBUTOR", [approval], [head], "pytest.py", "100644", "success"),
        ("CONTRIBUTOR", [approval, [2, "COMMENTED", "owner", head]], [head], "pytest.py", "100644", "success"),
        ("CONTRIBUTOR", [[1, "APPROVED", "someone-else", head]], [head], "pytest.py", "100644", "failure"),
        ("CONTRIBUTOR", [[1, "APPROVED", "owner", other]], [head], "pytest.py", "100644", "failure"),
        ("CONTRIBUTOR", [approval, [2, "CHANGES_REQUESTED", "owner", head]], [head], "pytest.py", "100644", "failure"),
        ("CONTRIBUTOR", [approval, [2, "DISMISSED", "owner", head]], [head], "pytest.py", "100644", "failure"),
        ("CONTRIBUTOR", [approval], [other], "pytest.py", "100644", "error"),
        ("CONTRIBUTOR", [approval], [head, other], "pytest.py", "100644", "error"),
    ]
    for n, (association, reviews, heads, path, mode, expected) in enumerate(cases):
        case = tmp_path / str(n)
        case.mkdir()
        env = {**os.environ, "GUARD_PYTHON": sys.executable, "GUARD_STUB": str(stub), "RUNNER_TEMP": str(case),
               "REPO": "owner/repo", "OWNER": "owner", "PR": "1", "BASE": "c" * 40, "HEAD": head,
               "AUTHOR_ASSOCIATION": association, "CHANGED_FILES": "1", "GH_TOKEN": "offline-test",
               "FILE": path, "MODE": mode, "REVIEWS": json.dumps(reviews), "API_HEADS": json.dumps(heads),
               "STATUS_LOG": str(case / "statuses"), "HEAD_CALLS": str(case / "head-calls"),
               "BASE_REF": "main", "DEFAULT_BRANCH": "main"}
        result = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", str(script)], env=env,
                                capture_output=True, text=True, encoding="utf-8")
        statuses = [json.loads(line) for line in (case / "statuses").read_text(encoding="utf-8").splitlines()]
        assert f"state={expected}" in statuses[-1], (n, result.stdout, result.stderr, statuses)
        assert (result.returncode == 0) == (expected == "success"), (n, result.stdout, result.stderr)


def test_the_guard_exempts_only_documentation_and_screenshots(tmp_path):
    def verdict(files, changed=None, modes=None, truncated=False):
        listing, base, head = tmp_path / "files", tmp_path / "base", tmp_path / "head"
        listing.write_text("".join(json.dumps(f) + "\n" for f in files), encoding="utf-8")
        paths = {p for f in files for p in f if p}
        rows = "".join(json.dumps([p, (modes or {}).get(p, "100644")]) + "\n" for p in paths)
        base.write_text(rows, encoding="utf-8")
        head.write_text(("TRUNCATED\n" if truncated else "") + rows, encoding="utf-8")
        env = {**os.environ, "CHANGED_FILES": str(len(files) if changed is None else changed)}
        # -X utf8: the verdict names a file, and Windows' console code page cannot print every name (-I ignores
        # PYTHONIOENCODING); the guard itself runs on ubuntu-latest, in UTF-8
        done = subprocess.run([sys.executable, "-I", "-X", "utf8", "-", str(listing), str(base), str(head)],
                              input=guard_program(), encoding="utf-8", capture_output=True, env=env)
        assert done.returncode == 0, done.stderr
        return done.stdout.strip()
    clean = [["docs/AUTHORING.md", None], ["docs/$(id).md", None], ["docs/é\nfile.md", None], ["README.md", None],
             ["content/media/lesson/screen.png", None]]
    assert verdict(clean) == "clean"
    for path in [".github/workflows/ci.yml", ".github/actions/python-env/uv-requirements.txt", ".github/CODEOWNERS",
                 "scripts/ci_needs_site.py", "scripts/test_content.sh", "tests/test_api.py", "tests/e2e/conftest.py",
                 "pytest.ini", "frontend/src/lib/cmdfmt.test.ts", "requirements-dev.txt", "frontend/package.json",
                 "frontend/package-lock.json", "frontend/scripts/licenses.mjs", "frontend/vite.config.ts",
                 "Containerfile", ".dockerignore", "deploy/nginx/nginx.conf", "frontend/vitest.config.ts",
                 "frontend/.npmrc", ".npmrc", "pytest.py", "pyproject.toml", "frontend/npm-shrinkwrap.json",
                 "frontend/src/App.tsx", "backend/academy/main.py", "unknown", "docs/../pytest.py", "content/unknown.py",
                 "docs/а.MD", "content/media/a/b/c.png", "content/en/lessons/lx0.yaml", "content/en/labs/x.yaml",
                 "content/en/incidents/x.yaml", "content/en/challenges/x.yaml", "content/en/diagnostics/x.yaml",
                 "content/recordings/lab.x.json", "content/en/tools.yaml", "content/media/lesson/x.svg"]:
        assert verdict(clean + [[path, None]]).startswith("review: 1 "), path
    assert verdict([["docs/x.md", "scripts/ci_needs_site.py"]]).startswith("review")  # a rename counts by its old path
    assert verdict(clean, modes={"docs/AUTHORING.md": "120000"}).startswith("review")  # a symbolic link
    assert verdict(clean, modes={"README.md": "160000"}).startswith("review")  # a submodule
    assert verdict(clean, changed=6).startswith("unlisted")  # fewer files listed than the pull request has
    assert verdict([["docs/a.md", None]] * 300).startswith("unlisted")  # immutable compare lists at most 300
    assert verdict(clean, truncated=True).startswith("unlisted")  # a file tree too large to read fails closed


@linux_shell
def test_a_pull_request_into_another_branch_gets_no_verdict(tmp_path):
    stub = tmp_path / "gh-stub.py"
    stub.write_text(GH_STUB, encoding="utf-8")
    script = tmp_path / "guard.sh"
    script.write_text('gh() { "$GUARD_PYTHON" "$GUARD_STUB" "$@"; }\n' + JOB["steps"][0]["run"], encoding="utf-8")
    env = {**os.environ, "GUARD_PYTHON": sys.executable, "GUARD_STUB": str(stub), "RUNNER_TEMP": str(tmp_path),
           "REPO": "owner/repo", "OWNER": "owner", "PR": "1", "BASE": "c" * 40, "HEAD": "a" * 40,
           "AUTHOR_ASSOCIATION": "OWNER", "CHANGED_FILES": "1", "GH_TOKEN": "offline-test", "FILE": "docs/a.md",
           "REVIEWS": "[]", "API_HEADS": json.dumps(["a" * 40]), "STATUS_LOG": str(tmp_path / "statuses"),
           "HEAD_CALLS": str(tmp_path / "head-calls"), "BASE_REF": "release", "DEFAULT_BRANCH": "main"}
    result = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", str(script)], env=env,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode != 0 and not (tmp_path / "statuses").exists()  # not even "opened by the owner"
