"""One offline manifest boundary for Workbench, lab setup and rendered charts.

validate_manifests accepts YAML text, one parsed object, or parsed documents. It returns
an independent normalized list and raises ManifestRefused for an unsafe or malformed
object. Callers must apply that returned content (not the original) so filled namespaces
survive. Setup can use namespace_mode='unset' before its namespace is available.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping
from copy import deepcopy
from typing import Literal

import yaml

WRAPPERS = {"List": "items", "Template": "objects"}
# Match Kind AND API group: a custom API reusing a familiar kind is not authorized.
KIND_GROUPS = {
    "Pod": "", "Service": "", "ConfigMap": "", "Secret": "", "ServiceAccount": "",
    "ReplicationController": "", "PersistentVolumeClaim": "", "Endpoints": "", "Event": "",
    "ResourceQuota": "", "LimitRange": "",
    "Deployment": "apps", "ReplicaSet": "apps", "StatefulSet": "apps", "DaemonSet": "apps",
    "ControllerRevision": "apps", "Job": "batch", "CronJob": "batch",
    "NetworkPolicy": "networking.k8s.io", "Ingress": "networking.k8s.io",
    "EndpointSlice": "discovery.k8s.io", "Role": "rbac.authorization.k8s.io",
    "RoleBinding": "rbac.authorization.k8s.io", "HorizontalPodAutoscaler": "autoscaling",
    "PodDisruptionBudget": "policy", "Lease": "coordination.k8s.io",
    "Route": "route.openshift.io", "ImageStream": "image.openshift.io",
    "ImageStreamTag": "image.openshift.io", "ImageStreamImage": "image.openshift.io",
    "Build": "build.openshift.io", "BuildConfig": "build.openshift.io",
    "DeploymentConfig": "apps.openshift.io",
}
# DeploymentConfig isn't a Kubernetes Deployment; its separate group is explicit.
KIND_SCOPES = {kind: True for kind in KIND_GROUPS}
KIND_SCOPES.update({
    "Namespace": False, "Project": False, "Node": False, "PersistentVolume": False,
    "ClusterRole": False, "ClusterRoleBinding": False, "Group": False, "User": False,
    "Identity": False, "SecurityContextConstraints": False, "StorageClass": False,
    "CustomResourceDefinition": False, "PriorityClass": False, "APIService": False,
    "MutatingWebhookConfiguration": False, "ValidatingWebhookConfiguration": False,
    "ValidatingAdmissionPolicy": False, "ValidatingAdmissionPolicyBinding": False,
    "ClusterOperator": False, "ClusterVersion": False, "MachineConfig": False,
})
WRITE_KINDS = frozenset(KIND_GROUPS)


class ManifestRefused(ValueError):
    """A validation failure safe to show to the learner."""


def validate_manifests(docs: str | Mapping | list, namespace: str | None, *,
                       allowed_kinds: Collection[str] | None = None,
                       elevated_kinds: Collection[str] = (),
                       namespace_mode: Literal["force", "check", "unset"] = "force",
                       kind_scopes: Mapping[str, bool] | None = None) -> list[dict]:
    """Validate recursively, refusing unknown writes and cross-namespace objects.

    force: fill missing namespaces; check: require explicit namespaces to match;
    unset: reject author-provided namespaces, for setup's field-validation stage.
    allowed_kinds can narrow the ordinary allowlist (e.g. elevated setup may contain
    only ResourceQuota, LimitRange, RoleBinding). elevated_kinds explicitly names
    additional privileged kinds; unknown ones also require a supplied kind_scopes
    entry. A scope table never automatically grants permission to a new kind.
    """
    if namespace_mode not in ("force", "check", "unset"):
        raise ValueError("namespace_mode must be force, check or unset")
    if isinstance(docs, str):
        try:
            docs = list(yaml.safe_load_all(docs))
        except (yaml.YAMLError, RecursionError) as exc:
            raise ManifestRefused(f"invalid YAML: {exc}") from exc
    elif isinstance(docs, Mapping):
        docs = [docs]
    if not isinstance(docs, list):
        raise ManifestRefused("manifests must be YAML documents or a list of Kubernetes objects")
    allowed = WRITE_KINDS if allowed_kinds is None else WRITE_KINDS.intersection(allowed_kinds)
    elevated = set(elevated_kinds)
    scopes = KIND_SCOPES if kind_scopes is None else kind_scopes
    try:
        output = deepcopy(docs)
    except RecursionError:
        raise ManifestRefused("manifests nested too deeply; flatten List/Template wrappers") from None
    active: set[int] = set()

    def visit(objects: list, depth: int = 0) -> None:
        if depth > 20:
            raise ManifestRefused("manifests nested too deeply; flatten List/Template wrappers")
        for obj in objects:
            if obj is None:
                continue  # Empty YAML documents are harmless; scalar false/0 are not objects.
            if not isinstance(obj, dict) or not isinstance(obj.get("kind"), str):
                raise ManifestRefused("each YAML document must be a Kubernetes object with a kind")
            if id(obj) in active:
                raise ManifestRefused("recursive YAML aliases are not allowed; use a finite List/Template")
            active.add(id(obj))
            kind = obj["kind"]
            version = obj.get("apiVersion")
            if not isinstance(version, str) or not version or version.count("/") > 1:
                raise ManifestRefused(f"{kind} needs an apiVersion, for example v1 or apps/v1")
            group = version.split("/", 1)[0] if "/" in version else ""
            metadata = obj.setdefault("metadata", {})
            if not isinstance(metadata, dict):
                raise ManifestRefused(f"{kind}.metadata must be an object")
            ns = metadata.get("namespace")
            if "namespace" in metadata and (not isinstance(ns, str) or not ns):
                raise ManifestRefused(f"{kind}.metadata.namespace must be a nonempty namespace name")
            if ns is not None and (namespace_mode == "unset" or ns != namespace):
                message = "lab setup must leave metadata.namespace unset" if namespace_mode == "unset" else f"it must match -n {namespace}"
                raise ManifestRefused(f"{kind} targets namespace {ns}; {message}")
            if kind in WRAPPERS:
                expected_group = "template.openshift.io" if kind == "Template" else ""
                if group != expected_group:
                    raise ManifestRefused(f"{kind} is only accepted from API group {expected_group or 'core (v1)'}")
                field = WRAPPERS[kind]
                inner = obj.get(field, [])
                if not isinstance(inner, list):
                    raise ManifestRefused(f"{kind}.{field} must be a list of objects")
                visit(inner, depth + 1)
            else:
                if kind.endswith("List"):
                    raise ManifestRefused(f"{kind} wrappers are not accepted; use kind: List")
                scope = scopes.get(kind)
                if scope is not True and kind not in elevated:
                    reason = "cluster-scoped" if scope is False else "of unknown scope"
                    raise ManifestRefused(f"{kind} is {reason}; it needs an explicit elevated allowance naming this kind")
                if kind not in allowed and kind not in elevated:
                    raise ManifestRefused(f"{kind} is not an allowed writable kind; use a supported lab resource")
                if scope is None:
                    raise ManifestRefused(f"{kind} has unknown scope; supply its discovered scope before allowing it")
                if kind in KIND_GROUPS and group != KIND_GROUPS[kind]:
                    raise ManifestRefused(f"{kind} from API group {group or 'core'} is not allowed; use {KIND_GROUPS[kind] or 'v1'}")
                if scope is False and ns is not None:
                    raise ManifestRefused(f"{kind} is cluster-scoped and must not set metadata.namespace")
                if scope is True and namespace_mode != "unset" and not namespace:
                    raise ManifestRefused(f"{kind} needs a lab namespace; choose -n academy-…")
                if scope is True and namespace_mode == "force":
                    metadata["namespace"] = namespace
                if kind == "Secret":
                    annotations = metadata.get("annotations", {})
                    if not isinstance(annotations, dict):
                        raise ManifestRefused("Secret.metadata.annotations must be an object")
                    if obj.get("type") == "kubernetes.io/service-account-token" or "kubernetes.io/service-account.name" in annotations:
                        raise ManifestRefused("ServiceAccount token Secrets cannot be provisioned here; use a normal lab Secret or ServiceAccount")
                # ServiceAccount definitions and ordinary Secrets remain allowed. Token
                # projection/automount in pods remains Kubernetes' usual workload behavior.
                # Any envelope-style nested objects must cross the same boundary.
                for field in ("items", "objects"):
                    if field in obj:
                        if not isinstance(obj[field], list):
                            raise ManifestRefused(f"{kind}.{field} must be a list of objects")
                        visit(obj[field], depth + 1)
            active.remove(id(obj))

    visit(output)
    return [obj for obj in output if obj is not None]


def check_manifests(docs: str | Mapping | list, namespace: str | None, **kwargs) -> str | None:
    """Compatibility facade for callers needing a learner-facing reason, not normalized YAML."""
    try:
        validate_manifests(docs, namespace, **kwargs)
    except ManifestRefused as exc:
        return str(exc)
    return None
