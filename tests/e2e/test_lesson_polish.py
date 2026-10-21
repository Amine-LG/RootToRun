"""The lesson page after the release polish (2026-10-20): what a learner found awkward, checked where it happens.

- "Before you start" (the lesson's source files) moved the page the wrong way when it was opened: the reveal policy
  counted the desktop contents column as a header, because that full-width box reaches over the column.
- The "Go deeper and references" sheet sat under the sticky site header: its title and close button were hidden.
- The phone's "In this lesson" list pushed the lesson down when open and stayed open on a tap elsewhere.
- The lesson's brief ("You will be able to", "To practise this yourself") was narrower than the lesson under it.
- The page bar listed six actions in one row with nothing to tell them apart.
- On Progress, a group's labels started wherever the figure before them ended ("0", "–", "12/15").
"""
import re

import pytest
from playwright.sync_api import expect
from addresses import lesson_at, lesson_url
from conftest import wait_true

SOURCES = "o3.init-sidecars"  # a lesson with source files ("Before you start") and depth sections
SHOTS = "o1.console-apps"  # a lesson with console screenshots

SETTLED = """() => new Promise(done => { let last = scrollY, same = 0, start = performance.now();
    const tick = () => { if (scrollY === last) same++; else { same = 0; last = scrollY }
        if (same >= 10 || performance.now() - start > 5000) done(); else requestAnimationFrame(tick) };
    requestAnimationFrame(tick) })"""

# the bottom of the sticky bars that run across the reading column (the header, the page bar, the phone's contents bar)
BARS = """() => { let b = 0; for (const el of document.querySelectorAll('.topbar, [data-sticky]')) { const cs = getComputedStyle(el)
    if (cs.position === 'sticky' || cs.position === 'fixed') { const r = el.getBoundingClientRect(); if (r.width > innerWidth / 2) b = Math.max(b, r.bottom) } }
    return b }"""


def box(loc):
    return loc.evaluate("e => { const r = e.getBoundingClientRect(); return {l: r.left, r: r.right, t: r.top, b: r.bottom} }")


def open_lesson(page, site, lid, wait="[data-testid=flow-step]"):
    page.goto(site.rstrip("/") + lesson_url(lid))
    page.wait_for_selector(wait)
    page.evaluate(SETTLED)


def finger(page, loc):
    """a finger on the control where it is (locator.tap() first scrolls a target in a sticky bar "into view" in
    Chromium, which moves the page by itself)"""
    b = loc.bounding_box()
    page.touchscreen.tap(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)


@pytest.fixture
def phone(browser):
    ctx = browser.new_context(viewport={"width": 375, "height": 760}, has_touch=True)
    pg = ctx.new_page()
    yield pg
    ctx.close()


# ---------------------------------------------------------------- "Before you start"
def test_before_you_start_opens_where_it_is(page, static_site):
    """Opening it, and a file inside it, keeps the learner at that place: the page only scrolls down to show what
    opened, never up, and the title clicked stays on screen below the sticky bars."""
    open_lesson(page, static_site, SOURCES)
    sources = page.get_by_test_id("lesson-sources")
    sources.evaluate("e => e.scrollIntoView({block: 'center'})")
    page.evaluate(SETTLED)
    y0 = page.evaluate("scrollY")
    sources.locator(":scope > summary").click()
    expect(sources).to_have_attribute("open", "")
    page.evaluate(SETTLED)
    y1 = page.evaluate("scrollY")
    assert y1 >= y0, ("the page moved up when the section opened", y0, y1)
    assert box(sources.locator(":scope > summary"))["t"] >= page.evaluate(BARS)
    file = sources.get_by_test_id("lesson-source-file").first
    file.locator("summary").click()
    expect(file).to_have_attribute("open", "")
    page.evaluate(SETTLED)
    assert page.evaluate("scrollY") >= y1
    title = box(file.locator("summary"))
    assert page.evaluate(BARS) <= title["t"] < page.viewport_size["height"], title
    # the keyboard does the same: Enter on the title closes the file, which keeps its title on screen
    file.locator("summary").focus()
    page.keyboard.press("Enter")
    expect(file).not_to_have_attribute("open", "")
    page.evaluate(SETTLED)
    title = box(file.locator("summary"))
    assert page.evaluate(BARS) <= title["t"] < page.viewport_size["height"], title


