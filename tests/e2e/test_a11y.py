"""Accessibility: axe-core finds no serious or critical violations on the main pages, in both themes."""
from pathlib import Path

import pytest

from academy import config
from addresses import lab_url, lesson_url, track_url

AXE = (config.ROOT / "frontend" / "node_modules" / "axe-core" / "axe.min.js")
PAGES = ["/", "/learn", track_url("admin1"), lesson_url("d.routes-tls"), lab_url("lab.deployment-reconciliation"), lab_url("inc.service-selector-503"),
         "/labs", "/incidents", "/terminal", "/studio/request-path", "/map", "/commands", "/handbook", "/review", "/me", "/about"]


INJECTS_SCRIPTS = True  # axe-core is added with a <script> tag (see conftest.py)

@pytest.mark.parametrize("theme", ["dark", "light"])
def test_no_serious_axe_violations(browser, static_site, theme):
    if not AXE.exists():
        pytest.skip("axe-core not installed (cd frontend && npm ci)")
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    ctx.add_init_script(f"try {{ localStorage.setItem('osa.theme', '{theme}') }} catch (e) {{}}")
    pg = ctx.new_page()
    problems = []
    for path in PAGES:
        pg.goto(static_site.rstrip("/") + path)
        pg.wait_for_selector("main .page:not(:has(.sk-page))")
        pg.wait_for_timeout(600)
        pg.add_script_tag(path=str(AXE))
        res = pg.evaluate("async () => (await axe.run(document, {resultTypes: ['violations']})).violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => ({id: v.id, n: v.nodes.length, ex: v.nodes.slice(0, 3).map(n => n.target.join(' ') + ' :: ' + (n.failureSummary || '').split('\\n').slice(1, 2).join(''))}))")
        for v in res:
            problems.append(f"{path} {v['id']} x{v['n']}: {v['ex']}")
    ctx.close()
    assert not problems, "\n".join(problems)
