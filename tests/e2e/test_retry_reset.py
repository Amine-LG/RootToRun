"""Learners can repeat every exercise. Three controls, never confused:
  - "Try again" starts a new attempt of the same exercise (fresh choices, old feedback gone); the first answer stays the
    honest record and the new one becomes the latest;
  - "Reset model" / "Reset" returns a model or a diagram to its starting state;
  - "Restart" starts an incident or a challenge again;
and only "Reset all learning progress" (Progress page) deletes saved progress. Reloading never leaves an exercise
finished and disabled. Static site, no cluster."""
import json
import re

from playwright.sync_api import expect
from addresses import lab_url, lesson_url

LESSON = "b.reconciliation"  # a check, a guess, a typed command and the reconciliation model
ORDER_LESSON = "f0.objects-api"
FINISHED = "d.services-dns"  # another lesson, finished first: nothing on this page may erase it


def go(page, site, route, wait="[data-testid=flow-step]"):
    page.goto(site.rstrip("/") + route)
    page.wait_for_selector(wait)


def step(page, sid):
    return page.locator(f"[data-step='{sid}']")


def progress(page):
    return page.evaluate("JSON.parse(localStorage.getItem('osa.progress.v2') || '{}')")


def lesson_data(page, site, lid):
    return page.evaluate(f"fetch('/data/en/lessons/{lid}.json').then(r => r.json())")


def finish_other_lesson(page, site):
    go(page, site, lesson_url(FINISHED) + "?step=99")
    page.get_by_test_id("lesson-done").click()
    assert progress(page)["lessons"][FINISHED]["done"]


def focused_testid(page):
    return page.evaluate("document.activeElement && (document.activeElement.dataset.testid || document.activeElement.className)")


def test_graded_check_can_be_answered_again_and_again(page, static_site):
    finish_other_lesson(page, static_site)
    go(page, static_site, lesson_url(LESSON))
    q_data = next(p for p in lesson_data(page, static_site, LESSON)["predict"] if p["after"] == "recall-chain")
    qid, right = q_data["id"], q_data["answer"]
    wrong = [i for i in range(len(q_data["choices"])) if i != right]
    q = step(page, "check:recall-chain").get_by_test_id("check")

    q.locator(f"[data-testid=choice][data-choice='{wrong[0]}']").click()
    q.get_by_test_id("check-submit").click()
    expect(q.get_by_test_id("verdict")).to_contain_text("Not quite")

    q.get_by_test_id("check-again").click()
    expect(q.get_by_test_id("verdict")).to_have_count(0)  # the old feedback is gone
    expect(q.locator("[data-testid=choice]").first).to_be_enabled()
    expect(q.get_by_test_id("check-submit")).to_be_disabled()  # nothing chosen yet
    assert focused_testid(page) == "choice"  # focus moved to the choices
    expect(q.get_by_test_id("check-live")).to_contain_text("New attempt")

    q.locator(f"[data-testid=choice][data-choice='{right}']").click()
    q.get_by_test_id("check-submit").click()
    expect(q.get_by_test_id("verdict")).to_contain_text("Right")
    # a right answer can be tried again too: choose a different answer and get its own feedback
    q.get_by_test_id("check-again").click()
    q.locator(f"[data-testid=choice][data-choice='{wrong[1]}']").click()
    q.get_by_test_id("check-submit").click()
    expect(q.get_by_test_id("verdict")).to_contain_text("Not quite")

    rec = progress(page)["predictions"][qid]
    assert (rec["first"]["ok"], rec["first"]["pick"], rec["latest"]["pick"], rec["n"]) == (False, wrong[0], wrong[1], 3)

    # a reload shows the latest answer with its feedback, and never a finished, disabled question
    page.reload()
    q = step(page, "check:recall-chain").get_by_test_id("check")
    expect(q.get_by_test_id("check-earlier")).to_be_visible()
    expect(q.locator(f"[data-testid=choice][data-choice='{wrong[1]}']")).to_have_class(re.compile("wrong"))
    q.get_by_test_id("check-again").click()
    q.locator(f"[data-testid=choice][data-choice='{right}']").click()
    q.get_by_test_id("check-submit").click()
    expect(q.get_by_test_id("verdict")).to_contain_text("Right")
    p = progress(page)
    assert p["predictions"][qid]["first"]["pick"] == wrong[0]  # the honest first answer survives every retry
    assert p["lessons"][FINISHED]["done"]  # and nothing else was touched


