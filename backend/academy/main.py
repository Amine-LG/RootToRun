"""The academy's API (product name: frontend/product.json).

Progress lives in the browser, with optional learner account sync. It serves content, recordings of
real command outputs, and, when a cluster is available (ACADEMY_CLUSTER != off), lab lifecycle,
verification, a policy-checked Workbench and a read-only Explorer.

Request safety (cluster mode):
  * Host header must be 127.0.0.1/localhost unless ACADEMY_ALLOWED_HOSTS lists more (blocks DNS rebinding).
  * State-changing requests need the custom header X-Academy: 1, which browsers cannot send cross-origin
    without a CORS preflight that this server never approves (blocks CSRF from other web pages).
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import accounts, authoring, config, curriculum, environment, explorer, kube, labs, media, runner, tools, urls

from contextlib import asynccontextmanager

# Types the frontend build uses that some systems' tables lack (Windows has no .woff2 or .mjs entry): the fonts and
# module scripts must keep their real type, whatever the platform
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".mjs")


@asynccontextmanager
async def _lifespan(_app):
    from . import ledger

    authoring.start(_app)
    ledger.start_sweeper()  # resumes any cleanup that was requested before a restart
    yield


app = FastAPI(title=config.SITE_NAME, docs_url=None, redoc_url=None, openapi_url=None, lifespan=_lifespan)
app.include_router(authoring.router)
app.include_router(accounts.router)
ALLOWED_HOSTS = {"127.0.0.1", "localhost", *[h.strip() for h in os.environ.get("ACADEMY_ALLOWED_HOSTS", "").split(",") if h.strip()]}
ANY_HOST = "*" in ALLOWED_HOSTS
if ANY_HOST and config.cluster_enabled():
    raise RuntimeError("ACADEMY_ALLOWED_HOSTS=* is only allowed with ACADEMY_CLUSTER=off: a server that can reach a cluster must stay local")
HEALTH_PATHS = {"/healthz", "/readyz"}


@app.middleware("http")
async def guard(request: Request, call_next):
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
    # Probes come from the kubelet with the pod IP as Host; health endpoints reveal nothing.
    if not ANY_HOST and host not in ALLOWED_HOSTS and host != "testserver" and request.url.path not in HEALTH_PATHS:
        return JSONResponse({"detail": "forbidden host"}, status_code=403, headers={"Cache-Control": "no-store"})
    if request.method == "OPTIONS":
        return JSONResponse({"detail": "no CORS"}, status_code=403, headers={"Cache-Control": "no-store"})
    if request.method not in ("GET", "HEAD") and request.headers.get("x-academy") != "1":
        return JSONResponse({"detail": "missing X-Academy header"}, status_code=403, headers={"Cache-Control": "no-store"})
    if request.url.path == "/api/author" or request.url.path.startswith("/api/author/"):
        try:
            authoring.require_author(request)
        except HTTPException as error:
            return JSONResponse({"detail": error.detail}, status_code=error.status_code,
                                headers={**(error.headers or {}), "Cache-Control": "no-store"})
    resp = await call_next(request)
    if request.url.path.startswith(("/api/author/", "/api/auth/", "/api/me/")) or request.url.path == "/api/me":
        resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


def need_cluster():
    if not config.cluster_enabled():
        raise HTTPException(409, "This academy runs in practice mode (no cluster). Recorded outputs are available instead.")


def need_training(what: str = "This action changes the cluster"):
    """Mutations need a cluster that the operator approved for training labs (see environment.py)."""
    need_cluster()
    env = environment.current()
    if env["class"] != "training":
        if env.get("needs") == "learner":
            raise HTTPException(409, f"{what}: connect the learner account first, then approve this cluster "
                                     "(My cluster → Connections, steps 1 and 2).")
        if env.get("needs") == "tls":
            raise HTTPException(409, f"{what}: {env['reason']}.")
        raise HTTPException(409, f"{what}, and this cluster is not approved for training labs. Approve it in My cluster → "
                                 "Connections (step 2) if it is a disposable training cluster.")


# ---------------------------------------------------------------- health
@app.get("/healthz")
def healthz():
    """Liveness: the process answers."""
    return {"ok": True}


@app.get("/readyz")
def readyz():
    """Readiness: content loads without errors and the frontend is present."""
    lang = config.DEFAULT_LANG
    problems = labs.errors(lang) + curriculum.load(lang)["errors"]
    ready = not problems and (config.DIST_DIR / "index.html").exists()
    body = {"ready": ready, "mode": "cluster" if config.cluster_enabled() else "practice", "content_problems": len(problems),
            "frontend": (config.DIST_DIR / "index.html").exists()}
    return JSONResponse(body, status_code=200 if ready else 503)


# ---------------------------------------------------------------- meta, status, connections
@app.get("/api/meta")
def meta():
    return {"mode": "cluster" if config.cluster_enabled() else "practice", "langs": list(config.LANGS), "default_lang": config.DEFAULT_LANG,
            "helm": config.helm_path() is not None, "authoring": getattr(app.state, "authoring", False), **accounts.metadata(),
            "repo_url": config.REPO_URL if re.fullmatch(r"https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9._-]+", config.REPO_URL) else "", "repo_branch": config.REPO_BRANCH, "version": _version(), "commit": build_commit()}


def _version() -> str:
    """The application's version: one place, frontend/package.json (semantic versioning)."""
    try:
        return json.loads((config.ROOT / "frontend" / "package.json").read_text(encoding="utf-8")).get("version", "")
    except Exception:
        return ""


