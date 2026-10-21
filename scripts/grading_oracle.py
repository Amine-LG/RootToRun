"""Check the practice-step command checker (frontend/src/lib/match.ts) against the real shell and the real client.

The checker never runs what a learner types; it compares it with the accepted forms of the task. This script finds
where that comparison disagrees with reality:

1. Every accepted form is given to the real `oc`/`kubectl` (client side only: the kubeconfig points at a closed local
   port, so nothing reaches a cluster). An accepted form the client itself rejects is a content error.
2. Near misses of every accepted form are generated (quotes removed or added, `kind/name` split or joined, words
   dropped or swapped, option values swapped, option spellings changed, misspelt options…) and graded by the real
   checker (through the vitest bridge, frontend/scripts/oracle.bridge.test.ts).
3. Every near miss the checker ACCEPTS is checked: bash must give the program the same words as for the accepted
   form up to the checker's documented equivalences, the client must not reject it, and, for read-only oc/kubectl
   commands, the two commands must give the same result when run as the ordinary user `developer` on the training
   cluster (only commands generated from the course's own accepted answers, never learner input; never an
   administrator).

Outputs: data/grading/ORACLE-REPORT.md (not committed), and frontend/src/lib/oracle.fixtures.json (real rejected and
real equivalent commands that the vitest suite replays). Needs the `oc` client (ACADEMY_OC, else `oc` on PATH, else
OpenShift Local's copy) and bubblewrap (`bwrap`): every client run is sandboxed, with only /usr, /etc and the client
visible read-only, a writable scratch directory and private (in-memory) /, /dev and /tmp, and without network. Step 3's comparison on a cluster runs only with --server, as the learner
connection of the local cluster mode (data/kube/learner.kubeconfig), still read-only on disk, and only for lines the
read-only cluster helper (scripts/cluster_read.py) accepts as reads.

    .venv/bin/python scripts/grading_oracle.py [--server] [--limit-steps N] [--file content/en/lessons/b4-network.yaml ...]
    (with --file or --limit-steps: a partial run that prints its findings and writes nothing)
"""
from __future__ import annotations

import json
import os
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OC = os.environ.get("ACADEMY_OC") or shutil.which("oc") or str(Path.home() / ".crc" / "bin" / "oc" / "oc")
LEARNER_KUBECONFIG = ROOT / "data" / "kube" / "learner.kubeconfig"
REPORT = ROOT / "data" / "grading" / "ORACLE-REPORT.md"
FIXTURES = ROOT / "frontend" / "src" / "lib" / "oracle.fixtures.json"
HOME = "/home/learner"
KINDS = {"pod", "pods", "po", "deployment", "deployments", "deploy", "service", "services", "svc", "user", "users",
         "group", "groups", "secret", "secrets", "configmap", "configmaps", "cm", "route", "routes", "node", "nodes",
         "project", "projects", "namespace", "namespaces", "ns", "role", "roles", "rolebinding", "rolebindings",
         "clusterrole", "clusterroles", "clusterrolebinding", "clusterrolebindings", "sa", "serviceaccount",
         "serviceaccounts", "pvc", "pv", "sc", "scc", "quota", "resourcequota", "limitrange", "limits", "identity",
         "identities", "template", "templates", "is", "imagestream", "istag", "job", "jobs", "cronjob", "cj"}
READ_PATHS = ("get", "describe", "explain", "api-resources", "api-versions", "auth can-i", "auth whoami", "whoami",
              "version", "policy who-can", "adm policy who-can", "rollout status", "rollout history", "logs", "status",
              "projects")  # never `project`: with a name it switches the learner kubeconfig's namespace
# commands that could reach a registry, a real server named on the line, or open a local port: never run here
LOCAL_RISK = re.compile(r"^(oc|kubectl) (login|logout|image|adm release|adm must-gather|registry|mirror|adm catalog|plugin|"
                        r"port-forward|proxy|attach|rsh|rsync|cp|debug|config|project|new-project)\b")
