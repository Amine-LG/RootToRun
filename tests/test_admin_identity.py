"""Administration lessons are recorded as the cluster administrator learners will use on OpenShift Local, kubeadmin:
not the certificate identity system:admin, which the recorder keeps for rollback and health checks only."""
import json

import pytest

from academy import config, curriculum

LESSONS = curriculum.load()["lessons"]
ADMIN = sorted(lid for lid, l in LESSONS.items() if l.record_on == "cluster-admin" and l.commands)


@pytest.mark.parametrize("lid", ADMIN)
def test_the_administrator_in_every_administration_recording_is_kubeadmin(lid):
    rec = json.loads((config.ROOT / "content" / "recordings" / f"lesson.{lid}.json").read_text(encoding="utf-8"))
    admin_entries = [e for e in rec["entries"] if e.get("as") == "admin"]
    if not admin_entries:
        pytest.skip("no administrator command")
    assert rec["cluster"].get("admin") == "kubeadmin"
    assert {e.get("identity") for e in admin_entries} == {"kubeadmin"}


def test_no_lesson_text_is_left_as_a_placeholder():
    for lid, l in LESSONS.items():
        for st in l.flow or []:
            for field in ("body", "notice", "then"):
                assert "NOTICE-PENDING" not in (getattr(st, field, "") or ""), (lid, st.id, field)
