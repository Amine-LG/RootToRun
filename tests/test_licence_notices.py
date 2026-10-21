"""Every licence notice draws the same line: the project's own code and course text are licensed by the project; the
console screenshots (with the Red Hat and OpenShift marks they show), third-party program output and adapted
examples keep their owners' terms and are not relicensed. The generated licence file used to grant CC BY-SA to
"other material under content/", which included the screenshots."""
import re
import subprocess
import sys

import pytest

from academy import config

ROOT = config.ROOT
NOTICES = ["content/LICENSE.md", "NOTICE", "THIRD_PARTY_NOTICES.md", "README.md", "frontend/scripts/licenses.mjs"]


def text(path: str) -> str:
    # one line per sentence is not guaranteed: compare with the wrapping removed
    return re.sub(r"['+,\s]*\n\s*['+]?\s*", " ", (ROOT / path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", NOTICES)
def test_each_notice_excludes_the_console_screenshots(path):
    t = text(path)
    assert re.search(r"screenshots of the OpenShift web console", t, re.I), path
    assert "not relicensed" in t or "not covered by" in t, path


def test_generated_licence_file_no_longer_grants_the_whole_content_directory():
    t = text("frontend/scripts/licenses.mjs")
    assert "other material under content/" not in t
    assert "Not covered by these licences, and not relicensed by the project" in t


def test_about_page_says_the_same():
    en = (ROOT / "frontend/src/i18n/en.ts").read_text(encoding="utf-8")
    lic = re.search(r"'about\.licences': '(.*)',\n", en).group(1)
    assert "screenshots of the OpenShift web console" in lic and "not relicensed" in lic
    legal = re.search(r"'about\.legal': '(.*)',\n", en).group(1)
    assert "No Red Hat training material is used" not in legal
    assert "do not reproduce Red Hat training courses" in legal


def test_no_public_file_makes_the_absolute_training_material_claim():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout.split()
    try:  # the export filter is a private tool: in the public repository every tracked file is public
        sys.path.insert(0, str(ROOT / "scripts"))
        from public_tree import public as published
    except ImportError:
        published = lambda path: True  # noqa: E731
    public = [f for f in files if published(f) and not f.startswith("tests/")]
    hits = [f for f in public if (ROOT / f).is_file() and "No Red Hat training material is used" in (ROOT / f).read_text(encoding="utf-8", errors="ignore")]
    assert hits == []
