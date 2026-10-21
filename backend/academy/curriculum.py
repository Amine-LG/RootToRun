"""Curriculum: modules, lessons and concepts from content/*.yaml, validated at load (hot reload)."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml

_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)  # libyaml when available: the content is large
import hashlib

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from . import config

Mode = Literal["REAL_LAB", "LOCAL_SIMULATION", "GUIDED_INVESTIGATION", "ENTERPRISE_ARCHITECTURE", "EXTERNAL_LAB_REQUIRED"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TitledText(Strict):
    title: str
    body: str


class Section(Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")  # stable: checks and progress refer to it
    title: str
    body: str
    depth: bool = False  # "go deeper" material (common mistakes, limits…), offered from every activity, not in the main flow


class Predict(Strict):
    prompt: str
    choices: list[str]
    answer: int
    explain: str
    feedback: list[str] = []  # optional, one per choice: why that answer is right or what misunderstanding it reveals
    # Where the question sits in the lesson. A "check" comes right after the section that teaches what it tests
    # (`after`); a "predict" item is an ungraded guess placed before the section that answers it (`answered_by`).
    role: Literal["check", "predict"] = "check"
    after: str | None = None  # a section id, or "start"; None means after the last core section
    answered_by: str | None = None
    # Set only by the translation overlay: a translated question keeps the id of the English question it translates,
    # so saved answers carry across languages. Authors never write it.
    translates: str | None = Field(default=None, exclude=True)

    @computed_field  # stable identity for progress: editing the question makes it a new question, on purpose
    @property
    def id(self) -> str:
        return self.translates or "q" + hashlib.sha1(self.prompt.strip().encode()).hexdigest()[:10]

    @model_validator(mode="after")
    def _feedback_matches_choices(self):
        if self.feedback and len(self.feedback) != len(self.choices):
            raise ValueError("feedback needs exactly one entry per choice")
        if self.choices and self.answer is not None and not 0 <= self.answer < len(self.choices):
            raise ValueError("answer is not a valid choice index")
        return self


class Explain(Strict):
    prompt: str
    audience: Literal["junior developer", "experienced administrator", "nontechnical manager", "peer engineer"]
    rubric: list[str]
    model: str


class Card(Strict):
    q: str
    a: str


class Ref(Strict):
    title: str
    url: str


class LessonCmd(Strict):
    """A command of the lesson, recorded by the recorder: on this machine, or on the cluster as one identity."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    cmd: str
    meaning: str = ""
    expect: Literal["ok", "fail", "any"] = "ok"
    timeout: int = 180
    # the directory, inside the practice directory, where the command runs: each recorded command starts a fresh
    # shell, so a lesson that says "you are in notes" records `cat welcome.txt` with cwd notes (shown in the prompt)
    # instead of a misleading `cd notes; cat welcome.txt`
    cwd: str = Field("", pattern=r"^([A-Za-z0-9_-][A-Za-z0-9._/-]*)?$")
    # who runs it, in a lesson recorded with `record_on: cluster-admin`: "admin" (the cluster administrator, kubeadmin
    # on OpenShift Local), "developer" (an ordinary user; the default), or one of the lesson's `test_users`, who must
    # log in first with a command of the lesson. Administrator access exists only in the trusted local recorder.
    as_: str = Field("", alias="as", pattern=r"^([a-z][a-z0-9-]*)?$")


