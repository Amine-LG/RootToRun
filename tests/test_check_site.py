"""scripts/check_site.py finds broken internal links and files that must not be published; the export's nginx
redirect map lists every old address exactly once."""
import json
import subprocess
import sys

from academy import config, urls

SCRIPT = config.ROOT / "scripts" / "check_site.py"


def site(tmp_path, pages: dict[str, str]):
    for name, text in pages.items():
        f = tmp_path / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    for required in ("404.html", "version.json", "licenses.txt"):
        (tmp_path / required).write_text("x", encoding="utf-8")
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "meta.json").write_text("{}", encoding="utf-8")
    return subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True, encoding="utf-8")


def test_a_complete_site_passes(tmp_path):
    r = site(tmp_path, {
        "index.html": '<a href="/learn/linux?x=1#top">x</a><script src="/assets/app.js"></script><a href="https://example.org/">e</a>',
        "learn/linux/index.html": '<link href="/assets/app.css">',
        "assets/app.js": "", "assets/app.css": "a{background:url(/assets/i.svg)}", "assets/i.svg": "<svg/>",
        "data/en/lessons/a.json": json.dumps({"body": "see [this](/learn/linux#part)"}),
    })
    assert r.returncode == 0, r.stdout
    assert "0 problem(s)" in r.stdout


def test_broken_links_and_assets_are_reported(tmp_path):
    r = site(tmp_path, {
        "index.html": '<a href="/learn/missing">x</a><script src="/assets/gone.js"></script>',
        "assets/app.css": "a{background:url('/assets/none.png')}",
        "data/en/lessons/a.json": json.dumps({"body": "[x](/lesson/nowhere)"}),
    })
    assert r.returncode == 1
    for path in ("/learn/missing", "/assets/gone.js", "/assets/none.png", "/lesson/nowhere"):
        assert f"broken internal link {path}" in r.stdout


def test_files_that_must_not_be_published_are_reported(tmp_path):
    r = site(tmp_path, {"index.html": "", "assets/app.js.map": "{}", ".env": "", "backend/main.py": ""})
    assert r.returncode == 1
    for name in ("assets/app.js.map", ".env", "backend/main.py"):
        assert f"{name}: must not be published" in r.stdout


def test_redirect_map(tmp_path):
    out = tmp_path / "redirects.map"
    # in a separate process: importing the export script changes environment variables for the rest of the session
    code = "import sys; sys.path.insert(0, sys.argv[1]); import export_static; export_static.write_redirect_map(__import__('pathlib').Path(sys.argv[2]))"
    subprocess.run([sys.executable, "-c", code, str(config.ROOT / "scripts"), str(out)], check=True)
    rows = [line.rstrip(";").split(" ") for line in out.read_text(encoding="utf-8").splitlines()]
    assert dict(rows) == urls.redirects() and len(rows) == len(urls.redirects())
    assert all(old.startswith("/") and new.startswith("/") for old, new in rows)
