"""Does a pull request change anything that the website or its browser tests are made from?

    git diff --name-only BASE...HEAD | python scripts/ci_needs_site.py      # prints true or false

The CI skips the production-image build and the browser tests only when every changed file is on the short list
below (documentation, repository forms, Python-only tests). Anything else, including a file this list does not know
or an empty list, means "true". The CI lists files without rename detection, so a file moved out of the site counts
by its old path too. Pushes to main and candidate builds always run everything; this only shortens pull requests
that cannot change the site, and is not a security control (a pull request can edit this file).
"""
from __future__ import annotations

import fnmatch
import sys

# Not read by the image build (see .dockerignore and the Containerfile's COPY lines) nor by the browser tests.
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
    return not all(any(fnmatch.fnmatchcase(p, pat) for pat in NOT_THE_SITE) and not p.startswith("tests/e2e/") for p in paths)


if __name__ == "__main__":
    print("true" if needs_site(sys.stdin.read().splitlines()) else "false")
