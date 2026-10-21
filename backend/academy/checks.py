"""Declarative verification against the real cluster.

A lab lists checks such as {type: deployment_ready, name: web}. Each check reads live objects
with `oc ... -o json` (as the learner, inside the lab project) and returns pass / fail / error,
with what was observed. Nothing here writes to the cluster, except `exec` for in-cluster probes
(curl / getent from a pod the lab created).
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.request
from typing import Any, Callable

from . import kube

Check = dict[str, Any]
Outcome = dict[str, Any]


def _get(ns: str, kind: str, name: str | None = None, selector: str | None = None, identity="learner"):
    args = ["get", kind] + ([name] if name else []) + (["-l", selector] if selector else []) + ["-n", ns]
    return kube.oc_json(identity, args)


def dig(obj: Any, path: str) -> Any:
    """Small JSON path: a.b[0].c, with [?name=web] filters on lists."""
    cur = obj
    path = path.replace("\\.", "\x00")  # `\.` escapes a dot inside a key (annotation names)
    for part in re.findall(r"[^.\[\]]+|\[[^\]]*\]", path):
        part = part.replace("\x00", ".")
        if cur is None:
            return None
        if part.startswith("[?"):
            k, v = part[2:-1].split("=", 1)
            cur = next((x for x in cur if isinstance(x, dict) and str(x.get(k)) == v), None) if isinstance(cur, list) else None
        elif part.startswith("["):
            idx = int(part[1:-1])
            cur = cur[idx] if isinstance(cur, list) and -len(cur) <= idx < len(cur) else None
        else:
            cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


_QSUFFIX = {"m": 1e-3, "": 1, "k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40}


def quantity(q: Any) -> float | None:
    """A Kubernetes resource quantity as a number: '500m' -> 0.5, '128Mi' -> 134217728, 2 -> 2."""
    if isinstance(q, (int, float)):
        return float(q)
    m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)(m|k|M|G|T|Ki|Mi|Gi|Ti)?\s*", str(q or ""))
    return float(m.group(1)) * _QSUFFIX[m.group(2) or ""] if m else None


def _cron_every(expr: Any, minutes: int) -> bool:
    """True when a five-field cron schedule runs every `minutes` minutes, every hour of every day (e.g. */30, 0,30,
    15,45 or 0-59/30 in the minute field for 30)."""
    f = str(expr or "").split()
    if len(f) != 5 or f[1:] != ["*", "*", "*", "*"]:
        return False
    m = f[0]
    step = re.fullmatch(r"(?:\*|0-59|(\d+)(?:-59)?)/(\d+)", m)
    if step:
        start = int(step.group(1) or 0)
        return int(step.group(2)) == minutes and start < minutes
    try:
        vals = sorted(int(x) for x in m.split(","))
    except ValueError:
        return False
    return len(vals) == 60 // minutes and all(0 <= v < 60 for v in vals) and all(b - a == minutes for a, b in zip(vals, vals[1:]))


def compare(observed: Any, op: str, value: Any) -> bool:
    if op == "cron_every":
        return _cron_every(observed, int(value))
    if op == "json_contains":  # substring of the JSON form: for lists and objects (a command, a policy rule)
        return observed is not None and str(value) in json.dumps(observed)
    if op in ("qlte", "qgte", "qeq"):  # resource quantities with units; a missing value never passes
        o, v = quantity(observed), quantity(value)
        if o is None or v is None:
            return False
        return {"qlte": o <= v, "qgte": o >= v, "qeq": abs(o - v) < 1e-9}[op]
    if op == "exists":
        return observed is not None
    if op == "absent":
        return observed is None
    if op == "eq":
        return observed == value or (observed is not None and str(observed) == str(value))
    if op == "ne":
        return observed != value and str(observed) != str(value)
    if op == "contains":
        return observed is not None and str(value) in (observed if isinstance(observed, (list, str)) else str(observed))
    if op == "not_contains":
        return observed is None or str(value) not in (observed if isinstance(observed, (list, str)) else str(observed))
    if op == "matches":
        return observed is not None and re.search(str(value), str(observed)) is not None
    try:
        o, v = float(observed), float(value)
    except (TypeError, ValueError):
        return False
    return {"gte": o >= v, "lte": o <= v, "gt": o > v, "lt": o < v}.get(op, False)


def _fail_unreachable(r) -> Outcome:
    if r.status in ("timeout", "not_connected", "oc_missing"):
        return {"status": "error", "observed": r.stderr.strip()[:300]}
    msg = (r.stderr or "").strip().splitlines()
    return {"status": "fail", "observed": kube.redact(msg[-1] if msg else "not found")[:300]}


# ---------------------------------------------------------------- check implementations
def c_exists(ns: str, c: Check) -> Outcome:
    obj, r = _get(ns, c["kind"], c["name"])
    if obj is None:
        return _fail_unreachable(r)
    return {"status": "pass", "observed": f"{c['kind']}/{c['name']} exists"}


def c_absent(ns: str, c: Check) -> Outcome:
    obj, r = _get(ns, c["kind"], c["name"])
    if obj is not None:
        return {"status": "fail", "observed": f"{c['kind']}/{c['name']} still exists"}
    if "NotFound" in r.stderr or "not found" in r.stderr:
        return {"status": "pass", "observed": "not found"}
    return _fail_unreachable(r)


def c_field(ns: str, c: Check) -> Outcome:
    obj, r = _get(ns, c["kind"], c["name"])
    if obj is None:
        return _fail_unreachable(r)
    observed = dig(obj, c["path"])
    ok = compare(observed, c.get("op", "eq"), c.get("value"))
    return {"status": "pass" if ok else "fail", "observed": f"{c['path']} = {observed!r}"}


def c_field_ref(ns: str, c: Check) -> Outcome:
    """A field of one object compared with a field of another (`ref`: kind, name, path), e.g. the image a Deployment
    runs contains the digest a Build produced."""
    obj, r = _get(ns, c["kind"], c["name"])
    if obj is None:
        return _fail_unreachable(r)
    ref = c["ref"]
    other, r2 = _get(ns, ref["kind"], ref["name"])
    if other is None:
        return _fail_unreachable(r2)
    observed, want = dig(obj, c["path"]), dig(other, ref["path"])
    ok = want not in (None, "") and compare(observed, c.get("op", "eq"), want)
    return {"status": "pass" if ok else "fail", "observed": f"{c['path']} = {observed!r}; {ref['kind']}/{ref['name']} {ref['path']} = {want!r}"}


def c_count(ns: str, c: Check) -> Outcome:
    obj, r = _get(ns, c["kind"], selector=c.get("selector"))
    if obj is None:
        return _fail_unreachable(r)
    items = obj.get("items", [])
    if "where" in c:
        conds = c["where"] if isinstance(c["where"], list) else [c["where"]]
        items = [i for i in items if all(compare(dig(i, w["path"]), w.get("op", "eq"), w.get("value")) for w in conds)]
    n = len(items)
    ok = compare(n, c.get("op", "gte"), c.get("value", 1))
    return {"status": "pass" if ok else "fail", "observed": f"{n} matching {c['kind']}"}


def c_deployment_ready(ns: str, c: Check) -> Outcome:
    d, r = _get(ns, "deployment", c["name"])
    if d is None:
        return _fail_unreachable(r)
    st, spec = d.get("status", {}), d.get("spec", {})
    want = c.get("replicas", spec.get("replicas", 1))
    ready, updated = st.get("readyReplicas", 0), st.get("updatedReplicas", 0)
    fresh = st.get("observedGeneration", 0) >= d["metadata"].get("generation", 0)
    desired_ok = "replicas" not in c or spec.get("replicas", 1) == want  # status can lag a wrong request (quota)
    paused = bool(spec.get("paused"))  # a paused rollout leaves pods on an older template than the one shown
    ok = desired_ok and fresh and not paused and ready >= want and updated >= want and st.get("replicas", 0) == want
    return {"status": "pass" if ok else "fail", "observed": f"spec.replicas {spec.get('replicas', 1)}, ready {ready}/{want}, updated {updated}, total {st.get('replicas', 0)}, observedGeneration current: {fresh}" + (", rollout PAUSED" if paused else "")}


def _pods(ns: str, selector: str):
    obj, r = _get(ns, "pods", selector=selector)
    return (obj or {}).get("items", []) if obj else None, r


def _container_state(p: dict) -> list[dict]:
    return p.get("status", {}).get("containerStatuses", []) or []


def c_pods(ns: str, c: Check) -> Outcome:
    """pods matching selector; optional owner (a Deployment name: only pods of its ReplicaSets), ready (every container
    ready and the Ready condition true; a pod with no container status yet is not ready), phase, waiting_reason,
    last_terminated_reason, annotation, max_restarts, qos (status.qosClass), requests (resource names every container
    of the running pod must request, after defaulting), max_cpu_request (sum over the pod's containers), min, max."""
    pods, r = _pods(ns, c["selector"])
    if pods is None:
        return _fail_unreachable(r)
    pods = [p for p in pods if not p["metadata"].get("deletionTimestamp")]

    if c.get("owner"):  # only pods created by this Deployment's ReplicaSets, not look-alikes carrying its labels
        own = re.compile(rf"{re.escape(c['owner'])}-[a-z0-9]+")
        pods = [p for p in pods if any(o.get("kind") == "ReplicaSet" and own.fullmatch(str(o.get("name", ""))) for o in p["metadata"].get("ownerReferences") or [])]

    def is_ready(p) -> bool:
        cs = _container_state(p)
        cond = next((x for x in p.get("status", {}).get("conditions") or [] if x.get("type") == "Ready"), None)
        return bool(cs) and all(x.get("ready", False) for x in cs) and (cond is None or cond.get("status") == "True")

    def cpu_requested(p) -> float:
        return sum(quantity(((ct.get("resources") or {}).get("requests") or {}).get("cpu")) or 0 for ct in (p.get("spec") or {}).get("containers") or [])

    def ok(p):
        cs = _container_state(p)
        if "ready" in c and is_ready(p) != bool(c["ready"]):
            return False
        if "requests" in c and any(dig(ct, f"resources.requests.{r}") is None for ct in (p.get("spec") or {}).get("containers") or [] for r in c["requests"]):
            return False
        if "max_cpu_request" in c and cpu_requested(p) > (quantity(c["max_cpu_request"]) or 0):
            return False
        if "phase" in c and p.get("status", {}).get("phase") != c["phase"]:
            return False
        if "waiting_reason" in c and not any((x.get("state", {}).get("waiting") or {}).get("reason") == c["waiting_reason"] for x in cs):
            return False
        if "last_terminated_reason" in c and not any((x.get("lastState", {}).get("terminated") or {}).get("reason") == c["last_terminated_reason"] for x in cs):
            return False
        if "annotation" in c:
            k, v = c["annotation"].split("=", 1)
            if p["metadata"].get("annotations", {}).get(k) != v:
                return False
        if "max_restarts" in c and sum(x.get("restartCount", 0) for x in cs) > c["max_restarts"]:
            return False
        if "qos" in c and p.get("status", {}).get("qosClass") != c["qos"]:
            return False
        return True

    good = [p for p in pods if ok(p)]
    lo, hi = c.get("min", 1), c.get("max", 10**6)
    summary = ", ".join(
        f"{p['metadata']['name']}: {p.get('status', {}).get('phase')}"
        + "".join(f" [{(x.get('state', {}).get('waiting') or {}).get('reason') or ('ready' if x.get('ready') else 'not ready')}, restarts {x.get('restartCount', 0)}]" for x in _container_state(p))
        + (f" QoS {p.get('status', {}).get('qosClass')}" if "qos" in c else "")
        for p in pods[:6]
    ) or "no pods"
    return {"status": "pass" if lo <= len(good) <= hi else "fail", "observed": f"{len(good)} of {len(pods)} match · {summary}"}


def c_endpoints(ns: str, c: Check) -> Outcome:
    """Ready endpoints behind a Service, read from its EndpointSlices."""
    obj, r = _get(ns, "endpointslices.discovery.k8s.io", selector=f"kubernetes.io/service-name={c['service']}")
    if obj is None:
        return _fail_unreachable(r)
    ready = 0
    ports = set()
    for s in obj.get("items", []):
        for p in s.get("ports") or []:
            ports.add(p.get("port"))
        for e in s.get("endpoints") or []:
            if (e.get("conditions") or {}).get("ready"):
                ready += len(e.get("addresses", []))
    ok = compare(ready, c.get("op", "gte"), c.get("value", 1))
    if ok and "port" in c:
        ok = c["port"] in ports
    return {"status": "pass" if ok else "fail", "observed": f"{ready} ready endpoint address(es), ports {sorted(x for x in ports if x) or '-'}"}


def c_event(ns: str, c: Check) -> Outcome:
    obj, r = kube.oc_json("learner", ["get", "events", "-n", ns])
    if obj is None:
        return _fail_unreachable(r)
    hits = [
        e for e in obj.get("items", [])
        if (not c.get("reason") or e.get("reason") == c["reason"])
        and (not c.get("message_contains") or c["message_contains"] in (e.get("message") or ""))
        and (not c.get("object_prefix") or (e.get("involvedObject", {}).get("name") or "").startswith(c["object_prefix"]))
    ]
    want_seen = c.get("seen", True)
    ok = bool(hits) == want_seen
    sample = (hits[0].get("message") or "")[:200] if hits else "none"
    return {"status": "pass" if ok else "fail", "observed": f"{len(hits)} event(s) · {sample}"}


def c_can_i(ns: str, c: Check) -> Outcome:
    subject = c["as"] if ":" in c["as"] else f"system:serviceaccount:{ns}:{c['as']}"
    resource, _, sub = c["resource"].partition("/")
    # `can-i get pods/log` would ask about a pod NAMED "log": a subresource needs --subresource, a name needs `name:`
    target = f"{resource}/{c['name']}" if c.get("name") else resource
    args = ["auth", "can-i", c["verb"], target, *([f"--subresource={sub}"] if sub else []), f"--as={subject}", "-n", ns]
    r = kube.oc("learner", args)
    answer = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    if answer not in ("yes", "no"):
        return {"status": "error", "observed": kube.redact(r.stderr.strip())[:300] or "no answer"}
    ok = (answer == "yes") == (c.get("expect", "yes") == "yes")
    return {"status": "pass" if ok else "fail", "observed": f"can {subject.split(':')[-1]} {c['verb']} {c['resource']}{'/' + c['name'] if c.get('name') else ''}? {answer}"}


def _first_running_pod(ns: str, selector: str) -> str | None:
    pods, _ = _pods(ns, selector)
    for p in pods or []:
        if p.get("status", {}).get("phase") == "Running" and not p["metadata"].get("deletionTimestamp"):
            return p["metadata"]["name"]
    return None


PROBE_IMAGE = "registry.access.redhat.com/ubi9/ubi-minimal"  # the image of every lab test client


def _probe_pod_problem(p: dict, app: str) -> str | None:
    """Why a pod cannot be trusted as the lab's own test client, or None. The learner controls the project, so a test
    pod could be replaced or relabelled, or given a fake curl through a volume or PATH. The lab's test clients come
    from a Deployment named after their `app` label, run `sleep infinity`, and mount nothing but the API token."""
    owners = p["metadata"].get("ownerReferences") or []
    if not any(o.get("kind") == "ReplicaSet" and re.fullmatch(rf"{re.escape(app)}-[a-z0-9]+", str(o.get("name", ""))) for o in owners):
        return "it is not managed by the lab's own Deployment"
    spec = p.get("spec") or {}
    if any(not str(ct.get("image", "")).startswith(PROBE_IMAGE) for ct in spec.get("containers") or []):
        return "it does not run the lab's client image"
    if any(set(v) - {"name", "projected"} for v in spec.get("volumes") or []):
        return "it mounts volumes the lab did not give it"
    for ct in spec.get("containers") or []:
        if ct.get("command") != ["sleep", "infinity"] or ct.get("args") or ct.get("volumeMounts") and any(not m.get("mountPath", "").startswith("/var/run/secrets/") for m in ct["volumeMounts"]):
            return "its container was changed"
        if any(e.get("name") in ("PATH", "LD_PRELOAD") for e in ct.get("env") or []):
            return "its environment was changed"
    return None


def c_exec(ns: str, c: Check) -> Outcome:
    """Run a fixed command in a lab pod (e.g. curl, getent) and match its output.

    With `trusted: true` the pod must be the lab's untouched test client (see _probe_pod_problem): a connection test
    run in a pod the learner replaced proves nothing, and the result is a failure the learner can fix by restarting."""
    if c.get("trusted"):
        pods, _ = _pods(ns, c["from"])
        app = c["from"].split("=", 1)[-1]
        running = [p for p in pods or [] if p.get("status", {}).get("phase") == "Running" and not p["metadata"].get("deletionTimestamp")]
        problems = {p["metadata"]["name"]: _probe_pod_problem(p, app) for p in running}
        bad = {n: why for n, why in problems.items() if why}
        if bad:
            n, why = next(iter(bad.items()))
            return {"status": "fail", "observed": f"test pod {n} ({c['from']}) cannot be trusted: {why}. Restore the lab's test clients (start the challenge again) and re-grade."}
        pod = next(iter(problems), None)
    else:
        pod = _first_running_pod(ns, c["from"])
    if not pod:
        return {"status": "error", "observed": f"no running pod for {c['from']} to test from"}
    r = kube.oc("learner", ["exec", pod, "-n", ns, "--", *c["command"]], timeout=c.get("timeout", 20))
    out = (r.stdout + r.stderr).strip()
    if r.status == "timeout":
        return {"status": "error", "observed": "timed out"}
    ok = True
    if "expect_code" in c:
        ok = r.code == c["expect_code"]
    if ok and "expect_output" in c:
        ok = re.search(c["expect_output"], out) is not None
    if ok and "expect_not_output" in c:
        ok = re.search(c["expect_not_output"], out) is None
    return {"status": "pass" if ok else "fail", "observed": kube.redact(out)[-300:] or f"exit code {r.code}"}


def _file_source(x: dict, vols: dict, want: dict, kind: str) -> str | None:
    """None when the file `want.path`/`want.file` in container `x` comes from the ConfigMap or Secret `want.name`:
    the deepest mount at or above the file decides, and `items` (or, without items, the key's own name) must put a
    key of that object at the file's path. Otherwise, why not."""
    served = f"{want['path'].rstrip('/')}/{want.get('file', 'index.html')}"
    field = "configMap" if kind == "ConfigMap" else "secret"
    ref = "name" if kind == "ConfigMap" else "secretName"

    def provides(v: dict, rel: str) -> bool | None:
        if v.get(field):
            sources = [(v[field].get(ref), v[field].get("items"))]
        else:
            sources = [((src.get(field) or {}).get("name"), (src.get(field) or {}).get("items")) for src in (v.get("projected") or {}).get("sources") or [] if src.get(field)]
        verdict = None
        for name, items in sources:
            hit = any(it.get("path") == rel for it in items) if items else "/" not in rel
            if hit:
                if name != want["name"]:
                    return False  # another source supplies that path
                verdict = True
        return verdict

    cands = []
    for m in x.get("volumeMounts") or []:
        mp = str(m.get("mountPath", "")).rstrip("/")
        if served == mp:
            rel = m.get("subPath") or ""
        elif served.startswith(mp + "/"):
            rel = served[len(mp) + 1:]
        else:
            continue
        cands.append((len(mp), m, rel))
    if cands:
        _, top, rel = max(cands, key=lambda t: t[0])
        if provides(vols.get(top.get("name"), {}), rel or want.get("file", "index.html")):
            return None
    return f"{served} does not come from {kind} {want['name']}"


def _env_source(x: dict, want: dict) -> str | None:
    """None when environment variable `want.var` of container `x` is taken from the ConfigMap or Secret named in
    `want` (a valueFrom reference, or envFrom of the whole object without a prefix), and not written literally."""
    var = want["var"]
    kind, name = ("configMapKeyRef", want["configmap"]) if "configmap" in want else ("secretKeyRef", want["secret"])
    for e in x.get("env") or []:  # an explicit env entry wins over envFrom
        if e.get("name") == var:
            src = (e.get("valueFrom") or {}).get(kind) or {}
            if src.get("name") == name and src.get("key", var) == want.get("key", src.get("key", var)):
                return None
            return f"{var} is set in the Deployment itself, not taken from {name}"
    whole = "configMapRef" if kind == "configMapKeyRef" else "secretRef"
    if any((ef.get(whole) or {}).get("name") == name and not ef.get("prefix") for ef in x.get("envFrom") or []):
        return None
    return f"{var} does not come from {name}"


def c_container(ns: str, c: Check) -> Outcome:
    """Properties of the containers in a Deployment's pod template, found by what they run, not by array position.

    image_prefix   the serving containers are those whose image starts with this (all containers if absent)
    all            check every container instead of the serving ones (e.g. "every container has a memory limit")
    probe          readinessProbe kinds accepted, e.g. [httpGet, tcpSocket]; with `port`, the probe must target it
    requires       dotted paths that must be set on the container, e.g. resources.limits.memory
    configmap_mount {name, path, file?}: the served file comes from this ConfigMap (deepest mount, items followed)
    secret_mount   {name, path, file}: the same for a Secret
    env_source     [{var, configmap|secret, key?}]: the variable is taken from that object, not written literally
    no_literal_env [names]: none of these variables has a literal value in the Deployment
    liveness       [kinds], liveness_port: a liveness probe that can detect a hung server
    """
    d, r = _get(ns, "deployment", c["name"])
    if d is None:
        return _fail_unreachable(r)
    tpl = (d.get("spec", {}).get("template", {}) or {}).get("spec", {}) or {}
    cs = tpl.get("containers") or []
    vols = {v.get("name"): v for v in tpl.get("volumes") or []}
    prefix = c.get("image_prefix")
    serving = [x for x in cs if not prefix or str(x.get("image", "")).startswith(prefix)]
    targets = cs if c.get("all") else serving
    if not targets:
        return {"status": "fail", "observed": f"no container runs {prefix} (images: {', '.join(str(x.get('image')) for x in cs) or 'none'})"}

    def port_of(x: dict, p) -> int | None:
        if isinstance(p, int):
            return p
        return next((cp.get("containerPort") for cp in x.get("ports") or [] if cp.get("name") == p), None)

    def problem(x: dict) -> str | None:
        if "probe" in c:
            pr = x.get("readinessProbe") or {}
            kind = next((k for k in ("httpGet", "tcpSocket", "grpc", "exec") if k in pr), None)
            if kind not in c["probe"]:
                return f"readiness probe {kind or 'missing'} (needs {' or '.join(c['probe'])})"
            if c.get("port") and port_of(x, (pr.get(kind) or {}).get("port")) != c["port"]:
                return f"readiness probe checks port {(pr.get(kind) or {}).get('port')}, not {c['port']}"
        if "liveness" in c:  # a liveness probe that can actually detect a hung server (not exec /bin/true)
            lp = x.get("livenessProbe") or {}
            kind = next((k for k in ("httpGet", "tcpSocket", "grpc", "exec") if k in lp), None)
            if kind not in c["liveness"]:
                return f"liveness probe {kind or 'missing'} (needs {' or '.join(c['liveness'])})"
            if c.get("liveness_port") and port_of(x, (lp.get(kind) or {}).get("port")) != c["liveness_port"]:
                return f"liveness probe checks port {(lp.get(kind) or {}).get('port')}, not {c['liveness_port']}"
        for path in c.get("requires", []):
            if dig(x, path) is None:
                return f"{path} not set"
        for key, kind in (("configmap_mount", "ConfigMap"), ("secret_mount", "Secret")):
            if key in c:
                why = _file_source(x, vols, c[key], kind)
                if why:
                    return why
        for want in c.get("env_source", []):  # {var, configmap|secret, key?}: the variable comes from that object
            why = _env_source(x, want)
            if why:
                return why
        literal = [e.get("name") for e in x.get("env") or [] if e.get("name") in c.get("no_literal_env", []) and "value" in e]
        if literal:
            return f"{', '.join(literal)} is written in the Deployment as a literal value"
        return None

    probs = {x.get("name"): problem(x) for x in targets}
    good = [n for n, pb in probs.items() if pb is None]
    ok = len(good) == len(targets) if c.get("all") else bool(good)
    observed = "; ".join(f"{n}: {pb or 'ok'}" for n, pb in probs.items())
    return {"status": "pass" if ok else "fail", "observed": observed[:300]}


def c_rules_deny(ns: str, c: Check) -> Outcome:
    """Effective rules of a subject must not allow any of the forbidden verbs on the given resources, whatever the
    resource names. `can-i` answers for one verb and one name at a time, so a grant limited to a name the grader did
    not think of would pass it; a SelfSubjectRulesReview, made as the subject, lists every rule that applies."""
    subject = c["as"] if ":" in c["as"] else f"system:serviceaccount:{ns}:{c['as']}"
    review = json.dumps({"apiVersion": "authorization.k8s.io/v1", "kind": "SelfSubjectRulesReview", "spec": {"namespace": ns}})
    r = kube.oc("learner", ["create", "-f", "-", "-o", "json", f"--as={subject}"], stdin=review)
    try:
        status = json.loads(r.stdout)["status"]
    except (ValueError, KeyError, TypeError):
        return {"status": "error", "observed": kube.redact(r.stderr.strip())[:300] or "no rules review"}
    if status.get("incomplete"):
        return {"status": "error", "observed": f"the rules review is incomplete: {status.get('evaluationError', '')}"[:300]}
    found = []
    for f in c["forbid"]:
        # "<resource>[.<group>][/<subresource>]", e.g. secrets, pods/log, deployments.apps/scale
        named, _, sub = f["resource"].partition("/")
        base, _, group = named.partition(".")
        res = f"{base}/{sub}" if sub else base
        # Kubernetes resource matching: exact, "*", and for subresources "*/<sub>" and "<resource>/*"
        names = {res, "*"} | ({f"*/{sub}", f"{base}/*"} if sub else set())
        for rule in status.get("resourceRules") or []:
            if not ({group, "*"} & set(rule.get("apiGroups") or [])) or not (names & set(rule.get("resources") or [])):
                continue
            verbs = set(rule.get("verbs") or [])
            hit = sorted(set(f["verbs"]) & verbs) or (["*"] if "*" in verbs else [])
            if hit:
                limited = rule.get("resourceNames") or []  # (not `names`: that set is still needed for the next rules)
                found.append(f"{'/'.join(hit)} {f['resource']}" + (f" (names: {', '.join(limited)})" if limited else ""))
    who = subject.split(":")[-1]
    return {"status": "fail" if found else "pass", "observed": f"{who} may {'; '.join(found)}"[:300] if found else f"{who} has none of: " + "; ".join(f"{'/'.join(f['verbs'])} {f['resource']}" for f in c["forbid"])[:250]}


def _selects(sel: dict | None, labels: dict) -> bool:
    """A label selector (matchLabels and simple matchExpressions) against a set of labels; {} or None selects all."""
    sel = sel or {}
    if any(labels.get(k) != v for k, v in (sel.get("matchLabels") or {}).items()):
        return False
    for e in sel.get("matchExpressions") or []:
        k, op, vals = e.get("key"), e.get("operator"), e.get("values") or []
        if (op == "In" and labels.get(k) not in vals) or (op == "NotIn" and labels.get(k) in vals) or (op == "Exists" and k not in labels) or (op == "DoesNotExist" and k in labels):
            return False
    return True


def _admits_port(rule: dict, port: int | None, port_name: str | None) -> bool:
    """A rule's `ports` admit TCP `port` (or the container port named `port_name`); no `ports` admits every port."""
    if port is None or not rule.get("ports"):
        return True
    for pe in rule["ports"]:
        if (pe.get("protocol") or "TCP") != "TCP":
            continue
        n = pe.get("port")
        if n is None or n == port or (port_name and n == port_name) or (isinstance(n, int) and pe.get("endPort") and n <= port <= pe["endPort"]):
            return True
    return False


def c_netpol_ingress(ns: str, c: Check) -> Outcome:
    """Evaluate the project's NetworkPolicies for pods with `labels`: are they isolated (`isolated: true`) for ingress, or
    for egress with `direction: Egress`, and (ingress) does some policy that selects them admit a peer from a namespace
    carrying `peer_ns_labels` (`allows: true`), on TCP `port` (or the container port named `port_name`) when given?
    A static reading of the policies, used where live traffic cannot show it (on a single-node cluster the router's
    host-network traffic is always admitted, so a missing router rule never shows as a failed request). Policies are
    matched to the pods by evaluating their whole podSelector against the pods' `labels`."""
    obj, r = _get(ns, "networkpolicy")
    if obj is None:
        return _fail_unreachable(r)
    direction = c.get("direction", "Ingress")
    pols = [p for p in obj.get("items") or [] if _selects((p.get("spec") or {}).get("podSelector"), c["labels"])]
    # a policy without policyTypes is an Ingress policy, and also an Egress one when it has egress rules
    def types(p: dict) -> list[str]:
        spec = p.get("spec") or {}
        return spec.get("policyTypes") or (["Ingress"] + (["Egress"] if spec.get("egress") else []))
    ingress = [p for p in pols if direction in types(p)]
    names = ", ".join(p["metadata"]["name"] for p in ingress) or "none"
    if "isolated" in c and bool(ingress) != bool(c["isolated"]):
        return {"status": "fail", "observed": f"policies isolating these pods for {direction.lower()}: {names}"}
    if direction != "Ingress":
        return {"status": "pass", "observed": f"policies isolating these pods for {direction.lower()}: {names}"}
    if "peer_ns_labels" in c:
        peer = c["peer_ns_labels"]

        def admits(rule: dict) -> bool:
            frm = rule.get("from")
            if not frm:
                return True
            # a namespaceSelector entry admits every pod of the matching namespaces only when it has no podSelector
            # (or an empty one); a podSelector alone means pods of this namespace
            return any("namespaceSelector" in f and _selects(f.get("namespaceSelector"), peer) and not (f.get("podSelector") or {}) for f in frm)

        port, port_name = c.get("port"), c.get("port_name")
        allowed = not ingress or any(admits(rule) and _admits_port(rule, port, port_name)
                                     for p in ingress for rule in (p.get("spec") or {}).get("ingress") or [])
        on = f" on port {port}" if port else ""
        if allowed != bool(c.get("allows", True)):
            return {"status": "fail", "observed": f"no policy among [{names}] admits namespaces labelled {peer}{on}"}
        return {"status": "pass", "observed": f"isolated by [{names}]; namespaces labelled {list(peer)} admitted{on}"}

    return {"status": "pass", "observed": f"policies isolating these pods for ingress: {names}"}


def c_any(ns: str, c: Check) -> Outcome:
    """Passes when any of the nested checks passes (alternative evidence for the same outcome)."""
    outs = [run_check(ns, {"id": f"{c.get('id')}.{i}", "title": "", **sub}) for i, sub in enumerate(c["of"])]
    good = next((o for o in outs if o["status"] == "pass"), None)
    if good:
        return {"status": "pass", "observed": good["observed"]}
    status = "error" if all(o["status"] == "error" for o in outs) else "fail"
    return {"status": status, "observed": " | ".join(o["observed"] for o in outs)[:300]}


def _location(resp) -> str | None:
    h = getattr(resp, "headers", None)
    return h.get("Location") if h is not None else None


def _helm_release(ns: str, release: str):
    """The newest stored revision of a Helm release, decoded: Helm keeps each revision in a Secret
    sh.helm.release.v1.<release>.v<N> (labels owner=helm, name=<release>, version=<N>), whose `release` field is
    base64(gzip(JSON)) inside the usual Secret base64."""
    import base64
    import gzip

    obj, r = _get(ns, "secret", selector=f"owner=helm,name={release}")
    if obj is None:
        return None, r
    items = obj.get("items") or []
    if not items:
        return {}, r
    newest = max(items, key=lambda s: int((s.get("metadata", {}).get("labels") or {}).get("version", "0") or 0))
    raw = base64.b64decode(base64.b64decode((newest.get("data") or {}).get("release", "")))
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw), r


