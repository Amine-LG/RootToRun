"""Which CI lane does a pull request need? (.github/workflows/ci.yml; docs/CI.md)

    git diff --no-renames --raw -z BASE...HEAD | python3 -I scripts/ci_needs_site.py --tier-raw   # tier=content|deep

"content" (the quick lane, checks-content.yml) only when EVERY changed path is contributor data on the short
allow-list below: course text, recordings and screenshots under content/, and Markdown documentation. Anything else
(code, tests, scripts, workflows, .github/**, package or lock files, Containerfile, nginx, a file type the list does
not name, an empty or malformed list) is "deep" (checks-app.yml). Without rename detection a moved file counts by its
old path too, so code cannot be renamed into an allowed name.

Trust: the pull-request workflow runs the copy of this file from the pull request's BASE commit (`git show
BASE:scripts/ci_needs_site.py`, isolated Python), never the copy in the pull request, so a change to this file takes
effect only after it is reviewed and merged. The output is one fixed word; no path ever reaches a workflow output.

Without arguments it keeps the old interface for the rollout (newline-separated paths in, `true`/`false` out: does
the change need the image and browser tests), unchanged from before the lanes, until the old ci.yml is gone.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import PurePosixPath
import re
import sys

ROOT_DOCS = {"README.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md", "CHANGELOG.md",
             "THIRD_PARTY_NOTICES.md"}
TEXT = {".yaml", ".yml", ".md"}


def content_path(path: str) -> bool:
    """True only for a file on the contributor-data allow-list (exact, case-sensitive suffixes)."""
    parts = path.split("/")
    if not path or "\\" in path or any(p in ("", ".", "..") for p in parts):
        return False
    suffix = PurePosixPath(path).suffix
    if path in ROOT_DOCS:
        return True
    if parts[0] == "docs":
        return len(parts) > 1 and suffix == ".md"
    if parts[0] != "content" or len(parts) < 2:
        return False
    if parts[1] == "media":  # content/media/<lesson>/<image>.png: type, size and symlinks checked by academy.media
        return len(parts) == 4 and suffix == ".png"
    if parts[1] == "recordings":  # recorded command outputs, checked against the lessons by the content tests
        return len(parts) > 2 and suffix == ".json"
    return suffix in TEXT


def tier(paths: list[str]) -> str:
    return "content" if paths and all(content_path(p) for p in paths) else "deep"


def parse_nul(raw: bytes) -> list[str]:
    """git's -z list: every name ends with NUL. Anything else (truncated, newline-separated, empty) gives []."""
    if not raw.endswith(b"\0"):
        return []
    return [os.fsdecode(p) for p in raw[:-1].split(b"\0")]


def parse_raw(raw: bytes) -> list[str]:
    """Git --raw -z without renames: header NUL path NUL. Only ordinary data files may use the content lane.

    Check both sides: deleting a link, executable or gitlink also needs the deep lane. Reject malformed headers,
    type changes and unexpected statuses rather than silently ignoring an entry.
    """
    if not raw.endswith(b"\0"):
        return []
    fields = raw[:-1].split(b"\0")
    if len(fields) % 2:
        return []
    paths = []
    for header, path in zip(fields[::2], fields[1::2]):
        if not re.fullmatch(rb":(?:000000|100644) (?:000000|100644) [0-9a-f]{4,64} [0-9a-f]{4,64} [AMD]", header):
            return []
        paths.append(os.fsdecode(path))
    return paths


# The old interface (until the old ci.yml is gone): files read neither by the image build nor by the browser tests.
NOT_THE_SITE = [
    "docs/*",
    ".github/ISSUE_TEMPLATE/*",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "README.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md", "CHANGELOG.md", "THIRD_PARTY_NOTICES.md",
    "tests/test_*.py",  # the Python suite (always run); browser tests live in tests/e2e/ and are not on this list
]


def needs_site(paths: list[str]) -> bool:
    paths = [p.strip() for p in paths if p.strip()]
    if not paths:
        return True
    return not all(any(fnmatch.fnmatchcase(p, pat) for pat in NOT_THE_SITE) and not p.startswith("tests/e2e/")
                   for p in paths)


if __name__ == "__main__":
    if sys.argv[1:] == ["--tier-raw"]:
        print(f"tier={tier(parse_raw(sys.stdin.buffer.read()))}")
    elif sys.argv[1:] == ["--tier"]:
        print(f"tier={tier(parse_nul(sys.stdin.buffer.read()))}")
    elif sys.argv[1:]:
        sys.exit("usage: ci_needs_site.py [--tier|--tier-raw]")
    else:
        print(str(needs_site(sys.stdin.read().splitlines())).lower())
