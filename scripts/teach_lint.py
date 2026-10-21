"""Check lessons written as a teaching flow against the rules a program can check (docs/teaching/TEACHING-STANDARD.md).

    .venv/bin/python scripts/teach_lint.py                 # every flow lesson
    .venv/bin/python scripts/teach_lint.py lx.first-steps  # selected lessons
    --legacy   also report question metrics for lessons still in the long-form format

Errors (exit code 1): a show/try step whose command has no recording. Everything else is a warning to resolve or
justify; these are signals for a human reviewer, not a measure of teaching quality.
"""
import sys

sys.path.insert(0, "backend")
from academy import curriculum  # noqa: E402
from academy.teachlint import legacy, lint  # noqa: E402

def main(argv: list[str]) -> int:
    d = curriculum.load("en")
    ids = [a for a in argv if not a.startswith("--")]
    lessons = [d["lessons"][i] for i in ids] if ids else list(d["lessons"].values())
    errors = 0
    flow = [l for l in lessons if l.flow]
    for l in flow:
        err, warn = lint(d, l)
        errors += len(err)
        print(f"== {l.id}: {len(l.flow)} steps, {sum(1 for s in l.flow if s.kind in ('try', 'ask', 'order', 'reflect'))} for the learner, "
              f"{len(err)} errors, {len(warn)} warnings")
        for e in err:
            print("   ERROR " + e)
        for w in warn:
            print("   warn  " + w)
    if "--legacy" in argv:
        for l in lessons:
            if not l.flow:
                issues = legacy(l)
                print(f"-- {l.id} (long-form): {len(issues)} question issues")
                for i in issues:
                    print("   " + i)
    print(f"\n{len(flow)} flow lessons, {len(lessons) - len(flow)} long-form, {errors} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
