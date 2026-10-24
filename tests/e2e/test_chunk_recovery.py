"""A page whose code cannot load never blanks the site. Page code is loaded when a page is first opened, from files
under /assets/ whose names contain a hash of their content: a tab opened before a deployment asks for names the new
deployment does not have (the production nginx answers 404 with an HTML page), and a dropped connection fails the
request. These tests answer a page's chunk the same ways, follow an in-site link to that page (no page load), and check
that the shell stays usable, that one automatic reload at most fetches the new names, that the recovery panel offers
Reload and Try again, and that the learner's progress is kept."""
import json
import re
import time

import pytest
from playwright.sync_api import expect
from addresses import lesson_url

LESSON = re.compile(r"/assets/Lesson-[^/?]+\.js(\?.*)?$")
LAB = re.compile(r"/assets/Lab-[^/?]+\.js(\?.*)?$")
ME = re.compile(r"/assets/Me-[^/?]+\.js(\?.*)?$")
MODELS_JS = re.compile(r"/assets/sims-[^/?]+\.js(\?.*)?$")
MODELS_CSS = re.compile(r"/assets/sims-[^/?]+\.css(\?.*)?$")
FIRST, SECOND = "d.services-dns", "d.routes-tls"
LAB_PATH = "/labs/a-tour-of-the-oc-cli"
MODEL_PATH = "/studio/model/traffic"
MARK = "osa.reloadedFor"  # sessionStorage: the address an automatic reload was last made for, and when
# What browsers and React report about a page's code that failed to load: expected here. Matched at the start of the
# message, without the " [source url]" that conftest appends; any other console or page error fails the test.
EXPECTED = re.compile("|".join([
    r"Failed to load resource: the server responded with a status of 404",  # Chromium: the 404 itself
    r"Failed to load resource: net::ERR_",  # Chromium: an aborted request, or offline
    r"ChunkError: The site's code could not be loaded",  # React reports the error the page area caught
    r"The page area caught: ChunkError: The site's code could not be loaded",  # and the page area logs it
    r"Failed to load module script: Expected a JavaScript",  # Chromium: the 404 page is HTML, not a module
    r"Loading module from “[^”]*” was blocked because of a disallowed MIME type",  # Firefox: the same
    r"Loading failed for the module with source",  # Firefox: a module that did not arrive
    r"The stylesheet \S+ was not loaded because its MIME type",  # Firefox: a stylesheet answered with HTML
    r"Error$",  # Firefox: how it shows the error object React reports (the message is not in the text)
    r"Failed to load resource: WebKit encountered an internal error",  # WebKit: a request made while offline
]))


ROOT = re.compile(r"^https?://[^/]+/(\?[^#]*)?$")


def gone(route):
    """How the production nginx answers a file name that the current deployment does not have (its 404 page is not
    cached: without that header WebKit would keep the 404 in its memory cache and answer a later request with it)."""
    route.fulfill(status=404, content_type="text/html", headers={"cache-control": "no-cache"},
                  body="<!doctype html><title>Page not found</title><h1>Page not found</h1>")


def deployed(page, chunk, fixed_after_reload=True):
    """A deployment made after this tab opened: `chunk`, a file of the deployment the tab runs, is gone, and the site's
    index names another entry script (what tells a browser that does not name the failed file, such as Safari, that the
    site changed). With fixed_after_reload, a reload fetches the new deployment, whose files all exist; without, the
    new deployment lacks the file too. .calls lists the requests for the file."""
    reloaded, calls = [], []
    page.on("request", lambda r: reloaded.append(r.url) if r.is_navigation_request() and r.frame == page.main_frame else None)
    new = lambda: bool(reloaded) and fixed_after_reload  # noqa: E731

    def old_file(route):
        calls.append(route.request.url)
        route.continue_() if new() else gone(route)

    def index(route):
        if route.request.resource_type != "fetch" or new():
            return route.fallback()
        html = route.fetch().text()
        route.fulfill(status=200, content_type="text/html", headers={"cache-control": "no-cache"},
                      body=re.sub(r"/assets/index-[^\"']+\.js", "/assets/index-NewDeploy.js", html))
    page.route(ROOT, index)
    page.route(chunk, old_file)
    old_file.calls = calls
    return old_file


def failing_record():
    """A file that is gone, with .calls listing the requests for it."""
    calls = []

    def handler(route):
        calls.append(route.request.url)
        gone(route)
    handler.calls = calls
    return handler


def dropped_once():
    """A request the network drops once: the file is still there when asked again."""
    calls = []

    def handler(route):
        calls.append(route.request.url)
        route.abort("connectionreset") if len(calls) == 1 else route.continue_()
    return handler


