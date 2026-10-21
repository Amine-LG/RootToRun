"""Pure command planning: explicit subcommands, flags, identities and resource scopes.

No discovery or processes occur here. A caller may supply an API-discovery scope table;
True means namespaced, False means cluster-scoped. Unknown scopes never authorize writes.
Session ownership and cluster approval must additionally be enforced by the execution owner.
"""
from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from . import config

NS_RE = re.compile(r"^academy-[a-z0-9]([a-z0-9-]{0,40}[a-z0-9])?$")
LABFILE_RE = re.compile(r"^lab/[a-zA-Z0-9][a-zA-Z0-9._/-]{0,120}$")
OUTPUT_RE = re.compile(r"^(json|yaml|wide|name|(go-template|template|jsonpath|jsonpath-as-json|custom-columns)=.+)$", re.DOTALL)
Scope = Literal["namespaced", "cluster-scoped", "unknown"]


def resource_scope(resource: str, table: Mapping[str, bool]) -> Scope:
    """Look up type[/name], preserving API group (and optional version) qualification.

    Qualified names never fall back to an unqualified type: a CRD can reuse that type.
    Table keys are CLI resource names/aliases, optionally group-qualified. Discovery
    adapters should omit ambiguous unqualified aliases. This function performs no I/O.
    """
    key = resource.split("/", 1)[0].lower()
    value = table.get(key)
    if value is None and "." in key:
        parts = key.split(".")
        if len(parts) > 2 and re.fullmatch(r"v\d+(?:(?:alpha|beta)\d+)?", parts[1]):
            value = table.get(".".join([parts[0], *parts[2:]]))
    return "namespaced" if value is True else "cluster-scoped" if value is False else "unknown"


def _scope_defaults() -> dict[str, bool]:
    table: dict[str, bool] = {}
    entries = [
        (True, "core", "pod pods po;service services svc;configmap configmaps cm;secret secrets;serviceaccount serviceaccounts sa;replicationcontroller replicationcontrollers rc;persistentvolumeclaim persistentvolumeclaims pvc;endpoints ep;event events ev;resourcequota resourcequotas quota;limitrange limitranges limits"),
        (True, "apps.openshift.io", "deploymentconfig deploymentconfigs dc"),
        (True, "apps", "deployment deployments deploy;replicaset replicasets rs;statefulset statefulsets sts;daemonset daemonsets ds;controllerrevision controllerrevisions"),
        (True, "batch", "job jobs;cronjob cronjobs cj"),
        (True, "networking.k8s.io", "networkpolicy networkpolicies netpol;ingress ingresses ing"),
        (True, "discovery.k8s.io", "endpointslice endpointslices"),
        (True, "rbac.authorization.k8s.io", "role roles;rolebinding rolebindings rb"),
        (True, "autoscaling", "horizontalpodautoscaler horizontalpodautoscalers hpa"),
        (True, "policy", "poddisruptionbudget poddisruptionbudgets pdb"),
        (True, "coordination.k8s.io", "lease leases"),
        (True, "route.openshift.io", "route routes"),
        (True, "image.openshift.io", "imagestream imagestreams is;imagestreamtag imagestreamtags istag;imagestreamimage imagestreamimages isimage"),
        (True, "build.openshift.io", "build builds;buildconfig buildconfigs bc"),
        (True, "template.openshift.io", "template templates"),
        (True, "operators.coreos.com", "subscription subscriptions sub;installplan installplans ip;operatorgroup operatorgroups og;catalogsource catalogsources catsrc;clusterserviceversion clusterserviceversions csv"),
        (True, "packages.operators.coreos.com", "packagemanifest packagemanifests"),
        (True, "operator.openshift.io", "ingresscontroller ingresscontrollers"),
        (False, "core", "node nodes no;namespace namespaces ns;persistentvolume persistentvolumes pv"),
        (False, "project.openshift.io", "project projects;projectrequest projectrequests"),
        (False, "user.openshift.io", "user users;group groups;identity identities"),
        (False, "rbac.authorization.k8s.io", "clusterrole clusterroles;clusterrolebinding clusterrolebindings crb"),
        (False, "security.openshift.io", "securitycontextconstraints scc"),
        (False, "storage.k8s.io", "storageclass storageclasses sc;csidriver csidrivers;csinode csinodes;volumeattachment volumeattachments"),
        (False, "apiextensions.k8s.io", "customresourcedefinition customresourcedefinitions crd crds"),
        (False, "admissionregistration.k8s.io", "validatingadmissionpolicy validatingadmissionpolicies;validatingadmissionpolicybinding validatingadmissionpolicybindings;validatingwebhookconfiguration validatingwebhookconfigurations;mutatingwebhookconfiguration mutatingwebhookconfigurations"),
        (False, "scheduling.k8s.io", "priorityclass priorityclasses pc"),
        (False, "machineconfiguration.openshift.io", "machineconfig machineconfigs mc;machineconfigpool machineconfigpools mcp"),
        (False, "config.openshift.io", "clusteroperator clusteroperators co;clusterversion clusterversions;apiserver apiservers;infrastructure infrastructures;network networks;scheduler schedulers;oauth oauths;proxy proxies;dns dnses;featuregate featuregates;console consoles"),
    ]
    for namespaced, group, rows in entries:
        for row in rows.split(";"):
            for alias in row.split():
                table[alias] = namespaced
                table[f"{alias}.{group}"] = namespaced
                if group == "core":
                    table[f"{alias}.v1"] = namespaced
    # Same plural name exists at different scopes in different API groups.
    table["ingresses.config.openshift.io"] = False
    table["images.config.openshift.io"] = False
    table["builds.config.openshift.io"] = False
    return table


