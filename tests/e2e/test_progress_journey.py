"""The learner's progress is read the same way on every page (frontend/src/lib/standing.ts).

A learner found Review still asking again for a question they had corrected, the Progress page counting typed commands
as checks and practice as "0/1" with nowhere to go, and Progress topics opening the knowledge map instead of the
lesson. These tests follow the learner through the real pages: a lesson, a reload, the course outline, Review and
Progress, then a later wrong answer, saved progress from before the change, an export and an import, and the links.
"""
import json

import pytest
from playwright.sync_api import expect
from addresses import lab_url, lesson_url, track_url

LESSON = "lx.first-steps"
T = 1792400000000


@pytest.fixture(params=[(1360, 900), (390, 844)], ids=["desktop", "phone"])
def sized(request, page):
    page.set_viewport_size({"width": request.param[0], "height": request.param[1]})
    return page


def go(page, site, path):
    page.goto(site.rstrip("/") + path)
    page.wait_for_selector("main .page:not(:has(.sk-page))")


def curriculum(page):
    return page.evaluate("fetch('/data/en/curriculum.json').then(r => r.json())")


def answer(q, right: bool):
    """Pick choices until one is right (right=True) or wrong (right=False); leaves that answer submitted."""
    choices = q.get_by_test_id("choice")
    for c in range(choices.count()):
        choices.nth(c).click()
        q.get_by_test_id("check-submit").click()
        if ("is-right" in (q.get_attribute("class") or "")) == right:
            return
        q.get_by_test_id("check-again").click()
    raise AssertionError("no such choice")


def stat(page, label):
    """The number of the Progress page's fact card whose label starts with `label`."""
    card = page.locator(".stat-card", has=page.locator("span", has_text=label)).first
    return card.locator("strong").inner_text(), card.locator("span").first.inner_text()


def seed(page, site, p):
    """Saved progress in this browser, written once (as an earlier visit would have left it)."""
    go(page, site, "/")
    page.evaluate("p => localStorage.setItem('osa.progress.v2', JSON.stringify(p))", p)


def empty(**patch):
    p = {"v": 2, "lessons": {}, "predictions": {}, "guesses": {}, "explains": {}, "labs": {}, "cards": {}, "confidence": {}, "days": [], "cmds": {}, "xp": 0}
    p.update(patch)
    return p


def test_a_corrected_answer_is_read_the_same_on_every_page_and_a_later_wrong_one_too(sized, static_site):
    page = sized
    go(page, static_site, lesson_url(LESSON))
    checks = page.get_by_test_id("check")
    expect(checks).to_have_count(2)
    answer(checks.nth(0), True)
    answer(checks.nth(1), False)
    checks.nth(1).get_by_test_id("check-again").click()
    answer(checks.nth(1), True)  # right, just after the answer was shown
    page.reload()
    expect(page.get_by_test_id("lesson-facts")).to_contain_text("checks 2/2 right (1 after seeing the answer)")
    # the corrected question is no longer outstanding
    go(page, static_site, "/review")
    expect(page.get_by_test_id("revisit")).to_have_count(0)
    go(page, static_site, "/me")
    assert stat(page, "Checks right on your latest answer") == ("2/2", "Checks right on your latest answer (1 after seeing the answer)")
    assert stat(page, "Checks right on the first try")[0] == "1/2"  # the first try stays an honest, separate fact
    expect(page.get_by_test_id("concept-row").locator(".ev-flag")).to_have_count(0)  # nothing "to review"
    go(page, static_site, track_url("linux"))
    expect(page.locator(".lesson-list a", has_text="Your first minutes in a shell").locator(".l-facts")).to_contain_text("checks 2/2")

    # a later attempt that is wrong is what is true now, on every page
    go(page, static_site, lesson_url(LESSON))
    first = page.get_by_test_id("check").nth(0)
    first.get_by_test_id("check-again").click()
    answer(first, False)
    expect(page.get_by_test_id("lesson-facts")).to_contain_text("checks 1/2 right (1 after seeing the answer)")
    go(page, static_site, "/review")
    expect(page.get_by_test_id("revisit")).to_contain_text("Your first minutes in a shell")
    expect(page.get_by_test_id("revisit")).to_contain_text("The latest answer to 1 of your questions was wrong")
    go(page, static_site, "/me")
    assert stat(page, "Checks right on your latest answer")[0] == "1/2"
    expect(page.get_by_test_id("concept-row").locator(".ev-flag").first).to_have_text("to review")
    go(page, static_site, track_url("linux"))
    expect(page.locator(".lesson-list a", has_text="Your first minutes in a shell").locator(".l-facts")).to_contain_text("checks 1/2")


