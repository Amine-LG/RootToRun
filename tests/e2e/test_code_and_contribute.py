"""Code presentation, copy controls, long-command display, the home page's primary paths and the lesson header's
contribution links (shown only when ACADEMY_REPO_URL is set)."""
import json
import os
import sys
import re
import subprocess
import time
import urllib.request
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect

from academy import config
from conftest import free_port
from sources_oracle import defined_in

from addresses import lesson_url


def _server(extra):
    port = free_port()
    env = {**os.environ, "ACADEMY_CLUSTER": "off", "KUBECONFIG": "/nonexistent", **extra}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "academy.main:app", "--app-dir", "backend",
                             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"], cwd=config.ROOT, env=env)
    url = f"http://127.0.0.1:{port}/"
    for _ in range(60):
        try:
            urllib.request.urlopen(url + "api/meta", timeout=1)
            break
        except OSError:
            time.sleep(0.25)
    # The first curriculum request builds the server's caches: seconds on a cold start, longer than an assertion waits
    # (the lesson page then stayed empty and the tests failed intermittently). It also fails clearly if the server never
    # came up.
    try:
        urllib.request.urlopen(url + "api/curriculum", timeout=60)
    except BaseException:
        proc.terminate()
        proc.wait(5)
        raise
    return proc, url


@pytest.fixture(scope="module")
def repo_server():
    proc, url = _server({"ACADEMY_REPO_URL": "https://github.com/example/example"})
    yield url
    proc.terminate()
    proc.wait(5)


LESSON = "n.console-clis"


def test_contribution_links_hidden_when_unset(page, practice_server):
    page.goto(practice_server.rstrip("/") + lesson_url(LESSON))
    expect(page.locator(".lesson-h h1")).to_be_visible()
    assert page.get_by_test_id("page-actions").count() == 0
    assert page.get_by_test_id("edit-source").count() == 0


def test_contribution_links_when_set(page, repo_server):
    """On the server (the API, not the static export): the lesson's Report and Edit links. Every kind of page is
    covered on the static site by test_contribute_everywhere.py."""
    page.goto(repo_server.rstrip("/") + lesson_url(LESSON) + "#some-section")
    menu = page.get_by_test_id("report-menu")
    expect(menu).to_be_visible()
    menu.click()
    rep = page.locator(".pa-wide [data-testid=report-content]")
    rep.focus()  # the link is brought up to date when it is used
    q = urlparse(rep.get_attribute("href"))
    assert q.scheme + "://" + q.netloc + q.path == "https://github.com/example/example/issues/new"
    p = parse_qs(q.query)
    assert p["template"] == ["content-problem.yml"]
    assert p["content-id"] == [LESSON]
    assert p["content-type"] == ["Lesson"]
    assert p["section"] == ["some-section"]
    assert p["page-url"] == [lesson_url(LESSON)]
    assert p["site-version"][0]
    assert "problem-type" not in p
    edit = page.locator(".pa-wide [data-testid=edit-source]").get_attribute("href")
    # the file whose YAML defines this lesson (content/en/lessons/o1-flow.yaml), found with a YAML parser
    assert edit == f"https://github.com/example/example/edit/main/{defined_in('lessons', LESSON)}", edit
    assert defined_in("lessons", LESSON) == "content/en/lessons/o1-flow.yaml"


def test_code_is_highlighted_and_copyable(page, static_site):
    page.context.grant_permissions(["clipboard-read", "clipboard-write"]) if page.context.browser.browser_type.name == "chromium" else None
    page.goto(static_site.rstrip("/") + lesson_url("n.console-clis"))
    page.wait_for_selector(".demo-term")
    term = page.locator(".demo-term").first
    assert term.locator(".tok-bin").count() >= 1
    btn = page.locator(".demo .copy-btn").first
    btn.focus()
    page.keyboard.press("Enter")
    expect(page.locator("[role=status]", has_text="Copied").first).to_be_attached()


def test_home_leads_with_the_two_openshift_paths(page, static_site):
    page.goto(static_site)
    expect(page.locator("h1")).to_contain_text("Container platform")
    assert "OpenShift" not in page.locator("h1").inner_text()
    expect(page.get_by_test_id("hero-start")).to_be_visible()
    expect(page.get_by_test_id("hero-start")).to_have_attribute("href", "/learn/application-operations")
    # the lede says what the platform teaches (referential use in running text, never in a heading)
    expect(page.locator(".hx-lede")).to_contain_text("OpenShift")
    foot = page.locator(".site-foot").inner_text()
    assert "Red Hat and OpenShift are trademarks of Red Hat, LLC, registered in the United States" in foot
    assert not re.search(r"\b(?:DO|EX)[1-4]80\b", page.locator("body").inner_text())


