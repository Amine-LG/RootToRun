"""A first visit on a 360 px phone: can the visitor reach a first lesson, a lab and a challenge, and does each page say
truthfully what this website does with it? Each test guards one finding of the phone discoverability audit (the home
button, the starting-point picker, the practice arena rows, the boxes at the top of labs and challenges)."""
import pytest
from playwright.sync_api import expect
from addresses import lab_url, lesson_at, track_url
from conftest import wait_true

PHONE = {"width": 360, "height": 740}


def phone(browser, motion="no-preference"):
    ctx = browser.new_context(viewport=PHONE, has_touch=True, reduced_motion=motion)
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    return ctx, page


def open_(page, site, path):
    page.goto(site.rstrip("/") + path)
    page.wait_for_selector("main h1")
    page.wait_for_selector("main .sk-page", state="detached")


# what a visitor really sees: between the sticky header and the phone's tab bar
ON_SCREEN = """sel => {
  const r = document.querySelector(sel)?.getBoundingClientRect()
  if (!r) return false
  const head = document.querySelector('.topbar')?.getBoundingClientRect().bottom ?? 0
  const tabs = document.querySelector('.shell > .tabbar')
  const foot = tabs && getComputedStyle(tabs).display !== 'none' ? tabs.getBoundingClientRect().top : innerHeight
  return r.top >= head && r.bottom <= foot
}"""


def test_the_home_main_button_opens_the_courses_first_lesson(browser, static_site):
    """The main button said "Start with application operations" and opened the course page, one more decision away
    from a lesson. It opens the lesson the course page's Begin button opens; the course stays one tap away."""
    ctx, page = phone(browser)
    open_(page, static_site, "/")
    start = page.get_by_test_id("hero-start")
    expect(start).to_be_visible()
    # who the direct entry is for, tied to the button for screen readers, with the beginner's way in right below
    expect(page.get_by_test_id("hero-level")).to_have_text("Intermediate: assumes Kubernetes basics.")
    expect(page.get_by_test_id("hero-level")).to_be_in_viewport()
    assert start.get_attribute("aria-describedby") == "hx-level"
    expect(page.locator(".hx-new a")).to_be_in_viewport()
    href = start.get_attribute("href")
    assert lesson_at(href), f"the main button does not open a lesson: {href}"
    expect(page.get_by_test_id("path-card").locator(f'a[href="{track_url("admin1")}"]')).to_have_count(1)
    open_(page, static_site, track_url("admin1"))
    assert page.get_by_test_id("path-next").get_attribute("href") == href, "not the lesson the course's Begin opens"
    open_(page, static_site, "/")
    page.get_by_test_id("hero-start").tap()
    page.wait_for_selector(".lesson-h h1")
    assert lesson_at(page.url) == lesson_at(href)
    assert page.errors == []
    ctx.close()


def test_the_home_page_says_labs_and_incidents_replay_in_the_browser(browser, static_site):
    ctx, page = phone(browser)
    open_(page, static_site, "/")
    how = page.locator(".hx-how li").nth(2)
    expect(how).to_contain_text("in your browser")
    expect(page.locator(".hx-lede")).not_to_contain_text("practise on your own local cluster when you are ready")
    ctx.close()


@pytest.mark.parametrize("motion", ["no-preference", "reduce"])
def test_choosing_a_starting_point_brings_its_start_button_on_screen(browser, static_site, motion):
    """After a tap on a starting point only its check mark changed on screen: the result and its button appeared below
    the phone's tab bar. The button is now scrolled into view (instantly when the visitor asks for reduced motion)."""
    ctx, page = phone(browser, motion)
    open_(page, static_site, "/")
    page.locator("#start-from .route-picks").scroll_into_view_if_needed()
    wait_true(page, "() => { const a = scrollY; return new Promise(r => setTimeout(() => r(scrollY === a), 200)) }")
    page.get_by_test_id("route-beginner").tap()
    expect(page.get_by_test_id("route-beginner")).to_have_attribute("aria-checked", "true")
    wait_true(page, ON_SCREEN, "[data-testid=start-learning]", timeout=5_000)
    # another choice: its own button is brought on screen too
    page.get_by_test_id("route-kube-to-openshift").tap()
    expect(page.get_by_test_id("start-learning")).to_contain_text("custom resources")
    wait_true(page, ON_SCREEN, "[data-testid=start-learning]", timeout=5_000)
    assert page.errors == []
    ctx.close()


def test_choosing_a_starting_point_with_the_keyboard_keeps_it_on_screen(browser, static_site):
    """Space or Enter on a starting point is a click too: it scrolled the page 548 px and hid the focused choice. A
    key press now only selects it (the result is announced), so the focused choice stays where it is."""
    ctx, page = phone(browser)
    open_(page, static_site, "/")
    page.locator("#start-from .route-picks").scroll_into_view_if_needed()
    wait_true(page, "() => { const a = scrollY; return new Promise(r => setTimeout(() => r(scrollY === a), 200)) }")
    page.locator("#rp-beginner").focus()
    before = page.evaluate("scrollY")
    page.keyboard.press("Space")
    expect(page.get_by_test_id("route-beginner")).to_have_attribute("aria-checked", "true")
    page.wait_for_timeout(400)  # a scroll would have started within a frame
    # the chosen route's text opening below may shift the page a little (the browser keeps the focused choice in
    # place); the bug was a jump to the start button, 548 px on this phone
    assert abs(page.evaluate("scrollY") - before) < 150
    wait_true(page, ON_SCREEN, "#rp-beginner")
    assert page.errors == []
    ctx.close()


def test_practice_arena_rows_fit_a_phone(browser, static_site):
    """Each challenge and incident row carried a line that did not wrap, so the row ran 120 px past the screen and the
    minutes were cut off."""
    ctx, page = phone(browser)
    open_(page, static_site, track_url("practice"))
    folded = page.locator(".chapter-h[aria-expanded=false]")
    while folded.count():
        folded.first.tap()
    rows = page.locator(".chapter .lesson-list a")
    assert rows.count() > 10
    wide = page.evaluate("""() => [...document.querySelectorAll('.chapter .lesson-list a')]
      .filter(a => a.scrollWidth > a.clientWidth + 1 || a.getBoundingClientRect().right > innerWidth)
      .map(a => a.textContent)""")
    assert wide == []
    ctx.close()


def test_a_lab_says_running_it_yourself_is_optional(browser, static_site):
    """The first box under a lab's title began "To run this for real:" and listed a cluster, above "Nothing runs
    anywhere": a phone visitor read that a cluster was needed. It says the tools are optional."""
    ctx, page = phone(browser)
    open_(page, static_site, lab_url("lab.cli-tour"))
    box = page.get_by_test_id("prereqs")
    expect(box).to_be_in_viewport()
    expect(box.locator(".prereqs-label")).to_have_text("Optional, to run it yourself:")
    expect(box).to_contain_text("On this website you replay outputs recorded on a real cluster.")
    ctx.close()


def test_a_challenge_does_not_claim_to_replay_anything(browser, static_site):
    """A challenge replays no output: its box said "On this website you replay outputs recorded on a real cluster",
    and that grading needs a cluster was only said 2.5 screens further down."""
    ctx, page = phone(browser)
    open_(page, static_site, lab_url("ch.ship-web-app"))
    box = page.get_by_test_id("prereqs")
    expect(box).to_be_in_viewport()
    expect(box).not_to_contain_text("replay")
    expect(box.locator(".prereqs-where")).to_contain_text("grading needs your own cluster")
    ctx.close()
