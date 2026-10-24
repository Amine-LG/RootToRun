# Contributing

Root to Run teaches with real commands and real outputs, so a contribution is judged on one thing first: is it
correct, and can someone else check it? Most content changes need no cluster.

## What you can contribute

- **Report a problem**: on the published site, every lesson has a *Report a problem* link that opens a form with the
  lesson, section and site version filled in (or open an issue directly). Link the official documentation that supports the correction.
- **Fix or improve a lesson**: *Edit this lesson* opens its source. Lessons are YAML files in `content/en/lessons/`
  with Markdown prose; [docs/AUTHORING.md](docs/AUTHORING.md) describes the format and
  [docs/teaching/TEACHING-STANDARD.md](docs/teaching/TEACHING-STANDARD.md) the rules a lesson must meet. To find a
  lesson by its id: `grep -n "^- id: c.auth" content/en/lessons/*.yaml`.
- **Add a lab, incident or challenge**, improve an interactive model, or fix the app (React and TypeScript in
  `frontend/`, FastAPI in `backend/`). Translations go in `content/<lang>/` and `frontend/src/i18n/`.

## Requirements for content

- **Accurate and verifiable.** Every technical claim must be checkable against the official documentation
  (docs.redhat.com, kubernetes.io, the projects' own docs) or a recording. Say which version you verified, and keep
  Kubernetes behaviour apart from OpenShift-specific behaviour.
- **Original work only.** No Red Hat training material, no exam questions or exam dumps, no confidential information,
  and nothing copied from books, courses or other sites. Short documentation examples may be adapted only under
  their licence, credited in `content/ATTRIBUTIONS.md`.
- **No unsupported images or marks.** Do not add screenshots, logos or other trademark assets: the existing console
  screenshots are a deliberate, documented exception. Never use vendor course or exam codes, and never suggest that
  the project is official, endorsed or a certification course.
- **Reproducible exercises.** A lab, incident or challenge must work from a clean disposable cluster (OpenShift Local)
  and clean up after itself. Never hand-edit `content/recordings/` and never invent output: commands are recorded by a
  maintainer with `scripts/record.py`.
- **No secrets.** No credentials, tokens, private hostnames or personal data in content, recordings or tests.

## Recordings, graders and models

- **Explanations** (prose, questions, explanations of answers, a command's `meaning`, references) can change freely.
- **Recorded commands are fingerprinted.** Changing a lesson's `commands`, `files` or `experiment`, or a lab's setup,
  commands or checks, makes `tests/test_content.py` fail with "commands changed since they were recorded". That is
  expected: open the pull request anyway and name the lessons that need a new recording; a maintainer records them.
- **Typed-command answers**: nothing a learner types is run; `frontend/src/lib/match.ts` compares it with the accepted
  answers. Every accepted answer must be a correct command. When you change them, run
  `.venv/bin/python scripts/grading_oracle.py --file content/en/lessons/<file>.yaml` (needs `oc` and `bwrap`, no
  cluster). A wrong command that the checker accepts is a bug: add a case to `frontend/src/lib/match.test.ts`.
- **Graders and interactive models** need tests with the change: a grader change needs a case that fails without
  it (`tests/`), a model change a unit test (`frontend/src/sims/models.test.ts`) and, for visible behaviour, a browser
  test (`tests/e2e/`).

## Who must review

A pull request from anyone but the owner needs the owner's approval of its exact commit before it can merge, unless
every changed file is Markdown documentation or a lesson screenshot. That includes lessons, labs, incidents,
challenges, diagnostics and recordings: their commands and manifests are shown to learners, applied to their own
clusters and run by the owner's recorder. The `ci-guard` check enforces this from the default branch
(`.github/workflows/ci-guard.yml`); after approving, the owner re-runs it or changes a label. A new commit needs a new
approval.

## Before you open a pull request

```bash
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements-dev.txt   # once
.venv/bin/python scripts/check_content.py               # every content file loads (else: the file and why)
.venv/bin/python -m pytest tests --ignore=tests/e2e     # Python, API, security and content checks
.venv/bin/python scripts/teach_lint.py                   # teaching rules
.venv/bin/python scripts/slugs.py --check                # lesson and lab addresses stay stable
.venv/bin/python scripts/public_scan.py                  # no credentials, keys or course codes
cd frontend && npm ci && npm test && npm run build && cd ..
.venv/bin/python -m playwright install firefox           # once
.venv/bin/python -m pytest tests/e2e                     # browser tests on the exported site
```

On Windows, the same checks in PowerShell are in [docs/WINDOWS.md](docs/WINDOWS.md). CI runs these checks on Linux
and Windows, builds the production image and runs the browser tests against it. Please do not weaken a
check to make it pass; if you think one is wrong, say so in the pull request.

## Pull requests

- One topic per pull request, small enough to review.
- Say what changed and why, and link the documentation or recording that supports a technical change.
- Mention anything a maintainer must do, such as lessons to record again.

Maintainers review every pull request and merge only when the checks pass. Merging never changes the website by
itself.

## Licence of contributions

By contributing, you agree that your code is licensed under the Apache License 2.0 and your course content under
CC BY-SA 4.0. You keep the copyright of what you write, and your name stays in the history. Contribute only what you
wrote, or may share under these licences with its source named.
