"""Where newly revealed content lands. These tests measure the viewport, not the DOM: after a click that reveals
something, its start (heading, command line, first output line) must be on screen below the sticky header, the page
must not jump when the content was already visible, and closing a section must keep its summary on screen.

Every case runs at three sizes and from three starting positions of the control (near the top, the middle and the
bottom of the screen), because the original failures depended on where the control was when it was clicked."""
import pytest
from addresses import lab_url, lesson_url

SIZES = [(1440, 900), (820, 1180), (390, 844)]
POSITIONS = ["top", "middle", "bottom"]

GEOM = """(sel) => { const e = typeof sel === 'string' ? document.querySelector(sel) : sel; if (!e) return null;
  const r = e.getBoundingClientRect(); let hb = 0;
  // everything sticky that covers this element: the header, and on phones the lesson outline bar
  for (const h of document.querySelectorAll('.topbar, .outline, [data-sticky]')) {
    const cs = getComputedStyle(h); if (!['sticky','fixed'].includes(cs.position) || h.contains(e)) continue;
    const b = h.getBoundingClientRect(); if (!b.height || (!h.classList.contains('topbar') && (b.right <= r.left || b.left >= r.right))) continue;
    if (b.top <= (parseFloat(cs.top) || 0) + 1) hb = Math.max(hb, b.bottom); }
  return { top: r.top, bottom: r.bottom, height: r.height, header: hb, vh: innerHeight, y: scrollY } }"""


