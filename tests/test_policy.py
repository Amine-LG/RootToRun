"""The command policy is the security boundary between the browser and the cluster."""
import json
import re
import shlex
import subprocess
from pathlib import Path

import pytest

from academy import policy

LAB = "/tmp/academy-test-labdir"


@pytest.fixture(autouse=True)
def no_subprocess(monkeypatch):
    """Policy/content tests must never execute anything, including cluster tools."""
    def refused(*args, **kwargs):
        pytest.fail(f"unexpected subprocess.run call: {args[0]!r}")
    monkeypatch.setattr(subprocess, "run", refused)

ALLOWED = [
    ("oc get pods -n academy-x", "learner", False),
    ("oc get pods -n openshift-etcd", "reader", False),
    ("oc get pods -A", "reader", False),
    ("oc adm policy who-can get pods -n academy-x", "learner", False),
    ("oc exec deploy/x -n academy-x -- id", "learner", True),
    ("oc apply -f - -n academy-x", "learner", True),
    ("oc apply -f lab/desired/web.yaml -n academy-x", "learner", True),
    ("oc create deployment web --image=registry.access.redhat.com/ubi9/httpd-24 -n academy-x", "learner", True),
    ("oc auth can-i list pods --as=system:serviceaccount:academy-x:sa -n academy-x", "learner", False),
    ("helm install demo lab/chart -n academy-x", "learner", True),
    ("oc rollout status deploy/web -n academy-x", "learner", False),
    ("oc -n academy-x get pods", "learner", False),
]

REFUSED = [
    ("oc get pods -n openshift-etcd", "learner"),  # learner stays in academy-* projects
    ("oc get pods -n default", "learner"),
    ("oc delete pod x -n openshift-etcd", "learner"),
    ("oc get secrets -n openshift-etcd", "reader"),  # the reader never reads Secret data
    ("oc create deployment x --image=y -n academy-x", "reader"),  # the reader is read-only
    ("oc get pods", "admin"),  # admin never comes from the browser
    ("oc delete project academy-x", "learner"),
    ("oc get pods -A", "learner"),
    ("oc login -u kubeadmin", "learner"),
    ("oc get pods --kubeconfig=/root/.kube/config -n academy-x", "learner"),
    ("oc get pods --token=abc -n academy-x", "learner"),
    ("oc get pods --server=https://evil -n academy-x", "learner"),
    ("oc get pods --as=system:admin -n academy-x", "learner"),
    ("oc apply -f /etc/passwd -n academy-x", "learner"),
    ("oc apply -f lab/../../etc/passwd -n academy-x", "learner"),
    ("bash -c id", "learner"),
    ("curl http://example.com", "learner"),
    ("oc get pods\noc get nodes", "learner"),
    ("oc adm drain crc", "learner"),
    ("oc adm policy add-cluster-role-to-user cluster-admin developer", "learner"),
    ("oc rsh pod", "learner"),
    ("oc edit deploy x -n academy-x", "learner"),
    ("oc exec -it deploy/x -n academy-x -- sh", "learner"),
    ("oc port-forward svc/x 8080 -n academy-x", "learner"),
    ("oc proxy", "learner"),
    ("oc cp a b", "learner"),
    ("oc debug node/crc", "learner"),
    ("oc patch scc restricted-v2 -p x", "learner"),  # cluster-scoped write
    ("oc label ns academy-x a=b", "learner"),
    ("helm install x bitnami/nginx -n academy-x", "learner"),  # charts only from the lab
    ("helm install x lab/chart -n default", "learner"),
    ("", "learner"),
    ("oc " + "x" * 2000, "learner"),
]


@pytest.mark.parametrize("cmd,identity,write", ALLOWED)
def test_allowed(cmd, identity, write):
    p = policy.plan(cmd, identity, None, LAB)
    assert p.write is write


@pytest.mark.parametrize("cmd,identity", REFUSED)
def test_refused(cmd, identity):
    with pytest.raises(policy.Refused):
        policy.plan(cmd, identity, None, LAB)


def test_lab_files_map_inside_the_lab_directory():
    p = policy.plan("oc apply -f lab/desired/web.yaml -n academy-x", "learner", None, LAB)
    assert f"{LAB}/desired/web.yaml" in p.argv


