"""Lessons written as a teaching flow are read as one article: every section on the page, a contents list that
jumps to headings and follows the reading position, typed-command practice that can be retried after the solution is
shown, and look-back questions that name the lesson they come from. Static site, no cluster."""
import json
import re

import pytest

from playwright.sync_api import expect
from addresses import TRACKS, lessons_of, lesson_url


def open_(page, site, route):
    page.goto(site.rstrip("/") + route)
    page.wait_for_selector("[data-testid=flow-step]")


def step(page, sid):
    return page.locator(f"[data-step='{sid}']")


def header_bottom(page):
    """The bottom of the sticky chrome over the page: the site header and, on wide screens, the lesson's page bar."""
    return page.evaluate("""Math.max(...[...document.querySelectorAll('.topbar, [data-testid=page-bar]')]
        .filter(e => ['sticky', 'fixed'].includes(getComputedStyle(e).position)).map(e => e.getBoundingClientRect().bottom))""")


def top_of(page, sel):
    return page.evaluate(f"document.querySelector({json.dumps(sel)}).getBoundingClientRect().top")


def settle(page, frames=10):
    """Waits until the page has stopped scrolling: the scroll position unchanged over `frames` consecutive animation
    frames (a fixed sleep was too short on a loaded machine and needlessly long on a fast one). Gives up after 5 s."""
    page.evaluate("""(n) => new Promise(done => {
        let last = scrollY, same = 0, start = performance.now()
        const tick = () => {
            if (scrollY === last) same++; else { same = 0; last = scrollY }
            if (same >= n || performance.now() - start > 5000) done(); else requestAnimationFrame(tick)
        }
        requestAnimationFrame(tick)
    })""", frames)


def test_a_beginner_starts_at_the_first_lesson_with_nothing_assumed(page, static_site):
    page.goto(static_site.rstrip("/") + "/")
    page.get_by_test_id("route-beginner").click()
    page.get_by_test_id("start-learning").click()
    page.wait_for_url(re.compile(re.escape(lesson_url("lx.first-steps")) + "$"))
    page.wait_for_selector("[data-testid=flow-step]")
    text = page.locator(".lesson-article").inner_text()
    assert not re.search(r"look back|last lesson|previous lesson|earlier lesson", text, re.I), "the first lesson refers to a lesson before it"
    expect(page.get_by_test_id("recall-from")).to_have_count(0)
    expect(page.locator(".lesson-h h1")).to_contain_text("Your first minutes in a shell")
    assert page.errors == []


def test_the_whole_lesson_is_on_the_page_without_continue_buttons(page, static_site):
    from academy import curriculum

    lesson = curriculum.load("en")["lessons"]["lx.first-steps"]
    open_(page, static_site, lesson_url("lx.first-steps"))
    expect(page.get_by_test_id("flow-step")).to_have_count(len(lesson.flow) + 1)  # every step, then the summary
    titled = [s for s in lesson.flow if s.kind == "teach" and s.title]
    expect(page.get_by_test_id("toc-link")).to_have_count(len(titled) + 1)  # each section, and the summary
    for s in titled:
        expect(page.locator(f"section#{s.id} h2")).to_have_text(s.title)
    expect(page.get_by_test_id("flow-continue")).to_have_count(0)
    expect(page.get_by_test_id("flow-skip")).to_have_count(0)
    # the last section is reachable by ordinary scrolling
    page.mouse.move(640, 400)
    for _ in range(40):
        page.mouse.wheel(0, 3000)
    page.wait_for_timeout(300)
    expect(page.get_by_test_id("lesson-done")).to_be_in_viewport()
    assert page.errors == []