def follow(page, href):
    """Click an in-site link to href, as a learner would: the app's router handles it without loading a page."""
    page.evaluate("""href => {
        const a = Object.assign(document.createElement('a'), { href, textContent: href })
        document.getElementById('main').append(a)
        a.click()
        a.remove()
    }""", href)


def document_loads(page):
    loads = []
    page.on("load", lambda p: loads.append(p.url))
    return loads


def home(page, site):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(site)
    expect(page.locator("#main h1")).to_be_visible()
    page.wait_for_load_state("networkidle")


def reloaded_recently(page, path):
    """As the app records an automatic reload for `path`: a second one within a minute is not made."""
    page.evaluate("([k, path]) => sessionStorage.setItem(k, JSON.stringify({ path, at: Date.now() }))", [MARK, path])


def stored(page):
    return json.loads(page.evaluate("localStorage.getItem('osa.progress.v2')") or "{}")


def address(url):
    """A page's address without a trailing slash: Python's server redirects /a/b to /a/b/ on a page load."""
    return re.sub(r"/+(?=$|[?#])", "", url, count=1)


def lesson_shown(page, lid, site):
    expect(page.get_by_test_id("lesson-facts")).to_be_visible()
    page.wait_for_load_state("load")  # a page can show before its load event: count a reload only once it is done
    assert address(page.url) == site.rstrip("/") + lesson_url(lid)


def shell_usable(page):
    """The header, tab bar and menu still work around the page area."""
    expect(page.get_by_test_id("tabbar")).to_be_visible()
    page.get_by_test_id("menu-open").click()
    expect(page.get_by_test_id("menu-close")).to_be_visible()
    page.get_by_test_id("menu-close").click()
    expect(page.get_by_test_id("menu-close")).to_have_count(0)


def unexpected(page):
    messages = [re.sub(r" \[[^\]]*\]$", "", e) for e in page.errors]
    return [m for m in messages if not EXPECTED.match(m)]


def test_a_missing_page_chunk_reloads_once_and_the_lesson_opens(page, static_site):
    home(page, static_site)
    loads = document_loads(page)
    chunk = deployed(page, LESSON)
    follow(page, lesson_url(FIRST) + "?from=home#overview")
    expect(page.get_by_test_id("lesson-facts")).to_be_visible()
    page.wait_for_load_state("load")
    assert len(loads) == 1, f"one automatic reload, not {loads}"
    assert address(page.url) == static_site.rstrip("/") + lesson_url(FIRST) + "?from=home#overview"  # all kept
    assert len(chunk.calls) >= 2
    follow(page, lesson_url(SECOND))
    lesson_shown(page, SECOND, static_site)
    assert unexpected(page) == []


def test_a_after_a_recent_reload_the_panel_shows_and_try_again_recovers(page, static_site):
    home(page, static_site)
    loads = document_loads(page)
    page.route(LESSON, gone)
    reloaded_recently(page, lesson_url(FIRST))
    follow(page, lesson_url(FIRST))
    panel = page.get_by_test_id("page-error")
    expect(panel).to_be_visible()
    expect(panel).to_have_attribute("data-kind", "chunk")
    expect(panel.locator("h1")).to_be_visible()
    expect(panel).to_contain_text("updated")
    expect(panel).to_contain_text("progress is saved in this browser")
    expect(page.get_by_test_id("page-reload")).to_be_visible()
    shell_usable(page)
    page.unroute(LESSON)
    page.get_by_test_id("page-retry").click()
    lesson_shown(page, FIRST, static_site)
    assert loads == [], "Try again loads the page in place, without reloading"
    expect(page.locator("#main h1").first).to_be_focused()  # not lost on the body with the button that was clicked
    follow(page, lesson_url(SECOND))
    lesson_shown(page, SECOND, static_site)
    assert unexpected(page) == []


def test_a_reload_from_the_panel_recovers(page, static_site):
    home(page, static_site)
    loads = document_loads(page)
    page.route(LESSON, gone)
    reloaded_recently(page, lesson_url(FIRST))
    follow(page, lesson_url(FIRST))
    expect(page.get_by_test_id("page-error")).to_be_visible()
    page.unroute(LESSON)
    page.get_by_test_id("page-reload").click()
    lesson_shown(page, FIRST, static_site)
    assert len(loads) == 1
    follow(page, lesson_url(SECOND))
    lesson_shown(page, SECOND, static_site)
    assert unexpected(page) == []


