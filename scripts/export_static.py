#!/usr/bin/env python3
"""Export the academy as a static site: frontend/dist plus data/*.json, no server and no cluster needed.

    cd frontend && npm ci && npm run build && cd ..
    .venv/bin/python scripts/export_static.py [--out frontend/dist] [--site-url https://example.org]

What it writes into the output directory:
  data/                 content and recorded outputs as JSON (the frontend reads these when /api is absent)
  <route>/index.html    one page per lesson, lab, incident, runbook, case and section, with its own title,
                        description and a readable pre-rendered version of the content (for search engines,
                        link previews and readers without JavaScript); the app replaces it when it starts.
                        Addresses are readable (/learn/<track>/<lesson>, /labs/<lab>…: backend/academy/urls.py)
  <old>/index.html      one page per old address (/lesson/<id>, /lab/<id>, /learn/<track id>…): the app opens
                        and replaces it with the current address (same query and #anchor, no extra history
                        entry); without JavaScript a refresh goes there; its canonical link names the new address
  404.html              fallback for any other path (single-page app)
  sitemap.xml, robots.txt (sitemap only when --site-url or ACADEMY_SITE_URL is given)

With --redirect-map FILE it also writes the old addresses as an nginx map (old path -> current path), outside the
site, so that a server can answer them with a permanent redirect instead of the page above (deploy/nginx/nginx.conf).

Everything exported is public course content and outputs recorded on a disposable cluster. The export refuses
to run when content has problems, and it scans the output for credentials before finishing.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["ACADEMY_AUTHORING"] = "0"  # local authoring is never exported
os.environ["ACADEMY_CLUSTER"] = "off"  # never touch a cluster while exporting

from backend.academy import config, curriculum, labs, main, media, urls  # noqa: E402

SITE_NAME = config.SITE_NAME  # the working product name: one setting (frontend: src/lib/brand.ts)
SECRET_PATTERNS = [
    re.compile(r"sha256~[A-Za-z0-9_-]{20,}"),  # OpenShift OAuth tokens
    re.compile(r"eyJhbGciOi[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),  # JWTs (ServiceAccount tokens)
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b[A-Za-z0-9]{5}-[A-Za-z0-9]{5}-[A-Za-z0-9]{5}-[A-Za-z0-9]{5}\b"),  # kubeadmin password format
]


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- tiny Markdown → HTML for the pre-rendered pages
def md_html(text: str) -> str:
    out, para, code, in_code, lst = [], [], [], False, []

    def inline(s: str) -> str:
        s = html.escape(s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![*\w])\*([^*\s][^*]*?)\*(?![*\w])", r"<em>\1</em>", s)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
        # in-site links, written in content as /lesson/<id> or /lab/<id>: to their current address
        s = re.sub(r"\[([^\]]+)\]\((/(?!/)[^)\s]*)\)", lambda m: f'<a href="{urls.canonical(m.group(2))}">{m.group(1)}</a>', s)
        return s

    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()
        if lst:
            out.append("<ul>" + "".join(f"<li>{inline(x)}</li>" for x in lst) + "</ul>")
            lst.clear()

    for line in (text or "").splitlines():
        if line.startswith("```"):
            if in_code:
                out.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
                code.clear()
            else:
                flush()
            in_code = not in_code
            continue
        if in_code:
            code.append(line)
        elif not line.strip():
            flush()
        elif re.match(r"^\s*([-*]|\d+\.)\s+", line):
            if para:
                flush()
            lst.append(re.sub(r"^\s*([-*]|\d+\.)\s+", "", line))
        elif line.startswith("|"):
            flush()
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                out.append("<p>" + " · ".join(inline(c) for c in cells) + "</p>")
        elif lst and line.startswith("  "):
            lst[-1] += " " + line.strip()
        else:
            para.append(line.strip())
    flush()
    return "\n".join(out)


def plain(text: str, n: int = 158) -> str:
    t = re.sub(r"[`*_#>|]", "", re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text or "")).strip()
    t = re.sub(r"\s+", " ", t)
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0] + "…"


def page(template: str, route: str, title: str, description: str, body: str, site_url: str | None, moved_to: str | None = None) -> str:
    """The app's HTML for `route`, with its title, description and pre-rendered body. `moved_to`: `route` is an old
    address; the canonical link names the current one, and readers without JavaScript are sent there."""
    full_title = f"{title} · {SITE_NAME}" if route != "/" else template_title(template)
    head = f"<title>{html.escape(full_title)}</title>"
    meta = (
        f'<meta name="description" content="{html.escape(description)}" />'
        f'<meta property="og:title" content="{html.escape(full_title)}" />'
        f'<meta property="og:description" content="{html.escape(description)}" />'
    )
    if site_url or moved_to:
        url = (site_url or "").rstrip("/") + (moved_to or route)
        meta += f'<link rel="canonical" href="{html.escape(url)}" /><meta property="og:url" content="{html.escape(url)}" />'
    if moved_to:
        meta += f'<noscript><meta http-equiv="refresh" content="0; url={html.escape(moved_to)}" /></noscript>'
    doc = re.sub(r"<title>.*?</title>", head, template, count=1, flags=re.S)
    doc = re.sub(r'<meta name="description"[^>]*/>\s*', "", doc, count=1)
    doc = re.sub(r'<meta property="og:(title|description)"[^>]*/>\s*', "", doc)
    doc = doc.replace("</head>", meta + "</head>", 1)
    return doc.replace('<div id="root"></div>', f'<div id="root"><main class="prerender">{body}</main></div>', 1)


def template_title(template: str) -> str:
    m = re.search(r"<title>(.*?)</title>", template, re.S)
    return html.unescape(m.group(1)) if m else SITE_NAME


def nav_links(cur) -> str:
    items = [("/", "Home"), ("/learn", "Learning paths"), ("/labs", "Labs"), ("/incidents", "Incident Center"), ("/handbook", "Operations handbook"), ("/commands", "Command reference"), ("/about", "About")]
    return "<nav>" + " · ".join(f'<a href="{h}">{html.escape(t)}</a>' for h, t in items) + "</nav>"


def routes(lang: str, studio_ids: list[str]) -> list[tuple[str, str, str, str]]:
    """(route, title, description, body html) for every public page."""
    cur = curriculum.load(lang)
    all_labs = labs.load(lang)
    at = urls.table()  # every page's address
    nav = nav_links(cur)
    out = []
    home_body = f"<h1>{html.escape(SITE_NAME)}</h1><p>{html.escape(config.SITE_DESCRIPTION)}</p>{nav}"
    out.append(("/", SITE_NAME, config.SITE_DESCRIPTION or SITE_NAME, home_body))
    course = "".join(
        f"<h2>{html.escape(tr.title)}</h2><p>{html.escape(plain(tr.summary, 400))}</p><ul>"
        + "".join(
            f'<li><a href="{at["lessons"][l]}">{html.escape(cur["lessons"][l].title)}</a></li>'
            for m in tr.modules
            for l in next((x.lessons for x in cur["modules"].values() if x.id == m), [])
            if l in cur["lessons"]
        )
        + "</ul>"
        for tr in cur["tracks"].values()
    )
    out.append(("/learn", "Learning paths", "Learning paths from containers to platform engineering: lessons, labs and incidents.", f"<h1>Learning paths</h1>{course}{nav}"))
    for tr in cur["tracks"].values():
        lessons = [l for m in tr.modules for l in next((x.lessons for x in cur["modules"].values() if x.id == m), []) if l in cur["lessons"]]
        body = f"<h1>{html.escape(tr.title)}</h1><p>{html.escape(tr.tagline or plain(tr.summary, 300))}</p><ol>" + "".join(f'<li><a href="{at["lessons"][l]}">{html.escape(cur["lessons"][l].title)}</a></li>' for l in lessons) + f"</ol>{nav}"
        out.append((at["tracks"][tr.id], tr.title, tr.tagline or plain(tr.summary), body))
    for lid, l in cur["lessons"].items():
        body = f"<h1>{html.escape(l.title)}</h1><p><strong>You will be able to:</strong> {html.escape(plain(l.objective, 600))}</p>"
        outputs = recorded_outputs(main.get_lesson(lid, lang))
        body += "".join(f"<h2>{html.escape(s.title)}</h2>{md_html(s.body)}" for s in l.sections) + "".join(flow_html(s, outputs, lid) for s in l.flow)
        body += "<h2>References</h2><ul>" + "".join(f'<li><a href="{html.escape(r.url)}">{html.escape(r.title)}</a></li>' for r in l.references) + "</ul>" + nav
        out.append((at["lessons"][lid], l.title, plain(l.objective), body))
    for lid, lab in all_labs.items():
        body = f"<h1>{html.escape(lab.title)}</h1><p>{html.escape(lab.summary)}</p>"
        if lab.kind == "incident":
            body += f"<h2>Symptom</h2>{md_html(lab.symptom)}"
        elif lab.kind == "challenge":
            body += f"<h2>Situation</h2>{md_html(lab.symptom)}<h2>Requirements</h2><ul>" + "".join(f"<li>{md_html(r)}</li>" for r in lab.requirements) + "</ul>"
        else:
            body += f"<p><strong>You will be able to:</strong> {html.escape(plain(lab.objective, 600))}</p>" + "".join(f"<h2>{html.escape(s.title)}</h2>{md_html(s.do)}" for s in lab.steps)
        out.append((at["labs"][lid], lab.title, plain(lab.summary), body + nav))
    for tid, g in cur["diagnostics"].items():
        out.append((at["diagnostics"][tid], g.title, plain(g.intro), f"<h1>{html.escape(g.title)}</h1>{md_html(g.intro)}{nav}"))
    for rid, r in cur["runbooks"].items():
        out.append((f"/runbook/{rid}", r.title, plain(r.when), f"<h1>{html.escape(r.title)}</h1>{md_html(r.when)}" + "".join(f"<h2>{html.escape(s.title)}</h2>{md_html(s.body)}" for s in r.steps) + nav))
    for cid, c in cur["cases"].items():
        out.append((f"/case/{cid}", c.title, plain(c.situation), f"<h1>{html.escape(c.title)}</h1>{md_html(c.context)}{md_html(c.situation)}{nav}"))
    sections = [
        ("/labs", "Labs", "Guided, step-by-step OpenShift labs recorded on a real cluster."),
        ("/challenges", "Challenges", "Original OpenShift challenges: a required end state and no steps, graded on a real cluster."),
        ("/incidents", "Incident Center", "Realistic OpenShift failures to investigate and repair: 503s, crash loops, denied pulls, OOM kills and more."),
        ("/review", "Review", "Spaced-repetition review of what you learned."),
        ("/terminal", "Practice terminal", "Type oc commands and get the real outputs recorded on an OpenShift cluster."),
        ("/commands", "Command reference", "Every command used in the labs, with its real output."),
        ("/studio", "Architecture studio", "Interactive models and diagrams of Kubernetes and OpenShift."),
        ("/map", "Knowledge map", "How the concepts of the course connect."),
        ("/handbook", "Operations handbook", "Runbooks and enterprise case studies."),
        ("/me", "My progress", "Your progress, stored only in your browser."),
        ("/about", "About", "How this course is built and tested, privacy, and how to use your own cluster."),
        ("/setup", "Set up your own practice", "The tools to install to practise the course's commands for real, how to check them, and when you need a cluster."),
    ]
    out += [(r, t, d, f"<h1>{html.escape(t)}</h1><p>{html.escape(d)}</p>{nav}") for r, t, d in sections]
    for sid in studio_ids:
        out.append((f"/studio/{sid}", "Explore", "Interactive models and diagrams of Kubernetes and OpenShift.", f"<h1>Explore</h1>{nav}"))
        if sid.startswith("diagram/"):  # links from before diagrams and models had separate URLs keep working
            out.append((f"/studio/{sid.split('/', 1)[1]}", "Explore", "Interactive models and diagrams of Kubernetes and OpenShift.", f"<h1>Explore</h1>{nav}"))
    return out


def recorded_outputs(lesson: dict) -> dict[str, str]:
    """The recorded output shown by each flow step that runs a command, by step id, chosen as the app chooses it
    (frontend/src/components/Flow.tsx, entryFor): the recorder keeps one entry per run, in order, so the k-th step that
    runs a command shows the k-th entry; `combined` keeps both streams in order, older recordings have them apart."""
    entries: dict[str, list[dict]] = {}
    for e in (lesson.get("recording") or {}).get("entries", []):
        entries.setdefault(e.get("cmd") or "", []).append(e)
    out, seen = {}, {}
    for step in lesson.get("flow") or []:
        cmd = step.get("run")
        if not cmd or cmd not in entries:
            continue
        k = seen.get(cmd, 0)
        seen[cmd] = k + 1
        e = entries[cmd][min(k, len(entries[cmd]) - 1)]
        text = e["combined"] if e.get("combined") is not None else "\n".join(x for x in (e.get("stdout"), e.get("stderr")) if x)
        out[step.get("id")] = text.removesuffix("\n")
    return out


def flow_html(step, outputs: dict[str, str], lesson: str = "") -> str:
    """One step of a lesson's teaching flow, for the pre-rendered page: what it teaches and shows (text, code, a
    demonstrated command with its recorded output), never the answer to a question or to a command the learner is
    asked to find. `outputs`: recorded output by step id (recorded_outputs)."""
    get = (lambda k: step.get(k)) if isinstance(step, dict) else (lambda k: getattr(step, k, None))
    out = f"<h2>{html.escape(get('title'))}</h2>" if get("title") else ""
    kind = get("kind")
    if kind in ("teach", "show", "try"):
        out += md_html(get("body") or "")
    if kind == "show":
        if get("code"):
            out += f"<pre><code>{html.escape(get('code').rstrip())}</code></pre>"
        if get("image") and lesson:  # a screenshot: the image with its words, for readers without the app
            img = get("image")
            i = media.info(lesson, img.src)
            cap = " · ".join(x for x in (get("caption"), img.captured) if x)
            out += (f'<figure><img src="{i['url']}" alt="{html.escape(img.alt)}" width="{i['width']}" height="{i['height']}" loading="lazy">'
                    f"<figcaption>{html.escape(cap)}</figcaption></figure>")
        if get("run"):
            lines = outputs.get(get("id"), "").split("\n")
            shown = "\n".join(lines[:40]) + ("\n…" if len(lines) > 40 else "")
            out += f"<pre><code>$ {html.escape(get('run'))}" + (f"\n{html.escape(shown)}" if shown else "") + "</code></pre>"
        out += md_html(get("notice") or "")
    if get("prompt"):
        out += f"<p>{html.escape(plain(get('prompt'), 600))}</p>"
    return out


def moved_pages(pages: list[tuple[str, str, str, str]]) -> list[tuple[str, str, str, str, str]]:
    """(old address, current address, title, description, body html) for every old address (urls.redirects())."""
    known = {route: (title, desc) for route, title, desc, _ in pages}
    out = []
    for old, new in sorted(urls.redirects().items()):
        title, desc = known[new]
        body = f'<h1>{html.escape(title)}</h1><p>This page has moved to <a href="{html.escape(new)}">{html.escape(new)}</a>.</p>'
        out.append((old, new, title, desc, body))
    return out


def scan_for_secrets(root: Path) -> list[str]:
    found = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in (".json", ".html", ".js", ".css", ".txt", ".xml"):
            text = p.read_text(encoding="utf-8", errors="ignore")
            for rx in SECRET_PATTERNS:
                m = rx.search(text)
                if m:
                    found.append(f"{p.relative_to(root).as_posix()}: {rx.pattern[:30]}… matched {m.group(0)[:12]}…")
    return found


def write_redirect_map(path: Path) -> None:
    """The old addresses as nginx `map` lines, sorted. Paths are slugs and ids, so they need no quoting."""
    rows = sorted(urls.redirects().items())
    bad = [old for old, new in rows if not re.fullmatch(r"/[A-Za-z0-9._/-]*", old + new)]
    if bad:
        raise SystemExit(f"addresses that cannot go in an nginx map: {bad}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{old} {new};\n" for old, new in rows), encoding="utf-8", newline="\n")


def export(out: Path, site_url: str | None) -> int:
    template_path = out / "index.html"
    if not template_path.exists():
        print(f"{template_path} not found: build the frontend first (cd frontend && npm run build)", file=sys.stderr)
        return 1
    template = template_path.read_text(encoding="utf-8")
    if "prerender" in template:  # exporting twice into the same dist: start from the app shell again
        template = re.sub(r'<div id="root">.*?</div>\s*(?=<script|</body>)', '<div id="root"></div>', template, flags=re.S)
    data = out / "data"
    shutil.rmtree(out / "media", ignore_errors=True)  # a screenshot no longer referenced must not stay published
    write(data / "meta.json", {k: v for k, v in {**main.meta(), "mode": "static", "authoring": False}.items()
                               if k not in ("accounts", "account_provider")})
    n = 0
    pages = 0
    moved = 0
    listed = []
    for lang in config.LANGS:
        d = data / lang
        problems = labs.errors(lang) + curriculum.load(lang)["errors"] + curriculum.integrity(set(labs.load(lang)), lang) + urls.problems()
        if problems:
            print("content problems:\n  " + "\n  ".join(problems), file=sys.stderr)
            return 1
        write(d / "curriculum.json", main.get_curriculum(lang))
        write(d / "commands.json", main.command_reference(lang))
        write(d / "cards.json", main.review_cards(lang))
        for lid, l in curriculum.load(lang)["lessons"].items():
            write(d / "lessons" / f"{lid}.json", main.get_lesson(lid, lang))
            for img in media.images(l):  # the screenshots a lesson shows, at the address the API serves them from
                (out / "media" / lid).mkdir(parents=True, exist_ok=True)
                shutil.copyfile(media.path(lid, img.src), out / "media" / lid / img.src)
        for cid in curriculum.load(lang)["cases"]:
            write(d / "cases" / f"{cid}.json", main.get_case(cid, lang))
        for rid in curriculum.load(lang)["runbooks"]:
            write(d / "runbooks" / f"{rid}.json", main.get_runbook(rid, lang))
        for tid in curriculum.load(lang)["diagnostics"]:
            write(d / "diagnostics" / f"{tid}.json", main.get_diagnostic(tid, lang))
        for lid, lab in labs.load(lang).items():
            write(d / "labs" / f"{lid}.json", main.get_lab(lid, lang))
            write(d / "labs" / f"{lid}.hints.json", {"hints": lab.hints, "hint_count": len(lab.hints)})
            write(d / "labs" / f"{lid}.reveal.json", main.lab_reveal(lid, lang))
            n += 1
        if lang == config.DEFAULT_LANG:
            ids_file = out / "studio-ids.json"
            studio_ids = json.loads(ids_file.read_text(encoding="utf-8")) if ids_file.exists() else []
            pages_ = routes(lang, studio_ids)
            for route, title, desc, body in pages_:
                target = out / "index.html" if route == "/" else out / route.lstrip("/") / "index.html"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(page(template, route, title, desc, body, site_url), encoding="utf-8", newline="\n")
                listed.append(route)
                pages += 1
            for old, new, title, desc, body in moved_pages(pages_):  # old addresses: not in the sitemap
                target = out / old.lstrip("/") / "index.html"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(page(template, old, title, desc, body, site_url, moved_to=new), encoding="utf-8", newline="\n")
                moved += 1
    (out / "404.html").write_text(page(template, "/404", "Page not found", "This page does not exist.", '<h1>Page not found</h1><p><a href="/">Home</a></p>', None), encoding="utf-8", newline="\n")
    robots = "User-agent: *\nAllow: /\n"
    if site_url:
        base = site_url.rstrip("/")
        (out / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "".join(f"  <url><loc>{html.escape(base + u)}</loc></url>\n" for u in listed)
            + "</urlset>\n", encoding="utf-8", newline="\n")
        robots += f"Sitemap: {base}/sitemap.xml\n"
    (out / "robots.txt").write_text(robots, encoding="utf-8", newline="\n")
    # what this build is: read by people and by deployment checks (no time stamp, so that an export is reproducible)
    write(out / "version.json", {"name": SITE_NAME, "version": main._version(), "commit": main.build_commit()})
    leaks = scan_for_secrets(out)
    if leaks:
        print("possible credentials in the export, refusing:\n  " + "\n  ".join(leaks), file=sys.stderr)
        return 2
    print(f"exported {n} labs, {pages} pages, {moved} redirects from old addresses and the curriculum to {out}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "frontend" / "dist"))
    ap.add_argument("--site-url", default=os.environ.get("ACADEMY_SITE_URL"))
    ap.add_argument("--redirect-map", help="also write the old addresses as an nginx map to this file")
    a = ap.parse_args()
    status = export(Path(a.out), a.site_url)
    if status == 0 and a.redirect_map:
        write_redirect_map(Path(a.redirect_map))
    sys.exit(status)
