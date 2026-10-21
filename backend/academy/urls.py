"""Public addresses (URLs) of the course's pages, built from stored, human-readable slugs.

    /learn/<track>                  a track (its course page)            /learn/platform-administration
    /learn/<track>/<lesson>         a lesson                             /learn/platform-administration/manage-local-users
    /diagnostic/<track>             a track's diagnostic                 /diagnostic/application-operations
    /labs/<lab>                     a guided lab                         /labs/deploy-expose-and-scale-an-application
    /incidents/<incident>           an incident                          /incidents/route-returns-503-pods-are-healthy
    /challenges/<challenge>         a challenge                          /challenges/ship-a-web-app

The slugs are stored in content/en/urls.yaml, one per track, lesson and lab id. scripts/slugs.py adds the missing
ones from titles and never changes an existing one, so an address stays the same when a title changes. Internal ids
(progress, recordings, links written in content) never change and never appear in an address. Addresses are the same
in every language.

Old addresses keep working (redirects()): /lesson/<id>, /lab/<id>, /learn/<track id>, /course[/<track id>] and
/diagnostic/<track id> lead to the current address with the same query and #anchor. The app replaces the history
entry; the static export writes a page at each old address. Links written in content as /lesson/<id> or /lab/<id>
are rewritten where they are rendered (frontend/src/lib/md.tsx, and rewrite() here for the static export).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import yaml

from . import config, curriculum, labs

FILE_NAME = "urls.yaml"
SECTIONS = ("tracks", "lessons", "labs")
LAB_SECTION = {"lab": "labs", "incident": "incidents", "challenge": "challenges"}  # lab kind -> first path segment
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# words a shortened slug should not end with ("...-without-a")
_DANGLING = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "the", "to", "with", "without"}
_cache: dict = {}


def file() -> Path:
    """The slug file. English is the source language; translations share its addresses."""
    return config.CONTENT_ROOT / "en" / FILE_NAME


def slugify(title: str, limit: int = 60) -> str:
    """A slug from a title: lower-case ASCII words joined by hyphens, at most `limit` characters, cut between words."""
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    t = t.replace("&&", " and ").replace("||", " or ").replace("&", " and ")
    words = [w for w in re.split(r"[^a-z0-9]+", t) if w]
    cut = False
    while len("-".join(words)) > limit and len(words) > 1:
        words.pop()
        cut = True
    while cut and len(words) > 1 and words[-1] in _DANGLING:
        words.pop()
    return "-".join(words)[:limit].strip("-") or "page"


def stored() -> dict[str, dict[str, str]]:
    """The slugs in content/en/urls.yaml: {"tracks": {id: slug}, "lessons": {...}, "labs": {...}}."""
    f = file()
    sig = (str(f), f.stat().st_mtime if f.exists() else 0)
    if _cache.get("stored", (None,))[0] == sig:
        return _cache["stored"][1]
    raw = (yaml.safe_load(f.read_text(encoding="utf-8")) if f.exists() else None) or {}
    raw = raw if isinstance(raw, dict) else {}  # a malformed file: no stored slugs (problems() lists every id)
    data = {s: {str(k): str(v) for k, v in (raw.get(s) or {}).items()} if isinstance(raw.get(s) or {}, dict) else {} for s in SECTIONS}
    _cache["stored"] = (sig, data)
    return data


def _content():
    return curriculum.load("en"), labs.load("en")


def slugs() -> dict[str, dict[str, str]]:
    """The slug of every track, lesson and lab that exists: the stored one, or (until scripts/slugs.py stores one, which
    problems() asks for) one from its title."""
    cur, all_labs = _content()
    s = stored()
    return {
        "tracks": {k: s["tracks"].get(k) or slugify(t.title) for k, t in cur["tracks"].items()},
        "lessons": {k: s["lessons"].get(k) or slugify(l.title) for k, l in cur["lessons"].items()},
        "labs": {k: s["labs"].get(k) or slugify(l.title) for k, l in all_labs.items()},
    }


def _build() -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    cur, all_labs = _content()
    stored()
    sig = _cache["stored"][0]
    c = _cache.get("built")
    if c and c[0] is cur and c[1] is all_labs and c[2] == sig:  # the same loaded content: same addresses
        return c[3], c[4]
    sl = slugs()
    track_of = {m: tid for tid, t in cur["tracks"].items() for m in t.modules}
    tracks = {tid: f"/learn/{slug}" for tid, slug in sl["tracks"].items()}
    lessons = {lid: f"{tracks[track_of[l.module]]}/{sl['lessons'][lid]}" if l.module in track_of else f"/lesson/{lid}"
               for lid, l in cur["lessons"].items()}
    lab_paths = {lid: f"/{LAB_SECTION[lab.kind]}/{sl['labs'][lid]}" for lid, lab in all_labs.items()}
    diagnostics = {tid: f"/diagnostic/{sl['tracks'][tid]}" for tid in cur["diagnostics"] if tid in sl["tracks"]}
    paths = {"tracks": tracks, "lessons": lessons, "labs": lab_paths, "diagnostics": diagnostics}
    old: dict[str, str] = {"/course": "/learn"}
    old |= {f"/lesson/{lid}": p for lid, p in lessons.items()}
    old |= {f"/lab/{lid}": p for lid, p in lab_paths.items()}
    for tid, p in tracks.items():
        old[f"/course/{tid}"] = p
        old[f"/learn/{tid}"] = p
    old |= {f"/diagnostic/{tid}": p for tid, p in diagnostics.items()}
    moved = {o: n for o, n in old.items() if o != n}
    _cache["built"] = (cur, all_labs, sig, paths, moved)
    return paths, moved


def table() -> dict[str, dict[str, str]]:
    """The address of everything that has a page: {"tracks"|"lessons"|"labs"|"diagnostics": {id: path}}. A lesson in no
    track (integrity() reports it) keeps its old address."""
    return _build()[0]


def redirects() -> dict[str, str]:
    """Every address that leads to another one (old path -> current path): the addresses used before readable URLs."""
    return _build()[1]


def canonical(href: str) -> str:
    """The current address for `href`, keeping its query and #anchor; anything else is returned unchanged."""
    m = re.match(r"^([^?#]*)(.*)$", href, re.S)
    path, rest = m.group(1), m.group(2)
    new = redirects().get(path.rstrip("/") or "/")
    return new + rest if new else href


