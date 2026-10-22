"""The phone chrome and every overlay, used as on a phone: touch, animations on (a phone animates: the Report panel
that opened off the left edge of the screen did so only while its entrance animation ran), real taps, Escape and
Back. Tab bar, menu drawer, search, the Report and Edit sheet (phones) and popover (desktop)."""
import os

import pytest
from playwright.sync_api import expect
from addresses import lesson_url
from conftest import wait_true
from test_contribute_everywhere import repo_site  # noqa: F401  (a site exported with a repository: Report/Edit shown)

LESSON = lesson_url("o2.kustomize-helm")
AT_LESSON = f"location.pathname.replace(/\\/$/, '') === {LESSON!r}"  # the static host adds a slash
PHONES = [(320, 640), (360, 780), (375, 812), (390, 844), (412, 915), (430, 932)]
INSIDE = """(sel) => [...document.querySelectorAll(sel)].filter((e) => e.getClientRects().length).map((e) => {
  const r = e.getBoundingClientRect(), vw = document.documentElement.clientWidth;
  return { l: Math.round(r.left), r: Math.round(r.right), t: Math.round(r.top), b: Math.round(r.bottom), vw, vh: innerHeight,
           inside: r.left >= -0.5 && r.right <= vw + 0.5 && r.top >= -0.5 && r.bottom <= innerHeight + 0.5 } })"""


def phone(browser, w, h, **kw):
    ctx = browser.new_context(viewport={"width": w, "height": h}, has_touch=True, reduced_motion="no-preference", **kw)
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    return ctx, pg


def opened(pg, path, site):
    pg.goto(site + path)
    pg.wait_for_selector("main .page:not(:has(.sk-page))")
    pg.wait_for_timeout(250)


def settled(pg):
    pg.wait_for_timeout(400)  # entrance animations (at most 0.22 s) have ended


@pytest.mark.parametrize("w,h", PHONES)
def test_the_report_sheet_fits_the_phone_and_every_choice_can_be_reached(browser, repo_site, w, h):
    ctx, pg = phone(browser, w, h)
    opened(pg, LESSON, repo_site)
    btn = pg.get_by_test_id("page-actions-more")
    assert btn.is_visible() and btn.get_attribute("aria-label") == "Report a problem or edit this lesson"
    if w >= 360:  # a word, not an unexplained icon (under 360px the flag alone keeps the way back on its row)
        assert "Report or edit" in btn.inner_text()
    btn.tap()
    sheet = pg.get_by_test_id("page-actions-more-sheet")
    sheet.wait_for()
    for sample in range(4):  # during its entrance (it rises from just below) and after: never beside the screen
        r = pg.evaluate(INSIDE, "[data-testid=page-actions-more-sheet]")
        assert r and r[0]["l"] >= 0 and r[0]["r"] <= w and r[0]["t"] >= 0, (sample, r)
        pg.wait_for_timeout(90)
    r = pg.evaluate(INSIDE, "[data-testid=page-actions-more-sheet]")
    assert r[0]["inside"], r
    items = sheet.locator(".pa-item")
    assert items.count() >= 4  # three kinds of report, and the edit link
    for i in range(items.count()):
        items.nth(i).scroll_into_view_if_needed()
        box = items.nth(i).bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= w + 0.5 and box["height"] >= 44, (i, box)
    assert pg.evaluate("document.documentElement.scrollWidth") <= w
    # the docked copy in the site header is a desktop feature: on a phone the menu's "This page" offers the actions
    pg.get_by_test_id("page-actions-more-close").tap()
    pg.evaluate("window.scrollTo(0, 2400)")
    settled(pg)
    assert not pg.get_by_test_id("page-actions-docked").is_visible()
    assert not pg.errors
    ctx.close()