def test_lab_files_need_a_lab():
    with pytest.raises(policy.Refused):
        policy.plan("oc apply -f lab/desired/web.yaml -n academy-x", "learner", None, None)


# ---------------------------------------------------------------- regressions from the security review
BYPASSES = [
    # host file read through template files
    ("oc get pods -n academy-x -o go-template-file=/etc/passwd", "learner"),
    ("oc get pods -n academy-x -o jsonpath-file=/etc/passwd", "learner"),
    ("oc get pods -n academy-x --output=go-template-file=/etc/passwd", "learner"),
    ("oc get pods -n academy-x -ogo-template-file=/etc/passwd", "learner"),
    ("oc get pods -n academy-x -o=custom-columns-file=/etc/passwd", "learner"),
    ("oc get pods -n academy-x --template=/etc/passwd", "learner"),
    ("oc get pods -n academy-x -o template-file", "learner"),
    # Secret aliases for the reader
    ("oc get secret.v1 -A -o yaml", "reader"),
    ("oc get secrets.core -A -o yaml", "reader"),
    ("oc get secret.v1.core -n openshift-config -o yaml", "reader"),
    ("oc get cm,secret -A -o yaml", "reader"),
    ("oc get -o yaml secrets -n openshift-config", "reader"),
    ("oc describe secret/x -n openshift-config", "reader"),
    ("oc extract secret/x -n openshift-config --to=-", "reader"),
    # host file write through extract
    ("oc extract secret/evil --to=/home/user/.ssh --confirm -n academy-x", "learner"),
    ("oc extract secret/evil --to ../../etc -n academy-x", "learner"),
    ("oc extract secret/evil -n academy-x", "learner"),
    # other file-reading flags and paths
    ("oc create secret tls t --cert=/etc/ssl/a.crt --key=/etc/ssl/a.key -n academy-x", "learner"),
    ("oc create route edge r --service=web --cert=/etc/x -n academy-x", "learner"),
    ("oc patch deploy/web --patch-file=/etc/passwd -n academy-x", "learner"),
    ("oc set env deploy/web --env-file=/etc/environment -n academy-x", "learner"),
    ("oc start-build hello --from-dir=/home -n academy-x", "learner"),
    ("oc new-app . -n academy-x", "learner"),
    ("oc set volume deploy/web --add --type=hostPath --path=/ -n academy-x", "learner"),
    ("oc apply -k /home/user/kustomize -n academy-x", "learner"),
    ("oc kustomize /etc", "learner"),
    ("oc label pod p -n academy-x a=b --server-side-field-manager-file=x", "learner"),
    # privileged pods through oc run
    ("oc run x --image=busybox --privileged -n academy-x", "learner"),
    ("oc run x --image=busybox -n academy-x --overrides={\"spec\":{\"hostPID\":true}}", "learner"),
    # cluster-scoped writes named in second position or type/name form
    ("oc create clusterrolebinding x --clusterrole=cluster-admin --user=developer -n academy-x", "learner"),
    ("oc set subject clusterrolebinding/cluster-admin --user=developer -n academy-x", "learner"),
    ("oc annotate scc/restricted-v2 a=b -n academy-x", "learner"),
]


@pytest.mark.parametrize("cmd,identity", BYPASSES)
def test_security_review_bypasses_are_refused(cmd, identity):
    with pytest.raises(policy.Refused):
        policy.plan(cmd, identity, None, LAB)


@pytest.mark.parametrize("cmd", [
    "oc get pods -n academy-x -o wide",
    "oc get pods -n academy-x -owide",
    "oc get pods -n academy-x -o=yaml",
    "oc get pods -n academy-x --output=json",
    "oc get pods -n academy-x -o jsonpath='{.items[0].metadata.name}'",
    "oc get pods -n academy-x -o custom-columns=NAME:.metadata.name",
    "oc get pods -n academy-x -o go-template='{{range .items}}{{.metadata.name}}{{end}}'",
    "oc extract secret/app-secret --to=- -n academy-x",
    "oc set volume deploy/web --add --name=data --mount-path=/data -n academy-x",
    "oc get secrets -n academy-x",
])
def test_legitimate_forms_still_work(cmd):
    policy.plan(cmd, "learner", None, LAB)


