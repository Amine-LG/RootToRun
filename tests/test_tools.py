"""The setup guide's data: the tool list (content/en/tools.yaml) and which lessons and labs use which tool, derived
from their commands (academy/tools.py)."""
import pytest

from academy import curriculum, labs, tools

TOOLS = tools.load("en")
NAMES = [c for t in TOOLS for c in t.commands]


def test_tool_list_is_complete_and_linked():
    ids = [t.id for t in TOOLS]
    assert len(ids) == len(set(ids)) and "oc" in ids and "podman" in ids
    for t in TOOLS:
        assert t.install and all(link.url.startswith("https://") for link in t.install)
        assert t.verify.split()[0] in {*t.commands, "bash", "command"}, t.id  # the check runs the tool itself


@pytest.mark.parametrize("cmd,expected", [
    ("oc get pods", {"oc"}),
    ("podman run --rm quay.io/x/busybox curl -s http://a/", {"podman"}),  # curl runs in the container
    ("oc exec deploy/web -- curl -s localhost:8080", {"oc"}),
    ("oc debug node/crc -- chroot /host crictl images", {"oc"}),
    ("host=$(oc project -q); curl -s https://$host/", {"oc", "curl"}),
    ("sh -c 'curl -s x; jq .'", set()),  # single-quoted text is not run by the learner's shell
    ("kubectl get pods -o json | jq '.items | length'", {"kubectl", "jq"}),
    ("sudo podman ps", {"podman"}),
    ("timeout 5 curl -s http://x/ || echo failed", {"curl"}),
    ('echo "oc is the client"', set()),
    ("for i in 1 2; do oc get pods; done", {"oc"}),
    ("X=1 helm template demo chart", {"helm"}),
    ("oc-mirror --help; ./oc version", set()),  # other programs whose names only start or end with a tool's name
])
def test_programs_in_command_position(cmd, expected):
    assert tools.programs(cmd, NAMES) == expected


def test_every_lesson_and_lab_names_what_it_uses():
    cur = curriculum.load("en")
    for l in cur["lessons"].values():
        if any(tools.lesson_commands(l)):
            assert tools.lesson_tools(l), f"{l.id}: commands, but no tool found"
    for lab in labs.load("en").values():
        assert "oc" in tools.used(tools.lab_commands(lab)), lab.id
    assert "podman" in tools.lesson_tools(cur["lessons"]["ct.podman-stack"])
    assert tools.lesson_tools(cur["lessons"]["lx.first-steps"]) == ["linux"]


def test_curriculum_export_carries_the_tools(monkeypatch):
    monkeypatch.setenv("ACADEMY_CLUSTER", "off")
    from academy import main
    c = main.get_curriculum("en")
    assert [t["id"] for t in c["tools"]] == [t.id for t in TOOLS]
    assert all("tools" in l and l["record_on"] in ("host", "cluster", "cluster-admin") for l in c["lessons"].values())
    assert all("tools" in lab for lab in c["labs"].values())
    # named here, from what these pages' commands run (not from the code that derives them): the Helm lab runs `oc`
    # and `helm`; an incident runs `oc`; the registry lesson runs `podman`, `skopeo` and `jq`
    assert c["labs"]["lab.kustomize-helm"]["tools"] == ["oc", "helm"]
    assert c["labs"]["inc.dns-typo"]["tools"] == ["oc"]
    assert c["lessons"]["ct.registries-skopeo"]["tools"] == ["podman", "skopeo", "jq"]


def test_the_setup_guide_covers_every_tool_the_course_uses():
    """The catalogue may grow; it must not lose a tool whose commands the course teaches."""
    assert {"linux", "podman", "skopeo", "jq", "curl", "kubectl", "oc", "openssl", "htpasswd", "helm", "git", "cosign"} <= {t.id for t in TOOLS}
