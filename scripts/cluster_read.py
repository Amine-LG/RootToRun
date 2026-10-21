"""Read-only access to the training cluster, for preparing administration lessons.

    .venv/bin/python scripts/cluster_read.py [--as admin|developer] <oc arguments>

Runs `oc` as the cluster administrator (the `crc-admin` context of ~/.kube/config, used in place) or as the ordinary
user developer (the academy's learner kubeconfig), but only for commands that change nothing: get, describe,
explain, api-resources, api-versions, auth can-i, auth whoami, whoami, version, (adm) policy who-can, logs, events,
adm node-logs, and create/apply/patch/set/label/annotate with --dry-run=server or --dry-run=client (never `oc adm
policy add-…`: it creates ClusterRoles despite --dry-run), and only with the options listed below: the connection,
the identity (except `auth can-i --as`), watches and output files cannot be chosen. Anything else is refused:
changes go through the recorder (scripts/record.py --lessons --admin), which saves the original state, rolls back
and verifies. This is a guard for the maintainer's own use, not a sandbox: it runs the real `oc` with the
administrator's credentials.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OC = os.environ.get("ACADEMY_OC") or shutil.which("oc") or str(Path.home() / ".crc" / "bin" / "oc" / "oc")
READ = re.compile(r"^(get|describe|explain|api-resources|api-versions|auth can-i|auth whoami|whoami|version|"
                  r"adm policy who-can|policy who-can|logs|events|adm node-logs|adm top|status|projects|"
                  r"adm policy scc-subject-review|adm policy scc-review|policy scc-subject-review|policy scc-review)( |$)")
# `oc adm policy add-scc-to-*` creates the system:openshift:scc:<name> ClusterRole for real before honouring
# --dry-run (seen on 4.21.8, 2026-10-16), so no policy command is allowed here, dry run or not
DRY = re.compile(r"^(create|apply|patch|set|label|annotate)( |$)")


# Options are checked one by one, as oc's parser (pflag) reads them: `--name=value`, `--name value`, `-xvalue`,
# `-x value`, and `_` read as `-` in names. An option that is not listed here is refused, so that no value can be
# mistaken for the command, and no option can redirect the connection, change the identity or write a local file.
VALUE_OPTS = {"namespace", "output", "selector", "field-selector", "sort-by", "label-columns", "container", "tail",
              "since", "since-time", "limit-bytes", "api-group", "verbs", "api-version", "for", "types", "unit", "path",
              "subresource", "template", "chunk-size", "request-timeout"}
FLAG_OPTS = {"all-namespaces", "show-labels", "no-headers", "show-kind", "ignore-not-found", "previous", "timestamps",
             "all-containers", "recursive", "client", "list", "quiet", "show-managed-fields",
             "namespaced", "cached", "no-truncate", "show-server"}
SHORT = {"n": "namespace", "o": "output", "l": "selector", "L": "label-columns", "c": "container", "A": "all-namespaces",
         "q": "quiet", "u": "unit"}
# only with a dry run (create, apply, patch, set, label, annotate); -f is a file name here, never "follow"
DRY_VALUE_OPTS = {"filename", "dry-run", "type", "patch", "field-manager", "validate", "role", "clusterrole", "user",
                  "group", "serviceaccount", "image", "from-literal", "from-file", "from-env-file", "env", "resource",
                  "verb", "resource-name", "port", "replicas", "labels", "containers", "selector"}
# `--validate` alone means true (pflag's optional value): it never takes the next word
DRY_FLAG_OPTS = {"overwrite", "server-side", "save-config", "all", "local", "recursive", "force-conflicts", "validate"}
# the subjects of a binding; anywhere else `--user` would choose another kubeconfig user
SUBJECT_OPTS = {"user", "group", "serviceaccount"}
DRY_SUBCOMMANDS = {"create": {"configmap", "secret", "rolebinding", "clusterrolebinding", "role", "clusterrole",
                              "serviceaccount", "namespace", "deployment", "service", "route", "job", "cronjob",
                              "quota", "priorityclass", "ingress", "poddisruptionbudget"},
                   "set": {"env", "image", "resources", "probe", "serviceaccount", "selector", "triggers", "data",
                           "volumes", "deployment-hook", "route-backends"}}
DRY_SHORT = {"f": "filename", "p": "patch", "R": "recursive"}
# impersonation only to ask "can this subject do it?"
CAN_I_VALUE_OPTS = {"as", "as-group"}


def refusal(args: list[str]) -> str | None:
    """Why `oc <args>` is refused here, or None if it changes nothing. Every option must be known; the command is
    read from the words that are not options or option values, exactly as oc would read them."""
    if not args or args[0].startswith("-"):
        return "write the command first, then its options"
    words, opts = [], []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--" or a == "-":
            return f"`{a}` is not allowed here"
        if a.startswith("--"):
            name, eq, value = a[2:].partition("=")
            name = name.replace("_", "-")
            if name == "dry-run" and not eq:
                return "write the dry run as --dry-run=client or --dry-run=server"
            opts.append((name, value if eq else None, a))
            if not eq and name not in FLAG_OPTS | DRY_FLAG_OPTS:  # a value in the next word
                if i + 1 >= len(args):
                    return f"`{a}` needs a value"
                opts[-1] = (name, args[i + 1], a)
                i += 1
        elif a.startswith("-") and len(a) > 1:
            letter, rest = a[1], a[2:]
            long = SHORT.get(letter) or DRY_SHORT.get(letter)
            if not long:
                return f"the option `{a}` is not allowed here"
            if long in FLAG_OPTS | DRY_FLAG_OPTS:
                if rest:  # a cluster of single-letter options, such as -Aw
                    return f"`{a}`: write single-letter options separately"
                opts.append((long, None, a))
            else:
                if rest.startswith("="):  # `-o=` is an explicitly empty value: nothing more is read
                    opts.append((long, rest[1:], a))
                    i += 1
                    continue
                if not rest:
                    if i + 1 >= len(args):
                        return f"`{a}` needs a value"
                    rest = args[i + 1]
                    i += 1
                opts.append((long, rest, a))
        else:
            words.append(a)
        i += 1
    path = " ".join(words[:3])
    line = " ".join(args)
    read, dry = READ.match(path), DRY.match(path)
    if not (read or dry):
        return f"`oc {line}` is not a read-only command"
    allowed = VALUE_OPTS | FLAG_OPTS
    if dry:
        allowed = allowed | DRY_VALUE_OPTS | DRY_FLAG_OPTS
        sub_ = DRY_SUBCOMMANDS.get(words[0])
        if sub_ is not None and len(words) > 1 and words[1] not in sub_:
            return f"`oc {words[0]} {words[1]}` is not one of the dry runs this helper knows"
        if words[:2] not in (["create", "rolebinding"], ["create", "clusterrolebinding"]):
            allowed = allowed - SUBJECT_OPTS
    if path.startswith("auth can-i"):
        allowed = allowed | CAN_I_VALUE_OPTS
    for name, value, raw in opts:
        if name not in allowed:
            return f"the option `{raw}` is not allowed here (connection, identity, output files and watches are fixed)"
        if name == "filename" and not dry:
            return f"`{raw}`: -f is only allowed with a dry run"
    if dry:
        runs = [v for n, v, _ in opts if n == "dry-run"]
        if runs not in (["client"], ["server"]):
            return f"`oc {line}` needs exactly one --dry-run=client or --dry-run=server"
    return None


def main() -> int:
    args = sys.argv[1:]
    who = "developer"
    if args[:1] == ["--as"]:
        who, args = args[1], args[2:]
    if who not in ("admin", "developer"):
        sys.exit("--as admin or --as developer")
    why = refusal(args)
    if why:
        sys.exit(f"refused: {why}. Cluster changes go through the recorder.")
    if who == "admin":
        main = Path.home() / ".kube" / "config"
        conn = [f"--kubeconfig={main}", "--context=crc-admin"]
        crc = Path.home() / ".crc" / "machines" / "crc" / "kubeconfig"  # after a reset, CRC's own file (context admin)
        if crc.exists() and (not main.exists() or "crc-admin" not in main.read_text(encoding="utf-8", errors="replace")):
            conn = [f"--kubeconfig={crc}", "--context=admin"]
    else:
        conn = [f"--kubeconfig={ROOT / 'data' / 'kube' / 'learner.kubeconfig'}"]
    env = {"HOME": os.environ.get("HOME", "/tmp"), "PATH": "/usr/bin:/bin", "LANG": "C"}
    return subprocess.run([OC, *conn, *args], env=env, timeout=120).returncode


if __name__ == "__main__":
    sys.exit(main())
