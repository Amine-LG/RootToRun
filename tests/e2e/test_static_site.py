"""The public, cluster-free experience: a visitor with nothing installed, on the static site."""
import json
import re

from playwright.sync_api import expect
from addresses import lab_url, lesson_url, track_url
from conftest import wait_true


def open_(page, site, route="/"):
    page.goto(site.rstrip("/") + route)
    page.wait_for_selector("main .page:not(:has(.sk-page))")


def test_home_has_one_obvious_start(page, static_site):
    requests = []
    page.on("request", lambda r: requests.append(r.url))
    open_(page, static_site)
    expect(page.get_by_role("heading", name=re.compile("Container platform skills, learned hands-on"))).to_be_visible()  # no third-party mark in headings
    start = page.get_by_test_id("start-learning")
    expect(start).to_be_visible()
    assert page.locator(".btn.primary:visible").count() == 1, "the home page must have exactly one primary action"
    expect(page.get_by_test_id("path-card")).to_be_visible()  # the page has rendered its content (no lazy request follows)
    expect(page.get_by_test_id("first-moment")).to_have_count(0)  # no mini-quiz on the home page
    assert [u for u in requests if "/api/" in u and not u.endswith("/api/meta")] == [], "the static site must not call the API"
    start.click()
    expect(page).to_have_url(re.compile(re.escape(lesson_url("lx.first-steps")) + "$"))
    assert page.errors == []


def test_map_journey_and_territory_page(page, static_site):
    open_(page, static_site, "/learn")
    expect(page.locator(".jmap .jm-stop")).to_have_count(6)  # six territories on one line, the practice arena beside it
    expect(page.get_by_test_id("map-practice")).to_be_visible()
    expect(page.locator(".jm-row")).to_have_count(7)
    # choosing a route highlights it without hiding anything
    page.get_by_test_id("route-select").select_option("kube-to-openshift")
    expect(page.locator(".jmap .jm-stop.off")).not_to_have_count(0)
    expect(page.locator(".jm-row")).to_have_count(7)  # nothing is hidden by a route
    assert page.locator(".jm-row.on, .jm-row.part").count() >= 1
    page.get_by_test_id("map-admin1").locator("a").click()
    expect(page).to_have_url(re.compile(re.escape(track_url("admin1")) + "$"))
    expect(page.locator(".chapter.open")).to_have_count(1)  # only the current chapter is expanded
    page.get_by_test_id("path-next").click()
    expect(page).to_have_url(re.compile(re.escape(track_url("admin1")) + "/[a-z0-9-]+$"))
    assert page.errors == []


def test_a_long_form_lesson_is_one_article_too(page, static_site):
    """Lessons not yet rewritten as flows are also read as one page: every part visible, checks answered in place."""
    open_(page, static_site, lesson_url("h.observability"))
    page.wait_for_selector("[data-testid=flow-step]")
    expect(page.get_by_test_id("lesson-next")).to_have_count(0)
    assert page.get_by_test_id("toc-link").count() >= 4
    check = page.locator("[data-testid=flow-step][data-kind=check]").first
    q = check.get_by_test_id("check").first
    q.locator("[data-testid=choice]").first.click()
    q.get_by_test_id("check-submit").click()
    expect(q.locator(".verdict")).to_be_visible()
    page.get_by_test_id("lesson-done").click()
    expect(page.locator(".toast")).to_contain_text("Lesson completed")
    expect(page.get_by_test_id("next-lesson")).to_be_visible()
    expect(page.get_by_test_id("lesson-facts")).to_contain_text("Finished reading")
    assert page.errors == []


def test_lab_practice_replays_real_output(page, static_site):
    open_(page, static_site, lab_url("lab.deployment-reconciliation"))
    expect(page.locator(".lab-h .pill.ok")).to_contain_text("Tested on OpenShift 4.21")
    step = page.locator(".lab-step")
    if step.get_by_test_id("skip-guess").count():
        step.get_by_test_id("skip-guess").click()
    step.locator("[data-testid=replay]").first.click()
    screen = step.locator(".screen").first
    expect(screen).to_contain_text("recorded")
    expect(screen.locator(".tx-table, .tx-out").first).to_be_visible(timeout=8000)
    assert page.errors == []


def test_lab_steps_complete_and_finish(page, static_site):
    open_(page, static_site, lab_url("lab.rbac"))
    page.wait_for_selector(".lab-step")
    for _ in range(25):
        step = page.locator(".lab-step")
        if not step.count():
            break
        if step.get_by_test_id("skip-guess").count():
            step.get_by_test_id("skip-guess").click()
        for b in step.locator("[data-testid=replay]").all():
            b.click()
        page.get_by_test_id("next-step").click()
        page.wait_for_selector(".lab-step, .finish")
    expect(page.locator(".finish")).to_be_visible()
    expect(page.locator(".finish-banner")).to_contain_text("Lab complete")
    expect(page.locator(".finish .checks")).to_contain_text("All checks passed")
    expect(page.locator(".finish .checks")).not_to_contain_text("Verified")  # "Verified" is earned on your own cluster
    assert page.errors == []


