"""Platform architecture diagrams in a browser: what each selection lights up and explains, and where the lessons
place them (control loop, OpenShift, enterprise, OLM, configuration)."""
from playwright.sync_api import expect

from addresses import lesson_url
from test_graph import open_

LIT = "[...document.querySelectorAll('.fd-node:not(.dim)')].map(e => e.dataset.nodeId).sort()"


def select(page, node):
    page.locator(f'.fd-node[data-node-id="{node}"]').click()
    return page.evaluate(LIT)


def test_openshift_networking_operators_deploy_the_router_and_the_pod_network(page, static_site):
    """OVN-Kubernetes used to float with no operator behind it, and the networking box did not say which operators it
    stands for."""
    page.set_viewport_size({'width': 1440, 'height': 900})
    open_(page, static_site, '/studio/diagram/openshift')
    assert select(page, 'ingress') == ['cvo', 'ingress', 'ovn', 'router']
    inspector = page.locator('.graph-inspector')
    for op in ['Ingress Operator', 'DNS Operator', 'Cluster Network Operator']:
        expect(inspector).to_contain_text(op)
    assert select(page, 'ovn') == ['ingress', 'ovn']
    select(page, 'olm')
    expect(inspector).to_contain_text('Ecosystem > Software Catalog')


def test_olm_diagram_is_olm_classic_with_the_four_install_modes(page, static_site):
    page.set_viewport_size({'width': 1440, 'height': 900})
    open_(page, static_site, '/studio/diagram/olm')
    expect(page.locator('main')).to_contain_text('Installing an operator with OLM Classic')
    assert select(page, 'og') == ['csv', 'og']
    inspector = page.locator('.graph-inspector')
    expect(inspector).to_contain_text('one other namespace')
    expect(inspector).to_contain_text('Exactly one OperatorGroup per namespace')
    select(page, 'olm')
    expect(inspector).to_contain_text('Catalog Operator')
    expect(inspector).to_contain_text('OLM Operator')


def test_enterprise_infra_nodes_are_compute_nodes_placed_by_configuration(page, static_site):
    page.set_viewport_size({'width': 1440, 'height': 900})
    open_(page, static_site, '/studio/diagram/enterprise')
    labels = page.locator('.fd-zone-label').all_inner_texts()
    assert 'Compute nodes' in labels and 'Cluster workloads' not in labels, labels
    select(page, 'infra')
    expect(page.locator('.graph-inspector')).to_contain_text('alone moves nothing')


def test_config_secrets_lesson_explores_the_two_paths_after_watching_them(page, static_site):
    """The configuration diagram was reachable only from Explore; the lesson that records both paths now embeds it,
    after the restart that shows the new variable."""
    page.set_viewport_size({'width': 1440, 'height': 900})
    open_(page, static_site, lesson_url('o1.config-secrets') + '?a=explore:diagram')
    steps = page.evaluate("[...document.querySelectorAll('[data-step]')].map(e => e.dataset.step)")
    assert steps.index('show:after-restart') < steps.index('explore:diagram') < steps.index('learn:secrets'), steps
    stage = page.locator("[data-step='explore:diagram']")
    stage.locator('.fd-node[data-node-id="env"]').click()
    expect(page.locator('.graph-inspector')).to_contain_text('oc rollout restart')
    stage.locator('.fd-node[data-node-id="files"]').click()
    expect(page.locator('.graph-inspector')).to_contain_text('subPath')


def test_first_kubernetes_lesson_shows_the_control_loop_after_the_deployment(page, static_site):
    """The lesson-level diagram used to appear, without a prompt, before the lesson had introduced the API, controllers
    or a Deployment."""
    page.set_viewport_size({'width': 1440, 'height': 900})
    open_(page, static_site, lesson_url('a.what-kubernetes-does') + '?a=explore:diagram')
    steps = page.evaluate("[...document.querySelectorAll('[data-step]')].map(e => e.dataset.step)")
    explores = [s for s in steps if s.startswith('explore:')]
    assert explores == ['explore:diagram'], steps
    assert steps.index('learn:scale') < steps.index('explore:diagram') < steps.index('learn:openshift'), steps
    stage = page.locator("[data-step='explore:diagram']")
    expect(stage).to_contain_text('What a cluster is made of')
    expect(stage.locator('.fd-node[data-node-id="sched"]')).to_be_visible()
