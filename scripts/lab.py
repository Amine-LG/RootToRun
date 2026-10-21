"""Command-line equivalent of the lab buttons, for people who prefer a shell (and for reproducible checks).

    .venv/bin/python scripts/lab.py list                    # labs, incidents and challenges, with recorded status
    .venv/bin/python scripts/lab.py start  ch.ship-web-app  # create the project and its starting state
    .venv/bin/python scripts/lab.py grade  ch.ship-web-app  # grade what is on the cluster now (read-only)
    .venv/bin/python scripts/lab.py finish ch.ship-web-app  # remove only what this lab created, and report it

It uses the same identities, cluster approval and functions as the local server: `start` and
`finish` refuse unless the connected cluster was approved for training labs (Connections page), and `grade` only
reads. Exit code: 0 when the grade is verified (or the action succeeded), 1 otherwise.
"""
import sys

sys.path.insert(0, "backend")
from academy import config, environment, labs  # noqa: E402

MARK = {"pass": "✓", "fail": "✗", "error": "!", "skip": "-"}


def need_training() -> None:
    if not config.cluster_enabled():
        raise SystemExit("practice mode (ACADEMY_CLUSTER=off): no cluster actions")
    env = environment.current()
    if env["class"] != "training":
        raise SystemExit(f"this cluster is not approved for training labs: {env.get('reason', '')}")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    all_labs = labs.load()
    if cmd == "list":
        for lid, lab in sorted(all_labs.items(), key=lambda kv: (kv[1].kind, kv[0])):
            rec = labs.recording(lid) or {}
            state = "recorded ok" if rec.get("ok") and rec.get("lab_hash") == labs.lab_hash(lab) else "not verified"
            print(f"{lab.kind:9} {lid:32} {lab.title:34} {state}")
        return 0
    if not rest or rest[0] not in all_labs:
        raise SystemExit(f"unknown or missing id; try: {sys.argv[0]} list")
    lab = all_labs[rest[0]]
    if cmd == "start":
        need_training()
        r = labs.prepare(lab, elevated="--elevated" in rest)
        print("ready:", lab.namespace if r.get("ok") else f"failed: {r.get('reason')}")
        return 0 if r.get("ok") else 1
    if cmd == "grade":
        if not config.cluster_enabled():
            raise SystemExit("practice mode (ACADEMY_CLUSTER=off): grading needs a cluster")
        v = labs.verify(lab)
        for r in v["results"]:
            print(f"  {MARK.get(r['status'], '?')} {r['title']}\n      {r['observed']}")
        print("verdict:", v["verdict"])
        return 0 if v["verdict"] == "verified" else 1
    if cmd == "finish":
        need_training()
        r = labs.cleanup(lab, wait_s=120)
        print("cleanup:", r.get("state"), r.get("reason", ""))
        return 0 if r.get("state") == "clean" else 1
    raise SystemExit(f"unknown command {cmd!r}; see --help")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
