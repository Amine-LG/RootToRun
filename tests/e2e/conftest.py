"""Browser tests. The static site is exported to a temporary directory and served with Python's http.server,
exactly as a public static host would serve it (no API, no cluster)."""
import functools
import http.server
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time

import pytest

from academy import config

DIST = config.ROOT / "frontend" / "dist"


def pytest_addoption(parser):
    parser.addoption("--shard", default=None, metavar="I/N",
                     help="run only the I-th of N parts of the browser tests (1-based; every test is in exactly one part)")


def pytest_collection_modifyitems(config, items):
    """--shard I/N keeps every N-th test, starting with the I-th, in collection order: the CI runs the N parts in
    parallel jobs. Parametrised groups of a long test are spread over the parts."""
    shard = config.getoption("--shard")
    if not shard:
        return
    try:
        i, n = (int(x) for x in shard.split("/"))
    except ValueError:
        raise pytest.UsageError(f"--shard {shard}: expected I/N, for example 2/3") from None
    if not 1 <= i <= n:
        raise pytest.UsageError(f"--shard {shard}: I must be between 1 and N")
    keep = [t for k, t in enumerate(items) if k % n == i - 1]
    config.hook.pytest_deselected(items=[t for k, t in enumerate(items) if k % n != i - 1])
    items[:] = keep


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="session")
def static_site(tmp_path_factory):
    # ACADEMY_E2E_SITE=http://127.0.0.1:<port>/ runs the same tests against a site that is already served, for example
    # the production image (Containerfile), with its real nginx rules, headers and Content-Security-Policy.
    import os
    if os.environ.get("ACADEMY_E2E_SITE"):
        yield os.environ["ACADEMY_E2E_SITE"].rstrip("/") + "/"
        return
    if not (DIST / "index.html").exists():
        pytest.skip("frontend not built (cd frontend && npm run build)")
    root = tmp_path_factory.mktemp("site")
    shutil.copytree(DIST, root, dirs_exist_ok=True)
    r = subprocess.run([sys.executable, str(config.ROOT / "scripts" / "export_static.py"), "--out", str(root)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    port = free_port()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}/"
    srv.shutdown()


@pytest.fixture(scope="session")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    import os
    with pw.sync_playwright() as p:
        b = getattr(p, os.environ.get("E2E_BROWSER", "firefox")).launch()  # E2E_BROWSER=chromium for a second engine
        yield b
        b.close()


def wait_true(page, expression, arg=None, timeout=30_000):
    """Wait until a JavaScript expression is truthy. page.wait_for_function compiles a string predicate with eval() in
    the page, which the production image's Content-Security-Policy rightly refuses; page.evaluate needs no eval."""
    deadline = time.monotonic() + timeout / 1000
    while not (page.evaluate(expression) if arg is None else page.evaluate(expression, arg)):
        if time.monotonic() > deadline:
            from playwright.sync_api import TimeoutError as PlaywrightTimeout
            raise PlaywrightTimeout(f"timed out after {timeout} ms waiting for: {expression}")
        page.wait_for_timeout(50)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    """Each phase's report on the test item (item.rep_setup, item.rep_call), for _trace_failures."""
    report = yield
    setattr(item, "rep_" + report.when, report)
    return report


@pytest.fixture(autouse=True)
def _trace_failures(request, monkeypatch):
    """E2E_ARTIFACTS=<dir> (the CI sets it) records a Playwright trace of every browser context a test opens
    (screenshots, DOM snapshots, sources) and keeps it in <dir> only when the test failed: open it with
    `python -m playwright show-trace <file>` or at trace.playwright.dev. Unset (the default), nothing changes.
    A passing test's trace is discarded without being written, unless the test closed the context itself before its
    result was known; such a trace is written, then removed when the test passes."""
    out = os.environ.get("E2E_ARTIFACTS")
    if not out:
        yield
        return
    from playwright.sync_api import Browser, BrowserContext

    node = request.node
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", node.nodeid.replace(".py::", "-"))[:150]
    traced, owned, written = [], [], []

    def failed():
        return any(getattr(getattr(node, "rep_" + when, None), "failed", False) for when in ("setup", "call"))

    def stop(ctx):
        if not ctx.__dict__.pop("_e2e_traced", False):
            return
        try:
            if failed() or not hasattr(node, "rep_call"):  # failed, or still running: keep it for now
                path = os.path.join(out, f"{stem}-{len(written) + 1}.zip")
                ctx.tracing.stop(path=path)
                written.append(path)
            else:
                ctx.tracing.stop()
        except Exception as e:  # a trace that cannot be saved (the browser has gone) never hides the test's result
            print(f"trace of {node.nodeid} not saved: {e}", file=sys.stderr)

    new_context, close = Browser.new_context, BrowserContext.close

    def traced_new_context(self, *args, **kwargs):
        ctx = new_context(self, *args, **kwargs)
        ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
        ctx._e2e_traced = True
        traced.append(ctx)
        return ctx

    def traced_new_page(self, **kwargs):  # Browser.new_page's own context bypasses new_context above
        ctx = self.new_context(**kwargs)
        owned.append(ctx)
        return ctx.new_page()

    def traced_close(self, *args, **kwargs):
        stop(self)
        return close(self, *args, **kwargs)

    os.makedirs(out, exist_ok=True)
    monkeypatch.setattr(Browser, "new_context", traced_new_context)
    monkeypatch.setattr(Browser, "new_page", traced_new_page)
    monkeypatch.setattr(BrowserContext, "close", traced_close)
    yield
    for ctx in traced:  # contexts left open, for example by an assertion that failed before ctx.close()
        stop(ctx)
    for ctx in owned:  # page.close() would have closed the context Browser.new_page makes; it is closed here
        close(ctx)
    if not failed():
        for path in written:
            if os.path.exists(path):
                os.remove(path)


@pytest.fixture(autouse=True)
def _injected_test_scripts(request, monkeypatch, _trace_failures):  # after _trace_failures: it wraps new_context
    """A module that injects a test script (axe-core) with a <script> tag sets INJECTS_SCRIPTS: against a served site
    its browser contexts bypass the site's Content-Security-Policy, which rightly refuses that tag. Every other test
    runs under the real policy, and a violation fails it like any console error."""
    if os.environ.get("ACADEMY_E2E_SITE") and getattr(request.module, "INJECTS_SCRIPTS", False):
        b = request.getfixturevalue("browser")
        new_context = b.new_context
        monkeypatch.setattr(b, "new_context", lambda **kw: new_context(**{"bypass_csp": True, **kw}))


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1360, "height": 900})
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    # Firefox logs a font fetch that a navigation cancelled (NS_BINDING_ABORTED, 2152398850) as an error; that is the
    # browser abandoning a download, not an application error. Every other console error still fails a test.
    # Chromium also logs the static site's expected 404 for the API probe (/api/meta: a static host has no API).
    def on_console(m):
        if m.type != "error" or "status=2152398850" in m.text:
            return
        if m.text.startswith("Failed to load resource") and "/api/" in (m.location or {}).get("url", ""):
            return
        pg.errors.append(m.text + f" [{(m.location or {}).get('url', '')}]")
    pg.on("console", on_console)
    yield pg
    ctx.close()