DEFAULT_RESOURCE_SCOPES = _scope_defaults()
CLUSTER_SCOPED = {k for k, v in DEFAULT_RESOURCE_SCOPES.items() if not v}
REFUSED_VERBS = {
    "login": "log in from the Connections panel; the browser never handles credentials",
    "logout": "use the Connections panel", "config": "kubeconfig changes are not allowed here",
    "project": "pass -n academy-… instead of switching the current project",
    "new-project": "lab projects are created by lab setup", "delete-project": "use lab cleanup",
    "rsh": "remote shells can change a pod; use `oc exec <pod> -n academy-… -- <command>`",
    "attach": "interactive remote execution; use your own terminal",
    "port-forward": "opens a long-running network tunnel; use your own terminal",
    "proxy": "exposes the API; use your own terminal", "cp": "copies files and executes remotely; use your own terminal",
    "edit": "use `oc patch`, `oc set` or the YAML editor", "kustomize": "rendering local files needs trusted lab setup",
}


class Refused(ValueError):
    pass


@dataclass
class Plan:
    argv: list[str]
    display: str
    identity: str
    write: bool
    namespace: str | None
    stdin_allowed: bool = False
    tool: str = "oc"


# Specifications: value flags and boolean flags. No CLI abbreviations are accepted.
def _spec(values: str = "", switches: str = "") -> dict[str, bool]:
    return {**dict.fromkeys(values.split(), True), **dict.fromkeys(switches.split(), False)}


