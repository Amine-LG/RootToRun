"""Practice pages sit in the same frame as lessons: their content starts and ends at the frame's edges (the header's and
the page bar's), so nothing looks shifted to one side, and nothing is wider than a phone. Static site, no cluster."""
import pytest
from playwright.sync_api import expect

from addresses import lab_url, lesson_url

PAGES = [lesson_url("lx.shell-basics"), "/labs/", lab_url("lab.cli-tour"), "/incidents/", lab_url("inc.dns-typo"),
         "/challenges/", lab_url("ch.bounded-cleanup")]

EDGES = """() => {
  const frame = document.querySelector('main .page'); const fb = frame.getBoundingClientRect(); const cs = getComputedStyle(frame);
  const blocks = [...frame.children].filter(e => !e.classList.contains('page-bar') && e.offsetParent).map(e => e.getBoundingClientRect());
  return {left: fb.left + parseFloat(cs.paddingLeft), right: fb.right - parseFloat(cs.paddingRight),
          contentLeft: Math.min(...blocks.map(b => b.left)), contentRight: Math.max(...blocks.map(b => b.right)),
          overflow: document.documentElement.scrollWidth - innerWidth}
}"""


@pytest.mark.parametrize("width", [1440, 1024, 768])
def test_practice_pages_use_the_whole_frame_like_lessons(browser, static_site, width):
    page = browser.new_page(viewport={"width": width, "height": 900})
    try:
        for path in PAGES:
            page.goto(static_site.rstrip("/") + path)
            expect(page.locator("main h1")).to_be_visible()
            e = page.evaluate(EDGES)
            assert abs(e["contentLeft"] - e["left"]) <= 1, (path, width, e)
            assert abs(e["contentRight"] - e["right"]) <= 1, (path, width, e)
            assert e["overflow"] <= 0, (path, width, e)
    finally:
        page.close()


def test_practice_pages_fit_a_phone(browser, static_site):
    page = browser.new_page(viewport={"width": 375, "height": 800})
    try:
        for path in PAGES:
            page.goto(static_site.rstrip("/") + path)
            expect(page.locator("main h1")).to_be_visible()
            assert page.evaluate(EDGES)["overflow"] <= 0, path
    finally:
        page.close()
