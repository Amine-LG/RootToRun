"""Grader evidence must not supply a diagnosis before the learner asks for the solution.

Titles are current author prose; grading results and recorded commands remain historical evidence.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest
import yaml

from academy import config, kube, labs, main

CHALLENGES = sorted(l.id for l in labs.load("en").values() if l.kind == "challenge")
MEASURED = ("id", "kind", "expect", "got", "ok")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("trial disclosure tests must not contact a cluster")
    for name in ("oc", "oc_json", "read", "helm", "whoami"):
        monkeypatch.setattr(kube, name, forbidden)


@pytest.mark.parametrize("lid", CHALLENGES)
def test_grader_outcomes_remain_available_without_disclosing_attempted_repairs(lid):
    original = copy.deepcopy(labs.recording(lid))
    public = TestClient(main.app).get(f"/api/labs/{lid}").json()
    trials = public["recording"]["trials"]
    assert original["trials"], "the example must actually contain grader trials"
    assert len(trials) == len(original["trials"])
    for shown, recorded in zip(trials, original["trials"]):
        assert shown["title"] == "", "an attempted repair's title can reveal the diagnosis"
        assert {k: shown[k] for k in MEASURED} == {k: recorded[k] for k in MEASURED}
        assert "commands" not in shown and "entries" not in shown
    assert public["lab"]["trials"] == [] and public["lab"]["fix"] == []
    assert "verify_after" not in public["recording"]
    assert labs.recording(lid) == original


def test_reveal_uses_current_titles_by_identity_without_changing_recorded_evidence(monkeypatch):
    lab = labs.load("en")["ch.recover-and-scale"].model_copy(deep=True)
    recording = copy.deepcopy(labs.recording(lab.id))
    original = copy.deepcopy(recording)
    # Different ordering makes a positional title overlay fail. None of these edits changes a file or recording.
    lab.trials.reverse()
    for trial in lab.trials:
        trial.title = f"Reviewed description for {trial.id}"
    monkeypatch.setattr(main, "_lab", lambda *args: lab)
    monkeypatch.setattr(labs, "recording", lambda *args: recording)
    result = TestClient(main.app).post(f"/api/labs/{lab.id}/reveal", headers={"X-Academy": "1"}).json()
    for trial, recorded in zip(result["trials"], original["trials"]):
        assert trial["title"] == f"Reviewed description for {recorded['id']}"
        assert {k: v for k, v in trial.items() if k != "title"} == {k: v for k, v in recorded.items() if k != "title"}
    assert result["verify_after"] == original["verify_after"]
    assert recording == original


def test_an_orphan_recorded_trial_cannot_restore_stale_teaching_text(monkeypatch):
    lab = labs.load("en")["ch.recover-and-scale"].model_copy(deep=True)
    lab.trials = []
    monkeypatch.setattr(main, "_lab", lambda *args: lab)
    result = main.lab_reveal(lab.id)
    assert result["trials"] and all(t["title"] == "" for t in result["trials"])


def test_static_export_obeys_disclosure_and_current_prose_contract(tmp_path):
    content = tmp_path / "content"
    shutil.copytree(config.CONTENT_ROOT, content)
    source = content / "en/challenges/ch-recover-and-scale.yaml"
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    trial = next(t for t in raw["trials"] if t["id"] == "two-of-three")
    trial["title"] = "A newly reviewed description of the incomplete attempt"
    source.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    recording_file = content / "recordings/ch.recover-and-scale.json"
    original_bytes = recording_file.read_bytes()
    recorded = json.loads(original_bytes)
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text('<html><head><title>Test</title></head><body><div id="root"></div></body></html>', encoding="utf-8")
    result = subprocess.run([sys.executable, str(config.ROOT / "scripts/export_static.py"), "--out", str(site)],
                            env={**os.environ, "ACADEMY_CLUSTER": "off", "ACADEMY_CONTENT_DIR": str(content)},
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    public = json.loads((site / "data/en/labs/ch.recover-and-scale.json").read_text(encoding="utf-8"))
    answer = json.loads((site / "data/en/labs/ch.recover-and-scale.reveal.json").read_text(encoding="utf-8"))
    assert all(t["title"] == "" for t in public["recording"]["trials"])
    shown = next(t for t in answer["trials"] if t["id"] == "two-of-three")
    assert shown["title"] == trial["title"]
    assert [{k: t[k] for k in MEASURED} for t in public["recording"]["trials"]] == [
        {k: t[k] for k in MEASURED} for t in recorded["trials"]]
    assert recording_file.read_bytes() == original_bytes