GLOBAL = _spec("-n --namespace --request-timeout")
OUTPUT = _spec("-o --output")
SELECT = _spec("-l --selector --field-selector")
FILES = _spec("-f --filename -k --kustomize")
WRITE_COMMON = {**OUTPUT, **_spec("--dry-run --field-manager", "--save-config")}
FLAGS = {
    "get": {**OUTPUT, **SELECT, **_spec("--sort-by -L --label-columns --chunk-size", "--show-labels --no-headers --ignore-not-found -A --all-namespaces")},
    "describe": {**SELECT, **_spec(switches="--show-events -A --all-namespaces")},
    "logs": {**SELECT, **_spec("-c --container --tail --since --since-time --limit-bytes --pod-running-timeout --max-log-requests", "--previous -p --timestamps --all-containers --prefix --ignore-errors")},
    "explain": _spec("--api-version --output", "--recursive"),
    "api-resources": {**OUTPUT, **_spec("--api-group --verbs --sort-by", "--namespaced --no-headers --cached")},
    "api-versions": {}, "version": {**OUTPUT, **_spec(switches="--client")},
    "whoami": _spec(switches="--show-server --show-console"),
    "auth can-i": _spec("--as --subresource", "--list --quiet -q --all-namespaces -A"),
    "auth whoami": OUTPUT,
    "events": {**OUTPUT, **_spec("--for --types", "-A --all-namespaces --no-headers")},
    "top pod": {**SELECT, **_spec("--sort-by", "--containers --no-headers --sum")},
    "top node": {**SELECT, **_spec("--sort-by", "--no-headers")},
    "status": _spec(switches="--suggest"), "projects": _spec(switches="-q --quiet"),
    "adm upgrade": {},
    "adm top nodes": _spec("--sort-by", "--no-headers"),
    "adm top pods": {**SELECT, **_spec("--sort-by", "--containers --no-headers")},
    "adm policy who-can": {},
    "adm policy scc-subject-review": {**_spec("-f --filename"), **OUTPUT},
    "adm policy scc-review": {**_spec("-f --filename"), **OUTPUT},
    "diff": {**FILES, **_spec("--field-manager", "--server-side --force-conflicts")},
    "extract": _spec("--to --keys", "--confirm"),
    "wait": {**SELECT, **_spec("--for --timeout", "--all")},
    "apply": {**FILES, **WRITE_COMMON, **_spec("--validate", "--server-side --force-conflicts --overwrite")},
    "replace": {**_spec("-f --filename"), **WRITE_COMMON, **_spec("--validate")},
    "delete": {**_spec("-f --filename"), **SELECT, **OUTPUT, **_spec("--grace-period --timeout", "--all --ignore-not-found --wait")},
    "create": {**_spec("-f --filename"), **WRITE_COMMON, **_spec("--validate")},
    "create deployment": {**WRITE_COMMON, **_spec("--image --replicas --port")},
    "create configmap": {**WRITE_COMMON, **_spec("--from-literal", "--append-hash")},
    "create secret generic": {**WRITE_COMMON, **_spec("--from-literal", "--append-hash")},
    "create serviceaccount": WRITE_COMMON,
    "create job": {**WRITE_COMMON, **_spec("--image --from")},
    "create cronjob": {**WRITE_COMMON, **_spec("--image --schedule")},
    "create role": {**WRITE_COMMON, **_spec("--verb --resource --resource-name")},
    "create rolebinding": {**WRITE_COMMON, **_spec("--role --clusterrole --serviceaccount --user --group")},
    "scale": {**SELECT, **WRITE_COMMON, **_spec("--replicas --current-replicas --resource-version --timeout")},
    "expose": {**SELECT, **WRITE_COMMON, **_spec("--name --port --target-port --protocol --type --hostname --labels")},
    "label": {**SELECT, **WRITE_COMMON, **_spec("--resource-version", "--overwrite --all")},
    "annotate": {**SELECT, **WRITE_COMMON, **_spec("--resource-version", "--overwrite --all")},
    "patch": {**WRITE_COMMON, **_spec("-p --patch --type --subresource")},
    "run": {**WRITE_COMMON, **_spec("--image --port --restart --env --labels --requests --limits", "--command")},
    "exec": _spec("-c --container --pod-running-timeout"),
    "debug": {**OUTPUT, **_spec("-c --container --image", "--one-container --quiet")},
    "autoscale": {**WRITE_COMMON, **_spec("--min --max --cpu --cpu-percent --name")},
    "new-app": {**WRITE_COMMON, **_spec("--name --image --docker-image --image-stream -e --env -l --labels --strategy --template -p --param", "--allow-missing-images --as-deployment-config")},
    # Renders a Template (from the project, or a lab file with -f) and prints the objects; it creates nothing.
    "process": {**OUTPUT, **_spec("-f --filename -p --param -l --labels", "--parameters --local --ignore-unknown-parameters")},
    "new-build": {**WRITE_COMMON, **_spec("--name --image --docker-image --image-stream -e --env --strategy --to", "--binary --allow-missing-images")},
    "start-build": _spec("--from-build --commit", "--wait"),
    "cancel-build": _spec("--state", "--restart"),
    "tag": _spec("--reference-policy", "--source --alias --scheduled --reference --delete"),
    "import-image": _spec("--from --reference-policy --import-mode", "--confirm --all --scheduled"),
}
for mode in ("edge", "passthrough", "reencrypt"):
    FLAGS[f"create route {mode}"] = {**WRITE_COMMON, **_spec("--service --port --hostname --insecure-policy")}
