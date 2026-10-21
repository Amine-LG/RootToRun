"""The home page as learners really reach it (first visit, a lesson opened, browser Back, a returning learner) and the
layout system (reading measure, wide content, the sticky page bar, phones down to 320 px). Assertions are on rendered
geometry: what the learner sees, not class names. Static site, no cluster."""
import json
import re
from urllib.parse import unquote

import pytest
from playwright.sync_api import expect
from addresses import lesson_url
from conftest import wait_true

LESSON_WIDE = "/learn/kubernetes/why-your-change-did-not-stick"  # prose, a recorded terminal, a model
LESSON_FIRST = "/learn/linux/your-first-minutes-in-a-shell"


def ctx_page(browser, w, h=900, progress=None, clock=False):
    """clock=True: the page's clock (timers, animation frames, performance.now) runs normally but can be moved ahead
    with page.clock.run_for(ms), so a test sees what happens seconds later without waiting for it."""
    ctx = browser.new_context(viewport={"width": w, "height": h})
    if progress is not None:
        ctx.add_init_script(f"localStorage.setItem('osa.progress.v2', {json.dumps(json.dumps(progress))})")
    page = ctx.new_page()
    if clock:
        page.clock.install()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    return ctx, page


def scrolled_past(page, y):
    """Waits for a wheel scroll to land (it is applied asynchronously) and says where the page is."""
    for _ in range(50):
        if page.evaluate("scrollY") > y:
            break
        page.wait_for_timeout(50)
    return page.evaluate("scrollY")


LATE = 3500  # longer than the router's wait for content (lib/router.ts: 3 s): a late jump would show after it


def ready(page):
    page.wait_for_selector("main .page:not(:has(.sk-page))")
    page.wait_for_load_state("networkidle")


def box(page, sel):
    return page.locator(sel).first.evaluate("e => { const r = e.getBoundingClientRect(); return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width} }")


def no_page_overflow(page):
    w, inner = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
    assert w <= inner, f"the page scrolls sideways: {w} > {inner}"


def assert_returning_home(page, wide: bool):
    """The returning layout, whole and coherent: nothing from the first visit, the courses beside (or under) the hero,
    the route asked in one line, and every 'continue' pointing at the same lesson."""
    expect(page.get_by_test_id("welcome")).to_be_visible()
    expect(page.get_by_test_id("intro")).to_have_count(0)
    expect(page.locator("#how-h")).to_have_count(0)
    expect(page.get_by_test_id("first-moment")).to_have_count(0)
    expect(page.get_by_test_id("route-now")).to_be_visible()
    expect(page.get_by_test_id("route-beginner")).to_be_hidden()  # folded: not asked again in full
    no_page_overflow(page)
    hero, copy, path = box(page, ".hx-hero"), box(page, ".hx-copy"), box(page, "[data-testid=path-card]")
    if wide:
        # the courses sit beside the resume column, at the hero's right edge, as on a first visit: not stranded below
        assert path["l"] > copy["r"], (copy, path)
        assert abs(path["r"] - hero["r"]) <= 2, (hero, path)
        assert path["t"] < copy["b"], (copy, path)
    else:
        # phones: one column, the courses panel uses the whole width
        assert abs(path["w"] - hero["w"]) <= 2 and path["t"] >= copy["b"], (hero, copy, path)
    cont = page.get_by_test_id("hero-continue").get_attribute("href")
    resume = page.get_by_test_id("today-resume")
    if resume.count():
        assert resume.get_attribute("href") == cont, "the next session must start where Continue goes"


