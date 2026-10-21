""""Reset model" returns an Explore model to exactly the state of a first visit: the learner's choice is no longer
selected, its feedback is gone, and another choice can be made at once, again and again, without a reload. Learning
progress and other lessons are untouched. Every model is checked, in the Explore studio and inside a lesson."""
import pytest
from playwright.sync_api import expect
from addresses import lesson_url

MODELS = ["scheduler", "reconcile", "rollout", "probes", "traffic", "rbac", "storage", "drift"]  # with a prediction


def progress(page):
    return page.evaluate("localStorage.getItem('osa.progress.v2')")


def open_model(page, site, mid):
    page.goto(site.rstrip("/") + f"/studio/model/{mid}")
    root = page.locator(".sim-root")
    root.wait_for()
    return root


@pytest.mark.parametrize("mid", MODELS)
def test_reset_model_clears_the_choice_and_lets_the_learner_choose_again(page, static_site, mid):
    page.goto(static_site.rstrip("/") + lesson_url("d.services-dns"))  # some learning progress that must survive
    page.wait_for_selector("[data-testid=flow-step]")
    saved = progress(page)
    assert saved and "d.services-dns" in saved
    root = open_model(page, static_site, mid)
    choices = root.locator(".sim-choice")
    labels = choices.all_inner_texts()
    assert len(labels) >= 2
    for rnd, pick in enumerate([0, 1, 0]):  # choose A, reset, choose B, reset, choose A again
        expect(root.locator(".sim-choice[aria-pressed=true]")).to_have_count(0)
        expect(root.locator(".sim-feedback")).to_have_count(0)
        choices.nth(pick).click()
        chosen = root.locator(".sim-choice[aria-pressed=true]")
        expect(chosen).to_have_count(1)  # the choice is visibly selected …
        expect(chosen).to_have_text(labels[pick])  # … and it is the one just clicked, not an earlier one
        assert chosen.get_attribute("data-state") in ("correct", "wrong")
        expect(root.locator(".sim-feedback")).to_be_visible()
        if rnd == 2:
            break
        root.get_by_test_id("sim-reset").click()
        root = page.locator(".sim-root")
        expect(root.locator(".sim-title")).to_be_focused()
        expect(root.locator(".sim-choice[aria-pressed=true]")).to_have_count(0)  # nothing remains selected
        expect(root.locator(".sim-choice[data-state=correct], .sim-choice[data-state=wrong]")).to_have_count(0)  # no marks
        expect(root.locator(".sim-feedback")).to_have_count(0)
        expect(root.get_by_test_id("sim-skip")).to_be_visible()  # back behind "Predict first", as on a first visit
        choices = root.locator(".sim-choice")
    assert progress(page) == saved  # Reset model never touches learning progress


def test_perms_model_prediction_is_reset(page, static_site):
    """The file-permission model keeps its own allowed/denied prediction: Reset clears it too."""
    root = open_model(page, static_site, "perms")
    allowed = root.get_by_role("button", name="Predict allowed")
    denied = root.get_by_role("button", name="Predict denied")
    for _ in range(2):
        allowed.click()
        expect(allowed).to_have_attribute("aria-pressed", "true")
        root.get_by_test_id("sim-reset").click()
        root = page.locator(".sim-root")
        allowed = root.get_by_role("button", name="Predict allowed")
        denied = root.get_by_role("button", name="Predict denied")
        expect(allowed).to_have_attribute("aria-pressed", "false")
        expect(denied).to_have_attribute("aria-pressed", "false")
        denied.click()
        expect(denied).to_have_attribute("aria-pressed", "true")
        expect(allowed).to_have_attribute("aria-pressed", "false")
        root.get_by_test_id("sim-reset").click()
        root = page.locator(".sim-root")
        allowed = root.get_by_role("button", name="Predict allowed")
        denied = root.get_by_role("button", name="Predict denied")


def test_reset_inside_a_lesson_starts_the_model_over(page, static_site):
    page.goto(static_site.rstrip("/") + lesson_url("b.reconciliation"))
    page.wait_for_selector("[data-testid=flow-step]")
    sim = page.locator("[data-step='explore:model'] .sim-root")
    sim.scroll_into_view_if_needed()
    sim.locator(".sim-choice").nth(0).click()
    expect(sim.locator(".sim-choice[aria-pressed=true]")).to_have_count(1)
    for _ in range(2):
        sim.get_by_test_id("sim-reset").click()
        sim = page.locator("[data-step='explore:model'] .sim-root")
        expect(sim.locator(".sim-choice[aria-pressed=true]")).to_have_count(0)
        expect(sim.locator(".sim-feedback")).to_have_count(0)
        sim.locator(".sim-choice").nth(1).click()
        expect(sim.locator(".sim-choice[aria-pressed=true]")).to_have_count(1)
        expect(sim.locator(".sim-feedback")).to_be_visible()
    page.reload()  # the reset is not undone by a reload
    sim = page.locator("[data-step='explore:model'] .sim-root")
    sim.scroll_into_view_if_needed()
    expect(sim.locator(".sim-choice[aria-pressed=true]")).to_have_count(1)  # the last real choice is remembered