def test_predict_guess_can_be_changed_and_keeps_the_first_guess(page, static_site):
    go(page, static_site, lesson_url(LESSON))
    data = next(p for p in lesson_data(page, static_site, LESSON)["predict"] if p["after"] == "guess-scale-rs")
    g = step(page, f"predict:{data['id']}").get_by_test_id("guess")
    wrong = next(i for i in range(len(data["choices"])) if i != data["answer"])
    g.locator(f".guess-choice[data-choice='{wrong}']").click()
    expect(g.locator(".guess-res")).to_contain_text("What actually happens")
    expect(g.locator(".guess-choice").first).to_be_disabled()

    g.get_by_test_id("guess-again").click()
    expect(g.locator(".guess-res")).to_have_count(0)
    expect(g.locator(".guess-choice").first).to_be_enabled()
    g.locator(f".guess-choice[data-choice='{data['answer']}']").click()
    expect(g.locator(".guess-res")).to_contain_text("That is what happens")
    assert progress(page)["guesses"][f"guess:{data['id']}"]["pick"] == wrong  # a guess after seeing the answer is not recorded

    page.reload()
    g = step(page, f"predict:{data['id']}").get_by_test_id("guess")
    expect(g.locator(".guess-res")).to_contain_text("What actually happens")  # the recorded guess, shown again
    g.get_by_test_id("guess-again").click()
    expect(g.locator(".guess-choice").first).to_be_enabled()


def test_typed_command_can_be_tried_again_after_the_solution(page, static_site):
    go(page, static_site, lesson_url(LESSON))
    t = step(page, "try:try-scale")
    t.get_by_test_id("try-input").fill("kubectl scale deployment web --replicas=5")
    t.get_by_test_id("try-check").click()
    expect(t.get_by_test_id("try-hint")).to_be_visible()
    t.get_by_test_id("try-show").click()
    expect(t.get_by_test_id("try-status")).to_contain_text("Solution shown")

    t.get_by_test_id("try-again").click()
    expect(t.get_by_test_id("try-result")).to_have_count(0)
    expect(t.get_by_test_id("try-hint")).to_have_count(0)
    expect(t.get_by_test_id("try-input")).to_have_value("")
    expect(t.get_by_test_id("try-input")).to_be_focused()
    t.get_by_test_id("try-input").fill("kubectl scale deploy/web --replicas 3")
    t.get_by_test_id("try-check").click()
    expect(t.get_by_test_id("try-status")).to_contain_text("with hints")  # honest: the first attempt needed help
    rec = progress(page)["predictions"][f"try:{LESSON}:try-scale"]
    assert rec["first"]["ok"] is False and rec["latest"]["ok"] is True

    page.reload()
    t = step(page, "try:try-scale")
    expect(t.get_by_test_id("try-status")).to_be_visible()
    t.get_by_test_id("try-again").click()
    expect(t.get_by_test_id("try-input")).to_be_enabled()


