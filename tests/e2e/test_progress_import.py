"""A learner's backup from the earlier site still works: an export made by an earlier version of the site (real
progress, checked in as frontend/src/lib/progress.baseline-export.json) is
imported on the Progress page over newer work in this browser that touches the same records. After a reload the
stored facts have the literal values expected (frontend/src/lib/progress.test.ts says why) and the exercises show
them: the incident reopens at Diagnose with its draft, its replayed evidence and its hint; the newer restart of the
challenge stays a fresh attempt; the check and the order show their latest results. Static site, no cluster."""
import json

from playwright.sync_api import expect

from academy import config
from addresses import lab_url, lesson_url

BACKUP = config.ROOT / "frontend" / "src" / "lib" / "progress.baseline-export.json"
T = 1792369800000  # later than everything in the backup
LOCAL = {
    "v": 2,
    "lessons": {"d.services-dns": {"seen": T}, "lx.first-steps": {"seen": T, "done": T + 1}},
    "predictions": {"q4bbc722ea3": {"first": {"ok": True, "at": T, "pick": 0}, "latest": {"ok": True, "at": T, "pick": 0}, "n": 1}},
    "labs": {"inc.dns-typo": {"started": T, "steps": {}, "incident": {"stage": 1, "hints": 0, "replays": ["1"]}},
             "ch.bounded-cleanup": {"started": T, "steps": {}, "incident": {"stage": 0, "hints": 0}}},
    "days": ["2026-10-20"],
    "xp": 50,
}


def stored(page):
    return page.evaluate("JSON.parse(localStorage.getItem('osa.progress.v2'))")


def test_a_backup_from_the_baseline_site_imports_over_newer_work(page, static_site):
    site = static_site.rstrip("/")
    page.goto(site + "/me")
    page.evaluate(f"localStorage.setItem('osa.progress.v2', {json.dumps(json.dumps(LOCAL))})")
    page.reload()
    page.locator("input[type=file]").set_input_files(str(BACKUP))
    expect(page.locator(".me-data")).to_contain_text("4 lessons")
    page.reload()

    p = stored(page)
    assert p["lessons"]["lx.first-steps"]["done"] == T + 1  # newer work kept
    assert p["lessons"]["d.services-dns"]["done"] == 1792369718229  # and the backup's
    assert p["predictions"]["q4bbc722ea3"]["first"] == {"ok": False, "at": 1792369715326, "pick": 2}
    assert p["predictions"]["q4bbc722ea3"]["latest"] == {"ok": True, "at": T, "pick": 0}
    assert p["predictions"]["try:b.reconciliation:try-scale"]["first"]["pick"] == -2  # the hint asked for, on record
    assert p["labs"]["inc.dns-typo"]["incident"] == {
        "stage": 2, "hints": 1, "draft": "The client asks for payments-web, but the Service is called web.",
        "replays": ["0", "1", "2"], "nextHintAt": 1792369735087}
    assert p["labs"]["ch.bounded-cleanup"]["incident"] == {"stage": 0, "hints": 0, "replays": []}
    assert p["labs"]["ch.bounded-cleanup"]["revealed"] == 1792369722321 and p["labs"]["ch.bounded-cleanup"]["hints"] == 1
    assert p["labs"]["inc.broken-rollout"]["selfCheck"]["root"] is True
    assert p["days"] == ["2026-10-19", "2026-10-20"] and p["xp"] == 50

    # the incident in progress reopens where it was left: Diagnose, with the draft
    page.goto(site + lab_url("inc.dns-typo"))
    expect(page.locator("textarea.diag")).to_have_value("The client asks for payments-web, but the Service is called web.")
    expect(page.get_by_role("button", name="Diagnose", exact=False).and_(page.locator("[aria-current=step]"))).to_have_count(1)
    expect(page.locator(".hint")).to_have_count(1)  # the hint shown in this attempt
    # its evidence: the commands replayed on either side (0 and 2 in the backup, 1 here) show what to notice
    page.goto(site + lab_url("inc.dns-typo") + "?stage=investigate")
    cmds = page.locator(".inv-cmd")
    expect(cmds.first).to_be_visible()
    noticed = [cmds.nth(i).locator(".notice").count() for i in range(cmds.count())]
    assert noticed[:4] == [1, 1, 1, 0], noticed

    # the challenge restarted here after the backup was made stays a fresh attempt
    page.goto(site + lab_url("ch.bounded-cleanup"))
    expect(page.get_by_test_id("reveal")).to_be_visible()
    expect(page.locator(".ch-solution")).to_have_count(0)
    expect(page.locator(".hint")).to_have_count(0)

    # the check shows its latest answer (made here), the order its latest result (shown, from the backup)
    page.goto(site + lesson_url("b.reconciliation"))
    q = page.locator("[data-step='check:recall-chain']").get_by_test_id("check")
    expect(q.get_by_test_id("check-earlier")).to_be_visible()
    expect(q.get_by_test_id("verdict")).to_contain_text("Right")
    page.goto(site + lesson_url("f0.objects-api"))
    expect(page.get_by_test_id("order").first.get_by_test_id("order-verdict")).to_contain_text("This is the right order")
    assert page.errors == []
