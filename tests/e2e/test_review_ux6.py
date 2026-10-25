"""UX v6 review regressions, Firefox/static export only; never opens a cluster or a socket.

Build the frontend as for tests/e2e/conftest.py::static_site. UX6_STATIC_ROOT may
point to an existing Vite build/export when the workspace must stay read-only.
"""
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from playwright.sync_api import expect

from academy import config, urls
from addresses import diag_url, lab_url, lesson_url
from conftest import still

BASE = "http://ux6.local"
VIEWPORTS = [(1440, 900), (820, 1180), (390, 844)]
AXE = config.ROOT / "frontend/node_modules/axe-core/axe.min.js"
LINK = re.compile(r"\[[^\]]+\]\((/(?:lab|lesson)/[^\s)]+)\)")


INJECTS_SCRIPTS = True  # axe-core is added with a <script> tag (see conftest.py)

@pytest.fixture(scope="session")
def ux6_export(tmp_path_factory):
    """Same copy + exporter as static_site, with request interception instead of a server."""
    source = Path(os.environ.get("UX6_STATIC_ROOT", str(config.ROOT / "frontend/dist")))
    if not (source / "index.html").is_file():
        pytest.skip("frontend not built (cd frontend && npm run build)")
    root = tmp_path_factory.mktemp("ux6-site")
    shutil.copytree(source, root, dirs_exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(config.ROOT / "scripts/export_static.py"), "--out", str(root)],
        cwd=config.ROOT, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "ACADEMY_CLUSTER": "off", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    return root


def context(browser, root, viewport, theme="light"):
    ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, reduced_motion="reduce")
    ctx.add_init_script(f"localStorage.setItem('osa.theme', '{theme}')")

    def serve(route):
        url = urlsplit(route.request.url)
        # All network activity stays inside this fixture, including the expected API probe.
        if url.netloc != urlsplit(BASE).netloc:
            route.abort()
            return
        if url.path == "/__review_axe.js":
            route.fulfill(status=200, body=AXE.read_bytes(), content_type="text/javascript")
            return
        path = (root / unquote(url.path).lstrip("/")).resolve()
        if not path.is_relative_to(root.resolve()):
            route.fulfill(status=404, body="Not found")
            return
        if path.is_dir():
            path /= "index.html"
        if path.is_file():
            route.fulfill(status=200, body=path.read_bytes(), content_type=mimetypes.guess_type(path)[0] or "application/octet-stream")
        else:
            route.fulfill(status=404, body="Not found")

    ctx.route("**/*", serve)
    return ctx


def open_page(page, path):
    page.goto(BASE + path)
    page.wait_for_selector("main .page:not(:has(.sk-page))")


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def test_all_lesson_diagnostic_challenge_links_resolve(ux6_export):
    """Check every content link, including hidden depth, answers and reference solutions.

    Require actual exported HTML AND the destination's JSON; a SPA shell/HTTP 200
    alone would let nonexistent lesson and lab ids slip through.
    """
    broken = []
    checked = 0
    for lang in (ux6_export / "data").iterdir():
        if not lang.is_dir():
            continue
        lessons = {p.stem for p in (lang / "lessons").glob("*.json")}
        labs = {p.stem for p in (lang / "labs").glob("*.json") if not p.stem.endswith((".hints", ".reveal"))}
        sources = list((lang / "lessons").glob("*.json")) + list((lang / "diagnostics").glob("*.json"))
        for path in (lang / "labs").glob("*.json"):
            if path.stem.endswith((".hints", ".reveal")):
                continue
            lab = json.loads(path.read_text(encoding="utf-8"))["lab"]
            if lab["kind"] == "challenge":
                sources += [path, path.with_name(path.stem + ".hints.json"), path.with_name(path.stem + ".reveal.json")]
        for source in sources:
            data = json.loads(source.read_text(encoding="utf-8"))
            hrefs = [href for text in strings(data) for href in LINK.findall(text)]
            if source.parent.name == "diagnostics":
                hrefs += [f"/{'lesson' if target in lessons else 'lab'}/{target}" for item in data["items"] for target in item["targets"]]
            if source.parent.name == "lessons":
                hrefs += [f"/lab/{lid}" for lid in data["labs"]]
                hrefs += [f"/lesson/{lid}" for lid in data["prerequisites"] if lid in lessons]
            for href in hrefs:
                checked += 1
                route = unquote(urlsplit(href).path).rstrip("/")
                parts = route.strip("/").split("/")
                valid = len(parts) == 2 and parts[1] in (lessons if parts[0] == "lesson" else labs)
                # an id-based address (how content links) and the readable address it leads to are both exported
                current = urls.canonical(route)
                if not valid or not (ux6_export / route.lstrip("/") / "index.html").is_file() or current == route \
                        or not (ux6_export / current.lstrip("/") / "index.html").is_file():
                    broken.append(f"{source.relative_to(ux6_export)} -> {href}")
    assert checked > 0, "link enumeration must not silently become empty"
    assert not broken, "\n".join(broken)


