"""Regression tests for UX defects that were found and fixed: overflow, overlap, hidden results, terminal scrolling."""
import pytest
from playwright.sync_api import expect
from addresses import lab_url, lesson_at, lesson_url, track_url

VIEWPORTS = [(390, 844), (820, 1180), (1440, 900)]
PAGES = ["/", "/learn", track_url("admin2"), lesson_url("d.routes-tls"), lab_url("lab.tls-exposure"), lab_url("inc.oomkilled"), "/labs", "/incidents",
         "/terminal", "/studio/diagram/openshift", "/map", "/commands", "/handbook", "/review", "/me", "/about"]


@pytest.mark.parametrize("w,h", VIEWPORTS)
def test_no_horizontal_page_overflow(browser, static_site, w, h):
    ctx = browser.new_context(viewport={"width": w, "height": h})
    pg = ctx.new_page()
    bad = []
    for path in PAGES:
        pg.goto(static_site.rstrip("/") + path)
        pg.wait_for_selector("main .page:not(:has(.sk-page))")
        pg.wait_for_timeout(400)
        sw = pg.evaluate("document.documentElement.scrollWidth")
        if sw > w + 1:
            bad.append(f"{path}: {sw}px")
    ctx.close()
    assert not bad, f"horizontal overflow at {w}px: {bad}"


def _overlaps(boxes_a, boxes_b=None, pad=1):
    hits = []
    pairs = [(a, b) for i, a in enumerate(boxes_a) for b in boxes_a[i + 1 :]] if boxes_b is None else [(a, b) for a in boxes_a for b in boxes_b]
    for a, b in pairs:
        if a["x"] + a["w"] - pad > b["x"] and b["x"] + b["w"] - pad > a["x"] and a["y"] + a["h"] - pad > b["y"] and b["y"] + b["h"] - pad > a["y"]:
            hits.append((a["t"], b["t"]))
    return hits


BOXES = "(sel) => [...document.querySelectorAll(sel)].map(e => { const r = e.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height, t: e.textContent.trim().slice(0, 30)} })"


@pytest.mark.parametrize("diagram", ["control-loop", "request-path", "openshift", "rbac", "storage", "enterprise"])
def test_diagram_labels_never_overlap_nodes(page, static_site, diagram):
    page.goto(static_site.rstrip("/") + f"/studio/{diagram}")
    page.wait_for_selector(".fd-node")
    page.wait_for_timeout(500)
    nodes = page.evaluate(BOXES, ".fd-node")
    labels = page.evaluate(BOXES, ".fd-edge-label")
    # every studio diagram has at least six nodes and six labelled edges: empty lists would make the overlap checks
    # below pass with nothing drawn
    assert len(nodes) >= 6 and len(labels) >= 6, (len(nodes), len(labels))
    assert not _overlaps(nodes), "nodes overlap"
    assert not _overlaps(labels, nodes), "edge labels overlap nodes"
    assert not _overlaps(labels), "edge labels overlap each other"
    # node text fits its box
    clipped = page.evaluate("[...document.querySelectorAll('.fd-node')].filter(e => e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1).map(e => e.textContent.slice(0, 30))")
    assert not clipped, clipped


@pytest.mark.parametrize("w", [390, 1440])
def test_terminal_output_wraps_without_horizontal_scroll(browser, static_site, w):
    ctx = browser.new_context(viewport={"width": w, "height": 900})
    pg = ctx.new_page()
    pg.goto(static_site.rstrip("/") + "/terminal")
    inp = pg.get_by_test_id("term-input")
    for c in ["oc describe svc web -n academy-inc-selector", "oc get pods -o wide -n academy-deploy", "oc get events -n academy-inc-pull --field-selector reason=Failed",
              "oc get node -o custom-columns=NODE:.metadata.name,CPU:.status.allocatable.cpu,MEMORY:.status.allocatable.memory"]:
        inp.fill(c)
        inp.press("Enter")
    # the four answers are really on screen before anything is measured (an empty transcript cannot overflow)
    expect(pg.locator(".tx-entry")).to_have_count(4)
    expect(pg.locator(".tx-body")).to_contain_text("academy-inc-selector")
    over = pg.evaluate("[...document.querySelectorAll('.tx-body')].map(e => e.scrollWidth - e.clientWidth)")
    assert over and all(o <= 1 for o in over), f"terminal scrolls horizontally: {over}"
    assert pg.evaluate("document.documentElement.scrollWidth") <= w + 1
    # one scroll area only: no scrollable element nested inside the transcript
    nested = pg.evaluate("[...document.querySelectorAll('.tx-body *')].filter(e => { const s = getComputedStyle(e); return (s.overflowY === 'auto' || s.overflowY === 'scroll') && e.scrollHeight > e.clientHeight + 1 }).length")
    assert nested == 0
    ctx.close()


def test_lab_output_in_steps_does_not_scroll_horizontally(browser, static_site):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    pg = ctx.new_page()
    pg.goto(static_site.rstrip("/") + lab_url("inc.broken-rollout"))
    pg.get_by_test_id("start-investigating").click()
    for b in pg.locator(".lesson-step [data-testid=replay]").all():
        b.click()
    pg.wait_for_timeout(1500)
    over = pg.evaluate("[...document.querySelectorAll('.screen-body')].map(e => e.scrollWidth - e.clientWidth)")
    assert over and all(o <= 1 for o in over), f"output blocks scroll horizontally: {over}"
    ctx.close()


def test_table_output_is_rendered_as_a_table(page, static_site):
    page.goto(static_site.rstrip("/") + "/terminal")
    inp = page.get_by_test_id("term-input")
    inp.fill("oc get pods -n academy-inc-oom")
    inp.press("Enter")
    page.wait_for_selector(".tx-table")
    assert page.locator(".tx-table th").first.inner_text().strip() == "NAME"


def test_keyboard_reaches_the_main_action(page, static_site):
    page.goto(static_site.rstrip("/") + "/")
    page.wait_for_selector("[data-testid=start-learning]")
    for _ in range(25):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.dataset.testid") == "start-learning":
            break
    else:
        pytest.fail("the primary action is not reachable with Tab within 25 presses")
    page.keyboard.press("Enter")
    page.wait_for_url(lambda u: lesson_at(u) is not None)
