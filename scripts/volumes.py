#!/usr/bin/env python3
"""Volumes left behind by lab projects on a StorageClass with reclaimPolicy Retain (needs a cluster-admin identity).

    .venv/bin/python scripts/volumes.py list             # every volume the ledger recorded, and its state
    .venv/bin/python scripts/volumes.py reclaim --yes    # reclaim the Released ones (reclaimPolicy -> Delete)

Only volumes the cleanup ledger recorded while a lab ran qualify, and only while their claimRef still names the claim
UID recorded then (see backend/academy/ledger.py). A volume is never adopted because its name or namespace looks
familiar: that is not proof of ownership.
"""
import json
import sys

sys.path.insert(0, "backend")
from academy import kube, ledger  # noqa: E402

cmd = (sys.argv[1:] or ["list"])[0]
runs = ledger.runs(("active", "cleaning", "blocked", "clean"))
if cmd == "list":
    print(json.dumps([{"run": r["id"], "volumes": ledger.volumes(r["id"])} for r in runs if ledger.volumes(r["id"])], indent=1))
elif cmd == "reclaim":
    if not kube.whoami("admin").get("connected"):
        raise SystemExit("connect the admin identity first (Connections page)")
    if "--yes" not in sys.argv:
        raise SystemExit("dry run: add --yes to reclaim the Released volumes listed by `list`")
    for r in runs:
        if any(v["phase"] == "released-needs-admin" for v in ledger.volumes(r["id"])):
            print(r["id"], json.dumps(ledger.reclaim_volumes(r["id"])))
else:
    raise SystemExit(__doc__)
