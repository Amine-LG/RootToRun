"""Diagrams and the knowledge map in a browser: geometry, camera, selection, full screen, text version, phones."""
import re

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeout, expect

from academy import curriculum as _cur
from conftest import wait_true

N_CONCEPTS = len(_cur.load('en')['concepts'])
DIAGRAMS = ['control-loop', 'request-path', 'openshift', 'rbac', 'storage', 'enterprise', 'auth-flow', 'scc-admission', 'olm', 'config-injection', 'networkpolicy']

GEOMETRY = """() => {
 const root=document.querySelector('.graph-expanded') || document.querySelector('.graph-workspace');
 const vp=root.querySelector('.fd-viewport'), v=vp.getBoundingClientRect();
 const box=e=>({id:e.dataset.nodeId||e.textContent.trim().slice(0,20),x:e.offsetLeft,y:e.offsetTop,w:e.offsetWidth,h:e.offsetHeight});
 const nodes=[...root.querySelectorAll('.fd-node')].map(box), labels=[...root.querySelectorAll('.fd-edge-label')].map(box);
 const hit=(a,b)=>a.x<b.x+b.w-1&&a.x+a.w>b.x+1&&a.y<b.y+b.h-1&&a.y+a.h>b.y+1;
 const overlap=[], crossings=[];
 nodes.forEach((a,i)=>nodes.slice(i+1).forEach(b=>{if(hit(a,b))overlap.push([a.id,b.id])}));
 labels.forEach((l,i)=>{nodes.forEach(n=>{if(hit(l,n))overlap.push(['label '+l.id,n.id])}); labels.slice(i+1).forEach(m=>{if(hit(l,m))overlap.push(['label '+l.id,'label '+m.id])})});
 root.querySelectorAll('.fd-edge').forEach(e=>{const len=e.getTotalLength(); if(!len)crossings.push(['empty',e.dataset.from,e.dataset.to]);
  for(let n=1;n<200;n++){const p=e.getPointAtLength(len*n/200); nodes.filter(b=>b.id!==e.dataset.from&&b.id!==e.dataset.to).forEach(b=>{if(p.x>b.x+1&&p.x<b.x+b.w-1&&p.y>b.y+1&&p.y<b.y+b.h-1)crossings.push([e.dataset.from,e.dataset.to,b.id])})}});
 const inside=[...root.querySelectorAll('.fd-node')].filter(e=>{const r=e.getBoundingClientRect(); return r.left>=v.left-1&&r.right<=v.right+1&&r.top>=v.top-1&&r.bottom<=v.bottom+1}).length;
 const m=new DOMMatrix(getComputedStyle(root.querySelector('.fd-canvas')).transform);
 return {overlap,crossings,nodes:nodes.length,inside,scale:m.a,transform:[m.a,m.e,m.f]};
}"""


def open_(page, site, path):
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(site.rstrip('/') + path)
    page.wait_for_selector('.fd-node', state='attached')
    page.evaluate('document.fonts.ready')
    page.wait_for_timeout(250)
    return errors


@pytest.mark.parametrize('width', [1440, 390])
@pytest.mark.parametrize('diagram', DIAGRAMS)
def test_diagram_is_complete_and_clean(page, static_site, diagram, width):
    page.set_viewport_size({'width': width, 'height': 900})
    errors = open_(page, static_site, f'/studio/diagram/{diagram}')
    g = page.evaluate(GEOMETRY)
    assert not g['overlap'], g['overlap']
    assert not g['crossings'], g['crossings'][:5]
    assert g['inside'] == g['nodes'], f'{g["inside"]} of {g["nodes"]} boxes visible at the first view'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'the page scrolls sideways'
    assert not errors, errors


# A box label wraps only between words (or between the words of a CamelCase name), never inside one
MIDWORD = """() => [...document.querySelectorAll('.fd-node strong')].flatMap(s => [...s.childNodes].filter(n => n.nodeType === 3).flatMap(t => {
 const r = document.createRange(), top = i => { r.setStart(t, i); r.setEnd(t, i + 1); return r.getClientRects()[0]?.top ?? 0 };
 const out = []; for (let i = 1; i < t.length; i++) if (top(i) > top(i - 1) + 2 && !/[\\s\\/-]/.test(t.data[i - 1])) out.push(t.data.slice(0, i) + '|' + t.data.slice(i));
 return out }))"""


@pytest.mark.parametrize('width', [1440, 390])
def test_box_labels_never_break_mid_word(page, static_site, width):
    page.set_viewport_size({'width': width, 'height': 900})
    for d in DIAGRAMS:
        open_(page, static_site, f'/studio/diagram/{d}')
        assert not page.evaluate(MIDWORD), (d, page.evaluate(MIDWORD))
    open_(page, static_site, '/studio/diagram/rbac')
    assert page.locator('.fd-node[data-node-id="crb"] strong').text_content() == 'ClusterRoleBinding'  # break points add no text