def saved_before(cur):
    """Progress saved before the change: a corrected answer, a typed command (not a check), and practice records."""
    q1, q2 = cur["lessons"][LESSON]["checks"]
    right = {"ok": True, "at": T, "pick": 0}
    full = {"root": True, "evidence": True, "fix": True, "at": T}
    return empty(
        lessons={LESSON: {"seen": T, "done": T}},
        predictions={
            q1: {"first": right, "latest": right, "n": 1},
            q2: {"first": {"ok": False, "at": T, "pick": 2}, "latest": {"ok": True, "at": T + 9000, "pick": 0, "shown": True, "revealedAt": T + 1000}, "n": 2},
            f"try:{LESSON}:try-up": {"first": {"ok": False, "at": T, "pick": -2}, "latest": {"ok": True, "at": T + 5, "pick": 0}, "n": 2},
        },
        labs={
            "lab.container-anatomy": {"started": T, "replayed": T},  # a lab worked through on the recordings
            "lab.rbac": {"started": T, "verified": T, "verdict": "failed", "verdictAt": T + 5},  # verified once, failing now
            "inc.crashloop-config": {"started": T, "revealed": T, "selfCheck": full},  # diagnosed
            "inc.imagepull": {"started": T, "revealed": T, "selfCheck": {**full, "fix": False}},  # debrief not finished
            "ch.helm-release": {"started": T, "revealed": T, "hints": 2},  # solution seen: a challenge is never done so
        },
    )


def read_pages(page, site):
    """What the learner reads about their progress, page by page."""
    out = {}
    go(page, site, "/me")
    for label in ("Checks right on your latest answer", "Checks right on the first try", "Labs completed", "Incidents diagnosed", "Verified on a real cluster"):
        out[label] = stat(page, label)[0]
    go(page, site, "/review")
    out["review"] = page.get_by_test_id("revisit").count()
    for path in ("/labs", "/incidents", "/challenges"):
        go(page, site, path)
        out[path] = page.locator(".score strong").first.inner_text()
    go(page, site, lesson_url(LESSON))
    out["lesson"] = page.get_by_test_id("lesson-facts").inner_text()
    go(page, site, track_url("linux"))
    out["course"] = page.get_by_test_id("course-time").inner_text()
    return out


def test_saved_progress_an_export_and_an_import_give_the_same_results_everywhere(page, static_site, browser, tmp_path):
    go(page, static_site, "/")
    cur = curriculum(page)
    seed(page, static_site, saved_before(cur))
    seen = read_pages(page, static_site)
    linux = [l for t in cur["tracks"] if t["id"] == "linux" for m in t["modules"] for mm in cur["modules"] if mm["id"] == m for l in mm["lessons"]]
    assert f"2 of {sum(len(cur['lessons'][l]['checks']) for l in linux if l in cur['lessons'])} answered correctly (1 after seeing the answer)" in seen["course"]
    course = seen.pop("course")
    labs = sum(1 for l in cur["labs"].values() if l["kind"] == "lab")
    incidents = sum(1 for l in cur["labs"].values() if l["kind"] == "incident")
    challenges = sum(1 for l in cur["labs"].values() if l["kind"] == "challenge")
    assert seen == {
        "Checks right on your latest answer": "2/2",  # the typed command is not a check
        "Checks right on the first try": "1/2",
        "Labs completed": "2",  # replayed, and verified once (its latest live check failing is shown as its status)
        "Incidents diagnosed": "1",  # the unfinished debrief does not count
        "Verified on a real cluster": "0",  # by the latest verdict
        "review": 0,
        "/labs": f"2/{labs}",
        "/incidents": f"1/{incidents}",
        "/challenges": f"0/{challenges}",
        "lesson": "Finished reading · checks 2/2 right (1 after seeing the answer)",
    }, seen
    # export, then import into another browser: the same facts, the same reading
    go(page, static_site, "/me")
    with page.expect_download() as dl:
        page.get_by_role("button", name="Export").click()
    path = tmp_path / "progress.json"
    dl.value.save_as(path)
    other = browser.new_context(viewport={"width": 390, "height": 844}).new_page()
    go(other, static_site, "/me")
    other.locator("input[type=file]").set_input_files(str(path))
    expect(other.locator(".me-data [role=status]")).to_contain_text("Imported")
    assert read_pages(other, static_site) == {**seen, "course": course}
    # importing an older copy again changes nothing: facts are merged, never replaced by older ones
    other.goto(static_site.rstrip("/") + "/me")
    other.locator("input[type=file]").set_input_files(str(path))
    expect(other.locator(".me-data [role=status]")).to_contain_text("Imported")
    assert read_pages(other, static_site) == {**seen, "course": course}
    other.context.close()