def test_order_exercise_can_be_tried_again_after_showing_the_order(page, static_site):
    go(page, static_site, lesson_url(ORDER_LESSON))
    o = page.get_by_test_id("order").first
    items = o.get_by_test_id("order-item")
    start = items.all_inner_texts()
    o.get_by_test_id("order-check").click()  # the start order is never the solution
    expect(o.locator(".order-list li.bad")).not_to_have_count(0)
    o.get_by_test_id("order-again").click()  # after a wrong order: fix it, the arrangement stays
    expect(o.locator(".order-list li.bad")).to_have_count(0)
    expect(o.get_by_test_id("order-check")).to_be_enabled()
    assert items.all_inner_texts() == start
    assert focused_testid(page).startswith("icon-btn")

    o.get_by_test_id("order-check").click()
    o.get_by_test_id("order-show").click()
    expect(o.get_by_test_id("order-verdict")).to_contain_text("This is the right order")
    solved = items.all_inner_texts()
    o.get_by_test_id("order-again").click()  # after the shown order: a fresh attempt from the start order
    assert items.all_inner_texts() == start != solved
    expect(o.locator(".order-list .icon-btn:not(:disabled)").first).to_be_visible()
    expect(o.get_by_test_id("order-check")).to_be_enabled()

    page.reload()
    o = page.get_by_test_id("order").first
    expect(o.get_by_test_id("order-verdict")).to_contain_text("This is the right order")  # the latest result, from before
    o.get_by_test_id("order-again").click()
    expect(o.get_by_test_id("order-check")).to_be_enabled()


def test_order_put_right_with_the_move_buttons_is_right(page, static_site):
    """The learner arranges the items in their authored order with the move buttons (the lesson data lists them in
    that order), checks, and is told it is right; it is recorded as right; Try again starts a new attempt."""
    go(page, static_site, lesson_url(ORDER_LESSON))
    [st] = [s for s in lesson_data(page, static_site, ORDER_LESSON)["flow"] if s["kind"] == "order"]  # the lesson's one order task
    want = [t.strip() for t in st["items"]]  # plain words here, so the rendered text is the same
    o = page.get_by_test_id("order").first
    texts = lambda: [t.strip() for t in o.locator(".order-t").all_inner_texts()]
    assert sorted(texts()) == sorted(want) and texts() != want  # the same items, not already in order
    for target, item in enumerate(want):  # bring each item up to its place, one press at a time
        at = texts().index(item)
        for _ in range(at - target):
            o.get_by_test_id("order-item").nth(texts().index(item)).locator(".icon-btn:not(.down)").click()
        assert texts()[target] == item
    assert texts() == want
    o.get_by_test_id("order-check").click()
    expect(o.get_by_test_id("order-verdict")).to_contain_text("Right")
    expect(o.locator(".order-list li.bad")).to_have_count(0)
    rec = progress(page)["predictions"][f"order:{ORDER_LESSON}:{st['id']}"]
    assert rec["latest"]["ok"] is True and rec["first"]["ok"] is True and not rec["latest"].get("shown")
    o.get_by_test_id("order-again").click()  # after a right order: a fresh attempt from the start order
    expect(o.get_by_test_id("order-verdict")).to_have_count(0)
    expect(o.get_by_test_id("order-check")).to_be_enabled()
    assert texts() != want
    o.get_by_test_id("order-check").click()  # and that new attempt is graded on its own
    expect(o.get_by_test_id("order-verdict")).to_contain_text("Not yet")
    assert progress(page)["predictions"][f"order:{ORDER_LESSON}:{st['id']}"]["latest"]["ok"] is False


