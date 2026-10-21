"""Readable addresses in the browser: old /lesson/<id> and /lab/<id> addresses (bookmarks, shared links, saved progress)
lead to the current address with their query and #anchor and no extra history entry, links written in content with ids
open readable addresses, and detail pages keep their chrome."""
import json
import re

from academy import config
from playwright.sync_api import expect

from addresses import diag_url, lab_url, lesson_url, track_url

SITE = config.SITE_NAME


def open_(page, site, route="/"):
    page.goto(site.rstrip("/") + route)
    page.wait_for_selector("main .page:not(:has(.sk-page))")


def ends_with(href):
    """The URL ends with `href`; a static host may add a slash to the path when it serves the page (a reload)."""
    path, rest = re.match(r"([^?#]*)(.*)", href).groups()
    return re.compile(re.escape(path) + "/?" + re.escape(rest) + "$")


def test_an_old_lesson_address_keeps_its_anchor_and_query_and_adds_no_history_entry(page, static_site):
    new = lesson_url("o1.cli")
    open_(page, static_site, new)
    page.wait_for_selector("[data-testid=toc-link]")
    anchor = page.locator("[data-testid=toc-link]").nth(2).get_attribute("href")
    assert anchor and anchor.startswith("#"), anchor
    open_(page, static_site, "/")
    before = page.evaluate("history.length")
    open_(page, static_site, f"/lesson/o1.cli?step=1{anchor}")
    expect(page).to_have_url(ends_with(f"{new}?step=1{anchor}"))
    expect(page).to_have_title(f"{page.locator('main h1').first.inner_text()} · {SITE}")
    target = page.locator(anchor)
    expect(target).to_be_in_viewport()
    assert page.evaluate("history.length") == before + 1, "the redirect must replace the old address, not add an entry"
    page.go_back()
    expect(page).to_have_url(re.compile(r"/$"))  # Back leaves the lesson; it never returns to the old address
    page.go_forward()
    expect(page).to_have_url(ends_with(f"{new}?step=1{anchor}"))
    assert page.errors == []


def test_old_lab_track_and_diagnostic_addresses_lead_to_their_pages(page, static_site):
    cases = {
        "/lab/inc.service-selector-503?stage=investigate": lab_url("inc.service-selector-503") + "?stage=investigate",
        "/lab/lab.rbac": lab_url("lab.rbac"),
        "/lab/ch.ship-web-app": lab_url("ch.ship-web-app"),
        "/learn/admin1": track_url("admin1"),
        "/course/start": track_url("start"),
        "/course": "/learn",
        "/diagnostic/admin1": diag_url("admin1"),
        "/challenges": "/challenges",  # Practice's list of challenges (it used to lead to the practice arena course)
    }
    assert cases["/lab/inc.service-selector-503?stage=investigate"].startswith("/incidents/")
    assert cases["/lab/ch.ship-web-app"].startswith("/challenges/") and cases["/lab/lab.rbac"].startswith("/labs/")
    for old, new in cases.items():
        open_(page, static_site, old)
        expect(page).to_have_url(ends_with(new))
        expect(page.get_by_test_id("not-found")).to_have_count(0)
    assert page.errors == []


def test_links_written_with_ids_open_readable_addresses(page, static_site):
    """Lesson content links to /lesson/o1.deploy-apps; the page shows and follows the readable address."""
    here = lesson_url("d.services-dns")
    open_(page, static_site, here)
    page.wait_for_selector("[data-testid=flow-step]")
    assert page.locator("main a[href^='/lesson/'], main a[href^='/lab/']").count() == 0
    link = page.locator(f"main a[href='{lesson_url('o1.deploy-apps')}']").first
    expect(link).to_be_attached()
    link.scroll_into_view_if_needed()
    link.click()
    expect(page).to_have_url(ends_with(lesson_url("o1.deploy-apps")))
    expect(page.locator("main h1").first).to_have_text("Deploying, exposing and scaling applications")
    page.go_back()
    expect(page).to_have_url(ends_with(here))
    page.go_forward()
    expect(page).to_have_url(ends_with(lesson_url("o1.deploy-apps")))
    assert page.errors == []


def test_a_saved_place_from_before_readable_addresses_resumes_at_the_new_one(browser, static_site):
    ctx = browser.new_context(viewport={"width": 1360, "height": 900})
    progress = {"v": 2, "days": ["2026-01-01"], "lessons": {"c.openshift-extends": {"seen": 1}},
                "last": {"href": "/lesson/c.openshift-extends", "title": "A platform run by operators", "at": 1}}
    ctx.add_init_script(f"try {{ localStorage.setItem('osa.progress.v2', {json.dumps(json.dumps(progress))}) }} catch (e) {{}}")
    try:
        page = ctx.new_page()
        open_(page, static_site, "/learn")
        expect(page.get_by_test_id("learn-continue")).to_have_attribute("href", lesson_url("c.openshift-extends"))
    finally:
        ctx.close()


def test_the_local_server_opens_old_addresses_too(page, practice_server):
    """The server returns the app for any page address; the app replaces an old one (no static export involved)."""
    open_(page, practice_server, "/lesson/o1.cli?a=checks")
    expect(page).to_have_url(ends_with(lesson_url("o1.cli") + "?a=checks"))
    open_(page, practice_server, lab_url("inc.dns-typo"))
    page.wait_for_selector(".pager-alert")
    assert "resolve" in page.title().lower()
    assert page.errors == []


def test_without_javascript_an_old_address_refreshes_to_the_new_one(browser, static_site):
    ctx = browser.new_context(java_script_enabled=False)
    try:
        page = ctx.new_page()
        page.goto(static_site.rstrip("/") + "/lesson/n.htpasswd-users")
        page.wait_for_url(re.compile(re.escape(lesson_url("n.htpasswd-users")) + "/?$"))
        expect(page.locator("main.prerender h1")).to_have_text("Manage local users")
    finally:
        ctx.close()


def test_detail_pages_keep_their_chrome_under_the_hub_address(page, static_site):
    """A lesson under /learn/<track>/ and an incident under /incidents/ are detail pages: no section tabs, as before."""
    open_(page, static_site, track_url("admin1"))
    expect(page.locator("nav.subnav")).to_be_visible()
    open_(page, static_site, lesson_url("o1.cli"))
    expect(page.locator("nav.subnav")).to_have_count(0)
    expect(page.locator(".topnav a.on")).to_have_attribute("href", "/learn")
    open_(page, static_site, lab_url("inc.dns-typo"))
    expect(page.locator("nav.subnav")).to_have_count(0)
    expect(page.locator(".topnav a.on")).to_have_attribute("href", "/labs")
    assert page.errors == []
