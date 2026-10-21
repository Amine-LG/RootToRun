"""Content integrity: every lab and incident is recorded, every recorded command passed, nothing is stale.

"Recorded" means scripts/record.py executed the lab on a real cluster with the learner's own safety policy,
checked every command's exit code against its expectation, and verified the final state. These tests do not
re-run anything; they make sure the stored evidence matches the current content exactly.
"""
import json
from pathlib import Path
import re

import pytest

from academy import config, curriculum, labs

LANG = "en"
LABS = labs.load(LANG)
CUR = curriculum.load(LANG)


def rec(lab_id):
    p = config.RECORDINGS_DIR / f"{lab_id}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def test_content_loads_without_errors():
    assert labs.errors(LANG) == []
    assert CUR["errors"] == []
    assert curriculum.integrity(set(LABS), LANG) == []


def test_course_size():
    assert len(CUR["lessons"]) >= 45
    assert sum(1 for l in LABS.values() if l.kind == "incident") >= 16


@pytest.mark.parametrize("lab_id", sorted(LABS))
def test_lab_is_recorded_and_current(lab_id):
    lab = LABS[lab_id]
    r = rec(lab_id)
    assert r is not None, f"{lab_id} has never been recorded: .venv/bin/python scripts/record.py {lab_id}"
    assert r["ok"], f"{lab_id} recording failed: {r.get('problems')}"
    assert r.get("lab_hash") == labs.lab_hash(lab), f"{lab_id} changed since it was recorded: record it again"
    recorded = {(e["step"], e["cmd"]): e for e in r["entries"]}
    for where, c in lab.all_commands():
        e = recorded.get((where, c.cmd))
        assert e is not None, f"{lab_id}: `{c.cmd}` ({where}) is not in the recording"
        if c.skip or e.get("skipped"):
            continue
        assert e["ok"], f"{lab_id}: `{c.cmd}` exited {e['code']} (expected {c.expect})"
    if any(c.model_dump().get("final", True) is not False for c in lab.checks):
        assert r["verify_after"]["verdict"] == "verified", f"{lab_id}: final checks did not pass when recorded"


@pytest.mark.parametrize("lesson_id", sorted(i for i, l in CUR["lessons"].items() if l.commands))
def test_lesson_host_commands_are_recorded_and_current(lesson_id):
    lesson = CUR["lessons"][lesson_id]
    r = rec(f"lesson.{lesson_id}")
    assert r is not None and r["ok"], f"record it: .venv/bin/python scripts/record.py --lessons {lesson_id}"
    assert r["lab_hash"] == lesson.fingerprint(), "the lesson's commands changed since they were recorded"
    assert [e["cmd"] for e in r["entries"]] == [c.cmd for c in lesson.commands]


@pytest.mark.parametrize("lab_id", sorted(i for i, l in LABS.items() if l.kind == "incident"))
def test_incident_was_really_broken_before_the_fix(lab_id):
    r = rec(lab_id)
    assert r["verify_before"]["verdict"] != "verified", "an incident must fail its checks before the fix"


def test_recordings_contain_no_credentials():
    for p in config.RECORDINGS_DIR.glob("*.json"):
        text = p.read_text(encoding="utf-8")
        # the recorder writes `sha256~<token>` in place of a token; anything longer after the prefix is a real one
        assert not re.search(r"sha256~(?!<token>)[A-Za-z0-9_-]{8,}", text), p.name
        assert not re.search(r"eyJhbGciOi[A-Za-z0-9_-]{20,}", text), f"{p.name} contains a JWT"


