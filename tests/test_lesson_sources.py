"""Reproducible inputs come from the lesson, preserving bytes rather than reconstructing examples."""
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from academy import config, curriculum
from scripts.export_lesson_sources import export_files


def test_export_handles_nested_paths_and_preserves_literal_line_endings(tmp_path):
    files = {"Containerfile": "FROM scratch\n", "data/example.sh": "#!/bin/sh\r\necho café\r\n", ".config": "literal $HOME `text`"}
    out = tmp_path / "experiment"
    assert export_files(files, out) == list(files)
    assert {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()} == {
        name: body.encode("utf-8") for name, body in files.items()}


@pytest.mark.parametrize("bad", ["../outside", "/absolute", "a/../../outside", "a//b", "a/./b", "", "a\\b", "null\0byte"])
def test_invalid_path_refuses_the_entire_export_before_writing(tmp_path, bad):
    out = tmp_path / "experiment"
    with pytest.raises(ValueError, match="source path"):
        export_files({"valid.txt": "first", bad: "invalid"}, out)
    assert not out.exists()


def test_file_directory_collision_is_detected_before_writing(tmp_path):
    out = tmp_path / "experiment"
    with pytest.raises(ValueError, match="parent directory"):
        export_files({"a": "a file", "a/b": "cannot fit below it"}, out)
    assert not out.exists()


def test_export_never_overwrites_an_existing_working_directory(tmp_path):
    existing = tmp_path / "notes.txt"
    existing.write_text("my notes", encoding="utf-8")
    with pytest.raises(ValueError, match="empty directory"):
        export_files({"notes.txt": "replacement"}, tmp_path)
    assert existing.read_text(encoding="utf-8") == "my notes"
    link = tmp_path / "link"
    target = tmp_path / "empty"
    target.mkdir()
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        export_files({"notes.txt": "replacement"}, link)
    assert list(target.iterdir()) == []


def test_real_troubleshooting_recipe_exports_without_creating_a_container(tmp_path):
    lesson = curriculum.load("en")["lessons"]["ct.troubleshoot-containers"]
    out = tmp_path / "experiment"
    result = subprocess.run([sys.executable, str(config.ROOT / "scripts/export_lesson_sources.py"), lesson.id,
                             "--out", str(out)], capture_output=True, text=True, encoding="utf-8",
                            env={**os.environ, "ACADEMY_CLUSTER": "off"}, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no commands executed" in result.stdout
    assert {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()} == {
        name: body.encode("utf-8") for name, body in lesson.files.items()}
    # These files are produced during the image build, not missing host inputs to invent or download.
    assert "crlf.sh" not in lesson.files and "noexec.sh" not in lesson.files
    assert "cp start.sh noexec.sh" in lesson.files["Containerfile"]
    assert "crlf.sh" in lesson.files["Containerfile"]


def test_copyable_setup_in_the_companion_creates_exact_existing_recording_inputs(tmp_path):
    path = config.ROOT / "docs/learning/CONTAINER-TROUBLESHOOTING-SETUP.md"
    if not path.exists():
        pytest.skip("the companion guide is kept in the development repository only")
    guide = path.read_text(encoding="utf-8")
    block = re.search(r"<!-- setup:start -->\s*```sh\n(.*?)\n```\s*<!-- setup:end -->", guide, re.S)
    assert block, "the companion must retain its complete copyable setup"
    result = subprocess.run(["/bin/sh"], input=block[1], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=5)
    assert result.returncode == 0, result.stderr
    out = tmp_path / "rtr-container-debug"
    expected = curriculum.load("en")["lessons"]["ct.troubleshoot-containers"].files
    assert {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()} == {
        name: body.encode("utf-8") for name, body in expected.items()}