def test_rbac_selection_shows_what_each_binding_can_reference(page, static_site):
    """Selecting a binding lights up exactly what it can reach: a RoleBinding reaches a Role and a ClusterRole, a
    ClusterRoleBinding only a ClusterRole. The old diagram linked groups to RoleBindings only."""
    page.set_viewport_size({'width': 1440, 'height': 900})
    open_(page, static_site, '/studio/diagram/rbac')
    lit = lambda: sorted(page.evaluate("[...document.querySelectorAll('.fd-node:not(.dim)')].map(e => e.dataset.nodeId)"))
    page.locator('.fd-node[data-node-id="crb"]').click()
    assert lit() == ['crb', 'crole', 'subject']
    expect(page.locator('.graph-inspector')).to_contain_text('never at a Role')
    page.locator('.fd-node[data-node-id="rb"]').click()
    assert lit() == ['crole', 'rb', 'role', 'subject']
    expect(page.locator('.graph-inspector')).to_contain_text('only in that project')
    page.locator('.fd-node[data-node-id="subject"]').click()
    assert lit() == ['crb', 'rb', 'subject']
    for kind in ['User', 'Group', 'ServiceAccount']:
        expect(page.locator('.graph-inspector')).to_contain_text(kind)
    labels = page.locator('.fd-edge-label').all_inner_texts()
    assert any('this project' in t.replace('\n', ' ') for t in labels), labels

def test_selection_details_and_escape(page, static_site):
    page.set_viewport_size({'width': 1440, 'height': 900})
    open_(page, static_site, '/studio/diagram/request-path')
    before = page.evaluate(GEOMETRY)['transform']
    page.locator('.fd-node[data-node-id="svc"]').click()
    inspector = page.locator('.graph-inspector')
    expect(inspector).to_contain_text('Service')
    expect(inspector).to_contain_text('selector')
    assert page.evaluate(GEOMETRY)['transform'] == before, 'selecting a visible box moved the camera'
    assert page.locator('.fd-node.dim').count() > 0 and page.locator('.fd-edge.hl').count() >= 2
    assert inspector.evaluate('e => getComputedStyle(e).position') == 'static', 'details must not float over the page'
    page.keyboard.press('Escape')
    expect(inspector).to_have_count(0)


def test_wheel_scrolls_the_page_and_ctrl_wheel_zooms(page, static_site):
    page.set_viewport_size({'width': 1440, 'height': 700})
    open_(page, static_site, '/studio/diagram/control-loop')
    vp = page.locator('.fd-viewport').first.bounding_box()
    page.mouse.move(vp['x'] + vp['width'] / 2, vp['y'] + vp['height'] / 2)
    scale, y0 = page.evaluate(GEOMETRY)['scale'], page.evaluate('scrollY')
    page.mouse.wheel(0, 300); page.wait_for_timeout(200)
    assert page.evaluate('scrollY') > y0 and page.evaluate(GEOMETRY)['scale'] == scale, 'plain wheel must scroll the page, not zoom'
    vp = page.locator('.fd-viewport').first.bounding_box(); page.mouse.move(vp['x'] + vp['width'] / 2, vp['y'] + min(vp['height'] / 2, 100))
    page.keyboard.down('Control'); page.mouse.wheel(0, -200); page.keyboard.up('Control'); page.wait_for_timeout(100)
    assert page.evaluate(GEOMETRY)['scale'] > scale
    page.get_by_role('button', name='Fit', exact=True).click()
    assert abs(page.evaluate(GEOMETRY)['scale'] - scale) < 1e-6


def test_drag_pans_and_buttons_zoom(page, static_site):
    page.set_viewport_size({'width': 1440, 'height': 900})
    open_(page, static_site, '/studio/diagram/storage')
    vp = page.locator('.fd-viewport').first.bounding_box()
    x0 = page.evaluate(GEOMETRY)['transform'][1]
    page.mouse.move(vp['x'] + 20, vp['y'] + 20); page.mouse.down(); page.mouse.move(vp['x'] + 120, vp['y'] + 40, steps=5); page.mouse.up()
    assert page.evaluate(GEOMETRY)['transform'][1] == pytest.approx(x0 + 100, abs=2)
    expect(page.locator('.graph-inspector')).to_have_count(0)  # a drag is not a click
    s = page.evaluate(GEOMETRY)['scale']
    page.get_by_role('button', name='Zoom in').click()
    # the scale is read back from the computed transform matrix, which browsers keep in single precision
    assert page.evaluate(GEOMETRY)['scale'] == pytest.approx(min(3, s * 1.25), rel=1e-4)
    page.locator('.fd-viewport').focus(); page.keyboard.press('-')
    assert page.evaluate(GEOMETRY)['scale'] == pytest.approx(s, rel=1e-4)


