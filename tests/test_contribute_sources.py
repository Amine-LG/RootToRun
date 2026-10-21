"""Every "Edit on GitHub" link opens the file that really defines what the page shows, and that file is in the public
repository.

The expected file of each item is found here by loading the content files with a YAML parser (not with the backend's
line scan that builds `source`), and the payloads checked are the ones the site receives (the API, which the static
export writes as data/*.json). A file is "in the public repository" when git tracks it and the private-export filter
keeps it; with RTR_PUBLIC_TREE=<dir> (a tree exported by scripts/public_tree.py) the file must also exist there."""
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from academy import config, curriculum, labs, main
from sources_oracle import model_files

EN = config.ROOT / "content" / "en"
FRONT = config.ROOT / "frontend" / "src"


def _tracked() -> set[str]:
    out = subprocess.run(["git", "ls-files"], cwd=config.ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return set(out.split("\n")) - {""}


def _public_filter():
    try:  # the export filter is a private tool: in the public repository every tracked file is public
        import sys
        sys.path.insert(0, str(config.ROOT / "scripts"))
        from public_tree import public
        return public
    except ImportError:
        return lambda path: True


TRACKED, PUBLIC = _tracked(), _public_filter()
TREE = Path(os.environ["RTR_PUBLIC_TREE"]) if os.environ.get("RTR_PUBLIC_TREE") else None


def assert_public(path: str, what: str):
    assert path and not path.startswith("/") and ".." not in path.split("/"), (what, path)
    assert (config.ROOT / path).is_file(), (what, path, "no such file")
    assert path in TRACKED, (what, path, "not tracked by git")
    assert PUBLIC(path), (what, path, "excluded from the public repository")
    if TREE:
        assert (TREE / path).is_file(), (what, path, f"not in the exported public tree {TREE}")


def _rel(f: Path) -> str:
    return f.relative_to(config.ROOT).as_posix()


def _defined(sub: str, many: bool, key: str = "id") -> dict[str, str]:
    """id -> the file that defines it, from the YAML itself."""
    out = {}
    for f in sorted((EN / sub).glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        for item in (data if many else [data]):
            assert item[key] not in out, (item[key], "defined twice")
            out[item[key]] = _rel(f)
    return out




def test_lessons_edit_their_own_file():
    want = _defined("lessons", many=True)
    assert set(want) == set(curriculum.load("en")["lessons"])
    for lid, path in want.items():
        assert main.get_lesson(lid)["source"] == path, lid
        assert_public(path, lid)


@pytest.mark.parametrize("sub,kind", [("labs", "lab"), ("incidents", "incident"), ("challenges", "challenge")])
def test_labs_incidents_and_challenges_edit_their_own_file(sub, kind):
    want = _defined(sub, many=False)
    assert want
    for lid, path in want.items():
        data = main.get_lab(lid)["lab"]
        assert data["kind"] == kind and data["source"] == path, (lid, data["source"])
        assert_public(path, lid)
    assert set(_defined("labs", False)) | set(_defined("incidents", False)) | set(_defined("challenges", False)) == set(labs.load("en"))


def test_runbooks_cases_and_diagnostics_edit_their_own_file():
    for sub, get, many, key in (("runbooks", main.get_runbook, True, "id"), ("cases", main.get_case, True, "id"),
                                ("diagnostics", main.get_diagnostic, False, "track")):
        want = _defined(sub, many, key)
        assert want, sub
        for ident, path in want.items():
            assert get(ident)["source"] == path, (sub, ident)
            assert_public(path, ident)


def test_concepts_paths_and_modules_edit_the_files_that_list_them():
    sources = main.get_curriculum()["sources"]
    assert sources == {"concepts": "content/en/concepts.yaml", "tracks": "content/en/tracks.yaml", "modules": "content/en/modules.yaml"}
    concepts = {c["id"] for c in yaml.safe_load((EN / "concepts.yaml").read_text(encoding="utf-8"))}
    tracks = {t["id"] for t in yaml.safe_load((EN / "tracks.yaml").read_text(encoding="utf-8"))}
    assert concepts == set(main.get_curriculum()["concepts"]) and tracks == {t["id"] for t in main.get_curriculum()["tracks"]}
    for path in sources.values():
        assert_public(path, path)


def test_models_and_diagrams_edit_their_code():
    """Every model's component file (from the import lines of sims/index.ts), the catalogue and the diagram data, as
    named in lib/contribute.ts."""
    files = model_files()
    contribute = (FRONT / "lib" / "contribute.ts").read_text(encoding="utf-8")
    table = dict(re.findall(r"(\w+): '(\w+\.tsx)'", contribute[contribute.index("MODEL_SOURCES"):contribute.index("const SIMS_DIR")]))
    assert len(files) >= 9 and table
    for model, path in files.items():
        assert f"frontend/src/sims/{table[model]}" == path, model
        assert_public(path, model)
    for const in ("MODEL_CATALOGUE", "DIAGRAMS_FILE"):
        path = re.search(rf"export const {const} = '([^']+)'", contribute).group(1)
        assert_public(path, const)
    assert re.search(r"export const DIAGRAMS_FILE = 'frontend/src/lib/diagrams.ts'", contribute)


def test_content_outside_the_repository_has_no_edit_link(tmp_path, monkeypatch):
    """Content served from another directory (ACADEMY_CONTENT_DIR) has no file in the repository: no source, never an
    invented path."""
    (tmp_path / "en" / "runbooks").mkdir(parents=True)
    (tmp_path / "en" / "runbooks" / "r.yaml").write_text("- id: rb.x\n  title: X\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONTENT_ROOT", tmp_path)
    main._SRC.clear()
    try:
        assert main.content_sources("en")["runbooks"] == {"rb.x": None}
    finally:
        main._SRC.clear()
