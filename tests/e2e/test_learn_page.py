"""The Learn page (/learn): one place to continue, your route, then the courses in the order they build."""
import json
import re

from playwright.sync_api import expect
from addresses import diag_url, lesson_url, track_url

COURSES = ["linux", "containers", "start", "admin1", "admin2", "platform"]


def open_(page, site, route="/learn"):
    page.goto(site.rstrip("/") + route)
    page.wait_for_selector("main .page:not(:has(.sk-page))")


def seeded(browser, progress, viewport=(1360, 900)):
    """A context whose first load starts from `progress` (later loads keep whatever the page saved)."""
    ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, reduced_motion="reduce")
    script = "if (!sessionStorage.getItem('learn-seeded')) {"
    script += f"localStorage.setItem('osa.progress.v2', {json.dumps(json.dumps(progress))});"
    ctx.add_init_script(script + "sessionStorage.setItem('learn-seeded','1');}")
    return ctx


def test_first_visit_has_one_clear_start_and_the_courses_in_order(page, static_site):
    open_(page, static_site)
    expect(page.get_by_role("heading", level=1)).to_have_text("Start from the beginning")
    go = page.get_by_test_id("learn-continue")
    expect(go).to_have_text(re.compile("Start with your first shell lesson"))
    expect(go).to_have_attribute("href", lesson_url("lx.first-steps"))
    assert page.locator(".btn.primary:visible").count() == 1, "one primary action on the page"
    # the courses, in order, each one link to its course page, with its purpose and what it builds on
    rows = page.locator(".jmap > .jm-stop")
    expect(rows).to_have_count(6)
    for i, track in enumerate(COURSES):
        row = page.get_by_test_id(f"map-{track}")
        expect(row.get_by_role("link")).to_have_attribute("href", track_url(track))
        assert rows.nth(i).get_attribute("data-testid") == f"map-{track}"
    expect(page.get_by_test_id("map-containers")).to_contain_text("Builds on Linux")
    expect(page.get_by_test_id("map-linux")).to_contain_text("No prerequisites")
    expect(page.get_by_test_id("map-practice").get_by_role("link")).to_have_attribute("href", "/learn/practice")
    assert page.locator(".jm-row.off").count() == 0, "with no route, no course is set apart"
    # every course link on the page leads somewhere
    for href in {a.get_attribute("href") for a in page.locator("main a[href^='/learn/']").all()}:
        assert page.request.get(static_site.rstrip("/") + href).status == 200, href
    assert page.errors == []


def test_choosing_a_route_emphasises_its_courses_and_hides_nothing(page, static_site):
    open_(page, static_site)
    page.get_by_test_id("route-select").select_option("kube-to-openshift")
    expect(page.locator(".jm-row.off")).not_to_have_count(0)
    assert page.locator(".jm-row.on, .jm-row.part").count() >= 1
    expect(page.locator(".jm-row")).to_have_count(7)  # nothing is hidden by a route
    expect(page.get_by_test_id("map-route-note")).to_contain_text("You use Kubernetes")
    expect(page.get_by_test_id("learn-continue")).to_have_attribute("href", lesson_url("b.crds-operators"))  # the route's own first step
    page.reload()
    page.wait_for_selector("main .page:not(:has(.sk-page))")
    expect(page.get_by_test_id("route-select")).to_have_value("kube-to-openshift")
    page.get_by_test_id("route-select").select_option("")
    expect(page.locator(".jm-row.off")).to_have_count(0)
    assert page.errors == []


def test_compare_routes_goes_to_the_home_page_chooser(page, static_site):
    open_(page, static_site)
    link = page.get_by_role("link", name="Compare routes")
    expect(link).to_have_attribute("href", "/#start-from")
    link.click()
    expect(page).to_have_url(re.compile(r"/#start-from$"))
    expect(page.get_by_test_id("route-beginner")).to_be_visible()


def test_a_returning_learner_continues_on_their_route(browser, static_site):
    ctx = seeded(browser, {"v": 2, "route": "beginner", "days": ["2026-01-01"], "lessons": {"lx.first-steps": {"seen": 1, "done": 1}}})
    try:
        page = ctx.new_page()
        open_(page, static_site)
        expect(page.get_by_role("heading", level=1)).to_have_text("Continue where you left off")
        go = page.get_by_test_id("learn-continue")
        expect(go).to_have_text(re.compile("Continue"))
        href = go.get_attribute("href")
        assert href.startswith(track_url("linux") + "/") and href != lesson_url("lx.first-steps"), href  # the next lesson, not the one already read
        here = page.locator(".jm-row.here")
        expect(here).to_have_count(1)
        expect(here).to_have_attribute("data-testid", "map-linux")
        expect(here).to_contain_text("Continue here")
        expect(here).to_contain_text("1 of 18 completed")
        expect(page.get_by_test_id("learn-route")).to_contain_text("1 of ")
        go.click()
        expect(page).to_have_url(re.compile(re.escape(href)))
    finally:
        ctx.close()


def test_phone_has_no_horizontal_scroll_and_the_start_is_on_the_first_screen(browser, static_site):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    try:
        page = ctx.new_page()
        open_(page, static_site)
        box = page.get_by_test_id("learn-continue").bounding_box()
        assert box["y"] >= 0 and box["y"] + box["height"] <= 844, box
        assert page.evaluate("document.documentElement.scrollWidth") <= 390
        for track in [*COURSES, "practice"]:
            row = page.get_by_test_id(f"map-{track}")
            assert row.bounding_box()["width"] <= 390
    finally:
        ctx.close()