def test_model_prediction_and_model_state_can_be_reset(page, static_site):
    finish_other_lesson(page, static_site)
    go(page, static_site, lesson_url(LESSON))
    sim = step(page, "explore:model").locator(".sim-root")
    sim.scroll_into_view_if_needed()
    choices = sim.locator(".sim-choice")
    choices.first.click()
    first_feedback = sim.locator(".sim-feedback").inner_text()
    expect(choices.nth(1)).to_have_attribute("aria-disabled", "true")
    sim.get_by_test_id("sim-predict-again").click()
    expect(sim.locator(".sim-feedback")).to_have_count(0)
    expect(choices.nth(1)).to_have_attribute("aria-disabled", "false")
    choices.nth(1).click()
    expect(sim.locator(".sim-feedback")).not_to_have_text(first_feedback)  # the new choice has its own feedback

    queue = sim.locator(".sim-panel", has_text="Work queue").locator(".sim-panel-head")
    expect(queue).to_contain_text("0 item(s)")
    sim.get_by_role("button", name="oc delete pod").click()
    expect(queue).not_to_contain_text("0 item(s)")
    sim.get_by_test_id("sim-reset").click()
    sim = step(page, "explore:model").locator(".sim-root")
    expect(sim.locator(".sim-title")).to_be_focused()
    expect(step(page, "explore:model").locator(".sim-host > [role=status]")).to_contain_text("Model reset")
    # the whole model starts again, its prediction included: nothing selected, no feedback, the prediction gate is back
    expect(sim.locator(".sim-feedback")).to_have_count(0)
    expect(sim.locator(".sim-choice[aria-pressed=true]")).to_have_count(0)
    expect(sim.get_by_test_id("sim-skip")).to_be_visible()
    sim.locator(".sim-choice").nth(1).click()  # a new choice opens the model again, in its starting state
    queue = sim.locator(".sim-panel", has_text="Work queue").locator(".sim-panel-head")
    expect(queue).to_contain_text("0 item(s)")
    assert progress(page)["lessons"][FINISHED]["done"]

    page.reload()
    sim = step(page, "explore:model").locator(".sim-root")
    sim.scroll_into_view_if_needed()
    expect(sim.locator(".sim-choice[aria-pressed=true]")).to_have_count(1)  # the choice made after the reset is kept
    expect(sim.get_by_test_id("sim-predict-again")).to_be_visible()  # no trap after a reload
    expect(sim.get_by_test_id("sim-reset")).to_be_visible()


def test_reset_model_clears_its_challenges_and_keeps_the_rest(page, static_site):
    """A challenge completed in a model starts again after Reset model (as does its prediction); another model's
    challenges and the learner's progress stay."""
    page.emulate_media(reduced_motion="reduce")  # "Run until steady" then runs every step at once
    finish_other_lesson(page, static_site)
    page.evaluate("localStorage.setItem('oa.sim.drift.challenges', 'self-heal')")  # another model's work
    go(page, static_site, lesson_url(LESSON))
    sim = step(page, "explore:model").locator(".sim-root")
    sim.scroll_into_view_if_needed()
    sim.locator(".sim-choice").first.click()
    first = sim.locator(".sim-challenge").first
    expect(first).to_have_attribute("data-done", "false")
    sim.get_by_role("button", name="oc delete pod").click()
    sim.get_by_role("button", name="Run until steady").click()
    expect(first).to_have_attribute("data-done", "true")
    stored = lambda: page.evaluate("localStorage.getItem('oa.sim.reconcile.challenges') || ''")
    assert stored()

    sim.get_by_test_id("sim-reset").click()
    sim = step(page, "explore:model").locator(".sim-root")
    assert stored() == ""
    assert page.evaluate("localStorage.getItem('oa.sim.reconcile.predict')") is None  # a first visit again
    sim.get_by_test_id("sim-skip").click()  # past "Predict first" again: the challenges are there, none completed
    expect(sim.locator(".sim-challenge")).not_to_have_count(0)
    expect(sim.locator(".sim-challenge[data-done=true]")).to_have_count(0)
    expect(sim.locator(".sim-feedback")).to_have_count(0)  # the prediction is open again
    assert page.evaluate("localStorage.getItem('oa.sim.drift.challenges')") == "self-heal"
    assert progress(page)["lessons"][FINISHED]["done"]
    page.reload()  # and nothing brings the old marks back
    sim = step(page, "explore:model").locator(".sim-root")
    sim.scroll_into_view_if_needed()
    if sim.get_by_test_id("sim-skip").count():
        sim.get_by_test_id("sim-skip").click()
    expect(sim.locator(".sim-challenge")).not_to_have_count(0)
    expect(sim.locator(".sim-challenge[data-done=true]")).to_have_count(0)