def test_the_report_sheet_closes_after_a_choice_outside_back_escape_and_its_button(browser, repo_site):
    ctx, pg = phone(browser, 390, 844)
    opened(pg, LESSON, repo_site)
    sheet = pg.get_by_test_id("page-actions-more-sheet")
    url = pg.url

    def open_it():
        pg.get_by_test_id("page-actions-more").tap()
        sheet.wait_for()
        settled(pg)

    open_it()
    with ctx.expect_page() as tab:  # a report opens GitHub in a new tab: the sheet closes behind it
        sheet.locator(".pa-item").first.tap()
    tab.value.close()
    wait_true(pg, "!document.querySelector('[data-testid=page-actions-more-sheet]')")
    open_it()
    pg.touchscreen.tap(195, 40)  # the dimmed page above the sheet
    wait_true(pg, "!document.querySelector('[data-testid=page-actions-more-sheet]')")
    open_it()
    pg.keyboard.press("Escape")
    wait_true(pg, "!document.querySelector('[data-testid=page-actions-more-sheet]')")
    assert pg.evaluate("document.activeElement?.dataset.testid") == "page-actions-more"  # focus back on its button
    open_it()
    pg.go_back()  # the phone's Back closes the sheet, the page stays
    wait_true(pg, "!document.querySelector('[data-testid=page-actions-more-sheet]')")
    assert pg.url == url
    open_it()
    pg.get_by_test_id("page-actions-more-close").tap()
    wait_true(pg, "!document.querySelector('[data-testid=page-actions-more-sheet]')")
    # nothing invisible is left over the page: a tap reaches the page and the tab bar
    assert pg.evaluate("document.elementFromPoint(195, 420)?.closest('.pa-backdrop, .menu-backdrop')") is None
    assert not pg.evaluate("document.documentElement.classList.contains('overlay-lock')")
    pg.get_by_test_id("tab-practice").tap()
    wait_true(pg, "location.pathname.startsWith('/labs')")
    ctx.close()


@pytest.mark.parametrize("w,path", [(900, LESSON), (1280, "/studio/model/scheduler")])  # pages whose actions dock
def test_the_desktop_report_popover_stays_inside_the_window_also_when_docked(browser, repo_site, w, path):
    ctx = browser.new_context(viewport={"width": w, "height": 800}, reduced_motion="no-preference")
    pg = ctx.new_page()
    opened(pg, path, repo_site)
    pg.get_by_test_id("report-menu").click()
    settled(pg)
    r = pg.evaluate(INSIDE, "[data-testid=page-actions] .pa-pop")
    assert r and r[0]["inside"], r
    pg.keyboard.press("Escape")
    pg.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    pg.get_by_test_id("page-actions-docked").wait_for()
    pg.get_by_test_id("page-actions-docked").click()
    for sample in range(4):  # the dock fades in: its panel opens from the window's edge throughout
        r = pg.evaluate(INSIDE, "[data-testid=page-actions-dock] .pa-pop")
        assert r and r[0]["inside"] and r[0]["r"] >= w - 40, (sample, r)
        pg.wait_for_timeout(60)
    with ctx.expect_page() as tab:  # choosing closes it
        pg.locator("[data-testid=page-actions-dock] .pa-pop .pa-item").first.click()
    tab.value.close()
    wait_true(pg, "!document.querySelector('[data-testid=page-actions-dock] .pa-pop:not([hidden])')")
    ctx.close()


def test_the_menu_closes_on_a_choice_a_tap_outside_escape_and_back_and_back_after_a_choice_returns(browser, static_site):
    site = static_site.rstrip("/")
    ctx, pg = phone(browser, 390, 844)
    opened(pg, LESSON, site)
    menu = pg.locator("#menu-sheet")

    def open_it():
        pg.get_by_test_id("menu-open").tap()
        menu.wait_for()
        settled(pg)
        assert pg.evaluate(INSIDE, "#menu-sheet")[0]["inside"]
        assert pg.evaluate("document.documentElement.classList.contains('overlay-lock')")  # the page holds still

    open_it()
    pg.touchscreen.tap(20, 400)  # the dimmed page beside the drawer
    wait_true(pg, "!document.querySelector('#menu-sheet')")
    open_it()
    pg.keyboard.press("Escape")
    wait_true(pg, "!document.querySelector('#menu-sheet')")
    assert pg.evaluate("document.activeElement?.dataset.testid") == "menu-open"
    open_it()
    pg.go_back()
    wait_true(pg, "!document.querySelector('#menu-sheet')")
    assert pg.evaluate(AT_LESSON)
    open_it()
    pg.get_by_test_id("menu-close").tap()
    wait_true(pg, "!document.querySelector('#menu-sheet')")
    # a choice: the page changes and the menu is gone; Back returns to the lesson at once (no extra entry)
    open_it()
    menu.get_by_role("link", name="Commands").tap()
    wait_true(pg, "location.pathname.startsWith('/commands') && !document.querySelector('#menu-sheet')")
    pg.go_back()
    wait_true(pg, AT_LESSON)
    # the current page's own link closes the menu too (no navigation happens)
    pg.goto(site + "/labs")
    pg.wait_for_selector("main .page:not(:has(.sk-page))")
    open_it()
    menu.get_by_role("link", name="Labs").tap()
    wait_true(pg, "!document.querySelector('#menu-sheet')")
    assert not pg.errors
    ctx.close()


