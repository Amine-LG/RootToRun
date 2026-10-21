"""Independent v9 review: strict expected failures for observable learner problems.
# The strict-xfail reproductions of review v9 were turned into ordinary regression tests once each finding was fixed.

Uses the existing static_site fixture's copy/export implementation. Its HTTP
server is replaced during setup with an inert object: all browser requests are
fulfilled from those files. No socket, backend or cluster is opened.

Run: ACADEMY_CLUSTER=off .venv/bin/python -m pytest tests/e2e/test_review_v9.py -q -rx
"""
import datetime
import importlib.util
import json
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from playwright.sync_api import expect
from academy import config
from addresses import diag_url, lesson_at, lesson_url, track_url

BASE = "http://v9.local"
VIEWPORTS = [(1440, 900), (820, 1180), (390, 844)]
AXE = config.ROOT / "frontend/node_modules/axe-core/axe.min.js"


@pytest.fixture(scope="session")
def static_site(tmp_path_factory):
    """Reuse conftest::static_site, substituting interception for its socket server."""
    spec = importlib.util.spec_from_file_location("v9_original_fixtures", Path(__file__).with_name("conftest.py"))
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    captured = {}

    class InertServer:
        def __init__(self, address, handler):
            captured["root"] = Path(handler.keywords["directory"])

        def serve_forever(self):
            pass

        def shutdown(self):
            pass

    # Undo immediately after export; this does not affect other test modules.
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ACADEMY_CLUSTER", "off")
        patch.delenv("ACADEMY_E2E_SITE", raising=False)  # these tests read the exported files themselves
        patch.setattr(original, "free_port", lambda: 8765)
        patch.setattr(original.http.server, "ThreadingHTTPServer", InertServer)
        exported = original.static_site.__wrapped__(tmp_path_factory)
        next(exported)
    yield captured["root"]
    with pytest.raises(StopIteration):
        next(exported)


def make_context(browser, root, viewport=(1440, 900), theme="light", progress=None):
    ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, color_scheme=theme, reduced_motion="reduce")
    script = "if (!sessionStorage.getItem('v9-seeded')) {"
    script += f"localStorage.setItem('osa.theme', {json.dumps(theme)});"
    if progress is not None:
        script += f"localStorage.setItem('osa.progress.v2', {json.dumps(json.dumps(progress))});"
    ctx.add_init_script(script + "sessionStorage.setItem('v9-seeded','1');}")

    def serve(route):
        parsed = urlsplit(route.request.url)
        if parsed.netloc != urlsplit(BASE).netloc:
            route.abort()
            return
        target = (root / unquote(parsed.path).lstrip("/")).resolve()
        if not target.is_relative_to(root.resolve()):
            route.fulfill(status=404, body="Not found")
            return
        if target.is_dir():
            target /= "index.html"
        if target.is_file():
            route.fulfill(status=200, body=target.read_bytes(), content_type=mimetypes.guess_type(target)[0] or "application/octet-stream")
        else:
            route.fulfill(status=404, body="Not found")

    ctx.route("**/*", serve)
    return ctx


def open_page(page, path="/"):
    page.goto(BASE + path)
    page.wait_for_selector("main .page:not(:has(.sk-page))")


def old_progress():
    ago = datetime.datetime.now() - datetime.timedelta(days=40)
    timestamp = int(ago.timestamp() * 1000)
    return {"v": 2, "route": "beginner", "lessons": {"lx.shell-basics": {"seen": timestamp, "done": timestamp}},
            "days": [ago.date().isoformat()], "last": {"href": lesson_url("lx.shell-basics") + "?a=summary", "title": "How a command is built", "at": timestamp}}


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_v9_01_start_is_visible_on_first_phone_screen(browser, static_site, theme):
    ctx = make_context(browser, static_site, (390, 844), theme)
    try:
        page = ctx.new_page()
        open_page(page)
        # the hero's primary action (start the first path, or continue) is the first way to start
        box = page.locator('[data-testid="hero-start"], [data-testid="hero-continue"]').first.bounding_box()
        assert box["y"] >= 0 and box["y"] + box["height"] <= 844, box
    finally:
        ctx.close()


