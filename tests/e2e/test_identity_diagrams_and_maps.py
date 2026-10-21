"""The login and SCC diagrams, and the knowledge map's relations and territory headings, as a learner sees them."""
import pytest
from playwright.sync_api import expect

from test_graph import open_

LIT = "[...document.querySelectorAll('.fd-node:not(.dim)')].map(e => e.dataset.nodeId).sort()"


def test_auth_flow_api_server_authenticates_and_hands_user_and_groups_to_rbac(page, static_site):
    """The API server sits in the Authentication zone; selecting it lights the token and the groups it turns into a
    user, and the RBAC decision it hands them to. The old diagram drew it under Authorization and linked Groups straight
    to the RBAC decision."""
    page.set_viewport_size({'width': 1440, 'height': 900})
    open_(page, static_site, '/studio/diagram/auth-flow')
    page.locator('.fd-node[data-node-id="api"]').click()
    assert page.evaluate(LIT) == ['api', 'groups', 'rbac', 'token']
    expect(page.locator('.graph-inspector')).to_contain_text('401 Unauthorized')
    page.locator('.fd-node[data-node-id="groups"]').click()
    assert page.evaluate(LIT) == ['api', 'groups']
    expect(page.locator('.graph-inspector')).to_contain_text('system:authenticated:oauth')
    # the API server's box is drawn inside the Authentication frame, the RBAC decision inside the Authorization frame
    inside = page.evaluate("""() => {
      const zone = l => [...document.querySelectorAll('.fd-zone')].find(z => z.textContent.trim() === l).getBoundingClientRect()
      const box = id => document.querySelector(`.fd-node[data-node-id="${id}"]`).getBoundingClientRect()
      const within = (b, z) => b.left >= z.left && b.right <= z.right && b.top >= z.top && b.bottom <= z.bottom
      return { api: within(box('api'), zone('Authentication')), rbac: within(box('rbac'), zone('Authorization')),
               apiInAuthz: within(box('api'), zone('Authorization')) }
    }""")
    assert inside == {'api': True, 'rbac': True, 'apiInAuthz': False}, inside


def test_scc_admission_details_name_restricted_v3_and_pod_security(page, static_site):
    page.set_viewport_size({'width': 1440, 'height': 900})
    open_(page, static_site, '/studio/diagram/scc-admission')
    page.locator('.fd-node[data-node-id="avail"]').click()
    expect(page.locator('.graph-inspector')).to_contain_text('restricted-v3')
    page.locator('.fd-node[data-node-id="order"]').click()
    expect(page.locator('.graph-inspector')).to_contain_text('openshift.io/required-scc')
    page.locator('.fd-node[data-node-id="admitted"]').click()
    expect(page.locator('.graph-inspector')).to_contain_text('Pod Security admission')


def test_scc_concept_is_related_to_serviceaccounts(page, static_site):
    """An SCC is granted to a ServiceAccount: the knowledge map joins the two concepts."""
    page.set_viewport_size({'width': 1440, 'height': 900})
    page.goto(static_site.rstrip('/') + '/map?concept=sec.scc')
    page.wait_for_selector('.km-node[data-node-id="sec.serviceaccounts"]')
    expect(page.locator('[data-testid="km-details"] .km-related')).to_contain_text('ServiceAccounts and tokens')


@pytest.mark.parametrize('width', [1440, 390])
def test_knowledge_map_territory_headings_never_cover_a_box(page, static_site, width):
    """Headings get one line in the layout: long territory names used to wrap onto the first box of their column."""
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(static_site.rstrip('/') + '/map?view=all')
    page.wait_for_selector('.km-head')
    page.evaluate('document.fonts.ready')
    page.wait_for_timeout(300)
    gaps = page.evaluate("""() => {
      const nodes = [...document.querySelectorAll('.km-node')].map(n => n.getBoundingClientRect())
      return [...document.querySelectorAll('.km-head')].map(h => {
        const r = h.getBoundingClientRect()
        const below = nodes.filter(n => Math.abs(n.left - r.left) < 4 && n.top >= r.top - 1).sort((a, b) => a.top - b.top)[0]
        return [h.textContent, below ? below.top - r.bottom : 99]
      })
    }""")
    assert gaps and all(g >= 0 for _, g in gaps), gaps
    expect(page.locator('.km-legend')).not_to_contain_text('coloured edge')


def test_map_legend_levels_look_different(page, static_site):
    """Read, Checked and Practised share the accent colour, so their dots must differ in fill, not only in label."""
    page.goto(static_site.rstrip('/') + '/map')
    page.wait_for_selector('.km-legend .km-dot')
    looks = page.evaluate("""[...document.querySelectorAll('.km-legend .km-ev')].map(e => {
      const s = getComputedStyle(e.querySelector('.km-dot')); return e.className + '|' + s.borderTopColor + '|' + s.backgroundColor + '|' + s.backgroundImage })""")
    styles = [x.split('|', 1)[1] for x in looks]
    assert len(set(styles)) == len(styles), looks