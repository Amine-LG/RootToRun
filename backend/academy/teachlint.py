"""Checks of the teaching standard (docs/teaching/TEACHING-STANDARD.md) that a program can make, for lessons written
as a teaching flow. Used by scripts/teach_lint.py and by the authoring page. These are signals for a human
reviewer, not a measure of teaching quality."""
from __future__ import annotations

import json
import re

from . import config, curriculum

BANNED = re.compile(r"\b(just|simply|obviously|easy|easily|of course|as you know)\b|!(?!=)", re.I)
TOOLS = {  # track -> (pattern, what to say)
    "linux": (re.compile(r"(?<![\w-])(oc|kubectl|podman|docker)\s+[a-z-]+|\bpods?\b|\bkubelet\b|\bOpenShift\b|\bKubernetes\b"),
              "container or platform vocabulary in a Linux lesson"),
    "containers": (re.compile(r"(?<![\w-])(oc|kubectl)\s+[a-z-]+"), "a cluster CLI in a container lesson"),
    "start": (re.compile(r"(?<![\w-])oc\s+[a-z-]+"), "oc in a Kubernetes lesson (use kubectl, or say why not)"),
}
BRIDGES = {"c.openshift-extends", "k.kubectl-to-oc"}  # lessons whose job is to compare the two clients
words = lambda s: len(re.findall(r"\S+", s or ""))  # noqa: E731


def track_of(d: dict, lesson_id: str) -> str:
    for t in d["tracks"].values():
        for m in t.modules:
            if lesson_id in d["modules"].get(m, curriculum.Module(id=m, title="", summary="")).lessons:
                return t.id
    return ""


# Words that refer the learner to an earlier lesson. They are only allowed with a link to (or, for a question, a
# `recalls:` naming) a lesson that really comes earlier in the same track; never in a track's first lesson.
LOOKBACK = re.compile(r"\b(look back|looking back|last lesson|previous lesson|earlier lesson|lesson before)\b", re.I)


def earlier_lessons(d: dict, lesson_id: str) -> list[str]:
    """Lessons before `lesson_id` in its track, in path order."""
    for t in d["tracks"].values():
        order = [x for m in t.modules for x in d["modules"][m].lessons] if all(m in d["modules"] for m in t.modules) else []
        if lesson_id in order:
            return order[: order.index(lesson_id)]
    return []


def recorded(lesson_id: str) -> set[str]:
    f = config.RECORDINGS_DIR / f"lesson.{lesson_id}.json"
    return {e["cmd"] for e in json.loads(f.read_text(encoding="utf-8"))["entries"]} if f.exists() else set()


def lint(d: dict, l) -> tuple[list[str], list[str]]:
    err, warn = [], []
    rec = recorded(l.id)
    tr = track_of(d, l.id)
    run_of_quiet = 0
    for st in l.flow:
        where = f"{st.kind} {st.id}"
        texts = [getattr(st, f, "") or "" for f in ("title", "body", "notice", "then", "prompt", "model", "why", "hint")]
        texts += [c.text + " " + c.why for c in getattr(st, "choices", [])] + [h.say for h in getattr(st, "hints", [])]
        if st.kind in ("show", "try") and st.run and st.run not in rec:
            err.append(f"{where}: `{st.run}` has no recording (run scripts/record.py --lessons {l.id})")
        if st.kind == "teach" and words(st.body) > 180:
            warn.append(f"{where}: {words(st.body)} words; one idea per step is usually under 180")
        run_of_quiet = 0 if st.kind in ("try", "ask", "order", "reflect", "explore") else run_of_quiet + 1
        if run_of_quiet == 5:
            warn.append(f"{where}: five steps in a row with nothing for the learner to do")
        for t in texts:
            m = BANNED.search(re.sub(r"`[^`]*`|```.*?```", "", t, flags=re.S))
            if m:
                warn.append(f"{where}: avoid {m.group(0)!r}")
                break
        if tr in TOOLS and l.id not in BRIDGES:
            pat, say = TOOLS[tr]
            for t in texts + [getattr(st, "run", "") or "", getattr(st, "code", "") or ""] + list(getattr(st, "accept", [])):
                m = pat.search(t)
                if m:
                    warn.append(f"{where}: {say} ({m.group(0)!r})")
                    break
        if st.kind == "ask":
            if words(st.prompt) > 30:
                warn.append(f"{where}: stem has {words(st.prompt)} words; aim for 25 or fewer")
            lens = [words(c.text) for c in st.choices]
            others = [n for i, n in enumerate(lens) if i != st.answer]
            if lens[st.answer] > max(others) and lens[st.answer] >= 1.3 * max(others) and lens[st.answer] - max(others) >= 3:
                warn.append(f"{where}: the right option is clearly the longest ({lens})")
            if len(st.choices) > 3:
                warn.append(f"{where}: four options; keep the fourth only for a distinct real misconception")
            if re.match(r"\s*(yes|right|correct)\b", st.choices[st.answer].why, re.I):
                warn.append(f"{where}: the right option's why starts with yes/right; the interface already says so")
        earlier = set(earlier_lessons(d, l.id)) | set(l.prerequisites)
        recalls = getattr(st, "recalls", "")
        if recalls and recalls not in earlier:
            err.append(f"{where}: recalls {recalls}, which does not come before this lesson")
        if any(LOOKBACK.search(t) for t in texts):
            links = set(re.findall(r"\(/lesson/([a-z0-9.-]+)", " ".join(texts)))
            if not earlier:
                err.append(f"{where}: refers to an earlier lesson, but nothing comes before this lesson")
            elif not (recalls or links & earlier):
                warn.append(f"{where}: refers to an earlier lesson without naming it (link it, or `recalls:` on a question)")
        if st.kind == "show" and st.code and st.origin == "file" and re.search(r"^\$ \S", st.code, re.M):
            err.append(f"{where}: terminal output in `code` must say where it comes from (origin: example or lab); never invent it")
        if st.kind == "try" and not st.hints:
            warn.append(f"{where}: no targeted hints for the usual mistakes")
    if not any(st.kind == "teach" and st.title.lower().startswith("what you can do") for st in l.flow):
        warn.append("no closing 'What you can do now' step")
    return err, warn


def legacy(l) -> list[str]:
    out = []
    for k, q in enumerate(l.predict):
        lens = [words(c) for c in q.choices]
        if q.answer is not None and lens[q.answer] == max(lens) and lens.count(max(lens)) == 1:
            out.append(f"Q{k}: the right option is the longest ({lens})")
        if words(q.prompt) > 30:
            out.append(f"Q{k}: stem has {words(q.prompt)} words")
    return out


