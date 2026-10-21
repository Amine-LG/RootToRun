#!/usr/bin/env python3
"""Store a readable slug for every track, lesson and lab that has none yet in content/en/urls.yaml.

    .venv/bin/python scripts/slugs.py           add the missing slugs (made from titles); existing ones never change
    .venv/bin/python scripts/slugs.py --check   change nothing; exit 1 when a slug is missing or invalid

A slug is made from the title once and then kept: renaming a lesson does not change its address. To change an
address on purpose, edit its slug in content/en/urls.yaml by hand (the old address then stops working, so prefer to
keep it). See backend/academy/urls.py for the address scheme.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.academy import curriculum, labs, urls  # noqa: E402

HEADER = """\
# Public addresses: one slug per track, lesson and lab id (see backend/academy/urls.py).
#   track   /learn/<track>                lesson  /learn/<track>/<lesson>
#   lab     /labs/<lab>, /incidents/<lab> or /challenges/<lab> (by kind)
# A slug is made from the title once (scripts/slugs.py adds missing ones) and never changes when the title does.
# Ids never change either: progress, recordings and links in content use them; old /lesson/<id> addresses redirect.
# Edit a slug by hand only to fix a bad one, before it is published. scripts/slugs.py keeps this header comment only.
"""


def scalar(s: str) -> str:
    """A YAML scalar that reads back as this exact string (quoted only when it would not, like `no` or `1e3`)."""
    try:
        if yaml.safe_load(s) == s and ":" not in s and "#" not in s:
            return s
    except yaml.YAMLError:
        pass
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def course_order() -> dict[str, list[str]]:
    """Ids in the order a reader of the file expects: tracks as listed, lessons in course order, labs by kind."""
    cur, all_labs = curriculum.load("en"), labs.load("en")
    lessons = [l for t in cur["tracks"].values() for m in t.modules for l in (cur["modules"][m].lessons if m in cur["modules"] else [])]
    lessons += [l for l in cur["lessons"] if l not in lessons]
    kinds = list(urls.LAB_SECTION)
    lab_ids = sorted(all_labs, key=lambda k: (kinds.index(all_labs[k].kind), k))
    return {"tracks": list(cur["tracks"]), "lessons": lessons, "labs": lab_ids}


def render(entries: dict[str, dict[str, str]], header: str) -> str:
    out = [header.rstrip("\n")]
    for sec in urls.SECTIONS:
        out.append(f"{sec}:")
        out += [f"  {scalar(k)}: {scalar(v)}" for k, v in entries[sec].items()]
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    f = urls.file()
    current = urls.stored()
    new = urls.missing()
    count = sum(len(v) for v in new.values())
    if check:
        problems = urls.problems()
        for p in problems:
            print(p)
        return 1 if problems else 0
    if not count:
        print(f"{f.relative_to(ROOT) if f.is_relative_to(ROOT) else f}: every track, lesson and lab has a slug")
    else:
        order = course_order()
        merged = {sec: dict(current[sec]) for sec in urls.SECTIONS}  # existing entries first, unchanged and in order
        for sec in urls.SECTIONS:
            for ident in order[sec]:
                if ident in new[sec]:
                    merged[sec][ident] = new[sec][ident]
                    print(f"  + {sec[:-1]} {ident}: {new[sec][ident]}")
        lines = (f.read_text(encoding="utf-8") if f.exists() else "").splitlines(keepends=True)
        n = next((i for i, line in enumerate(lines) if not line.startswith("#")), len(lines))
        f.write_text(render(merged, "".join(lines[:n]) or HEADER), encoding="utf-8", newline="\n")  # the file's own header comment is kept
        print(f"stored {count} new slug(s) in {f}")
    problems = urls.problems()
    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
