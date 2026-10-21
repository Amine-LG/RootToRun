"""Phones and tablets (390 px and others), touch, animations on: the content of every kind of page fits the screen,
stays readable and can be operated with a finger. Each test below guards a fault found by the mobile audit."""
import pytest
from addresses import lab_url, lesson_url, track_url

PHONE = {"width": 390, "height": 844}
PAGES = ["/", "/learn", track_url("start"), lesson_url("d.services-dns"), lesson_url("o2.kustomize-helm"),
         lab_url("lab.deploy-apps"), lab_url("inc.dns-typo"), lab_url("ch.right-size"), "/labs", "/studio",
         "/studio/model/rollout", "/studio/diagram/rbac", "/map", "/commands", "/handbook", "/me", "/review", "/about",
         "/setup", "/404.html"]  # an unknown address gets 404.html from the web server


def touch(browser, size=PHONE):
    """A touch screen of that size (a coarse pointer, no hover), with animations as a phone has them."""
    ctx = browser.new_context(viewport=size, has_touch=True, reduced_motion="no-preference")
    return ctx, ctx.new_page()


def open_(page, site, path):
    page.goto(site.rstrip("/") + path)
    page.wait_for_selector("main h1")  # every page, the "not found" one too, has its heading once rendered
    page.wait_for_selector("main .sk-page", state="detached")


def page_width(page):
    return page.evaluate("document.documentElement.scrollWidth")


@pytest.mark.parametrize("width", [320, 360, 412, 768])
def test_no_page_is_wider_than_the_screen(browser, static_site, width):
    ctx, page = touch(browser, {"width": width, "height": 800})
    wide = []
    for path in PAGES:
        open_(page, static_site, path)
        if page_width(page) > width:
            wide.append((path, page_width(page)))
    ctx.close()
    assert wide == []


def test_nothing_widens_the_page_once_opened(browser, static_site):
    # a model opened, a diagram box selected, an answer checked: all on a 320 px phone
    ctx, page = touch(browser, {"width": 320, "height": 640})
    open_(page, static_site, "/studio/model/rollout")
    page.get_by_test_id("sim-skip").tap()
    page.wait_for_selector(".sim-body")
    assert page_width(page) <= 320
    open_(page, static_site, "/studio/diagram/rbac")
    page.locator("button.fd-node").first.tap()
    page.wait_for_selector(".graph-has-inspector, .fd-detail, .graph-inspector")
    assert page_width(page) <= 320
    open_(page, static_site, lesson_url("d.services-dns"))
    card = page.locator("[data-kind=check]").first
    card.locator(".check-choice").nth(2).tap()
    card.get_by_role("button", name="Check my answer").tap()
    page.wait_for_selector("[data-kind=check] .verdict, [data-kind=check] .check-after")
    assert page_width(page) <= 320
    ctx.close()


def test_the_skip_link_of_a_prediction_sits_under_its_sentence(browser, static_site):
    # it was squeezed into a narrow column beside the sentence, four words a line
    ctx, page = touch(browser)
    open_(page, static_site, lesson_url("o2.kustomize-helm"))
    gate = page.locator(".sim-locked").first
    gate.scroll_into_view_if_needed()
    text, skip = gate.locator(".sim-locked-t").bounding_box(), gate.get_by_test_id("sim-skip").bounding_box()
    box = gate.bounding_box()
    assert skip["y"] >= text["y"] + text["height"] - 1  # below the sentence
    assert skip["width"] > box["width"] * 0.7  # the whole width, not a column
    assert skip["height"] >= 43.5  # a finger-sized target (44 px, less rounding)
    ctx.close()


def test_a_long_command_never_breaks_after_its_dashes(browser, static_site):
    # "--image=registry..." is longer than a phone's line: it was broken after "--", leaving it alone on a line
    ctx, page = touch(browser)
    open_(page, static_site, lab_url("lab.deploy-apps"))
    lines = page.evaluate("""() => {
      const code = document.querySelector('.cmd-text');
      const walker = document.createTreeWalker(code, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const at = n.textContent.indexOf('--image');
        if (at < 0) continue;
        const r = document.createRange(); r.setStart(n, at); r.setEnd(n, at + 3);
        return new Set([...r.getClientRects()].map((x) => Math.round(x.top))).size;
      }
      return -1;
    }""")
    ctx.close()
    assert lines == 1  # "--i" on one line: the option is never split from its dashes


