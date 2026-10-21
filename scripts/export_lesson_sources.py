"""Copy a lesson's actual recording inputs into a new directory; execute nothing.

    .venv/bin/python scripts/export_lesson_sources.py ct.troubleshoot-containers --out /tmp/my-container-lesson

This exports declared inputs, not generated files, cluster resources or credentials. Follow the lesson's
environment/identity requirements and command order. A successful export is not a successful experiment.
"""
from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def export_files(files: dict[str, str], out: Path) -> list[str]:
    """Validate every destination before writing. An existing directory must be empty and not a symlink."""
    paths = {}
    for name in files:
        path = PurePosixPath(name)
        if not name or "\0" in name or path.is_absolute() or any(p in ("", ".", "..") for p in name.split("/")) or "\\" in name:
            raise ValueError(f"source path must be relative and stay inside the output directory: {name!r}")
        paths[name] = path
    for name, path in paths.items():
        if any(str(parent) in paths for parent in path.parents):
            raise ValueError(f"source path is both a file and a parent directory: {name!r}")
    if out.is_symlink() or out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError(f"output must be a new or empty directory, never a symlink: {out}")
    if not files:
        raise ValueError("this lesson declares no source files; inspect its setup commands instead")
    out.mkdir(parents=True, exist_ok=True)
    for name in files:
        dest = out.joinpath(*paths[name].parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(files[name].encode("utf-8"))
    return list(files)


def main() -> int:
    from academy import curriculum

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lesson", help="existing lesson ID")
    parser.add_argument("--out", type=Path, required=True, help="new or empty working directory")
    args = parser.parse_args()
    lesson = curriculum.load("en")["lessons"].get(args.lesson)
    if lesson is None:
        parser.error(f"unknown lesson: {args.lesson}")
    try:
        names = export_files(lesson.files, args.out)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"{lesson.id}: exported {len(names)} source files to {args.out}")
    for name in names:
        print(f"  {name}")
    print(f"Recording environment: {lesson.record_on}. {lesson.supports}")
    print("Files only; no commands executed. Follow the lesson's environment, identities and command order.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