def test_contents_link_shows_the_heading_below_the_header_and_back_returns(page, static_site):
    open_(page, static_site, lesson_url("lx.first-steps"))
    page.mouse.move(640, 400)
    page.mouse.wheel(0, 600)
    settle(page)
    y0 = page.evaluate("scrollY")
    link = page.get_by_test_id("toc-link").filter(has_text="Going up a level")
    link.click()
    page.wait_for_url("**#going-up")
    settle(page)  # let the jump finish; then nothing may move any more
    hb = header_bottom(page)
    t1 = top_of(page, "section#going-up")
    at_end = page.evaluate("Math.ceil(scrollY + innerHeight) >= document.documentElement.scrollHeight")
    assert hb <= t1 and (t1 <= hb + 40 or at_end), f"heading not right under the header: header {hb}, heading {t1}"
    page.wait_for_timeout(600)
    assert abs(top_of(page, "section#going-up") - t1) < 1, "the page moved again after the jump"
    assert page.url.endswith("#going-up")
    expect(link).to_have_attribute("aria-current", "location")
    # a section above, then the same section again: always the heading, never the bottom of the section
    page.get_by_test_id("toc-link").filter(has_text="Where am I?").click()
    page.wait_for_url("**#one-place")
    settle(page)
    t2 = top_of(page, "section#one-place")
    assert header_bottom(page) <= t2 <= header_bottom(page) + 40
    page.go_back()
    page.wait_for_url("**#going-up")
    settle(page)
    assert abs(top_of(page, "section#going-up") - t1) < 2, "Back did not return to the previous heading"
    page.go_back()
    page.wait_for_url(lambda u: "#" not in u)
    settle(page)
    assert abs(page.evaluate("scrollY") - y0) < 2, "Back did not return to where the reader was"
    assert page.errors == []


def test_the_active_section_follows_ordinary_scrolling(page, static_site):
    open_(page, static_site, lesson_url("lx.first-steps"))
    page.evaluate("document.getElementById('paths-start-here').scrollIntoView({block: 'start'})")
    page.mouse.wheel(0, 1)
    page.wait_for_timeout(300)
    expect(page.get_by_test_id("toc-link").filter(has_text="Names are looked up from where you are")).to_have_attribute("aria-current", "location")


def test_next_lesson_opens_at_its_beginning(page, static_site):
    open_(page, static_site, lesson_url("lx.first-steps"))
    page.mouse.move(640, 400)
    for _ in range(40):
        page.mouse.wheel(0, 3000)
    page.wait_for_timeout(300)
    page.get_by_test_id("lesson-done").click()
    page.get_by_test_id("next-lesson").click()
    page.wait_for_url(re.compile(re.escape(lesson_url("lx.shell-basics")) + "$"))
    page.wait_for_selector("[data-testid=flow-step]")
    page.wait_for_timeout(500)
    assert page.evaluate("scrollY") == 0, "the next lesson did not open at its top"
    expect(page.locator(".lesson-h h1")).to_be_in_viewport()
    assert page.errors == []


def test_a_look_back_names_the_lesson_it_comes_from(page, static_site):
    open_(page, static_site, lesson_url("lx.shell-basics"))
    note = page.get_by_test_id("recall-from").first
    expect(note).to_contain_text("Your first minutes in a shell")
    expect(note).to_contain_text("not opened it")  # a fresh browser has not been through lesson 1
    expect(note.locator("a")).to_have_attribute("href", lesson_url("lx.first-steps"))
    open_(page, static_site, lesson_url("lx.first-steps"))
    open_(page, static_site, lesson_url("lx.shell-basics"))
    expect(page.get_by_test_id("recall-from").first).not_to_contain_text("not opened it")


def test_the_rejected_ls_variants_are_answered_correctly(page, static_site):
    open_(page, static_site, lesson_url("lx.shell-basics"))
    task = step(page, "try:try-la")
    expect(task).to_contain_text("You are in the practice directory")
    field = task.get_by_test_id("try-input")
    for wrong in ["ls -la practice", "ls practice -la"]:
        field.fill(wrong)
        task.get_by_test_id("try-check").click()
        expect(task.get_by_test_id("try-hint")).to_contain_text("is where you are")
    for right in ["ls -la", "ls -al", "ls -l -a", "ls  -a  -l"]:
        field.fill(right)
        task.get_by_test_id("try-check").click()
        expect(task.get_by_test_id("try-ok")).to_contain_text("does it")
    assert page.errors == []