# The model's whole visible state: its text without the polite announcements, and every field's value.
MODEL_STATE = """root => {
  const c = root.cloneNode(true);
  c.querySelectorAll('[role=status], [aria-live]:not([role=log])').forEach((e) => e.remove());
  return JSON.stringify([c.textContent.replace(/\\s+/g, ' '),
    [...root.querySelectorAll('input, select, textarea')].map((e) => e.type === 'checkbox' || e.type === 'radio' ? e.checked : e.value)]);
}"""
# one change per model, as a learner makes it, and (for a field) the field and its starting value
MODEL_CHANGE = {
    "scheduler": (lambda r: r.get_by_label("CPU request").fill("1500"), ("CPU request", "500")),
    "reconcile": (lambda r: r.get_by_role("button", name="oc delete pod").click(), None),
    "rollout": (lambda r: r.get_by_role("button", name=re.compile(r"^oc set image")).click(), None),
    "probes": (lambda r: r.get_by_label("Scenario").select_option("crash"), ("Scenario", "db-down")),
    "traffic": (lambda r: r.get_by_label("spec.host").fill("other.apps-crc.testing"), ("spec.host", "web-shop.apps-crc.testing")),
    "rbac": (lambda r: r.get_by_label("SCC admission (simplified)").check(), None),
    "storage": (lambda r: r.get_by_role("button", name="Create PVC data").click(), None),
    "drift": (lambda r: r.get_by_role("button", name="oc scale deployment/web --replicas=5").click(), None),
    "perms": (lambda r: r.get_by_label("Preset").select_option("root"), ("Preset", "openshift")),
}


def test_every_model_has_the_same_reset(page, static_site):
    page.goto(static_site.rstrip("/") + "/studio/model/scheduler")
    page.wait_for_selector(".sim-root")
    ids = page.evaluate("[...document.querySelectorAll('select option')].map(o => o.value).filter(v => v.startsWith('model/'))")
    assert len(ids) >= 9
    assert {i.removeprefix("model/") for i in ids} == set(MODEL_CHANGE), ids  # a change for every model
    for mid in ids:
        model = mid.removeprefix("model/")
        change, field = MODEL_CHANGE[model]
        page.goto(static_site.rstrip("/") + f"/studio/{mid}")
        root = page.locator(".sim-root")
        root.wait_for()
        gated = root.get_by_test_id("sim-skip").count() > 0
        if gated:
            root.get_by_test_id("sim-skip").click()
        start = root.evaluate(MODEL_STATE)
        change(root)
        changed = root.evaluate(MODEL_STATE)
        assert changed != start, f"{model}: the change did nothing"
        reset = root.locator(".sim-head-row").get_by_test_id("sim-reset")
        expect(reset).to_have_text("Reset model")
        # the models' own partial resets are gone: one reset per model, in its header
        expect(page.locator(".sim-root").get_by_role("button", name=re.compile(r"^\s*Reset", re.I))).to_have_count(1)
        reset.click()
        expect(page.locator(".sim-root .sim-title")).to_be_focused()
        root = page.locator(".sim-root")
        if gated:  # back behind "Predict first", as on a first visit; past it, exactly the starting state
            expect(root.get_by_test_id("sim-skip")).to_be_visible()
            root.get_by_test_id("sim-skip").click()
        assert root.evaluate(MODEL_STATE) == start, f"{model}: Reset model did not restore the starting state"
        if field:
            expect(root.get_by_label(field[0])).to_have_value(field[1])
        change(root)  # and the model still works after its reset
        assert root.evaluate(MODEL_STATE) == changed, model


def test_diagram_reset_clears_the_selection_and_the_zoom(page, static_site):
    page.goto(static_site.rstrip("/") + "/studio/diagram/request-path")
    page.wait_for_selector(".fd-node")
    zoom = page.locator(".graph-toolbar .zoom")
    fitted = zoom.inner_text()
    page.locator(".fd-node").first.click()
    page.get_by_role("button", name="Zoom in").click()
    page.get_by_role("button", name="Zoom in").click()
    expect(page.locator(".fd-node[aria-pressed=true]")).to_have_count(1)
    expect(zoom).not_to_have_text(fitted)
    page.get_by_test_id("diagram-reset").click()
    expect(page.locator(".fd-node[aria-pressed=true]")).to_have_count(0)
    expect(page.locator(".graph-inspector")).to_have_count(0)
    expect(zoom).to_have_text(fitted)
    page.locator(".fd-node").nth(1).click()  # and it works again
    expect(page.locator(".fd-node[aria-pressed=true]")).to_have_count(1)


