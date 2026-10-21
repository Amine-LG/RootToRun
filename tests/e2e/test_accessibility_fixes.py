"""Accessibility fixes: focus after "Check my answer", per-page titles, focus on the new page after a link, Escape on the
phone contents panel, not-found pages, touch-target sizes and placeholder contrast."""
import re

import pytest
from academy import config
from playwright.sync_api import expect
from addresses import lab_url, lesson_url
from conftest import wait_true

SITE = config.SITE_NAME
ACTIVE = "() => { const e = document.activeElement; return e ? { tag: e.tagName, testid: e.dataset.testid || '', cls: e.className || '', text: (e.textContent || '').trim().slice(0, 80) } : null }"


def open_(page, site, route="/"):
    page.goto(site.rstrip("/") + route)
    page.wait_for_selector("main .page:not(:has(.sk-page))")


def click_link(page, href):
    """A same-site link the app's router handles (a client-side navigation, as from any in-page link)."""
    page.evaluate("(h) => { const a = document.createElement('a'); a.href = h; a.textContent = 'x'; document.querySelector('main').append(a); a.click() }", href)


def test_check_verdict_takes_focus_and_is_announced(page, static_site):
    open_(page, static_site, lesson_url("h.observability"))
    q = page.locator("[data-testid=flow-step][data-kind=check]").first.get_by_test_id("check").first
    live = q.get_by_test_id("check-live")
    expect(live).to_have_attribute("aria-live", "polite")
    expect(live).to_have_text("")  # mounted and empty before the answer, so the later text is announced
    q.locator("[data-testid=choice]").first.click()
    q.get_by_test_id("check-submit").focus()
    page.keyboard.press("Enter")
    verdict = q.get_by_test_id("verdict")
    expect(verdict).to_be_visible()
    expect(verdict).to_be_focused()  # not <body>: the submit button is gone
    assert verdict.get_attribute("role") is None, "no pre-filled role=status: the live region announces"
    expect(live).to_have_text(re.compile(r"^(Right\.|Not quite\.)$"))
    assert page.errors == []


def test_every_route_has_its_own_title(page, static_site):
    open_(page, static_site, lesson_url("o1.cli"))
    h1 = page.locator("main h1").first.inner_text()
    expect(page).to_have_title(f"{h1} · {SITE}")
    click_link(page, "/labs")
    expect(page).to_have_title(f"Labs · {SITE}")
    click_link(page, lab_url("inc.dns-typo"))
    page.wait_for_selector("main h1.lesson-title")
    expect(page).to_have_title(f"{page.locator('main h1').first.inner_text()} · {SITE}")
    assert "resolve" in page.title().lower()  # the same title as the static export's page (test_static_site)
    click_link(page, "/learn")
    expect(page).to_have_title(f"Learning paths · {SITE}")
    click_link(page, "/")
    expect(page).to_have_title(SITE)
    assert page.errors == []


def test_a_link_moves_focus_to_the_new_pages_heading_without_scrolling(page, static_site):
    open_(page, static_site, "/")
    assert page.evaluate(ACTIVE)["tag"] != "H1", "first load: focus stays where the browser puts it"
    page.locator(".topnav a[href='/labs']").click()
    expect(page).to_have_url(re.compile(r"/labs$"))
    h1 = page.locator("main h1").first
    expect(h1).to_be_focused()
    assert h1.get_attribute("tabindex") == "-1"
    # from further down a page: the new page starts at its top, and focusing the heading scrolls nothing
    open_(page, static_site, lesson_url("o1.cli"))
    page.evaluate("window.scrollTo(0, 1500)")
    page.wait_for_timeout(300)
    click_link(page, lab_url("inc.dns-typo"))
    lab_h1 = page.locator("main h1.lesson-title")
    expect(lab_h1).to_be_focused()
    assert page.evaluate("window.scrollY") == 0
    # Back restores the reading position: focus does not jump to the heading
    page.go_back()
    expect(page).to_have_url(re.compile(re.escape(lesson_url("o1.cli")) + "/?$"))
    wait_true(page, "window.scrollY > 1000")
    page.wait_for_timeout(400)
    assert page.evaluate(ACTIVE)["tag"] != "H1"
    # an anchor jump within a page is not a new page
    page.locator("[data-testid=toc-link]").nth(1).click()
    page.wait_for_timeout(300)
    assert page.evaluate(ACTIVE)["tag"] != "H1"
    assert page.errors == []