def test_typed_practice_can_be_retried_after_the_solution_is_shown(page, static_site):
    open_(page, static_site, lesson_url("lx.first-steps"))
    task = step(page, "try:try-cd")
    task.get_by_test_id("try-input").fill("cd /notes")
    task.get_by_test_id("try-check").click()
    expect(task.get_by_test_id("try-hint")).to_contain_text("starts from the root")
    task.get_by_test_id("try-show").click()
    expect(task.get_by_test_id("try-status")).to_contain_text("Solution shown")
    expect(task.get_by_test_id("demo")).to_contain_text("/notes")
    # the field is still there: the learner keeps experimenting
    task.get_by_test_id("try-input").fill("cd ./notes/")
    task.get_by_test_id("try-check").click()
    expect(task.get_by_test_id("try-ok")).to_contain_text("does it")
    task.get_by_test_id("try-input").fill("cd notes/notes")
    task.get_by_test_id("try-check").click()
    expect(task.get_by_test_id("try-hint")).to_be_visible()
    rec = page.evaluate("JSON.parse(localStorage.getItem('osa.progress.v2')).predictions")["try:lx.first-steps:try-cd"]
    assert rec["first"]["ok"] is False  # helped: not counted as solved independently
    assert page.errors == []


def test_a_hint_is_available_before_any_attempt_and_counts_as_help(page, static_site):
    open_(page, static_site, lesson_url("lx.files-text"))
    task = step(page, "try:try-mkdir")
    task.get_by_test_id("try-hint-btn").click()
    expect(task.get_by_test_id("try-hint")).to_contain_text("both names")
    expect(task.get_by_test_id("try-input")).to_be_focused()  # Hint went away; focus did not fall to the page
    task.get_by_test_id("try-input").fill("mkdir archive old")
    task.get_by_test_id("try-check").click()
    expect(task.get_by_test_id("try-status")).to_contain_text("with hints")
    # a reload keeps the honest outcome: solved with help, neither open again nor solved on one's own
    page.reload()
    task = step(page, "try:try-mkdir")
    expect(task.get_by_test_id("try-status")).to_contain_text("with hints")


def test_a_shown_solution_stays_shown_after_retyping_and_reloading(page, static_site):
    open_(page, static_site, lesson_url("lx.first-steps"))
    task = step(page, "try:try-cd")
    task.get_by_test_id("try-input").fill("cd /notes")
    task.get_by_test_id("try-check").click()
    task.get_by_test_id("try-show").click()
    expect(task.get_by_test_id("try-result")).to_be_focused()
    task.get_by_test_id("try-input").fill("cd notes")
    task.get_by_test_id("try-check").click()
    expect(task.get_by_test_id("try-ok")).to_be_visible()
    page.reload()
    task = step(page, "try:try-cd")
    expect(task.get_by_test_id("try-status")).to_contain_text("Solution shown")


def test_order_task_marks_wrong_positions_and_can_show_the_order(page, static_site):
    open_(page, static_site, lesson_url("lx.files-text"))
    task = step(page, "order:order-cleanup")
    items = task.get_by_test_id("order-item")
    expect(items).to_have_count(4)
    task.get_by_test_id("order-check").click()
    expect(task.locator(".order-list li.bad")).not_to_have_count(0)
    task.get_by_test_id("order-show").click()
    expect(items.first).to_contain_text("ls notes")
    expect(items.last).to_contain_text("rm -r notes")


