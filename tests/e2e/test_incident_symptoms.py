"""An incident starts like a page from monitoring: the symptom panel shows what monitoring would see (availability, the
Route's answer, ready endpoints, restarts), never a check that reads the configuration and so states the cause (the
misspelt image, the wrong host name, the missing permission). Those checks appear with the answer."""
import json

from playwright.sync_api import expect
from addresses import lab_url


def recorded_before(page, lid):
    return page.evaluate(f"fetch('/data/en/labs/{lid}.json').then(r => r.json())")


def open_symptoms(page, site, lid):
    page.goto(site.rstrip("/") + lab_url(lid) + "?stage=symptom")
    panel = page.get_by_test_id("symptom-checks")
    panel.locator("summary").click()
    return panel


def test_the_symptom_panel_does_not_name_the_cause(page, static_site):
    panel = open_symptoms(page, static_site, "inc.imagepull")
    data = recorded_before(page, "inc.imagepull")
    types = {c["id"]: c["type"] for c in data["lab"]["checks"]}
    results = data["recording"]["verify_before"]["results"]
    field = next(r for r in results if types[r["id"]] == "field")  # the image check: names the misspelt image
    assert "htpd" in field["observed"]  # the recorded cause, as the grader saw it
    expect(panel).to_contain_text("web is available")
    expect(panel).not_to_contain_text(field["title"])
    expect(panel).not_to_contain_text("htpd")
    expect(page.get_by_test_id("symptom-checks-hidden")).to_contain_text("1 more")


def test_genuine_symptoms_are_shown_and_causes_hidden_whatever_the_check_type(page, static_site):
    """The API call's 403 is what the workload sees (shown); the missing verb and the misspelt binding are the cause
    (hidden). In the drift incident the replica check would print spec.replicas 0, one of the changes: hidden."""
    panel = open_symptoms(page, static_site, "inc.rbac-denied")
    results = {r["id"]: r for r in recorded_before(page, "inc.rbac-denied")["recording"]["verify_before"]["results"]}
    expect(panel).to_contain_text(results["api-200"]["title"])
    expect(panel).to_contain_text("403")
    for cause in ("can-list", "no-typo"):
        expect(panel).not_to_contain_text(results[cause]["title"])
    expect(page.get_by_test_id("symptom-checks-hidden")).to_contain_text("2 more")
    panel = open_symptoms(page, static_site, "inc.gitops-drift")
    expect(panel).not_to_contain_text("spec.replicas 0")
    expect(panel).not_to_contain_text("PORTAL_MODE")
    panel = open_symptoms(page, static_site, "inc.networkpolicy-block")
    expect(panel).to_contain_text("Connection timed out")  # the symptom, shown although it is an exec check


def test_symptom_level_checks_are_all_shown(page, static_site):
    panel = open_symptoms(page, static_site, "inc.service-selector-503")
    data = recorded_before(page, "inc.service-selector-503")
    for r in data["recording"]["verify_before"]["results"]:  # endpoints and the Route: what monitoring sees
        expect(panel).to_contain_text(r["title"])
    expect(page.get_by_test_id("symptom-checks-hidden")).to_have_count(0)


def test_an_incident_says_where_its_objects_come_from_before_the_investigation(page, static_site):
    page.goto(static_site.rstrip("/") + lab_url("inc.imagepull") + "?stage=symptom")
    bg = page.get_by_test_id("activity-background")
    bg.locator("summary").click()
    expect(bg).to_contain_text("Where everything comes from")
    expect(bg).not_to_contain_text("htpd")  # provenance, not the cause


def test_a_challenge_shows_its_background_first_and_its_review_questions_only_with_the_solution(page, static_site):
    page.goto(static_site.rstrip("/") + lab_url("ch.ship-web-app"))
    data = page.evaluate("fetch('/data/en/labs/ch.ship-web-app.json').then(r => r.json())")
    assert data["lab"]["background"] and data["lab"]["questions"]  # this challenge has both
    expect(page.get_by_test_id("activity-background")).to_be_visible()
    expect(page.get_by_test_id("challenge-questions")).to_have_count(0)
    page.get_by_test_id("reveal").click()
    expect(page.get_by_test_id("challenge-questions")).to_be_visible()


def test_a_challenge_shows_the_starter_files_it_asks_you_to_save(page, static_site):
    """ch.helm-release says to save its chart to work without the app: the chart must be on the page before the
    attempt, file by file, exactly as the app writes it (the files are inputs; the answer is in the fix and trials)."""
    page.goto(static_site.rstrip("/") + lab_url("ch.helm-release"))
    data = page.evaluate("fetch('/data/en/labs/ch.helm-release.json').then(r => r.json())")
    files = data["lab"]["files"]
    assert "chart/values.yaml" in files and "chart/templates/deployment.yaml" in files
    panel = page.get_by_test_id("challenge-files")
    expect(page.get_by_test_id("reveal")).to_be_visible()  # before any solution is shown
    panel.locator("summary").first.click()
    for path in files:
        expect(panel).to_contain_text(f"lab/{path}")
    expect(panel).to_contain_text("replicas: 1")  # values.yaml's real content
