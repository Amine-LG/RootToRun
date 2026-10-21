"""A lesson screenshot (frontend/src/components/Screenshot.tsx): at the column's width with its space reserved, what it
is and where it was captured, and an enlarged view at full size (a modal dialog: focus inside, Escape closes, focus
back on the button without moving the page). The lesson data is intercepted to add one screenshot step, and the
image is a generated test PNG: nothing here is a real screenshot."""
import json
import struct
import zlib

import pytest
from playwright.sync_api import expect
from addresses import lesson_url
from conftest import wait_true

LID = "lx.first-steps"
W, H = 1600, 1000
IMAGE = {"src": "where.png", "alt": "The top bar of the page, with the project name at the left",
         "captured": "test fixture (generated), not a real screenshot", "url": f"/media/{LID}/where.png", "width": W, "height": H}


def png(w, h):
    raw = b"".join(b"\x00" + b"\x40\x80\xc0" * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


PNG = png(W, H)


def with_screenshot(page, site):
    def lesson(route):
        data = json.loads(route.fetch().text())
        step = {"kind": "show", "id": "console-shot", "title": "Where you are", "body": "Look at the top bar.", "run": None, "code": None,
                "image": IMAGE, "caption": "The top bar", "origin": "file", "highlight": [], "notice": "The project name is at the left."}
        data["flow"].insert(3, step)
        route.fulfill(json=data)
    page.route(f"**/data/en/lessons/{LID}.json", lesson)
    page.route(f"**/api/lessons/{LID}*", lesson)
    page.route(f"**/media/{LID}/where.png", lambda r: r.fulfill(body=PNG, content_type="image/png"))
    page.goto(site.rstrip("/") + lesson_url(LID))
    return page.get_by_test_id("screenshot")


@pytest.mark.parametrize("width", [1360, 390], ids=["desktop", "phone"])
def test_a_screenshot_has_its_size_reserved_its_words_and_an_enlarged_view(page, static_site, width):
    page.set_viewport_size({"width": width, "height": 900})
    shot = with_screenshot(page, static_site)
    img = shot.locator("img.shot-img")
    expect(img).to_have_attribute("alt", IMAGE["alt"])
    expect(img).to_have_attribute("width", str(W))
    expect(img).to_have_attribute("height", str(H))
    expect(shot).to_contain_text("The top bar")
    expect(shot.get_by_test_id("screenshot-captured")).to_have_text(IMAGE["captured"])
    shot.scroll_into_view_if_needed()
    wait_true(page, "(() => { const i = document.querySelector('img.shot-img'); return i && i.complete && i.naturalWidth > 0 })()")
    box = img.bounding_box()
    col = shot.bounding_box()
    assert box["width"] <= col["width"] + 1  # never wider than the column
    assert abs(box["height"] / box["width"] - H / W) < 0.02  # the shape is kept
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")  # no sideways scrolling on a phone
    y = page.evaluate("scrollY")
    btn = shot.get_by_test_id("screenshot-enlarge")
    expect(btn).to_have_accessible_name("Enlarge the screenshot: The top bar")
    btn.click()
    dlg = shot.get_by_test_id("screenshot-dialog")
    expect(dlg).to_be_visible()
    full = dlg.locator("img")
    expect(full).to_have_attribute("alt", IMAGE["alt"])
    assert full.evaluate("i => i.getBoundingClientRect().width") >= min(W, width) - 2  # full size: scroll to read it
    expect(dlg.get_by_role("button", name="Close")).to_be_focused()
    page.keyboard.press("Escape")
    expect(dlg).to_be_hidden()
    expect(btn).to_be_focused()
    assert abs(page.evaluate("scrollY") - y) <= 2  # closing does not move the page


def test_clicking_the_image_or_the_backdrop_opens_and_closes_it(page, static_site):
    shot = with_screenshot(page, static_site)
    shot.locator("img.shot-img").click()
    dlg = shot.get_by_test_id("screenshot-dialog")
    expect(dlg).to_be_visible()
    page.mouse.click(4, 4)  # outside the dialog's box: its backdrop
    expect(dlg).to_be_hidden()


def test_the_full_size_copy_waits_and_the_dialog_works_from_the_keyboard_without_moving_the_page(page, static_site):
    shot = with_screenshot(page, static_site)
    img = shot.locator("img.shot-img")
    img.scroll_into_view_if_needed()
    wait_true(page, "(() => { const i = document.querySelector('img.shot-img'); return i && i.complete && i.naturalWidth > 0 })()")
    dlg = shot.get_by_test_id("screenshot-dialog")
    assert dlg.locator("img").count() == 0  # not downloaded twice before anyone asks for it
    y = page.evaluate("scrollY")
    btn = shot.get_by_test_id("screenshot-enlarge")
    btn.focus()
    page.keyboard.press("Enter")
    expect(dlg).to_be_visible()
    expect(dlg).to_have_attribute("aria-label", "The top bar")
    for _ in range(4):  # focus stays in the dialog
        page.keyboard.press("Tab")
        assert dlg.evaluate("d => d.contains(document.activeElement)")
    page.mouse.move(6, 6)
    page.mouse.wheel(0, 1500)  # over the backdrop: the lesson behind must not scroll
    page.wait_for_timeout(300)
    assert abs(page.evaluate("scrollY") - y) <= 2
    page.keyboard.press("Escape")
    expect(dlg).to_be_hidden()
    expect(btn).to_be_focused()
    assert abs(page.evaluate("scrollY") - y) <= 2
    assert not page.evaluate("document.documentElement.classList.contains('shot-open')")


def test_an_image_that_cannot_be_shown_says_what_it_showed(page, static_site):
    def lesson(route):
        data = json.loads(route.fetch().text())
        data["flow"].insert(3, {"kind": "show", "id": "console-shot", "title": "", "body": "", "run": None, "code": None, "image": IMAGE,
                                "caption": "The top bar", "origin": "file", "highlight": [], "notice": ""})
        route.fulfill(json=data)
    page.route(f"**/data/en/lessons/{LID}.json", lesson)
    page.route(f"**/media/{LID}/where.png", lambda r: r.fulfill(status=404, body="not found"))
    page.goto(static_site.rstrip("/") + lesson_url(LID))
    shot = page.get_by_test_id("screenshot")
    shot.scroll_into_view_if_needed()
    expect(shot.get_by_test_id("screenshot-missing")).to_contain_text(IMAGE["alt"])
    expect(shot.get_by_test_id("screenshot-enlarge")).to_have_count(0)  # nothing to enlarge
