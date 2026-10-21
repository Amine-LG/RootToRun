"""A manifest of a built site: one line per file, `<sha256>  <path>` (sorted, `/` separators). CI writes it for the
site exported on Linux and the one exported on Windows, and requires them to be identical: the same source must give
the same site, byte for byte, on every platform.

    .venv/bin/python scripts/site_manifest.py frontend/dist site.txt

It writes the file itself (bytes, LF), as a shell redirection could re-encode it (PowerShell does).
"""
import hashlib
import sys
from pathlib import Path


def manifest(root: Path) -> list[str]:
    # sorted by the /-separated path: Path objects sort without case on Windows, and the manifests must compare
    files = sorted((f.relative_to(root).as_posix(), f) for f in root.rglob("*") if f.is_file())
    return [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {rel}" for rel, f in files]


if __name__ == "__main__":
    if len(sys.argv) != 3 or not Path(sys.argv[1]).is_dir():
        sys.exit(__doc__)
    lines = manifest(Path(sys.argv[1]))
    Path(sys.argv[2]).write_bytes(("\n".join(lines) + "\n").encode())
    print(f"{sys.argv[2]}: {len(lines)} files")
