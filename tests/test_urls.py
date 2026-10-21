"""Readable public addresses (backend/academy/urls.py): stable stored slugs, no collisions, every old address and every
link written in content leads to a current page, and the static export writes every page and every redirect."""
import html
import os
import re
import shutil
import subprocess
import sys

import pytest
import yaml
from fastapi.testclient import TestClient

from academy import config, curriculum, labs, main, urls

CUR = curriculum.load("en")
LABS = labs.load("en")
TABLE = urls.table()
MOVED = urls.redirects()
ALL = [p for sec in TABLE.values() for p in sec.values()]


def test_every_track_lesson_and_lab_has_a_stored_unique_slug():
    stored = urls.stored()
    assert set(stored["tracks"]) >= set(CUR["tracks"])
    assert set(stored["lessons"]) >= set(CUR["lessons"])
    assert set(stored["labs"]) >= set(LABS)
    for sec in urls.SECTIONS:
        slugs = list(stored[sec].values())
        assert len(slugs) == len(set(slugs)), f"{sec}: duplicate slugs"
        assert all(urls.SLUG.match(s) for s in slugs), sec
    assert urls.problems() == []
    r = subprocess.run([sys.executable, str(config.ROOT / "scripts/slugs.py"), "--check"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_address_scheme():
    assert TABLE["tracks"]["start"] == "/learn/kubernetes"
    assert TABLE["tracks"]["admin1"] == "/learn/application-operations"
    assert TABLE["tracks"]["admin2"] == "/learn/platform-administration"
    assert TABLE["tracks"]["practice"] == "/learn/practice"  # unchanged: the nav and old links use it
    assert TABLE["lessons"]["n.htpasswd-users"] == "/learn/platform-administration/manage-local-users"
    assert TABLE["lessons"]["lx.first-steps"] == "/learn/linux/your-first-minutes-in-a-shell"
    assert TABLE["labs"]["inc.dns-typo"] == "/incidents/could-not-resolve-host"
    assert TABLE["diagnostics"]["admin1"] == "/diagnostic/application-operations"
    track_of = {m: t for t in CUR["tracks"].values() for m in t.modules}
    for lid, l in CUR["lessons"].items():  # every lesson sits under its own track's address
        assert TABLE["lessons"][lid] == f"{TABLE['tracks'][track_of[l.module].id]}/{urls.stored()['lessons'][lid]}"
    for lid, lab in LABS.items():
        assert TABLE["labs"][lid].startswith({"lab": "/labs/", "incident": "/incidents/", "challenge": "/challenges/"}[lab.kind])


def test_no_address_collides_with_another_page_or_an_old_address():
    assert len(ALL) == len(set(ALL)), "two pages share an address"
    assert not set(ALL) & set(MOVED), "a current address is also an old one"
    # the app's other pages (App.tsx) and the export's fixed pages never coincide with an item's address
    app = (config.ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    top = set(re.findall(r"a === '([a-z]+)'", app))
    assert {"learn", "labs", "incidents", "diagnostic", "challenges"} <= top
    fixed = {f"/{x}" for x in top}
    assert not set(ALL) & fixed
    for p in ALL:
        assert re.fullmatch(r"/(learn|labs|incidents|challenges|diagnostic)(/[a-z0-9]+(-[a-z0-9]+)*){1,2}", p), p
    # a track's slug is never another track's id: /learn/<id> is that track's old address
    for tid, p in TABLE["tracks"].items():
        assert p.rsplit("/", 1)[1] == tid or p.rsplit("/", 1)[1] not in CUR["tracks"], tid


def test_old_addresses_lead_to_the_current_one_with_query_and_anchor():
    assert MOVED["/lesson/n.htpasswd-users"] == "/learn/platform-administration/manage-local-users"
    assert urls.canonical("/lesson/n.htpasswd-users#idp") == "/learn/platform-administration/manage-local-users#idp"
    assert urls.canonical("/lesson/o1.cli/?a=checks#x") == "/learn/application-operations/working-with-the-oc-cli?a=checks#x"
    assert urls.canonical("/lab/inc.service-selector-503?stage=investigate") == "/incidents/route-returns-503-pods-are-healthy?stage=investigate"
    assert urls.canonical("/lab/ch.ship-web-app") == "/challenges/ship-a-web-app"
    assert urls.canonical("/learn/admin1") == "/learn/application-operations"
    assert urls.canonical("/course/start") == "/learn/kubernetes"
    assert urls.canonical("/course") == "/learn"
    assert urls.canonical("/diagnostic/admin2") == "/diagnostic/platform-administration"
    assert urls.canonical("/challenges") == "/challenges"  # Practice lists the challenges itself
    assert urls.canonical("/learn/linux") == "/learn/linux"  # slug == id: not a redirect
    assert urls.canonical("/lesson/does-not-exist") == "/lesson/does-not-exist"
    for lid in CUR["lessons"]:
        assert MOVED[f"/lesson/{lid}"] == TABLE["lessons"][lid]
    for lid in LABS:
        assert MOVED[f"/lab/{lid}"] == TABLE["labs"][lid]


def test_every_link_written_in_content_resolves_to_a_current_address():
    """Content keeps writing /lesson/<id> and /lab/<id> (ids are stable); each one must name a page with an address."""
    blobs = {f"lesson {k}": v.model_dump_json() for k, v in CUR["lessons"].items()}
    blobs |= {f"lab {k}": v.model_dump_json() for k, v in LABS.items()}
    blobs |= {f"runbook {k}": v.model_dump_json() for k, v in CUR["runbooks"].items()}
    blobs |= {f"case {k}": v.model_dump_json() for k, v in CUR["cases"].items()}
    current = set(ALL)
    seen, bad = 0, []
    for where, text in blobs.items():
        for href in re.findall(r"\]\((/(?:lesson|lab)/[^)\s\"]*)\)", text):
            seen += 1
            new = urls.canonical(href)
            if re.split(r"[?#]", new)[0] not in current:
                bad.append(f"{where}: {href}")
    assert seen > 100 and not bad, bad
    assert "](/learn/platform-administration/manage-local-users)" in urls.rewrite("[Manage local users](/lesson/n.htpasswd-users)")


def test_the_api_gives_every_item_its_address():
    cur = TestClient(main.app).get("/api/curriculum").json()
    assert {t["id"]: t["path"] for t in cur["tracks"]} == TABLE["tracks"]
    assert {k: v["path"] for k, v in cur["lessons"].items()} == TABLE["lessons"]
    assert {k: v["path"] for k, v in cur["labs"].items()} == TABLE["labs"]
    assert all(d["path"] == TABLE["diagnostics"][d["track"]] for d in cur["diagnostics"].values())


def test_the_server_serves_the_app_at_new_and_old_addresses(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html><title>app</title><div id=\"root\"></div>", encoding="utf-8")
    monkeypatch.setattr(config, "DIST_DIR", tmp_path)
    client = TestClient(main.app)
    for path in ["/learn/platform-administration/manage-local-users", "/incidents/could-not-resolve-host", "/challenges/ship-a-web-app",
                 "/diagnostic/application-operations", "/lesson/n.htpasswd-users", "/lab/inc.dns-typo"]:
        r = client.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html"), path


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    out = tmp_path_factory.mktemp("urls-export")
    (out / "index.html").write_text('<html><head><title>T</title></head><body><div id="root"></div><script type="module" src="/assets/app.js"></script></body></html>', encoding="utf-8")
    r = subprocess.run([sys.executable, str(config.ROOT / "scripts/export_static.py"), "--out", str(out), "--site-url", "https://lab.example"],
                       capture_output=True, text=True, encoding="utf-8", env={**os.environ, "ACADEMY_CLUSTER": "off"})
    assert r.returncode == 0, r.stderr
    return out


def test_the_static_export_writes_every_current_address(exported):
    for p in ALL:
        page = exported / p.lstrip("/") / "index.html"
        assert page.is_file(), p
        assert "http-equiv=\"refresh\"" not in page.read_text(encoding="utf-8"), p
    sitemap = (exported / "sitemap.xml").read_text(encoding="utf-8")
    assert all(f"<loc>https://lab.example{p}</loc>" in sitemap for p in ALL)
    assert "/lesson/" not in sitemap and "/lab/" not in sitemap and "/course" not in sitemap  # old addresses are not listed
    # pre-rendered pages link with current addresses, including links written in content as /lesson/<id>
    hrefs = set()
    for p in ALL:
        hrefs |= set(re.findall(r'href="([^"]+)"', (exported / p.lstrip("/") / "index.html").read_text(encoding="utf-8")))
    assert not [h for h in hrefs if re.match(r"/(lesson|lab)/", h)]
    assert "/learn/application-operations/deploying-exposing-and-scaling-applications" in hrefs  # written as /lesson/o1.deploy-apps


def test_the_static_export_writes_a_redirect_at_every_old_address(exported):
    assert len(MOVED) > 150
    for old, new in MOVED.items():
        page = exported / old.lstrip("/") / "index.html"
        assert page.is_file(), old
        text = page.read_text(encoding="utf-8")
        assert f'<link rel="canonical" href="https://lab.example{new}" />' in text, old
        assert f'<noscript><meta http-equiv="refresh" content="0; url={html.escape(new)}" /></noscript>' in text, old
        assert '<script type="module" src="/assets/app.js">' in text  # the app opens and keeps the query and #anchor
    old_page = (exported / "lesson/n.htpasswd-users/index.html").read_text(encoding="utf-8")
    assert "<title>Manage local users · " in old_page


def test_the_generator_adds_missing_slugs_and_never_changes_one(tmp_path):
    content = tmp_path / "content"
    shutil.copytree(config.CONTENT_ROOT, content, ignore=shutil.ignore_patterns("recordings"))
    f = content / "en" / "urls.yaml"
    data = yaml.safe_load(f.read_text(encoding="utf-8"))
    del data["lessons"]["n.htpasswd-users"]  # a new lesson, as far as the file knows
    data["lessons"]["o1.cli"] = "the-oc-cli"  # a slug edited by hand
    header = "# my header\n"
    f.write_text(header + yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    # a renamed lesson keeps its address
    lesson_file = next(p for p in (content / "en" / "lessons").glob("*.yaml") if "- id: lx.first-steps\n" in p.read_text(encoding="utf-8"))
    renamed, n = re.subn(r'(- id: lx\.first-steps\n\s+title: )"[^"\n]*"', r'\1"A completely new title"', lesson_file.read_text(encoding="utf-8"), count=1)
    assert n == 1
    lesson_file.write_text(renamed, encoding="utf-8")
    env = {**os.environ, "ACADEMY_CONTENT_DIR": str(content), "ACADEMY_CLUSTER": "off"}
    check = subprocess.run([sys.executable, str(config.ROOT / "scripts/slugs.py"), "--check"], capture_output=True, text=True, encoding="utf-8", env=env)
    assert check.returncode == 1 and "n.htpasswd-users has no stored slug" in check.stdout
    r = subprocess.run([sys.executable, str(config.ROOT / "scripts/slugs.py")], capture_output=True, text=True, encoding="utf-8", env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    after = yaml.safe_load(f.read_text(encoding="utf-8"))
    assert after["lessons"]["n.htpasswd-users"] == "manage-local-users"
    assert after["lessons"]["o1.cli"] == "the-oc-cli"
    assert after["lessons"]["lx.first-steps"] == "your-first-minutes-in-a-shell"
    assert list(after["lessons"])[:-1] == list(data["lessons"])  # existing entries keep their order; new ones come last
    assert f.read_text(encoding="utf-8").startswith(header)
    again = subprocess.run([sys.executable, str(config.ROOT / "scripts/slugs.py")], capture_output=True, text=True, encoding="utf-8", env=env)
    assert again.returncode == 0 and "every track, lesson and lab has a slug" in again.stdout


def test_slugify():
    assert urls.slugify("Manage local users") == "manage-local-users"
    assert urls.slugify("Did it work? Exit status, && and ||") == "did-it-work-exit-status-and-and-or"
    assert urls.slugify("403 Forbidden from the API") == "403-forbidden-from-the-api"
    assert urls.slugify("Équipes & accès") == "equipes-and-acces"
    long = urls.slugify("What a container changed, and moving images without a registry")
    assert long == "what-a-container-changed-and-moving-images" and len(long) <= 60


def test_pre_rendered_lessons_carry_their_teaching_but_no_answers(exported):
    """Without JavaScript (search engines, link previews) a lesson page shows what the lesson teaches and shows, and
    each demonstration shows the recording the app shows for it."""
    page = (exported / "learn/linux/your-first-minutes-in-a-shell/index.html").read_text(encoding="utf-8")
    assert "<h2>A prompt and nothing else</h2>" in page
    services = (exported / TABLE["lessons"]["d.services-dns"].lstrip("/") / "index.html").read_text(encoding="utf-8")
    assert "<pre><code>apiVersion: v1\nkind: Service\n" in services  # a manifest shown in the lesson
    checked = 0
    for lid, lesson in curriculum.load("en")["lessons"].items():
        text = (exported / TABLE["lessons"][lid].lstrip("/") / "index.html").read_bytes().decode()  # outputs keep \r
        entries: dict[str, list] = {}
        for e in (main.get_lesson(lid, "en").get("recording") or {}).get("entries", []):
            entries.setdefault(e["cmd"], []).append(e)
        runs: dict[str, int] = {}
        at = 0
        for step in lesson.flow:
            if step.kind == "teach" and step.title:
                assert f"<h2>{html.escape(step.title)}</h2>" in text, (lid, step.id)
            run = getattr(step, "run", None)
            if not run:
                continue
            k = runs[run] = runs.get(run, -1) + 1  # the k-th step running this command shows the k-th run
            if step.kind != "show" or run not in entries:
                continue
            e = entries[run][min(k, len(entries[run]) - 1)]
            out = e["combined"] if e.get("combined") is not None else "\n".join(x for x in (e.get("stdout"), e.get("stderr")) if x)
            first = "\n".join(out.removesuffix("\n").split("\n")[:3])
            block = f"<pre><code>$ {html.escape(run)}" + (f"\n{html.escape(first)}" if first else "")
            at = text.find(block, at)  # in flow order, so outputs swapped between two steps are caught
            assert at >= 0, (lid, step.id)
            at += len(block)
            checked += 1
    assert checked > 900
    old_password = (exported / TABLE["lessons"]["n.htpasswd-users"].lstrip("/") / "index.html").read_text(encoding="utf-8")
    assert "Login failed (401 Unauthorized)" in old_password  # the second login of the same command is refused


def test_pre_rendered_steps_never_show_hidden_fields():
    """Answers, hints and what a learner sees only after finding a command stay out of the page, also when a
    demonstration runs the same command."""
    code = """
import json, sys
sys.path.insert(0, sys.argv[1])
import export_static as x
lesson = {"flow": [
    {"kind": "show", "id": "s", "run": "oc get pods", "notice": "SHOWN-NOTICE"},
    {"kind": "try", "id": "t", "body": "SHOWN-TRY", "run": "oc get pods", "then": "HIDDEN-THEN", "hint": "HIDDEN-HINT",
     "hints": [{"match": "x", "say": "HIDDEN-SAY"}], "accept": ["HIDDEN-ACCEPT"]},
    {"kind": "ask", "id": "q", "prompt": "SHOWN-PROMPT", "choices": [{"text": "HIDDEN-CHOICE", "why": "HIDDEN-WHY"}],
     "explain": "HIDDEN-EXPLAIN"},
], "recording": {"entries": [{"cmd": "oc get pods", "combined": "FIRST-RUN\\n"}, {"cmd": "oc get pods", "combined": "SECOND-RUN\\n"}]}}
outputs = x.recorded_outputs(lesson)
print(json.dumps({"html": "".join(x.flow_html(s, outputs) for s in lesson["flow"]), "outputs": outputs}))
"""
    r = subprocess.run([sys.executable, "-c", code, str(config.ROOT / "scripts")], capture_output=True, text=True, encoding="utf-8", check=True)
    import json
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got["outputs"] == {"s": "FIRST-RUN", "t": "SECOND-RUN"}
    for shown in ("SHOWN-NOTICE", "SHOWN-TRY", "SHOWN-PROMPT", "FIRST-RUN"):
        assert shown in got["html"], shown
    assert "HIDDEN" not in got["html"] and "SECOND-RUN" not in got["html"]


def _plain(s) -> str:
    """Text as a reader sees it: markdown links, code marks and emphasis removed, white space collapsed."""
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(s))
    return re.sub(r"\s+", " ", re.sub(r"[`*_]", "", s)).strip()


def test_exported_lesson_pages_never_contain_a_hidden_answer(exported):
    """The whole page pipeline, on the real lessons: no explanation of a choice, hint, explanation, 'then' text,
    accepted command or ordering item of any step appears in a pre-rendered lesson page (the synthetic test above
    covers the step renderer only). A hidden text that the lesson also shows elsewhere (a step's body, notice, prompt
    or code, a depth section, the command reference) is not an answer and is not checked; neither is a text shorter than 25 characters."""
    hidden_keys = {"ask": ("explain",), "try": ("then", "hint"), "predict": ("explain", "then"), "reflect": ("model", "answer")}
    sources = {raw["id"]: raw for f in sorted((config.ROOT / "content/en/lessons").glob("*.yaml")) for raw in yaml.safe_load(f.read_text(encoding="utf-8"))}
    checked = 0
    for lid, path in TABLE["lessons"].items():
        source = sources[lid]
        page = (exported / path.lstrip("/") / "index.html").read_text(encoding="utf-8")
        text = _plain(html.unescape(re.sub(r"<[^>]+>", " ", page)))
        visible, hidden = [], []

        def strings(x):
            if isinstance(x, str):
                yield x
            elif isinstance(x, dict):
                for v in x.values():
                    yield from strings(v)
            elif isinstance(x, list):
                for v in x:
                    yield from strings(v)
        # what the lesson shows outside its steps (depth sections, command references, objective): visible by design
        visible += [_plain(t) for k, v in source.items() if k not in ("flow", "review") for t in strings(v)]
        for step in source.get("flow", []):
            kind = step.get("kind")
            for key in ("body", "notice", "prompt", "title", "run", "text", "code"):
                if isinstance(step.get(key), str) and key not in hidden_keys.get(kind, ()):
                    visible.append(_plain(step[key]))
            hidden += [(step.get("id"), _plain(step[key])) for key in hidden_keys.get(kind, ()) if isinstance(step.get(key), str)]
            hidden += [(step.get("id"), _plain(c["why"])) for c in step.get("choices") or [] if isinstance(c, dict) and c.get("why")]
            hidden += [(step.get("id"), _plain(h["say"])) for h in step.get("hints") or [] if isinstance(h, dict) and h.get("say")]
            if kind == "try":  # the commands a learner must find
                hidden += [(step.get("id"), _plain(a)) for a in step.get("accept") or [] if isinstance(a, str)]
            if kind == "order":  # the items, whose order is the answer
                hidden += [(step.get("id"), _plain(i)) for i in step.get("items") or [] if isinstance(i, str)]
        for sid, t in hidden:
            if len(t) < 25 or any(t in v for v in visible):
                continue  # too short to be distinctive, or shown on purpose elsewhere in the lesson
            checked += 1
            assert t not in text, (lid, sid, t[:80])
    assert checked > 3000