def test_full_screen_and_text_version(page, static_site):
    page.set_viewport_size({'width': 1280, 'height': 800})
    open_(page, static_site, '/studio/diagram/olm')
    page.get_by_role('button', name='Full screen').click()
    dialog = page.get_by_role('dialog')
    expect(dialog).to_be_visible()
    g = page.evaluate(GEOMETRY)
    assert g['inside'] == g['nodes'] and not g['crossings']
    page.keyboard.press('Escape')
    expect(dialog).to_have_count(0)
    expect(page.get_by_role('button', name='Full screen')).to_be_focused()
    page.get_by_role('button', name='Text version').click()
    items = page.locator('.graph-list > li')
    expect(items).to_have_count(9)
    expect(page.locator('.graph-list')).to_contain_text('Subscription')
    page.get_by_role('button', name='Show diagram').click()
    expect(page.locator('.fd-viewport')).to_be_visible()


def test_tab_reaches_every_box_and_keeps_it_in_view(page, static_site):
    page.set_viewport_size({'width': 1440, 'height': 900})
    open_(page, static_site, '/studio/diagram/enterprise')
    page.locator('.fd-viewport').focus()
    for _ in range(3): page.keyboard.press('+')
    in_view = """() => { const e=document.activeElement, v=document.querySelector('.fd-viewport').getBoundingClientRect(), r=e.getBoundingClientRect();
          return e.classList.contains('fd-node') && r.left>=v.left-1 && r.right<=v.right+1 && r.top>=v.top-1 && r.bottom<=v.bottom+1 }"""
    for _ in range(11):
        page.keyboard.press('Tab')
        # the view pans to the focused box after the key press; it must get there (it was checked too early under load)
        try:
            wait_true(page, in_view, timeout=5000)
        except PlaywrightTimeout:
            raise AssertionError(page.evaluate('document.activeElement.outerHTML.slice(0,120)')) from None


# ------------------------------------------------------------------ knowledge map

@pytest.mark.parametrize('width', [1440, 390])
def test_map_neighbourhood(page, static_site, width):
    page.set_viewport_size({'width': width, 'height': 900})
    errors = open_(page, static_site, '/map?concept=sec.rbac')
    focus = page.locator('.km-node.km-focus')
    expect(focus).to_contain_text('RBAC')
    g = page.evaluate(GEOMETRY)
    assert g['nodes'] == 8 and g['inside'] == 8 and not g['overlap'] and not g['crossings'], g
    assert g['scale'] >= .99, f'the neighbourhood is drawn at {g["scale"]:.0%}'
    assert page.locator('.km-edge').count() >= 7 and page.locator('marker').count() == 0  # related concepts: no arrows
    expect(page.locator('.graph-inspector')).to_contain_text('Reading: 0/')
    page.locator('.km-node[data-node-id="sec.scc"]').click()
    expect(focus).to_contain_text('Security Context Constraints')
    assert page.evaluate('location.search') == '?concept=sec.scc'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not errors, errors


def test_map_search_and_related_chips(page, static_site):
    open_(page, static_site, '/map?concept=sec.rbac')
    page.locator('#concept-search').fill('network pol')
    page.locator('#concept-search').press('Enter')
    expect(page.locator('.km-node.km-focus')).to_contain_text('NetworkPolicies')
    page.locator('.km-related .chip').first.click()
    expect(page.locator('.km-node.km-focus')).not_to_contain_text('NetworkPolicies')


@pytest.mark.parametrize('width', [1440, 390])
def test_map_everything(page, static_site, width):
    page.set_viewport_size({'width': width, 'height': 900})
    open_(page, static_site, '/map')
    page.get_by_role('button', name='Everything', exact=True).click()
    page.wait_for_timeout(300)
    g = page.evaluate(GEOMETRY)
    assert g['nodes'] == N_CONCEPTS and g['inside'] == N_CONCEPTS and not g['overlap'], g
    assert g['scale'] >= .99, 'the overview must be readable at 100%'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    node = page.locator('.km-node[data-node-id="sec.rbac"]')
    node.click()
    expect(page.locator('.graph-inspector')).to_contain_text('RBAC and effective permissions')
    assert page.locator('.km-edge.hl').count() >= 5 and page.locator('.km-node.dim').count() > 50
    page.get_by_role('button', name='Explore its neighbourhood').click()
    expect(page.locator('.km-node.km-focus')).to_contain_text('RBAC')


def test_map_territory_filter(page, static_site):
    open_(page, static_site, '/map')
    page.get_by_role('button', name='Everything', exact=True).click()
    page.locator('.xp-scope .chip', has_text=re.compile('^Linux$')).click()
    # exactly the concepts whose home module belongs to the Linux territory (read from the exported data, not frozen:
    # concepts move to the module where they are taught)
    cur = page.evaluate("fetch('/data/en/curriculum.json').then(r => r.json())")
    mods = set(next(t for t in cur['tracks'] if t['id'] == 'linux')['modules'])
    expected = sum(1 for c in cur['concepts'].values() if c.get('module') in mods)
    assert expected > 0
    expect(page.locator('.km-node')).to_have_count(expected)
    expect(page.locator('.graph-heading')).to_contain_text('Linux')