def test_progress_links_go_to_the_lesson_and_to_each_activity(sized, static_site):
    page = sized
    go(page, static_site, "/")
    cur = curriculum(page)
    seed(page, static_site, saved_before(cur))
    go(page, static_site, "/me")
    assert page.locator(".pg-me a[href^='/map']").count() == 0  # topics lead to learning material, not the map
    row = page.locator("[data-testid=concept-row][data-concept='linux.process']")
    taught = [l for l in cur["lessons"].values() if "linux.process" in l["concepts"]]
    expect(row.locator("th a")).to_have_attribute("href", lesson_url(next(l["id"] for l in taught if l["module"].startswith("lx"))))
    # the practice behind "0/1": listed with its status, its course, what completes it, and a working link
    btn = row.get_by_test_id("concept-where-btn")
    expect(btn).to_have_attribute("aria-expanded", "false")
    btn.click()
    expect(btn).to_have_attribute("aria-expanded", "true")
    where = page.get_by_test_id("concept-where")
    act = where.get_by_test_id("concept-activity").filter(has_text=cur["labs"]["lab.container-anatomy"]["title"])
    expect(act).to_contain_text("Practised (recorded)")
    expect(act).to_contain_text("Lab · ")
    expect(act).to_contain_text("To complete: work through every step on the recordings")
    hrefs = where.locator("a").evaluate_all("els => els.map(e => e.getAttribute('href'))")
    known = {lesson_url(l) for l in cur["lessons"]} | {lab_url(l) for l in cur["labs"]}
    assert hrefs and all(h in known for h in hrefs), hrefs
    act.get_by_role("link").click()
    expect(page.locator("h1").first).to_have_text(cur["labs"]["lab.container-anatomy"]["title"])
    page.go_back()
    expect(page.get_by_test_id("concept-row").first).to_be_visible()
    # the concept name itself opens the lesson
    page.locator("[data-testid=concept-row][data-concept='linux.process'] th a").click()
    expect(page.get_by_test_id("lesson-facts")).to_be_visible()


def test_an_incident_and_a_challenge_say_how_they_are_completed(page, static_site):
    go(page, static_site, "/")
    cur = curriculum(page)
    seed(page, static_site, saved_before(cur))
    go(page, static_site, "/me")
    more = page.locator(".me-more")
    if more.count():
        more.click()  # every concept with work on record, not only the first rows
    for concept, lab, says in (
        (next(c for c in cur["concepts"] if c in cur["labs"]["inc.imagepull"]["concepts"]), "inc.imagepull", "To complete: finish the debrief self-check"),
        (next(c for c in cur["concepts"] if c in cur["labs"]["ch.helm-release"]["concepts"]), "ch.helm-release", "To complete: verify your solution on a real cluster"),
    ):
        row = page.locator(f"[data-testid=concept-row][data-concept='{concept}']")
        row.get_by_test_id("concept-where-btn").click()
        act = page.get_by_test_id("concept-where").get_by_test_id("concept-activity").filter(has_text=cur["labs"][lab]["title"])
        expect(act).to_contain_text(says)
        expect(act.locator(".pill.ok")).to_have_count(0)  # revealed or half-debriefed: not completed
        row.get_by_test_id("concept-where-btn").click()


def test_recall_cards_are_told_apart_from_checks_and_counted_alike(sized, static_site):
    """Review's cards are not the lesson checks: answering checks does not review a card. A finished lesson's cards
    are ready at once as new ones; graded cards come back when due. Review, its tab and Progress give the same counts."""
    page = sized
    go(page, static_site, "/")
    cur = curriculum(page)
    cards = [c["id"] for c in page.evaluate("fetch('/data/en/cards.json').then(r => r.json())") if c["source"] == "lesson" and c["ref"] == LESSON]
    assert len(cards) >= 3
    now = page.evaluate("Date.now()")
    p = saved_before(cur)  # the lesson finished, its checks answered right (one after seeing the answer)
    p["labs"] = {}  # a lab worked on adds its own cards: here only the lesson's
    p["cards"] = {cards[0]: {"ef": 2.5, "interval": 1, "due": now - 60000, "reps": 1, "lapses": 0, "reviewedAt": now - 86400000},
                  cards[1]: {"ef": 2.5, "interval": 3, "due": now + 3 * 86400000, "reps": 2, "lapses": 0, "reviewedAt": now}}
    seed(page, static_site, p)
    fresh, again = len(cards) - 2, 1
    go(page, static_site, "/review")
    expect(page.get_by_test_id("rev-new").locator("strong")).to_have_text(str(fresh))
    expect(page.get_by_test_id("rev-again").locator("strong")).to_have_text(str(again))
    expect(page.get_by_test_id("rev-what")).to_contain_text("separate from the lesson checks")
    expect(page.get_by_test_id("revisit")).to_have_count(0)  # no check question is outstanding
    expect(page.locator(".rev-progress")).to_contain_text(f"{fresh + again} left")
    go(page, static_site, "/me")
    expect(page.locator(".pg-now-link")).to_have_text(f"Review: {fresh + again} recall cards ready ({fresh} new)")
    # grading one card on Review lowers every count by one
    go(page, static_site, "/review")
    page.get_by_test_id("flip").click()
    page.get_by_test_id("grade-good").click()
    expect(page.locator(".rev-progress")).to_contain_text(f"{fresh + again - 1} left")
    go(page, static_site, "/me")
    expect(page.locator(".pg-now-link")).to_contain_text(f"Review: {fresh + again - 1} recall cards ready")