def test_about_states_licences_version_and_ships_the_licence_texts(page, static_site):
    """The site says under which licences it is published and which build it is, and ships every licence text that
    its bundled fonts and libraries require (frontend/scripts/licenses.mjs)."""
    version = json.loads((config.ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))["version"]
    page.goto(static_site)
    page.locator(".site-foot").get_by_role("link", name="Licences").click()
    section = page.locator("#licences")
    expect(section).to_contain_text("Creative Commons Attribution-ShareAlike 4.0")
    expect(section).to_contain_text("Apache License 2.0")
    expect(page.get_by_test_id("build-version")).to_contain_text(version)
    expect(section.locator('a[href="/licenses.txt"]')).to_have_count(1)
    text = page.request.get(static_site + "licenses.txt").text()
    for needed in ("Apache License", "SIL OPEN FONT LICENSE", "react 18.", "shiki 4."):
        assert needed in text, needed
    # the console screenshots and the marks they show are named as not covered, never granted with the content
    assert "other material under content/" not in text
    assert "Not covered by these licences, and not relicensed by the project: the screenshots of the OpenShift web console" in text
    expect(section).to_contain_text("screenshots of the OpenShift web console")
    expect(section).to_contain_text("not relicensed")
    expect(page.locator("#trademarks")).not_to_contain_text("No Red Hat training material is used")
    meta = json.loads(page.request.get(static_site + "version.json").text())
    assert meta["version"] == version


@pytest.mark.parametrize("width", [320, 375])
def test_long_commands_do_not_widen_the_page(browser, static_site, width):
    ctx = browser.new_context(viewport={"width": width, "height": 800})
    pg = ctx.new_page()
    pg.goto(static_site.rstrip("/") + lesson_url(LESSON))
    pg.wait_for_selector(".demo-term")
    assert pg.evaluate("document.documentElement.scrollWidth") <= width
    ctx.close()


# every link of the credit line, read in one go inside the page, once the line is complete (its last link is there):
# read link by link it could re-render in between and come back half-rendered under load (a Chromium CI run)
CREDIT_LINKS = """() => { const c = document.querySelector('[data-testid=foot-credit]');
  if (!c) return null;
  const links = Object.fromEntries([...c.querySelectorAll('a')].map((a) => [a.innerText.trim(), a.getAttribute('href')]));
  return 'Licences' in links ? links : null }"""


def _credit(page):
    expect(page.get_by_test_id("foot-credit")).to_be_visible()
    return page.wait_for_function(CREDIT_LINKS, timeout=10000).json_value()


def test_footer_credits_the_creator_and_links_the_repository_when_set(page, repo_server):
    page.goto(repo_server.rstrip("/") + lesson_url(LESSON))
    links = _credit(page)
    assert links == {"Amine-LG": "https://github.com/Amine-LG", "Open source": "https://github.com/example/example",
                     "Contributors": "https://github.com/example/example/graphs/contributors", "Licences": "/about#licences"}
    legal = page.locator(".site-foot .foot-legal").inner_text()
    assert legal.startswith("© 2026 Amine-LG and contributors.")
    assert "used for identification purposes only and are not intended to indicate affiliation with or approval by Red Hat" in legal


def test_footer_credit_without_a_repository_and_on_the_static_site(page, static_site):
    """Without a repository address there is no contributors link; a served site may name one (the release image)."""
    repo = json.loads(urllib.request.urlopen(static_site.rstrip("/") + "/data/meta.json").read()).get("repo_url")
    page.goto(static_site.rstrip("/") + "/about")
    links = _credit(page)
    assert links["Amine-LG"] == "https://github.com/Amine-LG" and links["Licences"] == "/about#licences"
    if repo:
        assert links["Open source"] == repo and links["Contributors"] == f"{repo}/graphs/contributors"
    else:
        assert links["Open source"] == "/about#licences" and "Contributors" not in links
    expect(page.locator("main h1")).to_have_text("About Root to Run")
    credits = page.locator("#credits").inner_text()
    assert "created and is maintained by Amine-LG" in credits and "do not own, maintain, sponsor or endorse" in credits
