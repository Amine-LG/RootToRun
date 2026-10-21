"""Phase-5 counterexamples. Static content or mocked live responses; no cluster traffic."""
import json
import re

from playwright.sync_api import expect

from academy import labs
from addresses import lab_url


def progress(**patch):
    p = {'v': 2, 'lessons': {}, 'predictions': {}, 'guesses': {}, 'explains': {}, 'labs': {}, 'cards': {}, 'confidence': {}, 'days': [], 'cmds': {}, 'xp': 0}
    p.update(patch)
    return p


def seed(page, p):
    page.add_init_script('localStorage.setItem("osa.progress.v2",' + json.dumps(json.dumps(p)) + ')')


def open_(page, site, path):
    page.goto(site.rstrip('/') + path)
    page.wait_for_selector('main .page:not(:has(.sk-page))')


def test_V10_selecting_an_already_visible_node_keeps_initial_pan(page, static_site):
    page.set_viewport_size({'width': 1440, 'height': 900})
    page.emulate_media(reduced_motion='reduce')
    open_(page, static_site, '/studio/diagram/request-path')
    page.wait_for_selector('.fd-node')
    page.evaluate('document.fonts.ready')
    page.wait_for_timeout(300)
    node = page.locator('.fd-node').first
    vp = page.locator('.fd-viewport').first
    box = node.bounding_box(); view = vp.bounding_box()
    assert view['x'] <= box['x'] and box['x'] + box['width'] <= view['x'] + view['width']
    assert view['y'] <= box['y'] and box['y'] + box['height'] <= view['y'] + view['height']
    before = page.locator('.fd-canvas').first.evaluate('e=>getComputedStyle(e).transform')
    node.click()
    expect(page.locator('.graph-inspector')).to_be_visible()
    page.wait_for_timeout(300)
    after = page.locator('.fd-canvas').first.evaluate('e=>getComputedStyle(e).transform')
    assert after == before, f'V10: visible first node moved the untouched view: {before} -> {after}'


def test_V11_profile_includes_live_only_concept_evidence(page, static_site):
    seed(page, progress(labs={'lab.rbac': {'verified': 1000, 'verdict': 'verified', 'verdictAt': 1000}}))
    open_(page, static_site, '/me')
    expect(page.locator('.stat-card.ok strong')).to_have_text('1')
    expect(page.locator('[data-testid=concept-row][data-concept="sec.rbac"]')).to_be_visible()  # V11: evidence row must not disappear


def test_V12_one_replayed_step_does_not_make_a_live_lab_a_recording(page, static_site):
    lab = labs.load()['lab.rbac']; last = lab.steps[-1]
    completed = {s.id: {'at': 1000, 'source': 'live', 'matched': True} for s in lab.steps[:-1]}
    seed(page, progress(labs={lab.id: {'stepResults': completed}}))
    page.emulate_media(reduced_motion='reduce')
    open_(page, static_site, f'{lab_url(lab.id)}?step={last.id}')
    page.locator('.lab-step').get_by_test_id('replay').click()
    expect(page.locator('.lab-step .debrief')).to_be_visible()
    p = page.evaluate('JSON.parse(localStorage.getItem("osa.progress.v2"))')
    assert not p['labs'][lab.id].get('replayed'), f'V12: one replay plus earlier live steps became a recording: {p["labs"][lab.id]}'


def test_verified_catalogue_hides_and_survives_reload(page, static_site):
    page.set_viewport_size({'width': 1440, 'height': 900})
    open_(page, static_site, '/studio/diagram/request-path')
    toggle = page.get_by_test_id('studio-list-toggle')
    expect(page.locator('.studio-list')).to_be_visible()
    toggle.click()
    expect(page.locator('.studio-list')).to_be_hidden()
    expect(page.locator('[data-testid=studio-stage]')).to_be_visible()
    page.reload()
    expect(page.locator('.studio-list')).to_be_hidden()
    page.get_by_test_id('studio-list-toggle').click()
    expect(page.locator('.studio-list')).to_be_visible()


def test_verified_R15_hint_cooldown_survives_reload(page, static_site):
    open_(page, static_site, lab_url("inc.service-selector-503") + '?stage=investigate')
    page.get_by_test_id('hint').click()
    expect(page.locator('.hint')).to_have_count(1)
    page.reload()
    expect(page.get_by_test_id('hint')).to_be_disabled()
    expect(page.locator('.hint')).to_have_count(1)
