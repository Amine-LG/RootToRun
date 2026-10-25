"""Every lesson (shown whole), lab, incident, challenge and diagnostic renders and fits a 390 px phone: its own content
shows (the lesson's facts, the lab player, the diagnostic's introduction), not the recovery panel or a load error, with
no page or console error, and no horizontal page scroll. Long tables and code scroll inside their own boxes; buttons
that carry a title wrap. One test per page group. This is the content lane's browser check (docs/CI.md): it opens each
page as it first appears; frontend/src/lib/md.content.test.ts separately renders every string of the content through
the Markdown renderer, without the components that show them after a click."""
import json

import pytest
from addresses import PAGE_GROUPS, pages_of


def curriculum(page, site):
    return json.loads(page.request.get(site + "/data/en/curriculum.json").text())


def test_the_page_groups_cover_every_page_once(page, static_site):
    site = static_site.rstrip("/")
    cur = curriculum(page, site)
    grouped = [p for g in PAGE_GROUPS for p in pages_of(cur, g)]
    every = [x["path"] for x in cur["lessons"].values()] + [x["path"] for x in cur["labs"].values()] + \
        sorted({x["path"] for x in cur["diagnostics"].values()})
    assert sorted(grouped) == sorted(every)  # nothing left out, nothing visited twice


@pytest.mark.parametrize("group", PAGE_GROUPS)
def test_every_page_renders_and_is_no_wider_than_a_phone(page, static_site, group):
    site = static_site.rstrip("/")
    page.set_viewport_size({"width": 390, "height": 844})
    cur = curriculum(page, site)
    shows = {**{x["path"]: "[data-testid=lesson-facts]" for x in cur["lessons"].values()},
             **{x["path"]: "main .page.lab" for x in cur["labs"].values()},
             **{x["path"]: "[data-testid=diag-intro]" for x in cur["diagnostics"].values()}}
    routes = pages_of(cur, group)
    assert routes, group
    wide, broken = [], []
    for r in routes:
        page.goto(site + r)
        page.wait_for_selector("main .page:not(:has(.sk-page))")
        if page.locator("[data-testid=page-error]").count() or not page.locator(shows[r]).count():
            broken.append(r)
            continue
        w = page.evaluate("document.documentElement.scrollWidth")
        if w > 390:
            wide.append((r, w))
    assert not broken, broken
    assert page.errors == []
    assert not wide, wide
