"""Run every command of a lab or incident against a real cluster, assert the expected outcomes, verify the
result, and store the real outputs as a recording.

The recordings are:
  * the test suite for the content (a lab whose commands fail, or whose verification does not pass after
    the steps, fails the recording), and
  * the data for practice mode: learners without a cluster replay real outputs, labelled as recordings.
"""
from __future__ import annotations

import json
import re
import shlex
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config, environment, kube, labs, runner

TOKEN = re.compile(r"\{(pod|anypod|rs|ns|route-host)(?::([^}@]*))?(?:@([a-z0-9-]+))?\}")


def _pods(ns: str, selector: str):
    obj, _ = kube.oc_json("learner", ["get", "pods", "-n", ns] + (["-l", selector] if selector else []))
    return (obj or {}).get("items", [])


def resolve(text: str, lab: labs.Lab) -> str:
    def sub(m: re.Match) -> str:
        kind, arg, ns = m.group(1), m.group(2) or "", m.group(3) or lab.namespace
        if kind == "ns":
            return lab.namespace
        if kind in ("pod", "anypod"):
            pods = [p for p in _pods(ns, arg) if not p["metadata"].get("deletionTimestamp")]
            if kind == "pod":
                pods = [p for p in pods if p.get("status", {}).get("phase") == "Running"]
            pods.sort(key=lambda p: (p["metadata"]["creationTimestamp"], p["metadata"]["name"]))
            if not pods:
                raise RuntimeError(f"no {'running ' if kind == 'pod' else ''}pod for {arg} in {ns}")
            return pods[0]["metadata"]["name"]
        if kind == "rs":
            obj, _ = kube.oc_json("learner", ["get", "rs", "-n", ns, "-l", arg])
            items = sorted((obj or {}).get("items", []), key=lambda r: r["metadata"]["creationTimestamp"])
            if not items:
                raise RuntimeError(f"no replicaset for {arg}")
            return items[-1]["metadata"]["name"]
        if kind == "route-host":
            obj, _ = kube.oc_json("learner", ["get", "route", arg, "-n", ns])
            return (obj or {}).get("spec", {}).get("host", "")
        return m.group(0)

    return TOKEN.sub(sub, text)


def wait_checks(lab: labs.Lab, ids: list[str], timeout: float = 240) -> dict:
    t0 = time.monotonic()
    res = labs.verify(lab, ids)
    while res["verdict"] != "verified" and time.monotonic() - t0 < timeout:
        time.sleep(3)
        res = labs.verify(lab, ids)
    return res


def verify_checkable(lab: labs.Lab, timeout: float = 120) -> dict:
    """Grade once every check can run (no `error`, for example a probe pod still starting), within a bounded wait.

    The starting state is evidence that the grader rejects it; a grade where checks could not run proves nothing.
    """
    t0 = time.monotonic()
    res = labs.verify(lab)
    while any(r["status"] == "error" for r in res["results"]) and time.monotonic() - t0 < timeout:
        time.sleep(3)
        res = labs.verify(lab)
    return res


