"""Defense in depth for what a lab applies to the learner's own cluster: setup, break, elevated_setup (admin identity)
and the YAML a command sends with `-f -`. When the lab file loads, the model refuses roles with *, escalate, bind or
impersonate, bindings to administrative, system or templated roles, bindings to system, templated or "*" subjects,
service accounts outside the lab's projects, and, for what the admin identity applies, any cluster role but view;
also inside List and Template wrappers. These rules read only what the lab says: they do not know what a cluster role
already on the cluster allows, and they do not limit commands run as admin (the learner confirms each one as it will
run, test_lab_exec_confirm.py, and the owner reviews lab content). No cluster or process is used."""
import pytest
import yaml
from pydantic import ValidationError

from academy import config, labs

BASE = yaml.safe_load((config.ROOT / "content" / "en" / "labs" / "b5-quotas-limits.yaml").read_text(encoding="utf-8"))
NS = BASE["namespace"]
GROUP = "rbac.authorization.k8s.io"


def binding(role="view", role_kind="ClusterRole", subjects=None, api_group=GROUP, namespace=None, ns=NS):
    subjects = subjects if subjects is not None else [{"kind": "ServiceAccount", "name": "app", "namespace": ns}]
    meta = {"name": "probe", **({"namespace": namespace} if namespace else {})}
    return yaml.safe_dump({"apiVersion": f"{GROUP}/v1", "kind": "RoleBinding", "metadata": meta,
                           "roleRef": {"apiGroup": api_group, "kind": role_kind, "name": role},
                           "subjects": subjects}, sort_keys=False)


def role(verbs=("get", "list"), resources=("pods",), api_groups=("",), kind="Role"):
    return yaml.safe_dump({"apiVersion": f"{GROUP}/v1", "kind": kind, "metadata": {"name": "custom"},
                           "rules": [{"apiGroups": list(api_groups), "resources": list(resources), "verbs": list(verbs)}]})


def group(name):
    return [{"kind": "Group", "apiGroup": GROUP, "name": name}]


def wrapped(doc, kind="List"):
    field = "objects" if kind == "Template" else "items"
    version = "template.openshift.io/v1" if kind == "Template" else "v1"
    return yaml.safe_dump({"apiVersion": version, "kind": kind, "metadata": {"name": "w"},
                           field: [yaml.safe_load(doc)]}, sort_keys=False)


def lab_with(field, doc):
    return labs.Lab.model_validate({**BASE, field: [*BASE.get(field, []), doc]})


def lab_with_stdin(doc, as_):
    return labs.Lab.model_validate({**BASE, "commands": [*BASE.get("commands", []),
                                                         {"cmd": "oc apply -f -", "stdin": doc, "as": as_}]})


def test_the_base_lab_and_ordinary_objects_load():
    assert labs.Lab.model_validate(BASE).elevated_setup
    for field in ("setup", "break", "elevated_setup"):
        assert lab_with(field, binding())  # the view cluster role, to a service account of the lab
    for field in ("setup", "break"):
        assert lab_with(field, role()) and lab_with(field, binding("edit"))
    assert lab_with("elevated_setup", binding("custom", role_kind="Role"))
    assert lab_with_stdin(binding("edit"), "learner") and lab_with_stdin(binding("view"), "admin")
    # a service account named without a namespace is in the binding's own namespace, the lab's (a shipped challenge)
    assert lab_with("setup", binding(subjects=[{"kind": "ServiceAccount", "name": "default"}]))
    assert lab_with_stdin(binding("custom", role_kind="Role", subjects=[{"kind": "ServiceAccount", "name": "app"}]), "admin")


def test_a_command_cannot_put_a_binding_in_another_project():
    """setup and break may not set a namespace at all; YAML a command sends may, so a binding there stays in the lab's
    projects, also with a service account named without a namespace (it would then be that other project's)."""
    for as_ in ("learner", "admin"):
        with pytest.raises(ValidationError, match="outside the lab's projects"):
            lab_with_stdin(binding("view", namespace="openshift-config"), as_)
        with pytest.raises(ValidationError, match="outside the lab's projects"):
            lab_with_stdin(binding("view", namespace="openshift-config", subjects=[{"kind": "ServiceAccount", "name": "app"}]), as_)