_COMMIT: list[str] = []


def build_commit() -> str:
    """The commit this build comes from: ACADEMY_BUILD_COMMIT (set by a build that has no .git directory, such as a
    container build), else `git rev-parse` in the source tree, else empty. Only a plain hexadecimal id is reported."""
    if not _COMMIT:
        value = os.environ.get("ACADEMY_BUILD_COMMIT", "").strip()
        if not value:
            import subprocess

            try:
                value = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=config.ROOT, capture_output=True,
                                       text=True, encoding="utf-8", timeout=5).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                value = ""
        _COMMIT.append(value[:12] if re.fullmatch(r"[0-9a-f]{7,40}", value) else "")
    return _COMMIT[0]


_SRC: dict = {}

# Where each kind of item is written, relative to a language's content directory, and the pattern of the line that
# starts one item in such a file (a file may hold several: lessons, cases, runbooks).
_SOURCE_DIRS = {
    "lessons": (("lessons",), r"^- id:\s*['\"]?([\w.\-]+)"),
    "labs": (("labs", "incidents", "challenges"), r"^id:\s*['\"]?([\w.\-]+)"),  # one lab, incident or challenge per file
    "cases": (("cases",), r"^- id:\s*['\"]?([\w.\-]+)"),
    "runbooks": (("runbooks",), r"^- id:\s*['\"]?([\w.\-]+)"),
    "diagnostics": (("diagnostics",), r"^track:\s*['\"]?([\w.\-]+)"),  # one diagnostic per file, named by its track
}
# items whose whole kind lives in one file
_SOURCE_FILES = {"concepts": "concepts.yaml", "tracks": "tracks.yaml", "modules": "modules.yaml"}


def _rel(f) -> str | None:
    """A content file's path relative to the repository (resolved: no ../ escapes); None for content kept outside it
    (ACADEMY_CONTENT_DIR), which has no file in the repository to edit."""
    try:
        return f.resolve().relative_to(config.ROOT.resolve()).as_posix()
    except ValueError:
        return None