@pytest.mark.parametrize("how", ["click", "goto"])
@pytest.mark.parametrize("w", [1440, 390])
def test_home_after_opening_a_lesson_and_going_back(browser, static_site, how, w):
    """The reported problem: a first-time visitor scrolls down the home page, opens a lesson, comes back. The page is now
    the returning learner's (opening a lesson is progress), so the position saved on the first-visit layout must not be
    restored into it, early or three seconds late, and the returning layout must hold together."""
    site = static_site.rstrip("/")
    ctx, page = ctx_page(browser, w, 900 if w > 600 else 844, clock=True)
    page.goto(site + "/")
    ready(page)
    expect(page.get_by_test_id("intro")).to_be_visible()
    first_path = box(page, "[data-testid=path-card]")
    page.locator("#start-from").scroll_into_view_if_needed()
    page.mouse.wheel(0, 300)
    assert scrolled_past(page, 400) > 400
    if how == "click":
        page.get_by_test_id("start-learning").click()
    else:
        page.goto(site + LESSON_FIRST)
    ready(page)
    page.mouse.wheel(0, 1500)
    assert scrolled_past(page, 0) > 0
    page.go_back()
    ready(page)
    page.clock.run_for(LATE)
    assert page.evaluate("scrollY") == 0, "Back restored a position from the first-visit layout"
    assert_returning_home(page, wide=w > 960)
    if w > 960:
        same = box(page, "[data-testid=path-card]")
        assert abs(same["l"] - first_path["l"]) <= 2 and abs(same["w"] - first_path["w"]) <= 2, (first_path, same)
    # Forward then Back again: still the same page, still at the top
    page.go_forward()
    ready(page)
    page.go_back()
    ready(page)
    page.clock.run_for(LATE)
    assert page.evaluate("scrollY") == 0
    assert_returning_home(page, wide=w > 960)
    assert page.errors == []
    ctx.close()


@pytest.mark.parametrize("w", [1440, 390])
def test_back_to_a_changed_layout_stays_at_the_top_where_the_old_position_exists(browser, static_site, w):
    """The layout rule on its own: the position saved on the first-visit layout is one the returning layout can also
    reach, so only the layout check keeps Back at the top (the "unreachable position" rule cannot help here). The
    same-layout test above is the control: there the position is restored."""
    site = static_site.rstrip("/")
    y = 150
    ctx, page = ctx_page(browser, w, 900 if w > 600 else 844, clock=True)
    page.goto(site + "/")
    ready(page)
    expect(page.get_by_test_id("intro")).to_be_visible()
    page.evaluate(f"window.scrollTo(0, {y})")
    assert page.evaluate("scrollY") == y
    # follow the link where it is, without scrolling to it first: the router saves the position at this moment
    page.get_by_test_id("start-learning").evaluate("a => a.click()")
    expect(page.locator(".lesson-h h1")).to_be_visible()
    page.go_back()
    ready(page)
    expect(page.get_by_test_id("welcome")).to_be_visible()  # the returning layout
    page.clock.run_for(LATE)
    assert page.evaluate("scrollY") == 0, "Back restored a position saved on the first-visit layout"
    page.evaluate(f"window.scrollTo(0, {y})")
    assert page.evaluate("scrollY") == y  # the position exists on this layout too
    ctx.close()


def test_back_to_the_same_home_layout_restores_the_reading_position(browser, static_site):
    """Restoration still works where it should: a returning learner who scrolled the home page and opened a course comes
    back to where they were."""
    site = static_site.rstrip("/")
    prog = {"v": 2, "lessons": {"lx.first-steps": {"seen": 1, "done": 1}}, "days": ["2026-01-01"],
            "last": {"href": lesson_url("lx.shell-basics"), "title": "How a command is built", "at": 1}}
    ctx, page = ctx_page(browser, 390, 844, prog)
    page.goto(site + "/")
    ready(page)
    page.evaluate("window.scrollTo(0, 600)")
    page.wait_for_timeout(300)
    page.locator("[data-testid=path-card] a[href='/learn/containers']").click()
    ready(page)
    page.go_back()
    ready(page)
    page.wait_for_timeout(500)
    assert abs(page.evaluate("scrollY") - 600) <= 2
    ctx.close()


