"""The learning model's contracts: what the learner is doing is always explicit,
checks follow what they test, reading is not mastery, places survive detours and reloads, and a failed command never
completes a lab step."""
import json
import re

from playwright.sync_api import expect
from addresses import lab_url, lesson_url


def open_(page, site, route="/"):
    page.goto(site.rstrip("/") + route)
    page.wait_for_selector("main .page:not(:has(.sk-page))")


def answer_all_right(page, site, lesson_id):
    """Answer every check on the page correctly, whatever order the choices are shown in."""
    lesson = json.loads(page.request.get(site.rstrip("/") + f"/data/en/lessons/{lesson_id}.json").text())
    norm = lambda t: re.sub(r"\s+", " ", re.sub(r"[`*]", "", t)).strip()  # noqa: E731
    keys = {norm(p["prompt"]): p["answer"] for p in lesson["predict"]}
    checks = page.locator("[data-testid=check]")
    expect(checks.first).to_be_visible()  # the questions are on the page before they are counted (a busy runner)
    for q in checks.all():
        shown = norm(q.locator(".check-prompt").inner_text())
        answer = next(v for k, v in keys.items() if k == shown or shown.startswith(k[:80]))
        q.locator(f'[data-choice="{answer}"]').click()
        q.get_by_test_id("check-submit").click()
        expect(q.get_by_test_id("verdict")).to_be_visible()  # answered, before the next one


def test_reading_and_checking_look_different_and_nothing_is_graded_before_an_answer(page, static_site):
    open_(page, static_site, lesson_url("d.routes-tls"))
    page.wait_for_selector("[data-testid=flow-step]")
    learn = page.locator("[data-testid=flow-step][data-kind=learn]").first
    assert learn.locator("[data-testid=check-submit], [data-testid=choice]").count() == 0, "reading has no answer controls"
    check = page.locator("[data-testid=flow-step][data-kind=check]").first
    expect(check.get_by_test_id("check-submit")).to_be_disabled()  # nothing is graded until the learner submits
    assert check.locator(".verdict").count() == 0, "no feedback before an answer"


def test_checks_come_after_teaching(page, static_site):
    """A graded question never opens a lesson section: something that teaches comes before it in the article."""
    open_(page, static_site, lesson_url("d.routes-tls"))
    page.wait_for_selector("[data-testid=flow-step]")
    kinds = page.locator("[data-testid=flow-step]").evaluate_all("els => els.map(e => e.dataset.kind)")
    for i, k in enumerate(kinds):
        if k == "check":
            before = [x for x in kinds[:i] if x not in ("check", "predict")]
            assert before and before[-1] in ("learn", "show", "try", "explore"), kinds


def test_wrong_answer_feedback_is_beside_the_choice_and_visible(page, static_site):
    page.set_viewport_size({"width": 1440, "height": 900})
    open_(page, static_site, lesson_url("d.routes-tls"))
    page.wait_for_selector("[data-testid=flow-step]")
    page.locator("[data-testid=flow-step][data-kind=check]").first.scroll_into_view_if_needed()
    q = page.get_by_test_id("check").first
    wrong = q.locator(".check-choice").evaluate_all("els => els.map(e => +e.dataset.choice)")
    key = page.evaluate("fetch('/data/en/lessons/d.routes-tls.json').then(r => r.json())")
    first_check = next(p for p in key["predict"] if p.get("role", "check") == "check")
    q.locator(f'[data-choice="{next(c for c in wrong if c != first_check["answer"])}"]').click()  # authored choice A, a wrong answer (choices are shown shuffled)
    q.get_by_test_id("check-submit").click()
    v = q.locator(".verdict.bad")
    expect(v).to_contain_text("Not quite")
    box = v.bounding_box()
    assert box and box["y"] + 40 < 900, "the verdict must be visible without scrolling"
    letter = q.locator(".check-choice.answer .choice-k").inner_text().strip()
    expect(q.locator(".check-answer")).to_contain_text(f"The answer is {letter}")
    expect(q.get_by_role("button", name="Try again")).to_be_visible()


def test_knowing_it_already_skips_reading_but_is_not_called_mastery(page, static_site):
    open_(page, static_site, lesson_url("d.routes-tls"))
    page.get_by_test_id("test-out").click()
    page.wait_for_selector(".testout-view [data-testid=check]")
    answer_all_right(page, static_site, "d.routes-tls")
    page.get_by_test_id("skip-reading").click()
    expect(page).to_have_url(re.compile(r"a=summary"))
    expect(page.get_by_test_id("lesson-facts")).to_contain_text("Reading skipped after the checks")
    expect(page.locator(".summary-facts")).to_contain_text("skipped the reading")


