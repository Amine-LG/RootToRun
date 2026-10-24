"""The CI's structure and security properties (docs/CI.md), checked on the workflow files themselves: one router and
one required gate for pull requests, two lanes that share their Python, site and Windows jobs, official actions pinned
by commit only, one pinned uv, no expression in a shell script, read-only tokens, a guard that never runs pull-request
code, the gate's decision table for every combination of results, and the alert for a failing main."""
import json
import os
import re
import subprocess
import sys

import yaml

from academy import config

WF = config.ROOT / ".github" / "workflows"
ACTIONS = config.ROOT / ".github" / "actions"


def load(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # YAML 1.1 reads the key `on` as True
    return data


WORKFLOWS = {p.name: load(p) for p in sorted(WF.glob("*.yml"))}
COMPOSITES = {p.parent.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(ACTIONS.glob("*/action.yml"))}
SHARED = ("python", "site", "windows", "same-site")  # the jobs both lanes run, identically


def all_steps():
    for name, wf in WORKFLOWS.items():
        for job_id, job in wf["jobs"].items():
            for step in job.get("steps", []):
                yield f"{name}:{job_id}", job, step
    for name, action in COMPOSITES.items():
        for step in action["runs"]["steps"]:
            yield f"actions/{name}", {}, step


def test_only_official_actions_pinned_to_a_commit_or_files_of_this_repository():
    seen = set()
    for where, _, step in all_steps():
        uses = step.get("uses")
        if uses:
            seen.add(uses.split("@")[0])
            assert (re.fullmatch(r"actions/[a-z-]+(/[a-z-]+)?@[0-9a-f]{40}", uses)
                    or re.fullmatch(r"\./\.github/actions/[a-z-]+", uses)), f"{where}: {uses}"
    for name, wf in WORKFLOWS.items():
        for job_id, job in wf["jobs"].items():
            if "uses" in job:
                assert re.fullmatch(r"\./\.github/workflows/[a-z-]+\.yml", job["uses"]), f"{name}:{job_id}"
    assert "actions/checkout" in seen and not any(s.startswith("astral-sh/") for s in seen)


def test_uv_comes_from_one_place_pinned_by_version_and_hash():
    reqs = (ACTIONS / "python-env" / "uv-requirements.txt").read_text(encoding="utf-8")
    assert len(re.findall(r"^uv==\d+\.\d+\.\d+ \\$", reqs, re.M)) == 1
    assert len(re.findall(r"--hash=sha256:[0-9a-f]{64}", reqs)) >= 2  # Linux and Windows wheels
    install = [s["run"] for s in COMPOSITES["python-env"]["runs"]["steps"] if s.get("run", "").startswith("python -m pip")]
    assert install == ['python -m pip install --disable-pip-version-check --no-deps --require-hashes -r "$REQS"']
    for where, job, step in all_steps():
        run = step.get("run", "")
        assert not re.search(r"pip install[^\n]*\buv\b", run), where  # uv is installed only from the hashed file
        if re.search(r"(^|\s)uv (venv|pip)", run) and not where.startswith("actions/"):
            assert any(s.get("uses") == "./.github/actions/python-env" for s in job["steps"]), where


def test_no_expression_is_pasted_into_a_shell_script():
    """Values reach scripts through env: only, so no file name, title or branch name can become shell code."""
    for where, _, step in all_steps():
        assert "${{" not in step.get("run", ""), where


def test_read_only_tokens_timeouts_and_no_persisted_credentials():
    for name, wf in WORKFLOWS.items():
        assert wf["permissions"] in ({"contents": "read"}, {}), name
        for job_id, job in wf["jobs"].items():
            if "uses" not in job:  # the release candidate keeps its own longer limits (a fresh, uncached build)
                assert 0 < job["timeout-minutes"] <= (30 if name == "candidate.yml" else 15), f"{name}:{job_id}"
            writes = {k for k, v in (job.get("permissions") or {}).items() if v == "write"}
            allowed = {("candidate.yml", "publish"): {"packages"}, ("ci-guard.yml", "guard"): {"statuses"},
                       ("main-alert.yml", "alert"): {"issues"}}
            assert writes <= allowed.get((name, job_id), set()), f"{name}:{job_id}: {writes}"
    for where, _, step in all_steps():
        if step.get("uses", "").startswith("actions/checkout@"):
            assert step["with"]["persist-credentials"] is False, where


def test_triggers_pull_request_code_never_runs_with_more_than_a_read_token():
    triggers = {name: set(wf["on"]) for name, wf in WORKFLOWS.items()}
    assert triggers == {
        "ci.yml": {"pull_request"},
        "checks-content.yml": {"workflow_call"},
        "checks-app.yml": {"workflow_call"},
        "checks-main.yml": {"push", "workflow_dispatch", "schedule"},
        "candidate.yml": {"workflow_run"},
        "ci-guard.yml": {"pull_request_target"},
        "main-alert.yml": {"workflow_run"},
    }
    assert WORKFLOWS["checks-main.yml"]["on"]["push"] == {"branches": ["main"]}
    # candidate starts only from a successful ci-main run of a push to main in this repository
    assert WORKFLOWS["candidate.yml"]["on"]["workflow_run"]["workflows"] == [WORKFLOWS["checks-main.yml"]["name"]]
    assert "workflow_run.event == 'push'" in WORKFLOWS["candidate.yml"]["jobs"]["build"]["if"]
    assert "workflow_run.conclusion == 'success'" in WORKFLOWS["candidate.yml"]["jobs"]["build"]["if"]
    # the guard and the alert run from the default branch: they never check out, call an action or run a repository file
    for name, job_id in (("ci-guard.yml", "guard"), ("main-alert.yml", "alert")):
        job = WORKFLOWS[name]["jobs"][job_id]
        assert all("uses" not in s for s in job["steps"]), name
        run = job["steps"][0]["run"]
        if name == "ci-guard.yml":
            run = run.replace(guard_program(), "")  # the shell around the inline classifier
        assert not re.search(r"checkout|\bgit |\.venv|\bnpm |pytest|\bsource |(python3?|bash|sh) (-\w+ )*[\w./]+\.(py|sh)|\./", run), name
    assert set(WORKFLOWS["ci-guard.yml"]["on"]["pull_request_target"]["types"]) >= {"synchronize", "labeled", "unlabeled"}
    alert = WORKFLOWS["main-alert.yml"]["on"]["workflow_run"]
    assert alert == {"workflows": ["ci-main"], "types": ["completed"], "branches": ["main"]}


def test_concurrency_cancels_superseded_pull_request_runs_only():
    assert WORKFLOWS["ci.yml"]["concurrency"] == {"group": "ci-${{ github.event.pull_request.number }}",
                                                  "cancel-in-progress": True}
    assert "concurrency" not in WORKFLOWS["checks-main.yml"]  # every merged commit gets its own complete run
    for name in ("checks-content.yml", "checks-app.yml"):
        assert "concurrency" not in WORKFLOWS[name]  # the caller decides


def test_both_lanes_share_the_python_site_and_windows_jobs():
    """A content change gets the same Python suite, content checks, site build and Windows checks as code."""
    content, app = WORKFLOWS["checks-content.yml"]["jobs"], WORKFLOWS["checks-app.yml"]["jobs"]
    for job in SHARED:
        assert content[job] == app[job], job
    assert set(content) == {*SHARED, "pages"}
    assert set(app) == {*SHARED, "image", "browser", "windows-browser", "deps"}
    python = [s.get("run") for s in app["python"]["steps"] if s.get("run")]
    assert python == ["scripts/test_content.sh --data-checks", "scripts/test_content.sh --python"]
    script = (config.ROOT / "scripts" / "test_content.sh").read_text(encoding="utf-8")
    assert "-m content" not in script and "tests --ignore=tests/e2e -n" in script  # the whole suite, no marker
    windows = " ".join(s.get("run", "") for s in app["windows"]["steps"])
    assert "pytest -q tests --ignore=tests/e2e" in windows and "export_static.py" in windows and "serve.py" in windows


def test_the_content_lane_opens_every_page_in_a_browser():
    pages = WORKFLOWS["checks-content.yml"]["jobs"]["pages"]
    assert pages["needs"] == "site"
    run = " ".join(s.get("run", "") for s in pages["steps"])
    assert "tests/e2e/test_mobile_overflow.py" in run and "scripts/ci_browser.sh chromium" in run
    test = (config.ROOT / "tests" / "e2e" / "test_mobile_overflow.py").read_text(encoding="utf-8")
    assert "page-error" in test and "page.errors == []" in test  # a page that cannot render fails


def test_browser_coverage_before_and_after_a_merge():
    app, main = WORKFLOWS["checks-app.yml"]["jobs"], WORKFLOWS["checks-main.yml"]["jobs"]
    matrix = app["browser"]["strategy"]["matrix"]
    assert matrix == {"browser": ["chromium", "firefox"], "shard": [1, 2, 3]}  # the whole suite, both engines
    # Windows Firefox: part 1 of 5 before a merge (the deep lane), parts 2 to 5 after it, every test after a merge
    before = [s["run"] for s in app["windows-browser"]["steps"] if "--shard" in s.get("run", "")]
    assert len(before) == 1 and "--shard 1/5" in before[0]
    assert main["checks-app"] == {"uses": "./.github/workflows/checks-app.yml"}
    assert main["windows-browser-rest"]["strategy"]["matrix"] == {"shard": [2, 3, 4, 5]}
    assert any("--shard $env:SHARD" in s.get("run", "") for s in main["windows-browser-rest"]["steps"])


def test_the_release_candidate_tests_the_published_image_with_the_whole_suite():
    test = WORKFLOWS["candidate.yml"]["jobs"]["test"]
    assert test["strategy"]["matrix"] == {"shard": [1, 2, 3]}
    run = " ".join(s.get("run", "") for s in test["steps"])
    assert "tests/e2e" in run and "--shard" in run
    assert WORKFLOWS["candidate.yml"]["jobs"]["publish"]["needs"] == ["build", "test"]


def guard_program():
    run = WORKFLOWS["ci-guard.yml"]["jobs"]["guard"]["steps"][0]["run"]
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


def test_guard_uses_the_latest_owner_review_and_binds_the_diff_to_the_event_head(tmp_path):
    """Execute the trusted shell with an offline gh stub: historical approvals and a stale event cannot grant access."""
    stub = tmp_path / "gh-stub.py"
    stub.write_text(GH_STUB, encoding="utf-8")
    script = tmp_path / "guard.sh"
    script.write_text('gh() { "$GUARD_PYTHON" "$GUARD_STUB" "$@"; }\n' +
                      WORKFLOWS["ci-guard.yml"]["jobs"]["guard"]["steps"][0]["run"], encoding="utf-8")
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
               "STATUS_LOG": str(case / "statuses"), "HEAD_CALLS": str(case / "head-calls")}
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
        return subprocess.run([sys.executable, "-I", "-", str(listing), str(base), str(head)], input=guard_program(),
                              encoding="utf-8", capture_output=True, check=True, env=env).stdout.strip()
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

    # what is exempt from review also takes the content lane (never the reverse: the lane is about tests, not trust)
    namespace = {}
    exec(guard_program().split("def tree(", 1)[0], namespace)
    from scripts.ci_needs_site import content_path
    for path in [f.relative_to(config.ROOT).as_posix() for f in config.ROOT.rglob("*")
                 if f.is_file() and not any(p in {".git", ".venv", "node_modules", "dist", "__pycache__"} for p in f.parts)]:
        assert not namespace["exempt_path"](path) or content_path(path), path