def test_returning_learner_sees_one_journey(browser, static_site):
    """Continue, the next session and the courses agree: the lesson being read comes first in the session, the lesson
    after it follows, and its course is marked as where the learner is."""
    site = static_site.rstrip("/")
    prog = {"v": 2, "lessons": {"b.reconciliation": {"seen": 1}}, "days": ["2026-01-01"],
            "last": {"href": LESSON_WIDE, "title": "Why your change did not stick", "at": 1}}
    ctx, page = ctx_page(browser, 1440, 900, prog)
    page.goto(site + "/")
    ready(page)
    cont = page.get_by_test_id("hero-continue")
    expect(cont).to_have_attribute("href", LESSON_WIDE)
    expect(page.get_by_test_id("today-resume")).to_have_attribute("href", LESSON_WIDE)
    nxt = page.get_by_test_id("today-lesson").get_attribute("href")
    assert nxt not in (LESSON_WIDE, LESSON_FIRST), nxt  # not back to the very first lesson of the whole course
    expect(page.get_by_test_id("course-here")).to_contain_text("Kubernetes")
    assert_returning_home(page, wide=True)
    # the route question is one line; it opens on request and still works
    page.get_by_test_id("route-now").locator("summary").click()
    page.get_by_test_id("route-knows-containers").click()
    expect(page.get_by_test_id("route-now")).to_contain_text("I know Linux and containers")
    ctx.close()


def test_the_home_page_has_no_mini_quiz(page, static_site):
    page.goto(static_site)
    ready(page)
    expect(page.get_by_test_id("path-card")).to_be_visible()
    expect(page.get_by_test_id("first-moment")).to_have_count(0)
    expect(page.get_by_text("A moment from the first lesson")).to_have_count(0)
    expect(page.locator("main button[data-choice]")).to_have_count(0)  # no answer buttons on the home page


@pytest.mark.parametrize("w", [1440, 1920])
def test_lesson_prose_keeps_its_measure_while_wide_content_uses_the_room(browser, static_site, w):
    site = static_site.rstrip("/")
    ctx, page = ctx_page(browser, w)
    page.goto(site + LESSON_WIDE)
    ready(page)
    paras = page.locator(".lesson-article .act-learn .prose p").evaluate_all("ps => ps.map(p => p.getBoundingClientRect().width)")
    assert paras and max(paras) <= 700 and max(paras) >= 560, paras  # about 68 characters of the reading face
    term = box(page, ".lesson-article .flow-step.act-show figure")
    stage = box(page, ".lesson-article .explore-stage")
    for b in (term, stage):
        assert b["w"] >= max(paras) + 180, (b, max(paras))  # terminals and models are wider than the prose
        assert b["r"] <= w - 40, b  # and stay inside the frame
    assert term["w"] >= (860 if w == 1440 else 1000), term
    q = box(page, ".lesson-article .check-q")
    assert q["w"] <= 780, q  # questions stay at a comfortable text width
    no_page_overflow(page)
    ctx.close()


def test_a_lesson_does_not_scroll_itself_when_it_opens(browser, static_site):
    """Regression: the contents list, rendered open, fired its toggle event early in the page's life and the page jumped
    100-200 px down on load."""
    site = static_site.rstrip("/")
    ctx, page = ctx_page(browser, 1024, 768)
    # a fast load, in every browser: the page's clock reads as if it had started moments ago (a cached page in Chrome
    # renders its contents within 600 ms; a test machine may not)
    ctx.add_init_script("{ const now = performance.now.bind(performance); performance.now = () => now() - 10000 }")
    for path in (LESSON_FIRST, LESSON_WIDE, "/learn/platform-administration/rbac-and-effective-permissions"):
        page.goto(site + path)
        ready(page)
        page.wait_for_timeout(600)
        assert page.evaluate("scrollY") == 0, path
    ctx.close()


