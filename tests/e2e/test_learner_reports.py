"""Three problems a learner found while studying the Linux path:

1. a typed command was drawn differently from what was typed: the monospace font's contextual alternates turned `../`
   into ` ./` and `/*` into ` *` (the value was right; the field showed other characters), because a `font:`
   shorthand reset the rule that turns them off;
2. a question answered wrongly, then rightly after "Try again", still counted as wrong in the lesson's score and the
   course outline (the corrected answer was saved, but the score left out an answer given after seeing the answer);
3. opening "Go deeper and references", opening or closing a section in it, and closing it scrolled the page behind.
"""
from playwright.sync_api import expect
from addresses import lesson_url, track_url
from conftest import wait_true

SAMPLES = ["cat ../readme.txt", "echo rm logs/*.txt", "grep -c 'x' ./a//b.txt", "ls -- -> <= != == ::"]


def test_a_typed_command_is_drawn_with_its_own_characters(page, static_site):
    page.goto(static_site.rstrip("/") + lesson_url("lx.first-steps"))
    field = page.get_by_test_id("try-input").last
    field.click()
    field.press_sequentially(SAMPLES[0], delay=5)
    expect(field).to_have_value(SAMPLES[0])
    # every element drawn in the monospace font, the try field included, has contextual forms off
    bad = page.evaluate("""() => [...document.querySelectorAll('*')].filter(e => {
        const cs = getComputedStyle(e)
        return /JetBrains/.test(cs.fontFamily) && !/none|no-contextual/.test(cs.fontVariantLigatures)
      }).map(e => e.tagName + '.' + e.className).slice(0, 5)""")
    assert bad == [], bad
    assert page.evaluate("getComputedStyle(document.querySelector('[data-testid=try-input]')).fontVariantLigatures") == "none"


def test_a_mistyped_path_is_not_accepted(page, static_site):
    """The answer is compared as typed: `./readme.txt` (what the font drew) is not `../readme.txt`."""
    page.goto(static_site.rstrip("/") + lesson_url("lx.first-steps"))
    tries = page.get_by_test_id("try")
    step = tries.filter(has_text="directory above").first
    step.get_by_test_id("try-input").fill("cat ./readme.txt")
    step.get_by_test_id("try-check").click()
    expect(step.get_by_test_id("try-hint")).to_be_visible()
    expect(step.get_by_test_id("try-ok")).to_have_count(0)
    step.get_by_test_id("try-input").fill("cat ../readme.txt")
    step.get_by_test_id("try-check").click()
    expect(step.get_by_test_id("try-ok")).to_contain_text("cat ../readme.txt")


def answer(q, right: bool):
    """Pick choices until one is right (right=True) or until one is wrong (right=False); leaves it submitted."""
    choices = q.get_by_test_id("choice")
    for c in range(choices.count()):
        choices.nth(c).click()
        q.get_by_test_id("check-submit").click()
        ok = "is-right" in (q.get_attribute("class") or "")
        if ok == right:
            return
        q.get_by_test_id("check-again").click()
    raise AssertionError("no such choice")


def test_a_corrected_answer_counts_in_the_score_and_says_how(page, static_site):
    page.goto(static_site.rstrip("/") + lesson_url("lx.first-steps"))
    checks = page.get_by_test_id("check")
    expect(checks).to_have_count(2)
    answer(checks.nth(0), True)
    answer(checks.nth(1), False)
    expect(page.get_by_test_id("lesson-facts")).to_contain_text("checks 1/2 right")
    checks.nth(1).get_by_test_id("check-again").click()
    answer(checks.nth(1), True)
    expect(page.get_by_test_id("lesson-facts")).to_contain_text("checks 2/2 right (1 after seeing the answer)")
    # the record keeps both attempts: the first was wrong, the latest is right and was given after seeing the answer
    rec = page.evaluate("""() => { const p = JSON.parse(localStorage.getItem('osa.progress.v2')).predictions
        return Object.values(p).find(r => !r.first.ok) }""")
    assert rec["latest"]["ok"] and rec["latest"]["shown"] and rec["n"] >= 2
    # saved progress, read again after a reload and through the app's own navigation: the index and the lesson agree
    page.reload()
    expect(page.get_by_test_id("lesson-facts")).to_contain_text("checks 2/2 right (1 after seeing the answer)")
    page.locator(f"a[href='{track_url('linux')}']").first.click()  # the lesson's link to its course index
    item = page.locator(".lesson-list a", has_text="Your first minutes in a shell")
    expect(item.locator(".l-facts")).to_have_text("checks 2/2")
    page.reload()
    expect(item.locator(".l-facts")).to_have_text("checks 2/2")
    item.click()
    expect(page.get_by_test_id("lesson-facts")).to_contain_text("checks 2/2 right (1 after seeing the answer)")
    page.go_back()
    expect(item.locator(".l-facts")).to_have_text("checks 2/2")


