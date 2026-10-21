"""v3 learning experience: routes on the home page, welcome back after a break, and recall of
earlier material at the end of a lesson. Static site, no cluster."""
import datetime
import json
import re

from playwright.sync_api import expect
from addresses import diag_url, lesson_url


def open_(page, site, route="/"):
    page.goto(site.rstrip("/") + route)
    page.wait_for_selector("main .page:not(:has(.sk-page))")


def seed(page, progress: dict):
    """Start the page with this progress already in the browser (the store normalises anything it does not know)."""
    page.add_init_script(f"localStorage.setItem('osa.progress.v2', {json.dumps(json.dumps(progress))})")


def test_route_is_chosen_with_the_keyboard_and_remembered(page, static_site):
    open_(page, static_site)
    first = page.get_by_test_id("route-beginner")
    first.focus()
    page.keyboard.press("Space")
    expect(first).to_have_attribute("aria-checked", "true")
    page.keyboard.press("ArrowRight")
    second = page.get_by_test_id("route-knows-containers")
    expect(second).to_have_attribute("aria-checked", "true")
    expect(second).to_be_focused()
    begin = page.get_by_test_id("start-learning")
    expect(begin).to_have_attribute("href", diag_url("start"))
    expect(page.get_by_test_id("route-detail")).to_contain_text("Cluster optional")
    page.reload()
    page.wait_for_selector("main .page:not(:has(.sk-page))")
    expect(page.get_by_test_id("route-knows-containers")).to_have_attribute("aria-checked", "true")
    assert page.locator(".btn.primary:visible").count() == 1
    assert page.errors == []


def test_welcome_back_after_a_long_break_starts_with_recall(page, static_site):
    long_ago = (datetime.date.today() - datetime.timedelta(days=40)).isoformat()
    now_ms = int(datetime.datetime.now().timestamp() * 1000)
    seed(page, {"v": 2, "lessons": {"lx.shell-basics": {"seen": now_ms - 40 * 86400000, "done": now_ms - 40 * 86400000}},
                "predictions": {}, "guesses": {}, "explains": {}, "labs": {}, "cards": {}, "confidence": {},
                "diagnostics": {}, "days": [long_ago], "cmds": {}, "xp": 0, "route": "beginner"})
    open_(page, static_site)
    welcome = page.get_by_test_id("welcome")
    expect(welcome).to_contain_text("Welcome back after 6 weeks")
    expect(welcome).to_contain_text("recalling beats rereading")
    # the session puts recall first (cards from the lesson already read are due), then the next lesson on the route
    review = page.get_by_test_id("today-review")
    expect(review).to_be_visible()
    # the first unfinished lesson on the beginner route (the ten-minute first lesson was not read)
    expect(page.get_by_test_id("today-lesson")).to_have_attribute("href", lesson_url("lx.first-steps"))
    # after a long break with cards due, the primary action is recall, not rereading
    assert page.locator("[data-testid=welcome] a.btn").first.get_attribute("data-testid") == "recall-first"
    expect(page.get_by_test_id("today-practice")).to_have_count(0)  # one lesson read: nothing to prove yet on this route
    assert page.errors == []


def test_lesson_end_mixes_in_recall_of_an_earlier_lesson(page, static_site):
    now_ms = int(datetime.datetime.now().timestamp() * 1000)
    seed(page, {"v": 2, "lessons": {"lx.shell-basics": {"seen": now_ms - 5 * 86400000, "done": now_ms - 5 * 86400000}},
                "predictions": {}, "guesses": {}, "explains": {}, "labs": {}, "cards": {}, "confidence": {},
                "diagnostics": {}, "days": [], "cmds": {}, "xp": 0})
    open_(page, static_site, lesson_url("lx.files-text") + "?step=99")
    recall = page.get_by_test_id("recall-break")
    expect(recall).to_be_visible()
    items = recall.locator(".recall-list li")
    assert 1 <= items.count() <= 3
    expect(recall).to_contain_text("How a command is built")  # cards come from the earlier lesson, not this one
    items.first.get_by_role("button", name="Show the answer").click()
    items.first.get_by_role("button", name="I knew it").click()
    expect(items.first).to_contain_text("Scheduled for review in")
    stored = page.evaluate("JSON.parse(localStorage.getItem('osa.progress.v2')).cards")
    assert len(stored) == 1 and next(iter(stored.values()))["reps"] == 1
