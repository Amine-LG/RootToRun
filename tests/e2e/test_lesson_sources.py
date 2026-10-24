"""Recording setup must be reachable before the first command, with exact copyable inputs."""
import pytest
from playwright.sync_api import expect

from addresses import lesson_url


SETTLED = """() => new Promise(done => { let last = scrollY, same = 0, start = performance.now();
    const tick = () => { if (scrollY === last) same++; else { same = 0; last = scrollY }
        if (same >= 10 || performance.now() - start > 5000) done(); else requestAnimationFrame(tick) };
    requestAnimationFrame(tick) })"""


@pytest.mark.parametrize("lid", ["ct.troubleshoot-containers", "lx.files-text", "o3.init-sidecars", "gx.openshift-gitops"])
def test_existing_sources_are_available_before_the_experiment(page, static_site, lid):
    # Intercept only the clipboard interface: the real CodeBlock/CopyButton must deliver the unmodified source.
    page.add_init_script("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async text => {window.copiedSource = text}}})")
    page.goto(static_site.rstrip("/") + lesson_url(lid))
    sources = page.get_by_test_id("lesson-sources")
    expect(sources.locator(":scope > summary")).to_be_visible()
    first_step = page.get_by_test_id("flow-step").first
    assert sources.evaluate("(e, other) => Boolean(e.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_FOLLOWING)", first_step.element_handle())
    data = page.request.get(static_site + f"data/en/lessons/{lid}.json").json()
    assert data["files"], "test a lesson with actual recording inputs"
    sources.locator(":scope > summary").click()
    expect(sources).to_contain_text("creating any parent folders first")
    expect(sources.get_by_test_id("lesson-source-file")).to_have_count(len(data["files"]))
    for name, body in data["files"].items():
        # Use the summary rather than all text; the filename also occurs in the code header.
        file = sources.get_by_test_id("lesson-source-file").filter(has=page.locator("summary", has_text=name))
        # the page may still be scrolling to show what was opened (lib/reveal.ts): click once it stands still (a click
        # during the scroll landed beside the summary in a Firefox CI run)
        page.evaluate(SETTLED)
        file.locator(":scope > summary").click()
        expect(file).to_have_attribute("open", "")
        code = file.locator("pre code")
        # under load the panel can still be settling after the click: wait (briefly) for this file's code, then compare
        for _ in range(50):
            if (code.text_content() or "").rstrip("\n") == body.rstrip("\n"):
                break
            page.wait_for_timeout(100)
        assert code.text_content().rstrip("\n") == body.rstrip("\n")
        # opening the file scrolls it into view: click Copy once the page stands still, or the click lands on the
        # Copy button of the file above it (two Firefox CI runs copied the previous file's text)
        page.evaluate(SETTLED)
        copy = file.get_by_role("button", name=f"Copy source file {name}", exact=True)
        copy.scroll_into_view_if_needed()
        page.evaluate(SETTLED)
        copy.click()
        # the copy is written asynchronously
        for _ in range(50):
            if page.evaluate("window.copiedSource") == body:
                break
            page.wait_for_timeout(100)
        assert page.evaluate("window.copiedSource") == body
    assert page.errors == []


def test_no_empty_setup_panel_or_setup_answers_in_test_out(page, static_site):
    page.goto(static_site.rstrip("/") + lesson_url("a.images-registries"))
    page.wait_for_selector("[data-testid=flow-step]")
    expect(page.get_by_test_id("lesson-sources")).to_have_count(0)
    page.goto(static_site.rstrip("/") + lesson_url("ct.troubleshoot-containers") + "?a=checks")
    page.wait_for_selector("[data-testid=check]")
    expect(page.get_by_test_id("lesson-sources")).to_have_count(0)
    assert page.errors == []


def test_sources_fit_a_phone_and_cluster_practice_names_the_environment(page, static_site):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(static_site.rstrip("/") + lesson_url("d.services-dns"))
    sources = page.get_by_test_id("lesson-sources")
    sources.locator(":scope > summary").click()
    first = sources.get_by_test_id("lesson-source-file").first
    first.locator(":scope > summary").click()
    expect(first.get_by_test_id("copy")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    practice = page.locator(".host-cmds").locator("..")
    practice.locator(":scope > summary").click()
    expect(practice).to_contain_text("Follow its environment and identity requirements")
    expect(practice).not_to_contain_text("ordinary user, not on a cluster")
    assert page.errors == []
