# Writing content

All course content lives in `content/<lang>/` as YAML, validated strictly at load (unknown fields are errors).
Run `.venv/bin/python -m pytest tests/test_content.py` after any change.

## Structure

- `tracks.yaml`: learning paths → module ids.
- `modules.yaml`: modules → lesson ids (order matters).
- `concepts.yaml`: the concept graph (`id`, `title`, `module`, `related`).
- `lessons/*.yaml`: lessons, several per file, every one written as a teaching **flow** (below), with `review`
  cards, `labs` and `references` to official documentation. The older fields `sections`, `predict` and `explain`
  are still read for older content, but a flow lesson must not use them.
- `labs/*.yaml`, `incidents/*.yaml`: executable content (below).
- `urls.yaml`: the public address of every track, lesson and lab (a slug per id, e.g. lesson `n.htpasswd-users` is
  `/learn/platform-administration/manage-local-users`). After adding a lesson or lab, run
  `.venv/bin/python scripts/slugs.py`: it adds a slug made from the title and never changes an existing one, so
  renaming a lesson keeps its address. In content, keep linking by id (`[Manage local users](/lesson/n.htpasswd-users)`,
  `[the incident](/lab/inc.dns-typo)`): links are shown with the readable address, and ids never change.

## A lesson written as a teaching flow (preferred)

New and rewritten lessons are written as a **flow**: a list of small typed steps, read in order, in one growing
column. Read `docs/teaching/TEACHING-STANDARD.md` first: it says how a step should teach. The schema is in
`backend/academy/curriculum.py` (`Teach` … `Explore`).

```yaml
- id: lx.example
  title: "Three to six words"
  module: lx1-shell
  mode: GUIDED_INVESTIGATION
  minutes: 15
  supports: "What the recordings were made with, and where."
  concepts: [linux.shell]
  prerequisites: [lx.first-steps]
  objective: "What the learner can do at the end."
  record_on: host                # or cluster: kubectl and oc, as the learner identity, in a temporary namespace
  flow:
    - kind: ask                  # open with a short question on an earlier lesson
      id: recall
      prompt: "A look back. …?"
      choices:
        - {text: "…", why: "Why it is right, in one sentence."}
        - {text: "…", why: "The misconception behind this choice, and the correct model."}
        - {text: "…", why: "…"}
      answer: 0
    - kind: teach                # one idea; a title starts a new part in the outline
      id: idea
      title: "…"
      body: "…"
    - kind: show                 # a recorded command and its real output (or `code:` for a file)
      id: demo
      run: "ls -l"               # must equal a `cmd` below; the output comes from the recording
      highlight: ["readme.txt"]
      notice: "What to look at in the output."
    - kind: try                  # the learner types; compared with `accept` after normalising spaces
      id: practice
      body: "The task, in one sentence."
      accept: ["ls -la", "ls -al"]
      hints:                     # regular expressions for the mistakes people really make
        - {match: "^ls -l$", say: "What is missing, and why."}
      hint: "General help."
      run: "ls -la"              # shown once the learner succeeds or asks to see it
    - kind: ask
      id: predict
      guess: true                # a prediction, not scored; the next teach/show step answers it
      prompt: "…"
      choices: […]
      answer: 1
    - kind: order                # steps of a procedure, in the right order (shown shuffled)
      id: steps
      prompt: "…"
      items: ["…", "…", "…"]
      why: "…"
    - kind: reflect              # self-explanation, compared with a model answer, never scored
      id: in-your-words
      prompt: "…"
      model: "…"
    - kind: explore              # a model (sims/index.ts) or diagram (lib/diagrams.ts) at this point
      id: model
      sim: drift
      body: "What to try in it."
    - kind: teach
      id: what-next
      title: "What you can do now"
      body: "The new abilities, and how the next lesson builds on them."
  sections: []                   # only `depth: true` sections ("Go deeper"), optional
  review: [{q: "…", a: "…"}]
  commands: [{cmd: "ls -l", meaning: "…"}, {cmd: "ls -la", meaning: "…"}]   # every `run` above must be one of these;
                                             # recorded with scripts/record.py, in order, sharing files
  files: {"notes/todo.txt": "…"}             # written to the practice directory before recording
  references: [{title: "…", url: "https://…"}]
```

Then:

1. `.venv/bin/python scripts/record.py --lessons <id>` runs the commands and saves the real output
   (`content/recordings/lesson.<id>.json`, both streams in the order they arrived). Read the output, and fix the
   prose wherever it says something the recording does not show.
2. `.venv/bin/python scripts/teach_lint.py <id>` checks what a program can check: steps that are too long, too
   many steps without anything for the learner to do, answer keys that are longer than their distractors,
   "just" and "simply", tools that do not belong in the track, unrecorded commands.