def test_b_offline_shows_the_panel_without_reloading_and_try_again_works_once_back(page, static_site):
    home(page, static_site)
    loads = document_loads(page)
    page.context.set_offline(True)
    follow(page, lesson_url(FIRST))
    panel = page.get_by_test_id("page-error")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text("offline")
    shell_usable(page)
    page.wait_for_timeout(1500)
    assert loads == [], "no reload while offline: it would replace the site with the browser's offline page"
    page.context.set_offline(False)
    expect(panel).not_to_contain_text("offline")  # the panel follows the connection
    page.get_by_test_id("page-retry").click()
    lesson_shown(page, FIRST, static_site)
    follow(page, lesson_url(SECOND))
    lesson_shown(page, SECOND, static_site)
    # Firefox loads the page in place. Chromium remembers the files it failed to fetch while offline and fails the
    # import again without asking: the server answers for the file, so one reload (keeping progress) recovers.
    assert len(loads) <= 1
    assert unexpected(page) == []


def test_b_a_dropped_request_while_online_shows_the_panel_and_is_tried_again_in_place(page, static_site):
    home(page, static_site)
    loads = document_loads(page)
    page.route(LESSON, dropped_once())  # not a deployment: the server still has the file, so no reload
    follow(page, lesson_url(FIRST))
    expect(page.get_by_test_id("page-error")).to_be_visible()
    page.wait_for_timeout(1500)
    assert loads == []
    page.get_by_test_id("page-retry").click()
    lesson_shown(page, FIRST, static_site)
    assert loads == []
    assert unexpected(page) == []


def test_b_a_network_that_fails_while_online_shows_the_panel_not_the_browser_error_page(page, static_site):
    """navigator.onLine stays true on Wi-Fi without internet, behind a captive portal or on a dropped mobile link: a
    reload then lands on the browser's error page and the site is gone. The server is asked first."""
    home(page, static_site)
    loads = document_loads(page)
    page.route("**/*", lambda route: route.abort("internetdisconnected") if route.request.resource_type == "document" else route.fallback())
    page.route(LESSON, lambda route: route.abort("internetdisconnected"))  # the page's code, and any request for it
    follow(page, lesson_url(FIRST))
    panel = page.get_by_test_id("page-error")
    expect(panel).to_be_visible()
    page.wait_for_timeout(2000)
    assert loads == [], f"no reload into the browser's error page: {loads}"
    assert address(page.url) == static_site.rstrip("/") + lesson_url(FIRST)
    shell_usable(page)
    page.unroute("**/*")
    page.unroute(LESSON)
    page.get_by_test_id("page-retry").click()
    lesson_shown(page, FIRST, static_site)
    assert unexpected(page) == []


def test_b_a_browser_that_wrongly_reports_offline_still_opens_pages(page, static_site):
    """Some systems (NetworkManager setups, VPNs, web views) report offline while the network works."""
    page.add_init_script("Object.defineProperty(Navigator.prototype, 'onLine', { configurable: true, get: () => false })")
    home(page, static_site)
    follow(page, lesson_url(FIRST))
    lesson_shown(page, FIRST, static_site)
    follow(page, "/me")
    expect(page.locator("#main h1")).to_be_visible()
    expect(page.get_by_test_id("page-error")).to_have_count(0)
    assert unexpected(page) == []


def test_c_progress_is_kept_through_the_failure_and_the_reload(page, static_site):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(static_site.rstrip("/") + lesson_url(SECOND))
    page.get_by_test_id("lesson-done").click()
    expect(page.get_by_test_id("lesson-done")).to_have_count(0)
    before = stored(page)
    assert before["lessons"][SECOND]["done"]
    loads = document_loads(page)
    deployed(page, LAB)
    follow(page, LAB_PATH)
    expect(page.get_by_test_id("lab-back")).to_be_visible()
    page.wait_for_load_state("load")
    assert len(loads) == 1
    after = stored(page)
    assert after["lessons"] == before["lessons"] and after["xp"] == before["xp"]
    follow(page, lesson_url(SECOND))
    expect(page.locator(".summary-facts")).to_contain_text("You finished reading this lesson")
    expect(page.get_by_test_id("lesson-done")).to_have_count(0)
    # and through the panel, on a page this tab has not opened yet: the panel says the progress is kept, and it is
    reloaded_recently(page, "/me")
    page.route(ME, gone)
    follow(page, "/me")
    expect(page.get_by_test_id("page-error")).to_contain_text("progress is saved in this browser")
    assert stored(page)["lessons"] == before["lessons"]
    page.unroute(ME)
    page.get_by_test_id("page-retry").click()
    expect(page.get_by_test_id("page-error")).to_have_count(0)
    expect(page.locator("#main h1")).to_be_visible()
    assert len(loads) == 1 and stored(page)["lessons"] == before["lessons"]
    assert unexpected(page) == []


