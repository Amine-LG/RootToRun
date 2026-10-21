"""Every incident decides which of its checks are monitoring-level evidence (shown before the answer), and the list
names real checks. The list is prose: it is outside the recording fingerprint, so recordings stay current."""
from academy import labs


def test_every_incident_lists_its_symptom_checks():
    incidents = [l for l in labs.load(None).values() if l.kind == "incident"]
    assert len(incidents) >= 16
    for lab in incidents:
        ids = {c.id for c in lab.checks}
        assert lab.symptom_checks, f"{lab.id}: no symptom_checks"
        assert set(lab.symptom_checks) <= ids, lab.id


def test_the_symptom_list_is_outside_the_recording_fingerprint():
    lab = labs.load(None)["inc.imagepull"]
    assert labs.lab_hash(lab) == labs.lab_hash(lab.model_copy(update={"symptom_checks": []}))
