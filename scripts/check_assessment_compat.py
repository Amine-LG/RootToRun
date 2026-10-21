"""Protect saved answers when existing assessments are edited.

    .venv/bin/python scripts/check_assessment_compat.py

Question identity alone is insufficient: saved answers include a choice index and
an already-computed correctness flag. Retaining an identity while changing its
choices, answer or scored/prediction role reinterprets that history. Diagnostic
history also retains its item id, so its question and study targets must agree.

The reviewed fixture is append-friendly: new assessments need no fixture update.
Removing or changing a frozen assessment needs a deliberate progress migration
and review of the fixture, rather than automatically regenerating it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _digest(value: list) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def assessment_contracts(data: dict) -> dict[str, str]:
    """Fingerprint only the meaning of stored answers, excluding explanatory prose.

    Use compiled Predict ids for flow and legacy lessons: these are the identities
    consumed by plan.ts and progress.ts, rather than the flow's display step ids.
    """
    out = {}
    for lesson in data["lessons"].values():
        for question in lesson.predict:
            out[f"lesson/{lesson.id}/{question.id}"] = _digest(
                [question.choices, question.answer, question.role]
            )
    for diagnostic in data["diagnostics"].values():
        for item in diagnostic.items:
            out[f"diagnostic/{diagnostic.track}/{item.id}"] = _digest(
                [item.prompt, item.evidence, item.choices, item.answer, item.targets]
            )
    return out


def compatibility_problems(expected: dict[str, str], actual: dict[str, str]) -> list[str]:
    problems = []
    for key, fingerprint in sorted(expected.items()):
        if key not in actual:
            problems.append(f"{key}: saved assessment identity removed")
        elif actual[key] != fingerprint:
            problems.append(f"{key}: saved answer meaning changed (choices, answer, role or diagnostic question/targets)")
    return problems


def main() -> int:
    from academy import curriculum

    data = curriculum.load("en")
    if data["errors"]:
        print("\n".join(data["errors"]))
        return 1
    frozen = json.loads((ROOT / "tests/fixtures/assessment-contracts.json").read_text(encoding="utf-8"))
    problems = compatibility_problems(frozen, assessment_contracts(data))
    for problem in problems:
        print(problem)
    print(f"{len(problems)} compatibility problem(s); {len(frozen)} existing assessments protected")
    return int(bool(problems))


if __name__ == "__main__":
    sys.exit(main())
