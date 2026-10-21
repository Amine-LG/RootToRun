"""Report a problem and Edit on GitHub, on every kind of page (components/Contribute.tsx).

One page of each kind, on the static site exported with a repository address: the actions are at the top right, stay
reachable after scrolling far down (a compact copy in the sticky site header, not over the content), can be reached
and used with the keyboard under clear names, Edit opens the file that defines the page and Report opens the right
issue form with the page's public facts and nothing else. The expected files are read here from the content files
with a YAML parser and from the import lines of sims/index.ts, not from the code that builds the links. Without a
repository there are no actions at all."""
import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.request
from urllib.parse import parse_qs, urlparse, quote

import pytest
import yaml
from playwright.sync_api import expect

from academy import config
from addresses import diag_url, lab_url, lesson_url, track_url
from conftest import DIST, free_port
from sources_oracle import defined_in, model_files

REPO = "https://github.com/example/example"  # the repository of the locally exported site
FORMS = config.ROOT / ".github" / "ISSUE_TEMPLATE"
INJECTS_SCRIPTS = True  # the accessibility scan adds axe-core with a <script> tag (see conftest.py)
AXE = config.ROOT / "frontend" / "node_modules" / "axe-core" / "axe.min.js"


class RepoSite(str):
    """The site's address (no trailing slash), with the repository and branch its links must point to."""
    def __new__(cls, url: str, repo: str, branch: str):
        site = super().__new__(cls, url.rstrip("/"))
        site.repo, site.branch = repo, branch
        return site


@pytest.fixture(scope="module")
def repo_site(tmp_path_factory):
    """A site that names a repository. With ACADEMY_E2E_SITE (the CI runs the production image, built with the
    repository's address), that site and the repository its /data/meta.json names; otherwise the static export, as
    published, built here with an example repository."""
    if os.environ.get("ACADEMY_E2E_SITE"):
        url = os.environ["ACADEMY_E2E_SITE"].rstrip("/")
        with urllib.request.urlopen(url + "/data/meta.json", timeout=30) as r:
            meta = json.load(r)
        if not meta.get("repo_url"):
            pytest.skip("the site under test names no repository (built without REPO_URL)")
        yield RepoSite(url, meta["repo_url"], meta.get("repo_branch") or "main")
        return
    if not (DIST / "index.html").exists():
        pytest.skip("frontend not built (cd frontend && npm run build)")
    root = tmp_path_factory.mktemp("site-repo")
    shutil.copytree(DIST, root, dirs_exist_ok=True)
    r = subprocess.run([sys.executable, str(config.ROOT / "scripts" / "export_static.py"), "--out", str(root)], capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "ACADEMY_REPO_URL": REPO, "ACADEMY_REPO_BRANCH": "main"})
    assert r.returncode == 0, r.stderr
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", free_port()), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield RepoSite(f"http://127.0.0.1:{srv.server_address[1]}", REPO, "main")
    srv.shutdown()


def model_file(model: str) -> str:
    return model_files()[model]


# kind, address, content id, expected edit files (primary first), the forms offered
CASES = [
    ("lesson", lesson_url("n.console-clis") + "#a-section", "n.console-clis", [defined_in("lessons", "n.console-clis")], ["content", "command", "website"]),
    ("lab", lab_url("lab.deploy-apps"), "lab.deploy-apps", [defined_in("labs", "lab.deploy-apps")], ["content", "command", "website"]),
    ("incident", lab_url("inc.dns-typo"), "inc.dns-typo", [defined_in("incidents", "inc.dns-typo")], ["content", "command", "website"]),
    ("challenge", lab_url("ch.right-size"), "ch.right-size", [defined_in("challenges", "ch.right-size")], ["content", "command", "website"]),
    ("model", "/studio/model/scheduler", "scheduler", [model_file("scheduler"), "frontend/src/sims/index.ts"], ["content", "website"]),
    ("diagram", "/studio/diagram/rbac", "rbac", ["frontend/src/lib/diagrams.ts"], ["content", "website"]),
    ("runbook", "/runbook/rb.route-503", "rb.route-503", [defined_in("runbooks", "rb.route-503")], ["content", "website"]),
    ("case", "/case/case.friday-release", "case.friday-release", [defined_in("cases", "case.friday-release")], ["content", "website"]),
    ("diagnostic", diag_url("linux"), "linux", [defined_in("diagnostics", "linux", key="track")], ["content", "website"]),
]
STICKY_BAR = {"lesson", "lab", "incident", "challenge", "runbook", "case"}  # the page bar (PageHead.tsx PageBar) sticks at >= 901 px
FORM_FILE = {"content": "content-problem.yml", "command": "incorrect-command.yml", "website": "ui-bug.yml"}
TYPE = {"lesson": "Lesson", "lab": "Guided lab", "incident": "Incident", "challenge": "Challenge", "model": "Interactive model", "diagram": "Diagram",
        "concept": "Concept", "runbook": "Runbook", "case": "Case study", "diagnostic": "Diagnostic", "path": "Learning path", "commands": "Command reference"}


