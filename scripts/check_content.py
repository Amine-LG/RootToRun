"""Load all the course content (lessons, labs, incidents, challenges, modules, tracks, routes, concepts, cases, runbooks,
diagnostics) and report each problem on its file. Run it first when tests fail by the dozen: a file that does not
load drops its lessons, and everything that links to them fails too.

    .venv/bin/python scripts/check_content.py

In GitHub Actions each problem is also an error annotation on its file, shown on the pull request. Exit code 1 when
anything does not load.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from academy import config, curriculum, labs  # noqa: E402


def problems(lang: str = "en") -> list[str]:
    cur = curriculum.load(lang)
    return labs.errors(lang) + cur["errors"] + curriculum.integrity(set(labs.load(lang)), lang)


def source(problem: str) -> str | None:
    """The repository path of the file a problem names ("b2-images-storage.yaml: ..."), when exactly one file has it."""
    name = problem.split(":", 1)[0].strip().split("/")[-1]
    if not name.endswith((".yaml", ".yml", ".json")):
        return None
    found = [f for f in config.CONTENT_ROOT.rglob(name) if f.is_file()]
    if len(found) != 1:
        return None
    try:
        return found[0].resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return None


def annotation(problem: str, path: str | None) -> str:
    # GitHub's workflow command syntax: properties and message escaped as its documentation requires
    text = problem.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    where = f" file={path}," if path else " "
    return f"::error{where}title=Course content does not load::{text}"


def main() -> int:
    found = problems()
    for p in found:
        path = source(p)
        print(f"{path or '(content)'}: {p}")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(annotation(p, path))
    print(f"{len(found)} content problem(s)" + (": fix these first, the other failures follow from them" if found else ""))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