3. `.venv/bin/python -m pytest tests/test_content.py tests/test_i18n.py` for integrity, and add the lesson as the
   first target of an item in its track's diagnostic.

The questions of a flow keep stable ids derived from their prompts, like long-form questions: rewording a
prompt makes it a new question. In the authoring page, a flow lesson is previewed step by step, and validation
lists the teaching-standard warnings next to the errors.

## A lesson in the long-form format (older lessons)


A lesson is played as a plan of activities, compiled from these fields:

```yaml
- id: d.example
  title: "…"
  module: a5-network
  mode: REAL_LAB
  minutes: 30
  concepts: [net.services]
  objective: |                # shown as "You will be able to"
    …
  diagram: request-path       # optional Explore activity after the first core section (lib/diagrams.ts)
  simulator: traffic          # optional Explore activity after the last core section (src/sims/index.ts)
  sections:
    - id: pods-and-services   # stable: checks and progress refer to it; never reuse an id for other content
      title: "…"
      body: |
        One idea per section, in Markdown.
    - id: common-mistakes
      title: "Common mistakes"
      depth: true             # "go deeper": reachable from every activity, not part of the main flow
      body: "…"
  predict:                    # graded Checks unless role: predict
    - prompt: "…"
      after: pods-and-services  # the core section that teaches what this question tests (required in practice)
      choices: ["…", "…", "…"]
      answer: 1
      explain: "The key idea."
      feedback: ["why A is tempting and wrong", "why B is right", "why C is wrong"]  # one per choice
  review: [{q: "…", a: "…"}]  # recall cards for the review deck
  labs: [lab.example]
  references: [{title: "…", url: "https://docs.redhat.com/…"}]
```

Rules:

1. A Check must be answerable from the core sections up to and including its `after` section. The content tests
   refuse an `after` that is unknown or that points at a `depth: true` section.
2. `role: predict` (with `answered_by: <section id>`) makes an ungraded guess placed before the section that
   answers it. Use it only when that section explicitly gives the answer.
3. Write feedback for every choice: name the misconception, do not just say "wrong". No praise-only feedback.
4. Editing a question's prompt makes it a new question (its id is derived from the prompt), so learners' previous
   answers no longer count for it. That is intended: the question changed.
5. Commands written in prose (inline `oc …` or fenced blocks) must exist in a recording; otherwise reword.

## A lab

```yaml
id: lab.example
title: "…"
summary: "…"
module: a2-apps
minutes: 20
level: 1                      # 1–3
supports: "What this was tested on, and limits."
concepts: [k8s.deployment]
objective: |
  …
namespace: academy-example    # must start with academy-; created and deleted by the academy
setup:                        # manifests applied before the first step (no metadata.namespace)
  - |
    apiVersion: v1
    kind: ConfigMap
    …
steps:
  - id: create
    title: "…"
    do: "What to do (Markdown)."
    predict: {prompt: "…", choices: ["…", "…"], answer: 1, explain: "…"}
    commands:
      - {cmd: "oc create deployment web --image=… -n academy-example", meaning: "…"}
      - {cmd: "oc logs <pod> -n academy-example", run: "oc logs {pod:app=web} -n academy-example"}
      - {cmd: "oc auth can-i delete pods -n academy-example", expect: fail, meaning: "no: exit code 1"}
    wait_for: [web-ready]     # checks the recorder polls after this step
    observe: "What the learner should see."
    why: "Why it matters."
checks:
  - {id: web-ready, title: "web is available", type: deployment_ready, name: web, expect_text: "1/1"}
questions: [{q: "…", a: "…"}]
references: [{title: "…", url: "https://docs.redhat.com/…"}]
requires: [crc]               # only what the content cannot show by itself: crc, olm, reader, admin, dynamic-storage, routes
cluster_objects:              # cluster-scoped objects a step creates as admin, so the ledger can track and clean them
  - {kind: Group, name: academy-auditors, path: /apis/user.openshift.io/v1/groups/academy-auditors,
     created_by: "oc adm groups new academy-auditors developer", deleted_by: "oc delete group academy-auditors"}
```

Requirements are also derived from the content (admin or reader commands, PersistentVolumeClaims, Routes); the
preflight compares them with what the connected cluster and identities can actually do.

Rules that keep the promise that every command shown as run really ran:

1. Every command must run through the learner policy (or be `as: reader` / `as: admin`). If the policy refuses
   it, the recording fails.
2. Give each command an `expect`. Commands whose *point* is to fail (`can-i` answering no, `oc diff` finding
   drift, a curl that times out) use `expect: fail`, and the lesson explains the exit code.
3. Checks must fail before the learner acts. The recorder refuses a lab that is already "verified" at the start
   (and an incident that is not broken).
4. Use `final: false` for checks that only make sense during one step.
5. Never put credentials in outputs. Do not record commands that print tokens.

## An incident