def test_courses_are_reachable_and_visibly_focused_from_the_keyboard(page, static_site):
    open_(page, static_site)
    link = page.get_by_test_id("map-linux").get_by_role("link")
    link.focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    expect(link).to_be_focused()
    outline = page.evaluate("(a) => getComputedStyle(a, '::after').outlineStyle", link.element_handle())
    assert outline != "none", "the focused course row shows an outline"
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"/learn/linux$"))


def test_a_course_page_says_what_it_builds_on_and_what_comes_next(page, static_site):
    open_(page, static_site, "/learn/containers")
    expect(page.get_by_role("link", name="All courses")).to_have_attribute("href", "/learn")
    expect(page.locator(".ln-from").get_by_role("link", name="Linux")).to_have_attribute("href", "/learn/linux")
    expect(page.get_by_test_id("next-course")).to_have_attribute("href", track_url("start"))
    expect(page.locator(".chapter.open")).to_have_count(1)
    assert page.locator(".btn.primary:visible").count() == 1


def test_every_continue_agrees_and_follows_the_route(browser, static_site):
    """Regression: on the Kubernetes-to-OpenShift route, Home's hero sent the learner back to the first Linux lesson,
    the welcome card offered to "continue" a finished lesson, and the lesson's Next walked the whole course."""
    progress = {"v": 2, "route": "kube-to-openshift", "days": ["2026-01-01"],
                "lessons": {"b.crds-operators": {"seen": 1, "done": 1}, "k.kubectl-to-oc": {"seen": 1, "done": 1},
                            "c.openshift-extends": {"seen": 1, "done": 1}},
                "last": {"href": lesson_url("c.openshift-extends"), "title": "A platform run by operators", "at": 1}}
    ctx = seeded(browser, progress)
    page = ctx.new_page()
    open_(page, static_site, "/")
    target = page.get_by_test_id("hero-continue").get_attribute("href")
    assert target not in (lesson_url("lx.first-steps"), lesson_url("c.openshift-extends")), target
    # one resume action on the returning learner's first screen (it used to be repeated in a second card)
    expect(page.get_by_test_id("welcome").get_by_test_id("hero-continue")).to_have_count(1)
    open_(page, static_site, "/learn")
    expect(page.get_by_test_id("learn-continue")).to_have_attribute("href", target)
    # the route skips the applications module after the CLI lesson: Next follows the route, not the course
    open_(page, static_site, lesson_url("o1.cli"))
    expect(page.get_by_test_id("pager-next")).not_to_have_attribute("href", lesson_url("o1.deploy-apps"))
    ctx.close()


def test_a_chosen_route_starts_at_its_own_beginning_everywhere(browser, static_site):
    """Regression: with only a route chosen, Home sent the learner to the first Linux lesson while Learn and Progress
    sent them elsewhere."""
    ctx = seeded(browser, {"v": 2, "route": "refresh"})
    page = ctx.new_page()
    open_(page, static_site, "/")
    expect(page.get_by_test_id("hero-continue")).to_have_attribute("href", diag_url("admin1"))
    open_(page, static_site, "/learn")
    expect(page.get_by_test_id("learn-continue")).to_have_attribute("href", diag_url("admin1"))
    open_(page, static_site, "/me")
    expect(page.locator("a.btn.primary.lg").first).to_have_attribute("href", diag_url("admin1"))
    ctx.close()


def test_a_finished_route_leads_to_practice_not_back_to_linux(browser, static_site):
    page0 = browser.new_page()
    page0.goto(static_site.rstrip("/") + "/data/en/curriculum.json")
    cur = json.loads(page0.locator("body").inner_text())
    page0.close()
    r = next(x for x in cur["routes"] if x["id"] == "kube-to-openshift")
    mods = [m for s in r["steps"] for m in (next((t["modules"] for t in cur["tracks"] if t["id"] == s), [s]))]
    lessons = [l for m in mods for l in next((x["lessons"] for x in cur["modules"] if x["id"] == m), [])]
    ctx = seeded(browser, {"v": 2, "route": "kube-to-openshift", "days": ["2026-01-01"], "lessons": {l: {"seen": 1, "done": 1} for l in lessons}})
    page = ctx.new_page()
    open_(page, static_site, "/")
    expect(page.get_by_test_id("hero-continue")).to_have_attribute("href", "/learn/practice")
    open_(page, static_site, "/me")
    expect(page.locator("a.btn.primary.lg").first).to_have_attribute("href", "/learn/practice")
    ctx.close()


def test_a_same_page_anchor_scrolls_to_its_target_after_navigation(page, static_site):
    """Regression: an in-page link (#start-from) after arriving from another page restored that page's position."""
    # a course page (opening a lesson would make this a returning learner, whose home has no "starting point" link)
    open_(page, static_site, "/learn/platform-administration")
    page.evaluate("window.scrollTo(0, 1200)")
    page.wait_for_timeout(300)
    page.locator("a[href='/']").first.click()
    page.wait_for_selector("#start-from", state="attached")
    page.locator("a.hero-alt[href='#start-from']").click()
    page.wait_for_timeout(400)
    top = page.evaluate("document.getElementById('start-from').getBoundingClientRect().top")
    assert 0 <= top < 300, top
