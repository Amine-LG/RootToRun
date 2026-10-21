"""Browser tests for the access and GitOps models: what the RBAC model lets a learner build must match what the API
server accepts, and the GitOps model must show sync status and health as separate answers."""
from playwright.sync_api import expect


def open_model(page, site, mid):
    page.goto(site.rstrip('/') + f'/studio/model/{mid}')
    root = page.locator(f'[data-sim={mid}]')
    expect(root).to_be_visible()
    root.get_by_text('Skip the prediction').click()
    return root


def test_rbac_clusterrolebinding_to_a_role_is_refused(page, static_site):
    root = open_model(page, static_site, 'rbac')
    bindings = root.get_by_text('Bindings (7 active)')
    expect(bindings).to_be_visible()
    root.get_by_role('radio', name='ClusterRoleBinding', exact=True).click()
    expect(root.get_by_text('Only a ClusterRole: a ClusterRoleBinding cannot reference a Role.')).to_be_visible()
    root.get_by_label('roleRef', exact=True).select_option('Role|team-a|pod-reader')
    root.get_by_label('subject', exact=True).select_option('User alice')
    root.get_by_role('button', name='Create binding').click()
    refused = root.get_by_test_id('rbac-binding-refused')
    expect(refused).to_contain_text('roleRef.kind: Unsupported value: "Role": supported values: "ClusterRole"')
    expect(bindings).to_be_visible()  # nothing was created
    expect(root.get_by_text('ClusterRoleBinding pod-reader-alice')).to_have_count(0)

    root.get_by_label('roleRef', exact=True).select_option('ClusterRole||node-reader')
    expect(refused).to_have_count(0)
    root.get_by_role('button', name='Create binding').click()
    expect(root.get_by_text('Bindings (8 active)')).to_be_visible()
    expect(root.get_by_text('ClusterRoleBinding node-reader-alice → ClusterRole node-reader → User alice')).to_be_visible()


def test_rbac_group_grant_reaches_every_serviceaccount_of_the_namespace(page, static_site):
    root = open_model(page, static_site, 'rbac')
    root.get_by_label('as', exact=True).select_option('sa-b-builder')
    root.get_by_label('verb', exact=True).select_option('get')
    root.get_by_label('resource', exact=True).select_option('imagestreams/layers')
    root.get_by_label('namespace', exact=True).select_option('team-a')
    banner = root.locator('.sim-banner').first
    expect(banner).to_contain_text('--as=system:serviceaccount:team-b:builder\nno')
    # the second challenge's binding: system:image-puller in team-a for the group of every team-b ServiceAccount
    root.get_by_label('in namespace', exact=True).select_option('team-a')
    root.get_by_label('roleRef', exact=True).select_option('ClusterRole||system:image-puller')
    root.get_by_label('subject', exact=True).select_option('Group system:serviceaccounts:team-b')
    root.get_by_role('button', name='Create binding').click()
    expect(banner).to_contain_text('--as=system:serviceaccount:team-b:builder\nyes')
    expect(root.get_by_text('group system:serviceaccounts:team-b', exact=True)).to_be_visible()


def test_drift_shows_sync_status_and_health_separately(page, static_site):
    root = open_model(page, static_site, 'drift')
    status = root.get_by_test_id('drift-app-status')
    expect(status).to_contain_text('Sync status Synced · health Healthy')
    root.get_by_role('button', name='oc scale deployment/web --replicas=5').click()
    root.get_by_role('button', name='Let Argo CD reconcile').click()
    expect(status).to_contain_text('Sync status OutOfSync · health Healthy')
    root.get_by_role('button', name='oc delete configmap web-config').click()
    expect(root.locator('.sim-drift-row[data-status=OutOfSync]', has_text='ConfigMap/web-config')).to_contain_text('Missing')
    expect(status).to_contain_text('health Healthy')