def test_the_menu_keeps_the_focus_inside_and_offers_theme_and_page_actions(browser, repo_site):
    ctx, pg = phone(browser, 390, 844)
    opened(pg, LESSON, repo_site)
    pg.get_by_test_id("menu-open").tap()
    pg.locator("#menu-sheet").wait_for()
    for _ in range(40):  # Tab never leaves the open drawer
        pg.keyboard.press("Tab")
        assert pg.evaluate("!!document.activeElement?.closest('#menu-sheet')")
    dark = pg.evaluate("document.documentElement.dataset.theme")
    pg.get_by_test_id("menu-theme").tap()
    assert pg.evaluate("document.documentElement.dataset.theme") != dark
    pg.get_by_test_id("menu-page-actions").tap()  # "This page": the same Report and Edit sheet
    pg.get_by_test_id("page-actions-more-sheet").wait_for()
    wait_true(pg, "!document.querySelector('#menu-sheet')")  # one overlay at a time
    pg.wait_for_timeout(300)
    pg.go_back()  # one Back closes the sheet; the menu's entry was handed over, not left behind
    wait_true(pg, "!document.querySelector('[data-testid=page-actions-more-sheet]')")
    assert pg.evaluate(AT_LESSON) and pg.evaluate("!history.state?.overlay")
    ctx.close()


@pytest.mark.parametrize("w,h", PHONES + [(768, 1024), (844, 390)])
def test_the_tab_bar_names_the_main_places_and_shows_where_the_learner_is(browser, static_site, w, h):
    site = static_site.rstrip("/")
    ctx, pg = phone(browser, w, h)
    for path, current in [("/", "home"), (LESSON, "learn"), ("/challenges", "practice"), ("/studio", "explore"), ("/me", "me")]:
        opened(pg, path, site)
        bar = pg.get_by_test_id("tabbar")
        assert bar.is_visible()
        labels = [x.strip() for x in bar.locator("a").all_inner_texts()]
        assert labels == ["Home", "Learn", "Practice", "Explore", "Progress"], labels
        for a in bar.locator("a").all():
            b = a.bounding_box()
            assert b["height"] >= 44 and b["width"] >= 56, b
        assert bar.locator("[aria-current=page]").get_attribute("data-testid") == f"tab-{current}", path
        assert pg.evaluate("document.documentElement.scrollWidth") <= w
    # the header is light: the brand, Search with its word, Menu with its word
    head = [x.strip() for x in pg.locator(".topbar").locator("a:visible, button:visible").all_inner_texts()]
    assert any("Search" in x for x in head) and any("Menu" in x for x in head), head
    assert not pg.locator(".topbar .theme-toggle").is_visible() and not pg.locator(".topbar .me-link").is_visible()
    # the last line of the page is not hidden under the bar
    pg.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    settled(pg)
    foot = pg.locator(".foot-legal").bounding_box()
    assert foot["y"] + foot["height"] <= pg.get_by_test_id("tabbar").bounding_box()["y"] + 1
    ctx.close()


def test_the_tab_bar_makes_room_for_the_keyboard_and_desktop_keeps_its_navigation(browser, static_site):
    site = static_site.rstrip("/")
    ctx, pg = phone(browser, 390, 844)
    opened(pg, "/commands", site)
    pg.locator("main input").first.tap()
    wait_true(pg, "getComputedStyle(document.querySelector('[data-testid=tabbar]')).display === 'none'")
    pg.locator("main h1").first.tap()
    wait_true(pg, "getComputedStyle(document.querySelector('[data-testid=tabbar]')).display !== 'none'")
    ctx.close()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    opened(pg, "/", site)
    assert not pg.get_by_test_id("tabbar").is_visible() and not pg.get_by_test_id("menu-open").is_visible()
    assert pg.locator(".topnav a").count() >= 4 and pg.locator(".topbar .theme-toggle").is_visible()
    ctx.close()