for mode in ("clusterip", "nodeport", "loadbalancer", "externalname"):
    FLAGS[f"create service {mode}"] = {**WRITE_COMMON, **_spec("--tcp --node-port --external-name")}
for sub, values, switches in [
    ("env", "-c --containers -e --env --from --prefix", "--list --overwrite"),  # oc set env has no --keys (kubectl does)
    ("image", "", ""), ("data", "--from-literal", ""),
    ("resources", "-c --containers --requests --limits", ""),
    ("selector", "--resource-version", ""),
    ("probe", "-c --containers --get-url --open-tcp --period-seconds --initial-delay-seconds --timeout-seconds --failure-threshold --success-threshold", "--readiness --liveness --startup --remove"),
    ("triggers", "--from-image -c --containers", "--auto --manual --remove --remove-all --list"),
    ("volume", "--name --type --claim-name --claim-mode --claim-size --mount-path -m --sub-path --configmap-name --secret-name --containers", "--add --remove --overwrite --list"),
    ("serviceaccount", "", ""), ("subject", "--user --group --serviceaccount", ""),
]:
    FLAGS[f"set {sub}"] = {**WRITE_COMMON, **SELECT, **_spec(values, switches)}
for sub in ("status", "history", "restart", "undo", "pause", "resume"):
    FLAGS[f"rollout {sub}"] = {**SELECT, **_spec("--timeout --revision" if sub == "status" else "--revision" if sub == "history" else "--to-revision" if sub == "undo" else "", "--watch" if sub == "status" else "")}
for sub in ("who-can", "add-role-to-user", "add-role-to-group", "remove-role-from-user", "remove-role-from-group"):
    FLAGS[f"policy {sub}"] = {} if sub == "who-can" else {**OUTPUT, **_spec("-z --serviceaccount --rolebinding-name")}

READ_VERBS = {"process", "get", "describe", "logs", "explain", "api-resources", "api-versions", "version", "whoami", "auth", "events", "top", "status", "adm", "diff", "extract", "projects", "wait"}
WRITE_VERBS = {key.split()[0] for key in FLAGS} - READ_VERBS
HELM_VERBS_READ = {"list", "ls", "history", "status", "template", "get", "show", "lint"}
HELM_VERBS_WRITE = {"install", "upgrade", "uninstall", "rollback"}
HELM_FLAGS = {
    "list": {**OUTPUT, **_spec("--filter --max --offset", "--all --deployed --failed --pending --uninstalled --uninstalling --superseded --short -q --reverse --date")},
    "history": {**OUTPUT, **_spec("--max")},
    "status": {**OUTPUT, **_spec("--revision", "--show-resources --show-desc")},
    "template": _spec("-f --values --set --set-string --kube-version --api-versions", "--include-crds --skip-tests"),
    "lint": _spec("-f --values --set --set-string", "--strict"),
    "install": _spec("-f --values --set --set-string --timeout --description", "--wait --atomic --wait-for-jobs --disable-openapi-validation --skip-crds"),
    "upgrade": _spec("-f --values --set --set-string --timeout --description", "--wait --atomic --wait-for-jobs --reset-values --reuse-values --install --skip-crds"),
    "uninstall": _spec("--timeout --description", "--wait --ignore-not-found"),
    "rollback": _spec("--timeout", "--wait --wait-for-jobs --cleanup-on-fail"),
}
HELM_FLAGS["ls"] = HELM_FLAGS["list"]
for sub in ("manifest", "values", "hooks", "notes", "all"):
    HELM_FLAGS[f"get {sub}"] = _spec("--revision", "--all" if sub == "values" else "")
for sub in ("chart", "values", "readme", "all"):
    HELM_FLAGS[f"show {sub}"] = {}

