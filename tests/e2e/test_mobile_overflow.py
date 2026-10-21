"""Every lesson (shown whole), lab, incident, challenge and diagnostic fits a 390 px phone: no horizontal page scroll.
Long tables and code scroll inside their own boxes; buttons that carry a title wrap. One test per page group."""
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
def test_no_page_is_wider_than_a_phone(browser, static_site, group):
    site = static_site.rstrip("/")
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    routes = pages_of(curriculum(page, site), group)
    assert routes, group
    wide = []
    for r in routes:
        page.goto(site + r)
        page.wait_for_selector("main .page:not(:has(.sk-page))")
        w = page.evaluate("document.documentElement.scrollWidth")
        if w > 390:
            wide.append((r, w))
    ctx.close()
    assert not wide, wide