def test_incident_can_be_restarted_without_touching_other_progress(page, static_site):
    finish_other_lesson(page, static_site)
    url = static_site.rstrip("/") + lab_url("inc.broken-rollout")
    page.goto(url)
    page.get_by_test_id("start-investigating").click()
    page.get_by_role("button", name="I have a theory").click()
    page.locator("textarea.diag").fill("The new image tag does not exist, so the new pods never become ready.")
    page.get_by_test_id("reveal").click()
    page.wait_for_selector(".debrief-full")
    page.locator(".selfcheck-box input").first.check()
    page.get_by_test_id("self-check-save").click()

    # work in progress is not discarded without asking: dismissing keeps everything
    page.once("dialog", lambda d: d.dismiss())
    page.get_by_test_id("restart-attempt").click()
    expect(page.locator(".debrief-full")).to_be_visible()
    assert progress(page)["labs"]["inc.broken-rollout"].get("selfCheck")

    page.once("dialog", lambda d: d.accept())
    page.get_by_test_id("restart-attempt").click()
    expect(page).to_have_url(re.compile(r"stage=symptom"))
    expect(page.get_by_test_id("start-investigating")).to_be_visible()
    expect(page.locator("h1")).to_be_focused()
    lab = progress(page)["labs"]["inc.broken-rollout"]
    assert {k: v for k, v in lab["incident"].items() if k != "rev"} == {"stage": 0, "hints": 0} and lab["incident"]["rev"]
    assert "selfCheck" not in lab and "diagnosis" not in lab
    assert lab["revealed"]  # having seen the answer stays on record
    assert progress(page)["lessons"][FINISHED]["done"]

    page.goto(url)  # a plain reload of the incident: the new attempt, not the old debrief
    expect(page.get_by_test_id("start-investigating")).to_be_visible()
    page.get_by_test_id("start-investigating").click()
    page.get_by_role("button", name="I have a theory").click()
    expect(page.locator("textarea.diag")).to_have_value("")
    page.locator("textarea.diag").fill("A different theory: the readiness probe points to the wrong port.")
    page.get_by_test_id("reveal").click()
    expect(page.locator(".debrief-full .mine")).to_contain_text("different theory")


def test_challenge_can_be_restarted(page, static_site):
    url = static_site.rstrip("/") + lab_url("ch.bounded-cleanup")
    page.goto(url)
    page.get_by_test_id("hint").click()
    expect(page.locator(".hint")).to_have_count(1)
    page.get_by_test_id("reveal").click()
    expect(page.locator(".ch-solution")).to_be_visible()

    page.get_by_test_id("restart-attempt").click()  # nothing written: no confirmation needed
    expect(page.locator(".ch-solution")).to_have_count(0)
    expect(page.locator(".hint")).to_have_count(0)
    page.reload()
    expect(page.get_by_test_id("reveal")).to_be_visible()  # still a fresh attempt after a reload
    expect(page.locator(".ch-solution")).to_have_count(0)
    lab = progress(page)["labs"]["ch.bounded-cleanup"]
    assert lab["revealed"] and lab["hints"] == 1  # help received stays on record
    page.get_by_test_id("reveal").click()
    expect(page.locator(".ch-solution")).to_be_visible()


def test_only_reset_learning_progress_deletes_progress(page, static_site):
    finish_other_lesson(page, static_site)
    go(page, static_site, lesson_url(LESSON))
    q = step(page, "check:recall-chain").get_by_test_id("check")
    q.locator("[data-testid=choice]").first.click()
    q.get_by_test_id("check-submit").click()
    q.get_by_test_id("check-again").click()
    sim = step(page, "explore:model").locator(".sim-root")
    sim.scroll_into_view_if_needed()
    sim.locator(".sim-choice").first.click()
    sim.get_by_test_id("sim-reset").click()
    page.goto(static_site.rstrip("/") + "/me")
    expect(page.locator(".pg-me")).to_contain_text("1 of")  # the finished lesson is still counted
    p = progress(page)
    assert p["lessons"][FINISHED]["done"] and p["predictions"]

    page.get_by_test_id("reset").click()
    page.get_by_test_id("reset-confirm").click()
    p = progress(page)
    assert not p.get("lessons") and not p.get("predictions")
    assert page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('oa.sim.'))") == []
    go(page, static_site, lesson_url(LESSON))
    sim = step(page, "explore:model").locator(".sim-root")
    sim.scroll_into_view_if_needed()
    expect(sim.locator(".sim-feedback")).to_have_count(0)  # the model's prediction was cleared too
    q = step(page, "check:recall-chain").get_by_test_id("check")
    expect(q.locator("[data-testid=choice]").first).to_be_enabled()
    expect(q.get_by_test_id("check-earlier")).to_have_count(0)