def alert_run(tmp_path, conclusion, sha, head, open_issue):
    stub = tmp_path / "gh.py"
    stub.write_text('''import json, os, sys
args = sys.argv[1:]
with open(os.environ["LOG"], "a", encoding="utf-8") as f: f.write(json.dumps(args) + "\\n")
if args[:2] == ["issue", "list"]:
    print(os.environ["OPEN"])
elif args[:1] == ["api"]:
    print(os.environ["MAIN"])
''', encoding="utf-8")
    log = tmp_path / f"log-{conclusion}-{sha[:1]}-{open_issue or 'none'}"
    script = 'gh() { "$PY" "$STUB" "$@"; }\n' + WORKFLOWS["main-alert.yml"]["jobs"]["alert"]["steps"][0]["run"]
    env = {**os.environ, "PY": sys.executable, "STUB": str(stub), "LOG": str(log), "OPEN": open_issue, "MAIN": head,
           "REPO": "owner/repo", "OWNER": "owner", "CONCLUSION": conclusion, "SHA": sha, "EVENT": "push",
           "RUN_URL": "https://github.com/owner/repo/actions/runs/1", "GH_TOKEN": "offline-test"}
    result = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script], env=env,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return [c[:2] for c in calls if c[0] == "issue" and c[1] != "list"], calls


def test_a_failing_main_opens_one_issue_and_only_the_current_commit_closes_it(tmp_path):
    a, b = "a" * 40, "b" * 40
    actions, calls = alert_run(tmp_path, "failure", a, a, "")
    assert actions == [["issue", "create"]] and "--assignee" in calls[-1] and "owner" in calls[-1]
    for conclusion in ("failure", "cancelled", "timed_out", "startup_failure"):
        assert alert_run(tmp_path, conclusion, a, a, "7")[0] == [["issue", "comment"]], conclusion
    assert alert_run(tmp_path, "success", a, a, "7")[0] == [["issue", "close"]]
    assert alert_run(tmp_path, "success", b, a, "7")[0] == []  # an older commit passing does not close it
    assert alert_run(tmp_path, "success", a, a, "")[0] == []
    assert alert_run(tmp_path, "skipped", a, a, "7")[0] == []
