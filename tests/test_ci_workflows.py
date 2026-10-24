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
from test_ci_guard import guard_program

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


def alert_run(tmp_path, main, latest, open_issue, event_url, runs=None):
    """The alert's shell with an offline gh and the real jq: `main` is the commit main points to, `latest` its one run
    ("conclusion url", or "" for none) unless `runs` gives the API's pages, `open_issue` the open issue or ""."""
    stub = tmp_path / "gh.py"
    stub.write_text('''import json, os, sys
args = sys.argv[1:]
with open(os.environ["LOG"], "a", encoding="utf-8") as f: f.write(json.dumps(args) + "\\n")
if args[:2] == ["issue", "list"]:
    print(os.environ["OPEN"])
elif args[:1] == ["api"] and "/commits/main" in args[1]:
    print(os.environ["MAIN"])
elif args[:1] == ["api"] and any("/runs?" in a for a in args):
    endpoint = next(a for a in args if "/runs?" in a)
    assert "head_sha=" + os.environ["MAIN"] in endpoint and "status=completed" not in endpoint
    assert "--paginate" in args and "--slurp" in args
    if os.environ.get("RUNS"):
        print(os.environ["RUNS"])
    else:
        value = os.environ["LATEST"].split(" ", 1)
        rows = [] if not value[0] else [{"id": 1, "run_attempt": 1, "status": "completed",
                "run_started_at": "2026-10-24T10:00:00Z", "conclusion": value[0], "html_url": value[1]}]
        print(json.dumps([{"workflow_runs": rows}]))
''', encoding="utf-8")
    log = tmp_path / f"log-{len(list(tmp_path.glob('log-*')))}"
    script = 'gh() { "$PY" "$STUB" "$@"; }\n' + WORKFLOWS["main-alert.yml"]["jobs"]["alert"]["steps"][0]["run"]
    env = {**os.environ, "PY": sys.executable, "STUB": str(stub), "LOG": str(log), "OPEN": open_issue, "MAIN": main,
           "LATEST": latest, "REPO": "owner/repo", "OWNER": "owner", "EVENT_RUN_URL": event_url, "GH_TOKEN": "offline",
           "RUNS": json.dumps(runs) if runs is not None else ""}
    result = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script], env=env,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return [c[:2] for c in calls if c[0] == "issue" and c[1] != "list"], calls


def test_the_alert_follows_mains_current_state_not_the_event(tmp_path):
    a = "a" * 40
    run1, run2 = "https://github.com/owner/repo/actions/runs/1", "https://github.com/owner/repo/actions/runs/2"
    actions, calls = alert_run(tmp_path, a, f"failure {run1}", "", run1)
    assert actions == [["issue", "create"]] and "--assignee" in calls[-1] and "owner" in calls[-1]
    for conclusion in ("failure", "cancelled", "timed_out", "startup_failure"):
        assert alert_run(tmp_path, a, f"{conclusion} {run1}", "7", run1)[0] == [["issue", "comment"]], conclusion
    assert alert_run(tmp_path, a, f"failure {run2}", "7", run1)[0] == []  # an older run's event: no repeat comment
    assert alert_run(tmp_path, a, f"success {run2}", "7", run2)[0] == [["issue", "close"]]
    # the review's sequences: a newer failure at the same commit stays open when an older success arrives late,
    # and a late failure of an older commit opens nothing while main's own latest run passed
    assert alert_run(tmp_path, a, f"failure {run2}", "7", run1)[0] == []
    assert alert_run(tmp_path, a, f"success {run2}", "", run1)[0] == []
    assert alert_run(tmp_path, a, "", "7", run1)[0] == []  # no completed run for main's commit yet
    assert alert_run(tmp_path, a, f"skipped {run1}", "7", run1)[0] == []


def test_the_alert_waits_for_a_pending_retry_and_reads_every_page(tmp_path):
    url1, url2 = "https://github.com/owner/repo/actions/runs/1", "https://github.com/owner/repo/actions/runs/2"
    older = {"id": 1, "run_attempt": 1, "status": "completed", "conclusion": "success",
             "run_started_at": "2026-10-24T10:00:00Z", "html_url": url1}
    # a failed run being re-run: an older success must not close the issue, also when the queued attempt has no start
    # time yet (it would sort first, and the older success would look like the latest)
    for status, started in (("queued", "2026-10-24T12:00:00Z"), ("in_progress", "2026-10-24T12:00:00Z"),
                            ("queued", "")):
        retry = {"id": 2, "run_attempt": 2, "status": status, "conclusion": None, "run_started_at": started,
                 "html_url": url2}
        assert alert_run(tmp_path, "a" * 40, "", "7", url1, runs=[{"workflow_runs": [older, retry]}])[0] == [], started
    newer_attempt = {**older, "run_attempt": 2, "conclusion": "failure", "run_started_at": "2026-10-24T13:00:00Z"}
    pages = [{"workflow_runs": [{**older, "id": 2, "html_url": url2}]}, {"workflow_runs": [newer_attempt]}]
    assert alert_run(tmp_path, "a" * 40, "", "7", url1, runs=pages)[0] == [["issue", "comment"]]


def test_what_the_guard_exempts_also_takes_the_content_lane():
    """Exempt from review implies the content lane (never the reverse: the lane is about tests, not trust)."""
    namespace = {}
    exec(guard_program().split("def tree(", 1)[0], namespace)
    from scripts.ci_needs_site import content_path
    for path in [f.relative_to(config.ROOT).as_posix() for f in config.ROOT.rglob("*")
                 if f.is_file() and not any(p in {".git", ".venv", "node_modules", "dist", "__pycache__"} for p in f.parts)]:
        assert not namespace["exempt_path"](path) or content_path(path), path