# Commands named in lesson prose must exist in the recorded corpus (same verb and subcommand), except a short
# list the academy never executes on purpose.
NEVER_RUN = {
    "oc login": "credentials are handled by the Connections panel, never by a command the browser sends",
    "oc edit": "opens an interactive editor",
    "oc new-project": "lab projects are created by the lab lifecycle so they can be cleaned up safely",
    "oc create token": "its output is a credential",
    "oc debug node/<master>": "node access is never used by the academy",
    "oc adm must-gather": "collects a large diagnostic archive for vendor support",
    "oc adm node-logs": "reads a node's journal; cluster-admin only",
}
COMPOUND = {"adm", "auth", "set", "rollout", "policy", "create", "new-app", "import-image", "debug"}


def _sig(cmd):
    w = cmd.split()
    if w[0] == "kubectl":
        w[0] = "oc"
    if len(w) > 2 and w[1] in COMPOUND and not w[2].startswith(("-", "<", "…")):
        return " ".join(w[:4] if w[1] == "adm" and w[2] == "policy" and len(w) > 3 else w[:3])
    return " ".join(w[:2])


def test_commands_in_prose_are_recorded():
    corpus = set()
    for p in config.RECORDINGS_DIR.glob("*.json"):
        for e in json.loads(p.read_text(encoding="utf-8"))["entries"]:
            if e.get("ok") and not e.get("skipped"):
                corpus.add(_sig(e["cmd"]))
    missing = []
    def flow_text(l):  # every prose field of a teaching flow, including choices and feedback
        return [getattr(st, f, "") or "" for st in l.flow for f in ("body", "notice", "then", "hint", "prompt", "model", "why")] + \
            [c.why for st in l.flow for c in getattr(st, "choices", [])] + [st.choices[st.answer].text for st in l.flow if st.kind == "ask"] + \
            [h.say for st in l.flow for h in getattr(st, "hints", [])]  # wrong choices may show a command that does not exist, on purpose
    texts = {l.id: " ".join([l.objective, l.limits, l.enterprise, *[s.body for s in l.sections], *[p.prompt for p in l.predict], *[c.a for c in l.review], *flow_text(l)]) for l in CUR["lessons"].values()}
    texts |= {r.id: " ".join([r.when, *[s.body for s in r.steps]]) for r in CUR["runbooks"].values()}
    texts |= {c.id: " ".join([c.situation, *c.evidence, *c.automate, *[d.a for d in c.discussion]]) for c in CUR["cases"].values()}
    for lid, text in texts.items():
        fenced = [ln.strip().lstrip("$ ").split("  #")[0].strip() for blk in re.findall(r"```[a-z]*\n(.*?)```", text, re.S) for ln in blk.splitlines()]
        text = re.sub(r"```.*?```", " ", text, flags=re.S)
        host = [ln for ln in fenced if re.match(r"(podman|skopeo|buildah|crc) ", ln)]
        assert not host, f"{lid}: host commands in prose must be lesson `commands` so they are recorded: {host}"
        for m in re.findall(r"`((?:oc|kubectl) [^`]+)`", text) + [ln for ln in fenced if re.match(r"(oc|kubectl) ", ln)]:
            if m.split()[1].startswith("<"):
                continue  # a pattern such as `kubectl <verb> <kind>`, not a command
            s = _sig(m)
            if s in corpus or any(s.startswith(n) for n in NEVER_RUN) or any(c.startswith(s) for c in corpus):
                continue
            missing.append(f"{lid}: {m}")
    assert not missing, "lesson commands never executed by any lab:\n" + "\n".join(missing)


def test_lessons_only_refer_to_existing_diagrams_and_models():
    """A typo in `diagram:` or `simulator:` used to make an Explore activity silently disappear."""
    import re
    from content_reference_oracle import explore_problems

    root = Path(__file__).resolve().parent.parent / "frontend" / "src"
    diagrams = set(re.findall(r"^ {4}id: '([a-z0-9-]+)'", (root / "lib" / "diagrams.ts").read_text(encoding="utf-8"), re.M)) | {"pod-lifecycle", "crc-vs-prod"}
    models = set(re.findall(r"^ {4}id: '([a-z0-9-]+)'", (root / "sims" / "index.ts").read_text(encoding="utf-8"), re.M))
    assert len(models) == 9 and len(diagrams) >= 6
    bad = explore_problems(curriculum.load("en")["lessons"].values(), diagrams, models)
    assert not bad, bad


