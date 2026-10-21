"""Commands a learner can read and understand (lib/cmdfmt.ts, components/Understand.tsx, components/Prereqs.tsx).

- A crowded recorded command (several commands joined by `;`) is shown one command per line, without widening the
  page on a phone; a `for … do … done` loop stays one command.
- Copy gives exactly the command as it was recorded, whatever the display looks like.
- "Understand this command" opens and closes from the keyboard and reports its state.
- The prerequisite line of a lesson links to the right part of the setup guide.
"""
import json
import re
import shutil
import subprocess
import sys

import pytest
from playwright.sync_api import expect

from academy import curriculum
from addresses import lab_url, lesson_url

CUR = curriculum.load("en")


def run_of(lid: str, sid: str) -> str:
    return next(s.run for s in CUR["lessons"][lid].flow if s.id == sid)


TLS_POD = run_of("d.routes-tls", "tls-pod")
MAKE_SECRET = run_of("o3.ingress-gateway", "make-secret")
STACK_API = run_of("ct.podman-stack", "api")
LOOP = run_of("b.pod-lifecycle", "show-termination")

# records what the page asks the clipboard to hold, then lets the browser do it as usual
RECORD_COPY = """
  window.__copied = [];
  const c = navigator.clipboard;
  if (c && c.writeText) { const w = c.writeText.bind(c); c.writeText = (s) => { window.__copied.push(s); return w(s) } }
"""


def open_lesson(pg, site, lid):
    pg.goto(site.rstrip("/") + lesson_url(lid))
    pg.wait_for_selector(".demo-term")  # every activity of a lesson is on its one page


NEEDLE = {TLS_POD: "oc annotate service", MAKE_SECRET: "host=secure-", STACK_API: "--name academy-ct3-api", LOOP: "start=$(date"}


def demo(pg, cmd):
    """The recorded-command figure of `cmd`, found by a distinctive piece of one of its displayed lines."""
    return pg.locator("[data-testid=demo]", has=pg.locator(".demo-cmd", has_text=NEEDLE[cmd])).first


def shown_lines(fig):
    return [ln.inner_text().rstrip("\n") for ln in fig.locator(".demo-cmd").all()]


@pytest.fixture
def phone(browser):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    ctx.add_init_script(RECORD_COPY)
    pg = ctx.new_page()
    yield pg
    ctx.close()


def test_crowded_command_is_one_command_per_line_on_a_phone(phone, static_site):
    open_lesson(phone, static_site, "d.routes-tls")
    fig = demo(phone, TLS_POD)
    fig.scroll_into_view_if_needed()
    lines = shown_lines(fig)
    starts = [ln for ln in lines if ln.startswith("$ ")]  # each new command gets a prompt; continued lines get "> "
    assert [s.split()[1:3] for s in starts] == [["oc", "annotate"], ["sleep", "3"], ["oc", "get"], ["oc", "set"], ["oc", "set"], ["oc", "rollout"]]
    assert all(ln.startswith(("$ ", ">")) for ln in lines)
    assert not any(";" in ln for ln in lines)  # no command separator left on screen
    assert phone.evaluate("document.documentElement.scrollWidth") <= 390


def test_a_loop_is_not_split(phone, static_site):
    open_lesson(phone, static_site, "b.pod-lifecycle")
    lines = shown_lines(demo(phone, LOOP))
    assert lines[0].startswith("$ for app in stubborn polite;")
    # the whole loop is one command: every later line continues it ("> "), none starts a new one ("$ ")
    assert len(lines) > 1 and all(ln.startswith(">") for ln in lines[1:])
    assert lines[-1].rstrip().endswith("done")


@pytest.mark.parametrize("lid,cmd", [("d.routes-tls", TLS_POD), ("o3.ingress-gateway", MAKE_SECRET), ("ct.podman-stack", STACK_API)],
                         ids=["semicolons", "quotes-and-pipes", "nested-quotes"])
def test_copy_gives_the_recorded_command(phone, static_site, lid, cmd):
    open_lesson(phone, static_site, lid)
    fig = demo(phone, cmd)
    assert len(shown_lines(fig)) > 1  # the display differs from the recorded single line
    fig.locator(".copy-btn").click()
    expect(fig.locator("[role=status]")).to_have_text("Copied")
    assert phone.evaluate("window.__copied") == [cmd]


