"""The lesson's contents list marks the section being read, and only that one.

A learner found "Owners, and the administrator" marked through almost all of lx.users-permissions, scrolling down or
up. That section's id is `root`, which is also the id of the app's mount point: looked up in the whole document, the
mount point (above every reading line) was always "current", and a link to `#root` scrolled to the top of the app.
Sections are now looked up inside the article and `#id` links resolve inside the main content.
"""
import pytest
from playwright.sync_api import expect
from addresses import lesson_url

# the marked section must be on screen (below the sticky bars, measured where they stick); nothing is marked only while
# the introduction above every heading is read
SCAN = """async () => {
  const frames = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))
  const hdr = () => { let b = 0; for (const el of document.querySelectorAll('.topbar, [data-sticky]')) { const cs = getComputedStyle(el)
      if (cs.position === 'sticky' || cs.position === 'fixed') { const r = el.getBoundingClientRect(); if (r.width > innerWidth / 2) b = Math.max(b, (parseFloat(cs.top) || 0) + r.height) } } return b }
  const max = document.documentElement.scrollHeight - innerHeight, seen = new Set(), bad = []
  const ys = []; for (let y = 0; y <= max; y += 211) ys.push(y); ys.push(max)
  for (const y of [...ys, ...ys.slice().reverse()]) {
    scrollTo(0, y); await frames(); await frames()
    const a = document.querySelector('[data-testid=toc-link][aria-current]')
    const secs = [...document.querySelectorAll('.flow-col > section.lesson-part.titled')]
    if (a) {
      seen.add(a.textContent)
      const s = secs.find(x => '#' + x.id === a.getAttribute('href')), r = s && s.getBoundingClientRect()
      if (!r || r.bottom <= hdr() || r.top >= innerHeight) bad.push([y, 'marked off screen', a.textContent])
    } else if (secs.length && secs[0].getBoundingClientRect().top < hdr()) bad.push([y, 'nothing marked inside a section'])
  }
  return { bad, seen: seen.size, sections: document.querySelectorAll('[data-testid=toc-link]').length }
}"""

# each section in turn: with its heading scrolled to the top of the window (where the page can scroll that far), it is
# the section marked
EACH = """async () => {
  const frames = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))
  const hdr = () => { let b = 0; for (const el of document.querySelectorAll('.topbar, [data-sticky]')) { const cs = getComputedStyle(el)
      if (cs.position === 'sticky' || cs.position === 'fixed') { const r = el.getBoundingClientRect(); if (r.width > innerWidth / 2) b = Math.max(b, (parseFloat(cs.top) || 0) + r.height) } } return b }
  const max = document.documentElement.scrollHeight - innerHeight, wrong = []
  for (const s of document.querySelectorAll('.flow-col > section.lesson-part.titled')) {
    const y = Math.round(scrollY + s.getBoundingClientRect().top - hdr() - 8)
    // a heading the page cannot bring to the top (at the start), and the last screen, where the reading line moves down
    // so that short final sections are marked in turn: the scan above covers them
    if (y < 0 || y > max - innerHeight) continue
    scrollTo(0, y); await frames(); await frames()
    const a = document.querySelector('[data-testid=toc-link][aria-current]')
    if (a?.getAttribute('href') !== '#' + s.id) wrong.push([s.id, a?.getAttribute('href') || null])
  }
  return wrong
}"""


@pytest.fixture(params=[(1360, 900), (390, 844)], ids=["desktop", "phone"])
def sized(request, page):
    page.set_viewport_size({"width": request.param[0], "height": request.param[1]})
    return page


@pytest.mark.parametrize("lid", ["lx.users-permissions", "lx.editing", "e.storage", "lx.first-steps"])
def test_the_marked_section_is_the_one_on_screen_scrolling_down_and_up(sized, static_site, lid):
    """lx.users-permissions has a section `root`, lx.editing and e.storage a section `modes` (ids the app uses too)."""
    sized.goto(static_site.rstrip("/") + lesson_url(lid))
    expect(sized.get_by_test_id("toc-link").first).to_be_attached()
    r = sized.evaluate(SCAN)
    assert r["bad"] == [], r["bad"][:5]
    assert sized.evaluate(EACH) == []


def test_nothing_is_marked_while_the_introduction_is_read(page, static_site):
    page.goto(static_site.rstrip("/") + lesson_url("lx.users-permissions"))
    expect(page.get_by_test_id("toc-link").first).to_be_visible()
    expect(page.locator("[data-testid=toc-link][aria-current]")).to_have_count(0)


def test_the_link_to_a_section_whose_id_the_app_also_uses_goes_to_that_section(page, static_site):
    page.goto(static_site.rstrip("/") + lesson_url("lx.users-permissions"))
    link = page.get_by_test_id("toc-link").filter(has_text="Owners, and the administrator")
    link.click()
    section = page.locator(".flow-col > section#root")
    expect(section).to_be_focused()
    expect(link).to_have_attribute("aria-current", "location")
    top = section.evaluate("s => s.getBoundingClientRect().top")
    assert 0 <= top < 300, top  # the heading is at the top of the window, not the start of the page
    assert page.evaluate("scrollY") > 2000
    page.reload()  # the address keeps #root: the page opens at that section
    expect(page.get_by_test_id("toc-link").filter(has_text="Owners, and the administrator")).to_have_attribute("aria-current", "location")
    assert 0 <= page.locator(".flow-col > section#root").evaluate("s => s.getBoundingClientRect().top") < 300
