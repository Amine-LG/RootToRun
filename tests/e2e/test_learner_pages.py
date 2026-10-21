"""Progress, Review and Diagnostics read as parts of one product: they lead with what to do next, keep each kind of
evidence apart, fit phones and tablets, show a visible keyboard focus and stop their motion for people who ask."""
import re

import pytest
from playwright.sync_api import expect
from addresses import diag_url, lesson_url


def open_(page, site, route="/"):
    page.goto(site.rstrip("/") + route)
    page.wait_for_selector("main .page:not(:has(.sk-page))")


def finish_a_lesson(page, site):
    open_(page, site, lesson_url("b.architecture") + "?step=99")
    page.get_by_test_id("lesson-done").click()


def test_progress_leads_with_where_to_continue_and_keeps_evidence_apart(page, static_site):
    finish_a_lesson(page, static_site)
    open_(page, static_site, "/me")
    where = page.locator(".pg-now")
    expect(where).to_be_visible()
    expect(where.locator("a.btn.primary")).to_have_attribute("href", re.compile(r"^/(learn/[a-z0-9-]+/|labs/|incidents/|challenges/)[a-z0-9-]+"))
    groups = page.locator(".me-group")
    assert groups.count() == 3, "read and answered / practised / verified on a real cluster, never one score"
    assert page.locator(".me-grid .stat-card.ok").count() == 0, "nothing is verified on a cluster in practice mode"
    expect(page.locator("h1")).to_have_count(1)
    assert page.errors == []


def test_review_says_when_the_next_card_comes_back(page, static_site):
    finish_a_lesson(page, static_site)
    open_(page, static_site, "/review")
    for _ in range(40):
        if not page.get_by_test_id("flip").count():
            break
        page.get_by_test_id("flip").click()
        page.get_by_test_id("grade-good").click()
    done = page.locator(".callout.ok")
    expect(done).to_contain_text("All caught up")
    expect(done).to_contain_text("The next card is due")
    assert page.errors == []


@pytest.mark.parametrize("width", [390, 820])
def test_learner_pages_have_no_horizontal_scroll(browser, static_site, width):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    finish_a_lesson(page, static_site)
    wide = []

    def check(label):
        w = page.evaluate("document.documentElement.scrollWidth")
        if w > width:
            wide.append((label, w))

    for route in ("/me", "/review", "/about"):
        open_(page, static_site, route)
        check(route)
    open_(page, static_site, diag_url("admin1"))
    check("diagnostic intro")
    page.get_by_test_id("diag-start").click()
    page.get_by_test_id("diag-choice").first.click()
    page.get_by_test_id("diag-conf-1").click()
    check("diagnostic question")
    page.get_by_test_id("diag-next").click()
    page.get_by_test_id("diag-stop").click()
    expect(page.get_by_test_id("diag-results")).to_be_visible()
    check("diagnostic results")
    open_(page, static_site, "/me")
    check("/me with a diagnostic")
    ctx.close()
    assert not wide, wide


def test_the_main_actions_show_a_keyboard_focus(page, static_site):
    finish_a_lesson(page, static_site)
    open_(page, static_site, "/review")
    for _ in range(60):
        if page.evaluate("document.activeElement && document.activeElement.dataset.testid === 'flip'"):
            break
        page.keyboard.press("Tab")
    focus = page.evaluate("(() => { const s = getComputedStyle(document.activeElement); return [document.activeElement.dataset.testid, s.outlineStyle, parseFloat(s.outlineWidth)] })()")
    assert focus[0] == "flip", "the show-answer button is reachable by keyboard"
    assert focus[1] != "none" and focus[2] >= 2, focus


def test_page_motion_stops_when_the_visitor_asks(browser, static_site):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    page = ctx.new_page()
    finish_a_lesson(page, static_site)
    open_(page, static_site, "/me")
    page.wait_for_selector(".me-grid .bar i")
    names = page.evaluate("[...document.querySelectorAll('.pg .bar i, .pg-now')].map(e => getComputedStyle(e).animationName)")
    ctx.close()
    assert names and set(names) == {"none"}, names