def content_sources(lang: str | None = None) -> dict:
    """Where every item is written: {kind: {id: file}} for lessons, labs (also incidents and challenges), cases,
    runbooks and diagnostics, and {kind: file} for concepts, tracks and modules; files relative to the repository, as
    GitHub's editor needs them. Read from the files themselves (the loaders do not keep them). English is the source
    language: a translated item is written in content/<lang>/, anything else in English."""
    langs = ["en"] if (lang or "en") == "en" or lang not in config.LANGS else [lang, "en"]
    roots = [config.content_dir(x) for x in langs]
    files = sorted(f for r in roots for dirs, _ in _SOURCE_DIRS.values() for d in dirs for f in (r / d).glob("*.yaml"))
    sig = tuple((str(f), f.stat().st_mtime) for f in files)
    key = ",".join(langs)
    hit = _SRC.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    found: dict = {}
    for kind, (dirs, pattern) in _SOURCE_DIRS.items():
        out: dict[str, str | None] = {}
        for r in roots:  # the translation first: setdefault keeps the first file that defines an id
            for d in dirs:
                for f in sorted((r / d).glob("*.yaml")):
                    for m in re.finditer(pattern, f.read_text(encoding="utf-8"), re.M):
                        out.setdefault(m.group(1), _rel(f))
        found[kind] = out
    for kind, name in _SOURCE_FILES.items():
        f = next((r / name for r in roots if (r / name).exists()), None)
        found[kind] = _rel(f) if f else None
    _SRC[key] = (sig, found)
    return found


@app.get("/api/status")
def status(lang: str | None = None):
    cur = curriculum.load(lang)
    lab_ids = set(labs.load(lang))
    return {**kube.status(), "content_errors": labs.errors(lang) + cur["errors"] + curriculum.integrity(lab_ids, lang)}


class ConnectIn(BaseModel):
    identity: str
    confirm: str = ""


ADMIN_PHRASE = "use kubeadmin"


@app.post("/api/connect")
def connect(body: ConnectIn):
    need_cluster()
    environment.invalidate()  # capabilities belong to the identity that answered them
    if body.identity == "learner":
        return kube.login_user("learner")
    if body.identity == "admin":
        need_training("Connecting a cluster-admin identity")
        if body.confirm != ADMIN_PHRASE:
            raise HTTPException(400, f"Type '{ADMIN_PHRASE}' to confirm the cluster-admin connection.")
        if not environment.admin_target_is_approved_cluster():
            raise HTTPException(409, "kubeadmin would log in to another cluster than the one you approved (a different API "
                                     "address or certificate authority); nothing was sent.")
        r = kube.login_user("admin")
        if r.get("ok") and not environment.same_cluster("admin"):  # checked again after the login, whatever happened
            kube.disconnect("admin")
            raise HTTPException(409, "kubeadmin reached another cluster than the one you approved; it was logged out again.")
        return r
    raise HTTPException(400, "unknown identity")


@app.post("/api/disconnect")
def disconnect(body: ConnectIn):
    need_cluster()
    environment.invalidate()  # capabilities belong to the identity that answered them
    if body.identity not in kube.IDENTITIES:
        raise HTTPException(400, "unknown identity")
    kube.disconnect(body.identity)  # type: ignore[arg-type]
    return kube.status()


@app.get("/api/reader/plan")
def reader_plan():
    return {"plan": kube.reader_plan(), "confirm": "create reader"}


@app.post("/api/reader/setup")
def reader_setup(body: ConnectIn):
    need_cluster()
    need_training("Creating the reader identity creates cluster-scoped objects")
    if not environment.same_cluster("admin"):
        raise HTTPException(409, "The admin identity is connected to a different cluster than the learner; it is not used for the reader setup.")
    if body.confirm != "create reader":
        raise HTTPException(400, "Type 'create reader' to confirm.")
    return kube.setup_reader()


# ---------------------------------------------------------------- environment, approval, cleanup ledger
@app.get("/api/environment")
def get_environment(probe: bool = False):
    env = environment.current()
    out = {"env": env, "identities": environment.identity_clusters()}
    if probe and env.get("connected"):
        out["capabilities"] = environment.probe(force=True)
    return out


class ApproveIn(BaseModel):
    host: str
    note: str = ""


