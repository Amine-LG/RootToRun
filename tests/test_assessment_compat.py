"""Answer indices and correctness already saved in a browser must retain their meaning."""
import json
from pathlib import Path

import pytest

from academy import curriculum
from scripts.check_assessment_compat import assessment_contracts, compatibility_problems


def example():
    lesson = curriculum.Lesson(
        id="example", title="Read output", module="module", mode="LOCAL_SIMULATION", minutes=5,
        supports="local", concepts=[], objective="Interpret the result",
        flow=[{
            "kind": "ask", "id": "cause", "prompt": "Which resource owns the desired replica count?",
            "choices": [{"text": "Deployment", "why": "Owns the desired count"},
                        {"text": "Pod", "why": "A single running instance"}], "answer": 0,
        }],
    )
    diagnostic = curriculum.Diagnostic(
        track="track", title="Starting point", intro="Find a topic to study", minutes=1,
        items=[{
            "id": "replicas", "targets": ["example"], "prompt": "Where is the replica count declared?",
            "choices": ["Deployment", "Pod"], "answer": 0,
            "feedback": ["Desired state", "One instance"], "explain": "The controller acts on desired state",
        }],
    )
    return {"lessons": {lesson.id: lesson}, "diagnostics": {diagnostic.track: diagnostic}}


def test_existing_assessments_preserve_saved_answers():
    frozen = json.loads((Path(__file__).parent / "fixtures/assessment-contracts.json").read_text(encoding="utf-8"))
    assert frozen, "an empty baseline protects no saved answers"
    data = curriculum.load("en")
    assert not data["errors"], data["errors"]
    problems = compatibility_problems(frozen, assessment_contracts(data))
    assert not problems, "\n".join(problems)


def test_feedback_and_new_assessments_do_not_reinterpret_saved_answers():
    data = example()
    frozen = assessment_contracts(data)
    question = data["lessons"]["example"].predict[0]
    question.feedback = ["An improved explanation", "A clearer misconception"]
    question.explain = "More detailed feedback"
    data["diagnostics"]["track"].items[0].explain = "A better explanation"
    data["lessons"]["example"].predict.append(curriculum.Predict(
        prompt="A new question", choices=["A", "B"], answer=1, explain="A new idea",
    ))
    assert compatibility_problems(frozen, assessment_contracts(data)) == []


@pytest.mark.parametrize("change", ["reorder", "answer", "choice-text", "role", "prompt", "delete"])
def test_lesson_answer_contract_detects_incompatible_edits(change):
    data = example()
    frozen = assessment_contracts(data)
    question = data["lessons"]["example"].predict[0]
    if change == "reorder":
        question.choices.reverse()
        question.answer = 1  # even preserving the correct TEXT reinterprets a saved choice index
    elif change == "answer":
        question.answer = 1
    elif change == "choice-text":
        question.choices[1] = "ReplicaSet"
    elif change == "role":
        question.role = "predict"
    elif change == "prompt":
        question.prompt = "A different question"
    else:
        data["lessons"]["example"].predict.clear()
    problems = compatibility_problems(frozen, assessment_contracts(data))
    assert len(problems) == 1 and problems[0].startswith("lesson/example/"), problems


@pytest.mark.parametrize("change", ["reorder", "answer", "prompt", "evidence", "target", "id", "delete"])
def test_diagnostic_history_cannot_be_reused_for_a_different_assessment(change):
    data = example()
    frozen = assessment_contracts(data)
    item = data["diagnostics"]["track"].items[0]
    if change == "reorder":
        item.choices.reverse()
        item.answer = 1
    elif change == "answer":
        item.answer = 1
    elif change == "prompt":
        item.prompt = "A different question"
    elif change == "evidence":
        item.evidence = "replicas: 0"
    elif change == "target":
        item.targets = ["another-lesson"]
    elif change == "id":
        item.id = "renamed"
    else:
        data["diagnostics"]["track"].items.clear()
    problems = compatibility_problems(frozen, assessment_contracts(data))
    assert len(problems) == 1 and problems[0].startswith("diagnostic/track/"), problems