def test_existing_check_questions_keep_their_positions():
    """Progress saved by the first version keys answers as lesson:<id>:<index>, and migration maps that index to the
    question now at that position. New questions must therefore be appended, never inserted before existing ones.
    (Rewording a prompt also changes its stable id: update the fixture only for a deliberate change.)"""
    frozen = json.loads((Path(__file__).parent / "fixtures" / "question-positions.json").read_text(encoding="utf-8"))
    moved = []
    for lid, qids in frozen.items():
        if lid in CUR["lessons"] and CUR["lessons"][lid].flow:
            continue  # rewritten as a teaching flow: its questions are new, and positional answers are not migrated to them
        now = [q.id for q in CUR["lessons"][lid].predict] if lid in CUR["lessons"] else []
        if now[: len(qids)] != qids:
            moved.append(f"{lid}: was {qids}, now {now}")
    assert not moved, "check questions moved (append new ones at the end):\n" + "\n".join(moved)


def test_every_available_track_has_a_diagnostic_covering_each_lesson():
    """A diagnostic must reach every lesson (or practice item) of its track, or its study plan has blind spots."""
    d = curriculum.load("en")
    gaps = []
    for tr in d["tracks"].values():
        if tr.status != "available":
            continue
        g = d["diagnostics"].get(tr.id)
        if not g:
            gaps.append(f"{tr.id}: no diagnostic")
            continue
        firsts = {it.targets[0] for it in g.items}
        for mid in tr.modules:
            m = d["modules"][mid]
            for x in [*m.lessons, *m.labs]:
                if x not in firsts:
                    gaps.append(f"{tr.id}: {x} is not the first target of any item")
    assert not gaps, "\n".join(gaps)


def test_diagnostic_answers_are_not_always_in_the_same_place():
    """A position bias lets a learner score well without knowing anything."""
    from collections import Counter

    for g in curriculum.load("en")["diagnostics"].values():
        pos = Counter(it.answer for it in g.items)
        assert max(pos.values()) <= 0.5 * len(g.items), (g.track, dict(pos))


def test_practice_is_never_linked_before_the_lessons_it_needs():
    """A lesson may link a lab, incident or challenge only if every prerequisite of that practice comes at or before
    the lesson in the path (Foundations, then Application operations, then Platform administration, then Enterprise)."""
    order = [l for t in ("start", "admin1", "admin2", "platform") for m in CUR["tracks"][t].modules for l in CUR["modules"][m].lessons]
    pos = {l: i for i, l in enumerate(order)}
    early = []
    for l in order:
        for x in CUR["lessons"][l].labs:
            late = [p for p in LABS[x].prerequisites if p in pos and pos[p] > pos[l]]
            if late:
                early.append(f"{l} links {x}, which needs {late}")
        late = [p for p in CUR["lessons"][l].prerequisites if p in pos and pos[p] > pos[l]]
        if late:
            early.append(f"{l} has prerequisites that come later: {late}")
    assert not early, "\n".join(early)


def test_no_lesson_refers_to_a_lesson_that_does_not_come_before_it():
    """A look-back ("last lesson", "a look back", `recalls:`) must point to a lesson that really comes earlier in the
    learner's track, and the first lesson of a track can have none (a beginner starting there has done nothing)."""
    from academy import teachlint

    d = curriculum.load("en")
    bad = []
    for l in d["lessons"].values():
        if not l.flow:
            continue
        err, _ = teachlint.lint(d, l)
        bad += [f"{l.id}: {e}" for e in err if "earlier lesson" in e or "recalls" in e]
        for st in l.flow:
            if getattr(st, "recalls", "") and st.recalls not in d["lessons"]:
                bad.append(f"{l.id}/{st.id}: recalls an unknown lesson {st.recalls}")
    assert not bad, bad
    first = [d["modules"][t.modules[0]].lessons[0] for t in d["tracks"].values() if t.modules and d["modules"][t.modules[0]].lessons]
    assert "lx.first-steps" in first