def form_fields(name: str) -> dict:
    form = yaml.safe_load((FORMS / name).read_text(encoding="utf-8"))
    return {e["id"]: e["type"] for e in form["body"] if e.get("id")}


def open_page(pg, site, path):
    pg.goto(site + path)
    pg.wait_for_selector("main .page:not(:has(.sk-page))")
    actions = pg.get_by_test_id("page-actions")
    expect(actions).to_be_visible()
    return actions


@pytest.mark.parametrize("kind,path,ident,edits,forms", CASES, ids=[c[0] for c in CASES])
def test_actions_on_every_kind_of_page(browser, repo_site, kind, path, ident, edits, forms):
    ctx = browser.new_context(viewport={"width": 1280, "height": 720}, reduced_motion="reduce")
    # a learner's saved state must never travel in a report link
    ctx.add_init_script("try { localStorage.setItem('osa.secret-probe', 'SECRET-PROBE-7f3') } catch (e) {}")
    pg = ctx.new_page()
    actions = open_page(pg, repo_site, path)

    # at the top, on the right
    box, width = actions.bounding_box(), pg.viewport_size["width"]
    assert box["y"] < 420 and box["x"] + box["width"] > width * 0.55, box

    # Edit: GitHub's editor on the real file(s)
    links = pg.locator("[data-testid=page-actions] .pa-wide [data-testid=edit-source]")
    if not edits:
        assert links.count() == 0 and pg.get_by_test_id("edit-menu").count() == 0
    else:
        if pg.get_by_test_id("edit-menu").count():
            pg.get_by_test_id("edit-menu").click()
        hrefs = [a.get_attribute("href") for a in links.all()]
        assert hrefs == [f"{repo_site.repo}/edit/{quote(repo_site.branch, safe='')}/{p}" for p in edits], hrefs
        for a in links.all():
            expect(a).to_have_attribute("target", "_blank")
            expect(a).to_have_accessible_name(re.compile(r"^Edit .+ on GitHub \(opens in a new tab\)$"))
        pg.keyboard.press("Escape")

    # Report: the menu offers the right forms, each prefilled with fields its form has, and nothing private
    menu = pg.get_by_test_id("report-menu")
    expect(menu).to_have_attribute("aria-expanded", "false")
    menu.click()
    expect(menu).to_have_attribute("aria-expanded", "true")
    items = pg.locator("[data-testid=page-actions] .pa-wide [data-testid^=report-]:not([data-testid=report-menu])")
    assert [i.get_attribute("data-testid") for i in items.all()] == [f"report-{f}" for f in forms]
    for item in items.all():
        expect(item).to_be_visible()
        item.hover()  # the link is brought up to date when it is used
        href = item.get_attribute("href")
        u = urlparse(href)
        assert f"{u.scheme}://{u.netloc}{u.path}" == f"{repo_site.repo}/issues/new", href
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        form = item.get_attribute("data-testid").removeprefix("report-")
        assert q["template"] == FORM_FILE[form]
        fields = form_fields(q["template"])
        assert set(q) - {"template", "title"} <= set(fields), set(q) - set(fields)
        assert all(fields[k] in ("input", "textarea") for k in q if k in fields)
        assert q["page-url"] == urlparse(path).path, q  # relative, without query or fragment
        assert q["site-version"] and q["content-id"] == ident and q["content-type"] == TYPE[kind]
        if form != "website":
            assert q["content-title"] and q["title"].startswith(f"[{TYPE[kind]}] ")
            if "#" in path:  # the part of the page the reader is on
                assert q["section"] == path.split("#")[1], q
        for leak in ("127.0.0.1", "SECRET-PROBE", "Mozilla", "Firefox", "Chrome", "localStorage", "?"):
            assert leak not in "&".join(f"{k}={v}" for k, v in q.items()), (leak, q)
    pg.keyboard.press("Escape")
    expect(menu).to_have_attribute("aria-expanded", "false")

    # far down the page: still in view and over no content, either in the page's sticky bar (lessons, labs,
    # incidents, challenges, runbooks and cases on wide screens) or as a compact copy in the sticky site header
    pg.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    sticky_bar = kind in STICKY_BAR
    if sticky_bar:
        assert pg.evaluate("window.scrollY") > 400
        expect(actions).to_be_in_viewport()  # sticky: no waiting needed, but say what is expected before measuring
        header = pg.locator(".topbar").bounding_box()
        bar, a = pg.get_by_test_id("page-bar").bounding_box(), actions.bounding_box()
        assert bar["y"] >= header["y"] + header["height"] - 1 and bar["y"] + bar["height"] <= 200, (bar, header)  # stuck under the header
        assert a["y"] >= bar["y"] and a["y"] + a["height"] <= bar["y"] + bar["height"] and a["x"] + a["width"] <= width, (a, bar)
        assert pg.get_by_test_id("page-bar").evaluate("e => getComputedStyle(e).backgroundColor") not in ("rgba(0, 0, 0, 0)", "transparent")
        expect(pg.get_by_test_id("page-actions-dock")).to_have_count(0)  # no second copy
    elif pg.evaluate("window.scrollY") > 400:
        dock = pg.get_by_test_id("page-actions-docked")
        expect(dock).to_be_visible()  # appears once the page's own actions have gone behind the header
        header = pg.locator(".topbar").bounding_box()
        d = dock.bounding_box()
        assert d["y"] >= 0 and d["y"] + d["height"] <= header["y"] + header["height"], (d, header)
        assert d["x"] >= 0 and d["x"] + d["width"] <= width
        dock.click()
        panel = pg.locator("[data-testid=page-actions-dock] .pa-pop")
        expect(panel).to_be_visible()
        assert panel.locator("[data-testid=report-content]").count() == 1
        assert [a.get_attribute("href") for a in panel.locator("[data-testid=edit-source]").all()] == [f"{repo_site.repo}/edit/{quote(repo_site.branch, safe='')}/{p}" for p in edits]
        pg.keyboard.press("Escape")
        expect(dock).to_be_focused()
        # back at the top, only the page's own actions remain, and the focus moves to them
        pg.evaluate("window.scrollTo(0, 0)")
        expect(pg.get_by_test_id("page-actions-dock")).to_have_count(0)
        expect(menu).to_be_focused()
    ctx.close()