# ---------------------------------------------------------------- "Go deeper and references"
@pytest.mark.parametrize("width", [1360, 375])
def test_deeper_sheet_shows_its_close_button_and_closes_in_place(browser, static_site, width):
    """The sheet lies above the whole page, the site header included: its close button is the element under its own
    centre. The button, Escape and a click beside the sheet each close it, as often as it is opened, without moving
    the page, and the focus returns to "Go deeper"."""
    ctx = browser.new_context(viewport={"width": width, "height": 800})
    page = ctx.new_page()
    open_lesson(page, static_site, SOURCES)
    page.evaluate("scrollTo(0, 1800)")
    page.evaluate(SETTLED)
    y = page.evaluate("scrollY")
    opener = page.get_by_test_id("go-deeper")
    for how in ("button", "escape", "backdrop", "button"):
        if not opener.evaluate("b => { const r = b.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight }"):
            opener.scroll_into_view_if_needed()  # phones: the page bar scrolls away; the button is at the top of the lesson
            page.evaluate(SETTLED)
            y = page.evaluate("scrollY")
        # a real click where the button is: Playwright's click() first scrolls a target in a sticky bar "into view" in
        # Chromium, which moves the page by itself
        b = opener.bounding_box()
        page.mouse.click(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
        dialog = page.get_by_role("dialog", name="Go deeper and references")
        expect(dialog).to_be_visible()
        close = dialog.get_by_role("button", name="Close")
        expect(close).to_be_visible()
        assert close.evaluate("b => { const r = b.getBoundingClientRect(); return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)?.closest('button') === b }"), "something covers the close button"
        if how == "button":
            close.click()
        elif how == "escape":
            page.keyboard.press("Escape")
        else:
            page.mouse.click(8, page.viewport_size["height"] // 2) if width > 600 else page.keyboard.press("Escape")  # a phone sheet has no room beside it
        expect(dialog).to_have_count(0)
        expect(opener).to_be_focused()
        assert abs(page.evaluate("scrollY") - y) <= 2, (how, y, page.evaluate("scrollY"))
    ctx.close()


def test_deeper_sheet_title_stays_in_view_while_its_content_scrolls(page, static_site):
    open_lesson(page, static_site, SOURCES)
    page.get_by_test_id("go-deeper").click()
    sheet = page.locator(".deeper-panel")
    for d in sheet.locator("details").all():
        d.locator("summary").click()
    sheet.evaluate("s => s.scrollTo(0, s.scrollHeight)")
    close = sheet.get_by_test_id("deeper-close")
    assert box(close)["t"] >= 0 and box(close)["b"] <= box(sheet)["b"]
    expect(close).to_be_in_viewport()


# ---------------------------------------------------------------- the phone's "In this lesson"
def test_phone_contents_lies_over_the_page_and_closes_on_a_tap_elsewhere(phone, static_site):
    open_lesson(phone, static_site, SOURCES)
    phone.evaluate("scrollTo(0, 2400)")
    phone.evaluate(SETTLED)
    y = phone.evaluate("scrollY")
    toc = phone.locator(".flow-toc")
    finger(phone, toc.locator("summary"))
    expect(toc).to_have_attribute("open", "")
    links = phone.get_by_test_id("toc-link")
    expect(links.first).to_be_in_viewport()
    phone.wait_for_timeout(300)
    assert phone.evaluate("scrollY") == y, "opening the list moved the page"
    # a tap on the lesson below the list closes it and does nothing else (no link followed, no scrolling)
    url = phone.url
    lst = box(toc.locator("ol"))
    phone.touchscreen.tap(180, min(lst["b"] + 60, 700))
    expect(toc).not_to_have_attribute("open", "")
    expect(phone.get_by_test_id("toc-scrim")).to_have_count(0)  # nothing invisible is left to block the page
    assert phone.url == url and phone.evaluate("scrollY") == y
    # the site header counts as elsewhere too
    toc.locator("summary").tap()
    expect(toc).to_have_attribute("open", "")
    phone.locator(".topbar .brand, .topbar a").first.dispatch_event("pointerdown")
    expect(toc).not_to_have_attribute("open", "")


def test_phone_contents_escape_and_choosing_a_section(phone, static_site):
    open_lesson(phone, static_site, SOURCES)
    toc = phone.locator(".flow-toc")
    summary = toc.locator("summary")
    summary.focus()
    phone.keyboard.press("Enter")
    expect(toc).to_have_attribute("open", "")
    phone.keyboard.press("Tab")  # into the list
    phone.keyboard.press("Escape")
    expect(toc).not_to_have_attribute("open", "")
    expect(summary).to_be_focused()
    # choosing a section closes the list, names it in the address and shows its heading under the bar
    summary.tap()
    link = phone.get_by_test_id("toc-link").nth(2)
    target = link.get_attribute("href")
    link.tap()
    expect(toc).not_to_have_attribute("open", "")
    wait_true(phone, f"location.hash === {target!r}")
    phone.evaluate(SETTLED)
    head = box(phone.locator(f"[id='{target[1:]}']"))
    assert phone.evaluate(BARS) <= head["t"] < 760 / 2, head
    # Back returns to the place before the jump
    phone.go_back()
    wait_true(phone, "location.hash === ''")


def test_desktop_contents_stays_open_beside_the_lesson(page, static_site):
    open_lesson(page, static_site, SOURCES)
    expect(page.locator(".flow-toc")).to_have_attribute("open", "")
    page.mouse.click(700, 500)
    expect(page.locator(".flow-toc")).to_have_attribute("open", "")
    expect(page.get_by_test_id("toc-scrim")).to_have_count(0)


# ---------------------------------------------------------------- the lesson's brief
@pytest.mark.parametrize("width", [1280, 1440])
def test_brief_is_as_wide_as_the_lesson_and_in_two_columns(browser, static_site, width):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    open_lesson(page, static_site, SHOTS)
    brief, flow = box(page.get_by_test_id("lesson-brief")), box(page.locator(".lesson-flow"))
    assert abs(brief["l"] - flow["l"]) <= 1 and abs(brief["r"] - flow["r"]) <= 1, (brief, flow)
    goal, need = box(page.locator(".lesson-brief .lesson-goal")), box(page.get_by_test_id("prereqs"))
    assert abs(goal["t"] - need["t"]) <= 1 and goal["r"] <= need["l"] + 1, (goal, need)
    expect(page.locator(".lesson-goal")).to_contain_text("You will be able to")
    expect(page.locator(".lesson-goal .md")).not_to_be_empty()
    ctx.close()


@pytest.mark.parametrize("width", [375, 430, 768])
def test_brief_and_bar_fit_narrow_screens(browser, static_site, width):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    open_lesson(page, static_site, SHOTS)
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    goal, need = box(page.locator(".lesson-brief .lesson-goal")), box(page.get_by_test_id("prereqs"))
    if width < 600:
        assert need["t"] >= goal["b"] - 1, "one column on phones"
    # the pager: its own row, at the right end, Next after Previous
    prev, nxt = box(page.get_by_test_id("pager-prev")), box(page.get_by_test_id("pager-next"))
    bar = box(page.get_by_test_id("page-bar"))
    assert prev["r"] <= nxt["l"] and abs(nxt["r"] - bar["r"]) <= 2, (prev, nxt, bar)
    assert prev["t"] > box(page.locator(".lesson-bar > .back"))["t"], "the pager is on the second row"
    ctx.close()


# ---------------------------------------------------------------- the lesson's actions
def test_lesson_bar_groups_actions_and_leads_through_the_course(page, static_site):
    """One row on wide screens, in reading order: the way back, supporting material, then Previous and Next at the
    right end; Next is the one button. The keyboard meets them in that order, and Next and Previous are each other's
    way back."""
    lid = SHOTS
    open_lesson(page, static_site, lid)
    bar = page.get_by_test_id("page-bar")
    back, deeper = bar.locator(".back"), page.get_by_test_id("go-deeper")
    prev, nxt = page.get_by_test_id("pager-prev"), page.get_by_test_id("pager-next")
    tops = {round(box(x)["t"] + (box(x)["b"] - box(x)["t"]) / 2) for x in (back, deeper, prev, nxt)}
    assert max(tops) - min(tops) <= 2, "one row"
    assert box(back)["r"] <= box(deeper)["l"] < box(prev)["l"] < box(nxt)["l"]
    assert bar.evaluate("b => b.lastElementChild.matches('.lesson-pager')")
    assert "btn" in nxt.get_attribute("class") and "btn" not in prev.get_attribute("class")
    expect(nxt).to_have_accessible_name(re.compile(r"^Next\s*:\s*" + re.escape(nxt.get_attribute("title")) + "$"))
    expect(prev).to_have_accessible_name(re.compile(r"^Previous\s*:\s*" + re.escape(prev.get_attribute("title")) + "$"))
    # the keyboard order is the reading order: Go deeper, the contribution actions when the site has a repository
    # (Report a problem, Edit), Previous, Next
    deeper.focus()
    met = []
    for _ in range(8):
        page.keyboard.press("Tab")
        met.append(page.evaluate("document.activeElement.dataset.testid || document.activeElement.className"))
        if met[-1] == "pager-next":
            break
    contribution = met[:-2]
    assert met[-2:] == ["pager-prev", "pager-next"], met
    assert all(m in ("report-menu", "edit-source", "edit-menu") for m in contribution), met
    assert contribution == [m for m in ("report-menu", "edit-source", "edit-menu") if m in contribution], met
    expect(nxt).to_be_focused()
    page.keyboard.press("Enter")
    page.wait_for_url(lambda u: lesson_at(u) not in (None, lid))
    page.wait_for_selector("[data-testid=pager-prev]")
    assert lesson_at(page.url) and page.get_by_test_id("pager-prev").get_attribute("href") == lesson_url(lid)
    page.get_by_test_id("pager-prev").click()
    page.wait_for_url(lambda u: lesson_at(u) == lid)


# ---------------------------------------------------------------- Progress: "What you have done"
LABELS = """() => [...document.querySelectorAll('.me-group')].map(g => [...g.querySelectorAll('.stat-card')].map(c => {
    const n = c.querySelector('strong').getBoundingClientRect(), l = c.querySelector('span'), r = l.getBoundingClientRect()
    const range = document.createRange(); range.setStart(l.firstChild, 0); range.setEnd(l.firstChild, 1)
    return { nl: n.left, nr: n.right, ll: r.left, nb: n.bottom, first: range.getBoundingClientRect().bottom }
}))"""


@pytest.mark.parametrize("width,font", [(1280, 16), (375, 16), (1280, 22)])
def test_progress_figures_and_labels_line_up_whatever_the_figures(browser, static_site, width, font):
    """Within a group every label starts at the same place, after the widest figure, and each figure stands on the
    line of its label's first line of text: with no progress ("0", "–"), and with wider figures such as "12/15"
    (written into the page here: only the widths matter), on a phone and with a larger text size."""
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    page.goto(static_site.rstrip("/") + "/me")
    page.wait_for_selector(".me-group .stat-card")
    page.evaluate(f"document.documentElement.style.fontSize = '{font}px'")
    for state in ("empty", "wide"):
        if state == "wide":
            page.evaluate("""() => { const s = document.querySelectorAll('.me-group .stat-card strong'); s[1].textContent = '12/15'; s[4].textContent = '7' }""")
        for group in page.evaluate(LABELS):
            assert len({round(c["ll"]) for c in group}) == 1, (state, group)
            for c in group:
                assert c["nr"] <= c["ll"], (state, c)
                assert abs(c["nb"] - c["first"]) <= 6, ("figure and first line of its label", state, c)
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    ctx.close()


# ---------------------------------------------------------------- found by the independent review
def test_search_shortcut_waits_while_the_deeper_sheet_is_open(page, static_site):
    """Ctrl+K opened the search palette underneath the sheet, which kept the keys."""
    open_lesson(page, static_site, SOURCES)
    page.get_by_test_id("go-deeper").click()
    expect(page.locator(".deeper-panel")).to_be_visible()
    page.keyboard.press("Control+k")
    page.wait_for_timeout(200)
    expect(page.locator(".palette-wrap")).to_have_count(0)
    page.keyboard.press("Escape")
    expect(page.locator(".deeper-panel")).to_have_count(0)
    page.keyboard.press("Control+k")
    expect(page.locator(".palette-wrap")).to_be_visible()  # the shortcut works again once the sheet is closed


def test_phone_contents_closes_when_the_keyboard_leaves_it(phone, static_site):
    open_lesson(phone, static_site, SOURCES)
    toc = phone.locator(".flow-toc")
    toc.locator("summary").focus()
    phone.keyboard.press("Enter")
    expect(toc).to_have_attribute("open", "")
    for _ in range(phone.get_by_test_id("toc-link").count() + 3):  # Firefox also stops on the scrollable list itself
        phone.keyboard.press("Tab")
        if not toc.evaluate("d => d.contains(document.activeElement)"):
            break
    expect(toc).not_to_have_attribute("open", "")
    expect(phone.get_by_test_id("toc-scrim")).to_have_count(0)
    assert not toc.evaluate("d => d.contains(document.activeElement)")


def test_contents_follow_the_layout_when_the_window_is_resized(page, static_site):
    open_lesson(page, static_site, SOURCES)
    toc = page.locator(".flow-toc")
    expect(toc).to_have_attribute("open", "")
    page.set_viewport_size({"width": 768, "height": 900})
    expect(toc).not_to_have_attribute("open", "")  # the phone bar starts closed instead of covering the lesson
    expect(page.get_by_test_id("toc-scrim")).to_have_count(0)
    page.set_viewport_size({"width": 1360, "height": 900})
    expect(toc).to_have_attribute("open", "")


def test_phone_contents_opened_low_on_the_screen_fit_in_the_window(phone, static_site):
    """Opened before its bar has reached the top (the lesson's start is still on screen), the list used to run off the
    bottom of the window, where its last links could not be reached."""
    open_lesson(phone, static_site, SOURCES)
    summary = phone.locator(".flow-toc > summary")
    summary.evaluate("s => scrollTo(0, scrollY + s.getBoundingClientRect().top - innerHeight + 60)")  # the bar near the bottom
    phone.evaluate(SETTLED)
    summary.tap()
    expect(phone.locator(".flow-toc")).to_have_attribute("open", "")
    phone.evaluate(SETTLED)
    lst = box(phone.locator(".flow-toc ol"))
    assert lst["t"] >= 0 and lst["b"] <= 760, lst
    last = phone.get_by_test_id("toc-link").last
    last.scroll_into_view_if_needed()
    assert box(last)["b"] <= 760


def test_phone_contents_still_fit_when_the_window_gets_shorter(phone, static_site):
    """Found by the second review: the room was measured only when the list opened."""
    open_lesson(phone, static_site, SOURCES)
    summary = phone.locator(".flow-toc > summary")
    summary.evaluate("s => scrollTo(0, scrollY + s.getBoundingClientRect().top - 380)")  # the bar in the middle
    phone.evaluate(SETTLED)
    summary.tap()
    expect(phone.locator(".flow-toc")).to_have_attribute("open", "")
    phone.set_viewport_size({"width": 375, "height": 550})
    phone.wait_for_timeout(300)
    lst = box(phone.locator(".flow-toc ol"))
    assert lst["b"] <= 550, lst


@pytest.mark.parametrize("w,h,at", [(390, 844, 0.6), (390, 844, 0.4), (844, 390, 0.5)])
def test_phone_contents_end_above_the_tab_bar(browser, static_site, w, h, at):
    """Found by the final phone audit: the list's room was measured to the bottom of the window, under the tab bar, so
    its last links lay under the bar even with the list scrolled to its end, and a tap there opened a tab instead."""
    ctx = browser.new_context(viewport={"width": w, "height": h}, has_touch=True)
    pg = ctx.new_page()
    open_lesson(pg, static_site, "d.networkpolicy-ovn")  # a long list of sections
    summary = pg.locator(".flow-toc > summary")
    summary.evaluate(f"s => scrollTo(0, scrollY + s.getBoundingClientRect().top - innerHeight * {at})")
    pg.evaluate(SETTLED)
    finger(pg, summary)
    expect(pg.locator(".flow-toc")).to_have_attribute("open", "")
    pg.evaluate(SETTLED)
    bar = box(pg.get_by_test_id("tabbar"))
    assert bar["t"] < h  # the tab bar is shown at this size
    assert box(pg.locator(".flow-toc ol"))["b"] <= bar["t"] + 0.5
    last = pg.get_by_test_id("toc-link").last
    last.evaluate("a => a.closest('ol').scrollTo(0, 1e6)")
    pg.wait_for_timeout(200)
    b = box(last)
    assert pg.evaluate("([x, y]) => document.elementFromPoint(x, y)?.closest('[data-testid=toc-link]') === [...document.querySelectorAll('[data-testid=toc-link]')].at(-1)",
                       [(b["l"] + b["r"]) / 2, (b["t"] + b["b"]) / 2]), (b, bar)
    ctx.close()