def test_incident_flow(page, static_site):
    open_(page, static_site, lab_url("inc.service-selector-503"))
    expect(page.locator(".pager-alert")).to_contain_text("503")
    page.get_by_test_id("start-investigating").click()
    page.locator(".lesson-step [data-testid=replay]").nth(1).click()
    expect(page.locator(".lesson-step .screen").first).to_contain_text("<unset>", timeout=8000)
    page.get_by_test_id("hint").click()
    expect(page.locator(".hint")).to_have_count(1)
    page.get_by_role("button", name="I have a theory").click()
    page.locator("textarea.diag").fill("The Service selector app=payments-web matches no pod; the pods are labelled app=web. Fix the selector.")
    page.get_by_test_id("reveal").click()
    expect(page.locator(".compare")).to_contain_text("zero endpoints")
    expect(page.locator(".compare .mine")).to_contain_text("app=payments-web")
    expect(page.locator(".debrief-full .cmdblock")).to_have_count(2)
    expect(page.locator(".debrief-full .checks").first).to_contain_text("All checks passed")
    expect(page.locator(".debrief-full .checks").first).not_to_contain_text("Verified")
    assert page.errors == []


def test_practice_terminal(page, static_site):
    open_(page, static_site, "/terminal")
    page.locator(".starters button").first.click()
    expect(page.locator(".tx-entry")).to_have_count(1)
    inp = page.get_by_test_id("term-input")
    inp.fill("oc auth can-i create projectrequests")
    inp.press("Enter")
    expect(page.locator(".tx-body")).to_contain_text("yes")
    inp.fill("oc get pods -n somewhere-else")
    inp.press("Enter")
    expect(page.locator(".tx-nomatch")).to_contain_text("not recorded")
    assert page.errors == []


def test_command_reference_and_palette(page, static_site):
    open_(page, static_site, "/commands")
    page.get_by_test_id("cmd-search").fill("who-can")
    page.locator(".cmd-item-h").first.click()
    expect(page.locator(".cmd-item.open .screen")).to_be_visible()
    page.keyboard.press("Control+k")
    page.get_by_test_id("palette-input").fill("OOMKilled")
    # Enter opens the highlighted result: wait until it is the incident (the results settle as the index loads;
    # pressing Enter earlier opened whatever was first then, a flaky failure in a Chromium CI run)
    expect(page.locator(".palette-list [role=option][aria-selected=true]")).to_have_attribute("data-href", re.compile(re.escape(lab_url("inc.oomkilled")) + "$"))
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(re.escape(lab_url("inc.oomkilled")) + "$"))
    assert page.errors == []


def test_review_unlocks_after_a_lesson(page, static_site):
    open_(page, static_site, "/review")
    expect(page.locator(".empty")).to_be_visible()
    open_(page, static_site, lesson_url("h.observability") + "?step=99")
    page.get_by_test_id("lesson-done").click()
    open_(page, static_site, "/review")
    page.get_by_test_id("flip").click()
    page.get_by_test_id("grade-good").click()
    expect(page.locator(".rev-stats")).to_be_visible()
    assert page.errors == []


def test_progress_persists_exports_and_resets(page, static_site):
    open_(page, static_site, lesson_url("b.architecture") + "?step=99")
    page.get_by_test_id("lesson-done").click()
    page.reload()
    open_(page, static_site, "/me")
    expect(page.locator(".me-grid")).to_contain_text("1Lessons finished")
    with page.expect_download() as d:
        page.get_by_role("button", name="Export progress").click()
    assert d.value.suggested_filename.startswith("roottorun-progress")
    # Reset asks inline, focuses the safe choice, then confirms what really happened and updates the page.
    page.get_by_test_id("reset").click()
    expect(page.get_by_role("button", name="Cancel")).to_be_focused()
    page.get_by_test_id("reset-confirm").click()
    expect(page.locator(".callout.ok[role=status]")).to_contain_text("Your progress was deleted")
    expect(page.locator(".me-grid")).to_contain_text("0Lessons finished")
    expect(page.get_by_test_id("reset")).to_be_focused()
    open_(page, static_site, "/learn")
    expect(page.locator(".station.done")).to_have_count(0)