def test_lesson_and_diagram_controls_are_finger_sized(browser, static_site):
    ctx, page = touch(browser)
    small = []
    for path, sel in [(lesson_url("d.services-dns"), ".copy-btn, .run-btn, .cmd-actions .icon-btn, .graph-toolbar .btn, .graph-toolbar .icon-btn"),
                      (lab_url("lab.deploy-apps"), ".run-btn, .cmd-actions .icon-btn"),
                      ("/studio/diagram/rbac", ".graph-toolbar .btn, .graph-toolbar .icon-btn"),
                      (lab_url("ch.right-size"), "main .btn.sm"),
                      (track_url("start"), ".lab-chip, main .btn.sm")]:
        open_(page, static_site, path)
        heights = page.evaluate("(s) => [...document.querySelectorAll(s)].filter((e) => e.offsetParent).map((e) => [e.className, e.getBoundingClientRect().height])", sel)
        assert heights, (path, sel)
        small += [(path, c, round(h)) for c, h in heights if h < 43.5]
    ctx.close()
    assert small == []


def test_an_activity_line_never_starts_with_its_separator(browser, static_site):
    # "Explore · Change the inputs and watch what happens" wrapped with the "·" at the start of the second line
    ctx, page = touch(browser)
    open_(page, static_site, lab_url("lab.deploy-apps"))
    head = page.locator(".act-head").first
    sep = head.evaluate("(h) => [getComputedStyle(h.querySelector('.act-verb'), '::before').content, getComputedStyle(h.querySelector('.act-label'), '::after').content]")
    ctx.close()
    assert sep[0] in ("none", "normal") and "·" in sep[1]


def test_small_practice_labels_stay_readable(browser, static_site):
    ctx, page = touch(browser)
    sizes = []
    for path, sel in [(lab_url("inc.dns-typo"), ".ls-label"), (lab_url("lab.deploy-apps"), ".step-count")]:
        open_(page, static_site, path)
        sizes += page.evaluate("(s) => [...document.querySelectorAll(s)].filter((e) => e.offsetParent).map((e) => parseFloat(getComputedStyle(e).fontSize))", sel)
    ctx.close()
    assert sizes and min(sizes) >= 12.4


@pytest.mark.parametrize("size", [PHONE, {"width": 844, "height": 390}])
def test_what_a_tap_reveals_is_not_left_under_the_tab_bar(browser, static_site, size):
    """Found by the final phone audit: the reveal policy (lib/reveal.ts) scrolled a command's output so that its end sat
    at the bottom of the window, under the tab bar, which hid the last lines; and a control reached with the keyboard
    could stop under the bar too."""
    ctx, page = touch(browser, size)
    open_(page, static_site, lab_url("lab.deploy-apps"))
    bar = page.get_by_test_id("tabbar").bounding_box()["y"]
    assert bar < size["height"]  # the tab bar is shown
    btn = page.locator("[data-testid=replay]:visible").first
    btn.evaluate(f"(b) => scrollTo(0, scrollY + b.getBoundingClientRect().bottom - {bar} + 20)")  # just above the bar
    page.wait_for_timeout(300)
    b = btn.bounding_box()
    page.touchscreen.tap(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    page.wait_for_selector(".cmdblock.opened")
    page.wait_for_timeout(1500)  # the smooth scroll has ended
    top, bottom = btn.evaluate("b => { const r = b.closest('.cmdblock').getBoundingClientRect(); return [r.top, r.bottom] }")
    head = page.evaluate("document.querySelector('.topbar').getBoundingClientRect().bottom")
    if bottom - top <= bar - head - 24:  # it fits: all of it is shown, above the bar
        assert head <= top and bottom <= bar + 0.5, (top, bottom, bar)
    else:  # taller than the room: its start is shown under the header
        assert head - 0.5 <= top < bar, (top, bottom, bar)
    # the browser's own scrolling (a control reached with Tab) stops above the bar too
    assert page.evaluate("getComputedStyle(document.documentElement).scrollPaddingBottom") not in ("auto", "0px")
    ctx.close()