# options that would change where or as whom a command runs, or make the client write a file: never run here
UNSAFE_OPTION = re.compile(r"^(--(kubeconfig|context|server|cluster|user|token|username|password|as|as-group|as-uid|"
                           r"insecure-skip-tls-verify|certificate-authority|client-certificate|client-key|tls-server-name|"
                           r"cache-dir|profile|profile-output|log-file|log-dir)([=_-]|$)|-s)")


def unsafe(words: list[str]) -> bool:
    """True when the line cannot be run safely here: an option before the command (the command could then not be
    read reliably), an option that redirects the connection, the identity or a file, or a risky command."""
    return (len(words) < 2 or words[1].startswith("-") or LOCAL_RISK.match(" ".join(words)) is not None
            or any(UNSAFE_OPTION.match(w.replace("_", "-")) for w in words[1:]) or any("://" in w for w in words))


def try_steps() -> list[dict]:
    out = []

    def walk(x, f):
        if isinstance(x, dict):
            if x.get("kind") == "try" and "accept" in x:
                out.append({"file": f.name, "id": x["id"], "accept": x["accept"]})
            for v in x.values():
                walk(v, f)
        elif isinstance(x, list):
            for v in x:
                walk(v, f)

    for f in sorted((ROOT / "content" / "en").rglob("*.yaml")):
        walk(yaml.safe_load(f.read_text(encoding="utf-8")), f)
    return out


def raw_words(cmd: str) -> list[str] | None:
    """Words as typed (quotes kept), or None when the line uses shell syntax the checker only matches exactly."""
    words, cur, q, in_word = [], "", None, False
    for ch in cmd.strip():
        if q:
            if q == '"' and ch in "$`\\":
                return None  # bash would expand it inside double quotes (command substitution): only matched exactly
            cur += ch
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q, in_word = ch, True
            cur += ch
        elif ch.isspace():
            if in_word:
                words.append(cur)
            cur, in_word = "", False
        elif ch in "|;&<>`$()\\" or (ch == "#" and not in_word):
            return None
        else:
            cur += ch
            in_word = True
    if q:
        return None
    if in_word:
        words.append(cur)
    return words


def unquote(w: str) -> str:
    return w[1:-1] if len(w) >= 2 and w[0] == w[-1] and w[0] in "'\"" else w


def mutations(cmd: str) -> set[str]:
    w = raw_words(cmd)
    if not w or len(w) < 2:
        return set()
    out: set[str] = set()
    add = lambda ws: out.add(" ".join(ws))  # noqa: E731
    for i in range(1, len(w)):
        x = w[i]
        if unquote(x) != x:
            add(w[:i] + [unquote(x)] + w[i + 1:])                      # quotes removed
        elif re.search(r"[~*?\[{]", x):
            add(w[:i] + [f"'{x}'"] + w[i + 1:])                         # quotes added
        m = re.fullmatch(r"([A-Za-z.]+)/([^/]+)", unquote(x))
        if m and i >= 2:
            add(w[:i] + [m.group(1), m.group(2)] + w[i + 1:])           # kind/name split
            add(w[:i] + [m.group(1) + "s" if not m.group(1).endswith("s") else m.group(1)[:-1], m.group(2)] + w[i + 1:])
        if x in KINDS and i + 1 < len(w) and not w[i + 1].startswith("-"):
            add(w[:i] + [f"{x}/{w[i + 1]}"] + w[i + 2:])                 # kind name joined
        add(w[:i] + w[i + 1:])                                          # word dropped
        if i + 1 < len(w):
            add(w[:i] + [w[i + 1], w[i]] + w[i + 2:])                   # neighbours swapped
        if x.startswith("--") and len(x) > 4:
            name = x.split("=", 1)[0]
            add(w[:i] + [name[:-1] + x[len(name):]] + w[i + 1:])        # misspelt option
            if "=" in x:
                add(w[:i] + x.split("=", 1) + w[i + 1:])
        if re.fullmatch(r"-[a-zA-Z]", x) and i + 1 < len(w):
            add(w[:i] + [x + w[i + 1]] + w[i + 2:])                     # -n x -> -nx
            add(w[:i] + [x + "=" + w[i + 1]] + w[i + 2:])
            add(w[:i] + [x.upper() if x[1].islower() else x.lower(), w[i + 1]] + w[i + 2:])  # wrong case
        if x == "~" or unquote(x) == "~":
            add(w[:i] + [HOME] + w[i + 1:])
    # values of two options swapped
    opts = [i for i in range(1, len(w) - 1) if re.fullmatch(r"--?[A-Za-z][\w-]*", w[i]) and not w[i + 1].startswith("-")]
    for a in opts:
        for b in opts:
            if a < b and w[a + 1] != w[b + 1]:
                ws = list(w)
                ws[a + 1], ws[b + 1] = ws[b + 1], ws[a + 1]
                add(ws)
    out.discard(cmd)
    return out