def test_the_first_three_linux_lessons_meet_the_teaching_standard():
    """The acceptance pilot: no lint errors or warnings, look-backs that name their lesson, and every typed task with
    hints for the usual mistakes."""
    from academy import teachlint

    d = curriculum.load("en")
    order = [x for m in d["tracks"]["linux"].modules for x in d["modules"][m].lessons][:3]
    assert order == ["lx.first-steps", "lx.shell-basics", "lx.files-text"]
    for lid in order:
        err, warn = teachlint.lint(d, d["lessons"][lid])
        assert not err and not warn, (lid, err, warn)
    assert not any(getattr(s, "recalls", "") for s in d["lessons"]["lx.first-steps"].flow)
    for lid in order[1:]:
        assert any(getattr(s, "recalls", "") for s in d["lessons"][lid].flow), f"{lid}: its look-back does not name a lesson"


def test_the_lookback_rule_catches_a_first_lesson_that_assumes_a_previous_one():
    from academy import teachlint

    d = curriculum.load("en")
    l = d["lessons"]["lx.first-steps"].model_copy(deep=True)
    l.flow[0].body = "In the last lesson you typed `ls -l`."
    err, _ = teachlint.lint(d, l)
    assert any("nothing comes before this lesson" in e for e in err), err


def test_every_internal_link_points_to_existing_content():
    """No "not found" from a link in content: every /lesson/, /lab/, /learn/, /diagnostic/ link written in lessons,
    labs, runbooks, cases and routes names something that exists, and every route begins somewhere real."""
    targets = {
        "lesson": set(CUR["lessons"]),
        "lab": set(LABS),
        "learn": {t for t in CUR["tracks"]},
        "diagnostic": set(CUR["diagnostics"]),
    }
    blobs = {f"lesson {k}": v.model_dump_json() for k, v in CUR["lessons"].items()}
    blobs |= {f"lab {k}": v.model_dump_json() for k, v in LABS.items()}
    blobs |= {f"runbook {k}": v.model_dump_json() for k, v in CUR["runbooks"].items()}
    blobs |= {f"case {k}": v.model_dump_json() for k, v in CUR["cases"].items()}
    bad = []
    for where, text in blobs.items():
        for kind, ident in re.findall(r"\]\(/(lesson|lab|learn|diagnostic)/([A-Za-z0-9._-]+)", text):
            if ident not in targets[kind]:
                bad.append(f"{where}: /{kind}/{ident}")
    for r in CUR["routes"].values():
        b = r.begin
        kind = {"lesson": "lesson", "lab": "lab", "track": "learn", "diagnostic": "diagnostic"}[b.kind]
        if b.id not in targets[kind]:
            bad.append(f"route {r.id}: begins at missing {b.kind} {b.id}")
        # a route that begins with a lesson begins with its first lesson: "Continue" never sends the learner back
        first = next((l for s in r.steps for m in (CUR["tracks"][s].modules if s in CUR["tracks"] else [s])
                      for l in (CUR["modules"][m].lessons if m in CUR["modules"] else [])), None)
        if b.kind == "lesson" and b.id != first:
            bad.append(f"route {r.id}: begins at {b.id}, but its first lesson is {first}")
    for m in CUR["modules"].values():
        bad += [f"module {m.id}: missing lesson {x}" for x in m.lessons if x not in targets["lesson"]]
    for dk, diag in CUR["diagnostics"].items():
        for it in diag.items:
            bad += [f"diagnostic {dk}/{it.id}: missing target {x}" for x in it.targets if x not in targets["lesson"] and x not in targets["lab"]]
    assert not bad, bad