class Experiment(Strict):
    """A cluster change made on purpose by an administration lesson, with its rollback. The recorder refuses to run
    it unless it is started for administrator recordings, on the approved training cluster."""
    id: str = Field(pattern=r"^X-[A-Z0-9]+-\d\d$")
    objective: str
    changes: list[str] = Field(min_length=1)  # what may change, cluster-scoped objects first
    # read-only commands, run as the recovery administrator before the lesson and after the rollback: their outputs
    # must be identical, which is the evidence that the cluster was returned to its original state
    snapshot: list[str] = Field(min_length=1)
    # checks run as the recovery administrator before anything else; one that fails stops the recording before any
    # change (for example: the test users, project and Secret the lesson creates must not exist yet, so the rollback
    # can never delete something that was there before)
    preflight: list[LessonCmd] = []
    rollback: list[str] = Field(min_length=1)  # run as the recovery administrator, always, even after a failure
    settle: list[str] = []  # after the rollback, before the checks (`oc wait …` for an operator to finish)
    verify: list[LessonCmd] = []  # health checks after the rollback, run as the recovery administrator
    # after the rollback, a real password login through the cluster's own identity provider, as these users (only
    # "developer", whose password OpenShift Local keeps in ~/.crc): proves the existing provider still works
    login_checks: list[Literal["developer"]] = []


# A lesson "flow" is the teaching sequence written as small, typed steps, the way a teacher works: explain one idea,
# show it with real output, let the learner try or predict, react to what they chose, and move on. A lesson has either
# core `sections` (the older long-form format) or a `flow`; depth sections (common mistakes, limits) work with both.
_STEP_ID = r"^[a-z0-9][a-z0-9-]*$"


class Choice(Strict):
    text: str
    why: str  # shown when this choice is picked: why it is right, or the misunderstanding behind it


class Teach(Strict):
    kind: Literal["teach"]
    id: str = Field(pattern=_STEP_ID)
    title: str = ""  # a titled step starts a new part of the lesson in the outline
    body: str


class Part(Strict):
    text: str  # an option or argument exactly as it appears in the command, e.g. "--sub-path=tls.crt"
    means: str  # what it does here, and why this command uses it


class Understand(Strict):
    """"Understand this command": an optional, collapsed explanation of a demonstrated or practised command, for the
    commands with options a learner cannot be expected to know. Every statement is checked against the documentation
    listed in `refs` (official docs, man pages, `--help`); nothing is inferred from an option's name."""
    purpose: str  # what the command does, in one or two sentences
    parts: list[Part] = []  # the options and arguments worth explaining (not the trivial ones)
    output: str = ""  # what to expect to see
    needs: str = ""  # what must be true before it works (tools, permissions, earlier steps)
    mistakes: list[str] = []  # mistakes people really make with it
    caution: str = ""  # security-sensitive behaviour (secrets on the command line, privileges, deleting data…)
    concepts: list[str] = []  # concept ids (concepts.yaml) that the explanation builds on
    refs: list[Ref] = Field(min_length=1)  # where each statement was verified


def _check_understand(step_id: str, u: "Understand | None", *cmds: str | None) -> None:
    """An explanation belongs to a command the step shows, and every part it explains is written in that command."""
    if u is None:
        return
    shown = [c for c in cmds if c]
    if not shown:
        raise ValueError(f"step {step_id}: understand explains a command, but the step shows none")
    for p in u.parts:
        if not any(p.text in c for c in shown):
            raise ValueError(f"step {step_id}: understand part {p.text!r} does not appear in the command")


class Screenshot(Strict):
    """A real screenshot, never a mock-up: the PNG in content/media/<lesson id>/ (lib: academy/media.py), what it shows
    for someone who cannot see it, and where and as whom it was captured (shown under it)."""
    src: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*\.png$")
    alt: str = Field(min_length=20)  # what the image shows, in words: what to notice, not "screenshot of the console"
    captured: str = Field(min_length=10)  # e.g. "OpenShift Local 4.21.8 web console, as kubeadmin, 2026-10-20"

    @field_validator("alt", "captured", mode="before")
    @classmethod
    def _words(cls, v):
        return v.strip() if isinstance(v, str) else v  # spaces alone are not a description