def test_d_a_chunk_that_always_fails_reloads_exactly_once_then_shows_the_panel(page, static_site):
    home(page, static_site)
    loads = document_loads(page)
    deployed(page, LESSON, fixed_after_reload=False)  # the new deployment lacks the file too
    follow(page, lesson_url(FIRST))
    expect(page.get_by_test_id("page-error")).to_be_visible()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:  # long enough for a second reload to show
        page.wait_for_timeout(250)
    assert len(loads) == 1, f"exactly one automatic reload, not {loads}"
    assert address(page.url) == static_site.rstrip("/") + lesson_url(FIRST)
    shell_usable(page)
    assert unexpected(page) == []


def test_e_a_page_that_throws_shows_a_recovery_panel_without_reloading(page, static_site):
    home(page, static_site)
    loads = document_loads(page)
    broken = "export default function Broken() { throw new Error('test: this page is broken') }"
    page.route(LESSON, lambda route: route.fulfill(status=200, content_type="text/javascript", body=broken))
    follow(page, lesson_url(FIRST))
    panel = page.get_by_test_id("page-error")
    expect(panel).to_be_visible()
    expect(panel).to_have_attribute("data-kind", "render")
    expect(page.get_by_test_id("page-reload")).to_be_visible()
    expect(page.get_by_test_id("page-retry")).to_have_count(0)
    shell_usable(page)
    page.get_by_test_id("page-home").click()
    expect(page.get_by_test_id("page-error")).to_have_count(0)
    expect(page.locator("#main h1")).to_be_visible()
    assert loads == []
    assert [e for e in unexpected(page) if not re.match(r"(The page area caught: )?Error: test: this page is broken", e)] == []


@pytest.mark.parametrize("asset", [MODELS_JS, MODELS_CSS], ids=["script", "stylesheet"])
def test_f_models_that_failed_to_load_can_be_tried_again(page, static_site, asset):
    home(page, static_site)
    page.route(asset, gone)
    follow(page, MODEL_PATH)
    notice = page.get_by_test_id("studio-stage").get_by_test_id("model-error")
    expect(notice).to_be_visible()
    expect(page.get_by_test_id("page-error")).to_have_count(0)  # the Studio page itself is there
    expect(page.locator("#main h1")).to_be_visible()
    page.unroute(asset)
    notice.get_by_test_id("model-retry").click()
    expect(page.locator("[data-sim=traffic]")).to_be_visible()
    styled = page.evaluate("""() => [...document.styleSheets].some((s) => {
        try { return /\\/assets\\/sims-[^/]+\\.css/.test(s.href || '') && s.cssRules.length > 0 } catch { return false } })""")
    assert styled, "the models' stylesheet is loaded, not only their code"
    assert unexpected(page) == []


@pytest.mark.parametrize("reported", ["online", "offline"])
def test_f_a_lesson_whose_model_cannot_load_still_shows_the_lesson(page, static_site, reported):
    if reported == "offline":  # the browser says offline (rightly or not): the notice says so, the lesson still opens
        page.add_init_script("Object.defineProperty(Navigator.prototype, 'onLine', { configurable: true, get: () => false })")
    home(page, static_site)
    loads = document_loads(page)
    page.route(MODELS_JS, gone)
    follow(page, lesson_url(FIRST) + "?a=traffic")  # the lesson's "explore" activity embeds the traffic model
    notice = page.get_by_test_id("model-error")
    expect(notice).to_be_visible()
    expect(page.get_by_test_id("lesson-facts")).to_be_visible()
    expect(page.get_by_test_id("page-error")).to_have_count(0)
    expect(notice).to_contain_text("model could not load")
    expect(notice).not_to_contain_text("page could not load")
    if reported == "offline":
        expect(notice).to_contain_text("offline")
    page.unroute(MODELS_JS)
    notice.get_by_test_id("model-retry").click()
    expect(page.locator("[data-sim=traffic]")).to_be_visible()
    assert loads == []
    assert unexpected(page) == []


def test_f_a_diagram_does_not_need_the_models(page, static_site):
    home(page, static_site)
    loads = document_loads(page)
    models = failing_record()
    page.route(MODELS_JS, models)
    follow(page, "/studio/diagram/control-loop")
    expect(page.get_by_test_id("diagram-control-loop")).to_be_visible()
    deadline = time.monotonic() + 5
    while not models.calls and time.monotonic() < deadline:  # the model list is still asked for, and fails
        page.wait_for_timeout(100)
    assert models.calls
    page.wait_for_timeout(1500)
    expect(page.get_by_test_id("diagram-control-loop")).to_be_visible()
    assert loads == []
    expect(page.get_by_test_id("page-error")).to_have_count(0)
    expect(page.get_by_test_id("studio-stage").get_by_test_id("model-error")).to_have_count(0)
    assert unexpected(page) == []