def test_kubernetes_recordings_name_the_client_and_cluster(page, static_site):
    open_(page, static_site, lesson_url("a.what-kubernetes-does"))
    demo = page.get_by_test_id("demo").first
    expect(demo).to_contain_text(re.compile(r"kubectl v1\.\d+\.\d+ on OpenShift Local \(Kubernetes v1\.\d+\.\d+\)"))
    for text in page.locator(".demo-cmd").all_inner_texts():
        assert not re.match(r"[$>]\s*oc\s", text), text


def test_no_linux_lesson_mentions_platform_tools(static_site):
    """Linux lessons teach Linux: no oc, kubectl or pods in their steps (the teaching standard, rule 7)."""
    from academy import curriculum

    d = curriculum.load("en")
    linux = [l for t in d["tracks"].values() if t.id == "linux" for m in t.modules for l in [d["lessons"][x] for x in d["modules"][m].lessons]]
    bad = []
    for l in linux:
        for st in l.flow or []:
            text = " ".join(str(v) for v in st.model_dump().values())
            if re.search(r"(?<![\w-])(oc|kubectl)\s+[a-z]|\bpods?\b|OpenShift|Kubernetes", text):
                bad.append(f"{l.id}/{st.id}")
    assert not bad, bad


def test_each_recording_names_the_client_that_ran_it(page, static_site):
    """In the bridge lesson, kubectl and oc commands are labelled with their own client (honest provenance)."""
    open_(page, static_site, lesson_url("k.kubectl-to-oc"))
    oc_demo = page.get_by_test_id("demo").filter(has=page.locator(".demo-cmd", has_text=re.compile(r"^\$ oc get pods"))).first
    expect(oc_demo.locator(".demo-meta")).to_contain_text("oc 4.")
    expect(oc_demo.locator(".demo-meta")).not_to_contain_text("kubectl")
    task = step(page, "try:whoami")
    task.get_by_test_id("try-input").fill("oc whoami")
    task.get_by_test_id("try-check").click()
    expect(task.locator(".demo-meta")).to_contain_text(re.compile(r"kubectl v1\.\d+\.\d+ and oc 4\."))


def test_every_lesson_is_in_one_track(page, static_site):
    """The per-track test below covers every flow lesson: none is outside the six tracks."""
    from academy import curriculum

    cur = json.loads(page.request.get(static_site.rstrip("/") + "/data/en/curriculum.json").text())
    flow = {l.id for l in curriculum.load("en")["lessons"].values() if l.flow}
    in_tracks = [i for t in TRACKS for i in lessons_of(cur, t)]
    assert len(flow) >= 100 and flow <= set(in_tracks) and len(in_tracks) == len(set(in_tracks))


@pytest.mark.parametrize("track", TRACKS)
def test_every_flow_lesson_renders_with_its_recordings(page, static_site, track):
    """Every lesson written as a flow opens with all its steps, every demonstration has its recorded output (no "not
    recorded yet" warning), with no script errors and no horizontal scroll on a phone. One test per track."""
    from academy import curriculum

    page.set_viewport_size({"width": 390, "height": 844})
    cur = json.loads(page.request.get(static_site.rstrip("/") + "/data/en/curriculum.json").text())
    flow = {l.id for l in curriculum.load("en")["lessons"].values() if l.flow}
    ids = [i for i in lessons_of(cur, track) if i in flow]
    assert ids, track
    problems = []
    for lid in ids:
        page.goto(static_site.rstrip("/") + lesson_url(lid))
        page.wait_for_selector("[data-testid=lesson-part]")
        if page.locator(".demo-meta .warn").count():
            problems.append(f"{lid}: a demonstration has no recording")
        if page.evaluate("document.documentElement.scrollWidth") > 392:
            problems.append(f"{lid}: wider than the phone screen")
    assert not problems, problems
    assert page.errors == []