def test_nested_manifests_are_checked():
    from academy import runner

    crb = {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRoleBinding", "metadata": {"name": "x"}}
    foreign = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "s", "namespace": "kube-system"}}
    ok = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "c"}}
    assert runner.check_manifests([{"apiVersion": "v1", "kind": "List", "items": [ok, crb]}], "academy-x")
    assert runner.check_manifests([{"apiVersion": "template.openshift.io/v1", "kind": "Template", "objects": [foreign]}], "academy-x")
    assert runner.check_manifests([{"apiVersion": "v1", "kind": "ConfigMapList", "items": [ok]}], "academy-x")
    assert runner.check_manifests(["just a string"], "academy-x")
    assert runner.check_manifests([{"apiVersion": "v1", "kind": "List", "items": [ok]}, ok], "academy-x") is None


def test_every_lab_command_is_accepted_by_the_policy():
    """The recorder runs lab commands through this same policy; hardening must not silently break a lab."""
    import re

    from academy import labs

    def concrete(text, lab):
        text = re.sub(r"\{(pod|anypod):[^}@]+(@[^}]+)?\}", "pod-x", text)
        text = re.sub(r"\{rs:[^}@]+(@[^}]+)?\}", "rs-x", text)
        text = re.sub(r"\{route-host:[^}@]+(@[^}]+)?\}", "web.apps.example.com", text)
        return text.replace("{ns}", lab.namespace)

    refused = []
    loaded = labs.load("en")
    assert not labs.errors("en"), labs.errors("en")
    root = Path(__file__).resolve().parents[1]
    assert len(loaded) == sum(len(list((root / f"content/en/{d}").glob("*.yaml"))) for d in ("labs", "incidents", "challenges"))
    for lab in loaded.values():
        trial_cmds = [(f"trial:{t.id}", c) for t in lab.trials for c in t.commands]  # grader trials run as the learner too
        for where, c in [*lab.all_commands(), *trial_cmds]:
            if c.as_ == "admin" or c.skip:
                continue
            try:
                policy.plan(concrete(c.run or c.cmd, lab), c.as_, lab.namespace, LAB)
            except policy.Refused as e:
                refused.append(f"{lab.id} [{where}] {c.cmd}: {e}")
    assert not refused, "\n".join(refused)


@pytest.mark.parametrize("command,flag", [
    ("oc get pods --mystery", "--mystery"),
    ("oc get pods --image=x", "--image"),
    ("oc describe pods -o yaml", "-o"),
    ("oc rollout history deploy/web --to-revision=2", "--to-revision"),
    ("oc adm upgrade --to-image=x --allow-explicit-upgrade", "--to-image"),
    ("oc adm upgrade --to 4.21.0", "--to"),
    ("oc adm upgrade --channel=stable-4.21", "--channel"),
    ("oc adm upgrade --clear=true", "--clear"),
    ("oc debug deploy/web --to-namespace=default -- id", "--to-namespace"),
    ("oc debug deploy/web --to-namespace default -- id", "--to-namespace"),
    ("oc get pods --as-uid=1", "--as-uid"),
    ("oc get pods --as-group system:masters", "--as-group"),
    ("oc get pods -shttps://evil", "-s"),
    ("oc exec deploy/web -ti -- id", "-t"),
    ("oc exec deploy/web -csidecar -it -- id", "-i"),
    ("oc get pods -Aw", "-w"),
    ("helm install demo lab/chart --post-renderer=/bin/sh", "--post-renderer"),
    ("helm upgrade demo lab/chart --post-renderer=/bin/sh", "--post-renderer"),  # --reuse-values became allowed (harmless, used by ch.helm-release)
    ("helm list --set=x=y", "--set"),
    ("helm list --namespace=academy-x --kube-context=evil", "--kube-context"),
])
def test_flags_are_per_subcommand_and_name_the_refusal(command, flag):
    with pytest.raises(policy.Refused, match=re.escape(flag)):
        policy.plan(command, "learner", "academy-x", LAB)


