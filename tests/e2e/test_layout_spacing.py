"""Text never runs into the controls above it. A learner found the note under Progress's Export, Import and Reset
buttons touching them: a rule pulling small notes up under their paragraph (margin-top: -6px) also caught the note that
follows the buttons. Every element with a negative top margin must still clear what is above it."""
import pytest
from playwright.sync_api import expect
from addresses import lesson_url

CLEARS = """() => [...document.querySelectorAll('main *')].flatMap(el => {
  const cs = getComputedStyle(el), prev = el.previousElementSibling
  if (parseFloat(cs.marginTop) >= 0 || !prev || !el.getClientRects().length || !prev.getClientRects().length) return []
  if (el.matches('button.linkish')) return [] // a larger touch area, not a visible box
  const gap = el.getBoundingClientRect().top - prev.getBoundingClientRect().bottom
  return gap < 4 ? [[el.className || el.tagName, prev.className || prev.tagName, Math.round(gap)]] : []
})"""


@pytest.mark.parametrize("width", [1360, 390], ids=["desktop", "phone"])
def test_the_note_under_the_progress_buttons_keeps_clear_of_them(page, static_site, width):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(static_site.rstrip("/") + "/me")
    note = page.locator("#me-reset-scope")
    expect(note).to_be_visible()
    gap = page.evaluate("""() => document.getElementById('me-reset-scope').getBoundingClientRect().top
        - Math.max(...[...document.querySelectorAll('.me-actions > *')].map(b => b.getBoundingClientRect().bottom))""")
    assert gap >= 8, gap


@pytest.mark.parametrize("width", [1360, 390], ids=["desktop", "phone"])
@pytest.mark.parametrize("path", ["/me", "/review", "/labs", "/incidents", "/challenges", lesson_url("lx.users-permissions")])
def test_nothing_is_pulled_into_what_is_above_it(page, static_site, width, path):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(static_site.rstrip("/") + path)
    page.wait_for_selector("main .page:not(:has(.sk-page))")
    page.wait_for_timeout(300)
    assert page.evaluate(CLEARS) == []