def test_keyboard_reaches_and_uses_the_actions(browser, repo_site):
    """From the top of a lesson, Tab reaches "Report a problem", Enter opens it, Tab moves through its links (named
    with where they go), Escape closes it and gives the focus back; Edit is a link with a full name."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    pg = ctx.new_page()
    open_page(pg, repo_site, lesson_url("n.console-clis"))
    for _ in range(80):
        pg.keyboard.press("Tab")
        if pg.evaluate("document.activeElement.dataset.testid") == "report-menu":
            break
    else:
        raise AssertionError("Tab never reached Report a problem")
    menu = pg.get_by_test_id("report-menu")
    expect(menu).to_have_accessible_name("Report a problem")
    outline = pg.evaluate("getComputedStyle(document.activeElement).outlineStyle")
    assert outline != "none", "no visible focus on the button"
    pg.keyboard.press("Enter")
    expect(menu).to_have_attribute("aria-expanded", "true")
    pg.keyboard.press("Tab")
    first = pg.locator(":focus")
    expect(first).to_have_attribute("data-testid", "report-content")
    expect(first).to_have_accessible_name("A mistake in this lesson on GitHub (opens in a new tab)")
    expect(first).to_have_accessible_description(re.compile(r"\S"))
    pg.keyboard.press("Escape")
    expect(menu).to_be_focused()
    expect(menu).to_have_attribute("aria-expanded", "false")
    edit = pg.locator(".pa-wide [data-testid=edit-source]")
    expect(edit).to_have_accessible_name("Edit this lesson on GitHub (opens in a new tab)")
    assert pg.locator("[data-testid=page-actions] svg:not([aria-hidden=true])").count() == 0  # icons are decoration
    ctx.close()


def test_phone_shows_one_labelled_button_that_opens_a_sheet_with_everything(browser, repo_site):
    # animations on, as on a phone: the old compact panel opened off the left edge only while its entrance animated
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, reduced_motion="no-preference")
    pg = ctx.new_page()
    open_page(pg, repo_site, lab_url("inc.dns-typo"))
    btn = pg.get_by_test_id("page-actions-more")
    expect(btn).to_be_visible()
    expect(btn).to_have_accessible_name("Report a problem or edit this incident")
    expect(btn).to_contain_text("Report or edit")  # a word on the button, not an icon alone
    b = btn.bounding_box()
    assert b["width"] >= 44 and b["height"] >= 44 and b["x"] + b["width"] <= 390, b
    assert pg.get_by_test_id("report-menu").is_hidden()
    btn.tap()
    sheet = pg.get_by_test_id("page-actions-more-sheet")
    expect(sheet).to_be_visible()
    expect(sheet).to_have_attribute("role", "dialog")
    pg.wait_for_timeout(400)
    p = sheet.bounding_box()
    assert p["x"] >= 0 and p["x"] + p["width"] <= 390 and p["y"] >= 0 and p["y"] + p["height"] <= 844, p
    edit = sheet.locator("[data-testid=edit-source]")
    expect(edit).to_contain_text("shows the solution")  # the incident's file holds its answer
    assert pg.evaluate("document.documentElement.scrollWidth") <= 390
    pg.get_by_test_id("page-actions-more-close").tap()
    expect(sheet).to_have_count(0)
    # far down the page, a phone has no copy in the header: the menu's "This page" opens the same sheet
    pg.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    expect(pg.get_by_test_id("page-actions-docked")).to_be_hidden()
    pg.get_by_test_id("menu-open").tap()
    pg.get_by_test_id("menu-page-actions").tap()
    expect(sheet).to_be_visible()
    expect(sheet.locator("[data-testid=report-content]")).to_have_count(1)
    ctx.close()


def test_footer_reports_a_website_problem_from_every_page(page, repo_site):
    page.goto(repo_site + "/me")
    link = page.get_by_test_id("foot-report")
    expect(link).to_have_accessible_name("Report a problem with the website on GitHub (opens in a new tab)")
    link.hover()
    q = {k: v[0] for k, v in parse_qs(urlparse(link.get_attribute("href")).query).items()}
    assert q["template"] == "ui-bug.yml" and q["page-url"] == "/me" and q["site-version"]
    assert set(q) - {"template", "title"} <= set(form_fields("ui-bug.yml"))
    assert page.get_by_test_id("page-actions").count() == 0  # a page with no content of its own: the footer only


@pytest.mark.parametrize("path", ["/", "/learn", track_url("linux"), track_url("admin1"), "/labs", "/incidents", "/challenges",
                                  "/studio", "/map", "/map?concept=k8s.scheduler", "/commands", "/handbook", "/review", "/me", "/about"])
def test_hub_and_topic_pages_have_no_report_or_edit(browser, repo_site, path):
    """Report and Edit belong to a piece of content (a lesson, lab, incident, challenge, runbook, case, diagnostic, model,
    diagram); pages that list or organise them (courses, the map, the commands list, the hubs) offer only the footer's
    website report, at every width."""
    for w in (390, 1280):
        ctx = browser.new_context(viewport={"width": w, "height": 900})
        pg = ctx.new_page()
        pg.goto(repo_site + path)
        pg.wait_for_selector("main .page:not(:has(.sk-page))")
        pg.wait_for_timeout(300)
        for testid in ("page-actions", "page-actions-more", "report-menu", "edit-source", "page-actions-dock"):
            assert pg.get_by_test_id(testid).count() == 0, (path, w, testid)
        expect(pg.get_by_test_id("foot-report")).to_have_count(1)
        if w == 390:  # nor in the phone menu's "This page"
            pg.get_by_test_id("menu-open").click()
            assert pg.get_by_test_id("menu-page-actions").count() == 0, path
        ctx.close()


@pytest.mark.parametrize("path", [lesson_url("n.console-clis"), lab_url("lab.deploy-apps"), "/studio/model/scheduler", "/map?concept=k8s.scheduler"])
def test_no_actions_without_a_repository(page, static_site, path):
    meta = json.loads(page.request.get(static_site + "data/meta.json").text())
    if meta.get("repo_url"):
        pytest.skip("this site names a repository")
    page.goto(static_site.rstrip("/") + path)
    page.wait_for_selector("main .page:not(:has(.sk-page))")
    expect(page.locator("main h1").first).to_be_visible()
    page.wait_for_timeout(300)
    for testid in ("page-actions", "page-actions-dock", "foot-report", "report-menu", "edit-source"):
        assert page.get_by_test_id(testid).count() == 0, testid
    assert page.locator("a[href*='github.com/'][href*='/issues/new'], a[href*='/edit/']").count() == 0


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_actions_and_open_menus_pass_axe(browser, repo_site, theme):
    """axe-core on the actions themselves (the main accessibility scan runs on a site without a repository, where they
    are absent), with the menus open, in both themes. An automated scan, not a compliance claim."""
    if not AXE.exists():
        pytest.skip("axe-core not installed (cd frontend && npm ci)")
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    ctx.add_init_script(f"try {{ localStorage.setItem('osa.theme', '{theme}') }} catch (e) {{}}")
    pg = ctx.new_page()
    problems = []
    for path in (lesson_url("n.console-clis"), "/studio/model/scheduler"):
        open_page(pg, repo_site, path)
        pg.get_by_test_id("report-menu").click()
        pg.add_script_tag(path=str(AXE))
        res = pg.evaluate("async () => (await axe.run({include: [['[data-testid=page-actions]'], ['.site-foot']]}, {resultTypes: ['violations']})).violations.map(v => v.id + ' ' + v.impact + ' ' + v.nodes.map(n => n.target.join(' ')).join(', '))")
        problems += [f"{path}: {r}" for r in res]
    ctx.close()
    assert not problems, "\n".join(problems)


def test_lesson_bar_order_with_contribution_actions(browser, repo_site):
    """With a repository, a lesson's bar reads: Go deeper, then Report a problem and Edit, then Previous and Next at
    the right end; the keyboard meets them in that order (test_lesson_polish.py checks the bar without a repository)."""
    ctx = browser.new_context(viewport={"width": 1360, "height": 900})
    pg = ctx.new_page()
    pg.goto(repo_site.rstrip("/") + lesson_url("o1.console-apps"))
    pg.wait_for_selector("[data-testid=page-actions] .pa-wide [data-testid=report-menu]")
    ids = ["go-deeper", "report-menu", "edit-source", "pager-prev", "pager-next"]
    xs = [pg.locator(f"[data-testid=page-bar] .pa-wide [data-testid={i}], [data-testid=page-bar] > * [data-testid={i}], [data-testid=page-bar] > [data-testid={i}]").first.bounding_box()["x"] for i in ids]
    assert xs == sorted(xs), list(zip(ids, xs))
    pg.get_by_test_id("go-deeper").focus()
    for i in ids[1:]:
        pg.keyboard.press("Tab")
        assert pg.evaluate("document.activeElement.dataset.testid") == i, (i, pg.evaluate("document.activeElement.outerHTML.slice(0, 120)"))
    ctx.close()
