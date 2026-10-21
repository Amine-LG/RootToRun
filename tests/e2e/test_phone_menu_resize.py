"""Opening the phone menu makes the page behind it inert; widening the window hides the menu (CSS), so the menu must
close and the page must be usable again."""
from playwright.sync_api import expect
from conftest import wait_true


def test_widening_the_window_closes_the_phone_menu_and_frees_the_page(page, static_site):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(static_site)
    page.wait_for_selector("main h1")
    toggle = page.locator(".nav-toggle")
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    assert page.evaluate("document.querySelector('.shell > main').hasAttribute('inert')")
    page.set_viewport_size({"width": 1280, "height": 900})
    wait_true(page, "!document.querySelector('.shell > main').hasAttribute('inert')")
    assert not page.evaluate("[...document.querySelectorAll('[inert]')].length")
    link = page.locator("main a[href^='/learn']").first
    link.focus()
    expect(link).to_be_focused()  # an inert page could not take focus