# The Clipboard API refuses (an insecure origin, a denied permission): the page falls back to selecting the text in a
# hidden field and asking the browser to copy it. What that copies is observed in the browser's own `copy` event: the
# selection it is about to put on the clipboard.
REFUSE_CLIPBOARD = """
  window.__copied = [];
  if (navigator.clipboard) navigator.clipboard.writeText = () => Promise.reject(new DOMException('denied', 'NotAllowedError'));
  document.addEventListener('copy', () => {
    const a = document.activeElement;
    window.__copied.push(a && 'value' in a ? a.value.slice(a.selectionStart, a.selectionEnd) : String(getSelection()));
  }, true);
"""


def test_copy_falls_back_when_the_clipboard_api_refuses(browser, static_site):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    ctx.add_init_script(REFUSE_CLIPBOARD)
    pg = ctx.new_page()
    open_lesson(pg, static_site, "o3.ingress-gateway")
    fig = demo(pg, MAKE_SECRET)
    fig.locator(".copy-btn").click()
    expect(fig.locator("[role=status]")).to_have_text("Copied")
    assert pg.evaluate("window.__copied") == [MAKE_SECRET]  # the recorded line, not the display
    ctx.close()


def test_copy_says_so_when_nothing_could_be_copied(browser, static_site):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    ctx.add_init_script(REFUSE_CLIPBOARD + "document.execCommand = () => false;")  # the fallback fails too
    pg = ctx.new_page()
    open_lesson(pg, static_site, "o3.ingress-gateway")
    fig = demo(pg, MAKE_SECRET)
    fig.locator(".copy-btn").click()
    status = fig.locator("[role=status]")
    expect(status).to_have_text("Could not copy")
    expect(fig.get_by_text("Copied", exact=True)).to_have_count(0)  # never claims a copy that did not happen
    assert pg.evaluate("window.__copied") == []
    ctx.close()


CHROME_CHECK = """
import json, sys
from playwright.sync_api import sync_playwright
site, cases = sys.argv[1], json.loads(sys.argv[2])
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    pg = b.new_context(viewport={"width": 390, "height": 844}, permissions=["clipboard-read", "clipboard-write"]).new_page()
    out = []
    for path, needle in cases:
        pg.goto(site + path)
        pg.wait_for_selector(".demo-term")
        fig = pg.locator("[data-testid=demo]", has=pg.locator(".demo-cmd", has_text=needle)).first
        fig.locator(".copy-btn").click()
        fig.locator("[role=status]", has_text="Copied").wait_for(state="attached")  # written before it is announced
        out.append(pg.evaluate("navigator.clipboard.readText()"))
    b.close()
print(json.dumps(out))
"""