Same schema with `kind: incident`, plus: `symptom` (what users see), `break` (manifests applied after `setup`),
`investigate` (commands an expert would run), `hints` (progressive), `fix` (the reference repair), `fix_wait`
(checks to wait for after the fix), `root_cause`, `alternatives` and `sre` (prevention). The API hides
`break`, `fix`, `root_cause`, `alternatives` and `sre` until the learner asks for the answer.

## Record and test

```bash
.venv/bin/python scripts/record.py lab.example          # needs a cluster and the learner connected
.venv/bin/python -m pytest tests                        # fails if any recording is missing, failed or stale
```

Recordings are part of the content: commit them with the lab. Any change to what runs (commands, manifests,
checks, including their titles and expected texts) changes the lab's fingerprint and requires recording again;
other wording changes do not.

## Translating

Copy `content/en/` to `content/<lang>/` and translate the prose (keep ids, commands and manifests; the directory is
found automatically), and add `frontend/src/i18n/<lang>.ts`. Recordings are shared
between languages.

## Local authoring mode

Start one local server from your checkout, without cluster access:

```bash
ACADEMY_CLUSTER=off ACADEMY_AUTHORING=1 ./run.sh --fg
```

Open the `http://127.0.0.1:8768/author#token=…` URL printed once at startup (or in `data/server.log`
when running in the background). `ACADEMY_PORT` changes the port. For a direct Uvicorn invocation, bind to
`127.0.0.1`, use one worker and pass `--no-proxy-headers`. Do not put this server behind a proxy.

Authoring is off unless `ACADEMY_AUTHORING=1` is set when the server starts. Startup generates a fresh random
bearer token; optionally supply your own secret through `ACADEMY_AUTHORING_TOKEN`. Treat the startup URL and
server log as credentials: anyone who can read them and connect locally can edit the course. The browser reads
the fragment once, removes it from the address bar and retains the token in `sessionStorage` for that tab.
Every `/api/author/*` request requires both the bearer token and an actual loopback client address, including
reads. Non-loopback clients are refused even with the token. The normal Host, no-CORS and `X-Academy: 1`
write guards also apply. `/api/meta` exposes only an `authoring` boolean. Static exports force it to false and
never export author pages, author API data, drafts, revisions or tokens.

The workflow is **edit → validate → preview → draft → publish → git diff → pull request**:

1. Search for a lesson, module, track, route or diagnostic. List items show their exact YAML block; diagnostics
   show their entire YAML object. Keep the leading `- ` for list items.
2. Edit the source. Problems update after a short pause: safe YAML parsing, the Pydantic model, cross-references
   with the edit substituted, and saved-progress checks. Existing section ids cannot disappear or change.
   Existing questions keep their positions; append new questions at the end. Changed or removed prompts warn
   that their saved answers will not carry over, using the same prompt hash as the lesson model.
3. Open Preview to inspect the unsaved lesson's Markdown, questions with choices and feedback, explain prompts
   and review cards. Preview does not execute commands or write progress. Diagrams, simulations, lab workspaces
   and host recordings are not played inside this simple preview.
4. Save draft at any point, including incomplete YAML. Drafts live under `data/authoring/drafts/` and can be
   reopened from the list. They retain the original file hash so publishing an old draft detects conflicts.
5. Publish after resolving all errors; review the confirmation and any warnings. The server checks the hash of
   the whole containing file, records the previous block under `data/authoring/revisions/<kind>/<id>/`, replaces
   only that block atomically, then reloads and validates the whole curriculum. A validation failure restores
   the file. Surrounding comments and other items retain their bytes. A conflict requires reloading the file and
   reconciling your edit; save a draft before reloading if needed.
6. History shows the previous blocks. Restore validates through the same publish path and creates another
   revision. Progress protection still applies: a revision that removes section ids added later is refused.
7. Run `git diff -- content/en/`, review and run the content checks, then commit on your contribution branch and
   propose a pull request. Publishing never runs Git, commits, pushes or deploys anything.

New item supports appending a lesson to an existing lesson file or creating a diagnostic file. Give paths
relative to `content/`, such as `en/lessons/operations.yaml` or `en/diagnostics/new-track.yaml`. All references
must resolve when the candidate is substituted. For new lessons, first list their ids in the module YAML;
create the lesson before publishing unrelated edits. Changes involving several linked files are easier to
prepare directly in YAML and review together with Git. The editor does not offer a multi-file transaction.

Runtime data is git-ignored; drafts and revision files are written with mode `0600`. IDs and file paths are
restricted to the editable content families; traversal, symlinks, duplicate YAML keys, aliases and executable
YAML tags are refused. Authoring does not add multi-user collaboration, accounts, roles, permissions, remote
use, a hosted CMS or a replacement for Git review. YAML remains the source of truth and direct Git editing
continues to work. Keep a single authoring server per checkout; filesystem tools outside the app do not share
its write lock.