def settle(lab: labs.Lab, timeout: float = 240) -> None:
    """Wait until no pod in the lab projects is still pulling images or creating containers."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        busy = False
        for ns in lab.namespaces:
            obj, _ = kube.oc_json("learner", ["get", "pods", "-n", ns])
            for p in (obj or {}).get("items", []):
                statuses = p.get("status", {}).get("containerStatuses")
                if p.get("status", {}).get("phase") == "Pending" and not statuses and any(
                    c.get("type") == "PodScheduled" and c.get("status") == "True" for c in p.get("status", {}).get("conditions", [])):
                    busy = True
                for c in statuses or []:
                    if (c.get("state", {}).get("waiting") or {}).get("reason") in ("ContainerCreating", "PodInitializing"):
                        busy = True
        if not busy:
            return
        time.sleep(3)


def run_cmd(lab: labs.Lab, c: labs.Cmd) -> dict:
    entry = {"cmd": c.cmd, "as": c.as_, "expect": c.expect}
    if c.skip:
        return {**entry, "skipped": c.skip}
    try:
        text = resolve(c.run or c.cmd, lab)
    except RuntimeError as e:
        return {**entry, "run": c.run, "code": -1, "stdout": "", "stderr": str(e), "ok": False}
    stdin = resolve(c.stdin, lab) if c.stdin else None
    if c.as_ == "admin":
        argv = shlex.split(text)
        r = kube.oc("admin", argv[1:], stdin=stdin, timeout=c.timeout) if argv[0] in ("oc", "kubectl") else None
        out = r.public() if r else {"code": -1, "stdout": "", "stderr": "admin commands must be oc", "status": "error"}
        res = {"code": out["code"], "stdout": out["stdout"], "stderr": out["stderr"]}
    else:
        out = runner.execute(text, c.as_, lab.namespace, lab, stdin, timeout=c.timeout)
        if out.get("refused"):
            return {**entry, "run": text, "code": -1, "stdout": "", "stderr": f"REFUSED BY POLICY: {out['reason']}", "ok": False}
        res = {"code": out["code"], "stdout": out["stdout"], "stderr": out["stderr"]}
    ok = c.expect == "any" or (c.expect == "ok") == (res["code"] == 0)
    return {**entry, "run": text if text != c.cmd else None, **res, "stdout": res["stdout"][-20000:], "stderr": res["stderr"][-6000:], "ok": ok}


def cluster_meta() -> dict:
    meta = {}
    r = kube.oc("learner", ["version", "-o", "json"])
    try:
        v = json.loads(r.stdout)
        meta["kubernetes"] = v.get("serverVersion", {}).get("gitVersion")
        meta["oc"] = v.get("releaseClientVersion") or v.get("clientVersion", {}).get("gitVersion")
        meta["openshift"] = v.get("openshiftVersion")
    except ValueError:
        pass
    if not meta.get("openshift"):
        # developer cannot read ClusterVersion; the reader identity can.
        r = kube.oc("reader", ["get", "clusterversion", "version", "-o", "jsonpath={.status.desired.version}"])
        if r.code == 0 and r.stdout.strip():
            meta["openshift"] = r.stdout.strip()
    return meta


def run_trials(lab: labs.Lab, problems: list[str], log=print) -> list[dict]:
    """Grade each trial (a wrong, partial or alternative solution) on a fresh copy of the challenge.

    Checks expected to pass get a bounded wait for reconciliation; the rest are read after a short settle, because a
    wrong solution never converges. The verdict and the per-check expectations must match, or the recording fails.
    """
    out = []
    for t in lab.trials:
        c = labs.cleanup(lab, wait_s=120)
        if c.get("state") != "clean":
            problems.append(f"trial {t.id}: could not start clean: {c.get('state')}")
            break
        prep = labs.prepare(lab, elevated=True)
        if not prep["ok"]:
            problems.append(f"trial {t.id}: prepare failed: {prep.get('reason')}")
            break
        settle(lab)
        entries = []
        for cmd in t.commands:
            e = {"step": f"trial:{t.id}", **labs.run_tracked(lab, cmd, lambda cmd=cmd: run_cmd(lab, cmd))}
            entries.append(e)
            log(f"   [{'ok' if e.get('ok') else 'FAIL'}] trial {t.id}: {(e.get('run') or e['cmd'])[:100]} -> {e.get('code')}")
        # Reconciliation (rollouts, policy programming) takes time and may pass through other states: poll until the
        # expected result is observed twice in a row, within a bound; a wrong solution never converges, so the bound
        # is the outcome for it.
        def matches(v: dict) -> bool:
            got = {r["id"]: r["status"] for r in v["results"]}
            return v["verdict"] == t.expect and all(got.get(k) == want for k, want in t.expect_checks.items())
        t0, streak = time.monotonic(), 0
        v = verify_checkable(lab, timeout=60)
        while time.monotonic() - t0 < 150:
            streak = streak + 1 if matches(v) else 0
            if streak >= 2:
                break
            time.sleep(5)
            v = labs.verify(lab)
        got = {r["id"]: r["status"] for r in v["results"]}
        bad = [k for k, want in t.expect_checks.items() if got.get(k) != want]
        ok = streak >= 2 and v["verdict"] == t.expect and not bad and all(e.get("ok") for e in entries)  # stable, not one sample
        if not ok:
            problems.append(f"trial {t.id} ({t.kind}): expected {t.expect} {t.expect_checks or ''}, got {v['verdict']} {got}"
                            + ("; a trial command failed" if not all(e.get("ok") for e in entries) else ""))
        log(f"   trial {t.id}: expected {t.expect}, got {v['verdict']} -> {'ok' if ok else 'MISMATCH'}")
        out.append({"id": t.id, "title": t.title, "kind": t.kind, "expect": t.expect, "got": v["verdict"], "ok": ok,
                    "results": v["results"], "entries": entries})
    return out


def record(lab: labs.Lab, keep: bool = False, log=print) -> dict:
    started = time.time()
    rec: dict = {"lab": lab.id, "kind": lab.kind, "lab_hash": labs.lab_hash(lab), "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cluster": cluster_meta(), "entries": []}
    problems: list[str] = []
    if environment.current().get("class") != "training":
        return {"lab": lab.id, "ok": False, "problems": ["this cluster is not approved for training labs (Connections page); "
                                                         "nothing was cleaned, adopted or created"]}
    cleanup_first = labs.cleanup(lab, wait_s=120)
    if cleanup_first.get("state") == "unowned":
        # a project with this lab's name that the ledger did not create is never adopted here: the operator decides
        return {"lab": lab.id, "ok": False, "problems": [
            f"project(s) {', '.join(cleanup_first.get('unowned', []))} exist but were not created by this academy's ledger; "
            "adopt them on the Connections page (typing the name) or delete them, then record again"]}
    if cleanup_first.get("state") != "clean":
        problems.append(f"pre-cleanup: {cleanup_first.get('state')}: {cleanup_first.get('reason', '')}")
    prep = labs.prepare(lab, elevated=True)
    if not prep["ok"]:
        return {"lab": lab.id, "ok": False, "problems": [f"prepare failed: {prep.get('reason')}"] + [s["stderr"][-200:] for s in prep.get("steps", []) if s.get("code")]}
    settle(lab)
    if lab.kind == "incident":
        time.sleep(20)  # let symptoms develop (restarts, backoff, events)
    rec["verify_before"] = verify_checkable(lab)
    if lab.checks and rec["verify_before"]["verdict"] == "verified":
        problems.append("already verified before any learner action")

    failed = {"stop": False}

    def run_all(where: str, cmds: list[labs.Cmd]):
        for c in cmds:
            if failed["stop"]:
                return
            e = {"step": where, **labs.run_tracked(lab, c, lambda c=c: run_cmd(lab, c))}
            rec["entries"].append(e)
            flag = "skip" if e.get("skipped") else ("ok" if e["ok"] else "FAIL")
            log(f"   [{flag}] {where}: {(e.get('run') or e['cmd'])[:110]} -> {e.get('code')}")
            if not e.get("skipped") and not e["ok"]:
                failed["stop"] = where != "commands"  # stop the lab: later steps depend on this one
                problems.append(f"{where}: `{e.get('run') or e['cmd']}` exit {e.get('code')} (expected {c.expect}): {(e.get('stderr') or e.get('stdout'))[-200:]}")

    from . import policy

    reference = []
    for c in lab.commands:  # lab-level quick reference: mutating ones run inside the steps instead
        try:
            write = c.as_ != "admin" and policy.plan(c.run or c.cmd, c.as_, lab.namespace, str(labs.labfiles_dir(lab))).write
        except policy.Refused:
            write = False
        reference.append(c.model_copy(update={"skip": "runs in the lab steps"}) if write and not c.skip else c)
    run_all("commands", reference)
    if lab.kind == "incident":
        run_all("investigate", lab.investigate)
        run_all("fix", lab.fix)
        if lab.fix_wait:
            wait_checks(lab, lab.fix_wait)
    if lab.kind == "challenge":
        run_all("fix", lab.fix)  # the reference solution; learners never see it before solving or revealing
    for s in lab.steps:
        run_all(s.id, s.commands)
        if failed["stop"]:
            break
        if s.wait_for:
            w = wait_checks(lab, s.wait_for)
            if w["verdict"] != "verified":
                problems.append(f"step {s.id}: waited for {s.wait_for} but got {[(r['id'], r['observed'][:120]) for r in w['results'] if r['status'] != 'pass']}")
    final_ids = [c.id for c in lab.checks if c.model_dump().get("final", True) is not False]
    final = (wait_checks(lab, final_ids, timeout=10 if failed["stop"] else 180) if final_ids else {"verdict": "not-applicable", "results": []})
    rec["verify_after"] = final
    if final_ids and final["verdict"] != "verified":
        problems.append("final verification: " + "; ".join(f"{r['id']}: {r['observed'][:150]}" for r in final["results"] if r["status"] != "pass"))
    if getattr(lab, "trials", None) and not failed["stop"]:
        rec["trials"] = run_trials(lab, problems, log)
    rec["seconds"] = round(time.time() - started)
    if keep:
        rec["cleanup"] = {"state": "kept", "detail": ["--keep: the lab projects were left in place on purpose"]}
    else:
        # Cleanup is verified separately from execution; a recording is only ok when its cleanup is verified too.
        c = labs.cleanup(lab, wait_s=240)  # pods holding claims (StatefulSets) take longer to let a project go
        rep = c.get("report") or {}
        if rep.get("state") == "blocked" and kube.whoami("admin").get("connected") and any(v["phase"] == "released-needs-admin" for v in rep.get("volumes", [])):
            from . import ledger

            ledger.reclaim_volumes(rep["run"]["id"])  # Retain StorageClasses leave Released volumes; reclaim with admin
            rep = ledger.report(rep["run"]["id"])
        rec["cleanup"] = {"state": rep.get("state", c.get("state")), "remaining": rep.get("remaining"),
                          "detail": [f"{e['kind']}/{e['name']}: {e['phase']}" for e in rep.get("effects", [])] + [f"pv/{v['pv']}: {v['phase']}" for v in rep.get("volumes", [])]}
        # Everything the lab created is gone except volumes a Retain StorageClass keeps on purpose: those are owned
        # (recorded by the ledger with their claim UID) and wait for an administrator. That is reported as its own
        # state, never as "clean", and only accepted when the lab declares it in `supports`.
        effects_gone = all(e.get("phase") in ("gone", "deleted", "reclaimed") for e in rep.get("effects", []))
        vols = rep.get("volumes", [])
        if (rec["cleanup"]["state"] == "blocked" and effects_gone and vols and all(v["phase"] == "released-needs-admin" for v in vols)
                and "Retain" in lab.supports):
            rec["cleanup"]["state"] = "volumes-await-admin"
        elif rec["cleanup"]["state"] != "clean":
            problems.append(f"cleanup not verified: {rec['cleanup']}")
    rec["ok"] = not problems
    rec["problems"] = problems
    config.RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    out = config.RECORDINGS_DIR / f"{lab.id}.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out)  # one final, atomic write: never "ok" before the cleanup result is known
    return {"lab": lab.id, "ok": not problems, "problems": problems, "seconds": rec["seconds"]}


# ---------------------------------------------------------------- lessons: commands on the learner's own machine
HOST_ENV_KEYS = ("PATH", "HOME", "USER", "LANG", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "TMPDIR")  # the bus: Podman health checks use systemd timers


def _private_values() -> list[tuple[str, str]]:
    """Values that identify the recording machine or its owner, with the neutral text that replaces them."""
    import getpass
    import socket

    host = socket.gethostname()  # may itself be an address: it stays "workstation", as in earlier recordings
    pairs = [(str(Path.home()), "/home/learner"), (getpass.getuser(), "learner"), (host, "workstation")]
    try:
        fqdn = socket.getfqdn()
        if not re.fullmatch(r"[\d.]+|[\da-fA-F:]+", fqdn):  # an unresolvable name comes back as an address
            pairs.append((fqdn, "workstation"))
    except OSError:
        pass
    # the machine's own network addresses (LAN, VPN, bridges) become documentation addresses (RFC 5737, RFC 3849)
    import subprocess

    try:
        addrs = subprocess.run(["hostname", "-I"], capture_output=True, text=True, encoding="utf-8", timeout=5).stdout.split()
    except (OSError, subprocess.SubprocessError):
        addrs = []
    v4 = v6 = 200  # high numbers, so they never collide with documentation addresses a lesson uses itself
    for a in addrs:
        if a.startswith("127.") or a == "::1" or a == host:
            continue
        if ":" in a:
            pairs.append((a, f"2001:db8::{v6}"))
            v6 += 1
        else:
            pairs.append((a, f"192.0.2.{v4}"))
            v4 += 1
    # the DNS servers this machine uses (they reveal its network or VPN): one documentation address for all
    try:
        for line in Path("/etc/resolv.conf").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "nameserver" and parts[1] not in ("127.0.0.1", "::1", "127.0.0.53"):
                pairs.append((parts[1], "192.0.2.53"))
    except OSError:
        pass
    # longest first, so /home/<user> is replaced before <user>; skip values too short to replace safely
    return sorted({(v, r) for v, r in pairs if v and len(v) >= 3}, key=lambda x: -len(x[0]))


def redact(text: str, pairs: list[tuple[str, str]]) -> str:
    for value, neutral in pairs:
        text = re.sub(rf"(?<![\w.-]){re.escape(value)}(?![\w-])", neutral, text)
    return text


TIMED_OUT = -1  # never an expected outcome, whatever the command's `expect`


def _expected(expect: str, code: int) -> bool:
    return code != TIMED_OUT and (expect == "any" or (expect == "ok") == (code == 0))


def _run_ordered(cmd: str, cwd: Path, env: dict, timeout: int) -> tuple[int, str, str, str]:
    """Run a lesson command through bash and keep, besides stdout and stderr, both streams in the order their
    output arrived, as a terminal would show them (approximately: a program that buffers its stdout when it is
    not a terminal flushes it later than it would on screen)."""
    import selectors
    import subprocess

    import os as _os
    import signal

    # its own session, so that a timeout stops every process the command started, not only bash
    p = subprocess.Popen(["bash", "-c", cmd], cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    sel = None
    try:
        sel = selectors.DefaultSelector()
        sel.register(p.stdout, selectors.EVENT_READ, "out")
        sel.register(p.stderr, selectors.EVENT_READ, "err")
        parts: dict[str, list[bytes]] = {"out": [], "err": []}
        both: list[bytes] = []
        deadline = time.time() + timeout
        return _collect(p, sel, parts, both, deadline, timeout, 2)
    except BaseException:
        # interrupted (Ctrl-C) or failed while the command runs: stop every process it started before anything else
        # (a rollback must never run next to a lesson command that is still changing the cluster)
        try:
            _os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.wait(timeout=30)
        raise
    finally:
        import contextlib

        for close in (getattr(sel, "close", None), getattr(p.stdout, "close", None), getattr(p.stderr, "close", None)):
            if close:
                with contextlib.suppress(Exception):
                    close()


def _collect(p, sel, parts, both, deadline, timeout, open_):
    import os as _os
    import signal
    import subprocess

    while open_:
        left = deadline - time.time()
        if left <= 0:
            try:
                _os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait(timeout=30)
            return TIMED_OUT, b"".join(parts["out"]).decode(errors="replace"), f"timed out after {timeout}s", b"".join(both).decode(errors="replace")
        for key, _ in sel.select(timeout=min(left, 1)):
            chunk = key.fileobj.read1(65536)  # type: ignore[union-attr]
            if not chunk:
                sel.unregister(key.fileobj)
                open_ -= 1
                continue
            parts[key.data].append(chunk)
            both.append(chunk)
    try:
        code = p.wait(timeout=max(1, deadline - time.time()))
    except subprocess.TimeoutExpired:  # the streams closed but the process lives on: stop the whole group
        try:
            _os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.wait(timeout=30)
        code = TIMED_OUT
    dec = lambda b: b"".join(b).decode(errors="replace")  # noqa: E731
    return code, dec(parts["out"]), dec(parts["err"]), dec(both)


def _write_owner_only(path: Path, text: str) -> None:
    """Create a new file readable by its owner only (refused if anything, even a link, already has that name)."""
    import os

    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def _cluster_session(lesson, work: Path, env: dict) -> tuple[str | None, dict, str]:
    """Prepare a lesson recorded on the cluster: a temporary project created as the learner identity (never an
    administrator), a private copy of the learner kubeconfig whose current namespace is that project, and `kubectl`
    on the PATH. `kubectl` here is the Kubernetes client built into `oc` (the same binary invoked as kubectl);
    the recording states its version."""
    import os
    import re as _re
    import subprocess

    if not kube.whoami("learner").get("connected"):
        return None, {}, "the learner identity is not connected (Connections page)"
    if environment.current().get("class") != "training":
        return None, {}, "this cluster is not approved for training labs (Connections page); nothing was created"
    namespace = "academy-lesson-" + _re.sub(r"[^a-z0-9-]+", "-", lesson.id.lower()).strip("-")[:40]
    create = ["new-project", namespace, f"--description={config.MARKER}", "--skip-config-write"]
    r = kube.oc("learner", create, timeout=60)
    if not r.ok and ("AlreadyExists" in r.stderr or "already exists" in r.stderr):
        # a description can be copied, so an existing project is never deleted here: wait a little in case the
        # previous recording's project is still terminating, else stop and say so
        for _ in range(45):
            time.sleep(2)
            if not kube.oc("learner", ["get", "project", namespace], timeout=30).ok:
                break
        r = kube.oc("learner", create, timeout=60)
        if not r.ok and ("AlreadyExists" in r.stderr or "already exists" in r.stderr):
            return None, {}, f"project {namespace} already exists; it was not touched. Delete it yourself if it is a leftover, then record again"
    if not r.ok:
        return None, {}, f"could not create the temporary project {namespace}: {r.stderr.strip()[:200]}"
    # the UID of the project just created, read at once (`oc new-project` does not print it): cleanup deletes that
    # object only, and the API server refuses a same-name replacement
    from . import ledger

    _state, uid = ledger.uid_of("learner", f"/apis/project.openshift.io/v1/projects/{namespace}")
    cfg = work.parent / f"{work.name}.kubeconfig"
    src = kube.kubeconfig("learner")
    # relative file references (the cluster CA) must keep pointing next to the original kubeconfig
    _write_owner_only(cfg, _re.sub(r"(certificate-authority|client-certificate|client-key): (?!/)(\S+)",
                                   lambda m: f"{m.group(1)}: {src.parent / m.group(2)}", src.read_text(encoding="utf-8")))
    kube_env = {**env, "KUBECONFIG": str(cfg)}
    oc_path = config.oc_path()
    subprocess.run([oc_path, "config", "set-context", "--current", f"--namespace={namespace}"], env=kube_env, capture_output=True)
    bin_dir = work.parent / f"{work.name}.bin"
    bin_dir.mkdir()
    (bin_dir / "kubectl").symlink_to(oc_path)
    (bin_dir / "oc").symlink_to(oc_path)
    env.update(KUBECONFIG=str(cfg), PATH=f"{bin_dir}:{env.get('PATH', '')}")
    v = subprocess.run(["kubectl", "version", "-o", "json"], env=env, capture_output=True, text=True, encoding="utf-8")
    info = {}
    try:
        data = json.loads(v.stdout)
        info = {"kubernetes": data.get("serverVersion", {}).get("gitVersion", ""), "kubectl": data.get("clientVersion", {}).get("gitVersion", ""),
                "kubectl_note": "the Kubernetes client built into oc, invoked as kubectl", "namespace": namespace,
                "distribution": "OpenShift Local"}
        ocv = subprocess.run(["oc", "version", "--client"], env=env, capture_output=True, text=True, encoding="utf-8").stdout
        m = _re.search(r"Client Version: (\S+)", ocv)
        if m:
            info["oc"] = m.group(1)
    except ValueError:
        pass
    info["_project_uid"] = uid
    return namespace, info, ""


# ---------------------------------------------------------------- administration lessons (trusted recorder only)
# A lesson recorded with `record_on: cluster-admin` runs each command as one identity: the cluster administrator, the
# ordinary user `developer`, or a throwaway test user that the lesson creates and logs in. Administrator access is
# used here only, by the operator's explicit command (`scripts/record.py --lessons --admin`, which sets
# ACADEMY_ADMIN_RECORDING=1), never by the web server and never for anything a learner types.
#
# The administrator's credentials are used in place, from an existing kubeconfig context (default: the `crc-admin`
# context that OpenShift Local writes into ~/.kube/config), never copied. Rollback, snapshots and health checks use
# a separate recovery identity (default: the certificate-based `system:admin` kubeconfig that OpenShift Local keeps in
# ~/.crc/machines/crc/kubeconfig), which does not depend on the OAuth server, so an authentication experiment that
# goes wrong can still be undone.
ADMIN_REFUSED = ("login", "logout", "config", "project", "new-project")


def _admin_settings() -> dict:
    import os

    return {"kubeconfig": os.environ.get("ACADEMY_ADMIN_KUBECONFIG", str(Path.home() / ".kube" / "config")),
            "context": os.environ.get("ACADEMY_ADMIN_CONTEXT", "crc-admin"),
            "recovery": os.environ.get("ACADEMY_RECOVERY_KUBECONFIG", str(config.CRC_MACHINE / "kubeconfig")),
            "cluster_id": os.environ.get("ACADEMY_ADMIN_CLUSTER_ID", "")}


def _wrapper(bin_dir: Path, oc: str, kubeconfig: str, context: str | None, who: str) -> None:
    """`oc` and `kubectl` in bin_dir, bound to one kubeconfig (and context), refusing the commands that would rewrite
    that kubeconfig."""
    import shlex as _sh

    bin_dir.mkdir(parents=True, exist_ok=True)
    ctx = f" --context={_sh.quote(context)}" if context else ""
    refused = "|".join(ADMIN_REFUSED)
    # Every option is read by its canonical name (`--a_b=x` is `--a-b`), up to `--` (what follows belongs to another
    # program, as in `oc debug … -- ps -eZ`). Refused: options that change the connection, the credentials or the
    # kubeconfig, in any spelling, including a single-letter bundle that contains `-s` (`-As<server>`); options
    # before the command, except the namespace. Impersonation (`--as`) stays allowed: administration lessons use it to
    # show what another user may do. This guards trusted course content against mistakes; it is not a sandbox.
    deny = "kubeconfig|context|server|token|user|username|password|cluster|insecure-skip-tls-verify|" \
           "certificate-authority|client-certificate|client-key|tls-server-name|cache-dir|profile|profile-output"
    script = (f"#!/bin/bash\n# {who}: the kubeconfig is used in place; commands that would rewrite it are refused\n"
              f'refuse() {{ echo "refused by the recorder: $1 (the {who} identity and its kubeconfig are fixed)" >&2; exit 97; }}\n'
              'verb=""; skip=0\n'
              'for a in "$@"; do\n'
              '  if [ $skip = 1 ]; then skip=0; continue; fi\n'
              '  [ "$a" = "--" ] && break\n'
              '  case "$a" in\n'
              '    --?*) n="${a#--}"; n="${n%%=*}"; n="${n//_/-}"\n'
              f'      case "$n" in {deny}) refuse "$a";; esac\n'
              '      if [ -z "$verb" ]; then case "$n" in namespace) ;; *) refuse "write the command before $a";; esac; fi\n'
              '      case "$a" in --namespace|--output|--selector|--container|--filename|--loglevel|--request-timeout) skip=1;; esac;;\n'
              '    -?*) l="${a#-}"\n'
              '      case "${l:0:1}" in\n'
              '        n|o|l|c|f|v) [ ${#l} = 1 ] && skip=1;;\n'
              '        *) case "$l" in *s*) refuse "$a";; esac;;\n'
              '      esac\n'
              '      if [ -z "$verb" ] && [ "${l:0:1}" != n ]; then refuse "write the command before $a"; fi;;\n'
              '    *) [ -z "$verb" ] && verb="$a";;\n'
              '  esac\n'
              'done\n'
              f'case "$verb" in {refused}) echo "refused by the recorder: oc $verb would change the {who} kubeconfig '
              f'(use -n, or oc adm new-project)" >&2; exit 97;; esac\n'
              f'exec -a "$(basename "$0")" {_sh.quote(oc)} --kubeconfig={_sh.quote(kubeconfig)}{ctx} "$@"\n')
    for name in ("oc", "kubectl"):
        f = bin_dir / name
        f.write_text(script, encoding="utf-8")
        f.chmod(0o700)


def _sh(cmd: str, cwd: Path, env: dict, timeout: int = 300) -> dict:
    # experiment commands fail when any part of a pipeline fails, so that an error never passes for an empty answer
    code, out, err, both = _run_ordered("set -o pipefail\n" + cmd, cwd, env, timeout)
    return {"cmd": cmd, "code": code, "stdout": out, "stderr": err, "combined": both}


def _admin_session(lesson, work: Path, env: dict) -> tuple[dict, str]:
    """Identities for an administration lesson, after checking that every one of them points at the approved
    training cluster. Returns ({identity: env}, problem)."""
    import os
    import secrets
    import subprocess

    if os.environ.get("ACADEMY_ADMIN_RECORDING") != "1":
        return {}, "administration lessons are recorded only with scripts/record.py --lessons --admin"
    st = _admin_settings()
    if not st["cluster_id"]:
        return {}, "set ACADEMY_ADMIN_CLUSTER_ID to the approved training cluster's ID (oc get clusterversion version -o jsonpath='{.spec.clusterID}')"
    oc = config.oc_path()
    if not oc:
        return {}, "oc not found"
    base = {k: v for k, v in env.items() if k != "KUBECONFIG"}
    rec_bin, adm_bin = work.parent / f"{work.name}.recovery", work.parent / f"{work.name}.admin"
    _wrapper(rec_bin, oc, st["recovery"], None, "recovery administrator")
    _wrapper(adm_bin, oc, st["kubeconfig"], st["context"], "administrator")
    ids = {"recovery": {**base, "PATH": f"{rec_bin}:{base.get('PATH', '')}"},
           "admin": {**base, "PATH": f"{adm_bin}:{base.get('PATH', '')}"}}

    def ask(who: str, args: str) -> str:
        r = subprocess.run(["bash", "-c", f"oc {args}"], env=ids[who], capture_output=True, text=True, encoding="utf-8", timeout=60)
        return r.stdout.strip() if r.returncode == 0 else ""

    if ask("recovery", "whoami") != "system:admin":
        return {}, "the recovery kubeconfig does not authenticate as system:admin (certificate); nothing was run"
    server = ask("recovery", "whoami --show-server")
    cid = ask("recovery", "get clusterversion version -o jsonpath='{.spec.clusterID}'")
    if not server or cid != st["cluster_id"]:
        return {}, f"the recovery identity does not reach the approved cluster (server {server or '?'}, cluster ID {cid or '?'}); nothing was run"
    admin_name = ask("admin", "whoami")
    if not admin_name or ask("admin", "whoami --show-server") != server:
        return {}, f"the administrator context {st['context']} is not logged in to {server}; nothing was run"
    if ask("admin", "auth can-i '*' '*' --all-namespaces") != "yes":
        return {}, f"{admin_name} is not a cluster administrator; nothing was run"
    r = kube.oc("learner", ["whoami", "--show-server"])
    if not r.ok or r.stdout.strip() != server:
        return {}, "the developer (learner) identity points at another cluster; nothing was run"
    namespace, info, problem = _cluster_session(lesson, work, env)  # developer: its own temporary project
    if problem:
        return {}, problem
    ids["developer"] = dict(env)
    # test users: a kubeconfig that knows the cluster and its CA, but holds no credential until the lesson logs in
    ca = config.KUBE_DIR / "crc-api-ca.crt"
    secrets_out = {}
    for user in lesson.test_users:
        cfg = work.parent / f"{work.name}.{user}.kubeconfig"
        _write_owner_only(cfg, "")
        cfg_env = {**base, "KUBECONFIG": str(cfg), "PATH": f"{work.parent / f'{work.name}.bin'}:{base.get('PATH', '')}"}
        for args in (["config", "set-cluster", "training", f"--server={server}"] + ([f"--certificate-authority={ca}", "--embed-certs"] if ca.exists() else []),
                     ["config", "set-context", "training", "--cluster=training", f"--user={user}"], ["config", "use-context", "training"]):
            subprocess.run([oc, *args], env=cfg_env, capture_output=True, text=True, encoding="utf-8")
        os.chmod(cfg, 0o600)
        password = secrets.token_urlsafe(15)
        var = user.upper().replace("-", "_") + "_PASSWORD"
        secrets_out[var] = password
        ids[user] = cfg_env
    for var in lesson.secret_vars:
        secrets_out[var] = secrets.token_urlsafe(15)
    for e in ids.values():
        e.update(secrets_out)  # every identity may need a test user's password (htpasswd, oc login); all are redacted
    info.update(namespace=namespace, admin=admin_name, cluster_id=cid, api=server)
    return {"ids": ids, "info": info, "secrets": secrets_out}, ""


SENSITIVE = [(re.compile(r"sha256~[A-Za-z0-9_-]{20,}"), "sha256~<token>"), (re.compile(r"\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}"), "$2y$<bcrypt hash>"),
             (re.compile(r"(?i)(authorization: bearer )\S+"), r"\1<token>"),
             (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "<jwt>"),  # ServiceAccount and OIDC tokens
             (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "<private key>")]


def scrub(text: str, pairs: list[tuple[str, str]], secrets_: dict) -> str:
    import base64

    for value in sorted(secrets_.values(), key=len, reverse=True):
        text = text.replace(value, "<password>")
        for enc in {base64.b64encode(value.encode()).decode(), base64.b64encode(value.encode()).decode().rstrip("=")}:
            text = text.replace(enc, "<password (base64)>")
    for rx, rep in SENSITIVE:
        text = rx.sub(rep, text)
    return redact(text, pairs)


def _login_check(user: str, private, secrets_: dict) -> tuple[bool, str]:
    """A real password login as `user` into a temporary kubeconfig, `oc whoami`, then `oc logout` (which deletes the
    token on the server) and the file. The password is read from OpenShift Local's file and only given on stdin."""
    import os
    import subprocess
    import tempfile

    pw_file = config.CRC_MACHINE / f"{user}-password"
    oc = config.oc_path()
    if not pw_file.exists() or not oc:
        return False, f"no password file for {user} on this machine"
    try:
        server = subprocess.run([oc, "--kubeconfig", _admin_settings()["recovery"], "whoami", "--show-server"], capture_output=True, text=True, encoding="utf-8", timeout=60).stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "the API server did not answer"
    fd, cfg = tempfile.mkstemp(prefix="academy-login-check-")
    os.close(fd)
    env = {"HOME": os.environ.get("HOME", "/tmp"), "PATH": "/usr/bin:/bin", "KUBECONFIG": cfg}
    ca = config.KUBE_DIR / "crc-api-ca.crt"
    try:
        try:
            # the password goes on stdin (oc prompts for it), never on the command line where other users could read it
            login = subprocess.run([oc, "login", "-u", user, server, *([f"--certificate-authority={ca}"] if ca.exists() else [])],
                                   input=pw_file.read_text(encoding="utf-8").strip() + "\n", env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
            who = subprocess.run([oc, "whoami"], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        except subprocess.TimeoutExpired:
            return False, "the login or the identity check timed out"
        finally:
            try:  # end the session on the server whatever happened (logout deletes the token)
                out = subprocess.run([oc, "logout"], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
                logged_out = out.returncode == 0
            except subprocess.TimeoutExpired:
                logged_out = False
        ok = login.returncode == 0 and who.stdout.strip() == user and logged_out
        return ok, scrub(f"login exit {login.returncode}; whoami: {who.stdout.strip() or who.stderr.strip()}; "
                         f"{'logged out' if logged_out else 'LOGOUT FAILED'}", private, secrets_)
    finally:
        os.unlink(cfg)


def _safe_record(lesson, data: dict, problems: list[str]) -> str:
    """Write the private experiment record; a failure is reported, never allowed to stop the cleanup."""
    try:
        return str(_private_record(lesson, data))
    except Exception as e:  # noqa: BLE001
        problems.append(f"the private experiment record could not be written: {e}")
        return ""


def _private_record(lesson, data: dict) -> Path:
    """The full experiment record (outputs scrubbed of passwords and tokens), kept outside the repository."""
    d = config.RECORDER_DIR / "experiments" / lesson.experiment.id
    d.mkdir(parents=True, exist_ok=True)
    f = d / (data["started"].replace(":", "") + ".json")
    f.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return f


def record_lesson(lesson, log=print) -> dict:
    """Run a lesson's commands in a scratch directory with the lesson's files: on this machine, on the cluster as the
    learner identity, or (administration lessons) as several identities with an experiment and its rollback.

    These come from trusted course content, never from the browser, and may use pipes, so they run through
    bash. The environment is reduced to what rootless Podman needs. The private session directory (the work
    directory, copied kubeconfigs, wrappers, snapshots) is removed however the recording ends.
    """
    import shutil
    import tempfile

    # mkdtemp creates the directory 0700; the work directory and every session file live inside it
    import signal
    import threading

    # the Ctrl-C handler in force when the recording starts is put back at the end, whatever happened in between
    original = signal.getsignal(signal.SIGINT) if threading.current_thread() is threading.main_thread() else None
    base = Path(tempfile.mkdtemp(prefix="academy-lesson-"))
    try:
        return _record_lesson(lesson, base, log)
    finally:
        pending: list = []
        held = _hold_interrupts(pending)
        try:
            shutil.rmtree(base)
        except FileNotFoundError:
            pass
        except OSError as e:  # never silent: the directory holds copies of credentials
            import sys

            print(f"WARNING: could not remove the private session directory {base} ({e}); it holds copies of "
                  "credentials: remove it yourself", file=sys.stderr)
        finally:
            _release_interrupts(original if original is not None else held)
        if pending:  # Ctrl-C while the session directory was being removed: reported once it is gone
            raise pending[0]


def _hold_interrupts(deferred: list) -> object:
    """Hold Ctrl-C (SIGINT) while cleanup runs: it is recorded in `deferred` and re-raised afterwards, so that an
    interruption cannot leave a rollback or a cleanup half done. Only possible in the main thread."""
    import signal
    import threading

    if threading.current_thread() is not threading.main_thread():
        return None
    return signal.signal(signal.SIGINT, lambda signum, frame: deferred.append(KeyboardInterrupt()))


def _release_interrupts(previous: object) -> None:
    import signal

    if previous is not None:
        signal.signal(signal.SIGINT, previous)


def _record_lesson(lesson, base: Path, log) -> dict:
    import os
    import shutil
    import subprocess
    import tempfile

    started = time.time()
    env = {k: os.environ[k] for k in HOST_ENV_KEYS if k in os.environ}
    # `oc image …` and similar registry-only commands may run, but never against a cluster
    env["KUBECONFIG"] = "/nonexistent"
    crc_oc = config.CRC_HOME / "bin" / "oc"
    if not shutil.which("oc", path=env.get("PATH")) and (crc_oc / "oc").exists():
        env["PATH"] = f"{env.get('PATH', '')}:{crc_oc}"
    private = _private_values()
    work = base / "lesson"  # every session file is a sibling of this directory, inside the private base directory
    work.mkdir()
    entries, problems = [], []
    cluster_info: dict = {}
    namespace = None
    project_uid = None
    session: dict = {}
    secrets_: dict = {}
    if lesson.record_on == "cluster-admin":
        session, problem = _admin_session(lesson, work, env)
        if problem:
            shutil.rmtree(work.parent, ignore_errors=True)
            return {"lab": f"lesson.{lesson.id}", "ok": False, "problems": [problem], "seconds": 0}
        cluster_info = session["info"]
        namespace = cluster_info.get("namespace")
        project_uid = cluster_info.pop("_project_uid", None)
        secrets_ = session["secrets"]
    elif lesson.record_on == "cluster":
        namespace, cluster_info, problem = _cluster_session(lesson, work, env)
        project_uid = cluster_info.pop("_project_uid", None)  # never written into the recording
        if problem:
            shutil.rmtree(work.parent, ignore_errors=True)
            return {"lab": f"lesson.{lesson.id}", "ok": False, "problems": [problem], "seconds": 0}
    exp = lesson.experiment
    xrec: dict = {}
    deferred: list[BaseException] = []  # an interruption during rollback or cleanup, raised once cleanup is done
    snap_dir = work.parent / f"{work.name}.snapshot"
    if exp:
        snap_dir.mkdir()
        rec_env = {**session["ids"]["recovery"], "SNAPSHOT_DIR": str(snap_dir)}
        xrec = {"experiment": exp.id, "lesson": lesson.id, "objective": exp.objective,
                "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "cluster": {"id": cluster_info.get("cluster_id"), "api": cluster_info.get("api"), "kubernetes": cluster_info.get("kubernetes"),
                            "oc": cluster_info.get("oc")},
                "identities": {"admin": cluster_info.get("admin"), "recovery": "system:admin (certificate)", "developer": "developer",
                               **{u: u for u in lesson.test_users}},
                "changes": exp.changes, "planned": [{"as": c.as_ or "developer", "cmd": c.cmd, "expect": c.expect} for c in lesson.commands],
                "rollback_plan": exp.rollback, "snapshot": []}
        for v in exp.preflight:
            r = _sh(v.cmd, work, rec_env, v.timeout)
            ok = _expected(v.expect, r["code"])
            xrec.setdefault("preflight", []).append({"cmd": v.cmd, "code": r["code"], "ok": ok})
            if not ok:
                problems.append(f"preflight `{v.cmd}` exit {r['code']} (expected {v.expect}): nothing was changed")
        for k, cmd in enumerate([] if problems else exp.snapshot):
            r = _sh(cmd, work, rec_env, 120)
            (snap_dir / str(k)).write_text(r["stdout"], encoding="utf-8")
            xrec["snapshot"].append({"cmd": cmd, "code": r["code"], "before": scrub(r["stdout"], private, secrets_)})
            if r["code"] != 0:
                problems.append(f"snapshot `{cmd}` failed before any change: {r['stderr'][-200:]}")
        # the plan and the original state are on disk before anything changes; if they cannot be written, nothing runs
        if not _safe_record(lesson, xrec, problems) and not problems:
            problems.append("the private experiment record could not be written: nothing was changed")
    executed = False
    try:
        for name, body in lesson.files.items():
            f = (work / name).resolve()
            if work.resolve() not in f.parents:
                raise ValueError(f"lesson file outside the work dir: {name}")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body, encoding="utf-8")
        for c in ([] if problems else lesson.commands):
            where = (work / c.cwd).resolve() if c.cwd else work
            if where != work.resolve() and work.resolve() not in where.parents:
                raise ValueError(f"lesson command cwd outside the work dir: {c.cwd}")
            who = (c.as_ or "developer") if lesson.record_on == "cluster-admin" else "host"
            run_env = session["ids"][who] if session else env
            executed = True  # before the command: an interrupted first command must still be rolled back
            code, out, err, both = _run_ordered(c.cmd, where, run_env, c.timeout)
            ok = _expected(c.expect, code)
            out, err, both = (scrub(x, private, secrets_) for x in (out, err, both))
            ident = {"identity": cluster_info.get("admin") if who == "admin" else who} if session else {}
            entries.append({"step": "lesson", "cmd": c.cmd, **({"cwd": c.cwd} if c.cwd else {}), "as": who, **ident, "expect": c.expect, "run": None,
                            "code": code, "stdout": out[-20000:], "stderr": err[-6000:], "combined": both[-26000:], "ok": ok})
            log(f"   [{'ok' if ok else 'FAIL'}] {who}: {c.cmd[:110]} -> {code}")
            if not ok:
                problems.append(f"`{c.cmd}` as {who} exit {code} (expected {c.expect}): {(err or out)[-200:]}")
                break
    finally:
        held = _hold_interrupts(deferred)  # Ctrl-C during the rollback and cleanup is held until they are done
        if exp and not executed:  # nothing ran: there is nothing to roll back
            xrec["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            xrec["problems"] = problems
            xrec["restored"] = False
            xrec["private_file"] = _safe_record(lesson, xrec, problems)
            log(f"   experiment {exp.id}: stopped before any lesson command: {problems[:1]}")
        elif exp:
            # the rollback always runs, as the recovery identity, and is verified against the snapshot
            def _attempt(cmd: str) -> dict:  # one failing or interrupted rollback step never stops the next ones
                try:
                    return _sh(cmd, work, rec_env, 600)
                except BaseException as e:  # noqa: BLE001
                    if not isinstance(e, Exception):
                        deferred.append(e)  # Ctrl-C: the remaining rollback and the cleanup still run first
                    return {"cmd": cmd, "code": -2, "stdout": "", "stderr": f"could not run: {type(e).__name__} {e}", "combined": None}
            xrec["rollback"] = [{**r, "stdout": scrub(r["stdout"], private, secrets_)[-4000:], "stderr": scrub(r["stderr"], private, secrets_)[-2000:], "combined": None}
                                for r in (_attempt(cmd) for cmd in exp.rollback)]
            for r in xrec["rollback"]:
                if r["code"] != 0:
                    problems.append(f"rollback `{r['cmd']}` exit {r['code']}: {r['stderr'][-200:]}")
                try:  # reporting a step never stops the cleanup
                    log(f"   [{'ok' if r['code'] == 0 else 'FAIL'}] rollback: {r['cmd'][:100]} -> {r['code']}")
                except BaseException as exc:  # noqa: BLE001
                    if not isinstance(exc, Exception):
                        deferred.append(exc)
            try:  # whatever fails or is interrupted here, the project and the session files are still removed below
                xrec["settle"] = []
                for cmd in exp.settle:
                    r = _sh(cmd, work, rec_env, 1200)
                    xrec["settle"].append({"cmd": cmd, "code": r["code"], "output": scrub(r["combined"], private, secrets_)[-2000:]})
                    if r["code"] != 0:
                        problems.append(f"settle `{cmd}` exit {r['code']}")
                xrec["verify"] = []
                for v in exp.verify:
                    r = _sh(v.cmd, work, rec_env, v.timeout)
                    ok = _expected(v.expect, r["code"])
                    xrec["verify"].append({"cmd": v.cmd, "code": r["code"], "ok": ok, "output": scrub(r["combined"], private, secrets_)[-3000:]})
                    if not ok:
                        problems.append(f"after the rollback, `{v.cmd}` exit {r['code']} (expected {v.expect})")
                for user in exp.login_checks:
                    ok, detail = _login_check(user, private, secrets_)
                    xrec["verify"].append({"cmd": f"(password login as {user} through the cluster's own provider, then logout)", "code": 0 if ok else 1, "ok": ok, "output": detail})
                    log(f"   [{'ok' if ok else 'FAIL'}] login check: {user}")
                    if not ok:
                        problems.append(f"after the rollback, {user} could not log in: {detail}")
                for k, snap in enumerate(xrec["snapshot"]):
                    r = _sh(snap["cmd"], work, rec_env, 120)
                    snap["after"] = scrub(r["stdout"], private, secrets_)
                    snap["same"] = r["code"] == 0 and r["stdout"] == (snap_dir / str(k)).read_text(encoding="utf-8")
                    if not snap["same"]:
                        problems.append(f"not restored: `{snap['cmd']}` differs from before the lesson")
                xrec["restored"] = (all(s.get("same") and s.get("code", 0) == 0 for s in xrec["snapshot"]) and all(r["code"] == 0 for r in xrec["rollback"])
                                    and all(r["code"] == 0 for r in xrec["settle"]) and all(v["ok"] for v in xrec["verify"]))
                xrec["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                xrec["problems"] = problems
                xrec["private_file"] = _safe_record(lesson, xrec, problems)
                log(f"   experiment {exp.id}: {'restored' if xrec['restored'] else 'NOT RESTORED — see ' + xrec['private_file']}")
            except BaseException as exc:  # noqa: BLE001
                problems.append(f"after the rollback: {type(exc).__name__}: {exc}")
                xrec["restored"] = False
                xrec["problems"] = problems
                xrec["private_file"] = _safe_record(lesson, xrec, problems)
                if not isinstance(exc, Exception):
                    deferred.append(exc)  # Ctrl-C: finish the cleanup first, then stop
        try:  # removing the project and writing the record may fail; the session files below are removed anyway
            if namespace:
                from . import ledger

                # only the project this run created: a UID precondition makes the API server refuse anything else
                if project_uid:
                    deleted = ledger._delete_with_uid("learner", f"/apis/project.openshift.io/v1/projects/{namespace}", project_uid)
                    if deleted == "forbidden" and session:
                        # an experiment's rollback may have deleted the project already, and an ordinary user is refused
                        # (Forbidden) a project that no longer exists: the recovery administrator's NotFound proves it
                        r = _sh(f"oc get namespace {namespace}", work, session["ids"]["recovery"], 30)
                        if r["code"] != 0 and "(NotFound)" in r["stderr"]:
                            deleted = "not_found"
                    if deleted not in ("found", "not_found"):
                        problems.append(f"the recorder's temporary project {namespace} could not be deleted ({deleted})")
                    else:
                        # only NotFound proves the removal: a failed read (timeout, lost login) is not an absence
                        # an ordinary user may be refused (Forbidden) a deleted project's read; in an administration
                        # recording the recovery administrator reads the namespace instead, and its NotFound is the proof
                        def read_state() -> str:
                            state = kube.classify(kube.oc("learner", ["get", "project", namespace], timeout=30))
                            if state == "forbidden" and session:
                                r = _sh(f"oc get namespace {namespace}", work, session["ids"]["recovery"], 30)
                                return "found" if r["code"] == 0 else "not_found" if "(NotFound)" in r["stderr"] else "error"
                            if state == "forbidden":
                                # no administrator here: the user's own list of projects showed this one while it
                                # existed (they requested it), so its absence from a successful list is the proof
                                listed = kube.oc("learner", ["get", "projects", "-o", "name"], timeout=30)
                                if listed.ok:
                                    return "found" if f"project.project.openshift.io/{namespace}" in listed.stdout.split() else "not_found"
                            return state

                        t_end = time.monotonic() + 300
                        state = read_state()
                        while state != "not_found" and time.monotonic() < t_end:
                            time.sleep(3)
                            state = read_state()
                        if state == "found":
                            problems.append(f"the recorder's temporary project {namespace} still exists after its deletion")
                        elif state != "not_found":
                            problems.append(f"the removal of the recorder's temporary project {namespace} could not be confirmed ({state})")
                else:
                    log(f"   project {namespace} was left in place: its UID could not be read, so its deletion is not attempted")
                    problems.append(f"the recorder's temporary project {namespace} could not be deleted (UID unknown)")
            if exp and xrec.get("private_file"):
                xrec["problems"] = problems
                xrec["recorder_project_removed"] = not any("temporary project" in p for p in problems)
                _safe_record(lesson, xrec, problems)
        except BaseException as exc:  # noqa: BLE001
            problems.append(f"cleanup: {type(exc).__name__}: {exc}")
            if not isinstance(exc, Exception):
                deferred.append(exc)
        for suffix in (".bin", ".admin", ".recovery", ".snapshot"):
            shutil.rmtree(work.parent / f"{work.name}{suffix}", ignore_errors=True)
        (work.parent / f"{work.name}.kubeconfig").unlink(missing_ok=True)
        for user in lesson.test_users:
            (work.parent / f"{work.name}.{user}.kubeconfig").unlink(missing_ok=True)
        shutil.rmtree(work.parent, ignore_errors=True)
        _release_interrupts(held)
    if deferred:
        raise deferred[0]
    tools = {}
    for tool in ("podman", "skopeo", "buildah"):
        if shutil.which(tool):
            v = subprocess.run([tool, "--version"], capture_output=True, text=True, encoding="utf-8", env=env).stdout.strip()
            tools[tool] = v.split()[-1] if v else ""
    cluster_public = {k: v for k, v in cluster_info.items() if k != "cluster_id"}
    rec = {"lab": f"lesson.{lesson.id}", "kind": "lesson", "lab_hash": lesson.fingerprint(),
           "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cluster": cluster_public, "host": tools,
           "entries": entries, "seconds": round(time.time() - started), "ok": not problems, "problems": problems}
    if exp:
        rec["experiment"] = {"id": exp.id, "restored": xrec.get("restored", False),
                             "rollback": [{"cmd": r["cmd"], "code": r["code"]} for r in xrec.get("rollback", [])],
                             "verify": [{"cmd": v["cmd"], "code": v["code"], "ok": v["ok"]} for v in xrec.get("verify", [])],
                             "snapshot": [{"cmd": x["cmd"], "same": x.get("same", False)} for x in xrec.get("snapshot", [])]}
    if problems and lesson.record_on == "cluster-admin":
        # a failed administration recording never replaces a good one: it is kept privately for inspection
        out = config.RECORDER_DIR / "failed-recordings" / f"lesson.{lesson.id}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        log(f"   failed recording kept at {out}")
    else:
        out = config.RECORDINGS_DIR / f"lesson.{lesson.id}.json"
    config.RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"lab": rec["lab"], "ok": rec["ok"], "problems": problems, "seconds": rec["seconds"]}
