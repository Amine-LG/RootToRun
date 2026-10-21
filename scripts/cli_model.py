"""Build the option model of `oc` and `kubectl` that the command checker uses (frontend/src/lib/climodel.json).

The model comes from the real client, never from memory: every command path is read from `<client> <path> --help`
(subcommands, aliases, options, whether an option takes a value and whether it can be repeated), and every option
that takes a value is tried without one, to learn which may stand alone (`--dry-run`). Only the command paths that the
course uses (accepted answers and recorded commands) are kept, with the subcommand names of every command on the way, so that a typed command
can be resolved to its path exactly as the client does.

The options come from the client alone (a kubeconfig that does not exist). Resource names come from the training
cluster's API discovery, read as the ordinary user developer, only with --server; without it the committed resource
names are kept and nothing contacts a cluster.

    .venv/bin/python scripts/cli_model.py [--server]            # regenerate
    .venv/bin/python scripts/cli_model.py --check [--server]    # exit 1 when the committed model is out of date
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "src" / "lib" / "climodel.json"
OC = os.environ.get("ACADEMY_OC") or shutil.which("oc") or str(Path.home() / ".crc" / "bin" / "oc" / "oc")
SANDBOX = Path(tempfile.mkdtemp(prefix="cli-model-"))  # HOME and container storage of every program run here
for d in ("home", "xdg", "root", "run"):
    (SANDBOX / d).mkdir()
ENV = {"HOME": str(SANDBOX / "home"), "XDG_RUNTIME_DIR": str(SANDBOX / "xdg"), "XDG_CONFIG_HOME": str(SANDBOX / "home"),
       "XDG_DATA_HOME": str(SANDBOX / "home"), "PATH": "/usr/bin:/bin", "KUBECONFIG": "/nonexistent", "LANG": "C"}
OPT = re.compile(r"^\s{4}(?:-(\w), )?--([\w-]+)=(.*):$")  # oc's own help format
COBRA_OPT = re.compile(r"^\s+(?:-(\w), )?--([\w-]+)(?: (\S+))?\s{2,}(.*)$")  # cobra's default format
LIST_TYPES = {"strings", "stringArray", "stringSlice", "ints", "uints", "stringToString"}
# the programs modelled, how their help is laid out, and what their version command is. podman runs with its own
# empty storage (only `--help` and option parsing are exercised; nothing is created).
SPECS = {
    "oc": {"exe": OC, "style": "oc", "version": ["version", "--client"]},
    "kubectl": {"exe": OC, "style": "oc", "version": ["version", "--client"]},
    "podman": {"exe": shutil.which("podman"), "style": "cobra", "version": ["--version"],
               "isolate": ["--root", str(SANDBOX / "root"), "--runroot", str(SANDBOX / "run"), "--storage-driver", "vfs", "--events-backend", "none"]},
    "skopeo": {"exe": shutil.which("skopeo"), "style": "cobra", "version": ["--version"]},
    "helm": {"exe": shutil.which("helm") or str(Path.home() / "bin" / "helm"), "style": "cobra", "version": ["version", "--short"]},
}


def client(program: str, args: list[str]) -> subprocess.CompletedProcess:
    # `kubectl` is the Kubernetes client built into oc, selected by the name it is invoked as
    return subprocess.run([program, *args], executable=SPECS[program]["exe"], capture_output=True, text=True, encoding="utf-8", env=ENV,
                          timeout=30, stdin=subprocess.DEVNULL, cwd=SANDBOX)


def section(text: str, title: str) -> list[str]:
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip().rstrip(":") == title)
    except StopIteration:
        return []
    out = []
    for ln in lines[start + 1:]:
        if ln and not ln.startswith(" ") and not ln.startswith("\t"):
            break
        out.append(ln)
    return out


def options(text: str, title: str) -> dict:
    flags = {}
    for ln in section(text, title):
        m = OPT.match(ln)
        if m:
            short, name, default = m.groups()
            kind = "bool" if default in ("true", "false") else "list" if default.startswith("[") else "value"
            flags[name] = {"short": short or "", "kind": kind, **({"default": default == "true"} if kind == "bool" else {})}
            continue
        m = COBRA_OPT.match(ln)
        if m:
            short, name, typ, desc = m.groups()
            kind = "bool" if not typ else "list" if typ in LIST_TYPES or "(default [" in desc else "value"
            flags[name] = {"short": short or "", "kind": kind, **({"default": "(default true)" in desc} if kind == "bool" else {})}
    return flags


def node(program: str, path: list[str]) -> dict:
    text = client(program, [*path, "--help"]).stdout
    subs = {}
    listing = False  # inside a "… Commands:" heading (the root groups its commands under several)
    for ln in text.splitlines():
        if ln and not ln[0].isspace():
            listing = ln.rstrip().endswith(":") and "Commands" in ln
            continue
        m = re.match(r"^\s{2}([a-z][\w-]*)\s", ln)
        if listing and m:
            subs[m.group(1)] = True
    lines = text.splitlines()
    at = next((i for i, ln in enumerate(lines) if ln.strip() == "Aliases:"), None)  # the next line lists them, unindented
    aliases = [a.strip() for a in lines[at + 1].split(",")[1:] if a.strip()] if at is not None and at + 1 < len(lines) else []
    flags = {**options(text, "Options"), **options(text, "Flags")}
    return {"subs": sorted(subs), "aliases": aliases, "flags": flags, "globals": options(text, "Global Flags"), "text": text}


def course_commands() -> list[str]:
    out = []

    def walk(x):
        if isinstance(x, dict):
            if x.get("kind") == "try" and "accept" in x:
                out.extend(x["accept"])
            for k in ("cmd", "run"):  # recorded commands too, so that the model covers every command the course uses
                if isinstance(x.get(k), str):
                    out.append(x[k])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for f in sorted((ROOT / "content" / "en").rglob("*.yaml")):
        walk(yaml.safe_load(f.read_text(encoding="utf-8")))
    return out


def words(cmd: str) -> list[str] | None:
    if re.search(r"[|;&<>`$()\\]", cmd):
        return None
    try:
        return shlex.split(cmd)
    except ValueError:
        return None


def build() -> dict:
    model: dict = {}
    for program, spec in SPECS.items():
        if not spec["exe"] or not Path(spec["exe"]).exists():
            print(f"skipped {program}: not installed")
            continue
        cache: dict[tuple, dict] = {}

        def get(path: tuple) -> dict:
            if path not in cache:
                cache[path] = node(program, list(path))
            return cache[path]

        if spec["style"] == "oc":
            r = client(program, ["options"])  # oc prints this listing on stderr, kubectl on stdout
            glob = options(r.stdout + r.stderr, "The following options can be passed to any command")
        else:
            glob = {}  # filled below: only the root flags a subcommand really accepts (persistent ones)
        used: set[tuple] = set()
        for cmd in course_commands():
            w = words(cmd)
            if not w or w[0] != program:
                continue
            path: tuple = ()
            here = get(path)
            args = w[1:]
            i = 0
            while i < len(args):
                a = args[i]
                if a == "--":
                    break
                if a.startswith("-") and len(a) > 1:
                    name = a.lstrip("-").split("=", 1)[0]
                    f = here["flags"].get(name) or glob.get(name) or next(
                        (v for v in [*here["flags"].values(), *glob.values()] if len(name) == 1 and v["short"] == name), None)
                    if f and f["kind"] != "bool" and "=" not in a and not (len(a) > 2 and a[1] != "-"):
                        i += 1
                    i += 1
                    continue
                child = next((s for s in here["subs"] if s == a or a in get(path + (s,))["aliases"]), None) if here["subs"] else None
                if child is None:
                    break
                path = path + (child,)
                here = get(path)
                i += 1
            used.add(path)
        for path in used:
            glob.update({k: v for k, v in get(path).get("globals", {}).items() if k not in glob})
        if spec["style"] == "cobra":
            # a root flag is inherited only if it is persistent: ask a subcommand to parse it (with --help, so that
            # nothing runs); `podman ps --version` is an unknown flag
            probe_path = next((list(p) for p in sorted(used) if p), [])
            for name, f in get(())["flags"].items():
                if name in glob or name == "help":
                    continue
                arg = f"--{name}=false" if f["kind"] == "bool" else f"--{name}=x"
                r = client(program, [*probe_path, arg, "--help"])
                if "unknown flag" not in (r.stdout + r.stderr):
                    glob[name] = f
        keep: dict[str, dict] = {}
        for path in sorted(used):
            for k in range(len(path) + 1):
                p = path[:k]
                n = get(p)
                key = " ".join(p)
                entry = keep.setdefault(key, {"subs": {}, "aliases": n["aliases"]})
                if k < len(path):
                    continue
                entry["flags"] = {k2: v for k2, v in n["flags"].items() if k2 not in glob or not p} if spec["style"] == "cobra" else n["flags"]
            for k in range(len(path)):
                p = path[:k]
                key = " ".join(p)
                for s in get(p)["subs"]:
                    keep[key]["subs"][s] = get(p + (s,))["aliases"]
        # an option that takes a value, given without one: the program says "needs an argument" unless it has a
        # default for that case (pflag's NoOptDefVal, e.g. --dry-run)
        iso = spec.get("isolate", [])
        for key, entry in keep.items():
            for name, f in entry.get("flags", {}).items():
                if f["kind"] in ("value", "list"):
                    r = client(program, [*iso, *key.split(), f"--{name}"] if key else [*iso, f"--{name}"])
                    if "needs an argument" not in r.stderr:
                        f["optional"] = True
        probe = spec["version"]
        for name, f in glob.items():
            if f["kind"] in ("value", "list") and "needs an argument" not in client(program, [*iso, *probe, f"--{name}"]).stderr:
                f["optional"] = True
        out = client(program, probe)
        version = (out.stdout or out.stderr).strip().splitlines()[0]
        model[program] = {"version": version, "globals": glob, "commands": keep}
    return model


LEARNER = ROOT / "data" / "kube" / "learner.kubeconfig"


def kinds() -> dict:
    """Resource names as the client resolves them, from the training cluster's API discovery, read as the ordinary
    user developer (discovery is open to every logged-in user; nothing else is read). Plural, singular and short
    names map to `kind.group`; a name that two resources share resolves as the client resolves it (`oc explain`), so
    `ip` is IPAddress (networking.k8s.io) on Kubernetes 1.33+, not InstallPlan."""
    env = {**ENV, "KUBECONFIG": str(LEARNER)}
    r = subprocess.run([OC, "api-resources", "-o", "wide"], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
    if r.returncode != 0:
        sys.exit(f"api-resources failed (is the learner kubeconfig connected?): {r.stderr[:200]}")
    lines = r.stdout.splitlines()
    head = lines[0]
    cols = [head.index(c) for c in ("NAME", "SHORTNAMES", "APIVERSION", "NAMESPACED", "KIND", "VERBS")]
    words: dict[str, set[str]] = {}
    qualified: dict[str, str] = {}
    for ln in lines[1:]:
        cut = lambda k: ln[cols[k]:cols[k + 1]].strip()  # noqa: E731
        name, short, apiv, kind = cut(0), cut(1), cut(2), cut(4)
        group = apiv.rsplit("/", 1)[0] if "/" in apiv else ""
        canon = f"{kind.lower()}.{group}" if group else kind.lower()
        for w in {name, kind.lower(), *[x for x in short.split(",") if x]}:
            words.setdefault(w, set()).add(canon)
        if group:
            for w in (name, kind.lower()):
                qualified[f"{w}.{group}"] = canon
    resolve = {}
    for w, targets in sorted(words.items()):
        if len(targets) == 1:
            resolve[w] = next(iter(targets))
            continue
        e = subprocess.run([OC, "explain", w], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60).stdout
        g = re.search(r"^GROUP:\s*(\S*)", e, re.M)
        k = re.search(r"^KIND:\s*(\S+)", e, re.M)
        if k:
            resolve[w] = f"{k.group(1).lower()}.{g.group(1)}" if g and g.group(1) else k.group(1).lower()
    return {"resolve": resolve, "qualified": qualified}


def main() -> int:
    model = build()
    if "--server" in sys.argv:  # resource names from the training cluster's discovery: only when asked for
        model["kinds"] = kinds()
        v = subprocess.run([OC, "version", "-o", "json"], capture_output=True, text=True, encoding="utf-8", env={**ENV, "KUBECONFIG": str(LEARNER)})
        model["kinds"]["cluster"] = json.loads(v.stdout or "{}").get("serverVersion", {}).get("gitVersion", "")
    else:  # keep the committed resource names; nothing contacts a cluster
        model["kinds"] = json.loads(OUT.read_text(encoding="utf-8"))["kinds"] if OUT.exists() else sys.exit("first run: pass --server")
    text = json.dumps(model, indent=None, sort_keys=True, separators=(",", ":")) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is out of date: run scripts/cli_model.py")
            return 1
        print("cli model up to date")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    n = {p: len(m["commands"]) for p, m in model.items() if "commands" in m}
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text) // 1024} KiB): command paths {n}; {model['oc']['version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