# Forbidden alternate targets/authentication are rejected even where a same-named
# option exists for another subcommand. --user is allowed only as an RBAC subject.
ALTERNATE_FLAGS = {"--to-namespace", "--kubeconfig", "--server", "-s", "--context", "--cluster", "--token", "--username", "--password", "--certificate-authority", "--client-key", "--client-certificate", "--insecure-skip-tls-verify", "--tls-server-name", "--kube-apiserver", "--kube-context", "--kube-token", "--kube-as-user", "--kube-as-group", "--kube-ca-file", "--kube-insecure-skip-tls-verify", "--kube-tls-server-name"}
CONTAINER_PATH_FLAGS = {"--mount-path", "-m", "--sub-path"}


def _labfile(value: str, labdir: str | None) -> str:
    if not labdir or not LABFILE_RE.fullmatch(value) or ".." in value.split("/"):
        raise Refused("files can only come from the current lab (lab/<path>) or the YAML editor (-f -)")
    return labdir.rstrip("/") + "/" + value[4:]


def _check_output(value: str) -> None:
    if not OUTPUT_RE.fullmatch(value):
        raise Refused("output formats allowed here: json, yaml, wide, name, jsonpath=…, go-template=…, custom-columns=… (no template files)")


def _tokens(args: list[str], specs: Mapping[str, Mapping[str, bool]]) -> list[tuple[str, str | None]]:
    """Normalize flags including -nns, -o=yaml and -Aq; retain positional order."""
    arity = dict(GLOBAL)
    for spec in specs.values():
        for name, takes_value in spec.items():
            # -p is a switch for logs, value elsewhere: resolved after subcommand.
            if name != "-p":
                arity[name] = takes_value
    out: list[tuple[str, str | None]] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if not arg.startswith("-") or arg == "-":
            out.append(("", arg)); i += 1; continue
        parts = [arg] if arg.startswith("--") else ["-" + c for c in arg[1:].split("=", 1)[0]]
        offset = 2
        for part in parts:
            name = part.split("=", 1)[0]
            if name in ALTERNATE_FLAGS or name.startswith("--as") and name != "--as":
                raise Refused(f"flag `{name}` changes the connection, identity or target; use the Connections panel and -n academy-…")
            if name == "-p":
                # logs' -p is boolean; patch's -p takes inline JSON.
                takes_value = "logs" not in args
            elif name not in arity:
                raise Refused(f"flag `{name}` is not allowed here; use a supported flag for this subcommand")
            else:
                takes_value = arity[name]
            value = None
            if arg.startswith("--") and "=" in arg:
                value = arg.split("=", 1)[1]
            elif not arg.startswith("--") and (takes_value and len(arg) > offset or "=" in arg and offset == len(arg.split("=", 1)[0])):
                value = arg[offset:].removeprefix("=")
            if takes_value:
                if value is None:
                    i += 1
                    if i >= len(args) or args[i].startswith("-") and args[i] != "-":
                        raise Refused(f"flag `{name}` needs a value")
                    value = args[i]
                if value == "":
                    raise Refused(f"flag `{name}` needs a value")
            elif value is not None and value not in ("true", "false"):
                raise Refused(f"flag `{name}` needs true or false")
            out.append((name, value))
            offset += 1
            if takes_value or value is not None:
                break
        i += 1
    return out


def _path(positionals: list[str], specs: Mapping[str, Mapping[str, bool]]) -> str:
    for size in (3, 2, 1):
        key = " ".join(positionals[:size])
        if key in specs:
            # 'create' alone only accepts YAML; never arbitrary create subcommands.
            if key == "create" and len(positionals) > 1:
                break
            return key
    raise Refused(f"`{' '.join(positionals[:3])}` is not available here; use a supported subcommand")