def test_order_exercise_is_usable_with_a_keyboard_and_a_screen_reader(page, static_site):
    """Accessibility audit (agent D) on the order task: after "Check the order" focus goes to the verdict (the button
    becomes disabled), the result is announced by a live region mounted in advance, and the move buttons name the item
    they move and announce its new position."""
    go(page, static_site, lesson_url("ct.openshift-images"))
    o = page.get_by_test_id("order").first
    o.scroll_into_view_if_needed()
    live = o.get_by_test_id("order-live")
    expect(live).to_have_count(1)  # mounted before anything happens, so that what appears in it is announced
    expect(live).to_have_text("")
    items = o.get_by_test_id("order-item")
    n = items.count()
    texts = [t.strip() for t in o.locator(".order-t").all_inner_texts()]

    # (3) the move buttons say which item they move; moving announces the new position and keeps focus on the item
    first_down = items.first.locator(".icon-btn.down")
    assert texts[0][:20] in first_down.get_attribute("aria-label"), first_down.get_attribute("aria-label")
    first_down.focus()
    page.keyboard.press("Enter")
    expect(live).to_contain_text(f"now step 2 of {n}")
    expect(live).to_contain_text(texts[0][:20])
    assert texts[0][:20] in page.evaluate("document.activeElement.closest('li')?.innerText || ''")
    # moved back to the top: its "up" button is disabled there, so focus moves to its "down" button, not the page
    page.evaluate("document.activeElement.closest('li').querySelector('.icon-btn:not(.down)').focus()")
    page.keyboard.press("Enter")
    expect(live).to_contain_text(f"now step 1 of {n}")
    expect(o.locator(".icon-btn.down:focus")).to_have_count(1)  # moved in the next animation frame: wait for it

    # (1) checking with the keyboard moves focus to the verdict; (2) the live region announces the result
    o.get_by_test_id("order-check").focus()
    page.keyboard.press("Enter")
    expect(o.get_by_test_id("order-verdict")).to_be_focused()
    expect(live).to_contain_text("Not yet")
    expect(o.get_by_test_id("order-verdict")).not_to_have_attribute("role", "status")
    o.get_by_test_id("order-show").focus()
    page.keyboard.press("Enter")
    expect(o.get_by_test_id("order-verdict")).to_be_focused()  # the pressed link is gone
    expect(live).to_contain_text("This is the right order")


def test_a_wrong_command_after_try_again_is_recorded(page, static_site):
    """solve, Try again, then a wrong command: the failure is the latest attempt (the first success stays)."""
    go(page, static_site, lesson_url(LESSON))
    t = step(page, "try:try-scale")
    t.get_by_test_id("try-input").fill("kubectl scale deployment web --replicas=3")
    t.get_by_test_id("try-check").click()
    expect(t.get_by_test_id("try-status")).to_contain_text("on your own")
    t.get_by_test_id("try-again").click()
    t.get_by_test_id("try-input").fill("kubectl scale deployment web --replicas=7")
    t.get_by_test_id("try-check").click()
    rec = progress(page)["predictions"][f"try:{LESSON}:try-scale"]
    assert (rec["first"]["ok"], rec["latest"]["ok"], rec["n"]) == (True, False, 2), rec
    page.reload()
    t = step(page, "try:try-scale")
    expect(t.get_by_test_id("try-input")).to_be_visible()
    expect(t.get_by_test_id("try-result")).to_have_count(0)  # the latest attempt failed: not shown as solved