def test_search_fills_the_phone_screen_closes_with_back_and_cancel_and_a_result_navigates_once(browser, static_site):
    site = static_site.rstrip("/")
    ctx, pg = phone(browser, 320, 640)
    opened(pg, LESSON, site)
    pg.get_by_test_id("search-open").tap()
    pg.get_by_test_id("palette-input").wait_for()
    settled(pg)
    assert pg.evaluate(INSIDE, ".palette")[0]["inside"]
    assert pg.get_by_test_id("palette-cancel").is_visible()
    pg.get_by_test_id("palette-cancel").tap()
    wait_true(pg, "!document.querySelector('.palette')")
    pg.get_by_test_id("search-open").tap()
    pg.get_by_test_id("palette-input").wait_for()
    pg.go_back()
    wait_true(pg, "!document.querySelector('.palette')")
    assert pg.evaluate(AT_LESSON)
    pg.get_by_test_id("search-open").tap()
    pg.get_by_test_id("palette-input").fill("commands")
    pg.locator(".palette-list [role=option]").first.tap()
    wait_true(pg, f"!({AT_LESSON}) && !document.querySelector('.palette')")
    pg.go_back()
    wait_true(pg, AT_LESSON)
    ctx.close()


@pytest.mark.parametrize("w", [320, 390])
def test_no_overlay_makes_the_page_wider_than_the_phone(browser, repo_site, w):
    ctx, pg = phone(browser, w, 740)
    opened(pg, LESSON, repo_site)
    for opener, gone in [("menu-open", "menu-close"), ("page-actions-more", "page-actions-more-close"), ("search-open", "palette-cancel")]:
        pg.get_by_test_id(opener).tap()
        settled(pg)
        assert pg.evaluate("document.documentElement.scrollWidth") <= w, opener
        pg.get_by_test_id(gone).tap()
        settled(pg)
    ctx.close()


def test_the_lesson_sheets_the_enlarged_screenshot_and_a_full_screen_diagram_close_with_back(browser, static_site):
    SHOT_LESSON = "n.console-tour"  # real console screenshots
    site = static_site.rstrip("/")
    ctx, pg = phone(browser, 390, 844)
    # Go deeper: Back closes it and the lesson stays where it was
    opened(pg, LESSON, site)
    pg.get_by_test_id("go-deeper").tap()
    pg.locator(".deeper-panel").wait_for()
    settled(pg)
    assert pg.evaluate(INSIDE, ".deeper-panel")[0]["inside"]
    pg.go_back()
    wait_true(pg, "!document.querySelector('.deeper-panel')")
    assert pg.evaluate(AT_LESSON)
    # an enlarged screenshot
    opened(pg, lesson_url(SHOT_LESSON), site)
    shot = pg.get_by_test_id("screenshot").first
    shot.scroll_into_view_if_needed()
    shot.get_by_test_id("screenshot-enlarge").tap()
    wait_true(pg, "!!document.querySelector('dialog[open]')")
    pg.go_back()
    wait_true(pg, "!document.querySelector('dialog[open]')")
    assert pg.evaluate(f"location.pathname.replace(/\\/$/, '') === {lesson_url(SHOT_LESSON)!r}")
    # a diagram in full screen
    opened(pg, "/studio/diagram/rbac", site)
    pg.get_by_role("button", name="Full screen").first.tap()
    wait_true(pg, "!!document.querySelector('.graph-expanded')")
    pg.go_back()
    wait_true(pg, "!document.querySelector('.graph-expanded')")
    assert pg.evaluate("location.pathname.startsWith('/studio/diagram/rbac')")
    assert not pg.evaluate("document.documentElement.classList.contains('overlay-lock')")
    assert not pg.errors
    ctx.close()