_LINK = re.compile(r"(\]\()(/[^)\s]*)(\))")


def rewrite(markdown: str) -> str:
    """Markdown with its in-site link targets ([text](/lesson/<id>#part)) changed to current addresses."""
    return _LINK.sub(lambda m: m.group(1) + canonical(m.group(2)) + m.group(3), markdown or "")


def missing() -> dict[str, dict[str, str]]:
    """Ids that have no stored slug yet, with the slug scripts/slugs.py would store (unique in its section)."""
    cur, all_labs = _content()
    s = stored()
    titles = {"tracks": {k: t.title for k, t in cur["tracks"].items()},
              "lessons": {k: l.title for k, l in cur["lessons"].items()},
              "labs": {k: l.title for k, l in all_labs.items()}}
    out: dict[str, dict[str, str]] = {sec: {} for sec in SECTIONS}
    for sec in SECTIONS:
        taken = set(s[sec].values())
        for ident, title in titles[sec].items():
            if ident in s[sec]:
                continue
            # a track's slug must not be another track's id: /learn/<that id> is that track's old address
            blocked = taken | (set(titles["tracks"]) - {ident} if sec == "tracks" else set())
            base = slugify(title)
            slug, n = base, 2
            while slug in blocked:
                slug, n = f"{base}-{n}", n + 1
            taken.add(slug)
            out[sec][ident] = slug
    return out


def problems() -> list[str]:
    """What would make an address unstable, invalid or ambiguous."""
    cur, all_labs = _content()
    s = stored()
    out = []
    ids = {"tracks": set(cur["tracks"]), "lessons": set(cur["lessons"]), "labs": set(all_labs)}
    for sec in SECTIONS:
        for ident in sorted(ids[sec] - set(s[sec])):
            out.append(f"{FILE_NAME}: {sec} {ident} has no stored slug (run scripts/slugs.py)")
        for ident, slug in s[sec].items():
            if not SLUG.match(slug):
                out.append(f"{FILE_NAME}: {sec} {ident}: {slug!r} is not a slug (lower-case words joined by hyphens)")
        seen: dict[str, str] = {}
        for ident, slug in s[sec].items():
            if slug in seen:
                out.append(f"{FILE_NAME}: {sec} {ident} and {seen[slug]} share the slug {slug!r}")
            seen[slug] = ident
    for tid, slug in s["tracks"].items():
        if slug != tid and slug in ids["tracks"]:
            out.append(f"{FILE_NAME}: track {tid}: slug {slug!r} is the id of another track (its old address)")
    t = table()
    paths = [p for sec in t.values() for p in sec.values()]
    dup = sorted({p for p in paths if paths.count(p) > 1})
    out += [f"two pages share the address {p}" for p in dup]
    old = set(redirects())
    out += [f"the address {p} is also an old address that redirects" for p in sorted(old & set(paths))]
    return out