@pytest.mark.parametrize("flag", ["--to-namespace", "--kubeconfig", "--server", "--context", "--as-group", "--as-uid", "--as-root", "--as-user", "--token", "--cluster", "--user"])
@pytest.mark.parametrize("form", ["{flag}=evil", "{flag} evil"])
def test_alternate_target_and_identity_forms(flag, form):
    with pytest.raises(policy.Refused, match=re.escape(flag)):
        policy.plan("oc get pods " + form.format(flag=flag), "learner", "academy-x")


@pytest.mark.parametrize("command", [
    "oc get pods -nacademy-x -owide", "oc get pods -n=academy-x -o=yaml",
    "oc --namespace=academy-x get pods --output json", "oc -nacademy-x get pods",
    "oc get pods -Lapp -lapp=web", "oc logs -p deploy/web", "oc -n academy-x logs -p deploy/web",
])
def test_short_and_leading_forms(command):
    p = policy.plan(command, default_ns="academy-x")
    assert not p.write
    assert p.namespace == "academy-x"


def test_boolean_short_cluster_is_normalized():
    p = policy.plan("oc auth can-i -Aq list pods", "reader")
    assert "-A" in p.argv and "-q" in p.argv


@pytest.mark.parametrize("command", [
    "oc get pods --namespace=", "oc get pods -n", "oc get pods --output",
    "oc get pods -n academy-x --namespace academy-y", "helm list -n academy-x --namespace=academy-y",
    "oc get pods --show-labels=maybe", "oc get pods --namespace academy-system",
    "oc auth whoami --as=system:serviceaccount:academy-x:sa",
    "oc auth can-i list pods --as=system:serviceaccount:academy-system:sa -n academy-x",
    "oc adm upgrade 4.21.0", "oc get pods -- echo hi",
])
def test_ambiguous_or_invalid_forms_are_refused(command):
    with pytest.raises(policy.Refused):
        policy.plan(command, default_ns="academy-x")


@pytest.mark.parametrize("command", ["oc adm upgrade", "oc adm top nodes", "oc rollout history deploy/web", "oc rollout status deploy/web", "oc policy who-can get pods"])
def test_read_subcommands(command):
    assert policy.plan(command, default_ns="academy-x").write is False


@pytest.mark.parametrize("verb", ["exec", "debug"])
def test_remote_execution_is_an_effect(verb):
    command = f"oc {verb} deploy/web -- id"
    assert policy.plan(command, default_ns="academy-x").write is True
    with pytest.raises(policy.Refused):
        policy.plan(command, "reader", "academy-x")
    with pytest.raises(policy.Refused):
        policy.plan(command)


@pytest.mark.parametrize("resource,table,expected", [
    ("deployments.apps/web", {"deployments.apps": True}, "namespaced"),
    ("routes.route.openshift.io", {"routes.route.openshift.io": True}, "namespaced"),
    ("ingresses.config.openshift.io", policy.DEFAULT_RESOURCE_SCOPES, "cluster-scoped"),
    ("ingresses.networking.k8s.io", policy.DEFAULT_RESOURCE_SCOPES, "namespaced"),
    ("clusterserviceversions.operators.coreos.com", policy.DEFAULT_RESOURCE_SCOPES, "namespaced"),
    ("ingresscontrollers.operator.openshift.io", policy.DEFAULT_RESOURCE_SCOPES, "namespaced"),
    ("secrets.v1.core", policy.DEFAULT_RESOURCE_SCOPES, "namespaced"),
    ("deployments.evil.example", {"deployments": True}, "unknown"),
    ("unheardof", {}, "unknown"),
    ("newresource.example.io", {"newresource.example.io": False}, "cluster-scoped"),
])
def test_pure_scope_lookup(resource, table, expected):
    assert policy.resource_scope(resource, table) == expected


@pytest.mark.parametrize("resource", ["widgets", "deployments.evil.example", "groups.user.openshift.io", "validatingadmissionpolicies.admissionregistration.k8s.io", "ingresses.config.openshift.io"])
def test_unknown_and_cluster_scoped_writes_fail_closed(resource):
    with pytest.raises(policy.Refused):
        policy.plan(f"oc annotate {resource}/x note=hello -n academy-x")


