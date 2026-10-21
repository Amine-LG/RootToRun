"""My cluster → Connections, in the order it works: connect the learner, approve the cluster, then (optionally) connect
kubeadmin. The real server (without a cluster) serves the app; only the cluster endpoints are simulated here, with the
same rules as the backend (approval needs a connected learner and the typed API host; kubeadmin needs an approved
cluster). The point: connecting the learner shows the approval at once, without reloading the page."""
import json

from playwright.sync_api import expect

HOST, API = "api.crc.testing", "https://api.crc.testing:6443"


def simulate_cluster(page):
    s = {"learner": False, "approved": False, "admin": False}

    def ident(on, user):
        return {"connected": True, "user": user} if on else {"connected": False, "reason": "not connected"}

    def env():
        if not s["learner"]:
            return {"class": "read-only", "connected": False, "reason": "no learner account is connected: connect it first (My cluster → Connections, step 1)"}
        out = {"connected": True, "api": API, "host": HOST, "crc": True, "tls_verified": True, "fingerprint": "f"}
        return {**out, "class": "training", "reason": "approved"} if s["approved"] else {**out, "class": "read-only", "reason": "not approved for training labs yet"}

    def handle(route):
        req, path = route.request, route.request.url.split("/api/", 1)[1].split("?")[0]
        body = json.loads(req.post_data or "{}") if req.method == "POST" else {}
        if path == "meta":
            return route.fulfill(json={"mode": "cluster", "langs": ["en"], "default_lang": "en", "helm": False, "authoring": False, "accounts": False, "repo_url": "", "version": "test", "commit": "test"})
        if path == "status":
            return route.fulfill(json={"mode": "cluster", "oc": True, "api": API, "content_errors": [],
                                       "crc": {"crcStatus": "Running", "openshiftStatus": "Running", "openshiftVersion": "4.21.8"},
                                       "identities": {"learner": ident(s["learner"], "developer"), "admin": ident(s["admin"], "kubeadmin"), "reader": ident(False, "")}})
        if path == "environment":
            caps = {"probed": True, "user": "developer", "access": {}, "apis": {}} if s["learner"] else None
            payload = {"env": env(), "identities": {}, **({"capabilities": caps} if caps else {})}
            if s.get("hold_first") and not s.get("held"):  # keep the first answer back, to send it late
                s["held"] = (route, payload)
                return None
            return route.fulfill(json=payload)
        if path == "environment/approve":
            if not s["learner"] or body.get("host", "").strip().lower().rstrip("/") not in (HOST, API):
                return route.fulfill(status=400, json={"detail": f"type the API host {HOST} to approve this cluster"})
            s["approved"] = True
            return route.fulfill(json={"env": env()})
        if path == "disconnect":
            s[body.get("identity")] = False
            return route.fulfill(json={})
        if path == "connect":
            if body.get("identity") == "learner":
                s["learner"] = True
                return route.fulfill(json={"ok": True, "connected": True, "user": "developer"})
            if not s["approved"]:
                return route.fulfill(status=409, json={"detail": "connect the learner account first, then approve this cluster"})
            s["admin"] = True
            return route.fulfill(json={"ok": True, "connected": True, "user": "kubeadmin"})
        if path == "reader/plan":
            return route.fulfill(json={"plan": [], "confirm": "create reader"})
        if path == "cleanup":
            return route.fulfill(json={"runs": [], "leftovers": []})
        return route.continue_()

    page.route("**/api/**", handle)
    return s


def test_connect_then_approve_then_kubeadmin_in_order(page, practice_server):
    s = simulate_cluster(page)
    page.goto(practice_server + "connections")
    # the server's first answers can be slow on a busy runner (Windows CI, two browsers on two CPUs): wait for the page
    page.wait_for_selector("main .page:not(:has(.sk-page))", timeout=60_000)
    steps = page.locator(".cn-steps h3")
    expect(steps).to_have_count(4, timeout=15_000)
    expect(steps.nth(0)).to_contain_text("Your learner account")
    expect(steps.nth(1)).to_contain_text("Approve this cluster")
    expect(steps.nth(2)).to_contain_text("kubeadmin")
    # nothing connected: approval and kubeadmin are closed, and the page says what comes first
    expect(page.get_by_test_id("approve-needs-learner")).to_contain_text("step 1")
    expect(page.get_by_test_id("approve")).to_be_disabled()
    expect(page.get_by_test_id("admin-needs-approval")).to_contain_text("step 2")
    expect(page.get_by_test_id("connect-admin")).to_be_disabled()
    # connecting the learner shows the approval at once, with the exact host to type (no reload)
    page.get_by_test_id("connect-learner").click()
    expect(page.get_by_test_id("approve-host")).to_be_enabled()
    expect(page.get_by_test_id("approve-host")).to_have_attribute("placeholder", HOST)
    expect(page.get_by_test_id("approve-block")).to_contain_text(HOST)
    # a wrong host is refused with the host to type; the address as the page shows it is accepted
    page.get_by_test_id("approve-host").fill("api.other.example")
    page.get_by_test_id("approve").click()
    expect(page.get_by_test_id("env-panel")).to_contain_text(f"type the API host {HOST}")
    assert not s["approved"]
    page.get_by_test_id("approve-host").fill(API)
    page.get_by_test_id("approve").click()
    expect(page.get_by_test_id("env-panel")).to_contain_text("Training cluster (approved)")
    # only now is kubeadmin offered, still behind its typed confirmation
    expect(page.get_by_test_id("admin-needs-approval")).to_have_count(0)
    expect(page.get_by_test_id("connect-admin")).to_be_disabled()
    page.get_by_test_id("admin-phrase").fill("use kubeadmin")
    page.get_by_test_id("connect-admin").click()
    expect(page.get_by_test_id("id-admin")).to_contain_text("cluster-admin session active")
    assert s == {"learner": True, "approved": True, "admin": True}


def test_a_late_answer_never_undoes_a_newer_state_and_logout_hides_approval(page, practice_server):
    s = simulate_cluster(page)
    s["hold_first"] = True  # the page's first environment request ("nothing connected") answers late
    page.goto(practice_server + "connections")
    page.get_by_test_id("connect-learner").click()
    expect(page.get_by_test_id("approve-host")).to_be_enabled()
    route, payload = s["held"]
    route.fulfill(json={"env": {"class": "read-only", "connected": False, "reason": "no learner account is connected"}, "identities": {}})
    page.wait_for_timeout(500)
    expect(page.get_by_test_id("approve-host")).to_be_enabled()  # the stale "nothing connected" answer was ignored
    page.get_by_text("What the learner identity can do here").click()
    expect(page.get_by_test_id("env-panel")).to_contain_text("developer")
    # logging out closes the approval again, and the learner's capabilities are no longer shown
    page.get_by_test_id("id-learner").get_by_role("button", name="Log out").click()
    expect(page.get_by_test_id("approve-needs-learner")).to_be_visible()
    expect(page.get_by_test_id("approve")).to_be_disabled()
    expect(page.get_by_text("What the learner identity can do here")).to_have_count(0)