class Show(Strict):
    """A demonstration: a recorded command and its real output (`run`), a file or manifest (`code`), or a real
    screenshot (`image`)."""
    kind: Literal["show"]
    id: str = Field(pattern=_STEP_ID)
    title: str = ""
    body: str = ""  # before the output: why we run this, or what to look for
    run: str | None = None  # the exact `cmd` of one of the lesson's recorded commands
    code: str | None = None  # a file, manifest or snippet shown as is (never invented command output)
    image: Screenshot | None = None  # a screenshot, with `caption` saying what it is and `notice` what to see in it
    caption: str = ""  # what the code or image is, e.g. "deployment.yaml"
    # where `code` comes from, shown under it: a file or manifest (default); a documented example that was not run
    # for this course; or output recorded in one of the course's labs (name the lab in the caption)
    origin: Literal["file", "example", "lab"] = "file"
    highlight: list[str] = []  # output lines containing one of these strings are emphasised
    notice: str = ""  # after the output: what it shows
    understand: Understand | None = None  # "Understand this command", for a `run` with unfamiliar options

    @model_validator(mode="after")
    def _one_source(self):
        if sum(x is not None for x in (self.run, self.code, self.image)) != 1:
            raise ValueError(f"show step {self.id}: give exactly one of run (a recorded command), code or image")
        _check_understand(self.id, self.understand, self.run)
        return self


class Hint(Strict):
    match: str  # a regular expression searched in the learner's attempt (spaces normalised)
    say: str

    @model_validator(mode="after")
    def _regex(self):
        import re

        re.compile(self.match)
        return self


class Try(Strict):
    """Guided practice: the learner types a command; it is compared with the accepted ones (nothing runs)."""
    kind: Literal["try"]
    id: str = Field(pattern=_STEP_ID)
    title: str = ""
    body: str  # the task, in one or two sentences
    accept: list[str] = Field(min_length=1)  # commands that do the task, compared after normalising spaces
    hints: list[Hint] = []  # targeted help for the mistakes people really make, tested in order
    hint: str = ""  # general help after a wrong attempt that no targeted hint explains
    run: str | None = None  # a recorded command whose output is shown once the learner succeeds or asks to see it
    then: str = ""  # shown after success: what the output means
    understand: Understand | None = None  # explains the solution (first accepted command) and the recording, shown with them

    @model_validator(mode="after")
    def _understand(self):
        _check_understand(self.id, self.understand, self.accept[0], self.run)
        return self


class Ask(Strict):
    """A question with a reason to exist: predict, read output, choose an action, find a cause, transfer an idea."""
    kind: Literal["ask"]
    id: str = Field(pattern=_STEP_ID)
    prompt: str
    evidence: str = ""  # output or a manifest the question is about, shown as a code block under the prompt
    choices: list[Choice] = Field(min_length=2, max_length=4)
    answer: int
    guess: bool = False  # a prediction before the idea is taught: not scored, the following steps answer it
    explain: str = ""  # the idea to keep, shown after any answer (defaults to the right choice's `why`)
    # a question about an earlier lesson names it, so the page can say where it comes from and the lint can check that
    # the lesson really comes earlier in the learner's path
    recalls: str = ""

    @model_validator(mode="after")
    def _answer(self):
        if not 0 <= self.answer < len(self.choices):
            raise ValueError(f"ask step {self.id}: answer is not a valid choice index")
        return self

    def as_predict(self, answered_by: str | None) -> Predict:
        prompt = self.prompt if not self.evidence else f"{self.prompt}\n\n```\n{self.evidence.rstrip()}\n```"
        return Predict(prompt=prompt, choices=[c.text for c in self.choices], answer=self.answer,
                       explain=self.explain or self.choices[self.answer].why, feedback=[c.why for c in self.choices],
                       role="predict" if self.guess else "check", after=self.id, answered_by=answered_by)


class Order(Strict):
    """Put steps in order (a procedure, the path of a request). Shown shuffled; `items` is the right order."""
    kind: Literal["order"]
    id: str = Field(pattern=_STEP_ID)
    prompt: str
    items: list[str] = Field(min_length=3, max_length=7)
    why: str  # shown after checking: why this order


class Reflect(Strict):
    """Put it in your own words, then compare with a model answer (self-explanation; never scored)."""
    kind: Literal["reflect"]
    id: str = Field(pattern=_STEP_ID)
    prompt: str
    model: str


