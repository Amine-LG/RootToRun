"""An explicit Explore step must resolve just like a lesson-level model or diagram."""
from types import SimpleNamespace

import pytest

from academy.curriculum import Explore
from content_reference_oracle import explore_problems


def lesson(**kwargs):
    return SimpleNamespace(id="lesson", diagram=None, simulator=None, flow=[], **kwargs)


def test_both_explore_forms_and_legacy_diagram_aliases_resolve():
    content = lesson()
    content.diagram = "pod-lifecycle"
    content.simulator = "scheduler"
    content.flow = [Explore(kind="explore", id="read-path", diagram="request-path"),
                    Explore(kind="explore", id="place-pod", sim="scheduler")]
    assert explore_problems([content], {"pod-lifecycle", "request-path"}, {"scheduler"}) == []


@pytest.mark.parametrize("field,kind", [("diagram", "diagram"), ("sim", "model")])
@pytest.mark.parametrize("target", ["missing", "", "scheduler"], ids=["missing", "empty", "wrong-catalogue"])
def test_explicit_explore_references_are_checked_in_their_own_catalogue(field, kind, target):
    content = lesson()
    if field == "sim" and target == "scheduler":
        target = "request-path"  # a valid diagram must not be accepted as a model
    content.flow = [Explore(kind="explore", id="activity", **{field: target})]
    assert explore_problems([content], {"request-path"}, {"scheduler"}) == [
        f"lesson/activity: unknown {kind} {target!r}"]


@pytest.mark.parametrize("field,kind", [("diagram", "diagram"), ("simulator", "model")])
def test_lesson_level_references_remain_checked(field, kind):
    content = lesson()
    setattr(content, field, "missing")
    assert explore_problems([content], {"request-path"}, {"scheduler"}) == [f"lesson: unknown {kind} 'missing'"]


def test_non_explore_flow_steps_do_not_add_references():
    content = lesson()
    content.flow = [SimpleNamespace(kind="teach", id="explanation")]
    assert explore_problems([content], set(), set()) == []
