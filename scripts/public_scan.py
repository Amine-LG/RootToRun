"""Refuse text that must never be published: credentials, private keys, vendor course or exam codes, certification
titles and exam-preparation phrases, development-tool references, and personal terms you list yourself.

    .venv/bin/python scripts/public_scan.py                 # every file tracked by git
    .venv/bin/python scripts/public_scan.py frontend/dist    # every file under a directory (for example the built site)

Personal terms (names, e-mail addresses, host names, home directories, addresses) are read from the environment
variable PUBLIC_TREE_PRIVATE (comma-separated), so that the list itself is never committed. A clean result is not
proof that nothing sensitive is left: it only means none of these patterns matched. Exit status 1 on any finding;
findings show the file, the line and the kind, never the matched value in full.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = "a vendor course or exam code"
CERT = "a certification title or exam-preparation phrase"
FORBIDDEN = [
    # course and exam codes: EX, DO or RH and three digits, any case, written together or with a hyphen; with a space,
    # any case for EX and RH, upper case only for DO, so that "do 100 requests" stays ordinary English. Word boundaries
    # keep hex digests, pod names and words such as DOS or "rhel" out. The patterns below are written so that their own
    # source does not match them: this file is scanned like any other.
    (re.compile(r"\b(?:ex|do|rh)-?\d{3}\b", re.I), CODE),
    (re.compile(r"\b(?:[Ee][Xx]|[Rr][Hh]|DO) \d{3}\b"), CODE),
    # other vendor course prefixes, upper case and written together only (lower case would hit hex strings)
    (re.compile(r"\b(?:CL|AD)\d{3}\b"), CODE),
    (re.compile(r"\bRHC(?:SA|E|A)s?\b", re.I), CERT),
    (re.compile(r"\bRed\s+Hat\s+Certified\b", re.I), CERT),
    (re.compile(r"\bexam\s+objectives?\b", re.I), CERT),
    (re.compile(r"\bcertification\s+exams?\b", re.I), CERT),
    (re.compile(r"\bRed\s+Hat\s+OpenShift\s+(?:Administration|Developer)\s+(?:I{1,3}|[1-3])\b", re.I), CERT),
    (re.compile(r"sha256~[A-Za-z0-9_-]{30,}"), "an OpenShift token"),
    (re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"), "a private key"),
    (re.compile(r"LS0tLS1CRUdJT[i]"), "a base64-encoded PEM block"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "a JSON Web Token"),
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})"), "a GitHub token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "a cloud access key"),
    (re.compile(r"(?:client-key-data|client-certificate-data):\s*[A-Za-z0-9+/=]{40,}"), "kubeconfig credentials"),
    (re.compile(r"\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}"), "a bcrypt password hash"),
    (re.compile(r"\b[A-Za-z0-9]{5}-[A-Za-z0-9]{5}-[A-Za-z0-9]{5}-[A-Za-z0-9]{5}\b"), "an OpenShift Local style password"),
    (re.compile(r"/home/(?!(?:learner|core|deploy|ops|alice|user|<)\b)[a-z_][a-z0-9_-]*"), "a home directory"),
    (re.compile(r"(?:/Users/|C:\\\\Users\\\\)[A-Za-z]"), "a home directory"),
    # names of the coding assistants and their sessions belong to private development notes; the public credit names
    # only the companies whose models were used (README, About page)
    (re.compile(r"\b(?:Cl[a]ude|Co[d]ex)\b", re.I), "a development-tool reference"),
]
TEXT = {".md", ".yaml", ".yml", ".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".css", ".html", ".txt", ".sh", ".toml",
        ".cfg", ".ini", ".conf", ".tpl", ".xml", ".svg", ".env", ""}
SKIP = ("frontend/src/lib/climodel.json", "frontend/package-lock.json")


def shown(value: str) -> str:
    """The start of a match, enough to find it in the file but never the whole value (at most six characters)."""
    return value[:min(6, max(1, len(value) // 2))]


def scan(root: Path, files: list[str]) -> list[str]:
    private = [p.strip() for p in os.environ.get("PUBLIC_TREE_PRIVATE", "").split(",") if p.strip()]
    found = []
    for f in files:
        p = root / f
        if f.startswith(SKIP) or p.suffix not in TEXT or p.is_symlink() or not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for rx, what in FORBIDDEN:
            for m in rx.finditer(text):
                found.append(f"{f}:{text.count(chr(10), 0, m.start()) + 1}: {what}: {shown(m.group(0))}…")
        for word in private:
            for m in re.finditer(re.escape(word), text, re.I):
                found.append(f"{f}:{text.count(chr(10), 0, m.start()) + 1}: a private term")
    return found


def tracked(root: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return [f for f in out.split("\n") if f]


def main() -> int:
    if len(sys.argv) > 1:
        root = Path(sys.argv[1]).resolve()
        files = [str(p.relative_to(root)) for p in sorted(root.rglob("*")) if p.is_file()]
    else:
        root, files = ROOT, tracked(ROOT)
    problems = scan(root, files)
    for p in problems:
        print("  " + p)
    print(f"{len(problems)} problem(s) in {len(files)} files")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
