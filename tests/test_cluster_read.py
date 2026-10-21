"""The read-only cluster helper refuses anything that could change the cluster, redirect the connection, change the
identity or write a local file, including options that oc would read differently from a naive check."""
import importlib.util

import pytest

from academy import config

spec = importlib.util.spec_from_file_location("cluster_read", config.ROOT / "scripts" / "cluster_read.py")
cluster_read = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cluster_read)


@pytest.mark.parametrize("args", [
    ["get", "pods", "-n", "default"],
    ["get", "pods", "-ndefault", "-oyaml"],
    ["get", "clusterversion", "version", "-o", "jsonpath={.spec.clusterID}"],
    ["get", "pods", "-A", "--show-labels"],
    ["auth", "can-i", "create", "pods"],
    ["auth", "can-i", "create", "pods", "--as=developer", "-n", "team"],
    ["adm", "policy", "who-can", "get", "secrets"],
    ["logs", "web", "-c", "app", "--tail=20", "--previous"],
    ["version", "--client"],
    ["create", "--dry-run=server", "-f", "role.yaml"],
    ["create", "rolebinding", "x", "--clusterrole=view", "--user=dev", "--dry-run=server", "-o", "yaml"],
    ["apply", "-f", "role.yaml", "--dry-run=server", "--validate"],
    ["annotate", "namespace", "default", "a=b", "--dry-run=client"],
    ["label", "-n", "team", "pod", "web", "tier=x", "--dry-run=server"],
    ["patch", "deploy", "web", "--type=merge", "-p", '{"spec":{}}', "--dry-run=server"],
])
def test_read_only_commands_pass(args):
    assert cluster_read.refusal(args) is None


@pytest.mark.parametrize("args", [
    ["annotate", "namespace", "default", "audit-note=--dry-run=client"],     # the flag text inside a value
    ["annotate", "namespace", "default", "a=b", "--dry-run=client", "--dry-run=none"],
    ["annotate", "namespace", "default", "a=b", "--field-manager", "--dry-run=client"],  # taken as the value
    ["label", "-n", "--dry-run=client", "ns", "default", "a=b"],
    ["annotate", "ns", "default", "--", "a=b", "x", "--dry-run=client"],  # positional after --
    ["-n", "get", "delete", "pod", "web"],                                 # a flag value is not the command
    ["--cache-dir", "get", "delete", "pods", "--all"],
    ["get", "--cache-dir", "get", "x"],
    ["delete", "pod", "web"],
    ["adm", "policy", "add-scc-to-user", "privileged", "-z", "x", "--dry-run=client"],
    ["get", "pods", "--watch"],
    ["get", "pods", "-Aw"],
    ["get", "pods", "--watch_only=true"],
    ["logs", "-f", "web"],
    ["logs", "web", "-f=true"],
    ["get", "pods", "--kubeconfig=/tmp/x"],
    ["get", "pods", "-shttps://elsewhere.invalid", "--insecure-skip-tls-verify=true"],   # attached short value
    ["get", "pods", "--server=https://elsewhere.invalid"],
    ["get", "pods", "--as=system:admin", "--as-group=system:masters"],     # impersonation outside can-i
    ["version", "--client", "--profile=cpu", "--profile-output=/tmp/x"],   # writes a local file
    ["create", "--dry-run=client", "--raw=/api/v1/namespaces", "-f", "-"],
    ["get", "pods", "--token=abc"],
    ["annotate", "namespace", "default", "a=b", "--dry-run=client", "--dry_run=none"],   # oc normalises _ to -
    ["label", "namespace", "default", "a=b", "--dry-run=server", "--dry_run", "none"],
    ["annotate", "namespace", "default", "a=b", "--dry_run=client", "--dry-run=none"],
    ["edit", "deploy", "web"],
    ["exec", "web", "--", "id"],
    ["port-forward", "web", "8080"],
    ["project", "other"],
    ["create", "configmap", "x", "--from-literal=a=b", "--dry-run=client", "--validate", "--dry-run=none"],  # optional value
    ["create", "configmap", "x", "--from-literal=a=b", "--dry-run=client", "-o=", "--dry-run=none"],         # empty value
    ["annotate", "namespace", "default", "a=b", "--dry-run=server", "--user=other"],   # another kubeconfig user
    ["create", "configmap", "x", "--dry-run"],
    ["create", "unknownthing", "x", "--dry-run=client"],
    ["create", "unknownthing", "x", "--dry-run=client", "-f", "x.yaml"],
    ["set", "unknownthing", "x", "--dry-run=server", "--filename=x.yaml"],
    ["get", "pods", "-o=", "--kubeconfig=/tmp/x"],
])
def test_changes_are_refused(args):
    assert cluster_read.refusal(args)