@pytest.mark.parametrize("viewport", VIEWPORTS)

def test_u6_01_partial_topic_is_not_shown(browser, ux6_export, viewport):
    ctx = context(browser, ux6_export, viewport)
    try:
        page = ctx.new_page()
        diagnostic = json.loads((ux6_export / "data/en/diagnostics/start.json").read_text(encoding="utf-8"))
        curriculum = json.loads((ux6_export / "data/en/curriculum.json").read_text(encoding="utf-8"))
        track = next(t for t in curriculum["tracks"] if t["id"] == "start")
        modules = {m["id"]: m for m in curriculum["modules"]}
        order = [lid for mid in track["modules"] for lid in modules[mid]["lessons"]]
        items = sorted(diagnostic["items"], key=lambda item: order.index(item["targets"][0]))
        at = next(i for i, item in enumerate(items) if sum(x["targets"][0] == item["targets"][0] for x in items) > 1)
        first = items[at]
        target = first["targets"][0]
        assert sum(item["targets"][0] == target for item in items) > 1
        open_page(page, diag_url("start"))
        page.get_by_test_id("diag-start").click()
        for _ in items[:at]:
            page.get_by_test_id("diag-idk").click()
            page.get_by_test_id("diag-next").click()
            still(page)
        page.get_by_test_id("diag-choice").nth(first["answer"]).click()
        page.get_by_test_id("diag-conf-2").click()
        page.get_by_test_id("diag-next").click()
        still(page)
        page.get_by_test_id("diag-stop").click()
        expect(page.get_by_test_id("diag-results")).to_be_visible()
        # The learner has not demonstrated all of the topic's authored questions.
        assert page.locator(f'[data-testid="diag-shown"] a[href="{lesson_url(target)}"]').count() == 0
    finally:
        ctx.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("challenge", ["ch.helm-release", "ch.config-out-of-spec"])

def test_u6_02_unrecorded_solution_does_not_claim_recorded_grade(browser, ux6_export, theme, challenge):
    """A challenge without a recording must not promise recorded output. Both challenges are recorded now, so the
    test serves them as they were when the review found the problem: no recording, no reference run."""
    data = json.loads((ux6_export / f"data/en/labs/{challenge}.json").read_text(encoding="utf-8"))
    reference = json.loads((ux6_export / f"data/en/labs/{challenge}.reveal.json").read_text(encoding="utf-8"))
    data["recording"] = None
    reference["fix_recording"], reference["verify_after"] = [], None
    ctx = context(browser, ux6_export, VIEWPORTS[0], theme)
    try:
        page = ctx.new_page()
        page.route(f"**/data/en/labs/{challenge}.json", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(data)))
        page.route(f"**/data/en/labs/{challenge}.reveal.json", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(reference)))
        open_page(page, lab_url(challenge))
        page.get_by_test_id("reveal").click()
        page.locator(".ch-answer h2").wait_for()
        expect(page.locator(".ch-answer")).not_to_contain_text("Its recorded output and the grade it received are below.")
        expect(page.locator(".ch-answer")).to_contain_text("no recorded run of them is available yet")
    finally:
        ctx.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_review_pages_no_serious_axe_violations(browser, ux6_export, viewport, theme):
    if not AXE.is_file():
        pytest.skip("axe-core not installed")
    ctx = context(browser, ux6_export, viewport, theme)
    problems = []
    try:
        page = ctx.new_page()
        for path in [diag_url("admin1"), lab_url("ch.right-size"), lab_url("ch.helm-release")]:
            open_page(page, path)
            if path.startswith("/diagnostic"):
                page.get_by_test_id("diag-start").click()
                page.get_by_test_id("diag-choice").first.click()
            else:
                for summary in page.locator(".ch-brief details > summary").all():  # every panel of the brief is scanned
                    summary.click()
                page.get_by_test_id("reveal").click()
                page.locator(".ch-answer h2").wait_for()
            page.wait_for_timeout(600)
            page.add_script_tag(url=BASE + "/__review_axe.js")
            violations = page.evaluate("""async () => (await axe.run(document, {resultTypes: ['violations']})).violations
                .filter(v => ['serious', 'critical'].includes(v.impact))
                .map(v => ({id: v.id, targets: v.nodes.map(n => n.target)}))""")
            problems += [f"{path} {theme} {viewport}: {v}" for v in violations]
        assert not problems, "\n".join(problems)
    finally:
        ctx.close()
