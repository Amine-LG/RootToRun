"""Practice mode served by the API, and (opt-in) a full live incident on a real cluster."""
import re

from playwright.sync_api import expect
from addresses import lab_url


def test_practice_server(page, practice_server):
    page.goto(practice_server.rstrip("/") + lab_url("inc.oomkilled"))
    page.wait_for_selector(".pager-alert")
    expect(page.locator(".site-foot")).to_contain_text("Practice mode")
    expect(page.locator(".env-line")).to_contain_text("recorded")
    page.get_by_test_id("start-investigating").click()
    page.locator(".lesson-step [data-testid=replay]").nth(1).click()
    expect(page.locator(".lesson-step .screen").first).to_contain_text("OOMKilled exit=137", timeout=8000)
    assert page.errors == []


def test_live_incident_repaired_on_the_cluster(page, cluster_server):
    """Break an app on the cluster, repair it with the recorded fix, and let the academy verify it."""
    page.set_default_timeout(60000)
    page.goto(cluster_server + "#/lab/inc.service-selector-503")
    page.wait_for_selector(".pager-alert")
    expect(page.locator(".site-foot")).to_contain_text("Live cluster")
    expect(page.get_by_test_id("preflight")).to_contain_text("Ready to run here")  # approved training cluster, requirements met
    page.get_by_test_id("prepare").click()
    expect(page.locator(".env-msg")).to_contain_text("incident is live", timeout=120000)
    page.get_by_test_id("start-investigating").click()
    page.locator(".lesson-step [data-testid=run-live]").nth(1).click()
    expect(page.locator(".lesson-step .screen.live").first).to_contain_text("live")
    page.get_by_role("button", name="I have a theory").click()
    page.get_by_test_id("reveal").click()
    fix = page.locator(".debrief-full .cmdblock").first
    fix.get_by_test_id("run-live").click()
    fix.get_by_test_id("confirm-run").click()
    expect(fix.locator(".screen.live")).to_contain_text("service/web selector updated")
    for _ in range(20):
        page.get_by_test_id("verify").click()
        page.wait_for_timeout(2500)
        if page.locator(".env .checks .pill.ok").count():
            break
    expect(page.locator(".env .checks")).to_contain_text("Verified")
    page.get_by_role("button", name="Clean up").click()
    # clean means the API server confirmed every object this run created is gone, not that a delete was sent
    expect(page.locator(".env-msg")).to_contain_text("API server confirmed", timeout=150000)
    expect(page.get_by_test_id("cleanup-report")).to_contain_text("clean (verified)")
