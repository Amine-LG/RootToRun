"""A recorded grader attempt must not tell an independent learner what to repair."""
from playwright.sync_api import expect

from addresses import lab_url


def test_trial_descriptions_follow_solution_reveal_and_restart(page, static_site):
    page.goto(static_site.rstrip("/") + lab_url("ch.recover-and-scale"))
    page.locator(".ch-evidence summary").click()
    table = page.locator(".ch-trials")
    rows = table.locator("tbody tr")
    expect(rows.first).to_contain_text("Recorded attempt 1")
    data = page.request.get(static_site + "data/en/labs/ch.recover-and-scale.reveal.json").json()
    titles = [t["title"] for t in data["trials"]]
    assert titles and all(titles), "exercise an actual recorded description, not an empty fixture"

    def measured():
        return [(r.locator(".pill").inner_text(), r.locator("td").nth(1).inner_text(),
                 r.locator("td").nth(2).inner_text()) for r in rows.all()]

    before = measured()
    for title in titles:
        expect(table).not_to_contain_text(title)
    page.get_by_test_id("reveal").click()
    # the solution is fetched when asked for: on a busy CI runner (three browsers, two CPUs) that took over 5 s once
    expect(page.locator(".ch-solution")).to_be_visible(timeout=20_000)
    for title in titles:
        expect(table).to_contain_text(title)
    assert measured() == before

    # A new attempt must not inherit the previous attempt's solution descriptions.
    page.get_by_test_id("restart-attempt").click()
    expect(page.locator(".ch-solution")).to_have_count(0)
    page.locator(".ch-evidence summary").click()
    expect(rows.first).to_contain_text("Recorded attempt 1")
    for title in titles:
        expect(table).not_to_contain_text(title)
    assert measured() == before
    assert page.errors == []