def test_page_bar_stays_in_reach_and_clear_of_headings(browser, static_site):
    """On wide screens the page bar (way back, pager, contribution actions' slot) stays under the site header; a section
    reached from the contents lands below it, not under it. On phones it scrolls away."""
    site = static_site.rstrip("/")
    ctx, page = ctx_page(browser, 1440)
    page.goto(site + LESSON_WIDE)
    ready(page)
    expect(page.get_by_test_id("page-bar").locator("[data-testid=page-actions-slot]")).to_have_count(1)
    page.evaluate("window.scrollTo(0, 2500)")
    page.wait_for_timeout(300)
    header, bar = box(page, ".topbar"), box(page, "[data-testid=page-bar]")
    assert abs(bar["t"] - header["b"]) <= 1, (header, bar)
    rail = box(page, ".flow-parts")
    assert rail["t"] >= bar["b"], (bar, rail)  # the contents column is not under the bar
    page.get_by_test_id("toc-link").nth(3).click()
    page.wait_for_timeout(800)
    target = page.get_by_test_id("toc-link").nth(3).get_attribute("href")
    head = box(page, target)
    assert bar["b"] <= head["t"] <= bar["b"] + 60, (bar, head)
    ctx.close()
    ctx, page = ctx_page(browser, 390, 844)
    page.goto(site + LESSON_WIDE)
    ready(page)
    page.evaluate("window.scrollTo(0, 2500)")
    page.wait_for_timeout(300)
    assert box(page, "[data-testid=page-bar]")["b"] < 0  # scrolled away; the contents bar is the sticky one here
    ctx.close()


@pytest.mark.parametrize("w", [320, 390])
def test_nothing_is_wider_than_a_small_phone(browser, static_site, w):
    site = static_site.rstrip("/")
    returning = {"v": 2, "lessons": {"b.reconciliation": {"seen": 1}}, "days": ["2026-01-01"],
                 "last": {"href": LESSON_WIDE, "title": "Why your change did not stick", "at": 1}}
    for prog, paths in ((None, ["/", LESSON_WIDE, "/labs/deploy-expose-and-scale-an-application", "/studio/model/reconcile", "/map", "/learn"]),
                        (returning, ["/"])):
        ctx, page = ctx_page(browser, w, 640, prog)
        for path in paths:
            page.goto(site + path)
            ready(page)
            no_page_overflow(page)
        ctx.close()


# ---------------------------------------------------------------- the header: search, theme, phone menu
def test_search_is_a_combobox_with_a_listbox_and_enter_opens_the_active_result(page, static_site):
    page.goto(static_site)
    ready(page)
    page.keyboard.press("Control+k")
    field = page.get_by_test_id("palette-input")
    expect(field).to_be_focused()
    expect(field).to_have_attribute("role", "combobox")
    # a visible focus indicator on the field's row (the field itself draws none)
    ring = page.locator(".palette-in").evaluate("e => getComputedStyle(e).boxShadow + '|' + getComputedStyle(e).outlineStyle")
    assert ring.split("|")[0] != "none" or ring.split("|")[1] != "none", ring
    field.fill("request path")
    listbox = page.locator(f"#{field.get_attribute('aria-controls')}")
    expect(listbox).to_have_attribute("role", "listbox")
    options = listbox.locator("[role=option]")
    # models and diagrams join the results when their data has arrived (a slow network: later)
    wait_true(page, "document.querySelectorAll('#pal-list [role=option]').length >= 3")
    expect(listbox.locator("a, button, [tabindex]")).to_have_count(0)  # options are not links or tab stops
    first = field.get_attribute("aria-activedescendant")
    expect(page.locator(f"#{first}")).to_have_attribute("aria-selected", "true")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    active = page.locator(f"#{field.get_attribute('aria-activedescendant')}")
    assert active.get_attribute("id") != first
    expect(active).to_have_attribute("aria-selected", "true")
    expect(listbox.locator("[aria-selected=true]")).to_have_count(1)
    target = active.get_attribute("data-href")  # the address of the result the arrows reached
    page.keyboard.press("Enter")
    expect(page.locator(".palette-wrap")).to_have_count(0)
    ready(page)
    here = page.evaluate("location.pathname + location.search + location.hash")
    assert unquote(here) == unquote(target), (here, target)
    # a click on an option opens it too
    page.keyboard.press("Control+k")
    page.get_by_test_id("palette-input").fill("OOMKilled")
    page.locator("#pal-list [role=option]").first.click()
    expect(page).to_have_url(re.compile(r"/incidents/"))
    assert page.errors == []


def test_theme_toggle_says_what_it_does_and_its_state(page, static_site):
    page.goto(static_site)
    ready(page)
    toggle = page.get_by_role("button", name="Dark theme")
    dark = page.evaluate("document.documentElement.dataset.theme") == "dark"
    expect(toggle).to_have_attribute("aria-pressed", "true" if dark else "false")
    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "false" if dark else "true")
    assert page.evaluate("document.documentElement.dataset.theme") == ("light" if dark else "dark")


