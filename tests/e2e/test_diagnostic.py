"""Track diagnostics: answer with a confidence, get a plan; nothing is marked as done; results survive a reload."""
from playwright.sync_api import expect
from addresses import diag_url, track_url


def open_(page, site, route="/"):
    page.goto(site.rstrip("/") + route)
    page.wait_for_selector("main .page:not(:has(.sk-page))")


def still(page, frames=10):
    """Wait until the page has not scrolled for `frames` animation frames (at most 5 s): each new question is scrolled
    into view just after it appears, and under load a click during that scroll could hit another button."""
    page.evaluate("""(n) => new Promise(done => {
        let last = scrollY, same = 0, start = performance.now()
        const tick = () => {
            if (scrollY === last) same++; else { same = 0; last = scrollY }
            if (same >= n || performance.now() - start > 5000) done(); else requestAnimationFrame(tick)
        }
        requestAnimationFrame(tick)
    })""", frames)


def answer(page, choice: int | None, conf: int = 1):
    still(page)
    if choice is None:
        page.get_by_test_id("diag-idk").click()
        expect(page.get_by_test_id("diag-idk")).to_have_attribute("aria-checked", "true")
    else:
        page.get_by_test_id("diag-choice").nth(choice).click()
        expect(page.get_by_test_id("diag-choice").nth(choice)).to_have_attribute("aria-checked", "true")
        expect(page.get_by_test_id("diag-next")).to_be_disabled()  # a confidence level is required
        page.get_by_test_id(f"diag-conf-{conf}").click()
    page.get_by_test_id("diag-next").click()


def test_every_available_path_offers_its_diagnostic(page, static_site):
    # every territory, including the enterprise one that is still in preparation, has its own diagnostic
    for track in ("linux", "containers", "start", "admin1", "admin2", "platform", "practice"):
        open_(page, static_site, f"/learn/{track}")
        expect(page.get_by_test_id("diag-card")).to_be_visible()


def test_diagnostic_plan_reflects_answers_and_marks_nothing_done(page, static_site):
    open_(page, static_site, diag_url("admin1"))
    page.get_by_test_id("diag-start").click()
    expect(page.get_by_test_id("diag-question")).to_contain_text("Question 1 of")
    answer(page, None)  # "I don't know yet"
    answer(page, 0, conf=2)
    answer(page, 1, conf=0)
    expect(page.get_by_test_id("diag-question")).to_contain_text("Question 4 of")
    page.reload()
    page.wait_for_selector("[data-testid=diag-question]")
    expect(page.get_by_test_id("diag-question")).to_contain_text("Question 4 of"), "a reload resumes where the learner was"
    page.get_by_test_id("diag-stop").click()
    res = page.get_by_test_id("diag-results")
    expect(res).to_contain_text("of 3 answered correctly")
    expect(page.get_by_test_id("diag-study")).to_be_visible()  # the "I don't know" item at least
    # nothing is marked done: the path still shows 0 lessons finished, and the lessons carry diagnostic tags
    open_(page, static_site, track_url("admin1"))
    expect(page.get_by_test_id("diag-card")).to_contain_text("Diagnostic taken")
    expect(page.locator(".lesson-list .pill.diag-v").first).to_be_visible()
    expect(page.get_by_test_id("path-progress")).to_contain_text("0/")
    assert page.locator(".lesson-list a.done").count() == 0


def test_retake_clears_previous_answers(page, static_site):
    open_(page, static_site, diag_url("start"))
    page.get_by_test_id("diag-start").click()
    answer(page, 0)
    page.get_by_test_id("diag-stop").click()
    page.get_by_test_id("diag-retake").click()
    expect(page.get_by_test_id("diag-question")).to_contain_text("Question 1 of")
    assert page.get_by_test_id("diag-stop").count() == 0, "a retake starts with no answers"


def test_diagnostic_is_usable_on_a_phone(browser, static_site):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    open_(page, static_site, diag_url("admin2"))
    page.get_by_test_id("diag-start").click()
    page.wait_for_selector("[data-testid=diag-question]")
    assert page.evaluate("document.documentElement.scrollWidth") <= 390, "no horizontal page scroll"
    box = page.get_by_test_id("diag-next").bounding_box()
    assert box and box["height"] >= 40, "touch target"
    ctx.close()


def test_keyboard_only_answering_and_focus(page, static_site):
    """U6-05: arrow keys move and select within each radio group; focus lands on the question, then the results."""
    open_(page, static_site, diag_url("admin1"))
    page.get_by_test_id("diag-start").click()
    page.wait_for_selector("[data-testid=diag-question]")
    assert page.evaluate("document.activeElement.closest('[data-testid=diag-question]') !== null")
    first = page.get_by_test_id("diag-choice").first
    first.focus()
    page.keyboard.press("ArrowDown")
    expect(page.get_by_test_id("diag-choice").nth(1)).to_have_attribute("aria-checked", "true")
    page.get_by_test_id("diag-conf-0").focus()
    page.keyboard.press("ArrowRight")
    expect(page.get_by_test_id("diag-conf-1")).to_have_attribute("aria-checked", "true")
    page.get_by_test_id("diag-next").press("Enter")
    page.get_by_test_id("diag-stop").press("Enter")
    expect(page.get_by_test_id("diag-results")).to_be_visible()
    assert page.evaluate("document.activeElement.tagName") == "H2"


def test_path_offers_the_same_first_step_as_the_results(page, static_site):
    """U6-07: the path's 'Start your plan' goes where the results page's first recommendation goes."""
    open_(page, static_site, diag_url("admin1"))
    page.get_by_test_id("diag-start").click()
    for conf in (0, 0, 2):  # two guesses wrong, then a confident mistake
        answer(page, 0, conf)
    page.get_by_test_id("diag-stop").click()
    first = page.get_by_test_id("diag-study").locator("a").first.get_attribute("href")
    open_(page, static_site, track_url("admin1"))
    plan = page.get_by_test_id("path-plan")
    if first:
        assert plan.get_attribute("href") == first