def test_v9_02_first_beginner_unit_fits_a_ten_minute_win(browser, static_site):
    ctx = make_context(browser, static_site, (390, 844))
    try:
        page = ctx.new_page()
        open_page(page)
        page.get_by_test_id("route-beginner").click()
        href = page.get_by_test_id("start-learning").get_attribute("href")
        open_page(page, href)
        lesson_id = lesson_at(href)
        lesson = json.loads((static_site / f"data/en/lessons/{lesson_id}.json").read_text(encoding="utf-8"))
        # one short sitting: the rewritten first lesson has more practice and an honest estimate of 12 minutes
        assert lesson["minutes"] <= 15, f"First independently finishable lesson: {lesson['minutes']} minutes"
    finally:
        ctx.close()


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_v9_03_long_break_primary_action_starts_with_recall(browser, static_site, viewport):
    ctx = make_context(browser, static_site, viewport, progress=old_progress())
    try:
        page = ctx.new_page()
        open_page(page)
        welcome = page.get_by_test_id("welcome")
        expect(welcome).to_contain_text("Welcome back after 6 weeks")
        expect(page.get_by_test_id("today-review")).to_have_attribute("href", "/review")
        expect(welcome.locator("a.btn.primary")).to_have_attribute("href", "/review")
    finally:
        ctx.close()


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_v9_04_confidence_options_have_readable_contrast(browser, static_site, viewport):
    if not AXE.is_file():
        pytest.skip("axe-core is not installed")
    ctx = make_context(browser, static_site, viewport)
    try:
        page = ctx.new_page()
        open_page(page, diag_url("admin1"))
        page.get_by_test_id("diag-start").click()
        page.get_by_test_id("diag-choice").first.click()
        expect(page.get_by_test_id("diag-conf-0")).to_be_visible()
        page.evaluate(AXE.read_text(encoding="utf-8") + ";void 0")
        violations = page.evaluate("""async () => (await axe.run(document.querySelector('.diag-conf'),
            {runOnly:{type:'rule',values:['color-contrast']}})).violations.map(v => ({id:v.id,nodes:v.nodes.map(n=>n.failureSummary)}))""")
        assert not violations, violations
    finally:
        ctx.close()


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_v9_05_lesson_radio_supports_arrow_selection(browser, static_site, viewport):
    ctx = make_context(browser, static_site, viewport)
    try:
        page = ctx.new_page()
        open_page(page, lesson_url("lx.shell-basics") + "?a=checks")
        radios = page.get_by_test_id("check").first.get_by_role("radio")
        radios.first.focus()
        page.keyboard.press("Space")
        expect(radios.first).to_have_attribute("aria-checked", "true")
        page.keyboard.press("ArrowDown")
        expect(radios.nth(1)).to_be_focused()
        expect(radios.nth(1)).to_have_attribute("aria-checked", "true")
    finally:
        ctx.close()


def test_v9_06_word_splitting_check_starts_with_a_valid_assignment(browser, static_site):
    ctx = make_context(browser, static_site)
    try:
        page = ctx.new_page()
        open_page(page, lesson_url("lx.shell-expansion") + "?a=checks")  # word splitting moved to its own lesson
        question = page.get_by_test_id("check").filter(has_text="rm -r $dir")
        expect(question).to_have_count(1)
        # The value must first be assigned as one shell word before its later
        # unquoted expansion can demonstrate the stated two-argument behaviour.
        assert "dir='old reports'" in question.inner_text() or 'dir="old reports"' in question.inner_text()
    finally:
        ctx.close()


def gap_record(root):
    diagnostic = json.loads((root / "data/en/diagnostics/admin1.json").read_text(encoding="utf-8"))
    now = int(datetime.datetime.now().timestamp() * 1000)
    target = "o1.troubleshooting"
    answers = {item["id"]: {"pick": (item["answer"] + 1) % len(item["choices"]) if item["targets"][0] == target else item["answer"],
                             "conf": 2, "ok": item["targets"][0] != target, "at": now} for item in diagnostic["items"]}
    assert any(item["targets"][0] == target for item in diagnostic["items"])
    return {"v": 2, "route": "refresh", "diagnostics": {"admin1": {"started": now, "finished": now, "answers": answers}}}, target


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_v9_07_home_session_keeps_the_diagnostic_priority(browser, static_site, viewport):
    progress, target = gap_record(static_site)
    ctx = make_context(browser, static_site, viewport, progress=progress)
    try:
        page = ctx.new_page()
        open_page(page, diag_url("admin1"))
        href = lesson_url(target)
        expect(page.get_by_test_id("diag-first")).to_have_attribute("href", href)
        open_page(page, track_url("admin1"))
        expect(page.get_by_test_id("path-plan")).to_have_attribute("href", href)
        open_page(page)
        expect(page.get_by_test_id("today-lesson")).to_have_attribute("href", href)
    finally:
        ctx.close()


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_v9_08_results_evidence_is_keyboard_scrollable(browser, static_site, viewport):
    if not AXE.is_file():
        pytest.skip("axe-core is not installed")
    progress, _ = gap_record(static_site)
    ctx = make_context(browser, static_site, viewport, progress=progress)
    try:
        page = ctx.new_page()
        open_page(page, diag_url("admin1"))
        page.locator(".diag-answers summary").click()
        page.evaluate(AXE.read_text(encoding="utf-8") + ";void 0")
        violations = page.evaluate("""async () => (await axe.run(document.querySelector('.diag-answers'),
            {runOnly:{type:'rule',values:['scrollable-region-focusable']}})).violations.map(v => ({id:v.id,nodes:v.nodes.map(n=>n.target)}))""")
        assert not violations, violations
    finally:
        ctx.close()


