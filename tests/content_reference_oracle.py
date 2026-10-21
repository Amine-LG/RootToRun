"""References the lesson renderer consumes, including explicit flow activities."""


def explore_problems(lessons, diagrams: set[str], models: set[str]) -> list[str]:
    problems = []
    for lesson in lessons:
        references = [(lesson.id, "diagram", lesson.diagram), (lesson.id, "model", lesson.simulator)]
        references += [(f"{lesson.id}/{step.id}", kind, getattr(step, field))
                       for step in lesson.flow if step.kind == "explore"
                       for kind, field in (("diagram", "diagram"), ("model", "sim"))]
        for where, kind, target in references:
            if target is not None and target not in (diagrams if kind == "diagram" else models):
                problems.append(f"{where}: unknown {kind} {target!r}")
    return problems
