"""Complete learning journeys, end to end in the static site, the way a person would take them.

J1  A returning engineer: path → diagnostic (answers everything, one confident mistake) → plan → the suggested lesson
    → "answer its questions first" → skip the reading → the path shows the lesson as skipped, nothing else as done.
J2  A beginner: home → start learning → the first lesson, activity by activity, to its end → the path counts it.
J3  Practice: the triage diagnostic → an incident page, with its stage and hints.
"""
import json
import re

from playwright.sync_api import expect
from addresses import diag_url, is_practice, lesson_at, lesson_url, track_url


def norm(md: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[`*]", "", md)).strip()


def open_(page, site, route="/"):
    page.goto(site.rstrip("/") + route)
    page.wait_for_selector("main .page:not(:has(.sk-page))")


def data(page, site, path):
    return json.loads(page.request.get(site.rstrip("/") + "/data/en/" + path).text())


def still(page, frames=10):
    """Wait until the page has not scrolled for `frames` animation frames (at most 5 s)."""
    page.evaluate("""(n) => new Promise(done => {
        let last = scrollY, same = 0, start = performance.now()
        const tick = () => {
            if (scrollY === last) same++; else { same = 0; last = scrollY }
            if (same >= n || performance.now() - start > 5000) done(); else requestAnimationFrame(tick)
        }
        requestAnimationFrame(tick)
    })""", frames)


def test_returning_engineer_finds_gaps_and_tests_out(page, static_site):
    # Each new question is scrolled into view two frames after it appears; under load a click could land while the
    # page was still moving and hit another button. Reduced motion makes that scroll a jump, and `still` waits for it.
    page.emulate_media(reduced_motion="reduce")
    diag = data(page, static_site, "diagnostics/admin1.json")
    by_prompt = {norm(it["prompt"]): it for it in diag["items"]}
    open_(page, static_site, track_url("admin1"))
    page.get_by_test_id("diag-card-link").click()
    page.get_by_test_id("diag-start").click()
    mistake_target = None
    for n in range(len(diag["items"])):
        # The next question is ready only once its counter shows and no answer is selected yet: the app clears the
        # previous answer just after rendering the new question, and a click before that is lost (seen under load).
        expect(page.locator("#diag-q-n")).to_have_text(f"Question {n + 1} of {len(diag['items'])}")
        expect(page.locator("[data-testid=diag-choice][aria-checked=true]")).to_have_count(0)
        still(page)
        q = page.get_by_test_id("diag-question")
        prompt = norm(q.locator(".check-prompt").inner_text())
        it = next((v for k, v in by_prompt.items() if k == prompt or prompt.startswith(k[:80])), None)
        assert it, f"question not found in the data: {prompt[:80]}"
        pick = it["answer"]
        if mistake_target is None and it["targets"][0] == "o1.config-secrets":
            pick, mistake_target = (it["answer"] + 1) % len(it["choices"]), it["targets"][0]
        page.get_by_test_id("diag-choice").nth(pick).click()
        expect(page.get_by_test_id("diag-choice").nth(pick)).to_have_attribute("aria-checked", "true")
        page.get_by_test_id("diag-conf-2").click()  # certain, every time
        page.get_by_test_id("diag-next").click()
    assert mistake_target == "o1.config-secrets"
    expect(page.get_by_test_id("diag-results")).to_contain_text(f"{len(diag['items']) - 1} of {len(diag['items'])} answered correctly")
    study = page.get_by_test_id("diag-study")
    expect(study.locator("li")).to_have_count(1)
    expect(study).to_contain_text("certain, but wrong")
    page.get_by_test_id("diag-first").click()
    page.wait_for_url(re.compile(re.escape(lesson_url("o1.config-secrets"))))
    expect(page.get_by_test_id("diag-note")).to_contain_text("study")  # the lesson knows what the diagnostic said

    # The lesson: answer all its questions first, every one right, then skip the reading.
    lesson = data(page, static_site, "lessons/o1.config-secrets.json")
    checks = {norm(p["prompt"]): p for p in lesson["predict"] if p.get("role", "check") == "check"}
    page.get_by_test_id("test-out").click()
    page.wait_for_selector(".testout-view")
    for i in range(page.locator(".testout-view [data-testid=check]").count()):
        q = page.locator(".testout-view [data-testid=check]").nth(i)
        prompt = norm(q.locator(".check-prompt").inner_text())
        p = next((v for k, v in checks.items() if k == prompt or prompt.startswith(k[:80])), None)
        assert p, f"check not found: {prompt[:80]}"
        q.locator(f"[data-choice=\"{p['answer']}\"]").click()
        q.get_by_test_id("check-submit").click()
    page.get_by_test_id("skip-reading").click()

    open_(page, static_site, track_url("admin1"))
    page.locator(".chapter-h", has_text="Configuration and storage").click()
    row = page.locator(f".lesson-list a[href='{lesson_url('o1.config-secrets')}']")
    expect(row).to_have_class(re.compile(r"\bdone\b"))
    expect(row).to_contain_text("study")  # the diagnostic's verdict stays visible: it is not erased by skipping
    assert page.locator(".lesson-list a.done").count() == 1, "only the lesson really tested out counts as done"
    expect(page.get_by_test_id("path-progress")).to_contain_text("1/")


def test_beginner_reads_the_first_lesson_to_its_end(page, static_site):
    open_(page, static_site, "/")
    page.get_by_role("link", name=re.compile("Start learning|Begin|Start here", re.I)).first.click()
    page.wait_for_selector("main .page:not(:has(.sk-page))")
    if not lesson_at(page.url):
        page.get_by_test_id("path-next").click()
    page.wait_for_url(lambda u: lesson_at(u) is not None)
    lesson_id = lesson_at(page.url)
    for _ in range(80):
        if page.get_by_test_id("flow-step").count():  # a lesson written as a teaching flow: one growing column
            if page.get_by_test_id("lesson-done").count():
                page.get_by_test_id("lesson-done").click()
                break
            if page.get_by_test_id("flow-continue").count():
                page.get_by_test_id("flow-continue").click()
            elif page.get_by_test_id("flow-skip").count():
                page.get_by_test_id("flow-skip").click()  # a beginner may skip a question and still finish
            else:
                break
            continue
        act = page.get_by_test_id("activity")
        if act.get_attribute("data-kind") == "check" and act.get_by_test_id("check-submit").count():
            act.get_by_test_id("choice").first.click()  # a beginner may get it wrong: still allowed to continue
            act.get_by_test_id("check-submit").click()
        if page.get_by_test_id("lesson-done").count():
            page.get_by_test_id("lesson-done").click()
            break
        if not page.get_by_test_id("lesson-next").count():
            break
        page.get_by_test_id("lesson-next").click()
    from academy import curriculum

    d = curriculum.load("en")
    tid = next(t.id for t in d["tracks"].values() if any(lesson_id in d["modules"][m].lessons for m in t.modules))
    open_(page, static_site, track_url(tid))  # the territory the first lesson belongs to
    expect(page.locator(f".lesson-list a[href='{lesson_url(lesson_id)}']")).to_have_class(re.compile(r"\bdone\b"))


def test_practice_triage_leads_to_an_incident(page, static_site):
    open_(page, static_site, diag_url("practice"))
    page.get_by_test_id("diag-start").click()
    page.get_by_test_id("diag-idk").click()
    page.get_by_test_id("diag-next").click()
    page.get_by_test_id("diag-stop").click()
    link = page.get_by_test_id("diag-study").locator("a").first
    href = link.get_attribute("href")
    assert href and is_practice(href), href
    link.click()
    page.wait_for_selector("main .page:not(:has(.sk-page))")
    expect(page.locator("h1")).to_be_visible()
    assert "Page not found" not in page.locator("main").inner_text()
