#!/usr/bin/env bash
# The content lane of CI (.github/workflows/checks-content.yml), locally: edited a lesson, a lab or a doc? Run this
# (a few minutes; docs/CI.md). The Windows job and the page check run in CI.
#   scripts/test_content.sh                 # everything below, in order
#   scripts/test_content.sh --data-checks   # content loads, teaching rules, stable addresses, coverage, public scan
#   scripts/test_content.sh --python        # the whole Python suite, as CI runs it
#   scripts/test_content.sh --site          # frontend tests, type check and build; static export; scan; links
# Needs .venv (docs/INSTALL.md) and, for --site, Node.js 22 (npm). PYTHON and TEST_WORKERS override the defaults.
set -euo pipefail
cd "$(dirname "$0")/.."
export ACADEMY_CLUSTER=off KUBECONFIG=/nonexistent
python=${PYTHON:-.venv/bin/python}
[ -x "$python" ] || python=.venv/Scripts/python.exe
mode=${1:-all}
case "$mode" in all|--data-checks|--python|--site) ;; *) sed -n '2,8p' "$0" >&2; exit 2 ;; esac

if [ "$mode" = all ] || [ "$mode" = --data-checks ]; then
  echo "== content checks"
  "$python" scripts/check_content.py
  "$python" scripts/teach_lint.py > /dev/null  # its per-lesson report is long; errors still fail (exit 1)
  "$python" scripts/slugs.py --check
  "$python" scripts/coverage.py --check
  "$python" scripts/public_scan.py
fi
if [ "$mode" = all ] || [ "$mode" = --python ]; then
  echo "== the Python suite (unit, API, security and content tests)"
  workers=${TEST_WORKERS:-$(( $(nproc 2>/dev/null || echo 4) < 4 ? $(nproc 2>/dev/null || echo 4) : 4 ))}
  PYTHONWARNDEFAULTENCODING=1 "$python" -m pytest -q -p no:cacheprovider tests --ignore=tests/e2e -n "$workers"
fi
if [ "$mode" = all ] || [ "$mode" = --site ]; then
  echo "== frontend tests, type check and build; static export; public scan and internal links of the export"
  (cd frontend && npm ci --no-audit --no-fund && npm test && npm run build)
  "$python" scripts/export_static.py
  "$python" scripts/public_scan.py frontend/dist
  "$python" scripts/check_site.py frontend/dist
fi