class Explore(Strict):
    """An interactive model or diagram placed at this point of the flow (ids from the frontend's sims and diagrams)."""
    kind: Literal["explore"]
    id: str = Field(pattern=_STEP_ID)
    sim: str | None = None
    diagram: str | None = None
    body: str = ""  # what to try in it

    @model_validator(mode="after")
    def _one(self):
        if (self.sim is None) == (self.diagram is None):
            raise ValueError(f"explore step {self.id}: give exactly one of sim or diagram")
        return self


Step = Annotated[Teach | Show | Try | Ask | Order | Reflect | Explore, Field(discriminator="kind")]


class Lesson(Strict):
    id: str
    title: str  # two to six words
    subtitle: str = ""  # the details that do not fit in the title
    module: str
    mode: Mode
    minutes: int
    level: int = Field(1, ge=1, le=3)
    supports: str
    concepts: list[str]
    prerequisites: list[str] = []
    objective: str
    sections: list[Section] = []
    flow: list[Step] = []  # the teaching sequence (see Teach…Reflect); questions in it become `predict` items
    diagram: str | None = None
    simulator: str | None = None
    predict: list[Predict] = []
    explain: list[Explain] = []
    review: list[Card] = []
    labs: list[str] = []
    limits: str = ""
    enterprise: str = ""
    references: list[Ref] = []
    commands: list[LessonCmd] = []  # "try it on your machine", recorded on the host
    # where the commands are recorded: "host" (this machine, no cluster) or "cluster" (as the learner identity, in a
    # temporary namespace that is deleted afterwards; `kubectl` is available for upstream Kubernetes lessons)
    # "cluster-admin": as several identities (see LessonCmd.as_), possibly changing cluster configuration under an
    # `experiment` with a verified rollback; recorded only by `scripts/record.py --lessons --admin`
    record_on: Literal["host", "cluster", "cluster-admin"] = "host"
    files: dict[str, str] = {}  # written to the working directory of those commands
    test_users: list[str] = []  # throwaway users of a cluster-admin lesson; passwords are generated per recording
    # more generated values (a test user's next password…), available to the commands as environment variables and
    # redacted from the recording like the test users' passwords (`<NAME>_PASSWORD`)
    secret_vars: list[str] = Field([], json_schema_extra={"items": {"pattern": "^[A-Z][A-Z0-9_]*$"}})
    experiment: Experiment | None = None

    @model_validator(mode="after")
    def _activity_anchors(self):
        idents = {"", "admin", "developer", *self.test_users}
        for c in self.commands:
            if c.as_ not in idents:
                raise ValueError(f"command {c.cmd[:60]!r}: as={c.as_!r} is not admin, developer or one of test_users")
            if c.as_ and self.record_on != "cluster-admin":
                raise ValueError(f"command {c.cmd[:60]!r}: as= needs record_on: cluster-admin")
        if (self.experiment or self.test_users) and self.record_on != "cluster-admin":
            raise ValueError("an experiment or test users need record_on: cluster-admin")
        if self.flow:
            self._compile_flow()
        elif not self.sections:
            raise ValueError("a lesson needs sections or a flow")
        ids = [s.id for s in self.sections] + [st.id for st in self.flow]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate section or step ids: {sorted({i for i in ids if ids.count(i) > 1})}")
        qids = [p.id for p in self.predict]
        if len(set(qids)) != len(qids):
            raise ValueError("two questions in this lesson have the same prompt")
        valid = set(ids) | {"start"}
        for k, p in enumerate(self.predict):
            if p.after is not None and p.after not in valid:
                raise ValueError(f"question {k}: after={p.after!r} is not a section id")
            if p.answered_by is not None and p.answered_by not in ids:
                raise ValueError(f"question {k}: answered_by={p.answered_by!r} is not a section id")
            if p.role == "predict" and not p.answered_by:
                raise ValueError(f"question {k}: a predict item needs answered_by (the section that reveals the answer)")
        return self

    def _compile_flow(self):
        """Check the flow's references and derive `predict` from its questions, so answers, review and the
        "know this already?" checks work the same for both formats."""
        if any(not s.depth for s in self.sections):
            raise ValueError("a lesson with a flow keeps only depth sections (depth: true) in `sections`")
        cmds = {c.cmd for c in self.commands}
        derived = []
        for k, st in enumerate(self.flow):
            if isinstance(st, (Show, Try)) and st.run is not None and st.run not in cmds:
                raise ValueError(f"step {st.id}: run must be the exact cmd of one of the lesson's commands")
            if isinstance(st, Ask):
                later = next((x.id for x in self.flow[k + 1:] if isinstance(x, (Teach, Show))), None)
                if st.guess and later is None:
                    raise ValueError(f"step {st.id}: a guess must be followed by the teaching that answers it")
                derived.append(st.as_predict(later if st.guess else None))
        if self.predict and [p.id for p in self.predict] != [p.id for p in derived]:
            raise ValueError("a lesson with a flow writes its questions as ask steps, not in `predict`")
        self.predict = derived

    def fingerprint(self) -> str:
        import hashlib
        import json

        # cwd counts only when set, so that adding the field did not invalidate every existing recording
        data = {"commands": [c.model_dump(exclude={"meaning"} | ({"cwd"} if not c.cwd else set()) | ({"as_"} if not c.as_ else set()))
                             for c in self.commands], "files": self.files}
        # identities and the experiment count only when used, so that existing recordings stay valid
        if self.test_users:
            data["test_users"] = self.test_users
        if self.secret_vars:
            data["secret_vars"] = self.secret_vars
        if self.experiment:
            data["experiment"] = self.experiment.model_dump()
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