def bridge(batch: list[dict]) -> list[dict]:
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in.json", Path(d) / "out.json"
        src.write_text(json.dumps(batch), encoding="utf-8")
        env = {**os.environ, "ORACLE_IN": str(src), "ORACLE_OUT": str(dst), "KUBECONFIG": "/nonexistent"}
        vitest = ROOT / "frontend" / "node_modules" / ".bin" / "vitest"  # the installed one: never fetched from a registry
        if not vitest.exists():
            sys.exit("frontend dependencies are not installed: cd frontend && npm ci")
        r = subprocess.run([str(vitest), "run", "scripts/oracle.bridge.test.ts"], cwd=ROOT / "frontend", env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=3600)
        if not dst.exists():
            sys.exit(f"vitest bridge failed:\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
        return json.loads(dst.read_text(encoding="utf-8"))


SCRATCH = Path(tempfile.mkdtemp(prefix="oracle-"))
BWRAP = shutil.which("bwrap")
_cr = importlib.util.spec_from_file_location("cluster_read", ROOT / "scripts" / "cluster_read.py")
cluster_read = importlib.util.module_from_spec(_cr)
_cr.loader.exec_module(cluster_read)


def jail(argv_: list[str], network: bool = False, extra_ro: tuple[Path, ...] = ()) -> list[str]:
    """`argv_` in a bubblewrap sandbox. Only /usr, /etc, the client binary and `extra_ro` are visible (read-only);
    the scratch directory and a private /tmp are writable; no other host path is mounted, so host sockets (/run,
    /var, home directories) cannot be reached. No network unless `network` (the --server comparison). A command line
    the checks below misjudge can then still not write to the host outside the scratch directory (the sandbox's own /,
    /dev and /tmp are private and discarded), and offline it reaches nothing."""
    if not BWRAP:
        sys.exit("the grading oracle runs the client in a sandbox and needs bubblewrap (`bwrap`, Linux)")
    real_oc = Path(OC).resolve()
    ro = []
    for path in (real_oc, *extra_ro):
        if not str(path).startswith(("/usr/", "/etc/")):
            ro += ["--ro-bind", str(path), str(path)]
    return [BWRAP, "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc", "--symlink", "usr/bin", "/bin",
            "--symlink", "usr/sbin", "/sbin", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
            "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", *ro, "--bind", str(SCRATCH), str(SCRATCH),
            "--chdir", str(EMPTY), "--die-with-parent", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
            *([] if network else ["--unshare-net"]), "--", *argv_]


def sandboxed(words: list[str], network: bool) -> list[str]:
    """The client as the line names it: `kubectl` keeps the Kubernetes behaviour of the same binary."""
    exe = Path(OC).resolve()
    if words[0] == "kubectl":
        link = SCRATCH / "bin" / "kubectl"
        if not link.exists():
            link.parent.mkdir(exist_ok=True)
            link.symlink_to(exe)
        exe = link
    extra = (LEARNER_KUBECONFIG.resolve().parent,) if network else ()
    return jail([str(exe), *words[1:]], network, extra)


FAKE = SCRATCH / "kubeconfig"
FAKE.write_text("apiVersion: v1\nkind: Config\nclusters: [{name: f, cluster: {server: 'https://127.0.0.1:9'}}]\n"
                "users: [{name: u, user: {token: none}}]\ncontexts: [{name: f, context: {cluster: f, user: u, namespace: demo}}]\n"
                "current-context: f\n", encoding="utf-8")
EMPTY = SCRATCH / "cwd"
EMPTY.mkdir()


def argv(cmd: str) -> list[str] | None:
    """The words bash gives the program (home /home/learner, an empty directory, so no glob matches)."""
    w = raw_words(cmd)
    if w is None:
        return None
    line = "__argv " + " ".join(w)
    # failglob: an unquoted pattern is an error rather than itself, so that two lines never look equivalent only
    # because this directory happens to hold no file the pattern would match
    r = subprocess.run(jail(["/bin/bash", "--noprofile", "--norc", "-O", "failglob", "-c", "__argv() { printf '%s\\0' \"$@\"; }; " + line]),
                       cwd=EMPTY, env={"HOME": HOME, "PATH": "/usr/bin:/bin", "LANG": "C"}, capture_output=True, text=True, encoding="utf-8", timeout=10)
    return [x for x in r.stdout.split("\0")[:-1]] if r.returncode == 0 else None


SERVER_SIDE = re.compile(r"127\.0\.0\.1:9|connection to the server|couldn't get current server|dial tcp|memcache\.go")
ENVIRONMENT = re.compile(r"no such file or directory|does not exist|is not a directory|cannot stat|path .* does not exist", re.I)


def client(words: list[str]) -> tuple[str, str]:
    """`ok` (parsed; it would contact the server), `rejected` (the client refuses the command line itself) or `env`
    (it needs a local file this scratch directory does not have)."""
    if words[0] not in ("oc", "kubectl") or unsafe(words):
        return "skipped", ""
    try:
        r = subprocess.run(sandboxed(words, network=False), cwd=EMPTY, env={"HOME": str(SCRATCH), "PATH": "/usr/bin:/bin", "KUBECONFIG": str(FAKE), "LANG": "C"},
                           capture_output=True, text=True, encoding="utf-8", timeout=20, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "timeout", ""
    text = (r.stderr + r.stdout).strip()
    if r.returncode == 0 or SERVER_SIDE.search(text):
        return "ok", ""
    first = next((ln for ln in text.splitlines() if ln.strip() and "memcache" not in ln), "")
    return ("env" if ENVIRONMENT.search(text) else "rejected"), first[:240]


NORMALISE = [(re.compile(r"\b\d+(\.\d+)?[smhdy](\d+[smh])?\b"), "<age>"), (re.compile(r"\d{4}-\d\d-\d\dT[\d:.]+Z"), "<time>"),
             (re.compile(r"resourceVersion: \"?\d+\"?"), "resourceVersion"), (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f-]{27}"), "<uid>")]


def server(words: list[str]) -> tuple[int, str] | None:
    """Run a read-only command as the ordinary user developer (never an administrator); None when not read-only."""
    line = " ".join(words)
    path = " ".join(w for w in words[1:4] if not w.startswith("-"))
    if unsafe(words) or not any(path == p or path.startswith(p + " ") for p in READ_PATHS):
        return None
    # only what the read-only cluster helper accepts as a read: options read as oc reads them, no dry-run writes
    if cluster_read.refusal(words[1:]) is not None or not cluster_read.READ.match(" ".join(w for w in words[1:4] if not w.startswith("-"))):
        return None
    # no watch or follow in any spelling (`-w`, `-Aw`, `--watch_only=true`, `-f=true`)
    if any(re.match(r"^--(watch|watch-only|follow)([=]|$)", w.replace("_", "-")) or re.match(r"^-[A-Za-z]*[wf]", w) for w in words[1:]):
        return None
    if not LEARNER_KUBECONFIG.exists():
        return None
    try:
        r = subprocess.run(sandboxed(words, network=True), cwd=EMPTY, env={"HOME": str(SCRATCH), "PATH": "/usr/bin:/bin", "KUBECONFIG": str(LEARNER_KUBECONFIG), "LANG": "C"},
                           capture_output=True, text=True, encoding="utf-8", timeout=30, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return (-1, "timeout")
    text = r.stdout + "\n" + r.stderr
    if "the server doesn't have a resource type" in text:
        return None  # an operator's kind that the training cluster does not run: nothing to compare
    for rx, rep in NORMALISE:
        text = rx.sub(rep, text)
    return r.returncode, text.strip()


def dry_run(words: list[str]) -> str | None:
    """The object an `oc create <generator>` line would send, built by the client alone (client dry run, no
    validation against the unreachable server); None when not such a line or when the client needs the server."""
    line = " ".join(words)
    if not re.match(r"^(oc|kubectl) create \S", line) or "--dry-run" in line or re.search(r"(^| )(-f|--filename|-k|--kustomize|--edit)\b", line):
        return None
    st, _ = client(words)
    if st != "ok":
        return None
    r = subprocess.run(sandboxed([*words, "--dry-run=client", "-o", "yaml", "--validate=false"], network=False), cwd=EMPTY,
                       env={"HOME": str(SCRATCH), "PATH": "/usr/bin:/bin", "KUBECONFIG": str(FAKE), "LANG": "C"},
                       capture_output=True, text=True, encoding="utf-8", timeout=20, stdin=subprocess.DEVNULL)
    return re.sub(r"creationTimestamp: .*", "", r.stdout) if r.returncode == 0 else None


def main() -> int:
    # comparing results on a cluster is opt-in: without --server nothing contacts a cluster
    use_server = "--server" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit-steps") + 1]) if "--limit-steps" in sys.argv else None
    t0 = time.time()
    files = [Path(sys.argv[i + 1]).name for i, a in enumerate(sys.argv) if a == "--file"]  # a name or a path
    found = try_steps()
    unknown = [f for f in files if not any(s["file"] == f for s in found)]
    if unknown:
        sys.exit(f"no typed-command task with accepted answers in: {', '.join(unknown)} (lesson files are in content/en/lessons/)")
    steps = [s for s in found if not files or s["file"] in files][:limit]
    partial = bool(files or limit)
    # 1. accepted forms, client side
    content_errors = []
    for s in steps:
        for a in s["accept"]:
            w = argv(a)
            if w and w[0] in ("oc", "kubectl"):
                state, why = client(w)
                if state == "rejected":
                    content_errors.append({"step": s["id"], "file": s["file"], "cmd": a, "client": why})
    print(f"accepted forms: {sum(len(s['accept']) for s in steps)}; rejected by the client: {len(content_errors)}", flush=True)
    # 2. near misses, graded by the checker
    batch = []
    for s in steps:
        seen = set(s["accept"])
        for a in s["accept"][:4]:
            for m in sorted(mutations(a)):
                if m not in seen:
                    seen.add(m)
                    batch.append({"typed": m, "accept": s["accept"], "step": s["id"], "file": s["file"], "from": a})
    print(f"near misses: {len(batch)}", flush=True)
    verdicts = bridge([{"typed": b["typed"], "accept": b["accept"]} for b in batch])
    accepted = [{**b, **v} for b, v in zip(batch, verdicts) if v["accepted"]]
    print(f"accepted by the checker: {len(accepted)}", flush=True)
    # 3. every accepted near miss against reality
    false_pos, confirmed, unverified = [], [], []
    for b in accepted:
        typed_argv, via_argv = argv(b["typed"]), argv(b["via"])
        reason = None
        if typed_argv is None or via_argv is None:
            reason = "shell: bash could not expand the line"
        elif typed_argv == via_argv:
            confirmed.append({**b, "evidence": "bash passes identical words"})
            continue
        program = typed_argv[0]
        if reason is None and program in ("oc", "kubectl"):
            st, why = client(typed_argv)
            st_via, _ = client(via_argv)
            if st == "rejected" and st_via != "rejected":
                reason = f"client rejects it: {why}"
            elif (dx := dry_run(typed_argv)) is not None and (dy := dry_run(via_argv)) is not None:
                if dx != dy:
                    reason = "different object from the client's dry run"
                else:
                    confirmed.append({**b, "evidence": "the client builds the same object (client dry run)"})
                    continue
            elif use_server:
                x, y = server(typed_argv), server(via_argv)
                if x is not None and y is not None:
                    if x != y:
                        reason = f"different result as developer: exit {x[0]} vs {y[0]}: {x[1][:160]!r} vs {y[1][:160]!r}"
                    else:
                        confirmed.append({**b, "evidence": f"same result as developer (exit {x[0]})"})
                        continue
        if reason:
            false_pos.append({**b, "reason": reason, "argv": typed_argv, "via_argv": via_argv})
        else:
            unverified.append({**b, "argv": typed_argv, "via_argv": via_argv})
    # 4. rejected near misses that the real client also rejects: regression fixtures for the checker
    negatives = []
    for b, v in zip(batch, verdicts):
        if v["accepted"] or len(negatives) >= 400:
            continue
        w = argv(b["typed"])
        if w and w[0] in ("oc", "kubectl"):
            st, why = client(w)
            if st == "rejected":
                negatives.append({"typed": b["typed"], "accept": b["accept"][:6], "step": b["step"], "client": why})
    if partial:
        for e in content_errors:
            print(f"CONTENT ERROR {e['step']}: {e['cmd']} -- {e['client']}")
        for e in false_pos:
            print(f"FALSE POSITIVE {e['step']}: typed `{e['typed']}` accepted as `{e['via']}` -- {e['reason']}")
        for e in unverified:
            print(f"unverified {e['step']}: `{e['typed']}` ~ `{e['via']}`")
        print(f"partial run ({files or limit}): content errors {len(content_errors)}, false positives {len(false_pos)}, unverified {len(unverified)}, confirmed {len(confirmed)}")
        return 1 if false_pos or content_errors else 0
    client_version = subprocess.run(sandboxed(["oc", "version", "--client"], network=False), cwd=EMPTY, capture_output=True,
                                    text=True, encoding="utf-8", timeout=30, env={"HOME": str(SCRATCH), "PATH": "/usr/bin:/bin", "LANG": "C"}).stdout.split("\n")[0]
    FIXTURES.write_text(json.dumps({"generated": time.strftime("%Y-%m-%d"), "client": client_version,
                                    "rejected": negatives, "equivalent": [{"typed": c["typed"], "accept": [c["via"], *[a for a in c["accept"][:5] if a != c["via"]]], "step": c["step"], "evidence": c["evidence"]} for c in confirmed[:400]]},
                                   indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Grading oracle report", "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} by `scripts/grading_oracle.py` in {round(time.time() - t0)} s. "
        f"Client: `{client_version}`; "
        f"server checks as `developer`: {'yes' if use_server else 'no'}.", "",
        "| Measure | Count |", "|---|---|",
        f"| Practice steps with typed commands | {len(steps)} |",
        f"| Accepted forms | {sum(len(s['accept']) for s in steps)} |",
        f"| Accepted forms the real client rejects (content errors) | {len(content_errors)} |",
        f"| Generated near misses | {len(batch)} |",
        f"| Near misses the checker accepts | {len(accepted)} |",
        f"| ... confirmed equivalent (identical words, the same object from a client dry run, or the same result as developer) | {len(confirmed)} |",
        f"| ... **false positives** (shell or client disagrees) | {len(false_pos)} |",
        f"| ... not verifiable automatically (listed below for review) | {len(unverified)} |",
        f"| Rejected near misses kept as regression fixtures (the real client rejects them too) | {len(negatives)} |", "",
        "## Accepted forms the real client rejects", "",
        *([f"- `{e['step']}` ({e['file']}): `{e['cmd']}` — {e['client']}" for e in content_errors] or ["None."]), "",
        "## False positives", "",
        *([f"- `{e['step']}`: typed `{e['typed']}` accepted as `{e['via']}` — {e['reason']}" for e in false_pos] or ["None."]), "",
        "## Accepted near misses not verifiable automatically", "",
        "Each pair differs in words bash passes, for a program whose behaviour this script cannot run safely; the "
        "checker's rule that accepted it is named by the difference.", "",
        *[f"- `{e['step']}`: `{e['typed']}` ≈ `{e['via']}`" for e in unverified[:300]], *([f"- … {len(unverified) - 300} more"] if len(unverified) > 300 else []),
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"content errors {len(content_errors)}, false positives {len(false_pos)}, unverified {len(unverified)}, confirmed {len(confirmed)}; {REPORT.relative_to(ROOT)}")
    return 1 if false_pos or content_errors else 0


if __name__ == "__main__":
    sys.exit(main())