def _merge(base: Any, over: Any) -> Any:
    if isinstance(base, dict) and isinstance(over, dict):
        return {**base, **{k: _merge(base.get(k), v) for k, v in over.items()}}
    return over if over is not None else base


def c_helm_release(ns: str, c: Check) -> Outcome:
    """The newest revision of a Helm release has the expected status and effective values (chart defaults merged
    with the values the release was installed or upgraded with). Live objects changed by hand afterwards do not
    change the release: that is the point of checking it."""
    try:
        rel, r = _helm_release(ns, c["release"])
    except Exception as e:  # undecodable release data
        return {"status": "error", "observed": f"could not read the release: {type(e).__name__}"}
    if rel is None:
        return _fail_unreachable(r)
    if not rel:
        return {"status": "fail", "observed": f"no Helm release named {c['release']} in this project"}
    status = (rel.get("info") or {}).get("status")
    if status != c.get("status", "deployed"):
        return {"status": "fail", "observed": f"release {c['release']} revision {rel.get('version')} is {status}"}
    values = _merge((rel.get("chart") or {}).get("values") or {}, rel.get("config") or {})
    wrong = [f"{k} = {dig(values, k)!r}" for k, want in (c.get("values") or {}).items() if not compare(dig(values, k), "eq", want)]
    if wrong:
        return {"status": "fail", "observed": f"release {c['release']} revision {rel.get('version')} has " + ", ".join(wrong)}
    shown = ", ".join(f"{k} = {dig(values, k)!r}" for k in (c.get("values") or {}))
    return {"status": "pass", "observed": f"release {c['release']} revision {rel.get('version')} {status}" + (f": {shown}" if shown else "")}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # report the 3xx itself instead of following it
        return None


