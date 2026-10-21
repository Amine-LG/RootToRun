"""Workload models: the Probes panel at the time cursor is readable on a wide page (its boxes do not overlap) and a
pod waiting in CrashLoopBackOff is still listed in the EndpointSlice with ready: false; the Scheduler model binds a
pod to the only feasible node without scoring, as kube-scheduler does. Static site, no cluster."""
from playwright.sync_api import expect


def set_time(page, t):
    page.evaluate(
        "t => { const r = document.querySelector('.sim-scrub input[type=range]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(r, String(t)); r.dispatchEvent(new Event('input', {bubbles: true})) }",
        t,
    )


# every box of the "At t" panel: the probes, the database and pod boxes, the Service and EndpointSlice nodes
OVERLAPS = """() => {
  const pn = document.querySelector('[data-testid=probes-now]');
  const boxes = [...pn.querySelectorAll('.pn-probe, .pn-box, .pn-node')].map((e) => [e.className, e.getBoundingClientRect()]);
  const out = [];
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const [a, ra] = boxes[i], [b, rb] = boxes[j];
      if (b.includes('pn-node') && a.includes('pn-node')) continue;  // Service and EndpointSlice share a row
      const x = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
      const y = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
      if (x > 1 && y > 1) out.push(`${a} overlaps ${b}`);
    }
  }
  const panel = pn.getBoundingClientRect();
  for (const [a, r] of boxes) if (r.right > panel.right + 1) out.push(`${a} sticks out of the panel`);
  return out;
}"""


def test_probes_panel_boxes_do_not_overlap_beside_the_timeline(page, static_site):
    for width in (1440, 1360, 1024, 390):
        page.set_viewport_size({"width": width, "height": 900})
        page.goto(static_site.rstrip("/") + "/studio/model/probes")
        page.locator(".sim-root").wait_for()
        if page.get_by_test_id("sim-skip").count():  # the prediction is skipped once, then remembered
            page.get_by_test_id("sim-skip").click()
        set_time(page, 85)  # /ready fails during the database outage: the longest texts
        expect(page.get_by_test_id("now-readiness")).to_contain_text("503 · database down")
        assert page.evaluate(OVERLAPS) == [], width


def test_a_pod_in_crashloopbackoff_stays_in_the_endpointslice_as_not_ready(page, static_site):
    page.goto(static_site.rstrip("/") + "/studio/model/probes")
    page.get_by_test_id("sim-skip").click()
    page.get_by_label("Scenario").select_option("crash")
    now = page.get_by_test_id("probes-now")
    set_time(page, 10)  # exits at 3s, restarted at once, exits again at 7s: back-off 10s until 17s
    expect(now).to_contain_text("CrashLoopBackOff")
    expect(now).to_contain_text("ready: false")
    expect(now).not_to_contain_text("ready: none")
    expect(now).to_contain_text("no traffic: no running container")


def test_scheduler_binds_the_only_feasible_node_without_scoring(page, static_site):
    page.goto(static_site.rstrip("/") + "/studio/model/scheduler")
    page.get_by_test_id("sim-skip").click()
    page.get_by_label("nodeSelector").select_option("disktype=ssd")  # worker-c1 also has ssd but keeps its taint
    root = page.locator(".sim-root")
    expect(root.locator(".sim-banner")).to_contain_text("Bound to worker-a1")
    expect(root.locator(".sim-banner")).to_contain_text("only node that passed every filter")
    expect(root.locator('.sim-node[aria-label^="worker-a1"] .sim-scores')).to_have_count(0)
    expect(root.locator(".sim-note").last).to_contain_text("only one node passed the filters")
    # two feasible nodes: scored as usual
    page.get_by_label("nodeSelector").select_option("")
    expect(root.locator('.sim-node[aria-label^="worker-b1"] .sim-scores')).to_have_count(1)