@pytest.fixture(params=SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def sized(browser, request):
    w, h = request.param
    ctx = browser.new_context(viewport={"width": w, "height": h}, reduced_motion="reduce")
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    yield pg
    ctx.close()


def place(pg, loc, where):
    """Scroll so that the control sits near the top, middle or bottom of the visible area."""
    vh = pg.viewport_size["height"]
    y = {"top": 140, "middle": vh // 2, "bottom": vh - 90}[where]
    top = loc.evaluate("e => e.getBoundingClientRect().top + scrollY")
    pg.evaluate(f"window.scrollTo(0, {top} - {y})")
    pg.wait_for_timeout(150)


def settle(pg):
    pg.wait_for_timeout(250)  # two animation frames plus the (instant, reduced-motion) scroll


def visible_start(g, need=40):
    """The element's start is on screen below the header, with at least `need` px of it visible."""
    return g["top"] >= g["header"] - 1 and g["top"] <= g["vh"] - need


@pytest.mark.parametrize("where", POSITIONS)
def test_replayed_output_is_shown_from_its_command_line(static_site, sized, where):
    pg = sized
    pg.goto(static_site.rstrip("/") + lab_url("lab.cli-tour"))
    pg.wait_for_selector("[data-testid=replay]", state="attached")
    pg.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")  # some of the lab's commands sit in sections
    pg.wait_for_timeout(100)
    btn = pg.locator("[data-testid=replay]:visible").nth(1)
    blk = btn.locator("xpath=ancestor::div[contains(@class,'cmdblock')][1]")
    place(pg, btn, where)
    btn.click()
    pg.wait_for_selector(".cmdblock.opened .screen, .cmdblock.opened pre", state="attached")
    settle(pg)
    g = blk.evaluate(GEOM)
    assert visible_start(g), f"command line not on screen: {g}"
    first_line = blk.locator(".screen, pre").first.evaluate(GEOM)
    usable = first_line["vh"] - first_line["header"]
    # the beginning of the output is visible, not just its last lines
    assert first_line["top"] < first_line["vh"] - min(60, usable / 4), f"output starts off screen: {first_line}"
    if g["height"] <= g["vh"] - g["header"] - 24:
        assert g["bottom"] <= g["vh"] + 1, f"a block that fits is not fully shown: {g}"


def test_nothing_moves_when_revealed_content_is_already_visible(static_site, sized):
    pg = sized
    pg.goto(static_site.rstrip("/") + lab_url("lab.cli-tour"))
    pg.wait_for_selector("[data-testid=replay]", state="attached")
    pg.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")  # some of the lab's commands sit in sections
    pg.wait_for_timeout(100)
    # the first replay of a short command near the top: its output fits below it
    btn = pg.locator("[data-testid=replay]:visible").first
    place(pg, btn, "top")
    blk = btn.locator("xpath=ancestor::div[contains(@class,'cmdblock')][1]")
    start = blk.evaluate(GEOM)  # a command line hidden under the sticky header may rightly be scrolled into view
    y0 = pg.evaluate("scrollY")
    btn.click()
    settle(pg)
    g = blk.evaluate("e => { const r = e.getBoundingClientRect(); return { bottom: r.bottom, vh: innerHeight } }")
    if g["bottom"] <= g["vh"] and start["top"] >= start["header"] + 12:  # the reveal policy keeps a 12 px gap
        assert pg.evaluate("scrollY") == y0, "the page moved although the output was already visible"


@pytest.mark.parametrize("where", ["middle", "bottom"])
def test_opening_a_section_shows_its_summary_and_first_lines(static_site, sized, where):
    pg = sized
    pg.goto(static_site.rstrip("/") + lab_url("lab.troubleshooting-tools"))
    pg.wait_for_selector("details.more", state="attached")
    d = pg.locator("details.more:visible").first
    if not d.count():
        pytest.skip("no section on this activity")
    d.evaluate("e => { e.open = false; e.id = 'probe-section' }")  # it may be open by default
    d = pg.locator("#probe-section")  # keep a handle that stays valid after the section opens
    place(pg, d, where)
    d.locator("summary").first.click()
    settle(pg)
    g = d.evaluate(GEOM)
    assert visible_start(g, need=120), f"section summary or first lines off screen: {g}"


def test_closing_a_section_keeps_its_summary_on_screen(static_site, sized):
    pg = sized
    pg.goto(static_site.rstrip("/") + lab_url("lab.troubleshooting-tools"))
    pg.wait_for_selector("details.more", state="attached")
    d = pg.locator("details.more:visible").first
    if not d.count():
        pytest.skip("no section on this activity")
    d.evaluate("e => { e.open = false; e.id = 'probe-section' }")  # it may be open by default
    d = pg.locator("#probe-section")  # keep a handle that stays valid after the section opens
    place(pg, d, "top")
    d.locator("summary").first.click()
    settle(pg)
    h = d.evaluate("e => e.getBoundingClientRect().height")
    if h < pg.viewport_size["height"]:
        pytest.skip("section too short to scroll inside")
    # read deep inside the section, then close it with the keyboard from its summary
    top = d.evaluate("e => e.getBoundingClientRect().top + scrollY")
    pg.evaluate(f"window.scrollTo(0, {top} + {h} * 0.6)")
    pg.wait_for_timeout(150)
    d.locator("summary").first.focus()  # Playwright scrolls focus targets into view; restore the reading position
    pg.evaluate(f"window.scrollTo(0, {top} + {h} * 0.6)")
    pg.wait_for_timeout(150)
    pg.keyboard.press("Enter")
    settle(pg)
    g = d.locator("summary").first.evaluate(GEOM)
    assert g["top"] >= g["header"] - 1 and g["bottom"] <= g["vh"], f"summary lost after closing: {g}"


def test_back_restores_the_reading_position(static_site, sized):
    pg = sized
    pg.goto(static_site + "labs")
    pg.wait_for_selector("main a[href^='/labs/']")
    link = pg.locator("main a[href^='/labs/']").nth(8)
    place(pg, link, "bottom")
    link.hover()  # Playwright may scroll the target before clicking; measure the position the learner left from
    pg.wait_for_timeout(100)
    y0 = pg.evaluate("scrollY")
    assert y0 > 0
    link.click()
    pg.wait_for_selector(".page h1")
    pg.wait_for_timeout(200)
    assert pg.evaluate("scrollY") == 0, "a new page should start at the top"
    pg.go_back()
    pg.wait_for_selector("main a[href^='/labs/']")
    pg.wait_for_timeout(400)
    assert abs(pg.evaluate("scrollY") - y0) <= 2, "Back did not return to the reading position"


def test_terminal_starter_shows_the_terminal_and_does_not_jump(static_site, sized):
    pg = sized
    pg.goto(static_site + "terminal")
    pg.wait_for_selector(".transcript")
    starter = pg.locator(".transcript button.linkish, .tx-starters button, .starters button").first
    if not starter.count():
        pytest.skip("no starter commands on the terminal page")
    place(pg, starter, "bottom")
    starter.click()
    settle(pg)
    g = pg.evaluate(GEOM, ".transcript")
    usable = g["vh"] - g["header"]
    if g["height"] <= usable - 24:
        assert g["top"] >= g["header"] - 1 and g["bottom"] <= g["vh"] + 1, f"terminal not fully shown: {g}"
    else:
        assert visible_start(g), f"terminal title bar not on screen: {g}"


def test_check_verdict_is_shown(static_site, sized):
    pg = sized
    pg.goto(static_site.rstrip("/") + lesson_url("d.services-dns"))
    pg.wait_for_selector("[data-testid=flow-step]")
    step = pg.locator("[data-testid=flow-step][data-kind=check]").first
    opt = step.locator("[data-testid=choice]").first
    place(pg, opt, "bottom")
    opt.click()
    step.get_by_role("button", name="Check my answer").click()
    settle(pg)
    g = step.locator(".verdict").first.evaluate(GEOM)
    assert g and visible_start(g, need=30), f"verdict off screen: {g}"