def c_route_http(ns: str, c: Check) -> Outcome:
    """GET the Route's public URL from this machine, the way a browser would."""
    route, r = _get(ns, "route", c["route"])
    if route is None:
        return _fail_unreachable(r)
    ingress = (route.get("status", {}).get("ingress") or [{}])[0]
    admitted = next((x for x in ingress.get("conditions") or [] if x.get("type") == "Admitted"), None)
    if admitted and admitted.get("status") != "True":
        return {"status": "fail", "observed": f"Route {c['route']} is not admitted by the router: {admitted.get('reason', '')} {admitted.get('message', '')}".strip()[:300]}
    backend = (route.get("spec", {}).get("to") or {}).get("name")
    rpath = route.get("spec", {}).get("path") or ""
    if rpath and not c.get("path", "/").startswith(rpath):
        return {"status": "fail", "observed": f"Route {c['route']} only serves {rpath}, not {c.get('path', '/')} (another Route may answer there)"}
    if not backend:
        return {"status": "fail", "observed": f"Route {c['route']} has no backend Service"}
    if backend:
        svc, _ = _get(ns, "service", backend)
        if svc is None:
            return {"status": "fail", "observed": f"Route {c['route']} sends traffic to Service {backend}, which does not exist (another Route may answer for the same host)"}
    host = route.get("spec", {}).get("host") or ""
    tls = route.get("spec", {}).get("tls")
    # Only fetch hosts served by the cluster's own router (no SSRF to arbitrary hosts), and never follow redirects.
    canonical = ((route.get("status", {}).get("ingress") or [{}])[0]).get("routerCanonicalHostname") or ""
    domain = canonical.split(".", 1)[1] if "." in canonical else ""
    if not domain or not host.endswith("." + domain) or not re.fullmatch(r"[a-z0-9.-]+", host):
        return {"status": "error", "observed": f"refusing to fetch {host!r}: not a host of the cluster router ({domain or 'unknown domain'})"}
    scheme = c.get("scheme") or ("https" if tls else "http")  # `scheme: http` on a TLS Route tests its insecure policy
    if scheme not in ("http", "https"):
        return {"status": "error", "observed": f"unsupported scheme {scheme!r}"}
    url = f"{scheme}://{host}{c.get('path', '/')}"
    ctx = ssl.create_default_context()
    # The CRC router serves a certificate from the cluster's own ingress CA, which this host does not trust.
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ctx))
        with opener.open(urllib.request.Request(url, headers={"User-Agent": "academy-check"}), timeout=8) as resp:
            code, body, location = resp.status, resp.read(4000).decode("utf-8", "replace"), _location(resp)
    except urllib.error.HTTPError as e:
        code, body, location = e.code, e.read(2000).decode("utf-8", "replace"), _location(e)
    except Exception as e:  # the grading host could not complete the request (DNS, refused, timeout): not a learner failure
        return {"status": "error", "observed": f"{url}: {type(e).__name__}: {e} (this machine could not reach the router)"[:300]}
    ok = code == c.get("expect_status", 200)
    if ok and "location_prefix" in c:  # where a redirect points, e.g. https://
        ok = str(location or "").startswith(c["location_prefix"])
    if ok and "contains" in c:
        ok = c["contains"] in body
    text = re.sub(r"(?is)<(style|script|head)[^>]*>.*?</\1>", " ", body)  # page text, not its CSS
    snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()[:120]
    return {"status": "pass" if ok else "fail", "observed": f"{url} → HTTP {code}" + (f" → {location}" if location else "") + f" · {snippet}"}


