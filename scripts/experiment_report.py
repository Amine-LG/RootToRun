"""Public summaries of the administration experiments, from the recorder's full experiment records.

Each administration lesson (record_on: cluster-admin) declares an experiment; every recording writes a full record
that is never committed ($ACADEMY_PRIVATE_DIR/experiments/<ID>/<time>.json, default data/recorder/, scrubbed of
passwords and tokens). This script writes, for the latest record of each experiment,
docs/admin-practice/experiments/<ID>.md with what every experiment record must state, and an index,
docs/admin-practice/experiments/README.md. Only someone who recorded the experiments has those records: contributors
do not need to run it.

Nothing private is copied: no cluster ID, no host details, and outputs only as short, already scrubbed excerpts.

    .venv/bin/python scripts/experiment_report.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from academy import config, curriculum  # noqa: E402

PRIVATE = config.RECORDER_DIR / "experiments"
OUT = ROOT / "docs" / "admin-practice" / "experiments"


def excerpt(text: str, n: int = 6) -> str:
    lines = (text or "").strip().splitlines()
    return "\n".join(lines[:n] + ([f"… ({len(lines) - n} more lines)"] if len(lines) > n else []))


def main() -> int:
    lessons = {l.experiment.id: l for l in curriculum.load()["lessons"].values() if l.experiment}
    # a page is only ever regenerated from a record: without the records, existing pages stay as they are
    missing = [xid for xid in lessons if not (PRIVATE / xid).exists() or not any((PRIVATE / xid).glob("*.json"))]
    published = {xid for xid in missing if (OUT / f"{xid}.md").exists()}
    if published and "--allow-missing" not in sys.argv:
        print(f"no experiment record in {PRIVATE} for {', '.join(sorted(published))}, which already have a page; nothing "
              "written. Point ACADEMY_PRIVATE_DIR at the records, or pass --allow-missing to mark them never run.",
              file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    index = ["# Administration experiments", "",
             "Every administration lesson that changes the training cluster does it as a named experiment, recorded with "
             "its rollback and the evidence that the cluster was returned to its starting state. The full records "
             "(scrubbed of passwords and tokens) are kept outside the repository; these pages are generated "
             "from them by `scripts/experiment_report.py`.", "",
             "| Experiment | Lesson | Last run | Restored |", "|---|---|---|---|"]
    for xid, lesson in sorted(lessons.items()):
        runs = sorted((PRIVATE / xid).glob("*.json")) if (PRIVATE / xid).exists() else []
        if not runs:
            index.append(f"| {xid} | `{lesson.id}` | never run | — |")
            continue
        rec = json.loads(runs[-1].read_text(encoding="utf-8"))
        rec_file = ROOT / "content" / "recordings" / f"lesson.{lesson.id}.json"
        public = json.loads(rec_file.read_text(encoding="utf-8")) if rec_file.exists() else {}
        fresh = public.get("lab_hash") == lesson.fingerprint()
        status = ("restored and verified" if rec.get("restored") else "NOT RESTORED") if rec.get("snapshot") else "stopped before any change"
        index.append(f"| [{xid}]({xid}.md) | `{lesson.id}` | {rec.get('started', '?')[:16].replace('T', ' ')} UTC | {status} |")
        exp = lesson.experiment
        entries = public.get("entries", []) if fresh else []
        lines = [
            f"# {xid}: {lesson.title}", "",
            f"- **Teaching objective:** {exp.objective}",
            f"- **Lesson:** `{lesson.id}` ({lesson.title}); recording {'matches' if fresh else 'does NOT match'} the current lesson.",
            f"- **Target cluster:** OpenShift Local, API `{rec.get('cluster', {}).get('api')}`, Kubernetes "
            f"{rec.get('cluster', {}).get('kubernetes')}, client {rec.get('cluster', {}).get('oc')}. The recorder refuses any cluster whose ID differs "
            "from the approved one (the ID is kept in the private record).",
            "- **Identities:** " + "; ".join(f"{k}: {v}" for k, v in rec.get("identities", {}).items()) +
            ". Rollback, snapshots and health checks run as the recovery identity, which does not depend on the OAuth server.",
            f"- **Run:** started {rec.get('started')}, finished {rec.get('finished')}. Private record: `{runs[-1].name}` (outside the repository).",
            f"- **Final status:** {status}.", "",
            "## Resources that may change", "", *[f"- {c}" for c in exp.changes], "",
            "## Checks before any change (preflight)", "",
            *([f"- `{p['cmd']}`: exit {p['code']} ({'as expected' if p['ok'] else 'NOT as expected'})" for p in rec.get("preflight", [])] or ["- none"]), "",
            "## Original state (saved views, compared after the rollback)", "",
            *[f"- `{s['cmd']}`: {'identical after the rollback' if s.get('same') else 'DIFFERENT after the rollback'}" for s in rec.get("snapshot", [])], "",
            "## Planned operations and actual results", "",
            "| # | Identity | Command | Expected | Actual |", "|---|---|---|---|---|",
        ]
        for k, p in enumerate(rec.get("planned", []), 1):
            e = entries[k - 1] if k - 1 < len(entries) and entries[k - 1].get("cmd") == p["cmd"] else None
            actual = f"exit {e['code']}{'' if e['ok'] else ' (unexpected)'}" if e else "not run"
            cmd = p["cmd"].replace("|", "\\|")
            lines.append(f"| {k} | {p['as']} | `{cmd[:160]}{'…' if len(cmd) > 160 else ''}` | {p['expect']} | {actual} |")
        lines += ["", "The outputs are in the lesson's recording (`content/recordings/lesson." + lesson.id + ".json`), shown in the lesson.", "",
                  "## Rollback procedure (run as the recovery identity, always)", "",
                  *([f"{k}. `{r['cmd']}`: exit {r['code']}" for k, r in enumerate(rec.get("rollback", []), 1)] or ["not run"]), "",
                  "## Post-rollback verification", "",
                  *[f"- wait `{s['cmd']}`: exit {s['code']}" for s in rec.get("settle", [])],
                  *[f"- `{v['cmd']}`: exit {v['code']} ({'pass' if v['ok'] else 'FAIL'})\n\n  ```\n  {excerpt(v.get('output', '')).replace(chr(10), chr(10) + '  ')}\n  ```" for v in rec.get("verify", [])], "",
                  "## Residual differences", "",
                  *([f"- {p}" for p in rec.get("problems", [])] or ["None found: every saved view was identical after the rollback and every check passed."]), ""]
        (OUT / f"{xid}.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    (OUT / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(lessons)} experiment pages to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
