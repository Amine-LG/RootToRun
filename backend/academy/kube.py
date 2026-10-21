"""Cluster access: three identities, each with its own private kubeconfig, and a safe `oc` runner.

Identities (least privilege first):
  reader   ServiceAccount academy-system/academy-reader bound to the built-in `cluster-reader` role.
           Used by the Explorer and health views. Cannot read Secret data, cannot write.
  learner  The CRC `developer` user. Used for lab setup, learner commands and verification inside
           academy-* projects. Kubernetes RBAC itself limits it to projects it created.
  admin    `kubeadmin`. Only for named, pre-defined elevated actions that the user confirms explicitly
           (creating the reader ServiceAccount, labelling the node for a scheduling lab, ...).

Commands are argv lists (no shell). The child process gets a minimal environment, so no unrelated
secrets can leak into output. Tokens are redacted from anything returned to the browser.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from . import config

Identity = Literal["reader", "learner", "admin"]
IDENTITIES: tuple[Identity, ...] = ("reader", "learner", "admin")

_TOKEN_RE = re.compile(r"(sha256~[A-Za-z0-9_\-]{10,}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,})")


def redact(text: str) -> str:
    return _TOKEN_RE.sub("[redacted-token]", text or "")


@dataclass
class Result:
    argv: list[str]
    code: int
    stdout: str
    stderr: str
    seconds: float
    status: str = "ok"  # ok | error | timeout | oc_missing | not_connected

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.code == 0

    def json(self):
        return json.loads(self.stdout)

    def public(self) -> dict:
        shown = ["oc", *self.argv[1:]] if self.argv else []
        return {
            "command": " ".join(shown),
            "code": self.code,
            "status": self.status if self.code == 0 or self.status != "ok" else "error",
            "stdout": redact(self.stdout)[-60000:],
            "stderr": redact(self.stderr)[-8000:],
            "seconds": round(self.seconds, 2),
        }


def kubeconfig(identity: Identity) -> Path:
    return config.KUBE_DIR / f"{identity}.kubeconfig"


def _env(identity: Identity | None) -> dict:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "C.UTF-8"}
    if identity:
        env["KUBECONFIG"] = str(kubeconfig(identity))
    return env


def oc(identity: Identity | None, args: list[str], *, stdin: str | None = None, timeout: int | None = None) -> Result:
    """Run `oc <args>` as `identity`. args must already be validated by the caller."""
    path = config.oc_path()
    if not path:
        return Result([], 127, "", "`oc` was not found (PATH or ~/.crc/bin/oc).", 0, "oc_missing")
    if identity and not kubeconfig(identity).exists():
        return Result(["oc", *args], 1, "", f"Not connected as {identity}.", 0, "not_connected")
    t0 = time.monotonic()
    try:
        p = subprocess.run([path, *args], input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=timeout or config.OC_TIMEOUT_S, env=_env(identity))
    except subprocess.TimeoutExpired:
        return Result(["oc", *args], 124, "", f"Timed out after {timeout or config.OC_TIMEOUT_S}s. Is CRC running?", time.monotonic() - t0, "timeout")
    return Result(["oc", *args], p.returncode, p.stdout, p.stderr, time.monotonic() - t0, "ok")


def oc_json(identity: Identity, args: list[str], timeout: int | None = None):
    r = oc(identity, [*args, "-o", "json"], timeout=timeout)
    if not r.ok:
        return None, r
    try:
        return r.json(), r
    except ValueError:
        return None, r


# A read has more than two outcomes. Only an explicit NotFound from the API server proves absence; Forbidden,
# Unauthorized, timeouts and malformed output prove nothing. Note: OpenShift answers Forbidden (not NotFound) when a
# normal user asks for a project that does not exist, so a learner can never prove that a project is gone this way.
ReadState = Literal["found", "not_found", "forbidden", "unauthorized", "error"]


def classify(r: Result) -> ReadState:
    if r.ok:
        return "found"
    if r.status != "ok":
        return "error"  # timeout, oc missing, not connected
    err = r.stderr
    if "(NotFound)" in err:
        return "not_found"
    if "(Forbidden)" in err:
        return "forbidden"
    if "(Unauthorized)" in err or "must be logged in" in err:
        return "unauthorized"
    return "error"


def read(identity: Identity, args: list[str], timeout: int | None = None) -> tuple[ReadState, dict | None, Result]:
    """`oc get ... -o json` with a tri-state answer: found (with the object), not_found, or a reason it is unknown."""
    r = oc(identity, [*args, "-o", "json"], timeout=timeout)
    state = classify(r)
    if state != "found":
        return state, None, r
    try:
        return "found", r.json(), r
    except ValueError:
        return "error", None, r


# ---------------------------------------------------------------- CRC and connection status
def crc_status() -> dict:
    """`crc status -o json`, with the fields that matter. Never starts or stops anything."""
    path = config.crc_path()
    if not path:
        return {"installed": False}
    try:
        p = subprocess.run([path, "status", "-o", "json"], capture_output=True, text=True, encoding="utf-8", timeout=20, env=_env(None))
        data = json.loads(p.stdout or "{}")
    except (subprocess.TimeoutExpired, ValueError):
        return {"installed": True, "crcStatus": "Unknown"}
    keep = ("crcStatus", "openshiftStatus", "openshiftVersion", "diskUsage", "diskSize", "ramUsage", "ramSize", "preset", "success")
    return {"installed": True, **{k: data.get(k) for k in keep if k in data}}


def whoami(identity: Identity) -> dict:
    if not kubeconfig(identity).exists():
        return {"connected": False, "reason": "not connected"}
    r = oc(identity, ["whoami"], timeout=10)
    if r.ok:
        return {"connected": True, "user": r.stdout.strip()}
    reason = "token expired or revoked" if "Unauthorized" in r.stderr or "must be logged in" in r.stderr else (r.stderr.strip().splitlines() or ["unreachable"])[-1]
    return {"connected": False, "reason": redact(reason)[:200], "status": r.status}


# ---------------------------------------------------------------- logging in (secrets stay server-side)
def _ca_file() -> Path | None:
    """The CRC API CA, extracted from the kubeconfig CRC writes, so TLS is verified (no skip-tls)."""
    src = config.CRC_MACHINE / "kubeconfig"
    dst = config.KUBE_DIR / "crc-api-ca.crt"
    if dst.exists():
        return dst
    if not src.exists():
        return None
    import base64

    import yaml

    try:
        data = yaml.safe_load(src.read_text(encoding="utf-8"))
        ca = data["clusters"][0]["cluster"]["certificate-authority-data"]
    except Exception:
        return None
    _write_private(dst, base64.b64decode(ca).decode())
    return dst


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _absolute_paths(src: Path) -> str:
    """The kubeconfig at `src`, with relative certificate, key and token file paths made absolute: a copy lives in
    another directory, and kubectl resolves relative paths against the file that names them."""
    import yaml

    text = src.read_text(encoding="utf-8")
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return text  # oc reports the problem when it reads the copy
    if not isinstance(doc, dict):
        return text
    changed = False

    def absolute(v: str) -> str:
        p = Path(v).expanduser()
        return str(p if p.is_absolute() else (src.parent / p).resolve())

    for section, inner, keys in (("clusters", "cluster", ("certificate-authority",)),
                                 ("users", "user", ("client-certificate", "client-key", "tokenFile"))):
        for item in doc.get(section) or []:
            body = (item or {}).get(inner) if isinstance(item, dict) else None
            if not isinstance(body, dict):
                continue
            for k in keys:
                v = body.get(k)
                if isinstance(v, str) and v and absolute(v) != v:
                    body[k], changed = absolute(v), True
            # an exec credential plugin named by a relative path (one containing a slash) is also relative to the file;
            # a bare name is looked up on PATH and stays as it is
            ex = body.get("exec") if section == "users" else None
            cmd = ex.get("command") if isinstance(ex, dict) else None
            if isinstance(cmd, str) and "/" in cmd and absolute(cmd) != cmd:
                ex["command"], changed = absolute(cmd), True
    return yaml.safe_dump(doc, sort_keys=False) if changed else text


def login_user(identity: Literal["learner", "admin"]) -> dict:
    """Connect an identity. Either copy a kubeconfig given by the operator (ACADEMY_KUBECONFIG_<ID>, works
    with any cluster), or log in with the password CRC generated: it is read from CRC's files and sent to
    `oc` on stdin, so it never appears in argv, logs or HTTP responses."""
    ext = config.EXTERNAL_KUBECONFIG.get(identity)
    if ext:
        src = Path(ext).expanduser()
        if not src.exists():
            return {"ok": False, "reason": f"ACADEMY_KUBECONFIG_{identity.upper()} points to a missing file."}
        _write_private(kubeconfig(identity), _absolute_paths(src))
        who = whoami(identity)
        if not who.get("connected"):  # a kubeconfig that does not log in is not a connection: keep nothing
            kubeconfig(identity).unlink(missing_ok=True)
        return {"ok": who.get("connected", False), **who}
    user, pw_file = ("developer", "developer-password") if identity == "learner" else ("kubeadmin", "kubeadmin-password")
    pw_path = config.CRC_MACHINE / pw_file
    if not pw_path.exists():
        return {"ok": False, "reason": f"CRC password file not found ({pw_file})."}
    ca = _ca_file()
    target = kubeconfig(identity)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)
    if not target.exists():
        _write_private(target, "")
    args = ["login", config.API_SERVER, "-u", user]
    args += [f"--certificate-authority={ca}"] if ca else []
    r = oc(identity, args, stdin=pw_path.read_text(encoding="utf-8").strip() + "\n", timeout=60)
    os.chmod(target, 0o600)
    if not r.ok:
        target.unlink(missing_ok=True)
        return {"ok": False, "reason": redact((r.stderr or r.stdout).strip())[-400:]}
    return {"ok": True, **whoami(identity)}


def disconnect(identity: Identity) -> None:
    """Forget the local kubeconfig (and log out user sessions so the token is revoked)."""
    if identity in ("learner", "admin") and kubeconfig(identity).exists():
        oc(identity, ["logout"], timeout=15)
    kubeconfig(identity).unlink(missing_ok=True)


READER_SA = "academy-reader"


def reader_plan() -> list[dict]:
    """The exact elevated changes `setup_reader` makes, shown to the user before confirming."""
    return [
        {"action": "create namespace", "target": config.SYSTEM_NS, "why": "a home for the academy's own ServiceAccount"},
        {"action": "create serviceaccount", "target": f"{config.SYSTEM_NS}/{READER_SA}", "why": "a dedicated, non-human identity for read-only inspection"},
        {"action": "create clusterrolebinding", "target": f"academy-reader -> clusterrole/cluster-reader", "why": "read access to cluster objects (no Secret data, no writes)"},
        {"action": "request token", "target": "TokenRequest, 24h", "why": "short-lived token stored only in data/kube/reader.kubeconfig (0600)"},
    ]


def setup_reader() -> dict:
    """Create the least-privilege reader identity. Requires the admin identity (explicitly confirmed)."""
    if not whoami("admin").get("connected"):
        return {"ok": False, "reason": "Connect the admin identity first (explicit confirmation required)."}
    ns = config.SYSTEM_NS
    steps = []
    manifest = {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": ns, "labels": {"academy.lab/system": "true"}}},
            {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": READER_SA, "namespace": ns}},
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "ClusterRoleBinding",
                "metadata": {"name": "academy-reader", "labels": {"academy.lab/system": "true"}},
                "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": "cluster-reader"},
                "subjects": [{"kind": "ServiceAccount", "name": READER_SA, "namespace": ns}],
            },
        ],
    }
    r = oc("admin", ["apply", "-f", "-"], stdin=json.dumps(manifest))
    steps.append(r.public())
    if not r.ok:
        return {"ok": False, "steps": steps, "reason": redact(r.stderr)[-400:]}
    return refresh_reader_token(steps)


def refresh_reader_token(steps: list | None = None) -> dict:
    steps = steps or []
    r = oc("admin", ["create", "token", READER_SA, "-n", config.SYSTEM_NS, "--duration=24h"])
    if not r.ok:
        steps.append(r.public())
        return {"ok": False, "steps": steps, "reason": redact(r.stderr)[-400:]}
    token = r.stdout.strip()
    ca = _ca_file()
    import yaml

    cluster = {"server": config.API_SERVER}
    if ca:
        cluster["certificate-authority"] = str(ca)
    kc = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{"name": "crc", "cluster": cluster}],
        "users": [{"name": READER_SA, "user": {"token": token}}],
        "contexts": [{"name": "reader", "context": {"cluster": "crc", "user": READER_SA}}],
        "current-context": "reader",
    }
    _write_private(kubeconfig("reader"), yaml.safe_dump(kc))
    steps.append({"command": f"oc create token {READER_SA} -n {config.SYSTEM_NS} --duration=24h", "code": 0, "status": "ok", "stdout": "[token stored privately]", "stderr": ""})
    return {"ok": True, "steps": steps, **whoami("reader")}


def helm(identity: Identity, args: list[str], timeout: int | None = None) -> Result:
    """Run `helm <args>` with the identity's kubeconfig (used by the Workbench for lab charts)."""
    path = config.helm_path()
    if not path:
        return Result([], 127, "", "`helm` is not installed on the academy server.", 0, "oc_missing")
    if not kubeconfig(identity).exists():
        return Result(["helm", *args], 1, "", f"Not connected as {identity}.", 0, "not_connected")
    t0 = time.monotonic()
    try:
        p = subprocess.run([path, *args], capture_output=True, text=True, encoding="utf-8", timeout=timeout or 60, env=_env(identity))
    except subprocess.TimeoutExpired:
        return Result(["helm", *args], 124, "", "Timed out.", time.monotonic() - t0, "timeout")
    return Result(["helm", *args], p.returncode, p.stdout, p.stderr, time.monotonic() - t0, "ok")


def status() -> dict:
    if not config.cluster_enabled():
        return {"mode": "practice", "oc": False, "crc": {"installed": False}, "identities": {i: {"connected": False, "reason": "practice mode"} for i in IDENTITIES}, "api": None}
    return {
        "mode": "cluster",
        "oc": config.oc_path() is not None,
        "crc": crc_status(),
        "identities": {i: whoami(i) for i in IDENTITIES},
        "api": config.API_SERVER,
    }