DANGEROUS = [
    (binding("cluster-admin"), "may not grant the role"),
    (binding("admin"), "may not grant the role"),
    (binding("system:openshift:scc:privileged"), "may not grant the role"),
    (binding("${ROLE}"), "may not grant the role"),  # a Template parameter could become any role
    (binding("view", role_kind="clusterrole"), "may not grant the role"),
    (binding("view", api_group="authorization.openshift.io"), "may not grant the role"),
    (binding(subjects=group("system:authenticated")), "may not name the subject"),
    (binding(subjects=group("System:Authenticated")), "may not name the subject"),
    (binding(subjects=group("system:serviceaccounts")), "may not name the subject"),
    (binding(subjects=group("${GROUP}")), "may not name the subject"),
    (binding(subjects=[{"kind": "User", "apiGroup": GROUP, "name": "system:anonymous"}]), "may not name the subject"),
    (binding(subjects=[{"kind": "serviceaccount", "name": "app", "namespace": NS}]), "may not name the subject"),
    (binding(subjects=[{"kind": "ServiceAccount", "name": "default", "namespace": "openshift-config"}]),
     "outside the lab's projects"),
    (role(verbs=["*"]), "may not use"),
    (role(verbs=["get", "escalate"]), "may not use"),
    (role(verbs=["bind"]), "may not use"),
    (role(verbs=["impersonate"]), "may not use"),
    (role(resources=["*"]), "may not use"),
    (role(api_groups=["*"]), "may not use"),
]


@pytest.mark.parametrize("field", ["setup", "break", "elevated_setup"])
@pytest.mark.parametrize("doc, reason", DANGEROUS)
def test_dangerous_roles_and_bindings_are_refused_when_the_lab_loads(field, doc, reason):
    # elevated_setup refuses a Role (not an allowed kind there) or a non-view cluster role first; any refusal is fine
    with pytest.raises(ValidationError, match=reason if field != "elevated_setup" else "."):
        lab_with(field, doc)


@pytest.mark.parametrize("as_", ["learner", "admin"])
@pytest.mark.parametrize("doc, reason", DANGEROUS)
def test_a_command_cannot_send_them_with_dash_f(as_, doc, reason):
    with pytest.raises(ValidationError, match=reason):
        lab_with_stdin(doc, as_)


@pytest.mark.parametrize("cluster_role", ["edit", "tenant-admin", "aggregated-admin"])
def test_what_the_admin_applies_may_bind_only_view_or_a_role(cluster_role):
    """The model cannot know what a cluster role already on the cluster allows, so the admin identity binds none."""
    with pytest.raises(ValidationError, match="only a Role or the view cluster role"):
        lab_with("elevated_setup", binding(cluster_role))
    with pytest.raises(ValidationError, match="only a Role or the view cluster role"):
        lab_with_stdin(binding(cluster_role), "admin")


def test_reviewer_counterexamples_are_refused():
    """The independent reviews' examples: cluster-admin for every authenticated user applied by the admin identity,
    a self-made all-powerful Role and its binding in setup, and the same binding sent by an admin command."""
    worst = binding("cluster-admin", subjects=group("system:authenticated"))
    with pytest.raises(ValidationError):
        lab_with("elevated_setup", worst)
    with pytest.raises(ValidationError):
        lab_with("setup", role(verbs=["*", "bind", "escalate", "impersonate"], resources=["*"], api_groups=["*"]))
    with pytest.raises(ValidationError):
        lab_with_stdin(worst, "admin")
    with pytest.raises(ValidationError):
        lab_with("setup", wrapped(binding("${ROLE}"), kind="Template"))


@pytest.mark.parametrize("field", ["setup", "break"])
@pytest.mark.parametrize("kind", ["List", "Template"])
def test_wrapped_objects_are_checked(field, kind):
    crb = {"apiVersion": f"{GROUP}/v1", "kind": "ClusterRoleBinding", "metadata": {"name": "x"},
           "roleRef": {"apiGroup": GROUP, "kind": "ClusterRole", "name": "view"},
           "subjects": [{"kind": "ServiceAccount", "name": "app", "namespace": NS}]}
    with pytest.raises(ValidationError):
        lab_with(field, wrapped(yaml.safe_dump(crb), kind))
    with pytest.raises(ValidationError, match="may not grant the role"):
        lab_with(field, wrapped(binding("cluster-admin"), kind))


def test_elevated_setup_may_not_wrap_its_objects():
    with pytest.raises(ValidationError):
        lab_with("elevated_setup", wrapped(binding()))


@pytest.mark.parametrize("role_name, accepted", [("view", True), ("cluster-admin", False)])
def test_trial_stdin_has_the_same_binding_policy(role_name, accepted):
    """A challenge's trials are run by the recorder, some as admin: their YAML is checked like any command's."""
    base = next(l for l in labs.load("en").values() if l.kind == "challenge").model_dump(by_alias=True)
    base["trials"] = [{"id": "probe", "title": "probe", "kind": "wrong", "expect": "failed",
                       "commands": [{"cmd": "oc apply -f -", "as": "admin", "stdin": binding(role_name, ns=base["namespace"])}]}]
    if accepted:
        assert labs.Lab.model_validate(base)
    else:
        with pytest.raises(ValidationError, match="trial:probe stdin"):
            labs.Lab.model_validate(base)


def test_every_shipped_lab_still_loads():
    loaded = labs.load("en")
    assert labs.errors("en") == [] and len(loaded) > 40
    assert any(lab.elevated_setup for lab in loaded.values())
