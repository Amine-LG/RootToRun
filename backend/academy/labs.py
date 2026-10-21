"""Lab and incident definitions (YAML, validated) and their lifecycle on a real cluster.

Every command shown to a learner is data: what to display, what it means, who runs it, and what outcome is
expected. The recorder runs every one of them against a real cluster (see recorder.py), which both tests
the content and produces the recordings used by practice mode when no cluster is available.

Lifecycle:  prepare -> (learner works, in the Workbench or a terminal) -> verify -> cleanup
  * prepare: create the lab project(s) as the learner (`oc new-project`, marked academy-owned), write lab
    files, apply setup manifests (and break manifests for incidents). Resumes an interrupted lab.
  * verify: run declarative checks; the verdict is computed only from live cluster state.
  * cleanup: delete the lab projects, but only if they are academy-owned; confirm they are gone.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Literal

import yaml

_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)  # libyaml when available: the content is large
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

from . import checks, config, environment, kube, ledger, policy

MARKER = config.MARKER
Mode = Literal["REAL_LAB", "LOCAL_SIMULATION", "GUIDED_INVESTIGATION", "ENTERPRISE_ARCHITECTURE", "EXTERNAL_LAB_REQUIRED"]
FORBIDDEN_KINDS = {"Namespace", "Project", "ClusterRole", "ClusterRoleBinding", "SecurityContextConstraints", "Node",
                   "PersistentVolume", "StorageClass", "CustomResourceDefinition", "PriorityClass", "MutatingWebhookConfiguration",
                   "ValidatingWebhookConfiguration", "APIService", "ClusterOperator", "ClusterVersion", "MachineConfig"}
ELEVATED_KINDS = {"ResourceQuota", "LimitRange", "RoleBinding"}  # what elevated_setup may create (in the lab project only)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Cmd(Strict):
    cmd: str  # what the learner sees and types (may contain <placeholders>)
    meaning: str = ""
    run: str | None = None  # concrete form for the recorder: {pod:app=web} {rs:app=web} {ns} tokens
    stdin: str | None = None  # YAML for `-f -`
    as_: Literal["learner", "reader", "admin"] = Field("learner", alias="as")
    expect: Literal["ok", "fail", "any"] = "ok"
    skip: str = ""  # non-empty: displayed but never executed (the reason is shown)
    timeout: int = 90


class Predict(Strict):
    prompt: str
    choices: list[str] = []
    answer: int | None = None
    explain: str
    feedback: list[str] = []  # optional, one per choice: why that answer is right or what misunderstanding it reveals

    @model_validator(mode="after")
    def _feedback_matches_choices(self):
        if self.feedback and len(self.feedback) != len(self.choices):
            raise ValueError("feedback needs exactly one entry per choice")
        if self.choices and self.answer is not None and not 0 <= self.answer < len(self.choices):
            raise ValueError("answer is not a valid choice index")
        return self


class Step(Strict):
    id: str
    title: str
    do: str
    commands: list[Cmd] = []
    predict: Predict | None = None
    observe: str = ""
    why: str = ""
    checks: list[str] = []
    wait_for: list[str] = []  # checks the recorder polls after this step's commands


class CheckDef(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    type: str
    expect_text: str = ""

    @field_validator("type")
    @classmethod
    def known(cls, v):
        if v not in checks.CHECKS:
            raise ValueError(f"unknown check type {v}")
        return v


class QA(Strict):
    q: str
    a: str


class Trouble(Strict):
    problem: str
    hint: str


class Ref(Strict):
    title: str
    url: str


def _check_manifests(docs: list[str], allowed: set[str] | None = None) -> list[str]:
    for d in docs:
        for obj in yaml.safe_load_all(d):
            if obj is None:
                continue
            kind = obj.get("kind")
            if allowed is not None and kind not in allowed:
                raise ValueError(f"elevated setup may only create {sorted(allowed)}, not {kind}")
            if allowed is None and kind in FORBIDDEN_KINDS:
                raise ValueError(f"lab manifests may not create {kind}")
            if obj.get("metadata", {}).get("namespace"):
                raise ValueError("lab manifests must not set metadata.namespace (the lab namespace is applied)")
    return docs


class ClusterObject(Strict):
    """A cluster-scoped object that a lab step creates (as admin). Declared so the ledger can track and clean it."""
    kind: str
    name: str
    path: str  # REST path, e.g. /apis/user.openshift.io/v1/groups/academy-auditors
    created_by: str  # the exact `cmd` of the step command that creates it
    deleted_by: str = ""  # the exact `cmd` that deletes it, if the lab removes it itself


class Trial(Strict):
    """A recorded attempt that checks the grader itself: a wrong, partial or alternative solution and the verdict the
    grader must give it. The recorder runs each trial on a fresh copy of the challenge and fails if the grader
    disagrees, so a grader that accepts a plausible but ineffective object is caught before learners meet it."""
    id: str
    title: str
    kind: Literal["wrong", "partial", "alternative"]
    commands: list[Cmd]
    expect: Literal["failed", "partial", "verified"]
    expect_checks: dict[str, Literal["pass", "fail"]] = {}  # per-check expectations, where they matter


ANSWER_HIDDEN = ("incident", "challenge")  # their reference solution is withheld until verified or revealed


class Lab(Strict):
    id: str
    kind: Literal["lab", "incident", "challenge"] = "lab"
    title: str  # two to six words
    subtitle: str = ""
    summary: str
    module: str
    mode: Mode = "REAL_LAB"
    minutes: int
    level: int = Field(1, ge=1, le=3)
    supports: str
    concepts: list[str]
    prerequisites: list[str] = []
    objective: str
    background: str = ""
    commands: list[Cmd] = []
    namespace: str
    extra_namespaces: list[str] = []
    files: dict[str, str] = {}  # available to commands as lab/<path>
    setup: list[str] = []
    elevated_setup: list[str] = []  # applied as admin into the lab project; requires explicit consent
    elevated_why: str = ""
    break_: list[str] = Field([], alias="break")
    symptom: str = ""
    investigate: list[Cmd] = []  # incidents: commands a systematic investigator would run (recorded)
    fix: list[Cmd] = []  # incidents: a reference repair (hidden until verified or revealed)
    fix_wait: list[str] = []
    requirements: list[str] = []  # challenges: the outcomes to reach, stated as observable results
    trials: list[Trial] = []  # challenges: grader self-tests, run by the recorder
    steps: list[Step] = []
    hints: list[str] = []
    checks: list[CheckDef]
    variations: list[str] = []
    troubleshooting: list[Trouble] = []
    root_cause: str = ""
    alternatives: str = ""
    sre: str = ""
    questions: list[QA] = []
    enterprise: str = ""
    references: list[Ref] = []
    requires: list[Literal["crc", "olm", "reader", "admin", "dynamic-storage", "routes"]] = []  # beyond what the content shows
    cluster_objects: list[ClusterObject] = []
    # incidents: the checks that are monitoring-level evidence (availability, the Route's answer, a timeout, a 403), shown
    # before the answer; every other check states the cause and appears only with it. Prose, outside the recording hash.
    symptom_checks: list[str] = []

    @model_validator(mode="after")
    def challenge_complete(self):
        if self.kind == "challenge":
            missing = [n for n, v in (("requirements", self.requirements), ("checks", self.checks), ("fix (reference solution)", self.fix)) if not v]
            if missing:
                raise ValueError(f"a challenge needs {', '.join(missing)}")
            if self.steps:
                raise ValueError("a challenge has no steps: the learner chooses how to reach the outcomes")
            ids = {c.id for c in self.checks}
            for t in self.trials:
                unknown = set(t.expect_checks) - ids
                if unknown:
                    raise ValueError(f"trial {t.id}: unknown checks {sorted(unknown)}")
        return self

    @field_validator("namespace")
    @classmethod
    def ns_ok(cls, v):
        if not policy.NS_RE.match(v) or v == config.SYSTEM_NS:
            raise ValueError("lab namespace must be academy-<name>")
        return v

    @field_validator("extra_namespaces")
    @classmethod
    def extra_ok(cls, v):
        for n in v:
            if not policy.NS_RE.match(n) or n == config.SYSTEM_NS:
                raise ValueError("extra namespaces must be academy-<name>")
        return v

    @field_validator("setup", "break_")
    @classmethod
    def manifests_ok(cls, docs):
        return _check_manifests(docs)

    @field_validator("elevated_setup")
    @classmethod
    def elevated_ok(cls, docs):
        return _check_manifests(docs, ELEVATED_KINDS)

    @field_validator("files")
    @classmethod
    def files_ok(cls, v):
        for p in v:
            if p.startswith("/") or ".." in p.split("/") or not policy.LABFILE_RE.match("lab/" + p):
                raise ValueError(f"invalid lab file path {p}")
        return v

    @property
    def namespaces(self) -> list[str]:
        return [self.namespace, *self.extra_namespaces]

    def all_commands(self) -> list[tuple[str, Cmd]]:
        out = [("commands", c) for c in self.commands]
        for s in self.steps:
            out += [(s.id, c) for c in s.commands]
        out += [("investigate", c) for c in self.investigate] + [("fix", c) for c in self.fix]
        return out


_cache: dict = {}


def _files(lang: str) -> list[Path]:
    d = config.content_dir(lang)
    return sorted([*(d / "labs").glob("*.yaml"), *(d / "incidents").glob("*.yaml"), *(d / "challenges").glob("*.yaml")])


def load(lang: str | None = None) -> dict[str, Lab]:
    lang = lang if lang in config.LANGS else config.DEFAULT_LANG
    if lang != "en":
        return _overlay(lang)
    files = _files(lang)
    sig = tuple((str(f), f.stat().st_mtime) for f in files)
    c = _cache.get(lang)
    if c and c["sig"] == sig:
        return c["labs"]
    labs, errors = {}, []
    for f in files:
        try:
            lab = Lab.model_validate(yaml.load(f.read_text(encoding="utf-8"), Loader=_LOADER))
            if lab.id in labs:
                raise ValueError(f"duplicate id {lab.id}")
            ids = {ch.id for ch in lab.checks}
            for s in lab.steps:
                missing = (set(s.checks) | set(s.wait_for)) - ids
                if missing:
                    raise ValueError(f"step {s.id} refers to unknown checks {missing}")
            if set(lab.fix_wait) - ids:
                raise ValueError("fix_wait refers to unknown checks")
            if set(lab.symptom_checks) - ids:
                raise ValueError(f"symptom_checks refers to unknown checks {sorted(set(lab.symptom_checks) - ids)}")
            labs[lab.id] = lab
        except Exception as e:  # keep the app usable; report the broken file
            errors.append(f"{f.name}: {str(e)[:500]}")
    _cache[lang] = {"sig": sig, "labs": labs, "errors": errors}
    return labs


def _overlay(lang: str) -> dict[str, Lab]:
    """A translated lab replaces the English one only if it changes nothing but prose (same lab_hash), so recordings,
    checks and graders stay exactly those of the English lab. Untranslated labs fall back to English."""
    base = load("en")
    files = _files(lang)
    sig = (tuple((str(f), f.stat().st_mtime) for f in files), tuple(sorted((k, lab_hash(v)) for k, v in base.items())))
    c = _cache.get(lang)
    if c and c["sig"] == sig:
        return c["labs"]
    out, errs = dict(base), list(_cache["en"]["errors"])
    for f in files:
        try:
            raw = yaml.load(f.read_text(encoding="utf-8"), Loader=_LOADER) or {}
            raw.pop("source", None)
            lab = Lab.model_validate(raw)
            if lab.id not in base:
                raise ValueError(f"{lab.id} does not exist in English")
            if lab_hash(lab) != lab_hash(base[lab.id]):
                raise ValueError(f"{lab.id}: a translation may change only prose (title, hints, explanations), not commands or checks")
            out[lab.id] = lab
        except Exception as e:
            errs.append(f"{lang}/{f.name}: {str(e)[:500]}")
    _cache[lang] = {"sig": sig, "labs": out, "errors": errs}
    return out


def errors(lang: str | None = None) -> list[str]:
    lang = lang if lang in config.LANGS else config.DEFAULT_LANG
    load(lang)
    return _cache[lang]["errors"]


def lab_hash(lab: "Lab") -> str:
    """Fingerprint of everything that affects a recording; a changed lab must be recorded again."""
    data = lab.model_dump(by_alias=True, exclude={"title", "subtitle", "summary", "minutes", "level", "supports", "objective", "background", "hints", "variations", "troubleshooting", "root_cause", "alternatives", "sre", "questions", "enterprise", "references", "concepts", "prerequisites", "module", "mode", "elevated_why", "symptom", "requires", "cluster_objects", "symptom_checks"})
    data.pop("requirements", None)  # prose: the outcomes are graded by the checks, which stay in the hash
    if not data.get("trials"):
        data.pop("trials", None)  # absent and empty are the same lab (keeps older recordings current)
    for t in data.get("trials", []):
        t.pop("title", None)
        for c in t.get("commands", []):
            c.pop("meaning", None)
    for s in data.get("steps", []):  # step prose does not change what runs
        for k in ("title", "do", "observe", "why", "predict"):
            s.pop(k, None)
    for group in [data.get("commands", []), data.get("investigate", []), data.get("fix", []), *[s.get("commands", []) for s in data.get("steps", [])]]:
        for c in group:
            c.pop("meaning", None)
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def recording(lab_id: str) -> dict | None:
    f = config.RECORDINGS_DIR / f"{lab_id}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


# ---------------------------------------------------------------- cluster side
def project_state(ns: str) -> dict:
    """exists / owned / phase. The learner sees only its own projects, and OpenShift answers Forbidden (not NotFound)
    for a project it cannot see, whether or not it exists. So: found as the learner → its state; otherwise the reader
    (cluster-reader) decides authoritatively; without the reader, a successful project list that does not contain it
    means "not visible to the learner" (exists False, authoritative False); anything else is unknown (exists None)."""
    state, obj, r = kube.read("learner", ["get", "project", ns])
    if state != "found":
        if kube.whoami("reader").get("connected") and environment.same_cluster("reader"):
            rs, robj, rr = kube.read("reader", ["get", "namespace", ns])
            if rs == "not_found":
                return {"exists": False, "authoritative": True}
            if rs == "found":
                return {"exists": True, "owned": False, "visible": False, "phase": (robj or {}).get("status", {}).get("phase"),
                        "reason": "exists, but the learner cannot see it"}
        if state == "forbidden":
            ls, lobj, _lr = kube.read("learner", ["get", "projects"])
            if ls == "found" and ns not in {p["metadata"]["name"] for p in (lobj or {}).get("items", [])}:
                return {"exists": False, "authoritative": False, "reason": "not visible to the learner (not confirmed by the reader)"}
        return {"exists": None, "reason": (r.stderr.strip() or state)[:200]}
    ann = obj.get("metadata", {}).get("annotations", {})
    owned = ns.startswith(config.NS_PREFIX) and (ann.get("openshift.io/description") or "").startswith(config.MARKERS)
    return {"exists": True, "owned": owned, "phase": obj.get("status", {}).get("phase")}


def labfiles_dir(lab: Lab) -> Path:
    return config.LABFILES_DIR / lab.id


def write_files(lab: Lab) -> None:
    base = labfiles_dir(lab)
    for rel, text in lab.files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")


def apply(ns: str, docs: list[str], identity: str = "learner") -> list[dict]:
    if not docs:
        return []
    body = "\n---\n".join(docs)
    r = kube.oc(identity, ["apply", "-n", ns, "-f", "-"], stdin=body, timeout=90)  # type: ignore[arg-type]
    return [r.public()]


def _ensure_project(lab: Lab, ns: str, steps: list[dict], run_id: str | None = None) -> str | None:
    st = project_state(ns)
    if st.get("exists") is None:
        return f"The academy cannot tell whether project {ns} exists ({st.get('reason')}); nothing was created."
    if st.get("phase") == "Terminating":
        return f"Project {ns} is still being deleted. Wait a few seconds and retry."
    if st.get("exists") and not st.get("owned"):
        return f"Project {ns} exists but was not created by the academy; it will not be touched."
    path = f"/apis/project.openshift.io/v1/projects/{ns}"
    recorded = ledger.find_effect(run_id, "Project", ns) if run_id else None
    if st.get("exists") and recorded and recorded.get("uid"):
        _state, uid = ledger.uid_of("learner", path)
        if uid != recorded["uid"]:
            return (f"Project {ns} is not the one this lab run created (its UID changed: it was deleted and re-created). "
                    "The academy will not apply anything to it; clean up this run, then prepare again.")
    if st.get("exists") and run_id and not recorded:
        # The marker is a description any project admin can set: it is not proof that the academy created this
        # project. Only the operator may adopt it (Connections → lab environments), by typing its name.
        return (f"Project {ns} exists but is not in the cleanup ledger (it may come from an older version or another installation). "
                "Adopt it explicitly on the Connections page, or delete it yourself, before running this lab.")
    if not st.get("exists"):
        eid = ledger.intent(run_id, "Project", ns, path) if run_id else None
        desc = f"{MARKER} {ledger.run_marker(run_id)}" if run_id else MARKER
        r = kube.oc("learner", ["new-project", ns, f"--description={desc}", f"--display-name=Academy: {lab.title[:50]}", "--skip-config-write"], timeout=60)
        steps.append(r.public())
        if not r.ok:
            reason = kube.redact(r.stderr.strip())[-300:] or "the request did not complete"
            # Only an answer from the API server proves the project was not created; a timeout or a lost connection
            # leaves the intent open, and the next cleanup pass reconciles it (the project would carry this run's marker).
            if eid and r.status == "ok" and ledger.rejected(r.stderr):
                ledger.failed(eid, reason)
            return reason
        if eid:
            _state, uid = ledger.uid_of("learner", path)
            if uid:
                ledger.applied(eid, uid)  # if this read fails, the next cleanup pass reconciles the intent
        for _ in range(30):  # the project's default ServiceAccount and RBAC appear a moment later
            if kube.oc("learner", ["get", "serviceaccount", "default", "-n", ns]).ok:
                break
            time.sleep(0.5)
    return None


def prepare(lab: Lab, elevated: bool = False) -> dict:
    """Create (or resume) the lab projects, write lab files, apply setup (+ elevated, + break for incidents)."""
    steps: list[dict] = []
    if not kube.whoami("learner").get("connected"):
        return {"ok": False, "reason": "Connect the learner account first (My cluster → Connections, step 1).", "steps": steps}
    if lab.elevated_setup and not elevated:
        return {"ok": False, "needs_elevated": True, "reason": lab.elevated_why or "This lab needs an administrator to apply guardrails first.", "steps": steps}
    if lab.elevated_setup and not kube.whoami("admin").get("connected"):
        return {"ok": False, "needs_elevated": True, "reason": "Connect kubeadmin (My cluster → Connections, step 3) to apply this lab's elevated setup.", "steps": steps}
    if lab.elevated_setup and not environment.same_cluster("admin"):
        return {"ok": False, "reason": "The admin identity is connected to a different cluster than the learner; it is not used. Disconnect it.", "steps": steps}
    env = environment.current()
    if env["class"] != "training":
        return {"ok": False, "reason": "The academy does not create anything on this cluster yet: " + env.get("reason", ""), "steps": steps}
    pf = environment.preflight(lab)
    if not pf.get("runnable"):
        why = "; ".join(b["why"] for b in [*pf.get("blockers", []), *pf.get("unknown", [])]) or "requirements not met"
        return {"ok": False, "reason": f"This lab cannot run on this cluster as it is: {why}. The recorded replay is available instead.", "preflight": pf, "steps": steps}
    try:
        run_id = ledger.begin_run(lab.id, env["fingerprint"], env.get("api", ""))
    except ledger.LedgerUnavailable as e:
        return {"ok": False, "reason": str(e), "steps": steps}
    for ns in lab.namespaces:
        err = _ensure_project(lab, ns, steps, run_id)
        if err:
            return {"ok": False, "reason": err, "steps": steps}
    write_files(lab)
    steps += apply(lab.namespace, lab.setup)
    if lab.elevated_setup:
        steps += apply(lab.namespace, lab.elevated_setup, identity="admin")
    if lab.kind == "incident":
        steps += apply(lab.namespace, lab.break_)
    for ns in lab.namespaces:  # record claim → volume bindings now, not only at cleanup (a claim may be deleted first)
        ledger.note_volumes(run_id, ns)
    ok = all(s["code"] == 0 for s in steps)
    return {"ok": ok, "steps": steps, "reason": "" if ok else "a setup step failed"}


def verify(lab: Lab, only: list[str] | None = None) -> dict:
    # Without `only`, run the final checks; checks marked `final: false` belong to a single step.
    defs = [c for c in lab.checks if (c.id in only if only else c.model_dump().get("final", True) is not False)]
    results = [checks.run_check(lab.namespace, c.model_dump()) for c in defs]
    return {"verdict": checks.verdict(results), "results": results, "at": time.time()}


def cleanup(lab: Lab, wait_s: float = 60) -> dict:
    """Request cleanup of the lab's run and give it up to `wait_s` seconds. The background sweeper finishes the job
    and survives restarts; the result says exactly what is gone, what is still being deleted and what is blocked."""
    env = environment.current()
    if not env.get("connected"):
        return {"ok": False, "state": "unknown", "reason": "Not connected: the cluster cannot be checked."}
    try:
        run_id = ledger.active_run(lab.id, env["fingerprint"])
        if not run_id:
            # Nothing recorded for this lab. Projects that merely look like the academy's are reported, never adopted.
            states = {ns: project_state(ns) for ns in lab.namespaces}
            unknown = [ns for ns, st in states.items() if st.get("exists") is None]
            if unknown:
                return {"ok": False, "state": "unknown", "reason": f"The academy cannot tell whether {', '.join(unknown)} exists ({states[unknown[0]].get('reason', 'no answer')}). "
                        "Connect the reader identity to check, or look yourself; nothing was deleted."}
            unowned = [ns for ns, st in states.items() if st.get("exists")]
            unconfirmed = [ns for ns, st in states.items() if st.get("exists") is False and not st.get("authoritative")]
            if unowned:
                return {"ok": False, "state": "unowned", "unowned": unowned,
                        "reason": f"{', '.join(unowned)} exists but is not in the cleanup ledger, so the academy will not delete it. "
                                  "Adopt it explicitly on the Connections page (you type its name), or delete it yourself."}
            if unconfirmed:
                return {"ok": True, "state": "unverified", "reason": f"No project of this lab is visible to the learner ({', '.join(unconfirmed)}), and the ledger has no record of one. "
                        "Connect the reader identity to confirm that none exists."}
            return {"ok": True, "state": "clean", "reason": "Nothing to clean up: the API server confirms this lab has no project here.", "report": None}
        for ns in lab.namespaces:
            ledger.note_volumes(run_id, ns)
        ledger.request_cleanup(run_id)
        t0 = time.monotonic()
        rep = ledger.cleanup_pass(run_id)
        while rep["state"] == "cleaning" and time.monotonic() - t0 < wait_s:
            time.sleep(3)
            rep = ledger.cleanup_pass(run_id)
    except ledger.LedgerUnavailable as e:
        return {"ok": False, "state": "unknown", "reason": str(e)}
    return {"ok": rep["state"] != "blocked", "state": rep["state"], "report": rep}


LIVE_KINDS = ["deployments", "replicasets", "pods", "services", "endpointslices.discovery.k8s.io", "routes", "configmaps", "secrets",
              "persistentvolumeclaims", "networkpolicies", "serviceaccounts", "roles", "rolebindings", "jobs", "cronjobs",
              "buildconfigs", "builds", "imagestreams", "resourcequotas", "limitranges"]
_HIDDEN = {("ServiceAccount", "builder"), ("ServiceAccount", "deployer"), ("ServiceAccount", "default"),
           ("ConfigMap", "kube-root-ca.crt"), ("ConfigMap", "openshift-service-ca.crt")}


def live_state(ns: str) -> dict:
    """A compact view of what exists in the lab project right now (real data, read as the learner)."""
    obj, r = kube.oc_json("learner", ["get", ",".join(LIVE_KINDS), "-n", ns])
    if obj is None:
        return {"ok": False, "reason": kube.redact(r.stderr.strip())[-300:] or "unavailable", "items": [], "events": []}
    items = []
    for o in obj.get("items", []):
        md, st, sp = o.get("metadata", {}), o.get("status", {}) or {}, o.get("spec", {}) or {}
        kind = o.get("kind")
        if (kind, md.get("name")) in _HIDDEN or (kind == "RoleBinding" and md.get("name", "").startswith(("system:", "admin"))):
            continue
        if kind == "Secret" and (o.get("type") in ("kubernetes.io/dockercfg", "kubernetes.io/service-account-token") or md.get("name", "").startswith(("builder-", "default-", "deployer-"))):
            continue
        items.append({"kind": kind, "name": md.get("name"), "summary": summarize(kind, sp, st, o)})
    ev, _ = kube.oc_json("learner", ["get", "events", "-n", ns, "--sort-by=.lastTimestamp"])
    events = [
        {"type": e.get("type"), "reason": e.get("reason"), "object": f"{e.get('involvedObject', {}).get('kind')}/{e.get('involvedObject', {}).get('name')}",
         "message": (e.get("message") or "")[:300], "count": e.get("count") or 1, "last": e.get("lastTimestamp") or e.get("eventTime")}
        for e in (ev or {}).get("items", [])[-30:]
    ]
    return {"ok": True, "items": items, "events": events}


def summarize(kind: str, sp: dict, st: dict, o: dict) -> str:
    if kind == "Deployment":
        return f"ready {st.get('readyReplicas', 0)}/{sp.get('replicas', 0)} · updated {st.get('updatedReplicas', 0)} · image {', '.join(c.get('image', '').split('/')[-1] for c in sp.get('template', {}).get('spec', {}).get('containers', []))}"
    if kind == "ReplicaSet":
        return f"replicas {st.get('replicas', 0)} · ready {st.get('readyReplicas', 0)} · revision {o['metadata'].get('annotations', {}).get('deployment.kubernetes.io/revision', '?')}"
    if kind == "Pod":
        cs = st.get("containerStatuses") or []
        parts = []
        for c in cs:
            state = c.get("state", {})
            reason = (state.get("waiting") or {}).get("reason") or (state.get("terminated") or {}).get("reason") or ("Ready" if c.get("ready") else "Running, not ready")
            parts.append(f"{reason} · restarts {c.get('restartCount', 0)}")
        cond = next((c for c in st.get("conditions", []) if c.get("type") == "PodScheduled" and c.get("status") == "False"), None)
        if cond:
            parts.append(f"unschedulable: {cond.get('message', '')[:120]}")
        return f"{st.get('phase')} · " + ("; ".join(parts) or "no container status")
    if kind == "Service":
        ports = ", ".join(f"{p.get('port')}->{p.get('targetPort')}" for p in sp.get("ports", []))
        return f"{sp.get('type')} · selector {json.dumps(sp.get('selector') or {})} · ports {ports}"
    if kind == "EndpointSlice":
        eps = o.get("endpoints") or []
        ready = sum(len(e.get("addresses", [])) for e in eps if (e.get("conditions") or {}).get("ready"))
        return f"service {o['metadata'].get('labels', {}).get('kubernetes.io/service-name')} · ready {ready}/{sum(len(e.get('addresses', [])) for e in eps)} · ports {[p.get('port') for p in o.get('ports') or []]}"
    if kind == "Route":
        tls = (sp.get("tls") or {}).get("termination")
        return f"{'https' if tls else 'http'}://{sp.get('host')} → svc/{sp.get('to', {}).get('name')}{' · tls ' + tls if tls else ''}"
    if kind == "PersistentVolumeClaim":
        return f"{st.get('phase')} · class {sp.get('storageClassName')} · {sp.get('resources', {}).get('requests', {}).get('storage')}"
    if kind == "NetworkPolicy":
        return f"podSelector {json.dumps(sp.get('podSelector'))} · types {sp.get('policyTypes')}"
    if kind == "Job":
        return f"succeeded {st.get('succeeded', 0)} · failed {st.get('failed', 0)}"
    if kind == "CronJob":
        return f"schedule {sp.get('schedule')} · last {st.get('lastScheduleTime', '-')}"
    if kind == "Build":
        return f"{st.get('phase')}"
    if kind == "ResourceQuota":
        return " · ".join(f"{k} {st.get('used', {}).get(k, '0')}/{v}" for k, v in (st.get("hard") or sp.get("hard") or {}).items())
    if kind == "Secret":
        return f"type {o.get('type')} · keys {sorted((o.get('data') or {}).keys())}"
    if kind == "ConfigMap":
        return f"keys {sorted((o.get('data') or {}).keys())}"
    return ""


def adopt(ns: str, confirm: str, lab_id: str | None = None) -> str:
    """The operator explicitly adopts an academy-marked project that the ledger does not know (typed confirmation).
    Records its current UID in a new run so that cleanup can delete exactly that object. Returns the run id."""
    if confirm != ns:
        raise ValueError(f"type the project name ({ns}) to adopt it")
    if not ns.startswith(config.NS_PREFIX) or ns == "academy-system":
        raise ValueError("only academy-* lab projects can be adopted")
    st = project_state(ns)
    if not st.get("exists"):
        raise ValueError(f"{ns} is not visible to the learner (it may already be deleting, or belong to someone else)")
    if not st.get("owned"):
        raise ValueError(f"{ns} does not carry the academy marker; the academy never deletes it")
    env = environment.current()
    lab = lab_id or next((l.id for l in load().values() if ns in l.namespaces), f"adopted:{ns}")
    run_id = ledger.begin_run(lab, env["fingerprint"], env.get("api", ""))
    path = f"/apis/project.openshift.io/v1/projects/{ns}"
    if not ledger.find_effect(run_id, "Project", ns):
        _state, uid = ledger.uid_of("learner", path)
        if not uid:
            raise ValueError(f"could not read the UID of {ns}")
        ledger.applied(ledger.intent(run_id, "Project", ns, path), uid, "adopted by the operator: academy-marked project that was not in the ledger")
    return run_id


def run_tracked(lab: Lab, c: Cmd, run):
    """Run a lab command. If the lab declares that it creates or deletes a cluster-scoped object, go through the ledger:
    intent before, UID after a successful create; a declared delete is done by recorded UID (server-side precondition),
    never by name, and refused when the ledger cannot prove the object is the one this run created."""
    creates = [o for o in lab.cluster_objects if o.created_by == c.cmd]
    deletes = [o for o in lab.cluster_objects if o.deleted_by == c.cmd]
    if not creates and not deletes:
        note_lab_volumes(lab)  # a command may delete a claim: record its volume first
        out = run()
        note_lab_volumes(lab)  # and record bindings the command may have caused
        return out
    env = environment.current()
    run_id = ledger.begin_run(lab.id, env["fingerprint"], env.get("api", ""))
    base = {"cmd": c.cmd, "as": c.as_, "expect": c.expect, "run": None}

    def refuse(reason: str) -> dict:  # the shape of a recorder entry and of a Workbench refusal at once
        return {**base, "code": -1, "stdout": "", "stderr": f"REFUSED: {reason}", "ok": False, "refused": True, "reason": reason}

    if deletes:
        out = []
        for o in deletes:
            e = ledger.find_effect(run_id, o.kind, o.name)
            if not e or not e.get("uid") or e["phase"] in ledger.TERMINAL_OK:
                return refuse(f"{o.kind} {o.name} was not created by this lab run (no recorded UID), so the academy will not delete it.")
            state, uid = ledger.uid_of("admin", o.path)
            if state == "found" and uid != e["uid"]:
                return refuse(f"{o.kind} {o.name} has been replaced by a different object (UID changed); it is not deleted.")
            res = ledger._delete_with_uid("admin", o.path, e["uid"])
            if res in ("found", "not_found"):
                confirmed = ledger.uid_of("admin", o.path)[0] == "not_found"
                ledger._set(e["id"], "gone" if confirmed else "deleting",
                            "deleted by the lab's own step with a UID precondition; confirmed NotFound" if confirmed else "delete requested by the lab's own step (UID precondition); not confirmed yet")
            out.append(f'{o.kind.lower()}.{o.path.split("/")[2]} "{o.name}" deleted' if res == "found" else f"{o.kind} {o.name}: {res}")
        code = 0 if all("deleted" in x for x in out) else 1
        return {**base, "code": code, "stdout": "\n".join(out) + "\n", "stderr": "", "ok": c.expect == "any" or (c.expect == "ok") == (code == 0),
                "note": "Run by the academy as a UID-checked delete of the object this lab created."}
    pending = [(o, ledger.intent(run_id, o.kind, o.name, o.path, scope="cluster", identity="admin")) for o in creates]
    out = run()
    succeeded = isinstance(out, dict) and out.get("code") == 0 and not out.get("refused")
    for o, eid in pending:
        if not succeeded:
            if isinstance(out, dict) and (out.get("refused") or ledger.rejected(out.get("stderr", ""))):
                # refused before running, or AlreadyExists/Forbidden/Invalid: whatever has that name is not the academy's
                ledger.failed(eid, "the creating step was rejected; any object with this name is not the academy's")
            # otherwise (timeout, server error) the outcome is unknown: the intent stays open and is never adopted by name
            continue
        state, uid = ledger.uid_of("admin", o.path)
        if uid:
            ledger.applied(eid, uid)
    return out


def note_lab_volumes(lab: Lab) -> None:
    """Record claim → volume bindings of this lab's active run (before and after commands that may delete claims)."""
    env = environment.current()
    if env.get("class") == "practice" or not env.get("connected"):
        return
    try:
        run_id = ledger.active_run(lab.id, env["fingerprint"])
        if run_id:
            for ns in lab.namespaces:
                ledger.note_volumes(run_id, ns)
    except ledger.LedgerUnavailable:
        pass