def test_real_clipboard_holds_the_recorded_command(static_site):
    """The same, read back from the system clipboard of a real Chrome (skipped where Chrome is not installed)."""
    if not (shutil.which("google-chrome") or shutil.which("google-chrome-stable")):
        pytest.skip("Chrome is not installed")
    cases = [(lesson_url("o3.ingress-gateway"), NEEDLE[MAKE_SECRET]), (lesson_url("b.pod-lifecycle"), NEEDLE[LOOP]), (lesson_url("ct.podman-stack"), NEEDLE[STACK_API])]
    r = subprocess.run([sys.executable, "-c", CHROME_CHECK, static_site.rstrip("/"), json.dumps(cases)], capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [MAKE_SECRET, LOOP, STACK_API]


def test_understand_this_command_works_from_the_keyboard(page, static_site):
    open_lesson(page, static_site, "d.routes-tls")
    box = page.locator(".flow-show", has=demo(page, TLS_POD)).get_by_test_id("understand")
    toggle = box.get_by_role("button", name="Understand this command")
    body = box.get_by_test_id("understand-body")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(body).to_be_hidden()
    assert toggle.get_attribute("aria-controls") == body.get_attribute("id")
    toggle.focus()
    page.keyboard.press("Enter")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(body).to_be_visible()
    expect(body).to_contain_text("--sub-path=tls.crt")  # each explained option is shown as written in the command
    # ...next to what it means, as authored in the lesson (Markdown code marks are shown as code, not as backticks)
    part = next(p for p in understand_of("d.routes-tls", "tls-pod").parts if "--sub-path=tls.crt" in p.text)
    pair = body.locator(".understand-parts > div", has=page.locator("dt", has_text=part.text))
    expect(pair.locator("dd")).to_have_text(part.means.replace("`", ""))
    expect(body.get_by_role("link", name="OpenShift 4.21: Service serving certificate secrets")).to_be_visible()
    page.keyboard.press("Space")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(body).to_be_hidden()


def understand_of(lid: str, sid: str):
    return next(s.understand for s in CUR["lessons"][lid].flow if s.id == sid)


def test_a_solved_try_step_explains_its_command(page, static_site):
    """A typed command's explanation comes with its result: absent before the learner succeeds, then closed, opened
    on request, each part next to its meaning."""
    page.goto(static_site.rstrip("/") + lesson_url("f0.statefulsets"))
    t = page.locator("[data-step='try:scale-down']")
    t.scroll_into_view_if_needed()
    expect(t.get_by_test_id("understand")).to_have_count(0)
    step = next(s for s in CUR["lessons"]["f0.statefulsets"].flow if s.id == "scale-down")
    t.get_by_test_id("try-input").fill(step.accept[0])
    t.get_by_test_id("try-check").click()
    expect(t.get_by_test_id("try-status")).to_be_visible()
    toggle = t.get_by_test_id("understand-toggle")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    body = t.get_by_test_id("understand-body")
    for part in understand_of("f0.statefulsets", "scale-down").parts:
        pair = body.locator(".understand-parts > div", has=page.locator("dt", has_text=part.text))
        expect(pair.locator("dd")).to_have_text(part.means.replace("`", ""))
    expect(body.locator("dd", has_text="Waits until both objects are deleted.")).to_have_count(1)  # one known by heart


def test_prerequisites_link_to_the_setup_guide(page, static_site):
    page.goto(static_site.rstrip("/") + lesson_url("ct.podman-stack"))
    line = page.get_by_test_id("prereqs")
    expect(line).to_contain_text("Nothing runs on this website")
    link = line.get_by_role("link", name="Podman")
    expect(link).to_have_attribute("href", "/setup#podman")
    expect(line.get_by_role("link")).to_have_count(1)  # a host lesson: no cluster needed
    link.click()
    tool = page.locator("#podman")
    expect(tool).to_be_visible()
    expect(tool).to_contain_text("podman --version")
    expect(tool.get_by_role("link", name="Podman installation instructions")).to_have_attribute("href", "https://podman.io/docs/installation")
    # an administration lesson also names the cluster it needs
    page.goto(static_site.rstrip("/") + lesson_url("e.storage"))
    expect(page.get_by_test_id("prereqs").get_by_role("link", name="a disposable cluster you administer")).to_have_attribute("href", "/setup#cluster")
    # the registry lesson needs Skopeo (it runs `skopeo inspect`), and its link reaches Skopeo's setup card
    page.goto(static_site.rstrip("/") + lesson_url("ct.registries-skopeo"))
    skopeo = page.get_by_test_id("prereqs").get_by_role("link", name="Skopeo")
    expect(skopeo).to_have_attribute("href", "/setup#skopeo")
    skopeo.click()
    expect(page.locator("#skopeo")).to_be_visible()
    expect(page.locator("#skopeo")).to_contain_text("skopeo --version")


def test_a_lab_links_its_tools_to_the_setup_guide(page, static_site):
    """A guided lab names the command-line tools its commands use (this one runs `oc` and `helm`) and the cluster."""
    page.goto(static_site.rstrip("/") + lab_url("lab.kustomize-helm"))
    line = page.get_by_test_id("prereqs")
    expect(line.get_by_role("link")).to_have_text(["oc, the OpenShift CLI", "Helm", re.compile("cluster")])
    helm = line.get_by_role("link", name="Helm")
    expect(helm).to_have_attribute("href", "/setup#helm")
    helm.click()
    expect(page).to_have_url(re.compile(r"/setup#helm$"))
    expect(page.locator("#helm")).to_be_in_viewport()
    expect(page.locator("#helm")).to_contain_text("helm version")


def test_setup_page_is_a_real_page(page, static_site):
    page.goto(static_site.rstrip("/") + "/setup")
    expect(page.get_by_role("heading", level=1)).to_have_text("Set up your own practice")
    assert page.title().startswith("Set up your own practice")
    data = json.loads(page.request.get(static_site + "data/en/curriculum.json").text())
    expect(page.get_by_test_id("setup-tool")).to_have_count(len(data["tools"]) + 1)  # every tool, and the cluster
    # the tools the course's commands use, named here rather than taken from the catalogue that renders them
    shown = page.get_by_test_id("setup-tool").evaluate_all("cards => cards.map(c => c.id)")
    assert {"linux", "podman", "skopeo", "jq", "curl", "kubectl", "oc", "openssl", "htpasswd", "helm", "git", "cosign", "cluster"} <= set(shown), shown

