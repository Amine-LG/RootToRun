#!/usr/bin/env bash
# Everything CI runs, locally (docs/CI.md): the content lane, the full Python suite, the frontend tests and build, the
# static export and its checks, then the whole browser suite in Chromium and Firefox. Long (tens of minutes); for a
# lesson, lab or doc change, scripts/test_content.sh is enough.
#   scripts/test_all.sh                  # Linux or macOS, with .venv and Node.js 22
#   TEST_WEBKIT=1 scripts/test_all.sh    # also WebKit, in the official Playwright container (podman or docker):
#                                        # WebKit needs system libraries most hosts do not have
# The Windows checks are in docs/WINDOWS.md; the production image: scripts/smoke_image.sh after `podman build`.
set -euo pipefail
cd "$(dirname "$0")/.."
export ACADEMY_CLUSTER=off KUBECONFIG=/nonexistent
python=${PYTHON:-.venv/bin/python}
workers=${TEST_WORKERS:-4}

scripts/test_content.sh   # content checks, the whole Python suite, frontend tests and build, export, scan, links
for browser in chromium firefox; do
  echo "== browser tests in $browser"
  "$python" -m playwright install "$browser"
  E2E_BROWSER="$browser" "$python" -m pytest -q -p no:cacheprovider tests/e2e -n "$workers"
done
if [ "${TEST_WEBKIT:-0}" = 1 ]; then
  echo "== browser tests in WebKit (Playwright container; the version matches requirements-dev.txt)"
  version=$("$python" -c 'import importlib.metadata as m; print(m.version("playwright"))')
  engine=$(command -v podman || command -v docker)
  "$engine" run --rm --ipc=host -v "$PWD:/work:Z" -w /work -e ACADEMY_CLUSTER=off -e E2E_BROWSER=webkit \
    "mcr.microsoft.com/playwright/python:v$version-noble" \
    bash -c 'python -m venv /tmp/venv && /tmp/venv/bin/pip install -q -r requirements-dev.txt &&
             /tmp/venv/bin/python -m pytest -q -p no:cacheprovider tests/e2e -n 4'
fi
