"""scripts/site_manifest.py lists the files in an order that does not depend on the platform (Windows sorts paths
without case), so the manifests of the sites exported on Linux and on Windows can be compared line by line."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from site_manifest import manifest  # noqa: E402


def test_the_manifest_is_sorted_by_its_slash_separated_paths(tmp_path):
    for name in ("a.js", "B.js", "assets/x.css", "Z/y.txt"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(name.encode())
    assert [line.split("  ", 1)[1] for line in manifest(tmp_path)] == ["B.js", "Z/y.txt", "a.js", "assets/x.css"]
