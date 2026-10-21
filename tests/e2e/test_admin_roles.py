"""Who ran each recorded command, and whether a failure is the point of the step: the administrator's operations
show their real success as kubeadmin, an ordinary user's refusal is labelled as the expected result, and a command
recorded in the workstation shell says that it ran as an ordinary user. Static site, no cluster."""
import pytest
from playwright.sync_api import expect
from addresses import lesson_url

EXPECTED = "as this step expects"


def open_lesson(page, site, lid):
    page.goto(site.rstrip("/") + lesson_url(lid))
    expect(page.locator("h1")).to_be_visible()


def demo(page, step):
    return page.locator(f'[data-step="show:{step}"]').get_by_test_id("demo")


def test_a_deliberate_refusal_is_labelled_and_the_administrator_succeeds(page, static_site):
    open_lesson(page, static_site, "n.cluster-quotas")
    refused = demo(page, "dev-cannot-read")
    expect(refused.locator(".demo-term")).to_contain_text("developer $ oc get clusterresourcequota lab-developer")
    expect(refused.locator(".demo-term")).to_contain_text("Forbidden")
    expect(refused.get_by_test_id("expected-failure")).to_have_text(f"exit status 1, {EXPECTED}")
    created = demo(page, "crq-created")
    expect(created.locator(".demo-term")).to_contain_text("kubeadmin $ oc create clusterresourcequota")
    expect(created.locator(".demo-term")).to_contain_text("clusterresourcequota.quota.openshift.io/lab-developer created")
    expect(created.locator(".demo-meta")).to_contain_text("as kubeadmin, the cluster administrator")
    expect(created.get_by_test_id("expected-failure")).to_have_count(0)


def test_the_same_command_shows_each_identitys_own_result(page, static_site):
    # one command text, run first by developer (refused) and then by kubeadmin (accepted): each step shows its own run
    open_lesson(page, static_site, "o2.quotas-limits")
    dev = demo(page, "dev-patch")
    expect(dev.locator(".demo-term")).to_contain_text('User "developer" cannot patch resource "resourcequotas"')
    expect(dev.get_by_test_id("expected-failure")).to_be_attached()
    admin = demo(page, "admin-patch")
    expect(admin.locator(".demo-term")).to_contain_text("kubeadmin $ oc patch quota compute")
    expect(admin.locator(".demo-term")).to_contain_text("resourcequota/compute patched")
    expect(admin.locator(".demo-term")).not_to_contain_text("Forbidden")
    expect(admin.locator(".demo-meta")).not_to_contain_text("exit status")


def test_ldap_prune_really_deletes_the_retired_group(page, static_site):
    open_lesson(page, static_site, "p.ldap-group-sync")
    preview = demo(page, "prune-preview")
    expect(preview.locator(".demo-term")).to_contain_text("group/ldap-auditors")
    prune = demo(page, "prune")
    expect(prune.locator(".demo-term")).to_contain_text("kubeadmin $ oc adm prune groups")
    expect(prune.locator(".demo-term")).to_contain_text("group/ldap-auditors")
    expect(prune.locator(".demo-term")).not_to_contain_text("not enabled on this cluster")
    expect(prune.locator(".demo-meta")).not_to_contain_text("exit status")


def test_a_missing_namespace_is_shown_with_the_error_an_allowed_identity_gets(page, static_site):
    open_lesson(page, static_site, "gx.argocd-ops")
    expect(demo(page, "missing-ns").locator(".demo-term")).to_contain_text("Forbidden")
    admin = demo(page, "missing-ns-admin")
    expect(admin.locator(".demo-term")).to_contain_text("kubeadmin $ kubectl apply -f broken/configmap.yaml")
    expect(admin.locator(".demo-term")).to_contain_text('namespaces "no-such-namespace" not found')
    expect(admin.get_by_test_id("expected-failure")).to_be_attached()


@pytest.mark.parametrize("lid, step", [("f.rbac", "first-no"), ("o1.cli", "show-can-i")])
def test_a_workstation_command_on_the_cluster_says_it_ran_as_an_ordinary_user(page, static_site, lid, step):
    open_lesson(page, static_site, lid)
    expect(demo(page, step).locator(".demo-meta")).to_contain_text("as an ordinary user, not a cluster administrator")


def test_a_lab_shows_what_the_administrator_applies_first(page, static_site):
    from addresses import lab_url
    page.goto(static_site.rstrip("/") + lab_url("lab.quotas-limits"))
    page.get_by_text("Before you start").first.click()
    block = page.get_by_test_id("elevated-setup")
    expect(block.locator("summary")).to_contain_text("What a cluster administrator applies first")
    block.locator("summary").click()
    expect(block).to_contain_text("kind: ResourceQuota")
    expect(block).to_contain_text("kind: LimitRange")
