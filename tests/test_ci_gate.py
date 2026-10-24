"""ci-ok, the one check a ruleset requires (docs/CI.md): the router runs the base commit's classifier, calls exactly
one lane, and ci-ok passes only when the classifier ran and the lane it chose succeeded while the other was skipped.
Its own shell runs here against every result GitHub can give (failure, cancelled, skipped, missing), and no job of a
lane can be skipped by a condition (a skipped job counts as passed inside a called workflow)."""
import itertools
import os
import subprocess

from test_ci_workflows import WORKFLOWS


def test_the_router_calls_one_lane_per_verdict_and_the_gate_needs_all():
    jobs = WORKFLOWS["ci.yml"]["jobs"]
    assert set(jobs) == {"classify", "checks-content", "checks-app", "ci-ok"}
    assert jobs["checks-content"] == {"needs": "classify", "if": "needs.classify.outputs.tier == 'content'",
                                      "uses": "./.github/workflows/checks-content.yml"}
    assert jobs["checks-app"] == {"needs": "classify", "if": "needs.classify.outputs.tier == 'deep'",
                                  "uses": "./.github/workflows/checks-app.yml"}
    assert jobs["ci-ok"]["needs"] == ["classify", "checks-content", "checks-app"] and jobs["ci-ok"]["if"] == "always()"
    run = jobs["classify"]["steps"][1]["run"]
    assert 'git show "$BASE:scripts/ci_needs_site.py"' in run and "python3 -I" in run
    assert 'git diff --no-renames --raw -z "$BASE...$HEAD"' in run and "--tier-raw" in run
    assert 'if [ "$verdict" = "tier=content" ]; then tier=content; else tier=deep; fi' in run
    # inside a lane, a job is skipped only when one it needs failed (the lane then fails): no condition can quietly
    # skip a check, except the dependency review, which needs a pull request's base
    for name in ("checks-content.yml", "checks-app.yml", "checks-main.yml"):
        for job_id, job in WORKFLOWS[name]["jobs"].items():
            assert "if" not in job or (name, job_id, job["if"]) == (
                "checks-app.yml", "deps", "github.event_name == 'pull_request'"), f"{name}:{job_id}"
            assert job.get("strategy", {}).get("fail-fast", False) is False, f"{name}:{job_id}"


def gate_script():
    return WORKFLOWS["ci.yml"]["jobs"]["ci-ok"]["steps"][0]["run"]


def test_the_gate_decision_table_for_every_combination():
    """Exhaustive: every result GitHub can report (and an empty value) for each input, and odd verdicts."""
    results = ["success", "failure", "cancelled", "skipped", ""]
    tiers = ["content", "deep", "", "full", "content ", "CONTENT"]
    passes = []
    for classify, tier, content, app in itertools.product(results, tiers, results, results):
        env = {"PATH": os.environ["PATH"], "CLASSIFY": classify, "TIER": tier, "CONTENT": content, "APP": app}
        ok = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", gate_script()], env=env,
                            capture_output=True).returncode == 0
        expected = classify == "success" and ((tier, content, app) in {("content", "success", "skipped"),
                                                                       ("deep", "skipped", "success")})
        assert ok == expected, env
        passes += [(classify, tier, content, app)] if ok else []
    assert len(passes) == 2  # of 5 * 6 * 5 * 5 = 750 combinations