def test_finishing_without_answering_records_reading_only(page, static_site):
    open_(page, static_site, lesson_url("d.services-dns") + "?step=99")
    page.get_by_test_id("lesson-done").click()
    facts = page.get_by_test_id("lesson-facts")
    expect(facts).to_contain_text("Finished reading")
    expect(facts).to_contain_text("checks")
    prog = page.evaluate("JSON.parse(localStorage.getItem('osa.progress.v2'))")
    assert prog["lessons"]["d.services-dns"]["done"] and not prog["predictions"], "reading must not create answers"


def test_continue_opens_the_lesson_at_its_beginning(page, static_site):
    open_(page, static_site, lesson_url("d.services-dns"))
    page.wait_for_selector("[data-testid=flow-step]")
    open_(page, static_site, "/")
    page.get_by_role("link", name=re.compile("Pick up|Continue", re.I)).first.click()
    page.wait_for_url(re.compile(re.escape(lesson_url("d.services-dns")) + "$"))
    page.wait_for_selector("[data-testid=flow-step]")
    assert page.evaluate("scrollY") == 0


def test_lab_detour_returns_to_the_lesson(page, static_site):
    open_(page, static_site, lesson_url("d.services-dns") + "?a=practise")
    page.locator(".practice-lab").first.click()
    back = page.get_by_test_id("lab-back")
    expect(back).to_contain_text("Services, EndpointSlices and DNS")
    back.click()
    expect(page).to_have_url(re.compile(re.escape(lesson_url("d.services-dns") + "?a=practise")))


def test_lab_and_incident_places_are_in_the_url_and_survive_reload(page, static_site):
    open_(page, static_site, lab_url("lab.rbac") + "?step=finish")
    expect(page.locator(".finish")).to_be_visible()
    open_(page, static_site, lab_url("inc.service-selector-503"))
    page.get_by_test_id("start-investigating").click()
    expect(page).to_have_url(re.compile(r"stage=investigate"))
    assert page.locator(".notice").count() == 0, "findings must not be shown before the command is run"
    page.locator(".lesson-step [data-testid=replay]").first.click()
    expect(page.locator(".notice").first).to_be_visible(timeout=8000)
    page.get_by_role("button", name="I have a theory").click()
    page.locator("textarea.diag").fill("work in progress: the selector looks wrong")
    page.wait_for_timeout(900)  # the draft is saved as the learner types
    page.goto(static_site.rstrip("/") + lab_url("inc.service-selector-503"))
    page.wait_for_selector("textarea.diag")
    expect(page.locator("textarea.diag")).to_have_value("work in progress: the selector looks wrong")


def test_hints_are_spaced(page, static_site):
    open_(page, static_site, lab_url("inc.service-selector-503") + "?stage=investigate")
    page.get_by_test_id("hint").click()
    expect(page.locator(".hint")).to_have_count(1)
    expect(page.get_by_test_id("hint")).to_be_disabled()
    expect(page.get_by_test_id("hint")).to_contain_text("Next hint in")


def test_graph_keys_never_move_the_lesson(page, static_site):
    open_(page, static_site, lesson_url("d.services-dns") + "?a=explore:request-path")
    url = page.url
    page.locator(".fd-viewport").first.focus()
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowLeft")
    assert page.url == url


def test_v1_progress_migrates_without_inventing_evidence(page, static_site):
    v1 = {"v": 1, "lessons": {"d.routes-tls": {"seen": 1, "done": 2}}, "predictions": {"lesson:d.routes-tls:0": {"ok": True, "at": 3}},
          "explains": {}, "labs": {"lab.rbac": {"steps": {"s1": 4}}}, "cards": {}, "confidence": {}, "days": [], "cmds": {}, "xp": 40}
    page.goto(static_site)
    page.evaluate("v => localStorage.setItem('osa.progress.v1', JSON.stringify(v))", v1)
    open_(page, static_site, lesson_url("d.routes-tls"))
    expect(page.get_by_test_id("lesson-facts")).to_contain_text("Finished reading")
    # the lesson was rewritten since v1: its old positional answer belongs to a question that no longer exists, so it is
    # kept aside, never credited to one of the new questions
    expect(page.get_by_test_id("lesson-facts")).not_to_contain_text(re.compile(r"checks \d+/\d+ right"))
    prog = page.evaluate("JSON.parse(localStorage.getItem('osa.progress.v2'))")
    assert prog["v"] == 2 and prog["predictions"] == {}
    assert prog["legacy"]["predictions"] == {"lesson:d.routes-tls:0": {"ok": True, "at": 3}}
    assert prog["labs"]["lab.rbac"]["stepResults"]["s1"] == {"at": 4, "source": "legacy", "matched": False}
    assert page.evaluate("localStorage.getItem('osa.progress.v1')") is not None, "v1 data is kept, not overwritten"