def test_back_never_lands_on_a_leftover_overlay_entry(browser, static_site):
    """Every Back changes what is on screen: after a choice in the menu, after reopening it at once, after a reload with
    it open, and after handing it over to another overlay (an independent review found entries that could pile up)."""
    site = static_site.rstrip("/")
    ctx, pg = phone(browser, 390, 844)
    opened(pg, "/learn", site)
    pg.goto(site + LESSON)  # a distinct page before the lesson: Back must reach it
    pg.wait_for_selector("main .page:not(:has(.sk-page))")
    menu = pg.locator("#menu-sheet")

    def on_learn():
        return "location.pathname.replace(/\\/$/, '') === '/learn'"

    # a choice, then Back twice: the lesson, then /learn
    pg.get_by_test_id("menu-open").tap()
    menu.wait_for()
    menu.get_by_role("link", name="Commands").tap()
    wait_true(pg, "location.pathname.startsWith('/commands')")
    pg.go_back()
    wait_true(pg, AT_LESSON)
    pg.go_back()
    wait_true(pg, on_learn())
    pg.go_forward()
    wait_true(pg, AT_LESSON)
    # the lesson has rendered (as before the next opening below): on a busy Windows runner, the menu opened while the
    # page still loaded kept moving under Playwright's stability check until the tap timed out
    pg.wait_for_selector("main .page:not(:has(.sk-page))")
    # closed and reopened at once: it stays open; Back closes it; the next Back reaches /learn
    pg.get_by_test_id("menu-open").tap()
    menu.wait_for()
    settled(pg)  # its slide-in has ended
    pg.get_by_test_id("menu-close").tap()
    pg.get_by_test_id("menu-open").tap()
    # it opens and stays open (waited for, not slept on: a busy Windows runner took longer than 600 ms to show it)
    expect(menu).to_be_visible(timeout=5000)
    pg.wait_for_timeout(600)
    assert menu.is_visible()
    pg.go_back()
    wait_true(pg, "!document.querySelector('#menu-sheet')")
    assert pg.evaluate(AT_LESSON)
    pg.go_back()
    wait_true(pg, on_learn())
    pg.go_forward()
    wait_true(pg, AT_LESSON)
    pg.wait_for_selector("main .page:not(:has(.sk-page))")
    pg.get_by_test_id("menu-open").tap()
    menu.wait_for()
    pg.reload()  # reloaded with the menu open: its entry is stepped over
    pg.wait_for_selector("main .page:not(:has(.sk-page))")
    pg.wait_for_timeout(500)
    assert not menu.count() and pg.evaluate(AT_LESSON)
    pg.go_back()
    wait_true(pg, on_learn())
    ctx.close()


def test_the_report_sheet_takes_the_keyboard_focus_and_keeps_it(browser, repo_site):
    ctx, pg = phone(browser, 390, 844)
    opened(pg, LESSON, repo_site)
    pg.get_by_test_id("page-actions-more").focus()
    pg.keyboard.press("Enter")
    sheet = pg.get_by_test_id("page-actions-more-sheet")
    sheet.wait_for()
    wait_true(pg, "!!document.activeElement?.closest('[data-testid=page-actions-more-sheet]')")
    assert pg.evaluate("document.querySelector('.shell').hasAttribute('inert')")  # the page behind is out of reach
    for _ in range(12):
        pg.keyboard.press("Tab")
        assert pg.evaluate("!!document.activeElement?.closest('[data-testid=page-actions-more-sheet]')")
    pg.keyboard.press("Shift+Tab")
    assert pg.evaluate("!!document.activeElement?.closest('[data-testid=page-actions-more-sheet]')")
    pg.keyboard.press("Escape")
    wait_true(pg, "document.activeElement?.dataset.testid === 'page-actions-more'")
    assert not pg.evaluate("document.querySelector('.shell').hasAttribute('inert')")
    ctx.close()


def test_desktop_search_keeps_tab_inside_and_shows_no_cancel_button(browser, static_site):
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    opened(pg, "/", static_site.rstrip("/"))
    pg.keyboard.press("Control+k")
    pg.get_by_test_id("palette-input").wait_for()
    assert not pg.get_by_test_id("palette-cancel").is_visible()
    for keys in ("Tab", "Shift+Tab", "Tab", "Tab"):
        pg.keyboard.press(keys)
        assert pg.evaluate("!!document.activeElement?.closest('.palette')"), keys
    ctx.close()


LONG = lesson_url("d.networkpolicy-ovn")  # one of the longest lessons (34,000 px on a phone)
PANEL = "[data-testid$=-sheet], .pa-pop:not([hidden])"  # the Report panel: the phone sheet (or an older popover)
SHOTS = os.environ.get("E2E_SHOTS")  # a folder: screenshots of every step, to look at