@pytest.fixture(scope="session")
def practice_server():
    """The real server with ACADEMY_CLUSTER=off: it must behave like the static site and never reach a cluster."""
    import os
    import time
    import urllib.request

    port = free_port()
    env = {**os.environ, "ACADEMY_CLUSTER": "off"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "academy.main:app", "--app-dir", "backend",
                             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"], cwd=config.ROOT, env=env)
    url = f"http://127.0.0.1:{port}/"
    for _ in range(60):
        try:
            urllib.request.urlopen(url + "api/meta", timeout=1)
            break
        except OSError:
            time.sleep(0.25)
    # warm the caches the first curriculum request builds (seconds on a cold start); fails clearly if the server is down
    try:
        urllib.request.urlopen(url + "api/curriculum", timeout=60)
    except BaseException:
        proc.terminate()
        proc.wait(5)
        raise
    yield url
    proc.terminate()
    proc.wait(5)


@pytest.fixture(scope="session")
def cluster_server():
    """Opt-in: the running local academy (./run.sh) connected to a disposable cluster."""
    import os

    if os.environ.get("ACADEMY_E2E_CLUSTER") != "1":
        pytest.skip("set ACADEMY_E2E_CLUSTER=1 to run live-cluster browser tests against ./run.sh")
    return os.environ.get("ACADEMY_URL", "http://127.0.0.1:8768/")