def test_phone_menu_is_modal(browser, static_site):
    ctx, page = ctx_page(browser, 390, 844)
    page.goto(static_site.rstrip("/") + "/learn")
    ready(page)
    toggle = page.locator(".nav-toggle")
    toggle.click()
    sheet = page.get_by_role("dialog", name="Menu")
    expect(sheet).to_have_attribute("aria-modal", "true")
    for sel in ("main", ".site-foot", ".subnav"):
        assert page.locator(sel).evaluate("e => e.inert"), sel  # nothing behind the sheet is reachable
    page.keyboard.press("Escape")
    expect(toggle).to_be_focused()
    for sel in ("main", ".site-foot"):
        assert not page.locator(sel).evaluate("e => e.inert"), sel
    ctx.close()


# ---------------------------------------------------------------- the actions slot on every detail page, compact on phones
from test_contribute_everywhere import repo_site  # noqa: E402,F401  (the export with a repository address)


@pytest.mark.parametrize("path", ["/diagnostic/linux"])  # course pages have none (test_contribute_everywhere.py)
def test_diagnostic_and_path_pages_have_the_actions_in_the_page_bar(browser, repo_site, path):
    ctx, page = ctx_page(browser, 1440)
    page.goto(repo_site + path)
    ready(page)
    actions = page.locator("[data-testid=page-bar] [data-testid=page-actions-slot] [data-testid=page-actions]")
    expect(actions).to_be_visible()
    expect(page.locator(".pa-float")).to_have_count(0)
    bar, title = box(page, "[data-testid=page-bar]"), box(page, "main h1")
    assert bar["b"] <= title["t"], (bar, title)  # above the title, never beside or over it
    ctx.close()


@pytest.mark.parametrize("w", [320, 390])
def test_page_bar_is_compact_on_phones(browser, repo_site, w):
    """At most two rows: the way back and the actions share the first; the pager and "Go deeper" the second. A bar
    with nothing else (runbooks, cases) is one row."""
    from addresses import lab_url
    ctx, page = ctx_page(browser, w, 700)
    for path, rows in ((LESSON_WIDE, 2), (lab_url("inc.dns-typo"), 2), ("/runbook/rb.route-503", 1), ("/case/case.friday-release", 1),
                       ("/diagnostic/linux", 1)):
        page.goto(repo_site + path)
        ready(page)
        bar = box(page, "[data-testid=page-bar]")
        slot = box(page, "[data-testid=page-bar] [data-testid=page-actions-slot]")
        first = page.locator("[data-testid=page-bar] > :first-child").evaluate("e => { const r = e.getBoundingClientRect(); return {t: r.top, b: r.bottom, w: r.width} }")
        assert slot["t"] < first["b"] and first["t"] < slot["b"], (path, first, slot)  # on the same row
        assert first["w"] >= min(160, 0.5 * bar["w"]), (path, first)  # the way back stays readable, not squeezed
        assert bar["b"] - bar["t"] <= rows * 44 + 12, (path, bar)
        no_page_overflow(page)
    ctx.close()


def test_the_setup_guide_is_linked_from_reference_the_phone_menu_and_the_footer(browser, static_site):
    site = static_site.rstrip("/")
    ctx, page = ctx_page(browser, 1440)
    page.goto(site + "/commands")
    ready(page)
    page.locator(".subnav a[href='/setup']").click()
    ready(page)
    expect(page.locator(".subnav a[href='/setup']")).to_have_attribute("aria-current", "page")
    expect(page.locator(".topnav a.on")).to_have_text("Reference")
    expect(page.locator(".site-foot a[href='/setup']")).to_be_visible()
    ctx.close()
    ctx, page = ctx_page(browser, 390, 844)
    page.goto(site + "/learn")
    ready(page)
    page.locator(".nav-toggle").click()
    expect(page.get_by_role("dialog", name="Menu").locator("a[href='/setup']")).to_be_visible()
    ctx.close()