def hold(page, pattern):
    """Holds the responses to `pattern` until released, to answer a request after the learner has moved on."""
    held = []
    page.route(pattern, lambda route: held.append(route))
    return held


def test_a_late_solution_does_not_reach_a_restarted_challenge(page, static_site):
    """Show solution, Restart before the answer arrives: the answer belongs to the old attempt."""
    page.goto(static_site.rstrip("/") + lab_url("ch.bounded-cleanup"))
    page.get_by_test_id("hint").click()
    expect(page.locator(".hint")).to_have_count(1)
    held = hold(page, "**/ch.bounded-cleanup.reveal.json")
    page.get_by_test_id("reveal").click()
    page.get_by_test_id("restart-attempt").click()
    expect(page.locator(".hint")).to_have_count(0)
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    assert held, "the reveal request was not made"
    held[0].continue_()
    page.wait_for_timeout(800)
    expect(page.locator(".ch-solution")).to_have_count(0)
    assert progress(page)["labs"]["ch.bounded-cleanup"]["incident"]["stage"] == 0
    page.reload()
    expect(page.get_by_test_id("reveal")).to_be_visible()
    expect(page.locator(".ch-solution")).to_have_count(0)


def test_a_late_answer_does_not_reach_a_restarted_incident(page, static_site):
    page.goto(static_site.rstrip("/") + lab_url("inc.broken-rollout") + "?stage=diagnose")
    page.locator("textarea.diag").fill("The new image tag does not exist, so the new pods never become ready.")
    held = hold(page, "**/inc.broken-rollout.reveal.json")
    page.get_by_test_id("reveal").click()
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    assert held, "the reveal request was not made"
    page.once("dialog", lambda d: d.accept())
    page.get_by_test_id("restart-attempt").click()
    expect(page).to_have_url(re.compile(r"stage=symptom"))
    held[0].continue_()
    page.wait_for_timeout(800)
    expect(page).to_have_url(re.compile(r"stage=symptom"))  # no jump to the old attempt's debrief
    expect(page.get_by_test_id("start-investigating")).to_be_visible()
    lab = progress(page)["labs"]["inc.broken-rollout"]  # the restart is recorded even before the draft was saved
    assert lab["incident"]["stage"] == 0 and lab["incident"].get("rev") and "diagnosis" not in lab and not lab.get("revealed"), lab


def test_restart_asks_before_discarding_a_draft_not_saved_yet(page, static_site):
    """the confirmation looks at the text on screen, not the copy saved 600 ms later."""
    page.goto(static_site.rstrip("/") + lab_url("inc.broken-rollout") + "?stage=diagnose")
    asked = []
    page.on("dialog", lambda d: (asked.append(d.message), d.dismiss()))
    page.locator("textarea.diag").fill("A theory typed just now, long enough to matter.")
    page.get_by_test_id("restart-attempt").click()  # at once: before the draft is saved
    assert asked, "no confirmation before discarding the draft"
    expect(page.locator("textarea.diag")).to_have_value("A theory typed just now, long enough to matter.")


def test_a_restart_in_another_tab_does_not_disable_this_tab(page, static_site):
    """Two tabs on the same challenge; the learner restarts it in the second. The first tab follows the new attempt, and
    its Show solution still works (it used to discard every answer as belonging to an older attempt until a reload)."""
    url = static_site.rstrip("/") + lab_url("ch.bounded-cleanup")
    page.goto(url)
    page.get_by_test_id("hint").click()
    expect(page.locator(".hint")).to_have_count(1)
    other = page.context.new_page()
    other.goto(url)
    other.get_by_test_id("restart-attempt").click()
    expect(other.locator(".hint")).to_have_count(0)
    other.close()
    expect(page.locator(".hint")).to_have_count(0)  # this tab is now in the new attempt too
    page.get_by_test_id("reveal").click()
    expect(page.locator(".ch-solution")).to_be_visible()
    assert progress(page)["labs"]["ch.bounded-cleanup"]["incident"]["stage"] == 1
