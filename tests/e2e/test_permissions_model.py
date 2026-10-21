"""Browser-only permissions model: prediction gates, editable bits, narrow layouts and accessibility."""
import pytest
from playwright.sync_api import expect

from academy import config

FILE = '/opt/app/data/state.db'
DATA = '/opt/app/data'


INJECTS_SCRIPTS = True  # axe-core is added with a <script> tag (see conftest.py)

def open_model(page, site):
    page.goto(site.rstrip('/') + '/studio/model/perms')
    root = page.locator('[data-sim=perms]')
    expect(root).to_be_visible()
    return root


def predict(root, choice='allowed'):
    root.get_by_role('button', name=f'Predict {choice}', exact=True).click()
    return root.get_by_test_id('perms-result')


def test_permissions_prediction_edits_and_validation(page, static_site):
    root = open_model(page, static_site)
    result = root.get_by_test_id('perms-result')
    expect(result).to_have_count(0)
    expect(predict(root, 'allowed')).to_contain_text('Denied (EACCES)')
    expect(result.get_by_role('list', name='Permission trace')).to_contain_text('only other bits count')

    root.get_by_label('Preset', exact=True).select_option('fixed')
    expect(result).to_have_count(0)
    expect(predict(root)).to_contain_text('Allowed')
    expect(result).to_contain_text('group')

    # Native checkbox works from the keyboard, updates octal, and hides the previous result.
    group_write = root.get_by_role('checkbox', name=f'group w: {FILE}', exact=True)
    group_write.focus()
    page.keyboard.press('Space')
    expect(root.get_by_label(f'Octal mode: {FILE}', exact=True)).to_have_value('755')
    expect(result).to_have_count(0)
    expect(predict(root, 'denied')).to_contain_text('Denied')

    mode = root.get_by_label(f'Octal mode: {FILE}', exact=True)
    mode.fill('775')
    expect(group_write).to_be_checked()
    mode.fill('888')
    expect(mode).to_have_attribute('aria-invalid', 'true')
    expect(root.get_by_role('button', name='Predict allowed', exact=True)).to_be_disabled()
    expect(result).to_have_count(0)
    mode.fill('775')
    uid = root.get_by_label('Process UID', exact=True)
    uid.fill('-1')
    expect(uid).to_have_attribute('aria-invalid', 'true')
    expect(root.get_by_role('button', name='Predict allowed', exact=True)).to_be_disabled()
    uid.fill('1000680000')
    expect(predict(root)).to_contain_text('Allowed')

    # Root still needs an execute bit, while dropped capabilities remove write bypass.
    root.get_by_label('Preset', exact=True).select_option('root')
    mode.fill('600')
    root.get_by_role('combobox', name='Operation', exact=True).select_option('execute')
    expect(predict(root, 'denied')).to_contain_text('no x bits')
    root.get_by_role('checkbox', name=f'owner x: {FILE}', exact=True).check()
    expect(predict(root)).to_contain_text('CAP_DAC_OVERRIDE')
    root.get_by_label('Preset', exact=True).select_option('root-dropped')
    expect(predict(root, 'denied')).to_contain_text('Denied')
    assert not page.errors


def test_setgid_creation_and_umask_are_explained(page, static_site):
    root = open_model(page, static_site)
    root.get_by_label('Preset', exact=True).select_option('setgid')
    result = predict(root)
    expect(result.get_by_label('New file permissions')).to_contain_text(f'-rw-rw-r-- 1002 2000 {DATA}/new.txt')
    root.get_by_text(f'Setgid: {DATA}', exact=True).click()  # users click the label; the styled track covers the input
    expect(root.get_by_role('switch', name=f'Setgid: {DATA}')).not_to_be_checked()
    expect(predict(root).get_by_label('New file permissions')).to_contain_text('1002 1002')
    root.get_by_label('Umask for creation', exact=True).fill('077')
    expect(predict(root).get_by_label('New file permissions')).to_contain_text('-rw-------')
    root.get_by_label('Preset', exact=True).select_option('umask')
    expect(predict(root, 'denied')).to_contain_text('Denied')
    # There is no saved prediction or score for this model.
    assert page.evaluate("localStorage.getItem('oa.sim.perms.predict')") is None
    assert not page.errors


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('width', [390, 1440])
def test_permissions_layout_and_accessibility(browser, static_site, theme, width):
    ctx = browser.new_context(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
    ctx.add_init_script(f"localStorage.setItem('osa.theme', '{theme}')")
    pg = ctx.new_page()
    root = open_model(pg, static_site)
    root.get_by_label('Preset', exact=True).select_option('setgid')
    predict(root)
    root.locator('.sim-scope > summary').click()
    assert pg.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    axe = config.ROOT / 'frontend/node_modules/axe-core/axe.min.js'
    if axe.exists():
        pg.add_script_tag(path=str(axe))
        violations = pg.evaluate("""async () => (await axe.run(document.querySelector('[data-sim=perms]'),
            {resultTypes: ['violations']})).violations.filter(v => ['serious', 'critical'].includes(v.impact))
            .map(v => ({id: v.id, nodes: v.nodes.map(n => ({target:n.target, why:n.failureSummary}))}))""")
        assert not violations, violations
    ctx.close()