def test_progress_export_then_import_restores_it(page, static_site, tmp_path):
    """The exported file really holds the progress, and importing it into an emptied browser brings it back; a file
    that is not a progress file is refused without touching what is stored."""
    open_(page, static_site, lesson_url("b.architecture") + "?step=99")
    page.get_by_test_id("lesson-done").click()
    open_(page, static_site, "/me")
    expect(page.locator(".me-grid")).to_contain_text("1Lessons finished")
    with page.expect_download() as d:
        page.get_by_role("button", name="Export progress").click()
    saved = tmp_path / "progress.json"
    d.value.save_as(saved)
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["v"] == 2 and data["lessons"]["b.architecture"]["done"] > 0
    page.get_by_test_id("reset").click()
    page.get_by_test_id("reset-confirm").click()
    expect(page.locator(".me-grid")).to_contain_text("0Lessons finished")
    page.locator("input[type=file]").set_input_files(str(saved))
    expect(page.locator(".callout.ok[role=status]")).to_contain_text("Imported")
    page.reload()
    page.wait_for_selector("main .page:not(:has(.sk-page))")
    expect(page.locator(".me-grid")).to_contain_text("1Lessons finished")
    bad = tmp_path / "other.json"
    bad.write_text('{"v": 9, "lessons": {}}', encoding="utf-8")
    page.locator("input[type=file]").set_input_files(str(bad))
    expect(page.locator(".callout.bad[role=status]")).to_contain_text("could not be imported")
    page.reload()
    page.wait_for_selector("main .page:not(:has(.sk-page))")
    expect(page.locator(".me-grid")).to_contain_text("1Lessons finished")
    assert page.errors == []


def test_reset_reports_failure_when_storage_refuses(page, static_site):
    open_(page, static_site, lesson_url("b.architecture") + "?step=99")
    page.get_by_test_id("lesson-done").click()
    open_(page, static_site, "/me")
    expect(page.locator(".me-grid")).to_contain_text("1Lessons finished")
    page.evaluate("() => { Storage.prototype.setItem = function () { throw new DOMException('full', 'QuotaExceededError') } }")
    page.get_by_test_id("reset").click()
    page.get_by_test_id("reset-confirm").click()
    expect(page.locator(".callout.bad[role=status]")).to_contain_text("could not be deleted")
    expect(page.locator(".toast")).to_have_count(0)  # no success toast for a failed reset


def test_mobile_navigation(browser, static_site):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    pg = ctx.new_page()
    pg.goto(static_site.rstrip("/") + "/")
    pg.wait_for_selector("main .page:not(:has(.sk-page))")  # the page and the course data are in (the menu lists them)
    pg.locator(".nav-toggle").click()
    pg.locator(".menu-sheet").get_by_role("link", name="Incidents").click()
    expect(pg.get_by_role("heading", name="Incidents")).to_be_visible()
    expect(pg.locator(".menu-sheet")).to_have_count(0)  # the choice closed the menu
    ctx.close()


def test_theme_choice_is_remembered(page, static_site):
    open_(page, static_site)
    # the theme in effect before the click: the stored choice, else the system preference
    effective = "document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')"
    before = page.evaluate(effective)
    page.get_by_role("button", name="Dark theme").click()  # the toggle is named by what it turns on, with aria-pressed
    # a toggle that does nothing must fail here (waits for the change instead of reading it at once)
    wait_true(page, "(b) => ['light', 'dark'].includes(document.documentElement.dataset.theme) && document.documentElement.dataset.theme !== b", arg=before)
    theme = page.evaluate("document.documentElement.dataset.theme")
    page.reload()
    page.wait_for_selector("main .page")
    assert page.evaluate("document.documentElement.dataset.theme") == theme


def test_handbook(page, static_site):
    open_(page, static_site, "/handbook")
    page.get_by_role("link", name=re.compile("A Route answers 503")).click()
    expect(page.locator(".dtree")).to_be_visible()
    open_(page, static_site, "/case/case.friday-release")
    expect(page.locator(".owners")).to_be_visible()
    assert page.errors == []


def test_lab_commands_replay_their_recording(page, static_site):
    """Replaying a lab command shows the output recorded for it, from the static export."""
    open_(page, static_site, lab_url("lab.cli-tour"))
    page.wait_for_selector("[data-testid=replay]", state="attached")
    page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")  # some commands sit in sections
    block = page.locator(".cmdblock").filter(has_text="oc whoami").first
    block.get_by_test_id("replay").click()
    expect(block.locator(".screen")).to_contain_text("developer", timeout=8000)
    assert page.errors == []


def test_direct_links_and_page_titles(page, static_site):
    """Every lesson and lab has a real URL with its own title (shareable, indexable); old #/ links still work."""
    page.goto(static_site.rstrip("/") + lab_url("inc.dns-typo"))
    assert "resolve" in page.title().lower()
    page.wait_for_selector(".pager-alert")
    page.goto(static_site.rstrip("/") + "/#/lesson/o1.cli")  # an old link: the hash form, with an id
    expect(page).to_have_url(re.compile(re.escape(lesson_url("o1.cli")) + "$"))
