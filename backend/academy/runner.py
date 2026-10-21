"""One execution path for commands, shared by the Workbench API and the recorder.

Because the recorder runs every lab command through this function, a recorded command is guaranteed to be
accepted by the Workbench policy, and a policy change that breaks a lesson fails the recordings.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from . import kube, labs, manifests, policy


# Retained for existing imports; the shared module owns all object validation.
check_manifests = manifests.check_manifests


def _validate_helm(p: policy.Plan, timeout: int) -> None:
    """Validate rendered/new AND existing objects before a release mutation.

    Rendering uses only fixed lab charts and policy-checked values. Helm lookup and
    post-renderer/server dry-run options are unavailable. Release ownership still
    belongs to the lifecycle owner; manifest scope is only this validation boundary.
    """
    verb = p.argv[0]
    if verb not in policy.HELM_VERBS_WRITE:
        return
    # Values and namespace are separate argv values, so find release before any flags.
    release = p.argv[1] if len(p.argv) > 1 and not p.argv[1].startswith("-") else None
    if not release:
        raise manifests.ManifestRefused("put the Helm release name immediately after the subcommand")

    def check_result(args: list[str]) -> None:
        result = kube.helm(p.identity, args, timeout=timeout)
        if not result.ok:
            raise manifests.ManifestRefused("Helm manifests could not be inspected; fix the release/chart before retrying")
        manifests.validate_manifests(result.stdout, p.namespace, namespace_mode="check")

    if verb in ("upgrade", "uninstall", "rollback"):
        for field in ("manifest", "hooks"):
            check_result(["get", field, release, "-n", p.namespace])
    if verb == "rollback":
        revision = p.argv[2] if len(p.argv) > 2 and not p.argv[2].startswith("-") else "0"
        if not revision.isdigit() or revision == "0":
            raise manifests.ManifestRefused("rollback needs an explicit positive revision so its manifests can be checked; use `helm history` first")
        for field in ("manifest", "hooks"):
            check_result(["get", field, release, "--revision", revision, "-n", p.namespace])
    if verb in ("install", "upgrade"):
        if len(p.argv) < 3 or p.argv[2].startswith("-"):
            raise manifests.ManifestRefused("put the lab chart immediately after the Helm release name")
        render = ["template", release, p.argv[2], "-n", p.namespace, "--include-crds"]
        i = 3
        while i < len(p.argv):
            flag = p.argv[i]
            name = flag.split("=", 1)[0]
            if name in ("--set", "--set-string", "-f", "--values"):
                render.append(flag)
                if "=" not in flag:
                    i += 1
                    render.append(p.argv[i])
            i += 1
        own_tmp: str | None = None  # the only file this function may delete
        if verb == "upgrade":
            render.append("--is-upgrade")
            # Validation must not change what the learner's command does. When the command supplies no values,
            # `helm upgrade` reuses the release's previous values (an empty values file supplies none either), so
            # render with those too.
            resets = any(a.split("=", 1)[0] == "--reset-values" and a.partition("=")[2].lower() not in ("false", "0") for a in p.argv)
            if not resets and not _supplies_values(p.argv):
                prev = kube.helm(p.identity, ["get", "values", release, "-n", p.namespace, "-o", "yaml"], timeout=timeout)
                if not prev.ok:
                    raise manifests.ManifestRefused("the release's current values could not be read; pass the values explicitly with --set")
                if prev.stdout.strip() and prev.stdout.strip() != "null":
                    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8", newline="\n") as f:
                        f.write(prev.stdout)
                    own_tmp = f.name
                    render += ["-f", own_tmp]
        try:
            check_result(render)
        finally:
            if own_tmp:
                Path(own_tmp).unlink(missing_ok=True)


def _supplies_values(argv: list[str]) -> bool:
    """Does this Helm command line supply any value? --set flags do; a values file does only if it is not empty."""
    i = 0
    while i < len(argv):
        name, _, inline = argv[i].partition("=")
        if name in ("--set", "--set-string", "--set-file", "--set-json"):
            return True
        if name in ("-f", "--values"):
            path = inline or (argv[i + 1] if i + 1 < len(argv) else "")
            try:
                if yaml.safe_load(Path(path).read_text(encoding="utf-8")) not in (None, {}):
                    return True
            except (OSError, yaml.YAMLError):
                return True  # unreadable: assume it supplies values (Helm itself will fail on it)
            if not inline:
                i += 1
        i += 1
    return False


def _validate_inputs(p: policy.Plan, stdin: str | None, timeout: int) -> str | None:
    if p.stdin_allowed:
        if not stdin:
            raise manifests.ManifestRefused("paste YAML in the editor to use -f -")
        stdin = yaml.safe_dump_all(manifests.validate_manifests(stdin, p.namespace), sort_keys=False)
    if p.tool == "helm":
        _validate_helm(p, timeout)
        return stdin
    # Lab file manifests cross the same boundary as editor input. Replace file input
    # with the normalized YAML so every namespaced object explicitly carries its target.
    documents: list[dict] = []
    indices: list[int] = []
    for i, flag in enumerate(p.argv[:-1]):
        if flag not in ("-f", "--filename", "-k", "--kustomize") or p.argv[i + 1] == "-":
            continue
        path = Path(p.argv[i + 1])
        if flag in ("-k", "--kustomize"):
            rendered = kube.oc(p.identity, ["kustomize", str(path)], timeout=timeout)
            if not rendered.ok:
                raise manifests.ManifestRefused("the lab Kustomize manifest could not be rendered; check the lab files")
            text = rendered.stdout
        else:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                raise manifests.ManifestRefused("the lab manifest cannot be read; run lab setup or use the YAML editor") from None
        documents.extend(manifests.validate_manifests(text, p.namespace))
        indices.extend([i, i + 1])
    if indices:
        if stdin:
            documents.extend(list(yaml.safe_load_all(stdin)))
        p.argv = [a for i, a in enumerate(p.argv) if i not in indices] + ["-f", "-"]
        p.stdin_allowed = True
        stdin = yaml.safe_dump_all(documents, sort_keys=False)
    return stdin


def execute(command: str, identity: str = "learner", namespace: str | None = None, lab: "labs.Lab | None" = None,
            stdin: str | None = None, timeout: int = 60) -> dict:
    labdir = str(labs.labfiles_dir(lab)) if lab and lab.files else None
    try:
        p = policy.plan(command, identity, namespace or (lab.namespace if lab else None), labdir)
    except policy.Refused as e:
        return {"refused": True, "reason": str(e)}
    if stdin and not p.stdin_allowed:
        return {"refused": True, "reason": "YAML input is only accepted with `apply|create|replace|delete|diff -f -`"}
    try:
        stdin = _validate_inputs(p, stdin, timeout)
    except manifests.ManifestRefused as e:
        return {"refused": True, "reason": str(e)}
    if p.tool == "helm":
        r = kube.helm(p.identity, p.argv, timeout=timeout)  # type: ignore[arg-type]
    else:
        r = kube.oc(p.identity, p.argv, stdin=stdin if p.stdin_allowed else None, timeout=timeout)  # type: ignore[arg-type]
    out = r.public()
    out["command"] = p.display
    return {"display": p.display, "write": p.write, "verb": p.argv[0], "tool": p.tool, **out}