def test_progress_saved_before_the_fix_is_scored_by_its_latest_answer(page, static_site):
    """A record written before the fix (wrong, then right after the answer was shown) needs no migration."""
    page.goto(static_site.rstrip("/") + lesson_url("lx.first-steps"))
    checks = page.get_by_test_id("check")
    expect(checks).to_have_count(2)
    qids = page.evaluate("fetch('/data/en/curriculum.json').then(r => r.json()).then(c => c.lessons['lx.first-steps'].checks)")
    page.evaluate("""(qids) => {
        const p = JSON.parse(localStorage.getItem('osa.progress.v2') || '{}')
        const t = Date.now() - 3600e3, right = { ok: true, at: t, pick: 0 }
        p.predictions = { ...(p.predictions || {}), [qids[0]]: { first: right, latest: right, n: 1 },
          [qids[1]]: { first: { ok: false, at: t, pick: 2 }, latest: { ok: true, at: t + 9e3, pick: 0, shown: true, revealedAt: t + 1e3 }, n: 2 } }
        localStorage.setItem('osa.progress.v2', JSON.stringify(p)) }""", qids)
    page.goto(static_site.rstrip("/") + track_url("linux"))
    item = page.locator(".lesson-list a", has_text="Your first minutes in a shell")
    expect(item.locator(".l-facts")).to_have_text("checks 2/2")
    item.click()
    expect(page.get_by_test_id("lesson-facts")).to_contain_text("checks 2/2 right (1 after seeing the answer)")


def click_center(page, loc):
    b = loc.bounding_box()
    page.mouse.click(b["x"] + min(20, b["width"] / 2), b["y"] + b["height"] / 2)  # a real click: no scroll into view first


def test_go_deeper_keeps_the_reading_position(page, static_site):
    page.goto(static_site.rstrip("/") + lesson_url("lx.shell-expansion"))
    page.wait_for_load_state("networkidle")
    page.evaluate("scrollTo(0, 2500)")
    wait_true(page, "scrollY > 2000")
    page.wait_for_timeout(300)
    y = page.evaluate("Math.round(scrollY)")
    at = lambda: page.evaluate("Math.round(scrollY)")
    click_center(page, page.get_by_test_id("go-deeper"))
    panel = page.locator(".deeper-panel")
    expect(panel).to_be_visible()
    page.wait_for_timeout(500)
    assert abs(at() - y) <= 2, ("open", y, at())
    summary = panel.locator("details > summary").first
    click_center(page, summary)
    expect(panel.locator("details").first).to_have_attribute("open", "")
    page.wait_for_timeout(700)
    assert abs(at() - y) <= 2, ("expand", y, at())
    click_center(page, summary)
    page.wait_for_timeout(700)
    assert abs(at() - y) <= 2, ("collapse", y, at())
    page.keyboard.press("Escape")
    expect(panel).to_have_count(0)
    page.wait_for_timeout(500)
    assert abs(at() - y) <= 2, ("close", y, at())
    expect(page.get_by_test_id("go-deeper")).to_be_focused()  # focus returns to the button, without moving the page