def plan(command: str, identity: str = "learner", default_ns: str | None = None,
         labdir: str | None = None, *, resource_scopes: Mapping[str, bool] | None = None) -> Plan:
    if identity not in ("learner", "reader"):
        raise Refused("the Workbench runs as the learner or the read-only reader, never as admin")
    command = (command or "").strip()
    if not command or len(command) > 1500:
        raise Refused("enter one command of at most 1500 characters")
    if "\n" in command or "\r" in command:
        raise Refused("run one command at a time")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise Refused(f"cannot parse command: {exc}") from exc
    if not argv:
        raise Refused("enter a command")
    tool, args = argv[0], argv[1:]
    if tool not in ("oc", "kubectl", "helm"):
        raise Refused("only oc, kubectl and lab Helm commands run here; use `oc exec <pod> -n academy-… -- <command>` for a container command")
    if tool == "helm":
        return plan_helm(args, identity, default_ns, labdir)
    tail: list[str] = []
    if "--" in args:
        cut = args.index("--")
        args, tail = args[:cut], args[cut + 1:]
    tokens = _tokens(args, FLAGS)
    pos = [value for name, value in tokens if not name]
    if not pos:
        raise Refused("missing subcommand")
    verb = pos[0]
    if verb in REFUSED_VERBS:
        # Trusted lab kustomize inputs can still be rendered; no arbitrary paths.
        if verb == "kustomize" and len(pos) == 2 and pos[1].startswith("lab/") and not any(n for n, _ in tokens):
            return Plan([verb, _labfile(pos[1], labdir)], command, identity, False, None)
        raise Refused(f"`{verb}` is not available here: {REFUSED_VERBS[verb]}")
    key = _path(pos, FLAGS)
    spec = {**GLOBAL, **FLAGS[key]}
    ns = None
    all_ns = False
    stdin_allowed = False
    actual: list[str] = []
    shown: list[str] = []
    seen: dict[str, list[str | None]] = {}
    for name, value in tokens:
        if not name:
            actual.append(value); shown.append(value)
            continue
        if name not in spec:
            raise Refused(f"flag `{name}` is not allowed with `{key}`; use a supported flag for this subcommand")
        if spec[name] and value is None:
            raise Refused(f"flag `{name}` needs a value")
        seen.setdefault(name, []).append(value)
        if name in ("-n", "--namespace"):
            if ns is not None and ns != value:
                raise Refused("conflicting namespace flags; choose one -n academy-…")
            ns = value
            continue
        if name in ("-A", "--all-namespaces"):
            if value != "false":
                if identity != "reader" or verb not in ("get", "describe", "events", "auth"):
                    raise Refused(f"flag `{name}` reads other namespaces; use the reader identity or -n academy-…")
                all_ns = True
        if name == "--as":
            if key != "auth can-i" or identity != "learner" or not re.fullmatch(r"system:serviceaccount:academy-[a-z0-9-]+:[a-z0-9-]+", value or "") or (value or "").split(":")[2] == config.SYSTEM_NS:
                raise Refused("--as is only allowed with `oc auth can-i`, for ServiceAccounts in academy-* lab projects")
        if name in ("-o", "--output"):
            _check_output(value)
        mapped = value
        if name in ("-f", "--filename", "-k", "--kustomize"):
            if value == "-" and name in ("-f", "--filename"):
                stdin_allowed = True
            else:
                mapped = _labfile(value, labdir)
        elif value and value.startswith(("/", "~", "../")) and name not in CONTAINER_PATH_FLAGS:
            raise Refused(f"flag `{name}` cannot use a server path; use lab/<path> or the YAML editor")
        if name in ("-f", "--filename", "-k", "--kustomize"):
            actual.extend([name, mapped]); shown.extend([name, value])
        else:
            flag = name + ("=" + value if value is not None else "")
            actual.append(flag); shown.append(flag)
    restpos = pos[len(key.split()):]
    if key == "adm upgrade" and restpos:
        raise Refused("`oc adm upgrade` is allowed only to show status; run it without update flags or arguments")
    if tail and not (verb in ("exec", "debug", "run") or key in ("create deployment", "create job", "create cronjob")):
        raise Refused(f"`{key}` does not accept a remote command here; use `oc exec <pod> -n academy-… -- <command>`")
    if verb == "extract" and seen.get("--to") != ["-"]:
        raise Refused("`oc extract` prints to the terminal here: use `--to=-`")
    if key == "set volume" and any(v not in ("configmap", "secret", "pvc", "emptyDir") for v in seen.get("--type", [])):
        raise Refused("volume type is not allowed here; use configmap, secret, pvc or emptyDir (no host paths)")
    if verb in ("new-app", "new-build") and any(v == "." or v.startswith(("/", "~", "./", "../")) for v in restpos):
        raise Refused("local directories cannot be uploaded here; use a Git URL or an image")
    write = verb not in READ_VERBS and key not in ("rollout status", "rollout history", "policy who-can")
    if verb in ("exec", "debug"):
        if not tail or len(restpos) != 1:
            raise Refused(f"use `oc {verb} <workload> -n academy-… -- <command>`")
        target = restpos[0]
        if verb == "debug" and ("/" not in target or resource_scope(target, DEFAULT_RESOURCE_SCOPES) != "namespaced"):
            raise Refused("debug is limited to lab workloads; node debugging needs your own terminal")
        if tail[0] in ("sh", "bash", "/bin/sh", "/bin/bash") and "-c" not in tail:
            raise Refused("interactive shells are not supported; run one command, e.g. `-- sh -c 'id; ps'`")
    table = DEFAULT_RESOURCE_SCOPES if resource_scopes is None else resource_scopes
    resources: list[str] = []
    if verb in ("get", "describe", "delete", "label", "annotate", "patch", "scale", "expose", "autoscale", "exec", "debug", "wait", "extract", "top", "set", "rollout"):
        if restpos:
            resources.extend(restpos[0].split(","))
        resources.extend(t for t in restpos[1:] if "/" in t and "=" not in t)
        # Exec/wait/logs may name a bare pod; generation verbs have implicit scope.
        if verb == "exec" and resources and "/" not in resources[0]:
            resources[0] = "pods"
    elif verb == "create" and key != "create":
        resources = [pos[1]]
    elif verb in ("start-build", "cancel-build"):
        resources = ["builds.build.openshift.io"]
    elif verb in ("tag", "import-image"):
        resources = ["imagestreams.image.openshift.io"]
    elif verb in ("new-app", "new-build", "run"):
        resources = ["pods"]
    # Kubernetes resource categories are extensible, including by cluster-scoped CRDs.
    # Expand the shipped delete-all exercise to known namespaced types before execution.
    if write and "all" in resources:
        expansion = "pods,services,replicationcontrollers,deployments.apps,replicasets.apps,statefulsets.apps,daemonsets.apps,jobs.batch,cronjobs.batch,buildconfigs.build.openshift.io,builds.build.openshift.io,deploymentconfigs.apps.openshift.io,routes.route.openshift.io,imagestreams.image.openshift.io"
        resources = [part for resource in resources for part in (expansion.split(",") if resource == "all" else [resource])]
        target = restpos[0]
        expanded_target = ",".join(part for resource in target.split(",") for part in (expansion.split(",") if resource == "all" else [resource]))
        actual[actual.index(target)] = expanded_target
    scopes = [resource_scope(r, table) for r in resources]
    cluster_scoped = "cluster-scoped" in scopes
    if write and "unknown" in scopes:
        unknown = next(r for r, scope in zip(resources, scopes) if scope == "unknown")
        raise Refused(f"resource type `{unknown.split('/')[0]}` has unknown scope; writes need a known namespaced resource")
    if verb == "delete" and any(r.split("/")[0].split(".")[0] in ("project", "projects", "namespace", "namespaces", "ns") for r in resources):
        raise Refused("lab projects are removed by lab cleanup only")
    if write and cluster_scoped:
        raise Refused("cluster-scoped objects cannot be changed from the Workbench; use the lab's explicit elevated step")
    if ns is None and not all_ns and not cluster_scoped and verb not in ("api-resources", "api-versions", "version", "whoami", "explain", "projects", "adm") and key != "auth whoami":
        ns = default_ns
    if write:
        if identity != "learner":
            raise Refused("the reader identity is read-only; remote execution and object changes need the learner")
        if ns is None:
            raise Refused("writes and remote execution need -n academy-… (a lab project)")
    if ns is not None:
        if ns == config.SYSTEM_NS:
            raise Refused("academy-system belongs to the academy itself; choose a lab project")
        if identity == "learner" and not NS_RE.fullmatch(ns):
            raise Refused("the learner works in academy-* projects; use the reader identity to inspect other namespaces")
        if identity == "reader" and not re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", ns):
            raise Refused("invalid namespace")
    if verb in ("tag", "import-image"):
        # `<namespace>/<stream>:<tag>` names its own namespace, which would bypass -n. Only a registry host (with a
        # dot or a port) makes an external image reference; anything else before the slash is a project.
        for ref in restpos:
            first = ref.split("/")[0] if "/" in ref else None
            if first and not ("." in first or ":" in first) and first != ns:
                raise Refused(f"`{ref}` names the project `{first}`; image stream references stay in the lab project ({ns or '-n academy-…'})")
    if identity == "reader" and any(r.split("/")[0].split(".")[0] in ("secret", "secrets") for r in resources):
        raise Refused("Secret data is never read by the reader identity; inspect lab Secrets as the learner")
    # Strip leading options by putting the verb first (oc accepts global flags anywhere).
    for part in key.split():
        actual.remove(part)
        shown.remove(part)
    final = [*key.split(), *actual]
    display_args = [*key.split(), *shown]
    if ns is not None:
        final += ["-n", ns]; display_args += ["-n", ns]
    if tail:
        final += ["--", *tail]; display_args += ["--", *tail]
    return Plan(final, shlex.join([tool, *display_args]), identity, write, ns, stdin_allowed)


