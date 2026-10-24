#!/usr/bin/env bash
# CI (Linux): install a Playwright browser for the browser tests, and its system libraries only if the runner lacks
# them.
#   scripts/ci_browser.sh firefox|chromium
# `playwright install --with-deps` runs apt in every job: about 50 MB of fonts and media libraries, from a mirror that
# was slow on a third of the jobs (6 to 23 minutes instead of 15 seconds, the whole CI waiting for the slowest one).
# The site uses its own web fonts and no audio or video, and GitHub's Ubuntu runners already have the libraries the
# browsers need to start. Playwright refuses to start a browser whose libraries are missing, so the check below is a
# real start: if it fails, the libraries are installed with apt as before. The tests run in both cases.
set -euo pipefail
browser=${1:?usage: scripts/ci_browser.sh firefox|chromium}
python=.venv/bin/python

"$python" -m playwright install "$browser"
if "$python" - "$browser" <<'PY'
import sys

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = getattr(p, sys.argv[1]).launch()
    page = browser.new_page()
    page.set_content("<p>ready</p>")
    assert page.inner_text("p") == "ready"
    browser.close()
PY
then
  echo "$browser starts with the runner's own libraries: nothing installed with apt"
else
  echo "::notice title=Browser libraries::$browser does not start on this runner as it is: installing its libraries with apt"
  "$python" -m playwright install-deps "$browser"
fi
