"""Firefox regressions on the exported static site. No API or cluster server is used.

Long-output fixtures extend the public command corpus using the existing transcript
test style; page structure and all reveal/follow code remain the production build.
"""
import re

from playwright.sync_api import expect
from addresses import lab_url, lesson_url


def settle(page):
    page.wait_for_timeout(300)


def terminal(page, site):
    examples = [
        ("oc get review-old -n academy-review", "old history\n" * 80),
        ("oc get review-middle -n academy-review", "middle history\n" * 40),
        ("oc get review-new -n academy-review", "new output\n" * 100),
    ]
    def corpus(route):
        response = route.fetch()
        original = response.json()
        original += [{"cmd": cmd, "stdout": out, "stderr": "", "code": 0, "tested": True,
                      "run": None, "lab": "audit", "lab_title": "Review output fixture", "kind": "lab",
                      "as": "learner", "meaning": "", "skip": ""} for cmd, out in examples]
        route.fulfill(response=response, json=original)
    page.route("**/data/en/commands.json", corpus)
    page.emulate_media(reduced_motion="reduce")
    page.goto(site + "terminal")
    page.wait_for_selector("[data-testid=term-input]")
    return [cmd for cmd, _ in examples]


def submit(page, cmd):
    page.get_by_test_id("term-input").fill(cmd)
    page.get_by_test_id("term-input").press("Enter")
    settle(page)


def test_V2_13_phone_contents_jump_clears_the_header(browser, static_site):
    """On a phone, a contents link brings its heading below the sticky header, not under it."""
    context = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page = context.new_page()
    try:
        page.goto(static_site.rstrip("/") + lesson_url("d.services-dns"))
        page.wait_for_selector("[data-testid=flow-step]")
        page.locator(".flow-toc > summary").click()
        link = page.get_by_test_id("toc-link").nth(2)
        target = link.get_attribute("href").lstrip("#")
        link.click()
        settle(page)
        geometry = page.evaluate("""(id) => {
            const a = document.getElementById(id).getBoundingClientRect();
            const h = document.querySelector('.topbar').getBoundingClientRect();
            const bar = document.querySelector('.flow-parts').getBoundingClientRect();  // the sticky contents bar under it
            return {heading: a.top, header: h.bottom, bar: bar.bottom};
        }""", target)
        assert geometry["bar"] - 1 <= geometry["heading"] <= geometry["bar"] + 40, geometry
    finally:
        context.close()


def test_V2_14_new_output_button_shows_new_command_start(page, static_site):
    """A learner returning from history must start reading a long new result at its command, not its last lines."""
    cmds = terminal(page, static_site)
    submit(page, cmds[0])
    submit(page, cmds[1])
    body = page.locator(".tx-body")
    body.evaluate("e => e.scrollTop = 0")
    settle(page)
    submit(page, cmds[2])
    jump = page.locator(".tx-jump")
    expect(jump).to_be_visible()
    jump.click()
    settle(page)
    geometry = body.evaluate("""e => {
        const panel = e.getBoundingClientRect(), command = e.querySelector('.tx-entry:last-child .tx-cmdline').getBoundingClientRect();
        return {command: command.top, panel: panel.top, bottom: panel.bottom};
    }""")
    assert geometry["panel"] <= geometry["command"] <= geometry["bottom"] - 30, geometry


def test_V2_15_expanding_output_reveals_new_retained_lines(page, static_site):
    """Expanding a long excerpt should show the newly retained text from a readable start, not the viewport's last few pixels."""
    page.emulate_media(reduced_motion="reduce")
    def lesson(route):
        response = route.fetch()
        data = response.json()
        # Keep the real command and recording match; only length changes.
        for entry in data["recording"]["entries"]:
            entry["stdout"] = "retained output line\n" * 120
        route.fulfill(response=response, json=data)
    page.route("**/data/en/labs/lab.cli-tour.json", lesson)
    page.goto(static_site.rstrip("/") + lab_url("lab.cli-tour"))
    page.wait_for_selector("[data-testid=replay]", state="attached")
    page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
    settle(page)
    page.get_by_test_id("replay").first.click()
    settle(page)
    more = page.locator(".cmdblock .tx-more").first
    expect(more).to_be_visible()
    more.evaluate("e => window.scrollTo(0, e.getBoundingClientRect().top + scrollY - (innerHeight - 100))")
    settle(page)
    more.click()
    settle(page)
    geometry = page.locator(".cmdblock .transcript-stream .ln").nth(40).evaluate("""e => {
        const r = e.getBoundingClientRect(), h = document.querySelector('.topbar').getBoundingClientRect();
        return {line: r.top, header: h.bottom, height: innerHeight};
    }""")
    usable = geometry["height"] - geometry["header"] - 24
    assert geometry["header"] <= geometry["line"] <= geometry["header"] + 12 + usable * .4, geometry


def test_V2_16_forward_restores_scroll_saved_just_before_back(page, static_site):
    """Back immediately after scrolling must not erase the reading position that Forward should restore."""
    page.emulate_media(reduced_motion="reduce")
    page.goto(static_site + "labs")
    page.wait_for_selector(f"main a[href='{lab_url('lab.rbac')}']")
    page.locator(f"main a[href='{lab_url('lab.rbac')}']").click()
    page.wait_for_selector(".lab-h")
    settle(page)
    # scroll and Back occur in one task, before the router's 120ms save timer.
    wanted = page.evaluate("""() => {
        window.scrollTo(0, 800);
        const y = scrollY;
        history.back();
        return y;
    }""")
    assert wanted >= 200
    page.wait_for_url(re.compile(r".*/labs/?$"))  # a static host may add the trailing slash (http.server) or remove it (nginx)
    settle(page)
    page.evaluate("history.forward()")
    page.wait_for_url("**" + lab_url("lab.rbac"))
    page.wait_for_selector(".lab-h")
    settle(page)
    actual = page.evaluate("scrollY")
    assert abs(actual - wanted) <= 2, {"expected": wanted, "actual": actual}
