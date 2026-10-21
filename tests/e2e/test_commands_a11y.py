"""Accessibility of the command explanations and the setup guide (axe-core, serious and critical rules)."""
import pytest

from academy import config
from addresses import lesson_url

AXE = config.ROOT / "frontend" / "node_modules" / "axe-core" / "axe.min.js"
INJECTS_SCRIPTS = True  # axe-core is added with a <script> tag (see conftest.py)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_setup_guide_and_open_explanation_have_no_serious_axe_violations(browser, static_site, theme):
    if not AXE.exists():
        pytest.skip("axe-core not installed (cd frontend && npm ci)")
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    ctx.add_init_script(f"try {{ localStorage.setItem('osa.theme', '{theme}') }} catch (e) {{}}")
    pg = ctx.new_page()
    problems = []
    for path in ("/setup", lesson_url("d.routes-tls")):
        pg.goto(static_site.rstrip("/") + path)
        pg.wait_for_selector("main .page:not(:has(.sk-page))")
        for toggle in pg.get_by_test_id("understand-toggle").all():
            toggle.click()
        pg.wait_for_timeout(400)
        pg.add_script_tag(path=str(AXE))
        res = pg.evaluate("async () => (await axe.run(document, {resultTypes: ['violations']})).violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => ({id: v.id, n: v.nodes.length, ex: v.nodes.slice(0, 3).map(n => n.target.join(' '))}))")
        problems += [f"{path} {v['id']} x{v['n']}: {v['ex']}" for v in res]
    ctx.close()
    assert not problems, "\n".join(problems)
