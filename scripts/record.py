"""Record (and thereby test) labs and incidents against the connected cluster.

    .venv/bin/python scripts/record.py --all          # every lab and incident
    .venv/bin/python scripts/record.py lab.rbac inc.x  # selected ones
    .venv/bin/python scripts/record.py --lessons      # lessons' host commands (podman, skopeo) on this machine
    .venv/bin/python scripts/record.py --lessons --admin n.htpasswd-users
                                                      # administration lessons (record_on: cluster-admin): real
                                                      # administrator operations on the approved training cluster,
                                                      # each with its experiment's rollback and verification; needs
                                                      # ACADEMY_ADMIN_CLUSTER_ID
    --keep   leave the lab projects in place afterwards (for inspection)

Exit code 1 if any command did not behave as expected or a verification failed.
"""
import os
import sys
import time

sys.path.insert(0, "backend")
from academy import curriculum, kube, labs, recorder  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]


def cluster_lock():
    """One recording at a time on the training cluster: several people (or agents) may prepare lessons in parallel,
    but cluster changes are serialised by this lock, which is held until the process exits."""
    import fcntl

    from academy import config

    path = config.RECORDER_DIR / "cluster.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+", encoding="utf-8")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"waiting for another recording to finish (lock {path})", flush=True)
        fcntl.flock(f, fcntl.LOCK_EX)
    f.seek(0)
    f.truncate()
    f.write(f"pid {os.getpid()} {' '.join(sys.argv[1:])}\n")
    f.flush()
    return f

if "--lessons" in sys.argv:
    admin = "--admin" in sys.argv
    lessons = [l for l in curriculum.load()["lessons"].values() if l.commands and (not args or l.id in args)]
    # administration lessons change the cluster: recorded only when asked for by name, with --admin
    skipped = [l.id for l in lessons if (l.record_on == "cluster-admin") != admin or (admin and not args)]
    lessons = [l for l in lessons if l.id not in skipped]
    if skipped:
        print(f"skipped ({'not administration lessons, or not named' if admin else 'administration lessons: use --admin and name them'}): {len(skipped)}")
    if admin:
        import os

        os.environ["ACADEMY_ADMIN_RECORDING"] = "1"
    if any(l.record_on != "host" for l in lessons):
        _lock = cluster_lock()  # noqa: F841 (held until exit)
    bad = []
    for l in lessons:
        print(f"== lesson {l.id}", flush=True)
        r = recorder.record_lesson(l, log=lambda m: print(m, flush=True))
        print(f"   {'OK' if r['ok'] else 'FAILED'} in {r['seconds']}s")
        bad += [] if r["ok"] else [l.id]
        if admin and not r["ok"]:
            print("   stopping: an administration recording failed; check its experiment record before running another")
            break
    print(f"\n{len(lessons) - len(bad)}/{len(lessons)} lessons recorded ok" + (f"; failed: {bad}" if bad else ""))
    sys.exit(1 if bad else 0)
keep = "--keep" in sys.argv
_lock = cluster_lock()  # noqa: F841 (held until exit)
if not kube.whoami("learner").get("connected"):
    raise SystemExit("connect the learner identity first (the app's Connections page)")
all_labs = labs.load()
if labs.errors():
    raise SystemExit("content errors: " + "; ".join(labs.errors()))
ids = sorted(all_labs) if "--all" in sys.argv or not args else args
results = []
t0 = time.time()
for i in ids:
    lab = all_labs[i]
    if lab.elevated_setup and not kube.whoami("admin").get("connected"):
        print(f"== {i}: SKIPPED (needs the admin identity for elevated setup)")
        results.append({"lab": i, "ok": None})
        continue
    print(f"== {i}", flush=True)
    r = recorder.record(lab, keep=keep)
    results.append(r)
    print(f"   {'OK' if r['ok'] else 'FAILED'} in {r.get('seconds', '?')}s")
    for p in r.get("problems", []):
        print("   ! " + p)
bad = [r for r in results if r["ok"] is False]
print(f"\n{len(results) - len(bad)}/{len(results)} recorded ok in {time.time() - t0:.0f}s" + (f"; failed: {[r['lab'] for r in bad]}" if bad else ""))
sys.exit(1 if bad else 0)