def test_escape_closes_the_phone_contents_panel(browser, static_site):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    open_(page, static_site, lesson_url("o1.cli"))
    toc = page.locator("nav.flow-parts details")
    summary = toc.locator(":scope > summary")
    expect(toc).not_to_have_attribute("open", "")
    summary.click()
    expect(toc).to_have_attribute("open", "")
    page.locator("[data-testid=toc-link]").first.focus()
    page.keyboard.press("Escape")
    expect(toc).not_to_have_attribute("open", "")
    expect(summary).to_be_focused()
    # opened from the keyboard, closed with Escape on the toggle itself
    page.keyboard.press("Enter")
    expect(toc).to_have_attribute("open", "")
    page.keyboard.press("Escape")
    expect(toc).not_to_have_attribute("open", "")
    expect(summary).to_be_focused()
    ctx.close()


def test_not_found_pages_have_a_heading_and_a_way_back(page, static_site):
    open_(page, static_site, "/")
    for href in ["/lesson/does-not-exist", "/lab/nope", "/learn/linux/no-such-lesson", "/incidents/nope", "/no-such-page"]:
        click_link(page, href)
        nf = page.get_by_test_id("not-found")
        expect(nf.get_by_role("heading", level=1)).to_have_text("Page not found")
        expect(nf.locator("a[href='/learn']")).to_be_visible()
        expect(page).to_have_title(f"Page not found · {SITE}")
    page.get_by_test_id("not-found").locator("a[href='/learn']").click()
    expect(page).to_have_url(re.compile(r"/learn$"))
    assert page.errors == []


SIZE = "(sel) => [...document.querySelectorAll(sel)].filter(e => e.getClientRects().length).map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)] })"


def test_touch_targets_on_a_phone(browser, static_site):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    open_(page, static_site, lesson_url("o1.cli"))
    page.wait_for_selector("[data-testid=flow-step]")
    # the phone header: Search and Menu; progress and the other sections are in the tab bar (theme: in the menu)
    for sel, w, h in [(".topbar .search-btn", 40, 44), (".topbar .nav-toggle", 44, 44), (".tabbar a", 56, 44), ("button.linkish", 0, 44),
                      ("details.more > summary", 0, 44), ("nav.flow-parts summary", 0, 44)]:
        sizes = page.evaluate(SIZE, sel)
        assert sizes, sel
        assert all(sw >= w and sh >= h for sw, sh in sizes), f"{sel}: {sizes}"
    bar = page.locator("nav.flow-parts").bounding_box()
    assert page.locator("nav.flow-parts summary").bounding_box()["height"] >= bar["height"] - 2, "the toggle fills the bar"
    for route, sel in [("/labs", ".search-in input"), ("/commands", ".search-in input"), ("/me", "a.me-track-name")]:
        open_(page, static_site, route)
        sizes = page.evaluate(SIZE, sel)
        assert sizes and all(sh >= 44 for _, sh in sizes), f"{route} {sel}: {sizes}"
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    ctx.close()


CONTRAST = r"""(sel) => {
  const parse = (c) => { const m = c.match(/[\d.]+/g).map(Number); return m.length === 3 ? [...m, 1] : m }
  const lum = ([r, g, b]) => { const f = (x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4 }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b) }
  const el = document.querySelector(sel)
  const layers = []
  for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c[3] > 0) { layers.push(c); if (c[3] >= 1) break } }
  let bg = [255, 255, 255]
  for (const c of layers.reverse()) bg = bg.map((v, i) => v * (1 - c[3]) + c[i] * c[3])
  const cs = getComputedStyle(el, '::placeholder'), fg = parse(cs.color), a = fg[3] * parseFloat(cs.opacity || '1')
  const mixed = fg.slice(0, 3).map((v, i) => v * a + bg[i] * (1 - a))
  const [l1, l2] = [lum(mixed), lum(bg)]
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)
}"""


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_placeholders_are_readable(browser, static_site, theme):
    ctx = browser.new_context(viewport={"width": 1200, "height": 900})
    ctx.add_init_script(f"try {{ localStorage.setItem('osa.theme', '{theme}') }} catch (e) {{}}")
    page = ctx.new_page()
    for route, sel in [("/labs", ".search-in input"), ("/commands", "[data-testid=cmd-search]"), ("/terminal", "[data-testid=term-input]")]:
        open_(page, static_site, route)
        page.wait_for_selector(sel)
        ratio = page.evaluate(CONTRAST, sel)
        assert ratio >= 4.5, f"{theme} {route}: placeholder contrast {ratio:.2f}"
    ctx.close()


