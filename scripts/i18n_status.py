"""Translation status for every language: interface strings and course content.

    .venv/bin/python scripts/i18n_status.py                 # all languages
    .venv/bin/python scripts/i18n_status.py --stamp lessons lx.shell-basics   # the `source:` value for a translation

Content in a language other than English overlays the English items it translates (content/<lang>/...); a
translation records the fingerprint of the English item it was made from as `source:`. When the English item
changes, the translation is reported as stale. Machine translations must not be published as reviewed.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, "backend")
from academy import config, curriculum, labs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KINDS = ("tracks", "modules", "routes", "concepts", "lessons", "diagnostics", "cases", "runbooks")


def ui_keys(path: Path) -> set[str]:
    return set(re.findall(r"^\s*['\"]([a-z][\w.-]*)['\"]\s*:", path.read_text(encoding="utf-8"), re.M)) if path.exists() else set()


if "--stamp" in sys.argv:
    kind, ident = sys.argv[sys.argv.index("--stamp") + 1: sys.argv.index("--stamp") + 3]
    print(curriculum.source_hash(curriculum.load("en")[kind][ident]))
    sys.exit(0)

en_ui = ui_keys(ROOT / "frontend/src/i18n/en.ts")
en = curriculum.load("en")
print(f"English: {len(en_ui)} interface strings, " + ", ".join(f"{len(en[k])} {k}" for k in KINDS) + f", {len(labs.load('en'))} labs")
for lang in config.LANGS:
    if lang == "en":
        continue
    ui = ui_keys(ROOT / f"frontend/src/i18n/{lang}.ts")
    d = curriculum.load(lang)
    st = d.get("translation", {})
    print(f"\n{lang}: interface {len(ui & en_ui)}/{len(en_ui)} strings translated, {len(ui - en_ui)} unknown keys")
    for k in KINDS:
        s = st.get(k, {})
        tr = sum(v == "translated" for v in s.values())
        stale = sorted(i for i, v in s.items() if v == "stale")
        print(f"  {k:12} {tr}/{len(en[k])} translated" + (f", stale: {', '.join(stale)}" if stale else ""))
    problems = [e for e in d["errors"] + labs.errors(lang) if e.startswith(f"{lang}/") or f"{lang}/" in e]
    for p in problems:
        print(f"  ! {p}")
if len(config.LANGS) == 1:
    print("\nNo other language yet. Add one with content/<lang>/ and frontend/src/i18n/<lang>.ts.")
