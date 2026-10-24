# Continuous integration

Every pull request runs the whole Python suite, the content checks, the site build and export, and the Windows
contributor workflow. A pull request that changes only lessons, labs, recordings, screenshots or Markdown docs gets
the **content lane**, which adds a browser check of every page. Every other pull request gets the **deep lane**, which
adds the production image, the whole browser suite in Chromium and Firefox, a fifth of it in Firefox on Windows, and a
dependency review. After every merge, `ci-main` runs the deep lane again with all of the Windows browser tests. Only
official GitHub actions (`actions/*`, pinned to a commit) and the scripts of this repository are used: no third-party
action, app or service.

```
pull request ──> ci.yml ─ classify ── base commit's scripts/ci_needs_site.py --tier-raw
                    │        ├─ tier=content ──> checks-content.yml  python, site, windows, same-site, pages ─┐
                    │        └─ tier=deep ─────> checks-app.yml      python, site, windows, same-site,        ├─> ci-ok
                    │                                                 image, browser x6, windows-browser, deps ┘
                    └─ ci-guard.yml (pull_request_target, from the default branch) ──────────────────────> ci-guard
push to main ───> checks-main.yml (ci-main): checks-app.yml + windows-browser parts 2-5
                    ├─ success ──> candidate.yml: the exact image, the whole browser suite against it, publish
                    └─ failure ──> main-alert.yml: the "main is failing" issue, assigned to the owner
manual / weekly ─> checks-main.yml (ci-main), the same, without a candidate
```

## Which lane

`scripts/ci_needs_site.py` decides from git's raw list of changed files, taken from the **base** commit (a pull request
cannot change the decision for itself). **Content** only when every file is on this allow-list, as an ordinary file
(no symbolic link, executable or submodule; a moved file counts by its old path too):

- `content/**/*.yaml`, `*.yml`, `*.md`; `content/recordings/**/*.json`; `content/media/<lesson>/<image>.png`;
- `docs/**/*.md`; `README.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md`,
  `THIRD_PARTY_NOTICES.md`.

Everything else is **deep**: code, tests, scripts, workflows and anything under `.github/`, dependency and lock files,
the Containerfile and nginx, any other file type, and anything the list does not know.

| | content lane | deep lane | ci-main (after a merge, manual, weekly) |
|---|---|---|---|
| content checks (load, teaching rules, addresses, coverage, public scan) | yes | yes | yes |
| the whole Python suite, Linux and Windows | yes | yes | yes |
| frontend tests, type check, build, export, scan, internal links, Linux and Windows | yes | yes | yes |
| Linux and Windows exports identical | yes | yes | yes |
| every page opens in Chromium: renders, no error, fits a phone | yes | in the browser suite | in the browser suite |
| production image built once and smoke-tested | | yes | yes |
| the whole browser suite against the image, Chromium and Firefox | | yes (3 + 3 parts) | yes |
| browser tests in Firefox on Windows | | part 1 of 5 | all 5 parts |
| dependency review of added packages | | yes | |

A content change cannot touch the code, the nginx rules or the build that the image and the browser suite test; it
can break how a page renders, which the page check opens. The deep lane's jobs run side by side; the content lane's
python, site, windows and same-site jobs are the deep lane's own (`tests/test_ci_workflows.py` checks that they are
identical).

## Locally

```bash
scripts/test_content.sh      # content checks, the whole Python suite, frontend tests and build, export, links
scripts/test_all.sh          # everything, both browser engines (long); TEST_WEBKIT=1 adds WebKit in a container
```

## Who must review: ci-guard

`ci-guard` is the check a pull request cannot rewrite: `pull_request_target` runs it from the default branch; it checks
out and runs nothing from the pull request, reads the changed files and their file modes from the API, and posts the
commit status `ci-guard`. It passes when the owner opened the pull request, or when every changed file is Markdown
documentation or a lesson screenshot (an ordinary file), or when the owner approved that exact commit. Anything else
from anyone else needs the owner's approval first, including lessons, labs, incidents, challenges, diagnostics and
recordings: their commands and manifests are shown to learners, applied to their own clusters (a lab's
`elevated_setup` with the admin identity, after the learner's consent) and run by the owner's recorder. Content is never
run in CI, in either lane; the lab model refuses manifests that would hand out administration
(`backend/academy/labs.py`), and the owner's review covers what no validator can judge.

GitHub starts no trusted workflow on a review: after approving or withdrawing an approval, the owner re-runs
`ci-guard`, or adds or removes any label on the pull request. A new commit always needs a new approval. The comparison
API lists at most 300 files: that size, an incomplete listing or a file tree too large to read requires review too.
`.github/CODEOWNERS` asks the owner for reviews but blocks nothing by itself: "Require review from Code Owners" stays
off, because the owner cannot approve their own pull requests.

## What the checks guarantee, and what they do not

- On `pull_request`, GitHub runs the workflow files **of the pull request**: a pull request can edit `ci.yml` or a lane
  and make `ci-ok` pass. Taking the classifier from the base commit only stops mistakes; `ci-guard` is what stops
  someone else's pull request from changing CI unread.
- Pull-request jobs get a read-only token and no secrets (forks included); only the owner merges.
- `ci-ok` passes only if the classifier ran and exactly the lane it chose succeeded, the other being skipped
  (`tests/test_ci_gate.py` checks the decision for every combination of results). Inside a lane no job has a
  condition except the dependency review (pull requests only), so no check can be skipped quietly.
- A green run proves that each command exited successfully, not that every collected test executed.

## When main fails

`ci-main` runs after every merge and is never cancelled. A failed, cancelled or timed-out run opens one issue, "main is
failing", assigned to the owner (or comments on the open one); a passing run for the commit main points to closes it
(`main-alert.yml`). It is an alert, not a lock: nothing stops another merge while main is red, so fix main first. The
release candidate is built only from a successful `ci-main` run of a push to main.

## Required checks (repository ruleset)

Before this change: the eleven job names of the single-file workflow, which also reported `ci-ok`. After it: `ci-ok`
and `ci-guard`, both from GitHub Actions. The switch is the owner's, in this order: confirm on GitHub how `ci-ok`
reports failed, cancelled, skipped and re-run jobs; require `ci-ok` next to the eleven names; when this change is
ready to merge (its own run reports `ci-ok`, not the eleven names), remove the eleven names and merge it; check
`ci-guard` on a pull request from another account, then require it. Job names inside the lanes are not required and
may change.