CHECKS: dict[str, Callable[[str, Check], Outcome]] = {
    "exists": c_exists,
    "absent": c_absent,
    "field": c_field,
    "field_ref": c_field_ref,
    "count": c_count,
    "deployment_ready": c_deployment_ready,
    "pods": c_pods,
    "endpoints": c_endpoints,
    "event": c_event,
    "can_i": c_can_i,
    "exec": c_exec,
    "route_http": c_route_http,
    "container": c_container,
    "rules_deny": c_rules_deny,
    "helm_release": c_helm_release,
    "netpol_ingress": c_netpol_ingress,
    "any": c_any,
}


def run_check(ns: str, c: Check) -> Outcome:
    ns = c.get("namespace") or ns  # a check may target one of the lab's extra projects
    fn = CHECKS.get(c["type"])
    if not fn:
        return {"id": c.get("id"), "title": c.get("title"), "status": "error", "observed": f"unknown check type {c['type']}"}
    try:
        out = fn(ns, c)
    except Exception as e:  # a broken check must never look like a pass
        out = {"status": "error", "observed": f"{type(e).__name__}: {e}"[:300]}
    return {"id": c.get("id"), "title": c.get("title"), "expect": c.get("expect_text"), **out}


def verdict(results: list[Outcome]) -> str:
    """verified | partial | failed | unavailable — never 'verified' unless every check passed."""
    if not results:
        return "unavailable"
    # "unavailable" only when nothing could be checked; a real failure next to a check that could not run is still
    # a failure (the error is shown on its own line), never hidden behind "could not check".
    if all(r["status"] == "error" for r in results):
        return "unavailable"
    passed = sum(r["status"] == "pass" for r in results)
    if passed == len(results):
        return "verified"
    return "partial" if passed else "failed"