def finger(pg, sel):
    """A finger's tap where the control is. locator.tap() first scrolls its target into view, which moves the page
    under a sticky header (a phone never does that): the position checks below need the real thing."""
    b = pg.locator(sel).first.bounding_box()
    pg.touchscreen.tap(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)


def open_report(pg):
    """As a learner on a phone would: the page's own button if it is on screen, else the copy in the site header (an
    older design), else Menu > This page."""
    if pg.evaluate("(() => { const b = [...document.querySelectorAll('[data-testid=page-actions-more]')].find((e) => e.getClientRects().length); if (!b) return false; const r = b.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight })()"):
        finger(pg, "[data-testid=page-actions-more]")
    elif pg.locator("[data-testid=page-actions-docked]").is_visible():
        finger(pg, "[data-testid=page-actions-docked]")
    else:
        finger(pg, "[data-testid=menu-open]")
        pg.locator("#menu-sheet").wait_for()
        pg.wait_for_timeout(300)
        finger(pg, "[data-testid=menu-page-actions]")
    pg.locator(PANEL).first.wait_for()


# where the reader is: the page's own offset on screen (an open sheet pins the body, so scrollY alone reads 0 then)
READING = "Math.round(-document.body.getBoundingClientRect().top)"

# a finger drag inside the open sheet, dispatched as touch events: was its touchmove cancelled? (lib/overlay.ts: a drag
# that nothing in the sheet can scroll is cancelled, or iOS Safari hands it on to the page)
DRAG_INSIDE = """([sel, dy]) => { const t = document.querySelector(sel); const r = t.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + Math.min(r.height / 2, 40);
  const touch = (yy) => new Touch({identifier: 7, target: t, clientX: x, clientY: yy});
  t.dispatchEvent(new TouchEvent('touchstart', {cancelable: true, bubbles: true, touches: [touch(y)]}));
  const ev = new TouchEvent('touchmove', {cancelable: true, bubbles: true, touches: [touch(y + dy)]}); t.dispatchEvent(ev);
  t.dispatchEvent(new TouchEvent('touchend', {cancelable: true, bubbles: true, touches: []}));
  return ev.defaultPrevented }"""
# at the sheet's end: the finger moves up (past the end: held), then back down (towards the top: it scrolls, not held)
REVERSING_DRAG = """(sel) => { const t = document.querySelector(sel); const r = t.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + Math.min(r.height / 2, 40);
  const touch = (yy) => new Touch({identifier: 8, target: t, clientX: x, clientY: yy});
  t.dispatchEvent(new TouchEvent('touchstart', {cancelable: true, bubbles: true, touches: [touch(y + 60)]}));
  t.dispatchEvent(new TouchEvent('touchmove', {cancelable: true, bubbles: true, touches: [touch(y + 10)]}));
  const ev = new TouchEvent('touchmove', {cancelable: true, bubbles: true, touches: [touch(y + 35)]}); t.dispatchEvent(ev);
  t.dispatchEvent(new TouchEvent('touchend', {cancelable: true, bubbles: true, touches: []}));
  return ev.defaultPrevented }"""
PANEL_STATE = """(sel) => { const p = [...document.querySelectorAll(sel)].find((e) => e.getClientRects().length); if (!p) return null;
  const v = visualViewport, r = p.getBoundingClientRect(), close = p.querySelector('[data-testid$=-close]');
  const c = close?.getBoundingClientRect();
  const x0 = v.offsetLeft, y0 = v.offsetTop, x1 = x0 + v.width, y1 = y0 + v.height;  // the visible area
  return { inside: r.left >= x0 - 0.5 && r.right <= x1 + 0.5 && r.top >= y0 - 0.5 && r.bottom <= y1 + 0.5,
           across: r.left >= x0 - 0.5 && r.right <= x1 + 0.5, rect: [r.left, r.top, r.right, r.bottom].map(Math.round), vh: v.height,
           closeReachable: !!c && c.top >= y0 && c.bottom <= y1 && document.elementFromPoint(c.left + c.width / 2, c.top + c.height / 2)?.closest('[data-testid$=-close]') === close,
           scrollY: Math.round(-document.body.getBoundingClientRect().top) } }"""


