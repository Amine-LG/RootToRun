"""The current public address of a lesson, lab, track or diagnostic (backend/academy/urls.py, from the slugs in
content/en/urls.yaml), so browser tests name pages by their stable ids and follow the address scheme."""
from urllib.parse import urlparse

from academy import urls

_T = urls.table()


def lesson_url(lid: str) -> str:
    return _T["lessons"][lid]


def lab_url(lid: str) -> str:
    return _T["labs"][lid]


def track_url(tid: str) -> str:
    return _T["tracks"][tid]


def diag_url(tid: str) -> str:
    return _T["diagnostics"][tid]


def lesson_at(url: str) -> str | None:
    """The id of the lesson a page URL shows (a trailing slash, query and #anchor are ignored), or None."""
    path = urlparse(url).path.rstrip("/")
    return next((lid for lid, p in _T["lessons"].items() if p == path), None)


def is_practice(href: str) -> bool:
    """A lab, incident or challenge address."""
    return any(href.startswith(p) for p in ("/labs/", "/incidents/", "/challenges/"))


# Groups for tests that visit every page: one test per group instead of one long test, so a failure names its part
# of the site and the groups can run in parallel. Lessons by track, labs by kind, and the diagnostics.
TRACKS = ["linux", "containers", "start", "admin1", "admin2", "platform"]
PAGE_GROUPS = TRACKS + ["lab", "incident", "challenge", "diagnostics"]


def lessons_of(cur: dict, track: str) -> list[str]:
    """The lesson ids of a track, in course order, from the site's curriculum.json."""
    modules = {m["id"]: m for m in cur["modules"]}
    track_ = next(t for t in cur["tracks"] if t["id"] == track)
    return [i for m in track_["modules"] for i in modules[m].get("lessons", []) if i in cur["lessons"]]


def pages_of(cur: dict, group: str) -> list[str]:
    """The addresses of one page group (see PAGE_GROUPS)."""
    if group in TRACKS:
        return [cur["lessons"][i]["path"] for i in lessons_of(cur, group)]
    if group == "diagnostics":
        return sorted({d["path"] for d in cur["diagnostics"].values()})
    return [x["path"] for x in cur["labs"].values() if x.get("kind") == group]
