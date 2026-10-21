"""'Understand this command' (curriculum.Understand): optional explanations of demonstrated or practised commands.

They must explain the command the step really shows, cite where each statement was checked, link only to concepts
that exist, and not explain the same command twice.
"""
import pytest
from pydantic import ValidationError

from academy import curriculum

CUR = curriculum.load("en")
EXPLAINED = [(l.id, s) for l in CUR["lessons"].values() for s in l.flow if getattr(s, "understand", None)]


def test_a_useful_number_of_commands_are_explained():
    assert len(EXPLAINED) >= 20


@pytest.mark.parametrize("lid,step", EXPLAINED, ids=[f"{lid}/{s.id}" for lid, s in EXPLAINED])
def test_explanation_is_sourced_and_linked(lid, step):
    u = step.understand
    assert u.purpose.strip()
    assert u.refs and all(r.url.startswith("https://") and r.title.strip() for r in u.refs)
    assert all(c in CUR["concepts"] for c in u.concepts)
    shown = [x for x in (step.run, getattr(step, "accept", [None])[0]) if x]
    for p in u.parts:
        assert any(p.text in c for c in shown), p.text
        assert p.means.strip()
    assert len({p.text for p in u.parts}) == len(u.parts), "an option is explained twice"


def test_no_command_is_explained_twice():
    seen = {}
    for lid, s in EXPLAINED:
        cmd = s.run or s.accept[0]
        assert cmd not in seen, f"{lid}/{s.id} explains the same command as {seen.get(cmd)}"
        seen[cmd] = f"{lid}/{s.id}"


def test_parts_must_be_written_in_the_command():
    u = {"purpose": "p", "parts": [{"text": "--not-in-the-command", "means": "m"}], "refs": [{"title": "t", "url": "https://example.org/"}]}
    with pytest.raises(ValidationError, match="does not appear in the command"):
        curriculum.Show(kind="show", id="x", run="oc get pods", understand=u)
    with pytest.raises(ValidationError, match="shows none"):
        curriculum.Show(kind="show", id="x", code="a: 1", understand={**u, "parts": []})
    with pytest.raises(ValidationError):  # a source is required
        curriculum.Show(kind="show", id="x", run="oc get pods", understand={**u, "parts": [], "refs": []})
    ok = curriculum.Try(kind="try", id="y", body="b", accept=["oc get pods"], run="oc get pods -o wide", understand={**u, "parts": [{"text": "-o wide", "means": "m"}]})
    assert ok.understand.parts[0].text == "-o wide"  # a try step may explain its recorded command too


def test_unknown_concepts_are_integrity_problems():
    lid, step = EXPLAINED[0]
    data = dict(CUR)
    lesson = CUR["lessons"][lid].model_copy(deep=True)
    st = next(s for s in lesson.flow if s.id == step.id)
    st.understand.concepts = ["no.such-concept"]
    data["lessons"] = {**CUR["lessons"], lid: lesson}
    problems = curriculum.integrity(set(), "en", data=data)
    assert any("understand names unknown concept no.such-concept" in p for p in problems)
