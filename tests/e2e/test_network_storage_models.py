"""Networking and storage, diagrams and models, in a browser (static site, no cluster).

The storage model reclaims a Released volume when its policy is patched to Delete, as the lesson e.storage recorded on
a real cluster (it used to leave it Released forever). The storage diagram frames only the pod and its claim as the
project (it used to put the PV in a "Storage back-end" box). The NetworkPolicy diagram draws every caller as a
connection and matches the lesson on the router namespaces and DNS port."""
import re

from playwright.sync_api import expect


def lit(page):
    return sorted(page.evaluate("[...document.querySelectorAll('.fd-node:not(.dim)')].map(e => e.dataset.nodeId)"))


def open_diagram(page, site, did):
    page.set_viewport_size({'width': 1440, 'height': 900})
    page.goto(site.rstrip('/') + f'/studio/diagram/{did}')
    page.wait_for_selector('.fd-node', state='attached')


def test_storage_model_reclaims_a_released_volume_patched_to_delete(page, static_site):
    page.goto(static_site.rstrip('/') + '/studio/model/storage')
    page.get_by_test_id('sim-skip').click()
    page.locator('label:has(input[value=Retain])').click()
    page.get_by_role('button', name='Create PVC data').click()
    page.get_by_role('button', name='Create pod app-1').click()
    page.get_by_role('button', name='oc delete pod app-1').click()
    page.get_by_role('button', name='oc delete pvc data').click()
    pv = page.locator('.sim-obj[data-kind=pv]')
    expect(pv).to_contain_text('Released')
    expect(page.locator('.sim-disk')).to_contain_text('orders.db')
    pv.get_by_role('button', name='set reclaim Delete').click()
    expect(page.locator('.sim-obj[data-kind=pv]')).to_have_count(0)
    expect(page.locator('.sim-disk')).to_have_attribute('data-state', 'deleted')
    expect(page.locator('.sim-log-wrap')).to_contain_text('Released volume')


def test_storage_diagram_frames_the_project_and_explains_the_pv(page, static_site):
    open_diagram(page, static_site, 'storage')
    expect(page.locator('.fd-zone-label')).to_have_text(['Your project'])
    page.locator('.fd-node[data-node-id="pv"]').click()
    inspector = page.locator('.graph-inspector')
    expect(inspector).to_contain_text('not part of any project')
    expect(inspector).to_contain_text('represents')
    assert lit(page) == ['csi', 'disk', 'pv', 'pvc']
    page.locator('.fd-node[data-node-id="pvc"]').click()
    expect(inspector).to_contain_text('allowVolumeExpansion: true')


def test_networkpolicy_diagram_callers_are_connections(page, static_site):
    open_diagram(page, static_site, 'networkpolicy')
    for frm in ['router', 'same', 'other']:
        expect(page.locator(f'.fd-edge[data-from="{frm}"][data-to="target"]')).to_have_class(re.compile(r'\bflow\b'))
    page.locator('.fd-node[data-node-id="router"]').click()
    inspector = page.locator('.graph-inspector')
    expect(inspector).to_contain_text('openshift-host-network')
    page.locator('.fd-node[data-node-id="dns"]').click()
    expect(inspector).to_contain_text('5353')
    expect(page.locator('.fd-caption')).to_contain_text('AdminNetworkPolicy can deny')


def test_request_path_route_explains_tls_terminations(page, static_site):
    open_diagram(page, static_site, 'request-path')
    page.locator('.fd-node[data-node-id="route"]').click()
    inspector = page.locator('.graph-inspector')
    for term in ['edge', 'passthrough', 're-encrypt']:
        expect(inspector.locator('li', has_text=term)).to_have_count(1)
    assert lit(page) == ['route', 'router', 'svc']