def plan_helm(args: list[str], identity: str, default_ns: str | None, labdir: str | None) -> Plan:
    if identity != "learner":
        raise Refused("helm runs as the learner")
    tokens = _tokens(args, HELM_FLAGS)
    pos = [v for n, v in tokens if not n]
    if not pos:
        raise Refused("missing helm subcommand")
    key = _path(pos, HELM_FLAGS)
    spec = {**GLOBAL, **HELM_FLAGS[key]}
    ns = None
    actual: list[str] = []
    shown: list[str] = []
    for name, value in tokens:
        if name:
            if name not in spec:
                raise Refused(f"helm flag `{name}` is not allowed with `{key}`")
            if name in ("-n", "--namespace"):
                if ns is not None and ns != value:
                    raise Refused("conflicting namespace flags; choose one -n academy-…")
                ns = value; continue
            if name in ("-o", "--output"):
                _check_output(value)
            if name in ("-f", "--values"):
                actual.extend([name, _labfile(value, labdir)]); shown.extend([name, value])
                continue
            flag = name + ("=" + value if value is not None else "")
            actual.append(flag); shown.append(flag)
        else:
            mapped = _labfile(value, labdir) if value.startswith("lab/") else value
            actual.append(mapped); shown.append(value)
    if pos[0] in ("install", "upgrade", "template", "show", "lint"):
        charts = pos[len(key.split()):]
        chart = charts[-1] if charts else ""
        if not chart.startswith("lab/"):
            raise Refused("charts must come from the current lab (lab/<chart>)")
    arguments = pos[len(key.split()):]
    expected = {"install": (2,), "upgrade": (2,), "uninstall": (1,), "rollback": (2,), "template": (1, 2), "history": (1,), "status": (1,), "list": (0,), "ls": (0,)}
    if key.startswith(("get ", "show ")):
        sizes = (1,)
    else:
        sizes = expected.get(key)
    if sizes is not None and len(arguments) not in sizes:
        raise Refused(f"helm {key} needs {'a release and lab chart' if key in ('install', 'upgrade') else 'the supported number of arguments'}; rollback needs a release and explicit revision")
    if key == "lint" and any(not arg.startswith("lab/") for arg in arguments):
        raise Refused("charts must come from the current lab (lab/<chart>)")
    # Keep positionals before options so validation can identify the exact release/chart.
    positionals = [_labfile(v, labdir) if v.startswith("lab/") else v for v in pos]
    option_args = actual.copy()
    for value in positionals:
        option_args.remove(value)
    actual = [*positionals, *option_args]
    ns = ns or default_ns
    if ns is None or not NS_RE.fullmatch(ns) or ns == config.SYSTEM_NS:
        raise Refused("helm needs -n academy-… (a lab project)")
    for part in key.split():
        actual.remove(part)
        shown.remove(part)
    return Plan([*key.split(), *actual, "-n", ns], shlex.join(["helm", *key.split(), *shown, "-n", ns]), identity,
                pos[0] in HELM_VERBS_WRITE, ns, tool="helm")
