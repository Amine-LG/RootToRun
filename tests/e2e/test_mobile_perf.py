"""Cold-page download contracts: static hosts need no API, model code or command corpus for navigation."""
import re
from urllib.parse import urlsplit

from playwright.sync_api import expect
from addresses import lesson_url


def forbidden(url):
    path = urlsplit(url).path
    return path.endswith(('/commands.json', '/cards.json')) or bool(re.search(r'/assets/(sims|highlight)-.*\.(js|css)$', path))


def test_fresh_home_keeps_secondary_code_and_data_lazy(page, static_site):
    requests, scripts = [], []
    page.on('request', lambda r: requests.append(r.url))
    page.on('response', lambda r: scripts.append(r) if urlsplit(r.url).path.endswith('.js') else None)
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(static_site)
    expect(page.locator('#main h1')).to_be_visible()
    page.wait_for_load_state('networkidle')
    assert not [url for url in requests if forbidden(url)]
    # Budget all initial JS, including shared chunks; splitting/renaming the entry cannot bypass it.
    assert scripts
    assert sum(len(r.body()) for r in scripts) < 500_000
    page.keyboard.press('Control+k')
    expect(page.get_by_test_id('palette-input')).to_be_focused()
    page.wait_for_load_state('networkidle')
    assert not [url for url in requests if forbidden(url)], 'Opening empty search needs no corpus or models'
    page.get_by_test_id('palette-input').fill('request path')
    result = page.locator('[role=option][data-href="/studio/model/traffic"]')
    expect(result).to_be_visible()
    page.wait_for_load_state('networkidle')
    assert not [url for url in requests if re.search(r'/assets/sims-.*\.(js|css)$', url)], 'Searching model metadata must not fetch implementations'
    result.click()
    expect(page.locator('[data-sim=traffic]')).to_be_visible()
    assert page.errors == []


def test_plain_lesson_loads_cards_only_when_reading_first_finishes(page, static_site):
    requests = []
    page.set_viewport_size({'width': 390, 'height': 844})
    page.on('request', lambda r: requests.append(r.url))
    page.goto(static_site.rstrip('/') + lesson_url('d.routes-tls'))
    expect(page.get_by_test_id('lesson-done')).to_be_visible()
    page.wait_for_load_state('networkidle')
    assert not [url for url in requests if url.endswith(('/commands.json', '/cards.json')) or re.search(r'/assets/sims-.*\.(js|css)$', url)]
    # The first completion must unlock and fetch cards without a reload, even though the shell stayed mounted.
    with page.expect_response(re.compile(r'/data/en/cards\.json$')):
        page.get_by_test_id('lesson-done').click()
    cards = page.request.get(static_site.rstrip('/') + '/data/en/cards.json').json()
    expected = sum(c['source'] == 'lesson' and c['ref'] == 'd.routes-tls' for c in cards)
    assert expected > 0
    page.get_by_test_id('menu-open').click()
    expect(page.locator('.menu-sheet a[href="/review"] .count')).to_have_text(str(expected))
    assert page.errors == []