def test_a_failed_live_command_never_completes_the_step(page, practice_server):
    """Fake a connected training cluster in the browser; the exec endpoint answers with an unexpected failure."""
    def fulfil(route, body):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    page.route("**/api/meta", lambda r: fulfil(r, {"mode": "cluster", "langs": ["en"], "default_lang": "en"}))
    page.route("**/api/status*", lambda r: fulfil(r, {"mode": "cluster", "oc": True, "crc": {"installed": True},
                                                      "identities": {"learner": {"connected": True, "user": "developer"}, "reader": {"connected": False}, "admin": {"connected": False}}}))
    page.route("**/api/labs/lab.rbac/state", lambda r: fulfil(r, {"project": {"exists": True, "owned": True}, "items": [], "events": []}))
    page.route("**/api/labs/lab.rbac/preflight", lambda r: fulfil(r, {"class": "training", "runnable": True, "requirements": [], "blockers": [], "notes": []}))
    page.route("**/api/labs/lab.rbac/exec", lambda r: fulfil(r, {"code": 1, "stdout": "", "stderr": "Error from server (Forbidden): something unexpected", "run": "oc ..."}))
    page.route("**/api/environment*", lambda r: fulfil(r, {"env": {"class": "training", "reason": ""}, "identities": {}}))
    open_(page, practice_server, lab_url("lab.rbac"))
    step = page.locator(".lab-step")
    if step.get_by_test_id("skip-guess").count():
        step.get_by_test_id("skip-guess").click()
    page.wait_for_selector(".lab-step .cmdblock")
    for b in step.locator(".cmdblock button:has-text('Run')").all():
        b.click()
        if page.get_by_role("button", name=re.compile("Run it|Confirm", re.I)).count():
            page.get_by_role("button", name=re.compile("Run it|Confirm", re.I)).first.click()
    page.wait_for_timeout(800)
    prog = page.evaluate("JSON.parse(localStorage.getItem('osa.progress.v2') || '{}')")
    res = (prog.get("labs", {}).get("lab.rbac", {}) or {}).get("stepResults", {})
    assert res and all(not r["matched"] for r in res.values()), res
    assert not prog["labs"]["lab.rbac"].get("replayed"), "a failed live run must never count as practised"


def test_finishing_a_lab_step_does_not_jump_away_from_its_output(page, static_site):
    """Regression: completing a step used to move the learner to the next step and hide the output just replayed."""
    open_(page, static_site, lab_url("lab.deployment-reconciliation"))
    step = page.locator(".lab-step")
    title = step.locator("h2").inner_text()
    step.get_by_test_id("skip-guess").click()
    for b in step.locator("[data-testid=replay]").all():
        b.click()
    page.wait_for_timeout(1500)
    assert page.locator(".lab-step h2").inner_text() == title
    expect(page.locator(".lab-step .screen").first).to_be_visible()


def test_search_finds_models_diagrams_and_lab_steps_first(page, static_site):
    """Advanced learners search by topic; whole-phrase title matches rank above commands that merely contain the words."""
    open_(page, static_site, "/")
    page.keyboard.press("Control+k")
    page.get_by_test_id("palette-input").fill("request path")
    first = page.locator(".palette-list li").first
    expect(first).to_contain_text(re.compile("Model|Diagram"))
    page.get_by_test_id("palette-input").fill("scale the deployment")
    expect(page.locator(".palette-list")).to_contain_text("Lab step")
    rows = page.locator(".palette-list li").all_inner_texts()
    assert not any("`" in r or "**" in r for r in rows), "descriptions must not show raw Markdown"


def test_a_wrong_answer_comes_back_in_review(page, static_site):
    """Returning learners: questions answered wrongly are offered again, linked to the exact Check."""
    open_(page, static_site, lesson_url("d.routes-tls"))
    page.wait_for_selector("[data-testid=flow-step]")
    step = page.locator("[data-testid=flow-step][data-kind=check]").first
    sid = step.get_attribute("data-step")
    q = step.get_by_test_id("check")
    key = page.evaluate("fetch('/data/en/lessons/d.routes-tls.json').then(r => r.json())")
    answer = next(p for p in key["predict"] if p.get("role", "check") == "check")["answer"]
    q.locator(f'[data-choice="{(answer + 1) % 3}"]').click()  # wrong
    q.get_by_test_id("check-submit").click()
    open_(page, static_site, "/review")
    rev = page.get_by_test_id("revisit")
    expect(rev).to_contain_text("Routes")
    rev.get_by_role("link").first.click()
    page.wait_for_selector("[data-testid=flow-step]")
    page.wait_for_timeout(400)
    expect(page.locator(f"[data-step='{sid}']")).to_be_in_viewport()
