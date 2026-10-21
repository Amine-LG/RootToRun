"""The repository checks out and works the same on Linux, macOS and Windows (docs/WINDOWS.md): file names every
file system accepts, LF line endings everywhere, no symbolic links, and executable shell scripts."""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WINDOWS_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.I)


def tracked(*args):
    r = subprocess.run(["git", "ls-files", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        pytest.skip("not a git checkout")
    return [line for line in r.stdout.splitlines() if line]


def test_every_path_is_valid_on_windows_and_macos():
    paths = tracked()
    bad = [p for p in paths for part in p.split("/")
           if WINDOWS_RESERVED.match(part) or re.search(r'[<>:"|?*\\\x00-\x1f]', part) or part.endswith((" ", "."))]
    assert bad == []
    folded = {}
    for p in paths:
        folded.setdefault(p.lower(), []).append(p)
    assert [v for v in folded.values() if len(v) > 1] == []  # names that differ only by case collide there
    assert max(len(p) for p in paths) <= 160  # leaves room for the checkout folder under Windows' 260-character limit


def test_no_symbolic_links_and_shell_scripts_stay_executable():
    entries = [line.split(maxsplit=3) for line in tracked("-s")]
    assert [e[3] for e in entries if e[0] == "120000"] == []  # a link is checked out as a text file on Windows
    scripts = [e for e in entries if e[3].endswith(".sh")]
    assert scripts and [e[3] for e in scripts if e[0] != "100755"] == []


def test_text_files_are_lf_in_the_repository_and_in_this_checkout():
    assert "* text=auto eol=lf" in (ROOT / ".gitattributes").read_text(encoding="utf-8")
    rows = [line.split(maxsplit=3) for line in tracked("--eol")]
    # i/: the index, w/: this checkout (on Windows too, thanks to .gitattributes); -text: binary files
    assert [r[3] for r in rows if r[0] not in ("i/lf", "i/-text", "i/none")] == []
    assert [r[3] for r in rows if r[1] == "w/crlf" or r[1] == "w/mixed"] == []