def test_discovery_table_authorizes_only_namespaced_types():
    command = "oc patch widgets.example.io/x -p '{}' -n academy-x"
    assert policy.plan(command, resource_scopes={"widgets.example.io": True}).write
    for table in ({}, {"widgets.example.io": False}, {"widgets": True}):
        with pytest.raises(policy.Refused):
            policy.plan(command, resource_scopes=table)


@pytest.mark.parametrize("target", ["all", "all,pods", "pods,all"])
def test_delete_all_expands_to_explicit_namespaced_resources(target):
    p = policy.plan(f"oc delete {target} -l app=quick -n academy-x")
    assert "all" not in p.argv[1].split(",")
    assert all(policy.resource_scope(r, policy.DEFAULT_RESOURCE_SCOPES) == "namespaced" for r in p.argv[1].split(","))


def test_local_rbac_subject_flag_stays_after_exact_subcommand():
    p = policy.plan("oc --user bob create rolebinding view --clusterrole=view -n academy-x")
    assert p.argv[:2] == ["create", "rolebinding"]
    assert "--user=bob" in p.argv[2:]


def test_every_recorded_command_and_argv_is_accepted():
    from academy import labs

    root = Path(__file__).resolve().parents[1]
    loaded = labs.load("en")
    failures = []
    checked = 0

    def concrete(text, namespace):
        text = re.sub(r"\{(?:pod|anypod|rs):[^}]+\}", "pod-x", text)
        text = re.sub(r"\{route-host:[^}]+\}", "web.apps.example.com", text)
        return text.replace("{ns}", namespace)

    def inspect(obj, identity, namespace, path):
        nonlocal checked
        if isinstance(obj, dict):
            identity = obj.get("as", identity)
            # lab commands are what a learner may send to the Workbench; lesson recordings (as `host`, `developer`, the
            # administrator or a test user) are demonstrations made by the recorder, never sent by a learner
            if obj.get("skipped") or obj.get("skip") or identity not in ("learner", "reader"):
                return
            commands = []
            if isinstance(obj.get("argv"), list):
                argv = obj["argv"]
                # kube.Result may include the binary; recorder entries may omit it.
                if argv:
                    if Path(argv[0]).name in ("oc", "kubectl", "helm"):
                        argv = [Path(argv[0]).name, *argv[1:]]
                    else:
                        argv = ["oc", *argv]
                    commands.append(shlex.join(argv))
            if isinstance(obj.get("cmd"), str):
                commands.append(obj.get("run") or obj["cmd"])
            for command in commands:
                try:
                    policy.plan(concrete(command, namespace), identity, namespace, LAB)
                except policy.Refused as exc:
                    failures.append(f"{path}: {command}: {exc}")
                checked += 1
            for value in obj.values():
                if isinstance(value, (dict, list)):
                    inspect(value, identity, namespace, path)
        elif isinstance(obj, list):
            for item in obj:
                inspect(item, identity, namespace, path)

    for path in sorted((root / "content/recordings").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("experiment", None)  # an administration lesson's rollback and checks, run by the recorder only
        namespace = loaded[data["lab"]].namespace if data["lab"] in loaded else "academy-recording"
        # Inspect the entire recording, including any nested argv arrays. Elevated
        # and host commands must identify their authorization explicitly.
        inspect(data, "learner", namespace, path.name)
    assert checked >= 450
    assert not failures, "\n".join(failures)


def test_image_stream_references_cannot_name_another_project():
    """`oc tag production/app:latest --delete -n academy-x` would act on `production`, whatever -n says."""
    for cmd in ("oc tag production/app:latest --delete -n academy-x",
                "oc tag hello:latest production/hello:prod -n academy-x",
                "oc import-image production/ubi:9.5 --from=registry.access.redhat.com/ubi9/ubi-minimal:9.5 --confirm -n academy-x",
                "oc tag x:1 localhost/x:1 -n academy-x"):  # `localhost` is a project name here, not a registry
        with pytest.raises(policy.Refused):
            policy.plan(cmd, "learner", "academy-x")
    for cmd in ("oc tag hello:latest hello:prod -n academy-x",
                "oc tag registry.access.redhat.com/ubi9/ubi-minimal:9.5 ubi:9.5 -n academy-x",
                "oc tag academy-x/hello:latest hello:prod -n academy-x"):
        assert policy.plan(cmd, "learner", "academy-x").write