class DiagItem(Strict):
    """One diagnostic question. `targets` are what to study when it is missed: lesson ids, or lab, incident and
    challenge ids for the practice track. The first target decides the module the item is grouped under."""
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    targets: list[str] = Field(min_length=1)
    prompt: str
    evidence: str = ""  # optional command output or manifest shown under the prompt (rendered as a code block)
    choices: list[str] = Field(min_length=2, max_length=5)
    answer: int
    feedback: list[str]  # one per choice: why it is right, or what it confuses
    explain: str  # the short teaching point shown with the results

    @model_validator(mode="after")
    def _shape(self):
        if len(self.feedback) != len(self.choices):
            raise ValueError(f"{self.id}: feedback needs exactly one entry per choice")
        if not 0 <= self.answer < len(self.choices):
            raise ValueError(f"{self.id}: answer is not a valid choice index")
        return self


class Diagnostic(Strict):
    track: str
    covers: list[str] = []  # other tracks whose lessons this diagnostic also assesses (shown on their pages too)
    title: str
    intro: str
    minutes: int
    items: list[DiagItem]

    @model_validator(mode="after")
    def _unique(self):
        ids = [i.id for i in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate item ids: {sorted({i for i in ids if ids.count(i) > 1})}")
        return self


class Module(Strict):
    id: str
    title: str
    summary: str
    lessons: list[str] = []
    labs: list[str] = []  # practice modules list challenges, incidents and labs directly


class Track(Strict):
    id: str
    title: str
    short: str = ""  # label on the learning map
    accent: str = ""  # colour family on the map and the track's pages (a palette name the interface defines)
    icon: str = ""
    tagline: str = ""  # one short line for cards; the summary is shown on the path page
    level: str
    audience: str
    summary: str
    outcome: str
    modules: list[str]
    status: Literal["available", "coming-soon"] = "available"
    roadmap: list[str] = []  # planned topics with no material yet, shown as plain text (never as links)


class RouteBegin(Strict):
    kind: Literal["lesson", "diagnostic", "track", "lab"]
    id: str
    label: str  # the button text, e.g. "Take the 15-minute check"


class Route(Strict):
    """A recommended journey across the map for one kind of learner. Routes only order existing tracks and modules;
    learners can always leave a route and explore."""
    id: str
    title: str  # in the learner's words: "I'm new to all of this"
    who: str  # one sentence: who this is for
    promise: str  # what you can do at the end
    cluster: Literal["none", "optional", "recommended"] = "none"
    begin: RouteBegin
    steps: list[str]  # track or module ids, in order


class Concept(Strict):
    id: str
    title: str
    module: str
    related: list[str] = []


class Case(Strict):
    id: str
    title: str
    context: str
    situation: str
    ownership: dict[str, list[str]]  # application team, platform team, security, infrastructure, coordinate
    evidence: list[str]
    approvals: list[str]
    automate: list[str]
    discussion: list[Card]
    explain: list[Explain] = []
    concepts: list[str] = []
    references: list[Ref] = []


class Runbook(Strict):
    id: str
    title: str
    when: str
    severity_guide: str
    steps: list[TitledText]
    decision_tree: list[dict] = []
    escalate: list[str]
    concepts: list[str] = []
    labs: list[str] = []


_cache: dict = {}


def _flow_shape(lesson: Lesson) -> list:
    """What a translation of a flow lesson may not change: the steps, their commands and the keys of questions."""
    return [(st.kind, st.id, getattr(st, "run", None), getattr(st, "code", None), tuple(getattr(st, "accept", ())),
             getattr(st, "answer", None), len(getattr(st, "choices", ())), len(getattr(st, "items", ())), getattr(st, "guess", None))
            for st in lesson.flow]


def source_hash(item) -> str:
    """Fingerprint of an English item; a translation records it as `source:` to show which version it translates."""
    import hashlib
    import json

    return hashlib.sha256(json.dumps(item.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()[:12]


def load(lang: str | None = None) -> dict:
    """The course in one language. English is complete; another language overlays its translated items on the
    English ones by id, so anything untranslated falls back to English. `translation` records, per kind and id,
    whether the item is translated, stale (its English source changed since) or missing (shown in English)."""
    lang = lang if lang in config.LANGS else config.DEFAULT_LANG
    if lang == "en":
        return _load_dir(config.content_dir("en"))
    return _overlay(_load_dir(config.content_dir("en")), config.content_dir(lang))


_KINDS = {"tracks": "tracks.yaml", "modules": "modules.yaml", "routes": "routes.yaml", "concepts": "concepts.yaml"}


def _overlay(base: dict, root: Path) -> dict:
    files = sorted(root.rglob("*.yaml"))
    sig = (id(base), tuple((str(f), f.stat().st_mtime) for f in files))
    key = str(root)
    if key in _cache and sig == _cache[key]["sig"]:
        return _cache[key]["data"]
    models = {"tracks": Track, "modules": Module, "routes": Route, "concepts": Concept, "lessons": Lesson,
              "cases": Case, "runbooks": Runbook, "diagnostics": Diagnostic}
    data = {k: dict(v) if isinstance(v, dict) else v for k, v in base.items()}
    data["errors"] = list(base["errors"])
    status: dict[str, dict[str, str]] = {k: {} for k in models}

    def apply(kind: str, raw: dict, fname: str):
        try:
            raw = dict(raw)
            src = raw.pop("source", None)
            obj = models[kind].model_validate(raw)
            ident = obj.track if kind == "diagnostics" else obj.id
            english = base[kind].get(ident)
            if english is None:
                raise ValueError(f"{kind} {ident} does not exist in English")
            if kind == "lessons":
                if [x.id for x in obj.sections] != [x.id for x in english.sections]:
                    raise ValueError(f"lesson {ident}: a translation must keep the English section ids, in order")
                if _flow_shape(obj) != _flow_shape(english):
                    raise ValueError(f"lesson {ident}: a translation must keep every flow step (id, kind, commands, choices and answer), in order")
                same = [(q.role, q.answer, len(q.choices)) for q in obj.predict] == [(q.role, q.answer, len(q.choices)) for q in english.predict]
                if not same:
                    raise ValueError(f"lesson {ident}: a translation must keep every question, in order, with the same choices and answer")
                for q, eq in zip(obj.predict, english.predict):
                    q.translates = eq.id
            data[kind][ident] = obj
            status[kind][ident] = "translated" if src == source_hash(english) else "stale"
        except Exception as e:
            data["errors"].append(f"{root.name}/{fname}: {str(e)[:300]}")

    for kind, fname in _KINDS.items():
        f = root / fname
        if f.exists():
            for raw in yaml.load(f.read_text(encoding="utf-8"), Loader=_LOADER) or []:
                apply(kind, raw, fname)
    for kind in ("lessons", "cases", "runbooks"):
        for f in sorted((root / kind).glob("*.yaml")):
            for raw in yaml.load(f.read_text(encoding="utf-8"), Loader=_LOADER) or []:
                apply(kind, raw, f.name)
    for f in sorted((root / "diagnostics").glob("*.yaml")):
        apply("diagnostics", yaml.load(f.read_text(encoding="utf-8"), Loader=_LOADER) or {}, f.name)
    data["translation"] = status
    _cache[key] = {"sig": sig, "data": data}
    return data


def _load_dir(root: Path) -> dict:

    def _files(sub: str) -> list[Path]:
        return sorted((root / sub).glob("*.yaml"))

    files = [root / "tracks.yaml", root / "modules.yaml", root / "routes.yaml", root / "concepts.yaml", *_files("lessons"), *_files("cases"), *_files("runbooks"), *_files("diagnostics")]
    sig = tuple((str(f), f.stat().st_mtime if f.exists() else 0) for f in files)
    key = str(root)
    if key in _cache and sig == _cache[key]["sig"]:
        return _cache[key]["data"]
    errors: list[str] = []

    def read(path: Path):
        try:
            return yaml.load(path.read_text(encoding="utf-8"), Loader=_LOADER) or []
        except Exception as e:
            errors.append(f"{path.name}: {e}")
            return []

    tracks, modules, concepts, lessons, cases, runbooks = {}, {}, {}, {}, {}, {}
    for t in read(root / "tracks.yaml"):
        try:
            tr = Track.model_validate(t)
            tracks[tr.id] = tr
        except Exception as e:
            errors.append(f"tracks.yaml: {e}")
    for m in read(root / "modules.yaml"):
        try:
            mod = Module.model_validate(m)
            modules[mod.id] = mod
        except Exception as e:
            errors.append(f"modules.yaml: {e}")
    routes: dict[str, Route] = {}
    for r in read(root / "routes.yaml") if (root / "routes.yaml").exists() else []:
        try:
            ro = Route.model_validate(r)
            routes[ro.id] = ro
        except Exception as e:
            errors.append(f"routes.yaml: {e}")
    for c in read(root / "concepts.yaml"):
        try:
            con = Concept.model_validate(c)
            concepts[con.id] = con
        except Exception as e:
            errors.append(f"concepts.yaml: {e}")
    for target, sub, model in ((lessons, "lessons", Lesson), (cases, "cases", Case), (runbooks, "runbooks", Runbook)):
        for f in _files(sub):
            for item in read(f):
                try:
                    obj = model.model_validate(item)
                    if obj.id in target:
                        raise ValueError(f"duplicate id {obj.id}")
                    target[obj.id] = obj
                except Exception as e:
                    errors.append(f"{f.name}: {str(e)[:400]}")
    diagnostics: dict[str, Diagnostic] = {}
    for f in _files("diagnostics"):
        raw = read(f)
        try:
            dg = Diagnostic.model_validate(raw)
            if dg.track in diagnostics:
                raise ValueError(f"second diagnostic for track {dg.track}")
            diagnostics[dg.track] = dg
        except Exception as e:
            errors.append(f"{f.name}: {str(e)[:400]}")
    data = {"tracks": tracks, "modules": modules, "concepts": concepts, "lessons": lessons, "cases": cases, "runbooks": runbooks, "diagnostics": diagnostics, "routes": routes, "errors": errors}
    _cache[key] = {"sig": sig, "data": data}
    return data


def integrity(lab_ids: set[str], lang: str | None = None, *, data: dict | None = None) -> list[str]:
    """Cross-references: every id a track, lesson, module, case or runbook points to must exist."""
    d = load(lang) if data is None else data
    problems = []
    for t in d["tracks"].values():
        for m in t.modules:
            if m not in d["modules"]:
                problems.append(f"track {t.id}: missing module {m}")
    for m in d["modules"].values():
        if not any(m.id in t.modules for t in d["tracks"].values()):
            problems.append(f"module {m.id} is in no track")
    for m in d["modules"].values():
        for lid in m.lessons:
            if lid not in d["lessons"]:
                problems.append(f"module {m.id}: missing lesson {lid}")
        for lab in m.labs:
            if lab not in lab_ids:
                problems.append(f"module {m.id}: unknown lab {lab}")
    from . import media

    problems += media.problems(d["lessons"].values())
    for l in d["lessons"].values():
        if l.module not in d["modules"]:
            problems.append(f"lesson {l.id}: unknown module {l.module}")
        for p in l.prerequisites:
            if p not in d["lessons"]:
                problems.append(f"lesson {l.id}: unknown prerequisite {p}")
        for c in l.concepts:
            if c not in d["concepts"]:
                problems.append(f"lesson {l.id}: unknown concept {c}")
        for st in l.flow:
            u = getattr(st, "understand", None)
            for c in u.concepts if u else []:
                if c not in d["concepts"]:
                    problems.append(f"lesson {l.id}, step {st.id}: understand names unknown concept {c}")
        for lab in l.labs:
            if lab not in lab_ids:
                problems.append(f"lesson {l.id}: unknown lab {lab}")
        if not any(l.id in m.lessons for m in d["modules"].values()):
            problems.append(f"lesson {l.id} is not in any module")
        elif l.module in d["modules"] and l.id not in d["modules"][l.module].lessons:
            problems.append(f"lesson {l.id}: says module {l.module}, but that module does not list it")
    for c in d["concepts"].values():
        for r in c.related:
            if r not in d["concepts"]:
                problems.append(f"concept {c.id}: unknown related {r}")
    for rb in d["runbooks"].values():
        for lab in rb.labs:
            if lab not in lab_ids:
                problems.append(f"runbook {rb.id}: unknown lab {lab}")
    for ro in d.get("routes", {}).values():
        for st in ro.steps:
            if st not in d["tracks"] and st not in d["modules"]:
                problems.append(f"route {ro.id}: unknown step {st}")
        b = ro.begin
        known = {"lesson": d["lessons"], "diagnostic": d["diagnostics"], "track": d["tracks"]}.get(b.kind)
        if (known is not None and b.id not in known) or (b.kind == "lab" and b.id not in lab_ids):
            problems.append(f"route {ro.id}: unknown {b.kind} {b.id}")
    for dg in d["diagnostics"].values():
        tr = d["tracks"].get(dg.track)
        if not tr:
            problems.append(f"diagnostic {dg.track}: unknown track")
            continue
        for extra in dg.covers:
            if extra not in d["tracks"]:
                problems.append(f"diagnostic {dg.track}: covers unknown track {extra}")
        mods = [m for t in (dg.track, *dg.covers) if t in d["tracks"] for m in d["tracks"][t].modules]
        in_track = {x for m in mods if m in d["modules"] for x in (*d["modules"][m].lessons, *d["modules"][m].labs)}
        for it in dg.items:
            for t in it.targets:
                if t not in d["lessons"] and t not in lab_ids:
                    problems.append(f"diagnostic {dg.track}/{it.id}: unknown target {t}")
            if it.targets[0] not in in_track:
                problems.append(f"diagnostic {dg.track}/{it.id}: first target {it.targets[0]} is not in track {dg.track}")
    return problems