@pytest.mark.parametrize("w", [320, 360, 390, 430])
def test_report_is_whole_on_screen_at_the_top_middle_and_bottom_of_a_long_lesson(browser, repo_site, w):
    """The owner's sequence on an Android phone (the panel opened off the screen once the lesson was scrolled): open
    Report at the top, halfway and near the bottom, scroll while it is open, shorten the viewport as the keyboard does,
    close it; it is whole on screen every time, and closing leaves the lesson where it was."""
    ctx, pg = phone(browser, w, 740)
    opened(pg, LONG, repo_site)
    end = pg.evaluate("document.documentElement.scrollHeight - innerHeight")
    assert end > 20_000  # a long lesson, really scrolled
    for where, y in (("top", 0), ("middle", end // 2), ("bottom", end - 200)):
        pg.evaluate(f"window.scrollTo(0, {y})")
        settled(pg)
        before = pg.evaluate(READING)
        open_report(pg)
        for sample in range(4):  # while it animates in: never beside the screen
            s = pg.evaluate(PANEL_STATE, PANEL)
            assert s and s["across"] and s["rect"][1] >= 0, (where, sample, s)
            pg.wait_for_timeout(80)
        settled(pg)
        s = pg.evaluate(PANEL_STATE, PANEL)
        assert s["inside"] and s["closeReachable"], (where, s)
        assert s["scrollY"] == before, (where, "opening moved the lesson", s["scrollY"], before)
        # the page is held still, not moved away: what measures it (the saved reading position) still sees the reader
        assert pg.evaluate("Math.round(scrollY)") == before, (where, "scrollY while open", pg.evaluate("scrollY"))
        # every choice can be reached inside it (its own content scrolls) and lies within the screen when shown
        items = pg.locator(PANEL).first.locator(".pa-item")
        assert items.count() >= 4
        for i in range(items.count()):
            items.nth(i).scroll_into_view_if_needed()
            b = items.nth(i).bounding_box()
            assert b["x"] >= 0 and b["x"] + b["width"] <= w + 0.5 and b["y"] >= 0 and b["y"] + b["height"] <= 740 + 0.5, (where, i, b)
            # and nothing covers it (the tab bar, the header, the backdrop): a tap there reaches the choice itself
            hit = pg.evaluate("([x, y]) => document.elementFromPoint(x, y)?.closest('.pa-item')?.outerHTML.slice(0, 60)", [b["x"] + b["width"] / 2, b["y"] + b["height"] / 2])
            assert hit and hit == items.nth(i).evaluate("e => e.outerHTML.slice(0, 60)"), (where, i, hit)
        if SHOTS:
            pg.screenshot(path=f"{SHOTS}/report-{w}-{where}-open.png")
        # scrolling with it open moves neither the page nor the panel
        pg.mouse.wheel(0, 900)
        settled(pg)
        s = pg.evaluate(PANEL_STATE, PANEL)
        assert s["inside"] and s["scrollY"] == before, (where, "scrolled while open", s)
        # nor does a finger dragging over the dimmed page (a drag outside the sheet is cancelled)
        if pg.context.browser.browser_type.name == "chromium":  # a real finger (the browser's own touch input)
            cdp = pg.context.new_cdp_session(pg)
            for i, fy in enumerate((150, 250, 350, 450)):
                cdp.send("Input.dispatchTouchEvent", {"type": "touchStart" if i == 0 else "touchMove", "touchPoints": [{"x": w / 2, "y": 600 - fy}]})
            cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            cdp.detach()
        # the drag is cancelled where it starts outside the sheet (iOS Safari scrolls the page behind otherwise)
        assert pg.evaluate("""() => { const t = document.elementFromPoint(innerWidth / 2, 60);
            const touch = (yy) => new Touch({identifier: 9, target: t, clientX: innerWidth / 2, clientY: yy});
            t.dispatchEvent(new TouchEvent('touchstart', {cancelable: true, bubbles: true, touches: [touch(60)]}));
            const ev = new TouchEvent('touchmove', {cancelable: true, bubbles: true, touches: [touch(160)]}); t.dispatchEvent(ev);
            t.dispatchEvent(new TouchEvent('touchend', {cancelable: true, bubbles: true, touches: []}));
            return ev.defaultPrevented && !t.closest('.pa-sheet') }"""), (where, "a drag over the dimmed page was not held")
        settled(pg)
        s = pg.evaluate(PANEL_STATE, PANEL)
        assert s["inside"] and s["scrollY"] == before == pg.evaluate("Math.round(scrollY)"), (where, "a drag moved the lesson", s)
        # a drag inside a sheet that does not scroll is cancelled too
        sheet = pg.locator(PANEL).first
        if not sheet.evaluate("e => e.scrollHeight > e.clientHeight + 1"):
            assert pg.evaluate(DRAG_INSIDE, [f"{PANEL} .pa-item", -80]), (where, "a drag on a sheet that cannot scroll")
        # but never once the reader has zoomed in with a pinch: a drag then pans the zoomed view, even one the sheet
        # cannot take (at its top, the finger moving down). Chromium can set the zoom.
        if pg.context.browser.browser_type.name == "chromium":
            sheet.evaluate("e => { for (let el = e.querySelector('.pa-item'); el && el !== e.parentElement; el = el.parentElement) el.scrollTop = 0 }")
            assert pg.evaluate(DRAG_INSIDE, [f"{PANEL} .pa-item", 80]), (where, "unzoomed: a drag past the sheet's top is held")
            cdp = pg.context.new_cdp_session(pg)
            cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 2})
            wait_true(pg, "visualViewport.scale > 1.5")
            assert not pg.evaluate(DRAG_INSIDE, [f"{PANEL} .pa-item", 80]), (where, "panning a pinch-zoomed view was held")
            cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 1})
            wait_true(pg, "visualViewport.scale < 1.01")
            cdp.detach()
        # a shorter viewport (the on-screen keyboard): still whole, the close button still reachable
        pg.set_viewport_size({"width": w, "height": 420})
        settled(pg)
        s = pg.evaluate(PANEL_STATE, PANEL)
        assert s["inside"] and s["closeReachable"], (where, "shorter viewport", s)
        # now it scrolls: a drag it can take passes (towards its end), one past its top is cancelled
        scroller = sheet.evaluate("e => { for (let el = e.querySelector('.pa-item'); el && el !== e.parentElement; el = el.parentElement) if (el.scrollHeight > el.clientHeight + 1 && /(auto|scroll)/.test(getComputedStyle(el).overflowY)) return true; return false }")
        if scroller:
            sheet.evaluate("e => { for (let el = e.querySelector('.pa-item'); el && el !== e.parentElement; el = el.parentElement) el.scrollTop = 0 }")
            assert not pg.evaluate(DRAG_INSIDE, [f"{PANEL} .pa-item", -80]), (where, "a drag the sheet can scroll was cancelled")
            assert pg.evaluate(DRAG_INSIDE, [f"{PANEL} .pa-item", 80]), (where, "a drag past the sheet's top was not held")
            # a drag that reverses: each movement counts from the previous one (down the sheet, then back up)
            sheet.evaluate("e => { for (let el = e.querySelector('.pa-item'); el && el !== e.parentElement; el = el.parentElement) if (el.scrollHeight > el.clientHeight + 1) el.scrollTop = el.scrollHeight }")
            assert not pg.evaluate(REVERSING_DRAG, f"{PANEL} .pa-item"), (where, "a drag reversing at the sheet's end was cancelled")
        if SHOTS:
            pg.screenshot(path=f"{SHOTS}/report-{w}-{where}-short.png")
        pg.set_viewport_size({"width": w, "height": 740})
        settled(pg)
        finger(pg, f"{PANEL} [data-testid$=-close]")
        wait_true(pg, "!document.querySelector('[data-testid$=-sheet], .pa-pop:not([hidden])')")
        settled(pg)
        assert pg.evaluate(READING) == before == pg.evaluate("Math.round(scrollY)"), (where, "closing moved the lesson")
        assert not pg.evaluate("document.documentElement.classList.contains('overlay-lock')")
        pg.mouse.wheel(0, 300 if where == "top" else -300)  # the page scrolls again
        settled(pg)
        assert pg.evaluate("Math.round(scrollY)") != before
        pg.evaluate(f"window.scrollTo(0, {before})")
        if SHOTS:
            pg.screenshot(path=f"{SHOTS}/report-{w}-{where}-closed.png")
    assert not pg.errors
    ctx.close()