@pytest.mark.parametrize("viewport", VIEWPORTS)
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_v9_09_off_route_map_content_stays_readable(browser, static_site, viewport, theme):
    if not AXE.is_file():
        pytest.skip("axe-core is not installed")
    ctx = make_context(browser, static_site, viewport, theme, old_progress())
    try:
        page = ctx.new_page()
        open_page(page, "/learn")  # the map lives on the Learn page
        expect(page.get_by_test_id("map-platform").get_by_role("link")).to_have_attribute("href", track_url("platform"))
        page.evaluate(AXE.read_text(encoding="utf-8") + ";void 0")
        violations = page.evaluate("""async () => (await axe.run(document.querySelector('.jmap-wrap'),
            {runOnly:{type:'rule',values:['color-contrast']}})).violations.map(v => ({id:v.id,nodes:v.nodes.map(n=>({target:n.target,reason:n.failureSummary}))}))""")
        assert not violations, violations
    finally:
        ctx.close()


def test_v9_static_export_has_the_six_entry_destinations(static_site):
    curriculum = json.loads((static_site / "data/en/curriculum.json").read_text(encoding="utf-8"))
    assert len(curriculum["routes"]) == 6
    for route in curriculum["routes"]:
        begin = route["begin"]
        section = {"lesson": "lesson", "diagnostic": "diagnostic", "lab": "lab", "track": "learn"}[begin["kind"]]
        assert (static_site / section / begin["id"] / "index.html").is_file(), route["id"]


def test_v9_static_interception_renders_real_content(browser, static_site):
    ctx = make_context(browser, static_site)
    try:
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        open_page(page)
        expect(page.get_by_test_id("route-beginner")).to_be_visible()
        page.get_by_test_id("route-beginner").click()
        expect(page.get_by_test_id("start-learning")).to_have_attribute("href", lesson_url("lx.first-steps"))
        open_page(page, lesson_url("lx.first-steps"))
        expect(page.get_by_test_id("flow-step").first).to_be_visible()
        assert not errors
    finally:
        ctx.close()


def test_v9_10_shell_practice_identifies_the_recording_environment(browser, static_site):
    lesson = json.loads((static_site / "data/en/lessons/lx.shell-basics.json").read_text(encoding="utf-8"))
    assert lesson["host"] and "workstation" in lesson["supports"]
    ctx = make_context(browser, static_site)
    try:
        page = ctx.new_page()
        open_page(page, lesson_url("lx.shell-basics") + "?a=summary")  # a flow lesson shows its recordings inline
        demo = page.get_by_test_id("demo").first
        expect(demo).to_contain_text("workstation")
        expect(demo).not_to_contain_text("OpenShift")
    finally:
        ctx.close()


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_v9_05_review_rating_keeps_keyboard_on_the_next_card(browser, static_site, viewport):
    ctx = make_context(browser, static_site, viewport, progress=old_progress())
    try:
        page = ctx.new_page()
        open_page(page, "/review")
        page.get_by_test_id("flip").focus()
        page.keyboard.press("Enter")
        page.get_by_test_id("grade-good").focus()
        page.keyboard.press("Enter")
        expect(page.get_by_test_id("flip")).to_be_visible()
        # The app moves focus to the new question one animation frame later (Review.tsx). Pressing Tab before that
        # landed made this test fail intermittently; waiting for it also checks that the question is read first.
        expect(page.get_by_test_id("fc-q")).to_be_focused()
        page.keyboard.press("Tab")
        expect(page.get_by_test_id("flip")).to_be_focused()
    finally:
        ctx.close()


def test_v9_08_workstation_setup_output_is_keyboard_scrollable(browser, static_site):
    if not AXE.is_file():
        pytest.skip("axe-core is not installed")
    ctx = make_context(browser, static_site, (390, 844))
    try:
        page = ctx.new_page()
        open_page(page, lesson_url("lx.shell-basics") + "?a=summary")  # every recorded output of the flow is on the page
        page.evaluate(AXE.read_text(encoding="utf-8") + ";void 0")
        violations = page.evaluate("""async () => (await axe.run(document.querySelector('.lesson-flow'),
            {runOnly:{type:'rule',values:['scrollable-region-focusable']}})).violations.map(v => ({id:v.id,nodes:v.nodes.map(n=>n.target)}))""")
        assert not violations, violations
    finally:
        ctx.close()
