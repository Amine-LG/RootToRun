"""Check an exported static site: every internal link and asset resolves to a file, and nothing that must not be
published is in it (source maps, dotfiles, server or build files).

    .venv/bin/python scripts/check_site.py frontend/dist

An internal address resolves when the file exists or when <address>/index.html exists, as the nginx configuration
(deploy/nginx/nginx.conf) and most static hosts serve it. Links are read from the pages (href and src attributes),
the stylesheets (url(...)) and the lesson data (Markdown links). Exit status 1 on any problem.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ATTR = re.compile(r"""(?:href|src)\s*=\s*["']([^"']+)["']""")
CSS_URL = re.compile(r"""url\(\s*["']?([^"')]+)["']?\s*\)""")
MD_LINK = re.compile(r"\]\((/[^)\s]*)\)")
# never in a public site: source maps, dotfiles, Python, environment and key files
FORBIDDEN = re.compile(r"(\.map|\.py|\.pyc|\.env|\.pem|\.key|\.kubeconfig|\.sqlite3?|\.db)$|(^|/)\.")


def internal(target: str) -> str | None:
    """The path of an internal address, without query or #anchor; None for external, data: and anchor-only links."""
    if not target.startswith("/") or target.startswith("//"):
        return None
    return re.split(r"[?#]", target, maxsplit=1)[0] or "/"


def resolves(root: Path, path: str) -> bool:
    f = root / path.lstrip("/")
    return path == "/" or f.is_file() or (f / "index.html").is_file()


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def check(root: Path) -> tuple[list[str], dict[str, int]]:
    problems, counts = [], {"files": 0, "links": 0}
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(root).as_posix()
        counts["files"] += 1
        if FORBIDDEN.search(rel):
            problems.append(f"{rel}: must not be published")
        if f.suffix == ".html":
            targets = ATTR.findall(f.read_text(encoding="utf-8", errors="replace"))
        elif f.suffix == ".css":
            targets = CSS_URL.findall(f.read_text(encoding="utf-8", errors="replace"))
        elif f.suffix == ".json" and rel.startswith("data/"):
            targets = [m for s in strings(json.loads(f.read_text(encoding="utf-8"))) for m in MD_LINK.findall(s)]
        else:
            continue
        for t in targets:
            path = internal(t)
            if path is None:
                continue
            counts["links"] += 1
            if not resolves(root, path):
                problems.append(f"{rel}: broken internal link {path}")
    for required in ("index.html", "404.html", "version.json", "licenses.txt", "data/meta.json"):
        if not (root / required).is_file():
            problems.append(f"{required}: missing")
    return problems, counts


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = Path(sys.argv[1])
    problems, counts = check(root)
    for p in problems[:200]:
        print("  " + p)
    print(f"{len(problems)} problem(s): {counts['links']} internal links in {counts['files']} files")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