def test_help_is_remembered_across_a_reload(page, static_site):
    """A hint or a wrong attempt is saved at once: reloading and then answering is still 'with hints', not 'on your own'."""
    open_(page, static_site, lesson_url("lx.files-text"))
    step(page, "try:try-mkdir").get_by_test_id("try-hint-btn").click()
    page.reload()
    page.wait_for_selector("[data-testid=flow-step]")
    task = step(page, "try:try-mkdir")
    task.get_by_test_id("try-input").fill("mkdir archive old")
    task.get_by_test_id("try-check").click()
    expect(task.get_by_test_id("try-status")).to_contain_text("with hints")


def test_a_reflection_can_be_changed_after_comparing(page, static_site):
    open_(page, static_site, lesson_url("lx.first-steps"))
    r = page.locator("[data-step='reflect:explain-error']")
    r.locator("textarea").fill("The path starts from where you are, which is already notes.")
    r.get_by_test_id("reflect-compare").click()
    r.get_by_test_id("reflect-edit").click()
    expect(r.locator("textarea")).to_have_value("The path starts from where you are, which is already notes.")


def test_skipping_the_reading_needs_first_answers_right(page, static_site):
    """Regression: answering every check wrong, then retrying each with the answer just revealed, offered to skip the
    reading ("All right") and counted the checks as right."""
    page.goto(static_site.rstrip("/") + lesson_url("lx.shell-scripts") + "?a=checks")
    qs = page.locator(".testout-view [data-testid=check]")
    qs.first.wait_for()
    for i in range(qs.count()):
        q = qs.nth(i)
        q.locator("[data-testid=choice]").first.click()
        q.get_by_test_id("check-submit").click()
        if "is-wrong" in (q.get_attribute("class") or ""):  # the right answer is now on screen: retry with it
            right = q.locator(".check-choice.answer").first.get_attribute("data-choice")
            q.get_by_role("button", name="Try again").click()
            q.locator(f"[data-testid=choice][data-choice='{right}']").click()
            q.get_by_test_id("check-submit").click()
            expect(q).to_have_class(re.compile("is-right"))
    preds = page.evaluate("JSON.parse(localStorage.getItem('osa.progress.v2')).predictions")
    assert any(not r["first"]["ok"] for r in preds.values()), "the first choice was right everywhere; pick another lesson"
    expect(page.get_by_test_id("skip-reading")).to_have_count(0)
    shown = [r for r in preds.values() if not r["first"]["ok"]]
    assert all(r["latest"].get("shown") for r in shown)  # right only after the answer was shown


def test_a_revealed_check_stays_unscored_after_a_reload(page, static_site):
    """Regression: answering wrong, reloading (a fresh component) and then answering right was counted right."""
    open_(page, static_site, lesson_url("lx.shell-basics"))
    q = page.locator("[data-testid=flow-step][data-kind=check] [data-testid=check]").first
    right = None
    for c in range(q.locator("[data-testid=choice]").count()):
        q.locator("[data-testid=choice]").nth(c).click()
        q.get_by_test_id("check-submit").click()
        if "is-wrong" in (q.get_attribute("class") or ""):
            right = q.locator(".check-choice.answer").first.get_attribute("data-choice")
            break
        page.reload()  # the first choice was right: that record is honest; try the next one on a clean question
        page.evaluate("localStorage.clear()")
        page.reload()
        q = page.locator("[data-testid=flow-step][data-kind=check] [data-testid=check]").first
    assert right is not None
    page.reload()
    q = page.locator("[data-testid=flow-step][data-kind=check] [data-testid=check]").first
    q.get_by_test_id("check-again").click()  # a reload shows the latest (wrong) answer, with Try again
    q.locator(f"[data-testid=choice][data-choice='{right}']").click()
    q.get_by_test_id("check-submit").click()
    rec = [r for r in page.evaluate("Object.values(JSON.parse(localStorage.getItem('osa.progress.v2')).predictions)") if r["n"] >= 2]
    assert rec and rec[0]["latest"]["ok"] and rec[0]["latest"].get("shown"), rec