@app.post("/api/environment/approve")
def approve_environment(body: ApproveIn):
    need_cluster()
    try:
        return {"env": environment.approve(body.host, body.note)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@app.post("/api/environment/revoke")
def revoke_environment():
    need_cluster()
    return {"env": environment.revoke()}


@app.get("/api/labs/{lid}/preflight")
def lab_preflight(lid: str, lang: str | None = None):
    return environment.preflight(_lab(lid, lang))


@app.get("/api/cleanup")
def cleanup_report():
    """Every lab run the ledger knows that is not verified clean, with what remains and why."""
    if not config.cluster_enabled():
        return {"runs": []}
    from . import ledger

    try:
        return {"runs": [ledger.report(r["id"]) for r in ledger.runs()], "leftovers": ledger.leftovers()}
    except ledger.LedgerUnavailable as e:
        raise HTTPException(503, str(e)) from None


class AdoptIn(BaseModel):
    namespace: str
    confirm: str


@app.post("/api/cleanup/adopt")
def cleanup_adopt(body: AdoptIn):
    """Operator decision: put an academy-marked project that the ledger does not know under the ledger, then clean it."""
    need_training("Adopting a project for cleanup deletes it")
    from . import ledger

    try:
        run_id = labs.adopt(body.namespace, body.confirm)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    ledger.request_cleanup(run_id)
    return ledger.cleanup_pass(run_id)


@app.post("/api/cleanup/{run_id}")
def cleanup_retry(run_id: str):
    need_cluster()
    from . import ledger

    try:
        ledger.request_cleanup(run_id)
        return ledger.cleanup_pass(run_id)
    except KeyError:
        raise HTTPException(404, "unknown run") from None
    except ledger.LedgerUnavailable as e:
        raise HTTPException(503, str(e)) from None


# ---------------------------------------------------------------- curriculum
def _lab_summary(l: labs.Lab) -> dict:
    rec = labs.recording(l.id)
    return {"id": l.id, "kind": l.kind, "title": l.title, "summary": l.summary, "module": l.module, "mode": l.mode,
            "requires": environment.lab_requirements(l), "steps": [{"id": s.id, "title": s.title} for s in l.steps],
            "minutes": l.minutes, "level": l.level, "concepts": l.concepts, "namespace": l.namespace,
            "elevated": bool(l.elevated_setup), "recorded": bool(rec and rec.get("ok") and rec.get("lab_hash") == labs.lab_hash(l)), "recorded_at": (rec or {}).get("recorded_at"),
            "tools": tools.used(tools.lab_commands(l))}


@app.get("/api/curriculum")
def get_curriculum(lang: str | None = None):
    d = curriculum.load(lang)
    u = urls.table()  # public addresses (the same in every language); `path` below is what links use
    return {
        "tracks": [{**t.model_dump(), "path": u["tracks"].get(t.id, f"/learn/{t.id}")} for t in d["tracks"].values()],
        "modules": [m.model_dump() for m in d["modules"].values()],
        "lessons": {k: {"id": l.id, "title": l.title, "module": l.module, "mode": l.mode, "minutes": l.minutes, "level": l.level,
                        "concepts": l.concepts, "prerequisites": l.prerequisites, "labs": l.labs, "objective": l.objective,
                        "checks": [p.id for p in l.predict if p.role == "check"],
                        "check_after": {p.id: p.after for p in l.predict if p.role == "check" and p.after},
                        "path": u["lessons"].get(k, f"/lesson/{k}"),
                        # what practising it outside the website needs (backend/academy/tools.py; the setup guide)
                        "tools": tools.lesson_tools(l, lang), "record_on": l.record_on}
                    for k, l in d["lessons"].items()},
        "tools": [t.model_dump() for t in tools.load(lang)],
        "concepts": {k: c.model_dump() for k, c in d["concepts"].items()},
        "labs": {k: {**_lab_summary(l), "path": u["labs"].get(k, f"/lab/{k}")} for k, l in labs.load(lang).items()},
        "cases": [{"id": c.id, "title": c.title, "concepts": c.concepts} for c in d["cases"].values()],
        "runbooks": [{"id": r.id, "title": r.title, "when": r.when} for r in d["runbooks"].values()],
        "routes": [r.model_dump() for r in d["routes"].values()],
        # the files that define every concept, path and module (for "Edit on GitHub"; null: not in the repository)
        "sources": {k: v for k, v in content_sources(lang).items() if not isinstance(v, dict)},
        # keyed by every track a diagnostic covers; `track` names the diagnostic itself (its URL and saved answers)
        "diagnostics": {t: {"track": k, "title": g.title, "minutes": g.minutes, "count": len(g.items), "path": u["diagnostics"].get(k, f"/diagnostic/{k}")}
                        for k, g in d["diagnostics"].items() for t in (k, *g.covers)},
    }


@app.get("/api/diagnostics/{track}")
def get_diagnostic(track: str, lang: str | None = None):
    """A track's diagnostic. The answers are included: it is a self-assessment that only suggests where to start,
    and the static site could not hide them anyway."""
    g = curriculum.load(lang)["diagnostics"].get(track)
    if not g:
        raise HTTPException(404, "diagnostic not found")
    return {**g.model_dump(), "source": content_sources(lang)["diagnostics"].get(g.track)}


@app.get("/api/lessons/{lid}")
def get_lesson(lid: str, lang: str | None = None):
    d = curriculum.load(lang)
    l = d["lessons"].get(lid)
    if not l:
        raise HTTPException(404, "lesson not found")
    out = lesson_payload(l)
    if "translation" in d:  # a language other than English: say whether this lesson is translated
        out["lang_status"] = d["translation"]["lessons"].get(lid, "missing")
    return out


def lesson_payload(l: curriculum.Lesson):
    rec = labs.recording(f"lesson.{l.id}") if l.commands else None
    src = content_sources("en")["lessons"].get(l.id)
    out = {**l.model_dump(), "recording": _public_recording(rec, include_fix=True) if rec else None,
           "host": (rec or {}).get("host"), "source": src}
    for st in out.get("flow") or []:  # a screenshot's address and size, so the page reserves its space
        if st.get("image"):
            st["image"].update(media.info(l.id, st["image"]["src"]))
    return out


@app.get("/api/cases/{cid}")
def get_case(cid: str, lang: str | None = None):
    c = curriculum.load(lang)["cases"].get(cid)
    if not c:
        raise HTTPException(404)
    return {**c.model_dump(), "source": content_sources(lang)["cases"].get(c.id)}


@app.get("/api/runbooks/{rid}")
def get_runbook(rid: str, lang: str | None = None):
    r = curriculum.load(lang)["runbooks"].get(rid)
    if not r:
        raise HTTPException(404)
    return {**r.model_dump(), "source": content_sources(lang)["runbooks"].get(r.id)}


# ---------------------------------------------------------------- labs and incidents
def _lab(lid: str, lang: str | None = None) -> labs.Lab:
    l = labs.load(lang).get(lid)
    if not l:
        raise HTTPException(404, "lab not found")
    return l


def _public_recording(rec: dict | None, include_fix: bool) -> dict | None:
    if not rec:
        return None
    entries = [e for e in rec.get("entries", []) if include_fix or e.get("step") != "fix"]
    out = {"recorded_at": rec.get("recorded_at"), "cluster": rec.get("cluster"), "ok": rec.get("ok"), "entries": entries,
           "verify_before": rec.get("verify_before"),
           # Preserve measured outcomes, but withhold descriptions of the attempted repairs alongside the solution.
           # A title such as "image fixed, Service port still wrong" also gives away the diagnosis.
           "trials": [{**{k: t.get(k) for k in ("id", "kind", "expect", "got", "ok")},
                       "title": t.get("title", "") if include_fix else ""} for t in rec.get("trials", [])],
           # an administration lesson's experiment: whether its rollback restored the cluster, with the checks
           "experiment": rec.get("experiment")}
    if include_fix:  # for incidents, the repaired state is part of the answer
        out["verify_after"] = rec.get("verify_after")
    return out


@app.get("/api/labs/{lid}")
def get_lab(lid: str, lang: str | None = None):
    l = _lab(lid, lang)
    data = l.model_dump(by_alias=True)
    data["hint_count"] = len(l.hints)
    data["hints"] = []
    if l.kind in labs.ANSWER_HIDDEN:  # never send the answer before it is asked for
        for k in ("root_cause", "alternatives", "sre"):
            data[k] = ""
        data["break"] = []
        data["fix"] = []
    data["elevated"] = bool(l.elevated_setup)
    data["files"] = l.files  # inputs written to lab/ before the start (a challenge's chart, manifests); answers live in fix/trials
    data["trials"] = []  # grader self-tests contain solutions; their outcomes are in the recording
    data["source"] = content_sources(lang)["labs"].get(l.id)  # its YAML file in the repository (for "Edit on GitHub")
    return {"lab": data, "recording": _public_recording(labs.recording(lid), include_fix=l.kind not in labs.ANSWER_HIDDEN)}


@app.get("/api/labs/{lid}/hints")
def lab_hints(lid: str, n: int = 1, lang: str | None = None):
    l = _lab(lid, lang)
    return {"hints": l.hints[: max(0, min(n, len(l.hints)))], "hint_count": len(l.hints)}


@app.post("/api/labs/{lid}/reveal")
def lab_reveal(lid: str, lang: str | None = None):
    l = _lab(lid, lang)
    rec = labs.recording(lid)
    titles = {t.id: t.title for t in l.trials}
    return {"root_cause": l.root_cause, "alternatives": l.alternatives, "sre": l.sre,
            "fix": [c.model_dump(by_alias=True) for c in l.fix],
            "fix_recording": [e for e in (rec or {}).get("entries", []) if e.get("step") == "fix"],
            "verify_after": (rec or {}).get("verify_after"),
            # Titles are editable teaching prose; the recording remains the source of grading evidence.
            "trials": [{**t, "title": titles.get(t.get("id"), "")} for t in (rec or {}).get("trials", [])]}


class PrepareIn(BaseModel):
    confirm: bool = False
    elevated: bool = False


@app.post("/api/labs/{lid}/prepare")
def lab_prepare(lid: str, body: PrepareIn, lang: str | None = None):
    need_training("Preparing a lab creates a project and resources")
    l = _lab(lid, lang)
    if not body.confirm:
        raise HTTPException(400, "Preparing creates resources in the lab project; confirm first.")
    return labs.prepare(l, elevated=body.elevated)


@app.post("/api/labs/{lid}/verify")
def lab_verify(lid: str, lang: str | None = None):
    need_cluster()
    l = _lab(lid, lang)
    labs.note_lab_volumes(l)
    return labs.verify(l)


class StepCheck(BaseModel):
    checks: list[str]


@app.post("/api/labs/{lid}/check")
def lab_step_check(lid: str, body: StepCheck, lang: str | None = None):
    need_cluster()
    return labs.verify(_lab(lid, lang), only=body.checks)


@app.post("/api/labs/{lid}/cleanup")
def lab_cleanup(lid: str, body: PrepareIn, lang: str | None = None):
    need_cluster()
    l = _lab(lid, lang)
    if not body.confirm:
        raise HTTPException(400, f"Cleanup deletes {', '.join(l.namespaces)}; confirm first.")
    return labs.cleanup(l)


@app.get("/api/labs/{lid}/state")
def lab_state(lid: str, lang: str | None = None):
    if not config.cluster_enabled():
        return {"project": {"exists": None, "reason": "practice mode"}, "items": [], "events": []}
    l = _lab(lid, lang)
    st = labs.project_state(l.namespace)
    if not st.get("exists"):
        return {"project": st, "items": [], "events": []}
    return {"project": st, **labs.live_state(l.namespace)}


@app.get("/api/labs/{lid}/predict/{step_id}")
def lab_predict_answer(lid: str, step_id: str, lang: str | None = None):
    l = _lab(lid, lang)
    s = next((s for s in l.steps if s.id == step_id), None)
    if not s or not s.predict:
        raise HTTPException(404)
    return {"answer": s.predict.answer, "explain": s.predict.explain}


class ExecIn(BaseModel):
    where: str
    index: int
    confirm: bool = False


@app.post("/api/labs/{lid}/exec")
def lab_exec(lid: str, body: ExecIn, lang: str | None = None):
    """Run one of the lab's own (recorded) commands on the cluster, with its placeholders resolved live."""
    need_cluster()
    from . import policy, recorder

    l = _lab(lid, lang)
    cmds = [c for w, c in l.all_commands() if w == body.where]
    if not 0 <= body.index < len(cmds):
        raise HTTPException(404, "command not found")
    c = cmds[body.index]
    if c.skip:
        return {"refused": True, "reason": c.skip}
    if c.as_ == "admin" or (c.as_ == "learner" and _writes(c, l)):
        need_training("This step changes the cluster")
    if c.as_ == "admin":
        if not kube.whoami("admin").get("connected"):
            return {"refused": True, "reason": "This step runs as cluster-admin. Connect kubeadmin first (My cluster → Connections, step 3)."}
        if not environment.same_cluster("admin"):
            return {"refused": True, "reason": "The admin identity is connected to a different cluster than the learner; disconnect it."}
        if not body.confirm:
            return {"needs_confirm": True, "display": c.cmd, "namespace": l.namespace, "admin": True}
    else:
        try:
            write = policy.plan(c.run or c.cmd, c.as_, l.namespace, str(labs.labfiles_dir(l))).write
        except policy.Refused:
            write = False  # placeholders are resolved below; the runner re-checks the resolved command
        if write and not body.confirm:
            return {"needs_confirm": True, "display": c.cmd, "namespace": l.namespace}
    if l.files:
        labs.write_files(l)
    labs.note_lab_volumes(l)  # a step may delete a claim: record its volume first
    out = _run_tracked(l, c, lambda: recorder.run_cmd(l, c))
    labs.note_lab_volumes(l)
    return out


@app.get("/api/cards")
def review_cards(lang: str | None = None):
    """Every review card: lesson review questions and lab/incident questions."""
    out = []
    for l in curriculum.load(lang)["lessons"].values():
        out += [{"id": f"lesson:{l.id}:{i}", "q": c.q, "a": c.a, "source": "lesson", "ref": l.id, "title": l.title} for i, c in enumerate(l.review)]
    for lab in labs.load(lang).values():
        out += [{"id": f"lab:{lab.id}:{i}", "q": c.q, "a": c.a, "source": lab.kind, "ref": lab.id, "title": lab.title} for i, c in enumerate(lab.questions)]
    return out


# ---------------------------------------------------------------- workbench
class RunIn(BaseModel):
    command: str
    identity: str = "learner"
    namespace: str | None = None
    confirm: bool = False
    stdin: str | None = None
    lab_id: str | None = None


@app.post("/api/workbench/run")
def workbench_run(body: RunIn, lang: str | None = None):
    need_cluster()
    from . import policy

    lab = labs.load(lang).get(body.lab_id) if body.lab_id else None
    labdir = str(labs.labfiles_dir(lab)) if lab and lab.files else None
    namespace = body.namespace or (lab.namespace if lab else None)  # the same default the runner applies
    try:
        p = policy.plan(body.command, body.identity, namespace, labdir)
    except policy.Refused as e:
        return {"refused": True, "reason": str(e)}
    if body.identity == "reader" and not environment.same_cluster("reader"):
        return {"refused": True, "reason": "The reader identity points at another cluster than the learner; reconnect it on the Connections page."}
    if p.write:
        need_training("This command changes the cluster")
        from . import ledger

        if not ledger.owns_project(p.namespace or ""):
            return {"refused": True, "reason": f"Project {p.namespace} was not prepared by the academy on this machine (or was replaced since); "
                                               "start the lab first. Changes and remote commands run only in lab projects the academy created."}
    if p.write and not body.confirm:
        return {"needs_confirm": True, "display": p.display, "namespace": p.namespace}
    if lab and lab.files:
        labs.write_files(lab)
    if lab and p.write:
        labs.note_lab_volumes(lab)
    out = runner.execute(body.command, body.identity, namespace, lab, body.stdin, timeout=60)
    if lab and p.write:
        labs.note_lab_volumes(lab)
    return out


# ---------------------------------------------------------------- command reference (every command, recorded)
@app.get("/api/commands")
def command_reference(lang: str | None = None):
    out = []
    for l in labs.load(lang).values():
        rec = labs.recording(l.id) or {}
        by_cmd: dict[str, dict] = {}
        for e in rec.get("entries", []):
            if e.get("skipped") or (l.kind in labs.ANSWER_HIDDEN and e.get("step") in ("fix",) or str(e.get("step", "")).startswith("trial:")):
                continue
            by_cmd.setdefault(e["cmd"], e)
        for where, c in l.all_commands():
            if l.kind in labs.ANSWER_HIDDEN and where == "fix":
                continue
            e = by_cmd.get(c.cmd)
            out.append({"cmd": c.cmd, "meaning": c.meaning, "lab": l.id, "lab_title": l.title, "kind": l.kind, "as": c.as_,
                        "run": e.get("run") if e else None, "stdout": (e or {}).get("stdout", "")[:4000], "stderr": (e or {}).get("stderr", "")[:1500],
                        "code": (e or {}).get("code"), "tested": bool(e and e.get("ok")), "skip": c.skip})
    for l in curriculum.load(lang)["lessons"].values():  # commands for the learner's own machine
        if not l.commands:
            continue
        rec = labs.recording(f"lesson.{l.id}") or {}
        by_cmd = {e["cmd"]: e for e in rec.get("entries", [])}
        for c in l.commands:
            e = by_cmd.get(c.cmd) or {}
            out.append({"cmd": c.cmd, "meaning": c.meaning, "lab": l.id, "lab_title": l.title, "kind": "lesson", "as": "host", "run": None,
                        "stdout": e.get("stdout", "")[:4000], "stderr": e.get("stderr", "")[:1500], "code": e.get("code"),
                        "tested": bool(e.get("ok")), "skip": ""})
    return out


# ---------------------------------------------------------------- explorer
def _explore(fn, *a):
    if not config.cluster_enabled():
        return {"ok": False, "error": "Explorer needs a cluster; this academy runs in practice mode."}
    try:
        return fn(*a)
    except explorer.Bad as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/explore/overview")
def explore_overview():
    return _explore(explorer.overview)


@app.get("/api/explore/kinds")
def explore_kinds():
    return [{"kind": k, "namespaced": v[1]} for k, v in explorer.KINDS.items()]


@app.get("/api/explore/list")
def explore_list(kind: str, ns: str | None = None):
    return _explore(explorer.list_kind, kind, ns)


@app.get("/api/explore/get")
def explore_get(kind: str, name: str, ns: str | None = None):
    return _explore(explorer.get_one, kind, ns, name)


@app.get("/media/{lesson}/{name}")
def lesson_media(lesson: str, name: str):
    """A lesson's screenshot (academy/media.py); the static export copies the same files to /media/."""
    p = media.path(lesson, name)
    if p is None or not p.is_file():
        raise HTTPException(404, "image not found")
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- static frontend (History API routing)
@app.get("/{path:path}")
def spa(path: str):
    if path == "api/author" or path.startswith("api/author/"):
        raise HTTPException(404, "author route not found")
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "API route not found")  # never the app shell with 200 for a mistyped API path
    f = (config.DIST_DIR / path).resolve()
    if path and config.DIST_DIR.resolve() in f.parents and f.is_dir() and (f / "index.html").is_file():
        f = f / "index.html"  # pre-rendered page of the static export (same app, better title and preview)
    if path and config.DIST_DIR.resolve() in f.parents and f.is_file():
        headers = {"Cache-Control": "public, max-age=31536000, immutable"} if "/assets/" in f"/{path}" else {}
        return FileResponse(f, headers=headers)
    index = config.DIST_DIR / "index.html"
    if not index.exists():
        return JSONResponse({"detail": "frontend not built: run ./run.sh"}, status_code=503)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


_ = time  # keep import for future timing


# ---------------------------------------------------------------- ledger hooks for lab steps
def _writes(c, lab) -> bool:
    from . import policy

    try:
        return policy.plan(c.run or c.cmd, c.as_, lab.namespace, str(labs.labfiles_dir(lab))).write
    except policy.Refused:
        return True  # unresolved placeholders: assume it writes (the runner re-checks the resolved command)


def _run_tracked(lab, c, run):
    return labs.run_tracked(lab, c, run)
