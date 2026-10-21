"""Root to Run on http://127.0.0.1:8768 (local only), on Linux, macOS or Windows, in the foreground (Ctrl+C stops it).

    .venv/bin/python scripts/serve.py --practice          # Linux, macOS: no cluster at all, recorded outputs only
    .venv\\Scripts\\python.exe scripts\\serve.py --practice   # Windows (PowerShell)
    ... scripts/serve.py                                   # the same, and live labs if `oc` and a cluster are available
    ... scripts/serve.py --port 9000

It builds the frontend first when it is missing or older than its sources (`npm ci` once, then `npm run build`), as
run.sh does; run.sh and stop.sh run the same server in the background on Linux and macOS.
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
BUILT = FRONTEND / "dist" / "index.html"
# everything the build reads: sources, its configuration and its dependencies' versions
SOURCES = [FRONTEND / name for name in ("src", "public", "scripts", "index.html", "product.json", "package.json",
                                         "package-lock.json", "vite.config.ts", "tsconfig.json")]
LOCK, INSTALLED = FRONTEND / "package-lock.json", FRONTEND / "node_modules" / ".package-lock.json"


def stale() -> bool:
    """True when the build is missing or a frontend source is newer than it."""
    if not BUILT.exists():
        return True
    built = BUILT.stat().st_mtime
    for src in SOURCES:
        files = src.rglob("*") if src.is_dir() else [src]
        if any(f.is_file() and f.stat().st_mtime > built for f in files):
            return True
    return False


def build() -> None:
    npm = shutil.which("npm")  # npm.cmd on Windows: found through PATHEXT
    if not npm:
        sys.exit("npm not found: install Node.js 22.12 or newer, or build the frontend elsewhere")
    # npm writes node_modules/.package-lock.json on every install: older than the lock file means new dependencies
    if not INSTALLED.exists() or INSTALLED.stat().st_mtime < LOCK.stat().st_mtime:
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=FRONTEND, check=True)
    print("building the frontend", flush=True)
    subprocess.run([npm, "run", "-s", "build"], cwd=FRONTEND, check=True, stdout=subprocess.DEVNULL)


def port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--practice", action="store_true", help="no cluster access at all (ACADEMY_CLUSTER=off)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("ACADEMY_PORT", "8768")))
    ap.add_argument("--no-build", action="store_true", help="never build the frontend, even when it is missing")
    args = ap.parse_args()
    try:
        import uvicorn  # installed by requirements.txt
    except ImportError:
        sys.exit("run this with the project's environment: .venv/bin/python (Windows: .venv\\Scripts\\python.exe), "
                 "after `uv pip install -r requirements.txt` into it")
    if not args.no_build and stale():
        build()
    if not port_free(args.port):
        sys.exit(f"port {args.port} is busy (already running? another port: --port 9000)")
    if args.practice:
        os.environ["ACADEMY_CLUSTER"] = "off"  # read when the app is imported, below
    name = "Root to Run"
    try:
        name = json.loads((FRONTEND / "product.json").read_text(encoding="utf-8"))["name"]
    except (OSError, ValueError, KeyError):
        pass
    print(f"\n  {name}: http://127.0.0.1:{args.port}{'  (practice mode)' if args.practice else ''}\n  Ctrl+C stops it\n",
          flush=True)
    # in this process (no child server that could outlive it on Windows; ASCII output for any console), from the project directory as run.sh does
    os.chdir(ROOT)
    uvicorn.run("academy.main:app", app_dir=str(ROOT / "backend"), host="127.0.0.1", port=args.port,
                proxy_headers=False, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