def test_the_deeper_panel_keeps_keyboard_focus_inside(page, static_site):
    """Regression: Shift+Tab right after opening the modal panel moved focus to the page behind it."""
    open_(page, static_site, lesson_url("o1.cli"))
    # the lesson is rendered and the page no longer moves (on a busy CI runner the click was lost while it did)
    page.wait_for_selector("[data-testid=flow-step]")
    page.evaluate("""() => new Promise(done => { let last = scrollY, same = 0, start = performance.now();
        const tick = () => { if (scrollY === last) same++; else { same = 0; last = scrollY }
            if (same >= 10 || performance.now() - start > 5000) done(); else requestAnimationFrame(tick) };
        requestAnimationFrame(tick) })""")
    page.get_by_test_id("go-deeper").click()
    panel = page.locator(".deeper-panel")
    expect(panel).to_be_visible()
    for keys in (["Shift+Tab"], ["Tab"] * 12, ["Shift+Tab"] * 12):
        for k in keys:
            page.keyboard.press(k)
        assert panel.evaluate("p => p.contains(document.activeElement)"), keys


# ---------------------------------------------------------------- keyboard in the search palette and the phone menu
def test_search_palette_keeps_and_returns_keyboard_focus(page, static_site):
    """The search dialog is modal: the focus stays in its field (the results are a listbox the arrows move through,
    not tab stops), Escape closes it, and the focus goes back to the button that opened it."""
    open_(page, static_site, "/learn")
    btn = page.locator(".topbar .search-btn")
    btn.focus()
    page.keyboard.press("Enter")
    field = page.get_by_test_id("palette-input")
    expect(field).to_be_focused()
    page.keyboard.type("route")
    dialog = page.locator(".palette-wrap")
    for key in ["Shift+Tab", "Tab", "Tab", "Shift+Tab"]:
        page.keyboard.press(key)
        expect(field).to_be_focused()
    page.keyboard.press("ArrowDown")
    expect(field).to_be_focused()
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(btn).to_be_focused()


def test_phone_menu_keeps_and_returns_keyboard_focus(browser, static_site):
    """The phone menu covers the page: Tab cycles between its links and its button (never to links hidden behind
    it), and Escape closes it with the focus back on the button."""
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    open_(page, static_site, "/learn")
    toggle = page.locator(".nav-toggle")
    toggle.focus()
    page.keyboard.press("Enter")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    for _ in range(40):
        page.keyboard.press("Tab")
        assert page.evaluate("!!document.activeElement.closest('.menu-sheet, .nav-toggle')"), page.evaluate("document.activeElement.outerHTML.slice(0, 120)")
    page.keyboard.press("Escape")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(toggle).to_be_focused()
    ctx.close()


def test_home_regions_and_challenge_list_structure(browser, static_site):
    """No two regions of the home page share a name; the challenge tiles' headings sit under a level-2 heading."""
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    open_(page, static_site, "/")
    names = page.evaluate("[...document.querySelectorAll('section[aria-labelledby]')].map(s => s.getAttribute('aria-labelledby'))")
    assert len(names) == len(set(names)), names
    open_(page, static_site, "/challenges")
    levels = page.evaluate("[...document.querySelectorAll('main h1, main h2, main h3')].map(h => +h.tagName[1])")
    assert levels[0] == 1 and all(b - a <= 1 for a, b in zip(levels, levels[1:])), levels
    ctx.close()
