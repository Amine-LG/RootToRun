"""The NetworkPolicy lesson must not teach that a namespaceSelector alone matches host-network routers. OpenShift 4.21
network security docs: "Using the namespaceSelector field without the podSelector field set to {} will not include
hostNetwork pods"; the documented allow-from-router policy has both. The recorded rule (namespaceSelector only) worked
on the one-node training cluster because traffic from a pod's own node is never blocked."""
import yaml

from academy import config

LESSON = "d.networkpolicy-ovn"


def lesson():
    for item in yaml.safe_load((config.ROOT / "content/en/lessons/b4-network.yaml").read_text(encoding="utf-8")):
        if isinstance(item, dict) and item.get("id") == LESSON:
            return item
    raise AssertionError(LESSON)


def step(les, sid):
    return next(s for s in les["flow"] if s.get("id") == sid)


def test_the_correct_choice_names_podselector_for_host_network_routers():
    choice = step(lesson(), "why-policy-group")["choices"][0]
    assert "podSelector: {}" in choice["why"] and "only the ordinary pods" in choice["why"]


def test_the_documented_form_is_shown_as_an_example_with_podselector_in_the_same_entry():
    ex = step(lesson(), "router-rule-host-network")
    assert ex["origin"] == "example"
    entry = yaml.safe_load(ex["code"])["spec"]["ingress"][0]["from"][0]
    assert entry["podSelector"] == {} and "namespaceSelector" in entry  # one entry: AND, not two peers


def test_the_apply_notice_and_review_no_longer_overclaim():
    les = lesson()
    assert "this rule is what keeps it working" not in step(les, "apply-allow-router")["notice"]
    card = next(c for c in les["review"] if isinstance(c, dict) and "default-deny" in c.get("q", ""))
    assert "podSelector {}" in card["a"]
