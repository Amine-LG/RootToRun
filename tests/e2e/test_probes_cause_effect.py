"""The Probes model shows cause and effect at the time cursor: which probe failed and why, what that did to the
container and to Service traffic, and the recovery. Readiness failures take the pod out of traffic without a
restart; a liveness probe that checks the database kills and restarts the container. Static site, no cluster."""
from playwright.sync_api import expect


def set_time(page, t):
    page.evaluate(
        "t => { const r = document.querySelector('.sim-scrub input[type=range]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(r, String(t)); r.dispatchEvent(new Event('input', {bubbles: true})) }",
        t,
    )


def test_probes_show_which_probe_failed_and_what_it_did(page, static_site):
    page.goto(static_site.rstrip("/") + "/studio/model/probes")
    page.get_by_test_id("sim-skip").click()
    now, story = page.get_by_test_id("probes-now"), page.get_by_test_id("probes-story")
    # before the outage: everything passes and the Service sends traffic to the pod
    set_time(page, 50)
    expect(story).to_contain_text("receives Service traffic")
    expect(now.get_by_test_id("now-readiness")).to_contain_text("200 OK")
    # the database is down: /ready answers 503 three times in a row, the pod is NotReady, no traffic, no restart
    set_time(page, 85)
    expect(now.get_by_test_id("now-readiness")).to_contain_text("503 · database down")
    expect(now.get_by_test_id("now-liveness")).to_contain_text("200 OK")  # /healthz does not check the database
    expect(now).to_contain_text("Running · NotReady")
    expect(now).to_contain_text("no traffic: the pod is not Ready")
    expect(story).to_contain_text("a readiness failure never restarts it")
    # the database is back: Ready again, traffic again
    set_time(page, 125)
    expect(story).to_contain_text("passes again now the database is back")
    expect(now).to_contain_text("requests reach the pod")
    # the anti-pattern: /healthz checks the database, so liveness kills and restarts the container
    page.locator('label:has-text("also checks the database") .sim-switch').click()
    set_time(page, 84)
    expect(story).to_contain_text("liveness probe (/healthz) failed 3 times in a row (database down), so the kubelet killed and restarted the container")
    expect(now).to_contain_text("restart 1")
    set_time(page, 92)
    expect(now.get_by_test_id("now-liveness")).to_contain_text("503 · database down")
    expect(story).to_contain_text("at 3 the kubelet kills the container")
