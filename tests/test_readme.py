"""The README opens with the live site (the product: no account, nothing to install) and, once it is uploaded, the
walkthrough video: a github.com upload (user-attachments) on a line of its own, which GitHub shows as a player (it
strips <video> tags). A placeholder address is never published. The screenshots stay below, every image a small file
in the repository."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
IMAGES = re.findall(r"!\[([^\]]+)\]\(([^)]+)\)", README)
FIRST_SECTION = README.index("## What learning here looks like")
SITE = "https://roottorun.aminelg.com"


def test_the_live_site_comes_first():
    at = README.index(f"]({SITE})")
    assert at < FIRST_SECTION and "Try it live" in README[:FIRST_SECTION]
    assert f"({SITE})" in README[README.index("## Getting started"):]


def test_the_walkthrough_is_a_real_upload_or_absent():
    assert "WALKTHROUGH-VIDEO" not in README  # the placeholder used before the upload
    assert "<video" not in README and "<iframe" not in README
    uploads = re.findall(r"https://github\.com/user-attachments/assets/\S+", README)
    for u in uploads:
        assert re.fullmatch(r"https://github\.com/user-attachments/assets/[0-9a-f-]{36}", u), u
        line = next(l for l in README.splitlines() if u in l)
        assert line.strip() == u, line  # alone on its line: GitHub shows it as a player
        assert README.index(u) < FIRST_SECTION


def test_the_screenshots_stay_and_every_image_is_small():
    shown = [src for _, src in IMAGES]
    for name in ("home", "lesson", "try", "explore-dark", "incident-dark"):
        assert f"docs/screenshots/{name}.png" in shown
    for src in shown:
        assert (ROOT / src).stat().st_size < 400_000, src  # no large media in the source repository
